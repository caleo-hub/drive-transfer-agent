import pytest
from pydantic import ValidationError

from drive_transfer_agent.models import JobInput
from drive_transfer_agent.safety import DomainError, label, local_path, parse_drive_url, redact, relative_path


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://drive.google.com/drive/folders/abc_1?resourcekey=key_2", "abc_1"),
        ("https://drive.google.com/drive/u/0/folders/ABC-2", "ABC-2"),
        ("https://drive.google.com/file/d/file_1/view", "file_1"),
        ("https://drive.google.com/open?id=abc", "abc"),
        ("https://www.drive.google.com/?id=abc", "abc"),
    ],
)
def test_sources(url, expected):
    assert parse_drive_url(url)["id"] == expected


@pytest.mark.parametrize(
    "url",
    [
        "abc",
        "https://evil.test/drive/folders/a",
        "file:///abc",
        "https://drive.google.com.evil.test/folders/a",
        "https://drive.google.com/folders/../a",
        "https://drive.google.com/folders/a?resourcekey=../x",
        "https://x:secret@drive.google.com/folders/a",
    ],
)
def test_invalid_sources(url):
    with pytest.raises(DomainError):
        parse_drive_url(url)


@pytest.mark.parametrize(
    "value", ["..", "a/b", "a\\b", "CON", "con.txt", "COM1", "LPT9.pdf", "x:", "a\n", "x."]
)
def test_invalid_names(value):
    with pytest.raises(DomainError):
        label(value)


@pytest.mark.parametrize("value", ["../x", "/root", "D:/x", "a\\b", "a/../../b", "a\nb", "-flag"])
def test_repair_cannot_escape(value):
    with pytest.raises(DomainError):
        relative_path(value)


def test_windows_paths():
    assert local_path(r"D:\Backup", windows=True) == r"D:\Backup"
    assert local_path(r"\\server\share\Backup", windows=True) == r"\\server\share\Backup"
    for value in [r"D:relative", r"\relative", r"\\?\C:\path"]:
        with pytest.raises(DomainError):
            local_path(value, windows=True)


def test_strict_options():
    with pytest.raises(ValidationError):
        JobInput(items=[{"drive_url": "https://drive.google.com/folders/a"}], auto_repair="false")


def test_redaction():
    secret = "AIza" + "a" * 35
    result = redact(
        {
            "access_token": "sensitive",
            "url": "https://drive.google.com/folders/a?resourcekey=private",
            "message": f"api_key={secret}",
        }
    )
    assert "sensitive" not in str(result)
    assert "private" not in str(result)
    assert secret not in str(result)
