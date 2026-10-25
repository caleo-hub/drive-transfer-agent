import hashlib
import io
import platform
import zipfile

import httpx
import pytest

from drive_transfer_agent.rclone import Rclone
from drive_transfer_agent.safety import DomainError


@pytest.mark.parametrize("valid", [True, False])
async def test_installer_verifies_checksum_and_does_not_extract_other_paths(settings, monkeypatch, valid):
    system = "windows" if platform.system() == "Windows" else "linux"
    name = f"rclone-v1.2.3-{system}-amd64.zip"
    binary = "rclone.exe" if system == "windows" else "rclone"
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr(f"rclone-v1.2.3-{system}-amd64/{binary}", b"test executable")
        archive.writestr("../../escape.txt", b"must never be extracted")
    data = content.getvalue()
    checksum = hashlib.sha256(data).hexdigest() if valid else "0" * 64

    def handler(request):
        if request.url.path.endswith("version.txt"):
            return httpx.Response(200, text="rclone v1.2.3\n")
        if request.url.path.endswith("SHA256SUMS"):
            return httpx.Response(200, text=f"{checksum}  {name}\n")
        return httpx.Response(200, content=data)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    monkeypatch.setattr(platform, "machine", lambda: "AMD64")
    runner = Rclone(settings, None)
    if valid:
        result = await runner.install()
        assert result["checksum_verified"]
        assert (settings.data / "bin" / binary).read_bytes() == b"test executable"
    else:
        with pytest.raises(DomainError, match="Checksum"):
            await runner.install()
        assert not (settings.data / "bin" / binary).exists()
    assert not (settings.data.parent / "escape.txt").exists()
