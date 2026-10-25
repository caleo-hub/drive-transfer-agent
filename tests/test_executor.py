import asyncio
import json
from pathlib import Path

from drive_transfer_agent.executor import Executor
from drive_transfer_agent.models import ItemInput, JobInput
from drive_transfer_agent.safety import DomainError
from drive_transfer_agent.store import FINAL


class FakeConnections:
    async def metadata(self, object_id, resource_key=""):
        return {"id": object_id, "name": object_id, "mimeType": "application/vnd.google-apps.folder"}


class FakeRclone:
    def __init__(self):
        self.processes = {}
        self.copies = 0
        self.checks = 0

    async def json(self, args, **kwargs):
        return {}


async def wait_job(executor, key):
    for _ in range(200):
        job = executor.store.job(key)
        if job["status"] in FINAL:
            return job
        await asyncio.sleep(0.01)
    raise AssertionError("Job did not finish")


def prepare(settings, store):
    rclone = FakeRclone()
    executor = Executor(settings, store, rclone, FakeConnections())
    store.put(
        "destination",
        "d",
        {"id": "d", "name": "Downloads", "kind": "local", "path": str(settings.data / "downloads")},
    )
    return executor


async def test_inspect_needs_no_destination_and_never_copies(settings, store):
    executor = prepare(settings, store)

    async def command(key, args, timeout=100):
        assert args[0] == "lsjson"
        return 0, json.dumps([{"Path": "a.txt", "Size": 3, "Hashes": {"MD5": "hash"}}]), ""

    executor.command = command
    spec = JobInput(mode="inspect", items=[ItemInput(drive_url="https://drive.google.com/folders/a")])
    job, _ = await executor.start(spec, "inspect-request")
    result = await wait_job(executor, job["id"])
    assert result["status"] == "success"
    assert result["items"][0]["bytes"] == 3


async def test_empty_is_attention(settings, store):
    executor = prepare(settings, store)

    async def command(*args, **kwargs):
        return 0, "[]", ""

    executor.command = command
    spec = JobInput(items=[ItemInput(drive_url="https://drive.google.com/folders/a")], destination_id="d")
    job, _ = await executor.start(spec, "empty-request")
    result = await wait_job(executor, job["id"])
    assert result["status"] == "attention"
    assert result["items"][0]["status"] == "empty"


async def test_partial_failure_continues(settings, store):
    executor = prepare(settings, store)

    async def inspect(key, item, spec):
        source = store.get("source", item["source_ref"])
        if source["id"] == "bad":
            raise DomainError("Acesso negado")
        return {
            "name": source["id"],
            "kind": "folder",
            "count": 1,
            "bytes": 1,
            "unknown_size": False,
            "source_ref": item["source_ref"],
            "files": [],
            "metadata": {},
        }

    async def transfer(*args):
        return {"ok": True, "coverage": "hash"}

    executor.inspect, executor.folder_transfer = inspect, transfer
    spec = JobInput(
        items=[ItemInput(drive_url=f"https://drive.google.com/folders/{i}") for i in ["bad", "good"]],
        destination_id="d",
    )
    job, _ = await executor.start(spec, "partial-request")
    result = await wait_job(executor, job["id"])
    assert result["status"] == "failed"
    assert [i["status"] for i in result["items"]] == ["failed", "success"]


async def test_capacity_known_unknown_insufficient(settings, store, monkeypatch):
    executor = prepare(settings, store)
    dest = store.get("destination", "d")
    monkeypatch.setattr("drive_transfer_agent.executor.free_space", lambda _: 2 * 1024**3)
    assert (await executor.capacity(dest, 1))["status"] == "sufficient"
    assert (await executor.capacity(dest, 3 * 1024**3))["status"] == "insufficient"
    assert (await executor.capacity(dest, 1, unknown=True))["status"] == "estimated"
    monkeypatch.setattr("drive_transfer_agent.executor.free_space", lambda _: None)
    assert (await executor.capacity(dest, 1))["status"] == "unknown"
    assert (await executor.capacity({"kind": "mega", "path": ""}, 1))["status"] == "unknown"


async def test_final_audit_after_last_repair_and_missing_on_destination(settings, store):
    executor = prepare(settings, store)
    commands = []

    async def command(key, args, timeout=100):
        commands.append(args)
        if args[0] == "check":
            executor.rclone.checks += 1
            report = Path(args[args.index("--combined") + 1])
            report.write_text("+ missing.txt\n" if executor.rclone.checks < 4 else "= missing.txt\n")
            return (1 if executor.rclone.checks < 4 else 0), "", ""
        if "--files-from-raw" in args:
            path = Path(args[args.index("--files-from-raw") + 1])
            assert path.read_text() == "missing.txt\n"
        return 0, "", ""

    executor.command = command
    store.put("source", "ref", {"id": "a"})
    spec = {"mode": "download", "export_gdocs": True, "create_empty": True, "auto_repair": True}
    audit = await executor.folder_transfer(
        "job",
        {"source_ref": "ref", "files": [{"Hashes": {"MD5": "x"}}]},
        str(settings.data / "target"),
        spec,
        lambda **_: None,
    )
    assert audit["ok"]
    assert executor.rclone.checks == 4
    assert sum("--files-from-raw" in c for c in commands) == 3


