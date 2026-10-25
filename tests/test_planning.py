import json

import httpx
import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from drive_transfer_agent.agent import Chat
from drive_transfer_agent.api import create_app
from drive_transfer_agent.connections import Connections
from drive_transfer_agent.executor import Executor
from drive_transfer_agent.models import ItemInput, JobInput
from drive_transfer_agent.planning import FOLDER, Planner, mega_path
from drive_transfer_agent.queue import Queues
from drive_transfer_agent.safety import DomainError
from drive_transfer_agent.storage_tools import StorageTools
from drive_transfer_agent.store import Store

NAMES = [
    "34 – Anestesia para Otorrinolaringologia",
    "35 – Oftalmologia",
    "36 – Anestesia Ambulatorial",
    "37 – Sistema Endócrino",
    "38 – Urgências - Trauma",
]


class DirectoryConnections:
    def __init__(self):
        self.entries = [
            {"id": f"folder_{n}", "name": name, "mimeType": FOLDER, "parents": ["root"]}
            for n, name in enumerate(NAMES, 34)
        ]
        self.entries += [
            {"id": "file_34", "name": "34 – arquivo.pdf", "mimeType": "application/pdf", "parents": ["root"]},
            {"id": "folder_340", "name": "340 – Não selecionar", "mimeType": FOLDER, "parents": ["root"]},
        ]
        self.calls = []

    def status(self):
        return {"google": True, "mega": True, "model": True}

    async def metadata(self, object_id, resource_key=""):
        if object_id == "root":
            return {"id": "root", "name": "Anest-Review Extensive 2026", "mimeType": FOLDER}
        return next(e for e in self.entries if e["id"] == object_id)

    async def list_children(self, parent, resource_key="", page_token="", page_size=100):
        self.calls.append((parent, page_token))
        assert parent == "root"
        return (
            {"files": self.entries[:2], "nextPageToken": "page-two"}
            if not page_token
            else {"files": self.entries[2:]}
        )


class Rclone:
    processes = {}

    def __init__(self):
        self.commands = []

    async def json(self, args, **kwargs):
        self.commands.append(args)
        if "--stat" in args:
            return {"IsDir": True, "Name": args[1].split(":", 1)[1].split("/")[-1]}
        if args[0] == "size":
            return {"count": 9, "bytes": 123}
        return [
            {"Name": "ANEST REVIEW 2026", "IsDir": True, "ID": "existing-mega-id", "Size": -1},
            {"Name": "teste.pdf", "IsDir": False, "Size": 3},
        ]

    async def run(self, args, **kwargs):
        self.commands.append(args)
        return 0, "", ""

    async def version(self):
        return {"installed": True, "version": "test"}


@pytest.fixture
def setup(settings):
    store = Store(settings.data / "jobs.sqlite3")
    connections = DirectoryConnections()
    executor = Executor(settings, store, Rclone(), connections)
    planner = Planner(store, executor, connections)
    ref = executor.register_source("https://drive.google.com/drive/folders/root")["source_ref"]
    store.put("conversation", "c", {"id": "c", "title": "Teste"})
    return planner, executor, connections, ref


async def prepare_plan(setup):
    planner, executor, _, parent = setup
    planner.capture_intent(
        "c", "Baixe as pastas de 34 a 38 para o MEGA. Faça um plano primeiro.", [{"source_ref": parent}]
    )
    selection = await planner.select("c", parent)
    dest = await planner.resolve_mega("/ANEST REVIEW 2026")
    return await planner.create("c", dest["id"], selection_id=selection["id"])


async def test_paged_selection_resolves_only_folder_ids_and_exact_targets(setup):
    planner, executor, connections, parent = setup
    plan = await prepare_plan(setup)
    assert connections.calls == [("root", ""), ("root", "page-two")]
    assert [i["source_id"] for i in plan["items"]] == [f"folder_{n}" for n in range(34, 39)]
    assert [i["name"] for i in plan["items"]] == NAMES
    assert [i["target"] for i in plan["items"]] == ["mega:ANEST REVIEW 2026/" + n for n in NAMES]
    assert all("Anest-Review Extensive" not in i["target"] for i in plan["items"])
    assert executor.store.active() is None
    assert all(args[0] not in {"copy", "copyto", "mkdir"} for args in executor.rclone.commands)
    with pytest.raises(DomainError, match="pasta-pai"):
        await planner.create("c", plan["destination"]["id"], [parent])
    with pytest.raises(DomainError, match="subpastas"):
        executor.normalize(
            JobInput(
                items=[ItemInput(source_ref=parent)],
                conversation_id="c",
                destination_id=plan["destination"]["id"],
            )
        )


