import httpx
import pytest

from drive_transfer_agent.api import create_app


class RcloneStub:
    processes = {}

    async def version(self):
        return {"installed": False, "version": None}


@pytest.fixture
def app(settings, vault):
    return create_app(settings, vault=vault, rclone=RcloneStub())


async def test_local_guard_and_non_echoing_validation(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        assert (await client.post("/api/conversations")).status_code == 403
        assert (
            await client.post(
                "/api/conversations", headers={"x-dta-request": "1", "origin": "https://evil.test"}
            )
        ).status_code == 403
        response = await client.post(
            "/api/setup",
            headers={"x-dta-request": "1"},
            json={"kind": "invalid", "values": {"api_key": "private-value"}},
        )
        assert response.status_code == 422
        assert "private-value" not in response.text


async def test_setup_without_model_and_secret_paste_not_saved(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver", headers={"x-dta-request": "1"}
    ) as client:
        conversation = (await client.post("/api/conversations")).json()["id"]
        response = await client.post(
            f"/api/conversations/{conversation}/messages", json={"text": "Oi", "request_id": "request-0001"}
        )
        assert response.status_code == 200
        assert response.json()["actions"][0]["provider"] == "model"
        secret = "AIza" + "x" * 35
        await client.post(
            f"/api/conversations/{conversation}/messages", json={"text": secret, "request_id": "request-0002"}
        )
        messages = (await client.get(f"/api/conversations/{conversation}/messages")).text
        assert secret not in messages


async def test_queue_import_redacts_resource_keys_and_is_atomic(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver", headers={"x-dta-request": "1"}
    ) as client:
        conversation = (await client.post("/api/conversations")).json()["id"]
        endpoint = f"/api/conversations/{conversation}/queue/import"
        response = await client.post(
            endpoint, json={"text": "A | https://drive.google.com/folders/a?resourcekey=private"}
        )
        assert response.status_code == 200
        assert "private" not in response.text
        response = await client.post(endpoint, json={"text": "https://drive.google.com/folders/b\ninvalid"})
        assert response.status_code == 400
        queue = (await client.get(f"/api/conversations/{conversation}/queue")).json()
        assert len(queue["items"]) == 1


async def test_preferences_destination_validation(app, settings):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver", headers={"x-dta-request": "1"}
    ) as client:
        response = await client.post(
            "/api/destinations",
            json={"name": "Downloads", "kind": "local", "path": str(settings.data / "downloads")},
        )
        destination = response.json()
        assert response.status_code == 200
        response = await client.put("/api/preferences", json={"destination_id": destination["id"]})
        assert response.status_code == 200
        assert (await client.put("/api/preferences", json={"destination_id": "missing"})).status_code == 400
