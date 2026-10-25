from google.adk.tools import FunctionTool

from drive_transfer_agent.agent import Chat
from drive_transfer_agent.executor import Executor
from drive_transfer_agent.queue import Queues


class FakeRclone:
    processes = {}

    async def version(self):
        return {"installed": True, "version": "test"}


class FakeConnections:
    def status(self):
        return {"google": False, "mega": False, "model": False}


def test_every_adk_tool_has_a_valid_schema(settings, store, vault):
    executor = Executor(settings, store, FakeRclone(), FakeConnections())
    chat = Chat(settings, store, vault, executor, FakeConnections(), Queues(store))
    tools = chat.tools("conversation", "request")
    for tool in tools:
        declaration = FunctionTool(tool)._get_declaration()
        assert declaration.name == tool.__name__
    assert all("shell" not in t.__name__ for t in tools)


async def test_bare_link_uses_preferences_without_model_and_deduplicates(settings, store, vault):
    executor = Executor(settings, store, FakeRclone(), FakeConnections())
    chat = Chat(settings, store, vault, executor, FakeConnections(), Queues(store))
    conversation = chat.create()["id"]
    store.put("preferences", "default", {"default_action": "inspect"})
    started = []

    async def start(spec, idem):
        started.append(spec)
        return {"id": "real-job-reference", "status": "pending"}, True

    executor.start = start
    text = "https://drive.google.com/folders/course?resourcekey=private"
    response = await chat.send(conversation, text, "same-request")
    repeated = await chat.send(conversation, text, "same-request")
    assert response["job_ids"] == ["real-job-reference"]
    assert repeated == response
    assert len(started) == 1
    assert started[0].mode == "inspect"
    assert "private" not in str(store.messages(conversation))


async def test_ambiguous_queue_requires_current_item_id(settings, store, vault):
    executor = Executor(settings, store, FakeRclone(), FakeConnections())
    chat = Chat(settings, store, vault, executor, FakeConnections(), Queues(store))
    change = next(t for t in chat.tools("c", "r") if t.__name__ == "change_queue")
    result = change(action="rename", item_id="second", name="New name")
    assert "error" in result
    assert not store.get("queue", "c")