@pytest.mark.parametrize("problem", ["missing", "duplicate", "cycle"])
async def test_selection_never_falls_back_to_parent_or_partial_results(setup, problem):
    planner, executor, connections, parent = setup
    planner.capture_intent("c", "Baixe as pastas 34 a 38", [{"source_ref": parent}])
    if problem == "missing":
        connections.entries = [e for e in connections.entries if e["id"] != "folder_37"]
    elif problem == "duplicate":
        connections.entries.append({"id": "duplicate", "name": "37 – Outra pasta", "mimeType": FOLDER})
    else:

        async def cycle(*args):
            return {"files": [], "nextPageToken": "same"}

        connections.list_children = cycle
    with pytest.raises(DomainError):
        await planner.select("c", parent)
    assert not executor.store.list("selection")
    assert not executor.store.jobs()


async def test_review_scope_changes_and_plan_tampering_are_enforced_below_tools(setup):
    planner, executor, _, _ = setup
    plan = await prepare_plan(setup)
    with pytest.raises(DomainError, match="aprovação"):
        executor.normalize(JobInput(**plan["spec"]))
    planner.capture_intent("c", "faça", [])
    assert planner.get(plan["id"], "c")["approved"]
    assert len(executor.normalize(JobInput(**plan["spec"]))["items"]) == 5
    changed = JobInput(**plan["spec"])
    changed.items[0].folder_label = "Nome diferente"
    with pytest.raises(DomainError, match="plano salvo"):
        executor.normalize(changed)
    dest = plan["destination"]
    executor.store.put("destination", dest["id"], {**dest, "path": "Destino errado"})
    with pytest.raises(DomainError, match="destino mudou"):
        executor.normalize(JobInput(**plan["spec"]))
    executor.store.put("destination", dest["id"], dest)
    planner.capture_intent("c", "Agora baixe as pastas 35 a 38", [])
    with pytest.raises(DomainError):
        planner.approve(plan["id"], "c")
    with pytest.raises(DomainError):
        executor.normalize(JobInput(**plan["spec"]))


async def test_plan_execution_is_idempotent_and_preflight_does_not_copy(setup):
    planner, executor, _, _ = setup
    plan = await prepare_plan(setup)
    started = []

    async def inspect(*args):
        raise AssertionError("A fake start must not launch real work")

    async def start(spec, idem):
        executor.normalize(spec)
        started.append((spec, idem))
        return executor.store.create_job(idem, spec.model_dump())

    executor.start = start
    preflight = await planner.preflight(plan["id"], "c")
    assert not preflight["copied"]
    assert started[0][0].mode == "inspect"
    executor.store.update_job(preflight["job_id"], status="success")
    planner.approve(plan["id"], "c")
    first = await planner.execute(plan["id"], "c")
    second = await planner.execute(plan["id"], "c")
    assert first["job_id"] == second["job_id"]
    assert len(executor.store.jobs()) == 2


async def test_name_selection_context_and_destination_are_exact(setup):
    planner, executor, _, parent = setup
    planner.capture_intent(
        "c", "Baixe só essas pastas para o MEGA\n" + "\n".join(NAMES), [{"source_ref": parent}]
    )
    planner.capture_intent("c", "É a pasta existente /ANEST REVIEW 2026", [])
    selected = await planner.select("c", parent)
    dest = await planner.resolve_mega("mega:/ANEST REVIEW 2026")
    plan = await planner.create("c", dest["id"], selection_id=selected["id"], request_id="same")
    repeated = await planner.create("c", dest["id"], selection_id=selected["id"], request_id="same")
    assert plan == repeated
    wrong = await planner.resolve_mega("/Outra")
    with pytest.raises(DomainError, match="caminho MEGA"):
        await planner.create("c", wrong["id"], selection_id=selected["id"])
    with pytest.raises(DomainError, match="pasta existente"):
        await StorageTools(executor, planner).mkdir("c", dest["id"], "ANEST REVIEW 2026")


