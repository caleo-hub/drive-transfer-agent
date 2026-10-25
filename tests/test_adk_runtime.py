from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from drive_transfer_agent.agent import Chat
from drive_transfer_agent.executor import Executor
from drive_transfer_agent.queue import Queues


async def test_real_adk_runner_function_call_and_persistent_session(settings, store, vault):
    """Exercise ADK itself, including function dispatch and the after-tool callback, without an API key."""
    calls = []

    class ScriptedModel(BaseLlm):
        model: str = "offline-test-model"

        async def generate_content_async(self, llm_request, stream=False):
            calls.append(llm_request)
            if len(calls) == 1:
                content = types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(
                                id="setup-call", name="request_setup", args={"provider": "google"}
                            )
                        )
                    ],
                )
            else:
                content = types.Content(
                    role="model", parts=[types.Part(text="Abra o cartão para conectar sua conta Google.")]
                )
            yield LlmResponse(content=content)

    class ConnectionStub:
        def status(self):
            return {"google": False, "mega": False}

    executor = Executor(settings, store, object(), ConnectionStub())
    chat = Chat(settings, store, vault, executor, ConnectionStub(), Queues(store))
    chat.model_factory = lambda _: ScriptedModel()
    vault.set("model", "offline-test-placeholder")
    conversation = chat.create()["id"]
    answer = await chat.send(conversation, "Quero conectar meu Google Drive", "runtime-request")
    assert answer["text"] == "Abra o cartão para conectar sua conta Google."
    assert answer["actions"] == [{"type": "setup", "provider": "google"}]
    assert len(calls) == 2
    assert (settings.data / "sessions.sqlite3").exists()
    session = await chat.session_service.get_session(
        app_name="drive_transfer_agent", user_id="local", session_id=conversation
    )
    assert session is not None
    assert len(session.events) >= 3
