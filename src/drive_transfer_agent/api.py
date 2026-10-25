import asyncio
import json
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .agent import Chat
from .config import Settings
from .connections import Connections
from .executor import Executor
from .models import (
    ConversationUpdate,
    DestinationInput,
    ItemInput,
    JobInput,
    MessageInput,
    Preferences,
    QueueAction,
    SetupInput,
)
from .queue import Queues
from .rclone import Rclone
from .safety import DomainError, local_path, redact, relative_path
from .store import FINAL, Store, uid
from .vault import Vault


def create_app(settings=None, *, vault=None, rclone=None, connections=None):
    settings = settings or Settings()
    settings.initialize()
    store = Store(settings.data / "jobs.sqlite3")
    vault = vault or Vault(settings)
    rclone = rclone or Rclone(settings, vault)
    connections = connections or Connections(settings, vault, rclone)
    executor = Executor(settings, store, rclone, connections)
    queues = Queues(store)
    chat = Chat(settings, store, vault, executor, connections, queues)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await executor.close()

    app = FastAPI(title="Drive Transfer Agent", version="0.1.0", lifespan=lifespan)
    app.state.executor, app.state.store = executor, store
    app.state.chat, app.state.connections, app.state.settings = chat, connections, settings
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_guard(request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and origin not in {
                f"http://127.0.0.1:{settings.dta_port}",
                f"http://localhost:{settings.dta_port}",
                "http://localhost:5173",
                "http://127.0.0.1:5173",
            }:
                return JSONResponse({"message": "Origem não autorizada."}, status_code=403)
            if request.headers.get("x-dta-request") != "1":
                return JSONResponse({"message": "Cabeçalho local obrigatório."}, status_code=403)
            try:
                if int(request.headers.get("content-length", "0")) > 1024 * 1024:
                    return JSONResponse({"message": "Pedido excede 1 MiB."}, status_code=413)
            except ValueError:
                return JSONResponse({"message": "Pedido inválido."}, status_code=400)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return JSONResponse(
            {"message": error.message, "details": redact(error.details)}, status_code=error.status
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        # Pydantic's default response echoes rejected inputs, including protected setup fields.
        return JSONResponse(
            {
                "message": "Campos inválidos. Confira os nomes, links e opções informados.",
                "fields": [".".join(str(part) for part in e["loc"]) for e in error.errors()],
            },
            status_code=422,
        )

    @app.get("/api/health")
    async def health():
        return {
            "ok": True,
            "rclone": await rclone.version(),
            "connections": connections.status(),
            "active_job_id": (store.active() or {}).get("id"),
            "platform": sys.platform,
        }

    @app.post("/api/setup/install")
    async def install():
        async with executor.maintenance:
            executor.idle()
            try:
                return await rclone.install()
            except DomainError:
                raise
            except Exception:
                raise DomainError(
                    "Não foi possível baixar e validar o rclone oficial. Confira a rede e tente novamente.",
                    503,
                ) from None

    @app.post("/api/setup")
    async def setup(value: SetupInput):
        async with executor.maintenance:
            executor.idle()
            if value.kind == "model":
                key = value.values.get("api_key", "").strip()
                if not key:
                    raise DomainError("Informe a chave no campo protegido.")
                vault.set("openai", key)
                return {"status": "saved", "provider": "model"}
            if value.kind == "google":
                return connections.begin_google(value.values)
            return await connections.connect_mega(value.values)

    @app.get("/api/setup/{flow_id}")
    async def setup_status(flow_id: str):
        return connections.flow(flow_id)

    @app.delete("/api/setup/{flow_id}")
    async def cancel_setup(flow_id: str):
        value = connections.flow(flow_id)
        if value["status"] == "pending":
            connections.flows[flow_id]["status"] = "cancelled"
        return connections.flow(flow_id)

    @app.get("/api/setup/oauth/callback", response_class=HTMLResponse)
    async def oauth_callback(state: str = "", code: str = "", error: str = ""):
        async with executor.maintenance:
            executor.idle()
            await connections.callback(state, code, error)
        return "<html lang='pt-BR'><title>Drive Transfer Agent</title><h1>Autorização processada</h1><p>Volte ao chat para conferir a conexão. Você pode fechar esta aba.</p></html>"

    @app.get("/api/connections")
    async def connection_status():
        return connections.status()

    @app.post("/api/connections/{provider}/test")
    async def test_connection(provider: str):
        async with executor.maintenance:
            executor.idle()
            return await connections.test(provider)

    @app.delete("/api/connections/{provider}")
    async def disconnect(provider: str):
        if provider not in {"google", "mega", "model"}:
            raise DomainError("Provedor inválido.")
        async with executor.maintenance:
            executor.idle()
            vault.set("openai" if provider == "model" else provider, None)
            if provider == "google":
                for flow in connections.flows.values():
                    if flow["status"] == "pending":
                        flow["status"] = "cancelled"
        return {
            "disconnected": True,
            "message": "Conexão removida deste aplicativo. Nenhum arquivo foi excluído.",
        }

    @app.get("/api/destinations")
    async def destinations():
        return store.list("destination")

    @app.post("/api/destinations")
    async def add_destination(value: DestinationInput):
        path = value.validated_path()
        duplicate = next(
            (d for d in store.list("destination") if d["name"].casefold() == value.name.casefold()), None
        )
        if duplicate:
            raise DomainError("Já existe um destino com esse nome.")
        body = {"id": uid(), **value.model_dump(), "path": path}
        return store.put("destination", body["id"], body)

    @app.post("/api/destinations/select-local")
    async def select_local():
        def choose():
            import tkinter
            from tkinter import filedialog

            root = tkinter.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            try:
                return filedialog.askdirectory(title="Escolha uma pasta para os downloads")
            finally:
                root.destroy()

        try:
            return {"path": await asyncio.to_thread(choose)}
        except Exception:
            raise DomainError(
                "Seletor visual indisponível neste ambiente. Informe o caminho completo da pasta."
            ) from None

    @app.get("/api/destinations/mega/folders")
    async def mega_folders(path: str = ""):
        async with executor.maintenance:
            executor.idle()
            path = relative_path(path) if path else ""
            entries = await rclone.json(
                ["lsjson", "mega:" + path, "--dirs-only", "--retries", "1"], timeout=90
            )
            return {
                "path": path,
                "folders": [
                    {"name": p["Name"], "path": "/".join(filter(None, [path, p["Name"]]))} for p in entries
                ],
            }

    @app.get("/api/destinations/{destination_id}/capacity")
    async def capacity(destination_id: str):
        dest = store.get("destination", destination_id)
        if not dest:
            raise DomainError("Destino não encontrado.", 404)
        async with executor.maintenance:
            executor.idle()
            return await executor.capacity(dest, 0)

    @app.post("/api/destinations/{destination_id}/open")
    async def open_destination(destination_id: str):
        dest = store.get("destination", destination_id)
        if not dest or dest["kind"] != "local":
            raise DomainError("Escolha uma pasta local cadastrada.")
        path = Path(local_path(dest["path"]))
        if not path.is_dir():
            raise DomainError("A pasta ainda não existe.")
        if os.name == "nt":
            os.startfile(str(path))
        else:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"opened": True}

    @app.get("/api/preferences")
    async def preferences():
        return store.get("preferences", "default", Preferences().model_dump())

    @app.put("/api/preferences")
    async def save_preferences(value: Preferences):
        if value.destination_id and not store.get("destination", value.destination_id):
            raise DomainError("Destino não encontrado.")
        return store.put("preferences", "default", value.model_dump())

    @app.post("/api/sources")
    async def source(value: ItemInput):
        return executor.register_source(value.drive_url)

    @app.get("/api/jobs")
    async def jobs():
        return [executor.public(j) for j in store.jobs()]

    @app.post("/api/jobs", status_code=202)
    async def start_job(value: JobInput, idempotency_key: str = Header(min_length=8, max_length=200)):
        job, created = await executor.start(value, idempotency_key)
        return {"job_id": job["id"], "status": job["status"], "created": created}

    @app.post("/api/preflight", status_code=202)
    async def preflight(value: JobInput, idempotency_key: str = Header(min_length=8, max_length=200)):
        value.mode = "inspect"
        job, _ = await executor.start(value, idempotency_key)
        return {"job_id": job["id"], "status": job["status"]}

    @app.get("/api/jobs/{job_id}")
    async def job_status(job_id: str):
        return executor.public(store.job(job_id))

    @app.post("/api/jobs/{job_id}/stop")
    async def stop_job(job_id: str):
        return await executor.stop(job_id)

    @app.get("/api/jobs/{job_id}/log")
    async def job_log(job_id: str):
        store.job(job_id)
        if not job_id.isalnum():
            raise DomainError("ID inválido.")
        path = settings.data / "logs" / f"{job_id}.log"
        if not path.exists():
            return PlainTextResponse("Nenhum log disponível.")

        def filtered():
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    yield redact(line)

        return StreamingResponse(
            filtered(),
            media_type="text/plain",
            headers={"Content-Disposition": f'attachment; filename="{job_id}.log"'},
        )

    @app.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str, request: Request):
        store.job(job_id)

        async def events():
            revision = -1
            ticks = 0
            while not await request.is_disconnected():
                job = executor.public(store.job(job_id))
                if revision != job["revision"]:
                    revision = job["revision"]
                    yield f"id: {revision}\nevent: snapshot\ndata: {json.dumps(job)}\n\n"
                if job["status"] in FINAL:
                    yield f"event: done\ndata: {json.dumps({'status': job['status']})}\n\n"
                    return
                ticks += 1
                if ticks % 20 == 0:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(
            events(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    @app.get("/api/conversations")
    async def conversations(archived: bool = False):
        return [c for c in store.list("conversation") if c.get("archived", False) == archived]

    @app.post("/api/conversations")
    async def new_conversation():
        return chat.create()

    @app.patch("/api/conversations/{conversation_id}")
    async def update_conversation(conversation_id: str, value: ConversationUpdate):
        return await chat.archive(conversation_id, value.archived)

    @app.delete("/api/conversations/{conversation_id}")
    async def delete_conversation(conversation_id: str):
        return await chat.delete(conversation_id)

    @app.get("/api/conversations/{conversation_id}/messages")
    async def messages(conversation_id: str):
        chat.conversation(conversation_id)
        return store.messages(conversation_id)

    @app.post("/api/conversations/{conversation_id}/messages")
    async def send_message(conversation_id: str, value: MessageInput):
        return await chat.send(conversation_id, value.text, value.request_id)

    @app.get("/api/conversations/{conversation_id}/queue")
    async def queue(conversation_id: str):
        chat.conversation(conversation_id)
        return redact(queues.get(conversation_id))

    @app.post("/api/conversations/{conversation_id}/queue")
    async def change_queue(conversation_id: str, value: QueueAction):
        chat.conversation(conversation_id, editable=True)
        for item in value.items:
            if item.drive_url:
                item.source_ref = executor.register_source(item.drive_url)["source_ref"]
                item.drive_url = ""
        return queues.change(conversation_id, value)

    @app.post("/api/conversations/{conversation_id}/queue/import")
    async def import_queue(conversation_id: str, value: dict):
        chat.conversation(conversation_id, editable=True)
        text = value.get("text", "")
        if not isinstance(text, str) or len(text) > 100000:
            raise DomainError("Lote inválido.")
        # Validate the full batch before applying any queue mutation.
        items = []
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            name, url = line.split("|", 1) if "|" in line else (None, line)
            try:
                item = ItemInput(drive_url=url.strip(), folder_label=name.strip() if name else None)
                item.source_ref = executor.register_source(item.drive_url)["source_ref"]
                item.drive_url = ""
                items.append(item)
            except (DomainError, ValueError):
                raise DomainError(
                    f"Linha {number}: nome ou link inválido. A fila não foi alterada."
                ) from None
        if not items:
            raise DomainError("Nenhum link encontrado.")
        return queues.change(conversation_id, QueueAction(action="add", items=items))

    static = Path(__file__).parent / "static"
    if static.is_dir():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    async def index():
        if (static / "index.html").exists():
            return FileResponse(static / "index.html")
        return HTMLResponse(
            "<h1>Drive Transfer Agent</h1><p>Compile a interface conforme o README ou use o servidor Vite em desenvolvimento.</p>"
        )

    return app
