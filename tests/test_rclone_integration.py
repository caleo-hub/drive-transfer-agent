import asyncio
import os
import shutil
import sys
from pathlib import Path

import pytest

from drive_transfer_agent.executor import Executor
from drive_transfer_agent.models import ItemInput, JobInput
from drive_transfer_agent.rclone import Rclone
from drive_transfer_agent.store import FINAL


@pytest.fixture
def installed_rclone():
    candidate = (
        Path(__file__).parents[1]
        / ".state"
        / "runtime"
        / "bin"
        / ("rclone.exe" if os.name == "nt" else "rclone")
    )
    binary = os.environ.get("DTA_TEST_RCLONE") or (
        str(candidate) if candidate.exists() else shutil.which("rclone")
    )
    if not binary:
        pytest.skip("Install rclone with scripts/install-test-rclone.py to run local integration")
    return binary


async def wait(executor, key):
    for _ in range(1000):
        result = executor.store.job(key)
        if result["status"] in FINAL:
            return result
        await asyncio.sleep(0.02)
    raise AssertionError("Real rclone job did not finish")


@pytest.mark.integration
async def test_real_folder_copy_repair_verify_and_extra_files(settings, store, vault, installed_rclone):
    settings.rclone_bin = installed_rclone
    source, dest = settings.data / "source", settings.data / "destination"
    (source / "nested").mkdir(parents=True)
    (source / "nested" / "a.txt").write_text("source content")
    (source / "b.txt").write_text("more content")
    (dest / "Course").mkdir(parents=True)
    (dest / "Course" / "extra.txt").write_text("preserve me")
    store.put("preferences", "default", {"reserve_bytes": 0})
    store.put("destination", "d", {"id": "d", "name": "Test", "kind": "local", "path": str(dest)})

    class LocalMetadata:
        async def metadata(self, *args):
            return {"id": "course", "name": "Course", "mimeType": "application/vnd.google-apps.folder"}

    executor = Executor(settings, store, Rclone(settings, vault), LocalMetadata())
    real_command = executor.command
    commands = []

    async def local_command(key, args, timeout=86400):
        commands.append(args)
        result = await real_command(
            key, [str(source) if value == "gdrive:" else value for value in args], timeout
        )
        if args[0] == "copy" and "--files-from-raw" not in args:
            path = dest / "Course" / "nested" / "a.txt"
            path.write_text("broken content")
        return result

    executor.command = local_command
    spec = JobInput(
        items=[ItemInput(drive_url="https://drive.google.com/folders/course")], destination_id="d"
    )
    job, _ = await executor.start(spec, "real-copy-and-repair")
    result = await wait(executor, job["id"])
    assert result["status"] == "success", result
    assert (dest / "Course" / "nested" / "a.txt").read_text() == "source content"
    assert (dest / "Course" / "extra.txt").read_text() == "preserve me"
    assert any("--files-from-raw" in command for command in commands)
    assert result["items"][0]["audit"]["coverage"] == "hash"
    (dest / "Course" / "b.txt").write_text("changed content")
    before = len([c for c in commands if c[0] == "copy"])
    spec.mode = "verify"
    job, _ = await executor.start(spec, "real-verify-only")
    result = await wait(executor, job["id"])
    assert result["status"] == "failed"
    assert len([c for c in commands if c[0] == "copy"]) == before
    assert (dest / "Course" / "b.txt").read_text() == "changed content"


@pytest.mark.integration
async def test_shared_individual_file_staging_without_parent_listing(
    settings, store, vault, installed_rclone
):
    settings.rclone_bin = installed_rclone
    source = settings.data / "individual.txt"
    source.write_text("single shared file")
    dest = settings.data / "output"
    dest.mkdir()
    store.put("preferences", "default", {"reserve_bytes": 0})
    store.put("destination", "d", {"id": "d", "name": "Test", "kind": "local", "path": str(dest)})

    class LocalMetadata:
        async def metadata(self, *args):
            return {
                "id": "file",
                "name": "individual.txt",
                "mimeType": "text/plain",
                "size": str(source.stat().st_size),
            }

    executor = Executor(settings, store, Rclone(settings, vault), LocalMetadata())
    real_command = executor.command

    async def local_command(key, args, timeout=86400):
        if args[:2] == ["backend", "copyid"]:
            args = ["copyto", str(source), args[4]]
        return await real_command(key, args, timeout)

    executor.command = local_command
    job, _ = await executor.start(
        JobInput(
            items=[ItemInput(drive_url="https://drive.google.com/file/d/file/view")], destination_id="d"
        ),
        "individual-file-test",
    )
    result = await wait(executor, job["id"])
    assert result["status"] == "success", result
    assert (dest / "individual.txt").read_text() == "single shared file"
    assert not list((settings.data / "tmp").iterdir())


async def test_silent_process_cancellation_and_timeout(settings, vault):
    settings.rclone_bin = sys.executable
    rclone = Rclone(settings, vault)
    flag = False

    async def cancelled():
        return flag

    task = asyncio.create_task(
        rclone.run(["-c", "import time; time.sleep(30)"], job_id="silent", cancel=cancelled)
    )
    for _ in range(50):
        if "silent" in rclone.processes:
            break
        await asyncio.sleep(0.02)
    flag = True
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=5)
    assert not rclone.processes
    with pytest.raises(TimeoutError):
        await rclone.run(["-c", "import time; time.sleep(30)"], timeout=0.1)
    assert not rclone.processes