@pytest.mark.parametrize(
    "description",
    [
        "a pasta existente /ANEST REVIEW 2026 no MEGA. Preserve os nomes.",
        "o destino /ANEST REVIEW 2026, sem incluir a pasta-pai",
        'a pasta existente "/ANEST REVIEW 2026" no MEGA',
        "a pasta existente “/ANEST REVIEW 2026” no MEGA",
    ],
)
def test_destination_path_does_not_include_surrounding_portuguese(setup, description):
    planner, _, _, _ = setup
    intent = planner.capture_intent("c", description, [])
    assert intent["destination_path"] == "ANEST REVIEW 2026"


async def test_browse_registers_files_and_redacts_resource_keys(setup):
    planner, executor, connections, parent = setup
    connections.entries[0]["resourceKey"] = "private-resource-key"
    first = await planner.browse(parent)
    assert first["complete"] is False
    ref = first["entries"][0]["source_ref"]
    assert executor.store.get("source", ref)["resource_key"] == "private-resource-key"
    assert "private-resource-key" not in json.dumps(first)
    page = await planner.browse(parent, "page-two")
    assert any(e["id"] == "file_34" and e["source_ref"] for e in page["entries"])


async def test_inventory_registration_commits_once_per_page(setup, monkeypatch):
    planner, executor, _, parent = setup
    commits = []
    original = executor.store.put_many

    def batch(kind, records):
        commits.append((kind, len(records)))
        return original(kind, records)

    monkeypatch.setattr(executor.store, "put_many", batch)
    page = await planner.browse(parent)
    assert commits == [("source", 2)]
    assert all(executor.store.get("source", e["source_ref"]) for e in page["entries"])


async def test_connected_accounts_do_not_request_setup_and_range_blocks_legacy_run(setup, settings, vault):
    planner, executor, connections, parent = setup
    chat = Chat(settings, executor.store, vault, executor, connections, Queues(executor.store))
    tools = {tool.__name__: tool for tool in chat.tools("c", "request")}
    assert tools["request_setup"]("google")["configured"] is True
    assert "ui_action" not in tools["request_setup"]("mega")
    planner.capture_intent("c", "Baixe as pastas 34 a 38 para o MEGA", [{"source_ref": parent}])
    dest = await planner.resolve_mega("/ANEST REVIEW 2026")
    result = await tools["run_transfer"]("download", [parent], dest["id"])
    assert "error" in result
    assert not executor.store.jobs()


