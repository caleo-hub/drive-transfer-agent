import time

import httpx
import pytest

from drive_transfer_agent.connections import Connections
from drive_transfer_agent.safety import DomainError
from drive_transfer_agent.vault import Vault


class RcloneStub:
    async def run(self, args, **kwargs):
        return 0, "obscured", ""


def test_encrypted_vault(settings):
    from cryptography.fernet import Fernet

    settings.dta_master_key = Fernet.generate_key().decode()
    vault = Vault(settings)
    vault.set("google", {"refresh_token": "sensitive-value"})
    assert b"sensitive-value" not in vault.path.read_bytes()
    assert vault.get("google")["refresh_token"] == "sensitive-value"
    vault.set("google", None)
    assert not vault.get("google")


def test_oauth_flow_expiry_and_cancellation(settings, vault):
    service = Connections(settings, vault, RcloneStub())
    first = service.begin_google({"client_id": "test.apps.googleusercontent.com"})
    second = service.begin_google({"client_id": "test.apps.googleusercontent.com"})
    assert service.flow(first["id"])["status"] == "cancelled"
    assert "code_challenge=" in second["authorization_url"]
    assert "verifier" not in second
    service.flows[second["id"]]["expires_at"] = time.time() - 1
    assert service.flow(second["id"])["status"] == "expired"


async def test_oauth_refusal_invalid_state_and_success(settings, vault, monkeypatch):
    service = Connections(settings, vault, RcloneStub())
    with pytest.raises(DomainError):
        await service.callback("invalid", "code", "")
    first = service.begin_google({"client_id": "test"})
    await service.callback(service.flows[first["id"]]["state"], "", "access_denied")
    assert service.flow(first["id"])["status"] == "refused"
    second = service.begin_google({"client_id": "test"})

    async def post(self, *args, **kwargs):
        return httpx.Response(
            200, json={"access_token": "private", "refresh_token": "private-refresh", "expires_in": 3600}
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    await service.callback(service.flows[second["id"]]["state"], "private-code", "")
    assert service.flow(second["id"])["status"] == "success"
    assert service.status()["google"]
    assert "private" not in str(service.flow(second["id"]))


async def test_mega_failure_preserves_previous_connection(settings, vault):
    class Broken(RcloneStub):
        async def run(self, args, **kwargs):
            return (0, "obscured", "") if args[0] == "obscure" else (1, "", "password=secret 401")

    vault.set("mega", {"email": "old@example.test", "obscured": "old"})
    service = Connections(settings, vault, Broken())
    with pytest.raises(DomainError) as error:
        await service.connect_mega({"email": "new@example.test", "password": "secret"})
    assert "secret" not in str(error.value)
    assert vault.get("mega")["email"] == "old@example.test"
