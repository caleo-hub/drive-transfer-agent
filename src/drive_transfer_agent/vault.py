import json
import os
import threading

import keyring
from cryptography.fernet import Fernet

from .safety import DomainError


class Vault:
    """Encrypted application config. The encryption key lives in the OS credential store."""

    def __init__(self, settings):
        self.settings = settings
        self.path = settings.data / "secrets.enc"
        self.lock = threading.RLock()

    def cipher(self):
        key = self.settings.dta_master_key or os.environ.get("DTA_MASTER_KEY")
        if not key:
            try:
                key = keyring.get_password("DriveTransferAgent", "vault")
                if not key:
                    key = Fernet.generate_key().decode()
                    keyring.set_password("DriveTransferAgent", "vault", key)
            except Exception:
                raise DomainError(
                    "Armazenamento seguro indisponível. No Windows, use o Gerenciador de Credenciais; "
                    "em desenvolvimento sem interface, configure DTA_MASTER_KEY.",
                    503,
                ) from None
        return Fernet(key.encode())

    def read(self):
        with self.lock:
            if not self.path.exists():
                return {}
            try:
                return json.loads(self.cipher().decrypt(self.path.read_bytes()))
            except DomainError:
                raise
            except Exception:
                raise DomainError("Não foi possível abrir as credenciais protegidas.", 503) from None

    def get(self, key, default=None):
        return self.read().get(key, default)

    def set(self, key, value):
        with self.lock:
            cipher = self.cipher()
            data = self.read()
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
            temp = self.path.with_suffix(".tmp")
            temp.write_bytes(cipher.encrypt(json.dumps(data).encode()))
            if os.name != "nt":
                temp.chmod(0o600)
            temp.replace(self.path)
