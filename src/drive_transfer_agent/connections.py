import asyncio
import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode

import httpx

from .safety import DomainError, explain_error
from .store import uid


class Connections:
    def __init__(self, settings, vault, rclone):
        self.settings, self.vault, self.rclone = settings, vault, rclone
        self.flows = {}
        self.token_lock = asyncio.Lock()
        self.rclone.credentials = self.environment

    def status(self):
        try:
            data = self.vault.read()
            return {
                "google": bool(data.get("google")),
                "mega": bool(data.get("mega")),
                "model": bool(self.settings.google_api_key or data.get("model")),
                "vault_available": True,
            }
        except DomainError:
            return {
                "google": False,
                "mega": False,
                "model": bool(self.settings.google_api_key),
                "vault_available": False,
            }

    async def google_token(self):
        async with self.token_lock:
            token = self.vault.get("google")
            if not token:
                raise DomainError("Conecte o Google Drive pelo cartão de contas.")
            if token.get("expires_at", 0) < time.time() + 120:
                async with httpx.AsyncClient(timeout=20) as client:
                    result = await client.post(
                        "https://oauth2.googleapis.com/token",
                        data={
                            "client_id": token["client_id"],
                            "client_secret": token.get("client_secret", ""),
                            "refresh_token": token["refresh_token"],
                            "grant_type": "refresh_token",
                        },
                    )
                if result.status_code != 200:
                    raise DomainError("A conexão Google expirou. Reconecte a conta.")
                token.update(result.json())
                token["expires_at"] = time.time() + token.get("expires_in", 3600)
                self.vault.set("google", token)
            return token

    async def environment(self, providers):
        env = {}
        data = self.vault.read()
        if "gdrive" in providers and data.get("google"):
            token = await self.google_token()
            rtoken = {k: token[k] for k in ("access_token", "refresh_token", "token_type") if k in token}
            # Fresh token supplied for each child; the application persists refreshes centrally.
            from datetime import datetime, timezone

            rtoken["expiry"] = datetime.fromtimestamp(token["expires_at"], timezone.utc).isoformat()
            env.update(
                {
                    "RCLONE_CONFIG_GDRIVE_TOKEN": json.dumps(rtoken),
                    "RCLONE_CONFIG_GDRIVE_CLIENT_ID": token["client_id"],
                    "RCLONE_CONFIG_GDRIVE_CLIENT_SECRET": token.get("client_secret", ""),
                    "RCLONE_CONFIG_GDRIVE_SCOPE": "drive.readonly",
                }
            )
        mega = data.get("mega") if "mega" in providers else None
        if mega:
            env.update(
                {
                    "RCLONE_CONFIG_MEGA_USER": mega["email"],
                    "RCLONE_CONFIG_MEGA_PASS": mega["obscured"],
                    "RCLONE_CONFIG_MEGA_USE_HTTPS": "true",
                }
            )
            if mega.get("otp") and mega.get("otp_expires", 0) > time.time():
                env["RCLONE_CONFIG_MEGA_2FA"] = mega["otp"]
        return env

    def begin_google(self, values):
        client_id = values.get("client_id") or self.settings.google_client_id
        client_secret = values.get("client_secret") or self.settings.google_client_secret
        if not client_id:
            raise DomainError("Configure o ID OAuth Google do projeto no cartão de conexão.")
        for flow in self.flows.values():
            if flow["status"] == "pending":
                flow["status"] = "cancelled"
        flow_id, state, verifier = uid(), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        redirect = f"http://127.0.0.1:{self.settings.dta_port}/api/setup/oauth/callback"
        flow = {
            "id": flow_id,
            "status": "pending",
            "state": state,
            "verifier": verifier,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect,
            "expires_at": time.time() + 600,
        }
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        query = {
            "client_id": client_id,
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": "https://www.googleapis.com/auth/drive.readonly",
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        flow["authorization_url"] = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(query)
        self.flows[flow_id] = flow
        return self.flow(flow_id)

    def flow(self, flow_id):
        flow = self.flows.get(flow_id)
        if not flow:
            raise DomainError("Sessão de configuração não encontrada.", 404)
        if flow["status"] == "pending" and time.time() > flow["expires_at"]:
            flow["status"] = "expired"
        return {k: flow[k] for k in ("id", "status", "authorization_url", "expires_at") if k in flow}

    async def callback(self, state, code, error):
        flow = next((f for f in self.flows.values() if secrets.compare_digest(f["state"], state)), None)
        if not flow or self.flow(flow["id"])["status"] != "pending":
            raise DomainError("A autorização expirou ou foi cancelada. Inicie novamente.")
        if error or not code:
            flow["status"] = "refused"
            return
        flow["status"] = "exchanging"
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                result = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "code": code,
                        "client_id": flow["client_id"],
                        "client_secret": flow["client_secret"],
                        "redirect_uri": flow["redirect_uri"],
                        "grant_type": "authorization_code",
                        "code_verifier": flow["verifier"],
                    },
                )
            if result.status_code != 200:
                raise DomainError(
                    "O Google não concluiu a autorização. Confira o cliente OAuth e tente novamente."
                )
            token = result.json()
            if "refresh_token" not in token:
                raise DomainError("O Google não forneceu acesso persistente. Reconecte autorizando o acesso.")
            token.update(
                client_id=flow["client_id"],
                client_secret=flow["client_secret"],
                expires_at=time.time() + token.get("expires_in", 3600),
            )
            self.vault.set("google", token)
            flow["status"] = "success"
        except BaseException:
            flow["status"] = "failed"
            raise

    async def connect_mega(self, values):
        email, password = values.get("email", "").strip(), values.get("password", "")
        if not email or not password:
            raise DomainError("Informe o e-mail e a senha no formulário protegido.")
        code, obscured, _ = await self.rclone.run(["obscure", "-"], input_text=password + "\n", secure=True)
        if code:
            raise DomainError("Não foi possível preparar a conexão MEGA.")
        otp = values.get("otp", "").strip()
        candidate = {
            "email": email,
            "obscured": obscured.strip(),
            "otp": otp,
            "otp_expires": time.time() + 60,
        }
        env = {"RCLONE_CONFIG_MEGA_USER": email, "RCLONE_CONFIG_MEGA_PASS": candidate["obscured"]}
        if otp:
            env["RCLONE_CONFIG_MEGA_2FA"] = otp
        # Test before replacing the saved account. No raw command output leaves this method.
        code, _, err = await self.rclone.run(
            ["about", "mega:", "--json", "--retries", "1"], env_extra=env, secure=True, timeout=90
        )
        if code:
            raise DomainError(
                "Não foi possível conectar ao MEGA. Confira os dados, o código temporário "
                "e se a conta já foi acessada pelo navegador. " + explain_error(err)
            )
        self.vault.set("mega", candidate)
        return {"status": "success", "provider": "mega"}

    async def metadata(self, object_id, resource_key=""):
        token = await self.google_token()
        headers = {"Authorization": f"Bearer {token['access_token']}"}
        if resource_key:
            headers["X-Goog-Drive-Resource-Keys"] = f"{object_id}/{resource_key}"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"https://www.googleapis.com/drive/v3/files/{object_id}",
                headers=headers,
                params={
                    "supportsAllDrives": "true",
                    "fields": "id,name,mimeType,size,parents,md5Checksum,capabilities(canDownload)",
                },
            )
        if response.status_code != 200:
            raise DomainError(explain_error(str(response.status_code)))
        return response.json()

    async def test(self, provider):
        if provider == "google":
            token = await self.google_token()
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(
                    "https://www.googleapis.com/drive/v3/about",
                    params={"fields": "user(displayName,emailAddress),storageQuota"},
                    headers={"Authorization": f"Bearer {token['access_token']}"},
                )
            if response.status_code != 200:
                raise DomainError(explain_error(str(response.status_code)))
            return {"connected": True, **response.json()}
        if provider == "mega":
            if not self.vault.get("mega"):
                raise DomainError("Conecte sua conta MEGA.")
            return {
                "connected": True,
                "capacity": await self.rclone.json(["about", "mega:", "--json"], timeout=90),
            }
        raise DomainError("Provedor inválido.")