async def test_drive_list_api_pagination_parameters_and_incomplete_search(settings, vault, monkeypatch):
    service = Connections(settings, vault, Rclone())

    async def token():
        return {"access_token": "private-access"}

    service.google_token = token
    requests = []

    async def get(self, url, **kwargs):
        requests.append(kwargs)
        return httpx.Response(
            200, json={"files": [], "nextPageToken": "next", "incompleteSearch": len(requests) == 2}
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    data = await service.list_children("parent", "private-key", "cursor", 1000)
    assert data["nextPageToken"] == "next"
    assert requests[0]["params"]["q"] == "'parent' in parents and trashed = false"
    assert requests[0]["params"]["pageToken"] == "cursor"
    assert requests[0]["headers"]["X-Goog-Drive-Resource-Keys"] == "parent/private-key"
    with pytest.raises(DomainError, match="incompleta"):
        await service.list_children("parent")


@pytest.mark.parametrize(
    "bad", ["/../escape", "//absolute", "D:/escape", "a\\b", "-flag", "https://mega.nz/fm/abc"]
)
def test_mega_paths_reject_escape_and_navigation_urls(bad):
    with pytest.raises(DomainError):
        mega_path(bad)


async def test_storage_inventory_usage_and_scoped_mkdir(setup):
    planner, executor, _, _ = setup
    dest = await planner.resolve_mega("/ANEST REVIEW 2026")
    tools = StorageTools(executor, planner)
    first = await tools.list_entries(dest["id"], limit=1)
    assert not first["complete"] and first["next_offset"] == 1
    assert (await tools.list_entries(dest["id"], offset=1))["complete"]
    assert (await tools.usage(dest["id"]))["bytes"] == 123
    created = await tools.mkdir("c", dest["id"], "Nova pasta")
    assert created["target"] == "mega:ANEST REVIEW 2026/Nova pasta"
    for bad in ["../escape", "/absolute", "D:/escape"]:
        with pytest.raises(DomainError):
            tools.target(dest["id"], bad)


async def test_plan_api_requires_human_approval_and_keeps_archived_readonly(setup, settings, vault):
    planner, executor, connections, _ = setup
    app = create_app(settings, vault=vault, rclone=executor.rclone, connections=connections)
    app.state.chat.planner = planner
    plan = await prepare_plan(setup)

    async def start(spec, idem):
        executor.normalize(spec)
        return executor.store.create_job(idem, spec.model_dump())

    executor.start = start
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        endpoint = f"/api/conversations/c/plans/{plan['id']}/execute"
        assert (await c.get("/api/conversations/c/plan")).json()["items"] == plan["items"]
        assert (await c.post(endpoint)).status_code == 403
        response = await c.post(endpoint, headers={"x-dta-request": "1"})
        assert response.status_code == 200
        assert len(executor.store.jobs()) == 1
        executor.store.update_job(response.json()["job_id"], status="success")
        await c.patch("/api/conversations/c", json={"archived": True}, headers={"x-dta-request": "1"})
        assert (await c.post(endpoint, headers={"x-dta-request": "1"})).status_code == 409


async def test_real_adk_plans_subset_and_cannot_execute_before_review(setup, settings, vault):
    planner, executor, connections, parent = setup
    chat = Chat(settings, executor.store, vault, executor, connections, Queues(executor.store))
    vault.set("openai", "offline-placeholder")
    responses = []

    class ScriptedModel(BaseLlm):
        model: str = "offline-planner"

        async def generate_content_async(self, llm_request, stream=False):
            for content in llm_request.contents:
                for part in content.parts or []:
                    if part.function_response and part.function_response.id not in {r[0] for r in responses}:
                        responses.append((part.function_response.id, part.function_response.response))
            step = len(responses)
            if step == 0:
                name, args = "select_source_folders", {"parent_ref": parent}
            elif step == 1:
                name, args = "resolve_mega_destination", {"path": "/ANEST REVIEW 2026"}
            elif step == 2:
                name, args = "plan_transfer", {"destination_id": responses[-1][1]["id"]}
            elif step == 3:
                name, args = "execute_transfer_plan", {"plan_id": responses[-1][1]["id"]}
            else:
                yield LlmResponse(
                    content=types.Content(role="model", parts=[types.Part(text="Plano pronto para revisão.")])
                )
                return
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(function_call=types.FunctionCall(id=str(step), name=name, args=args))],
                )
            )

    chat.model_factory = lambda _: ScriptedModel()
    answer = await chat.send(
        "c",
        "Baixe as pastas 34 a 38 para o MEGA. Faça um plano primeiro. https://drive.google.com/drive/folders/root",
        "adk-plan",
    )
    assert answer["text"] == "Plano pronto para revisão."
    assert len(chat.planner.latest("c")["items"]) == 5
    assert "aprovação" in responses[-1][1]["error"]
    assert not executor.store.jobs()


async def test_old_conversation_and_bare_link_preserve_subset_without_auto_download(setup, settings, vault):
    planner, executor, connections, parent = setup
    chat = Chat(settings, executor.store, vault, executor, connections, Queues(executor.store))
    executor.store.put("preferences", "default", {"default_action": "download", "destination_id": "old"})
    executor.store.add_message("c", "old", "user", "Baixe só as pastas 34 a 38. Faça um plano primeiro.")
    await chat.send("c", "https://drive.google.com/drive/folders/root", "link-after-selection")
    intent = executor.store.get("intent", "c")
    assert intent["range"] == [34, 38]
    assert intent["require_review"] and intent["parent_ref"] == parent
    assert not executor.store.jobs()
