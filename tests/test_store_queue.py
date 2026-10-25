import concurrent.futures

import pytest

from drive_transfer_agent.models import ItemInput, QueueAction
from drive_transfer_agent.queue import Queues
from drive_transfer_agent.safety import DomainError
from drive_transfer_agent.store import Store


def test_idempotency_and_concurrent_creation(store):
    def create():
        return store.create_job("same-request", {"mode": "inspect"})

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        jobs = list(pool.map(lambda _: create(), range(4)))
    assert len({j[0]["id"] for j in jobs}) == 1
    assert sum(j[1] for j in jobs) == 1
    with pytest.raises(DomainError) as error:
        store.create_job("another-request", {})
    assert error.value.status == 409


def test_idempotency_rejects_different_spec(store):
    store.create_job("same", {"mode": "inspect"})
    with pytest.raises(DomainError):
        store.create_job("same", {"mode": "download"})


def test_restart_reconciles_without_restarting(store):
    job, _ = store.create_job("request", {"mode": "download"})
    Store(store.path).reconcile()
    assert store.job(job["id"])["status"] == "interrupted"
    assert store.active() is None


def test_destination_provenance(store):
    store.claim("D:/Backup/Course", "a")
    store.claim("d:/backup/course", "a")
    with pytest.raises(DomainError):
        store.claim("d:/backup/course", "b")


def test_queue_atomic_import_and_stable_ids(store):
    queue = Queues(store)
    first = queue.import_text(
        "c", "A | https://drive.google.com/folders/a\nB | https://drive.google.com/folders/b"
    )
    ids = [i["item_id"] for i in first["items"]]
    with pytest.raises(DomainError):
        queue.import_text("c", "https://drive.google.com/folders/c\ninvalid")
    assert len(queue.get("c")["items"]) == 2
    queue.change("c", QueueAction(action="reorder", order=list(reversed(ids))))
    queue.change("c", QueueAction(action="rename", item_id=ids[0], name="New A"))
    assert queue.get("c")["items"][1]["folder_label"] == "New A"
    queue.change("c", QueueAction(action="remove", item_id=ids[0]))
    queue.change("c", QueueAction(action="undo"))
    assert queue.get("c")["items"][1]["item_id"] == ids[0]


def test_queue_duplicate_name_undo_and_limit(store):
    queue = Queues(store)
    queue.change("c", QueueAction(action="add", items=[ItemInput(source_ref="x", folder_label="A")]))
    with pytest.raises(DomainError):
        queue.change("c", QueueAction(action="add", items=[ItemInput(source_ref="y", folder_label="a")]))
    assert len(queue.get("c")["items"]) == 1
    with pytest.raises(DomainError):
        queue.change("c", QueueAction(action="add", items=[ItemInput(source_ref=str(i)) for i in range(100)]))


def test_message_deduplication(store):
    store.add_message("c", "same", "assistant", "one")
    store.add_message("c", "same", "assistant", "two")
    assert len(store.messages("c")) == 1
    assert store.reply("c", "same")["text"] == "one"
