import asyncio

import httpx
import pytest
from google.adk.sessions import DatabaseSessionService

from drive_transfer_agent.api import create_app
from drive_transfer_agent.models import ItemInput, QueueAction


class RcloneStub:
    processes = {}

    async def version(self):
        return {"installed": False, "version": None}


@pytest.fixture
def app(settings, vault):
    return create_app(settings, vault=vault, rclone=RcloneStub())


async def test_archive_restore_and_legacy_conversations(app):
    store = app.state.store
    store.put("conversation", "legacy", {"id": "legacy", "title": "Anterior à atualização"})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver", headers={"x-dta-request": "1"}
    ) as client:
        conversation = (await client.post("/api/conversations")).json()
        key = conversation["id"]
        store.add_message(key, "before-archive", "user", "Preserve o histórico")
        queue = app.state.chat.queues.change(
            key, QueueAction(action="add", items=[ItemInput(source_ref="existing")])
        )
        response = await client.patch(f"/api/conversations/{key}", json={"archived": True})
        assert response.json()["archived"] is True
        assert [c["id"] for c in (await client.get("/api/conversations")).json()] == ["legacy"]
        assert [c["id"] for c in (await client.get("/api/conversations?archived=true")).json()] == [key]
        assert len((await client.get(f"/api/conversations/{key}/messages")).json()) == 1
        assert (await client.get(f"/api/conversations/{key}/queue")).json() == queue
        assert (
            await client.post(
                f"/api/conversations/{key}/messages", json={"text": "Oi", "request_id": "archived-request"}
            )
        ).status_code == 409
        assert (
            await client.post(f"/api/conversations/{key}/queue", json={"action": "clear"})
        ).status_code == 409
        assert (
            await client.post(
                f"/api/conversations/{key}/queue/import", json={"text": "https://drive.google.com/folders/a"}
            )
        ).status_code == 409
        assert (await client.patch(f"/api/conversations/{key}", json={"archived": False})).status_code == 200
        assert len((await client.get("/api/conversations")).json()) == 2
        assert (
            await client.post(
                f"/api/conversations/{key}/messages", json={"text": "Oi", "request_id": "restored-request"}
            )
        ).status_code == 200


async def test_delete_removes_messages_queue_and_adk_session_after_restart(app, settings):
    chat, store = app.state.chat, app.state.store
    key = chat.create()["id"]
    other = chat.create()["id"]
    store.add_message(key, "delete-request", "user", "Mensagem para apagar")
    store.add_message(other, "keep-request", "user", "Mensagem para preservar")
    store.put("queue", key, {"items": [{"source_ref": "x"}], "removed": None})
    store.put("destination", "keep-destination", {"id": "keep-destination"})
    job, _ = store.create_job("completed-job", {"conversation_id": key})
    store.update_job(job["id"], status="success")
    service = DatabaseSessionService(db_url=f"sqlite+aiosqlite:///{settings.data / 'sessions.sqlite3'}")
    await service.create_session(app_name="drive_transfer_agent", user_id="local", session_id=key)
    await service.create_session(app_name="drive_transfer_agent", user_id="local", session_id=other)
    assert chat.session_service is None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver", headers={"x-dta-request": "1"}
    ) as client:
        assert (await client.delete(f"/api/conversations/{key}")).json() == {"deleted": True}
        for suffix in ("messages", "queue"):
            assert (await client.get(f"/api/conversations/{key}/{suffix}")).status_code == 404
        assert (await client.patch(f"/api/conversations/{key}", json={"archived": True})).status_code == 404
        assert (await client.delete(f"/api/conversations/{key}")).status_code == 404
    assert store.messages(key) == []
    assert store.get("queue", key) is None
    assert store.reply(key, "delete-request") is None
    assert len(store.messages(other)) == 1
    assert store.job(job["id"])["status"] == "success"
    assert store.get("destination", "keep-destination")
    assert await service.get_session(app_name="drive_transfer_agent", user_id="local", session_id=key) is None
    assert await service.get_session(app_name="drive_transfer_agent", user_id="local", session_id=other)


async def test_delete_waits_for_chat_and_protects_active_transfer(app):
    chat, store = app.state.chat, app.state.store
    key = chat.create()["id"]
    job, _ = store.create_job("active-job", {"conversation_id": key})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver", headers={"x-dta-request": "1"}
    ) as client:
        assert (await client.delete(f"/api/conversations/{key}")).status_code == 409
        assert store.get("conversation", key)
        # Archiving does not stop or alter the transfer.
        assert (await client.patch(f"/api/conversations/{key}", json={"archived": True})).status_code == 200
        assert store.active()["id"] == job["id"]
        store.update_job(job["id"], status="success")
        lock = chat.locks[key]
        async with lock:
            deletion = asyncio.create_task(client.delete(f"/api/conversations/{key}"))
            await asyncio.sleep(0)
            assert not deletion.done()
        assert (await deletion).status_code == 200


async def test_conversation_mutations_require_local_guard_and_boolean(app):
    key = app.state.chat.create()["id"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        assert (await client.delete(f"/api/conversations/{key}")).status_code == 403
        assert (await client.patch(f"/api/conversations/{key}", json={"archived": True})).status_code == 403
        assert (
            await client.patch(
                f"/api/conversations/{key}", headers={"x-dta-request": "1"}, json={"archived": "true"}
            )
        ).status_code == 422
