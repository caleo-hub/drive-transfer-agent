import asyncio
import hashlib
import json
import tempfile
from pathlib import Path

from .models import JobInput, Preferences
from .rclone import free_space, terminate_tree, volume_id
from .safety import DomainError, explain_error, label, parse_drive_url, public_url, redact, relative_path
from .store import FINAL

EXPORTS = {
    "application/vnd.google-apps.document": ".docx",
    "application/vnd.google-apps.spreadsheet": ".xlsx",
    "application/vnd.google-apps.presentation": ".pptx",
}


class Executor:
    def __init__(self, settings, store, rclone, connections):
        self.settings, self.store, self.rclone, self.connections = settings, store, rclone, connections
        self.maintenance = asyncio.Lock()
        self.tasks = {}
        self.store.reconcile()

    def idle(self):
        active = self.store.active()
        if active:
            raise DomainError(
                "Aguarde ou cancele a tarefa ativa antes de alterar a configuração.",
                409,
                {"job_id": active["id"]},
            )

    def register_source(self, drive_url):
        parsed = parse_drive_url(drive_url)
        key = hashlib.sha256(drive_url.encode()).hexdigest()[:32]
        self.store.put("source", key, {**parsed, "url": drive_url})
        return {"source_ref": key, "url": public_url(drive_url)}

    def normalize(self, spec: JobInput):
        data = spec.model_dump()
        names = [i["folder_label"].casefold() for i in data["items"] if i.get("folder_label")]
        if len(names) != len(set(names)):
            raise DomainError("Dois itens têm o mesmo nome de destino.")
        source_ids = set()
        for item in data["items"]:
            if item["drive_url"]:
                item["source_ref"] = self.register_source(item["drive_url"])["source_ref"]
            if not item["source_ref"] or not self.store.get("source", item["source_ref"]):
                raise DomainError("Origem desconhecida. Envie o link do Drive novamente.")
            source_id = self.store.get("source", item["source_ref"])["id"]
            if spec.mode == "inspect" and source_id in source_ids:
                raise DomainError("A mesma origem aparece mais de uma vez na consulta.")
            source_ids.add(source_id)
            item["drive_url"] = ""
        if spec.mode != "inspect" and not self.store.get("destination", spec.destination_id):
            raise DomainError("Escolha um destino cadastrado.")
        return data

    async def start(self, spec: JobInput, idem: str):
        if self.maintenance.locked():
            raise DomainError("Uma configuração está em andamento. Aguarde sua conclusão.", 409)
        for flow_id in getattr(self.connections, "flows", {}):
            if self.connections.flow(flow_id)["status"] in {"pending", "exchanging"}:
                raise DomainError("Conclua ou cancele a autorização Google antes de iniciar uma tarefa.", 409)
        data = self.normalize(spec)
        job, created = self.store.create_job(idem, data)
        if created:
            task = asyncio.create_task(self.work(job["id"]))
            self.tasks[job["id"]] = task
            task.add_done_callback(lambda _: self.tasks.pop(job["id"], None))
        return self.public(self.store.job(job["id"])), created

    @staticmethod
    def public(job):
        return redact(job)

    async def cancelled(self, key):
        return self.store.job(key)["cancel_requested"]

    async def stop(self, key):
        job = self.store.job(key)
        if job["status"] not in FINAL:
            if job["status"] == "pending":
                items = [
                    {"source_ref": i["source_ref"], "status": "cancelled", "stage": "done"}
                    for i in job["spec"]["items"]
                ]
                self.store.update_job(
                    key,
                    status="cancelled",
                    stage="done",
                    cancel_requested=True,
                    items=items,
                    message="Cancelada antes de iniciar.",
                )
                task = self.tasks.get(key)
                if task:
                    task.cancel()
                conversation = job["spec"].get("conversation_id")
                if conversation:
                    self.store.add_message(
                        conversation,
                        "job:" + key,
                        "system",
                        "Cancelada antes de iniciar.",
                        job_id=key,
                        status="cancelled",
                    )
                return self.public(self.store.job(key))
            self.store.update_job(key, cancel_requested=True, message="Cancelamento solicitado.")
            process = self.rclone.processes.get(key)
            if process:
                await terminate_tree(process)
            task = self.tasks.get(key)
            if task:
                task.cancel()
        return self.public(self.store.job(key))

    async def close(self):
        for key in list(self.tasks):
            await self.stop(key)
        if self.tasks:
            await asyncio.gather(*list(self.tasks.values()), return_exceptions=True)

    async def command(self, key, args, timeout=86400):
        if self.store.job(key).get("space_exhausted"):
            raise DomainError("Reserva de espaço atingida. Escolha outro destino antes de tentar novamente.")

        async def line(text):
            with (self.settings.data / "logs" / f"{key}.log").open("a", encoding="utf-8") as log:
                log.write(text + "\n")
            try:
                entry = json.loads(text)
                stats = entry.get("stats")
                if stats:
                    self.store.update_job(
                        key,
                        stats={
                            k: stats[k]
                            for k in (
                                "bytes",
                                "totalBytes",
                                "speed",
                                "eta",
                                "transfers",
                                "checks",
                                "errors",
                                "transferring",
                            )
                            if k in stats
                        },
                    )
            except ValueError:
                pass

        return await self.rclone.run(
            [
                *args,
                "--use-json-log",
                "--stats",
                "1s",
                "--stats-log-level",
                "NOTICE",
                "--retries",
                "3",
                "--low-level-retries",
                "5",
                "--retries-sleep",
                "5s",
            ],
            job_id=key,
            on_line=line,
            cancel=lambda: self.cancelled(key),
            timeout=timeout,
        )

    def flags(self, source, spec):
        flags = ["--drive-root-folder-id", source["id"]]
        if source.get("resource_key"):
            flags += ["--drive-resource-key", source["resource_key"]]
        if spec["export_gdocs"]:
            flags += ["--drive-export-formats", "docx,xlsx,pptx"]
        else:
            flags += ["--drive-skip-gdocs"]
        return flags

    async def inspect(self, key, item, spec):
        source = self.store.get("source", item["source_ref"])
        metadata = await self.connections.metadata(source["id"], source["resource_key"])
        if await self.cancelled(key):
            raise asyncio.CancelledError
        mime = metadata.get("mimeType", "")
        folder = mime == "application/vnd.google-apps.folder"
        if mime == "application/vnd.google-apps.shortcut":
            raise DomainError("Envie o link do arquivo ou pasta original em vez de um atalho.")
        if not folder and metadata.get("capabilities", {}).get("canDownload") is False:
            raise DomainError("O proprietário não permite baixar este arquivo.")
        name = item.get("folder_label") or metadata.get("name") or f"DriveFolder_{source['id']}"
        name = label(name)
        if not folder and mime.startswith("application/vnd.google-apps."):
            if not spec["export_gdocs"]:
                return {
                    "name": name,
                    "kind": "file",
                    "count": 0,
                    "bytes": 0,
                    "unknown_size": False,
                    "source_ref": item["source_ref"],
                    "metadata": metadata,
                }
            if mime not in EXPORTS:
                raise DomainError("Este documento Google não possui formato de exportação suportado no MVP.")
            if not name.lower().endswith(EXPORTS[mime]):
                name += EXPORTS[mime]
        files = []
        if folder:
            code, out, err = await self.command(
                key,
                ["lsjson", "gdrive:", "--recursive", "--files-only", "--hash", *self.flags(source, spec)],
                timeout=120,
            )
            if code:
                raise DomainError(explain_error(err))
            try:
                files = json.loads(out)
            except ValueError:
                raise DomainError("Inventário incompleto. A transferência não foi iniciada.") from None
            for file in files:
                relative_path(file["Path"])
            count = len(files)
            size = sum(max(f.get("Size", -1), 0) for f in files)
            unknown = any(f.get("Size", -1) < 0 for f in files)
        else:
            count = 1
            size = int(metadata.get("size", 0))
            unknown = "size" not in metadata
        return {
            "name": name,
            "kind": "folder" if folder else "file",
            "count": count,
            "bytes": size,
            "unknown_size": unknown,
            "source_ref": item["source_ref"],
            "metadata": metadata,
            "coverage": "hash_or_size" if folder else "hash" if metadata.get("md5Checksum") else "size",
            "files": files,
        }

    def destination(self, spec, name):
        dest = self.store.get("destination", spec["destination_id"])
        if not dest:
            raise DomainError("Destino não encontrado.")
        target = (
            str(Path(dest["path"]) / name)
            if dest["kind"] == "local"
            else "mega:" + "/".join(p for p in [dest["path"], name] if p)
        )
        return dest, target

    async def capacity(self, dest, required, unknown=False, temp_required=0):
        preferences = Preferences(**self.store.get("preferences", "default", {}))
        reserve = preferences.reserve_bytes
        temporary_path = str(self.settings.data / "tmp")
        temporary_free = free_space(temporary_path)
        local_free = free_space(dest["path"]) if dest["kind"] == "local" else temporary_free
        remote_free = None
        if dest["kind"] == "mega":
            quota = await self.rclone.json(["about", "mega:", "--json", "--retries", "1"], timeout=90)
            remote_free = quota.get("free")
        same_volume = dest["kind"] == "local" and volume_id(dest["path"]) == volume_id(temporary_path)
        local_need = (required if dest["kind"] == "local" else 0) + reserve
        if same_volume or dest["kind"] == "mega":
            local_need += temp_required
        insufficient = (
            (local_free is not None and local_free < local_need)
            or (remote_free is not None and remote_free < required)
            or (not same_volume and temporary_free is not None and temporary_free < temp_required + reserve)
        )
        return {
            "status": "insufficient"
            if insufficient
            else "estimated"
            if unknown
            else "unknown"
            if local_free is None or dest["kind"] == "mega" and remote_free is None
            else "sufficient",
            "required_bytes": required,
            "temporary_bytes": temp_required,
            "reserve_bytes": reserve,
            "local_free_bytes": local_free,
            "temporary_free_bytes": temporary_free,
            "remote_free_bytes": remote_free,
        }

    async def monitor_space(self, key, dest, completed):
        while not completed.is_set():
            available = [free_space(str(self.settings.data / "tmp"))]
            if dest["kind"] == "local":
                available.append(free_space(dest["path"]))
            reserve = Preferences(**self.store.get("preferences", "default", {})).reserve_bytes
            if any(space is not None and space < reserve for space in available):
                self.store.update_job(
                    key,
                    space_exhausted=True,
                    message="Reserva de espaço atingida. A operação será interrompida.",
                )
                process = self.rclone.processes.get(key)
                if process:
                    await terminate_tree(process)
                return
            try:
                await asyncio.wait_for(completed.wait(), timeout=1)
            except TimeoutError:
                pass

    async def audit_folder(self, key, source, target, spec, inspection):
        with tempfile.TemporaryDirectory(dir=self.settings.data / "tmp") as temp:
            report = Path(temp) / "combined.txt"
            args = [
                "check",
                "gdrive:",
                target,
                "--one-way",
                "--combined",
                str(report),
                *self.flags(source, spec),
            ]
            if target.startswith("mega:"):
                args += ["--size-only"]
            code, _, _ = await self.command(key, args)
            lines = report.read_text(encoding="utf-8").splitlines() if report.exists() else []
            repair = []
            for line in lines:
                if len(line) > 2 and line[0] in {"+", "*"}:
                    repair.append(relative_path(line[2:]))
            equal = sum(line.startswith("= ") for line in lines)
            errors = any(line.startswith("! ") for line in lines)
            success = code == 0 and not repair and not errors and equal > 0
            hashes = all(bool(f.get("Hashes")) for f in inspection["files"])
            coverage = "size" if target.startswith("mega:") else "hash" if hashes else "hash_or_size"
            return {
                "ok": success,
                "repair": repair,
                "equal": equal,
                "coverage": coverage,
                "errors": errors,
                "returncode": code,
            }

    async def folder_transfer(self, key, inspection, target, spec, update):
        source = self.store.get("source", inspection["source_ref"])
        flags = self.flags(source, spec)
        if spec["mode"] == "download":
            update(stage="copy")
            args = ["copy", "gdrive:", target, *flags]
            if spec["create_empty"]:
                args += ["--create-empty-src-dirs"]
            code, _, err = await self.command(key, args)
            if code:
                raise DomainError(explain_error(err))
        update(stage="check")
        audit = await self.audit_folder(key, source, target, spec, inspection)
        for attempt in range(3):
            if audit["ok"] or not audit["repair"] or not spec["auto_repair"] or spec["mode"] == "verify":
                break
            update(stage="repair", repair_round=attempt + 1)
            with tempfile.TemporaryDirectory(dir=self.settings.data / "tmp") as temp:
                paths = Path(temp) / "paths.txt"
                paths.write_text("\n".join(audit["repair"]) + "\n", encoding="utf-8")
                code, _, err = await self.command(
                    key, ["copy", "gdrive:", target, *flags, "--files-from-raw", str(paths), "--ignore-times"]
                )
                if code:
                    raise DomainError(explain_error(err))
            update(stage="check")
            audit = await self.audit_folder(key, source, target, spec, inspection)
        return audit

    async def file_transfer(self, key, inspection, target, spec, update):
        source = self.store.get("source", inspection["source_ref"])
        # Staging makes file-only shared links independent of access to their parent folder.
        with tempfile.TemporaryDirectory(dir=self.settings.data / "tmp") as temp:
            staged = Path(temp) / inspection["name"]
            update(stage="copy" if spec["mode"] == "download" else "check")
            args = [
                "backend",
                "copyid",
                "gdrive:",
                source["id"],
                str(staged),
                "--drive-export-formats",
                "docx,xlsx,pptx",
            ]
            if source.get("resource_key"):
                args += ["--drive-resource-key", source["resource_key"]]
            code, _, err = await self.command(key, args)
            if code or not staged.is_file():
                raise DomainError(explain_error(err))
            if spec["mode"] == "download":
                dest, _ = self.destination(spec, inspection["name"])
                capacity = await self.capacity(dest, staged.stat().st_size)
                if capacity["status"] == "insufficient":
                    raise DomainError("O arquivo preparado não cabe no destino. Escolha outro destino.")
                code, _, err = await self.command(key, ["copyto", str(staged), target])
                if code:
                    raise DomainError(explain_error(err))
            update(stage="check")
            for attempt in range(4):
                if target.startswith("mega:"):
                    stat = await self.rclone.json(
                        ["lsjson", target, "--stat"], job_id=key, cancel=lambda: self.cancelled(key)
                    )
                    ok, coverage = stat["Size"] == staged.stat().st_size, "size"
                else:

                    def digest(path):
                        with Path(path).open("rb") as stream:
                            return hashlib.file_digest(stream, "sha256").hexdigest()

                    ok = Path(target).is_file() and await asyncio.to_thread(
                        digest, staged
                    ) == await asyncio.to_thread(digest, target)
                    coverage = "hash"
                if ok or attempt == 3 or spec["mode"] == "verify" or not spec["auto_repair"]:
                    return {"ok": ok, "coverage": coverage, "equal": int(ok), "repair": []}
                update(stage="repair", repair_round=attempt + 1)
                code, _, err = await self.command(key, ["copyto", str(staged), target, "--ignore-times"])
                if code:
                    raise DomainError(explain_error(err))
                update(stage="check")

    async def work(self, key):
        job = self.store.update_job(key, status="running", stage="inspect", message="Consultando a origem.")
        spec = job["spec"]
        results, prepared, targets = [], [], set()

        def publish(index, **changes):
            clear_stats = changes.get("stage", results[index]["stage"]) != results[index]["stage"]
            results[index].update(changes)
            self.store.update_job(
                key,
                current=index,
                stage=results[index]["stage"],
                items=results,
                **({"stats": {}} if clear_stats else {}),
            )

        try:
            # Inspect the entire queue before any copy: capacity and target collisions must
            # be known before the first item can change the destination.
            for index, item in enumerate(spec["items"]):
                if await self.cancelled(key):
                    raise asyncio.CancelledError
                current = {
                    "source_ref": item["source_ref"],
                    "status": "running",
                    "stage": "inspect",
                    "integrity": "unknown",
                }
                results.append(current)
                publish(index)
                try:
                    inspection = await self.inspect(key, item, spec)
                    current.update({k: v for k, v in inspection.items() if k not in {"files", "metadata"}})
                    if inspection["count"] == 0:
                        publish(
                            index,
                            status="empty",
                            stage="done",
                            message="Nenhum arquivo visível. Não houve cópia.",
                        )
                        continue
                    dest, target = None, None
                    if spec.get("destination_id"):
                        dest, target = self.destination(spec, inspection["name"])
                        if target.casefold() in targets:
                            for previous_index, _, _, previous_target in list(prepared):
                                if previous_target and previous_target.casefold() == target.casefold():
                                    publish(
                                        previous_index,
                                        status="failed",
                                        stage="done",
                                        message="Nome de destino repetido. Defina nomes distintos.",
                                    )
                                    prepared = [p for p in prepared if p[0] != previous_index]
                            raise DomainError(
                                "Dois itens resultaram no mesmo destino. Defina nomes distintos."
                            )
                        targets.add(target.casefold())
                        current["destination"] = target
                        if spec["mode"] == "verify" and dest["kind"] == "local" and not Path(target).exists():
                            raise DomainError("O destino a verificar ainda não existe.")
                    prepared.append((index, inspection, dest, target))
                    publish(index, status="pending")
                except (DomainError, OSError, TimeoutError) as error:
                    publish(
                        index,
                        status="failed",
                        stage="done",
                        message=str(error)
                        if isinstance(error, DomainError)
                        else "Não foi possível consultar a origem ou o destino.",
                    )

            if prepared and prepared[0][2]:
                total = sum(inspection["bytes"] for _, inspection, _, _ in prepared)
                temporary = max((i["bytes"] for _, i, _, _ in prepared if i["kind"] == "file"), default=0)
                unknown = any(i["unknown_size"] for _, i, _, _ in prepared)
                capacity = await self.capacity(
                    prepared[0][2], total if spec["mode"] != "verify" else 0, unknown, temporary
                )
                self.store.update_job(key, capacity=capacity)
                if capacity["status"] == "insufficient" and spec["mode"] != "inspect":
                    for index, _, _, _ in prepared:
                        publish(
                            index,
                            status="attention",
                            stage="done",
                            capacity=capacity,
                            message="A fila não cabe no destino. Escolha outro destino e tente novamente.",
                        )
                    prepared = []

            for index, inspection, dest, target in prepared:
                if await self.cancelled(key):
                    raise asyncio.CancelledError

                def update(**changes):
                    publish(index, **changes)

                if spec["mode"] == "inspect":
                    update(
                        status="success",
                        stage="done",
                        capacity=self.store.job(key).get("capacity"),
                        message="Consulta concluída; nenhum arquivo foi copiado.",
                    )
                    continue
                update(status="running")
                try:
                    staged_bytes = inspection["bytes"] if inspection["kind"] == "file" else 0
                    capacity = await self.capacity(
                        dest,
                        inspection["bytes"] if spec["mode"] == "download" else 0,
                        inspection["unknown_size"],
                        staged_bytes,
                    )
                    update(capacity=capacity)
                    if capacity["status"] == "insufficient":
                        update(
                            status="attention",
                            stage="done",
                            message="Espaço insuficiente. Escolha outro destino.",
                        )
                        continue
                    source_id = self.store.get("source", inspection["source_ref"])["id"]
                    self.store.claim(target, source_id)
                    if dest["kind"] == "local" and spec["mode"] == "download":
                        parent = Path(target) if inspection["kind"] == "folder" else Path(target).parent
                        parent.mkdir(parents=True, exist_ok=True)
                        with tempfile.NamedTemporaryFile(dir=parent, prefix=".dta-write-test-"):
                            pass
                    done = asyncio.Event()
                    monitor = asyncio.create_task(self.monitor_space(key, dest, done))
                    try:
                        transfer = (
                            self.folder_transfer if inspection["kind"] == "folder" else self.file_transfer
                        )
                        audit = await transfer(key, inspection, target, spec, update)
                        if self.store.job(key).get("space_exhausted"):
                            raise DomainError(
                                "Reserva de espaço atingida. Arquivos concluídos foram preservados."
                            )
                        update(
                            status="success" if audit["ok"] else "failed",
                            stage="done",
                            audit=audit,
                            integrity="ok" if audit["ok"] else "fail",
                        )
                    finally:
                        done.set()
                        await monitor
                except (DomainError, OSError, TimeoutError) as error:
                    update(
                        status="failed",
                        stage="done",
                        message=str(error)
                        if isinstance(error, DomainError)
                        else "Falha de acesso ao disco ou tempo limite. Consulte o diagnóstico.",
                    )
            statuses = {i["status"] for i in results}
            state = (
                "failed"
                if "failed" in statuses
                else "attention"
                if statuses & {"empty", "attention"}
                else "success"
            )
            self.store.update_job(
                key,
                status=state,
                stage="done",
                items=results,
                stats={},
                message="Consulta concluída."
                if spec["mode"] == "inspect"
                else "Tarefa concluída. Consulte o resultado e o alcance da auditoria por item.",
            )
        except asyncio.CancelledError:
            for item in results:
                if item["status"] in {"running", "pending"}:
                    item.update(status="cancelled", stage="done")
            for item in spec["items"][len(results) :]:
                results.append({"source_ref": item["source_ref"], "status": "cancelled", "stage": "done"})
            self.store.update_job(
                key,
                status="cancelled",
                stage="done",
                items=results,
                stats={},
                message="Cancelada. Arquivos concluídos foram preservados.",
            )
        except (DomainError, OSError, TimeoutError) as error:
            for item in results:
                if item["status"] in {"running", "pending"}:
                    item.update(status="failed", stage="done")
            self.store.update_job(
                key,
                status="failed",
                stage="done",
                items=results,
                stats={},
                message=str(error)
                if isinstance(error, DomainError)
                else "Falha no disco ou tempo limite. Revise o destino e tente novamente.",
            )
        except Exception:
            for item in results:
                if item["status"] in {"running", "pending"}:
                    item.update(status="failed", stage="done")
            self.store.update_job(
                key,
                status="failed",
                stage="done",
                items=results,
                stats={},
                message="Falha inesperada no executor. Revise a configuração e tente novamente.",
            )
        finally:
            final = self.store.job(key)
            conversation = spec.get("conversation_id")
            if conversation:
                self.store.add_message(
                    conversation, "job:" + key, "system", final["message"], job_id=key, status=final["status"]
                )
