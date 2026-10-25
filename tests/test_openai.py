import json
import os

import pytest
from google.adk.models.lite_llm import LiteLLMClient
from litellm import ModelResponse
from pydantic import ValidationError

from drive_transfer_agent.agent import Chat
from drive_transfer_agent.config import Settings
from drive_transfer_agent.executor import Executor
from drive_transfer_agent.queue import Queues
from drive_transfer_agent.rclone import Rclone


@pytest.mark.parametrize("name", ["gpt-5.4-mini", "openai/gpt-5.4-mini"])
def test_openai_model_name_normalized(name):
    assert Settings(agent_model=name, _env_file=None).agent_model == "openai/gpt-5.4-mini"


@pytest.mark.parametrize("name", ["", "gemini-flash-latest", "anthropic/claude", "https://host/model"])
def test_foreign_model_configuration_rejected(name):
    with pytest.raises(ValidationError):
        Settings(agent_model=name, _env_file=None)


@pytest.mark.parametrize("use_environment", [False, True])
async def test_openai_adapter_tools_and_private_key(
    settings, store, vault, monkeypatch, caplog, use_environment
):
    calls = []
    secret = "sk-proj-" + "x" * 80
    original_environment_key = os.environ.get("OPENAI_API_KEY")
    vault.set("openai", "unused-vault-placeholder" if use_environment else secret)
    if use_environment:
        settings.openai_api_key = secret

    async def completion(self, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "setup-call",
                        "type": "function",
                        "function": {
                            "name": "request_setup",
                            "arguments": json.dumps({"provider": "google"}),
                        },
                    }
                ],
            }
            finish = "tool_calls"
        else:
            message = {"role": "assistant", "content": "Abra o cartão Google Drive."}
            finish = "stop"
        return ModelResponse(
            model="gpt-5.4-mini", choices=[{"index": 0, "message": message, "finish_reason": finish}]
        )

    monkeypatch.setattr(LiteLLMClient, "acompletion", completion)

    class ConnectionStub:
        def status(self):
            return {"google": False, "mega": False}

    connection = ConnectionStub()
    executor = Executor(settings, store, object(), connection)
    chat = Chat(settings, store, vault, executor, connection, Queues(store))
    conversation = chat.create()["id"]
    answer = await chat.send(conversation, "Quero conectar meu Google Drive", "openai-request")
    assert answer["text"] == "Abra o cartão Google Drive."
    assert answer["actions"] == [{"type": "setup", "provider": "google"}]
    assert len(calls) == 2
    assert all(call["api_key"] == secret for call in calls)
    assert all(call["api_base"] == "https://api.openai.com/v1" for call in calls)
    assert all(call["model"] == "openai/gpt-5.4-mini" for call in calls)
    assert "request_setup" in {tool["function"]["name"] for tool in calls[0]["tools"]}
    assert any(message["role"] == "tool" for message in calls[1]["messages"])
    assert secret not in json.dumps([call["messages"] for call in calls])
    assert secret not in json.dumps(answer)
    assert secret not in caplog.text
    assert os.environ.get("OPENAI_API_KEY") == original_environment_key
    assert secret.encode() not in (settings.data / "sessions.sqlite3").read_bytes()


async def test_rclone_does_not_inherit_model_key(settings, vault, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "private-model-key")
    monkeypatch.setenv("DTA_MASTER_KEY", "private-master-key")
    env = await Rclone(settings, vault).environment(set())
    assert "OPENAI_API_KEY" not in env
    assert "DTA_MASTER_KEY" not in env
