import asyncio
import hashlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import httpx
import psutil

from .safety import DomainError, explain_error, redact


async def terminate_tree(process):
    if process.returncode is not None:
        return
    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for child in reversed(children):
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        parent.terminate()
        _, alive = await asyncio.to_thread(psutil.wait_procs, [*children, parent], timeout=2)
        for child in alive:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
    except psutil.NoSuchProcess:
        pass
    await process.wait()


class Rclone:
    def __init__(self, settings, vault):
        self.settings, self.vault = settings, vault
        self.credentials = None
        # An explicit empty config is rclone's portable in-memory mode. Windows reserves
        # NUL as a filename in recent releases, so do not use os.devnull here.
        self.config = ""
        self.processes = {}

    def binary(self):
        managed = self.settings.data / "bin" / ("rclone.exe" if os.name == "nt" else "rclone")
        binary = self.settings.rclone_bin or (str(managed) if managed.exists() else shutil.which("rclone"))
        if not binary:
            raise DomainError("Instale o rclone pelo cartão de configuração.", 503)
        return binary

    async def environment(self, providers):
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RCLONE_")}
        env.update(RCLONE_CONFIG_GDRIVE_TYPE="drive", RCLONE_CONFIG_MEGA_TYPE="mega")
        if self.credentials and providers:
            env.update(await self.credentials(providers))
        return env

    async def run(
        self,
        args,
        *,
        job_id=None,
        on_line=None,
        timeout=600,
        env_extra=None,
        cancel=None,
        input_text=None,
        secure=False,
    ):
        providers = {name for name in ("gdrive", "mega") if any(arg.startswith(name + ":") for arg in args)}
        env = await self.environment(providers)
        env.update(env_extra or {})
        command = [
            self.binary(),
            *args,
            "--config",
            str(self.config),
            "--ask-password=false",
            "--contimeout",
            "10s",
            "--timeout",
            "60s",
        ]
        options = (
            {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
        )
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if input_text is not None else asyncio.subprocess.DEVNULL,
            env=env,
            **options,
        )
        key = job_id or str(process.pid)
        self.processes[key] = process
        out, err = bytearray(), bytearray()

        async def read(stream, result):
            while chunk := await stream.readline():
                if len(result) + len(chunk) > 32 * 1024 * 1024:
                    raise DomainError("A saída excedeu o limite de inventário. Use pastas menores.")
                result.extend(chunk)
                if on_line and not secure:
                    await on_line(redact(chunk.decode("utf-8", errors="replace").strip()))

        async def monitor():
            while process.returncode is None:
                if cancel and await cancel():
                    await terminate_tree(process)
                    raise asyncio.CancelledError
                await asyncio.sleep(0.25)

        async def execute():
            if input_text is not None:
                process.stdin.write(input_text.encode())
                await process.stdin.drain()
                process.stdin.close()
            async with asyncio.TaskGroup() as group:
                group.create_task(read(process.stdout, out))
                group.create_task(read(process.stderr, err))
                group.create_task(monitor())
                group.create_task(process.wait())

        try:
            await asyncio.wait_for(execute(), timeout=timeout)
            if cancel and await cancel():
                raise asyncio.CancelledError
            return (
                process.returncode,
                out.decode("utf-8", errors="replace"),
                err.decode("utf-8", errors="replace"),
            )
        except BaseException:
            await terminate_tree(process)
            raise
        finally:
            self.processes.pop(key, None)

    async def json(self, args, **kwargs):
        code, out, err = await self.run(args, **kwargs)
        if code:
            raise DomainError(explain_error(err))
        try:
            return json.loads(out)
        except ValueError:
            raise DomainError("O rclone não retornou um resultado completo.") from None

    async def version(self):
        try:
            code, out, _ = await self.run(["version"], timeout=10)
            return {"installed": code == 0, "version": out.splitlines()[0] if out else "desconhecida"}
        except DomainError:
            return {"installed": False, "version": None}

    async def install(self):
        system = {"Windows": "windows", "Linux": "linux"}.get(platform.system())
        arch = {"AMD64": "amd64", "x86_64": "amd64", "aarch64": "arm64", "ARM64": "arm64"}.get(
            platform.machine()
        )
        if not system or not arch:
            raise DomainError("Instalação automática disponível para Windows/Linux x64 ou ARM64.")
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.get("https://downloads.rclone.org/version.txt")
            response.raise_for_status()
            version = response.text.strip().removeprefix("rclone ")
            if not re.fullmatch(r"v\d+\.\d+\.\d+", version):
                raise DomainError("Versão oficial não reconhecida.")
            name = f"rclone-{version}-{system}-{arch}.zip"
            base = f"https://downloads.rclone.org/{version}"
            sums = await client.get(f"{base}/SHA256SUMS")
            sums.raise_for_status()
            match = re.search(rf"^([a-fA-F0-9]{{64}})\s+\*?{re.escape(name)}$", sums.text, re.M)
            if not match:
                raise DomainError("Checksum oficial indisponível.")
            archive = bytearray()
            async with client.stream("GET", f"{base}/{name}") as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    archive.extend(chunk)
                    if len(archive) > 150 * 1024**2:
                        raise DomainError("Pacote oficial excedeu o limite esperado.")
        if hashlib.sha256(archive).hexdigest() != match[1].lower():
            raise DomainError("Checksum inválido. Instalação cancelada.")
        binary_name = "rclone.exe" if system == "windows" else "rclone"
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            member = f"rclone-{version}-{system}-{arch}/{binary_name}"
            info = zipped.getinfo(member)
            if info.file_size > 250 * 1024**2:
                raise DomainError("Executável oficial excedeu o limite esperado.")
            data = zipped.read(member)
        target = self.settings.data / "bin" / binary_name
        temporary = target.with_suffix(".download")
        temporary.write_bytes(data)
        temporary.chmod(0o700)
        temporary.replace(target)
        return {"installed": True, "version": version, "checksum_verified": True}


def free_space(path: str):
    target = Path(path)
    while not target.exists() and target.parent != target:
        target = target.parent
    try:
        return shutil.disk_usage(target).free
    except OSError:
        return None


def volume_id(path: str):
    target = Path(path)
    while not target.exists() and target.parent != target:
        target = target.parent
    try:
        return target.stat().st_dev
    except OSError:
        return None