async def test_verify_never_copies_and_disabled_repair_still_audits(settings, store):
    executor = prepare(settings, store)

    async def command(key, args, timeout=100):
        assert args[0] == "check"
        Path(args[args.index("--combined") + 1]).write_text("* different.txt\n")
        return 1, "", ""

    executor.command = command
    store.put("source", "ref", {"id": "a"})
    audit = await executor.folder_transfer(
        "job",
        {"source_ref": "ref", "files": []},
        "mega:target",
        {"mode": "verify", "export_gdocs": True, "auto_repair": True},
        lambda **_: None,
    )
    assert not audit["ok"]
    assert audit["coverage"] == "size"


async def test_download_without_repair_still_checks(settings, store):
    executor = prepare(settings, store)
    commands = []

    async def command(key, args, timeout=100):
        commands.append(args[0])
        if args[0] == "check":
            Path(args[args.index("--combined") + 1]).write_text("* changed.txt\n")
            return 1, "", ""
        return 0, "", ""

    executor.command = command
    store.put("source", "ref", {"id": "a"})
    audit = await executor.folder_transfer(
        "job",
        {"source_ref": "ref", "files": []},
        "mega:target",
        {"mode": "download", "export_gdocs": True, "auto_repair": False, "create_empty": True},
        lambda **_: None,
    )
    assert not audit["ok"]
    assert commands == ["copy", "check"]


async def test_cancel_during_silent_inspection_does_not_advance(settings, store):
    executor = prepare(settings, store)
    entered = asyncio.Event()
    seen = []

    async def inspect(key, item, spec):
        seen.append(item["source_ref"])
        entered.set()
        while not await executor.cancelled(key):
            await asyncio.sleep(0.01)
        raise asyncio.CancelledError

    executor.inspect = inspect
    job, _ = await executor.start(
        JobInput(
            mode="inspect",
            items=[
                ItemInput(drive_url="https://drive.google.com/folders/a"),
                ItemInput(drive_url="https://drive.google.com/folders/b"),
            ],
        ),
        "cancel-request",
    )
    await entered.wait()
    await executor.stop(job["id"])
    result = await wait_job(executor, job["id"])
    assert result["status"] == "cancelled"
    assert len(seen) == 1
    assert len(result["items"]) == 2


async def test_cancel_before_worker_launch_releases_executor(settings, store):
    executor = prepare(settings, store)
    spec = JobInput(mode="inspect", items=[ItemInput(drive_url="https://drive.google.com/folders/a")])
    job, _ = await executor.start(spec, "cancel-before-launch")
    await executor.stop(job["id"])
    await asyncio.sleep(0)
    assert store.job(job["id"])["status"] == "cancelled"
    assert store.active() is None


async def test_full_queue_capacity_checked_before_first_copy(settings, store, monkeypatch):
    executor = prepare(settings, store)
    store.put("preferences", "default", {"reserve_bytes": 0})
    monkeypatch.setattr("drive_transfer_agent.executor.free_space", lambda _: 6)

    async def inspect(key, item, spec):
        name = store.get("source", item["source_ref"])["id"]
        return {
            "name": name,
            "kind": "folder",
            "count": 1,
            "bytes": 4,
            "unknown_size": False,
            "source_ref": item["source_ref"],
            "files": [],
            "metadata": {},
        }

    async def transfer(*args):
        raise AssertionError("Copy must not start when the whole queue does not fit")

    executor.inspect, executor.folder_transfer = inspect, transfer
    job, _ = await executor.start(
        JobInput(
            items=[ItemInput(drive_url=f"https://drive.google.com/folders/{name}") for name in ["a", "b"]],
            destination_id="d",
        ),
        "whole-queue-capacity",
    )
    result = await wait_job(executor, job["id"])
    assert result["status"] == "attention"
    assert all(item["status"] == "attention" for item in result["items"])


async def test_staging_on_another_volume_is_measured(settings, store, monkeypatch):
    executor = prepare(settings, store)
    store.put("preferences", "default", {"reserve_bytes": 0})
    monkeypatch.setattr(
        "drive_transfer_agent.executor.volume_id", lambda p: 1 if p == "destination-volume" else 2
    )
    monkeypatch.setattr(
        "drive_transfer_agent.executor.free_space", lambda p: 100 if p == "destination-volume" else 2
    )
    capacity = await executor.capacity({"kind": "local", "path": "destination-volume"}, 4, temp_required=4)
    assert capacity["status"] == "insufficient"
    assert capacity["temporary_free_bytes"] == 2


async def test_space_exhaustion_stops_future_commands(settings, store, monkeypatch):
    executor = prepare(settings, store)
    job, _ = store.create_job("space-monitor", {"items": []})
    store.put("preferences", "default", {"reserve_bytes": 10})
    monkeypatch.setattr("drive_transfer_agent.executor.free_space", lambda _: 0)
    await executor.monitor_space(job["id"], store.get("destination", "d"), asyncio.Event())
    assert store.job(job["id"])["space_exhausted"]
    from pytest import raises

    with raises(DomainError):
        await executor.command(job["id"], ["copy", "source", "target"])
