import ntpath
import os
import re
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit


class DomainError(Exception):
    def __init__(self, message: str, status: int = 400, details=None):
        self.message, self.status, self.details = message, status, details
        super().__init__(message)


def parse_drive_url(value: str) -> dict:
    url = urlsplit(value.strip())
    if url.scheme not in {"https", "http"} or url.hostname not in {
        "drive.google.com",
        "www.drive.google.com",
    }:
        raise DomainError("Use um link de arquivo ou pasta do Google Drive.")
    if url.username or url.password or url.port not in {None, 80, 443}:
        raise DomainError("Link do Drive inválido.")
    query = parse_qs(url.query)
    folder = re.fullmatch(r"/(?:drive/(?:u/\d+/)?)?folders/([\w-]+)/?", url.path, re.ASCII)
    file = re.fullmatch(r"/file/d/([\w-]+)(?:/(?:view|edit|preview))?/?", url.path, re.ASCII)
    object_id = folder[1] if folder else file[1] if file else query.get("id", [""])[0]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", object_id) or not (
        folder or file or url.path in {"/", "/open", "/uc"}
    ):
        raise DomainError("O link não contém um ID válido do Drive.")
    key = query.get("resourcekey", [""])[0]
    if key and not re.fullmatch(r"[A-Za-z0-9_-]+", key):
        raise DomainError("Chave de recurso inválida.")
    return {
        "id": object_id,
        "resource_key": key,
        "kind_hint": "folder" if folder else "file" if file else None,
    }


def label(value: str) -> str:
    if re.search(r"[\x00-\x1f]", value):
        raise DomainError("O nome contém caracteres de controle.")
    value = value.strip()
    if not value or value in {".", ".."} or len(value) > 180:
        raise DomainError("Informe um nome de até 180 caracteres.")
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', value) or value.endswith((".", " ")):
        raise DomainError("O nome contém caracteres não permitidos no Windows.")
    if re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", value, re.I):
        raise DomainError("Esse nome é reservado pelo Windows.")
    return value


def relative_path(value: str) -> str:
    if not value or "\\" in value or "\n" in value or "\r" in value or "\x00" in value:
        raise DomainError("Caminho relativo inválido.")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or ":" in value or value.startswith("-"):
        raise DomainError("O caminho deve permanecer dentro da pasta da tarefa.")
    return str(path)


def local_path(value: str, *, windows: bool | None = None) -> str:
    value = value.strip().strip('"')
    if "\x00" in value or "\n" in value or "\r" in value:
        raise DomainError("Destino inválido.")
    windows = os.name == "nt" if windows is None else windows
    if windows:
        drive, tail = ntpath.splitdrive(value)
        if not drive or not tail.startswith(("\\", "/")) or value.startswith(("\\\\?", "\\\\.")):
            raise DomainError("Escolha um caminho Windows absoluto ou UNC.")
        return ntpath.normpath(value)
    if not Path(value).is_absolute():
        raise DomainError("Escolha um caminho absoluto.")
    return str(Path(value).resolve())


SECRET_PATTERN = re.compile(
    r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}|AIza[\w-]{20,}|ya29\.[\w.-]+|1//[\w.-]{20,}|"
    r"(?:password|senha|access_token|refresh_token|api_key|client_secret)\s*[=:]\s*[^\s,;]+",
    re.I,
)


def redact(value):
    if isinstance(value, dict):
        return {
            k: (
                "[protegido]"
                if re.search(r"token|password|secret|resource_key|api_key|authorization", k, re.I)
                else redact(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    if not isinstance(value, str):
        return value
    value = SECRET_PATTERN.sub("[protegido]", value)
    return re.sub(r"([?&]resourcekey=)[^&\s]+", r"\1[protegido]", value, flags=re.I)


def public_url(value: str) -> str:
    parsed = urlsplit(value)
    query = parse_qs(parsed.query)
    query.pop("resourcekey", None)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query, doseq=True), ""))


def explain_error(message: str) -> str:
    text = message.lower()
    for patterns, advice in [
        (
            ("quota", "dailylimit"),
            "Cota do provedor atingida. Aguarde a liberação antes de tentar novamente.",
        ),
        (("ratelimit", "429"), "O provedor limitou as solicitações. Aguarde antes de tentar novamente."),
        (
            ("invalid_grant", "401", "token expired"),
            "A conexão expirou. Reconecte a conta pelo cartão de contas.",
        ),
        (
            ("cannotdownload", "download_restricted"),
            "O proprietário restringiu o download. Solicite liberação.",
        ),
        (
            ("403", "forbidden", "permission denied"),
            "Confira a conta, o compartilhamento e a permissão no destino.",
        ),
        (("404", "not found"), "A origem não foi encontrada ou não está visível para a conta conectada."),
        (("no space", "disk full"), "Espaço insuficiente. Escolha outro destino ou libere espaço."),
        (("timeout", "connection", "network"), "Falha de rede. Confira a conexão e tente novamente."),
    ]:
        if any(p in text for p in patterns):
            return advice
    return "A operação falhou. Consulte os detalhes filtrados no relatório da tarefa."
