"""Structured discovery and immutable transfer plans; none of the read tools copy files."""

import hashlib
import json
import re
import time
import unicodedata
from urllib.parse import urlsplit

from .models import ItemInput, JobInput, Preferences
from .safety import DomainError, label, parse_drive_url, relative_path
from .store import uid

FOLDER = "application/vnd.google-apps.folder"
RANGE = re.compile(r"\bpastas?\s*(?:de\s*)?(\d+)\s*(?:a|até|ate|[-–—])\s*(\d+)\b", re.I)
NUMBER = re.compile(r"^\s*(\d+)\s*(?:[-–—.)]|$)")
APPROVAL = re.compile(
    r"^(?:sim|pode|faça|faca|faça isso|execute|execute o plano|pode seguir|pode executar|pode iniciar|pode fazer|inicie|comece|aprovo|confirmo|autorizo|prossiga)[.!\s]*$",
    re.I,
)


def normalized_name(value):
    return " ".join(
        unicodedata.normalize("NFKC", value).casefold().replace("–", "-").replace("—", "-").split()
    )


def mega_path(value):
    value = value.strip()
    if value.startswith("mega:"):
        value = value[5:]
    if "://" in value:
        raise DomainError(
            "Um link /fm/ do MEGA é navegação, não um caminho. Liste as pastas do MEGA para localizá-lo."
        )
    if value.startswith("/"):
        value = value[1:]
    return relative_path(value) if value else ""


def validate_transfer_scope(store, spec):
    """Enforce human selection and plan boundaries below every model tool."""
    if spec.mode == "inspect" or not spec.conversation_id:
        return
    intent = store.get("intent", spec.conversation_id, {})
    if intent.get("discovery_only"):
        raise DomainError("O pedido atual é uma consulta/listagem. Nenhuma cópia foi autorizada.", 409)
    dest = store.get("destination", spec.destination_id, {})
    if intent.get("destination_kind") and dest.get("kind") != intent["destination_kind"]:
        raise DomainError("O destino não corresponde ao provedor pedido pelo usuário.", 409)
    if intent.get("destination_path") and (
        dest.get("kind") != "mega" or dest.get("path") != intent["destination_path"]
    ):
        raise DomainError("O destino não corresponde ao caminho MEGA explícito do pedido.", 409)
    if intent.get("selection_required"):
        selection = store.get("selection", intent.get("selection_id", ""))
        if not selection or selection["revision"] != intent["revision"]:
            raise DomainError(
                "Selecione primeiro as subpastas solicitadas. Copiar a pasta-pai está bloqueado.", 409
            )
        expected = [i["source_ref"] for i in selection["items"]]
        actual = [i.source_ref for i in spec.items]
        if sorted(actual) != sorted(expected):
            raise DomainError(
                "A tarefa não corresponde às subpastas selecionadas; a pasta-pai não pode substituí-las.", 409
            )
    if intent.get("require_review") and not spec.plan_id:
        raise DomainError("Prepare e apresente um plano antes de iniciar esta transferência.", 409)
    if spec.plan_id:
        plan = store.get("plan", spec.plan_id)
        if not plan or plan["conversation_id"] != spec.conversation_id:
            raise DomainError("Plano desconhecido nesta conversa.", 404)
        if plan["revision"] != intent.get("revision", 0):
            raise DomainError("O pedido mudou. Prepare um novo plano antes de transferir.", 409)
        if plan["requires_approval"] and not plan.get("approved"):
            raise DomainError("O plano está pronto para revisão; aguarde a aprovação do usuário.", 409)
        if spec.model_dump() != plan["spec"]:
            raise DomainError("As origens ou opções não correspondem ao plano salvo.", 409)
        if store.get("destination", spec.destination_id) != plan["destination"]:
            raise DomainError("O destino mudou depois do plano. Prepare um novo plano.", 409)


class Planner:
    def __init__(self, store, executor, connections):
        self.store, self.executor, self.connections = store, executor, connections

    def capture_intent(self, conversation, text, sources):
        intent = self.store.get("intent", conversation, {"revision": 0})
        before = {
            k: intent.get(k)
            for k in (
                "range",
                "names",
                "parent_ref",
                "require_review",
                "selection_required",
                "destination_kind",
                "destination_path",
            )
        }
        transferring = bool(
            re.search(
                r"\b(?:baixe|baixar|copie|copiar|envie|enviar|transfira|transferir|mande)\b", text, re.I
            )
        )
        if re.search(r"\b(?:liste|listar|mostre|consultar|consulte)\b", text, re.I) and not transferring:
            intent["discovery_only"] = True
        if transferring or APPROVAL.fullmatch(text.strip()):
            intent["discovery_only"] = False
        if transferring and re.search(r"\bmega\b", text, re.I):
            intent["destination_kind"] = "mega"
        if transferring and re.search(r"\b(?:pc|computador|disco local)\b", text, re.I):
            intent.update(destination_kind="local", destination_path=None)
        clean = re.sub(r"https?://\S+", "", text)
        path_match = re.search(
            r"""(?:raiz\s+(?:de|da)|pasta(?:\s+existente)?|destino)\s*[:=]?\s*(["“']?)(/[^\r\n]+)""",
            clean,
            re.I,
        )
        if path_match:
            quote, path = path_match.groups()
            if quote:
                end_quote = "”" if quote == "“" else quote
                path = path.split(end_quote, 1)[0]
            else:
                path = (
                    re.split(
                        r"\s+(?:no|na|do|da)\s+MEGA\b|[.;]\s+|,\s*(?:mantendo|preservando|sem|com|que)\b",
                        path,
                        maxsplit=1,
                        flags=re.I,
                    )[0]
                    .strip()
                    .rstrip(".")
                )
            intent.update(destination_kind="mega", destination_path=mega_path(path))
        found = RANGE.search(text)
        if found:
            start, end = map(int, found.groups())
            if not 1 <= start <= end or end - start >= 100:
                raise DomainError("Use um intervalo crescente de até 100 pastas.")
            if intent.get("range") != [start, end]:
                intent.pop("names", None)
            intent.update(range=[start, end], selection_required=True)
        name_lines = [
            line.strip().removeprefix("- ").strip()
            for line in text.splitlines()
            if NUMBER.match(line.strip().removeprefix("- "))
        ]
        if len(name_lines) > 1:
            intent.update(names=name_lines, selection_required=True)
        if transferring and re.search(
            r"\b(?:só|so|apenas|somente|essas|estas)\b.*\bpastas\b|\bpastas\b.*\b(?:apenas|somente)\b",
            text,
            re.I,
        ):
            intent["selection_required"] = True
        if re.search(r"(?:fa[çc]a|monte|prepare)\s+(?:um\s+)?plano|plano\s+primeiro|planeje", text, re.I):
            intent["require_review"] = True
        if re.search(
            r"n[aã]o\s+(?:execute|inicie|copie|baixe)|sem\s+(?:copiar|iniciar|baixar)|(?:apenas|só)\s+(?:um\s+)?plano",
            text,
            re.I,
        ):
            intent["require_review"] = True
        if re.search(r"(?:já|ja)\s+existe|existente", text, re.I):
            intent["destination_must_exist"] = True
        if re.search(r"(?:crie|criar)\s+(?:uma\s+)?(?:nova\s+)?pasta", text, re.I):
            intent["destination_must_exist"] = False
        if re.search(
            r"(?:copie|baixe|transfira)\s+(?:a\s+)?(?:pasta\s+inteira|todas\s+as\s+pastas)", text, re.I
        ) and not re.search(r"n[aã]o", text, re.I):
            intent.update(
                selection_required=False, range=None, names=None, selection_id=None, parent_ref=None
            )
        if intent.get("selection_required") and len(sources) == 1:
            old = self.store.get("selection", intent.get("selection_id", ""), {})
            if sources[0]["source_ref"] not in {i["source_ref"] for i in old.get("items", [])}:
                intent["parent_ref"] = sources[0]["source_ref"]
        after = {k: intent.get(k) for k in before}
        if before != after:
            intent["revision"] += 1
            intent.pop("selection_id", None)
        self.store.put("intent", conversation, intent)
        if APPROVAL.fullmatch(text.strip()):
            plan = self.latest(conversation)
            if plan and plan["revision"] == intent["revision"] and plan["status"] == "ready":
                self.approve(plan["id"], conversation)
        return intent

    def source(self, source_ref):
        source = self.store.get("source", source_ref)
        if not source:
            raise DomainError("Origem desconhecida. Use uma referência registrada do Drive.")
        return source

    async def browse(self, source_ref, page_token="", page_size=100):
        if not 1 <= page_size <= 1000:
            raise DomainError("O tamanho da página deve estar entre 1 e 1000.")
        source = self.source(source_ref)
        meta = await self.connections.metadata(source["id"], source.get("resource_key", ""))
        if meta.get("mimeType") != FOLDER:
            raise DomainError("A origem precisa ser uma pasta para listar subpastas.")
        data = await self.connections.list_children(
            source["id"], source.get("resource_key", ""), page_token, page_size
        )
        entries, registrations = [], []
        for child in data["files"]:
            is_folder = child.get("mimeType") == FOLDER
            parents = child.get("parents", [])
            if parents and source["id"] not in parents:
                raise DomainError("A resposta contém um item fora da pasta consultada.")
            entry = {"id": child["id"], "name": child["name"], "kind": "folder" if is_folder else "file"}
            if child.get("mimeType") != "application/vnd.google-apps.shortcut":
                url = (
                    f"https://drive.google.com/drive/folders/{child['id']}"
                    if is_folder
                    else f"https://drive.google.com/file/d/{child['id']}/view"
                )
                if child.get("resourceKey"):
                    url += "?resourcekey=" + child["resourceKey"]
                entry["source_ref"] = hashlib.sha256(url.encode()).hexdigest()[:32]
                registrations.append(
                    (
                        entry["source_ref"],
                        {
                            **parse_drive_url(url),
                            "url": url,
                            "parent_id": source["id"],
                            "discovered_name": child["name"],
                        },
                    )
                )
            entries.append(entry)
        self.store.put_many("source", registrations)
        return {
            "parent_ref": source_ref,
            "parent_name": meta.get("name"),
            "entries": entries,
            "next_page_token": data.get("nextPageToken", ""),
            "complete": not bool(data.get("nextPageToken")),
        }

    async def select(self, conversation, parent_ref, start_number=0, end_number=0, names=None):
        intent = self.store.get("intent", conversation, {"revision": 0})
        if not parent_ref:
            parent_ref = intent.get("parent_ref", "")
        if intent.get("parent_ref") and parent_ref != intent["parent_ref"]:
            raise DomainError("Essa pasta-pai não corresponde ao pedido atual.")
        if not start_number and intent.get("range"):
            start_number, end_number = intent["range"]
        names = names or intent.get("names") or []
        if intent.get("names") and {normalized_name(n) for n in names} != {
            normalized_name(n) for n in intent["names"]
        }:
            raise DomainError("Os nomes selecionados não correspondem ao pedido do usuário.")
        if not names and not (1 <= start_number <= end_number and end_number - start_number < 100):
            raise DomainError("Informe nomes exatos ou um intervalo crescente de até 100 pastas.")
        if intent.get("range") and [start_number, end_number] != intent["range"]:
            raise DomainError("O intervalo selecionado não corresponde ao pedido do usuário.")
        if len(names) > 100 or len({normalized_name(n) for n in names}) != len(names):
            raise DomainError("A seleção aceita até 100 nomes distintos.")
        entries, token, seen = [], "", set()
        for _ in range(20):
            page = await self.browse(parent_ref, token, 1000)
            entries.extend(e for e in page["entries"] if e["kind"] == "folder")
            token = page["next_page_token"]
            if not token:
                break
            if token in seen:
                raise DomainError("Paginação inconsistente; seleção não confirmada.")
            seen.add(token)
        else:
            raise DomainError("A listagem excedeu o limite. Selecione uma pasta-pai menor.")
        selected = []
        keys = names if names else list(range(start_number, end_number + 1))
        for key in keys:
            matches = [
                e
                for e in entries
                if (
                    normalized_name(e["name"]) == normalized_name(key)
                    if names
                    else bool(NUMBER.match(e["name"])) and int(NUMBER.match(e["name"])[1]) == key
                )
            ]
            if len(matches) != 1:
                raise DomainError(
                    f"Pasta {key}: {'não encontrada' if not matches else 'mais de uma correspondência'}. Nada será copiado."
                )
            selected.append(matches[0])
        if len({e["id"] for e in selected}) != len(selected):
            raise DomainError("A seleção contém a mesma pasta mais de uma vez.")
        if names and intent.get("range"):
            numbers = [int(NUMBER.match(e["name"])[1]) for e in selected if NUMBER.match(e["name"])]
            if sorted(numbers) != list(range(intent["range"][0], intent["range"][1] + 1)):
                raise DomainError("Os nomes não correspondem ao intervalo solicitado.")
        body = {
            "id": uid(),
            "conversation_id": conversation,
            "parent_ref": parent_ref,
            "revision": intent["revision"],
            "items": selected,
            "complete": True,
            "created_at": time.time(),
        }
        self.store.put("selection", body["id"], body)
        intent.update(selection_id=body["id"], selection_required=True, parent_ref=parent_ref)
        self.store.put("intent", conversation, intent)
        return body

    async def mega_folders(self, path=""):
        path = mega_path(path)
        async with self.executor.maintenance:
            self.executor.idle()
            entries = await self.executor.rclone.json(
                ["lsjson", "mega:" + path, "--dirs-only", "--retries", "1"], timeout=90
            )
        return {
            "path": "/" + path,
            "folders": [
                {
                    "name": e["Name"],
                    "id": e.get("ID"),
                    "path": "/" + "/".join(filter(None, [path, e["Name"]])),
                }
                for e in entries
                if e.get("IsDir", True)
            ],
        }

    async def resolve_mega(self, path):
        if path.startswith("https://mega.nz/fm/"):
            handle = urlsplit(path).path.split("/")[-1]
            matches = [e for e in (await self.mega_folders())["folders"] if e.get("id") == handle]
            if len(matches) != 1:
                raise DomainError(
                    "Não foi possível resolver esse link de navegação. Use list_mega_folders e o caminho exato."
                )
            path = matches[0]["path"]
        path = mega_path(path)
        async with self.executor.maintenance:
            self.executor.idle()
            stat = await self.executor.rclone.json(
                ["lsjson", "mega:" + path, "--stat", "--retries", "1"], timeout=90
            )
        if not isinstance(stat, dict) or not stat.get("IsDir"):
            raise DomainError("O destino existente não foi confirmado como pasta no MEGA.")
        existing = next(
            (d for d in self.store.list("destination") if d["kind"] == "mega" and d["path"] == path), None
        )
        if existing:
            return existing
        body = {"id": uid(), "kind": "mega", "name": stat.get("Name") or "Raiz do MEGA", "path": path}
        return self.store.put("destination", body["id"], body)

    def latest(self, conversation):
        pointer = self.store.get("latest_plan", conversation)
        return self.store.get("plan", pointer["id"]) if pointer else None

    async def create(
        self,
        conversation,
        destination_id,
        source_refs=None,
        selection_id="",
        names=None,
        mode="download",
        request_id="",
    ):
        intent = self.store.get("intent", conversation, {"revision": 0})
        refs, names = source_refs or [], names or []
        selection_id = selection_id or intent.get("selection_id", "")
        selection = self.store.get("selection", selection_id) if selection_id else None
        if selection:
            if selection["conversation_id"] != conversation or selection["revision"] != intent["revision"]:
                raise DomainError("A seleção pertence a outro pedido. Liste e selecione novamente.")
            if refs and refs != [e["source_ref"] for e in selection["items"]]:
                raise DomainError(
                    "As origens não correspondem à seleção de subpastas; não substitua pela pasta-pai."
                )
            refs = [e["source_ref"] for e in selection["items"]]
        if names and len(names) != len(refs):
            raise DomainError("Informe um nome por origem ou omita todos.")
        prefs = Preferences(**self.store.get("preferences", "default", {}))
        dest = self.store.get("destination", destination_id or prefs.destination_id)
        if not dest:
            raise DomainError("Localize ou cadastre o destino exato antes de planejar.")
        if intent.get("destination_kind") and dest["kind"] != intent["destination_kind"]:
            raise DomainError("Escolha um destino no provedor solicitado pelo usuário.")
        if intent.get("destination_path") and dest["path"] != intent["destination_path"]:
            raise DomainError("Localize o caminho MEGA exato informado pelo usuário antes de planejar.")
        plan_id, items, preview = uid(), [], []
        for index, ref in enumerate(refs):
            source = self.source(ref)
            meta = await self.connections.metadata(source["id"], source.get("resource_key", ""))
            name = label(names[index] if names else meta["name"])
            if (
                meta.get("mimeType", "").startswith("application/vnd.google-apps.")
                and meta["mimeType"] != FOLDER
            ):
                from .executor import EXPORTS

                if meta["mimeType"] in EXPORTS and not name.lower().endswith(EXPORTS[meta["mimeType"]]):
                    name += EXPORTS[meta["mimeType"]]
            items.append(ItemInput(source_ref=ref, folder_label=name))
            _, target = self.executor.destination({"destination_id": dest["id"]}, name)
            preview.append({"source_ref": ref, "source_id": source["id"], "name": name, "target": target})
        spec = JobInput(
            mode=mode,
            items=items,
            destination_id=dest["id"],
            conversation_id=conversation,
            export_gdocs=prefs.export_gdocs,
            create_empty=prefs.create_empty,
            auto_repair=prefs.auto_repair,
            plan_id=plan_id,
        )
        # Validate the selection even for a draft. Approval itself is only checked at execution.
        if intent.get("selection_required"):
            expected = [e["source_ref"] for e in (selection or {}).get("items", [])]
            if sorted(refs) != sorted(expected) or not expected:
                raise DomainError(
                    "O plano precisa conter exatamente as subpastas selecionadas, nunca a pasta-pai."
                )
        if len({p["target"].casefold() for p in preview}) != len(preview):
            raise DomainError("Duas origens resultariam no mesmo destino.")
        if request_id:
            signature = json.dumps(
                [conversation, request_id, intent["revision"], dest, spec.model_dump(exclude={"plan_id"})],
                sort_keys=True,
            )
            plan_id = hashlib.sha256(signature.encode()).hexdigest()[:32]
            existing = self.store.get("plan", plan_id)
            if existing:
                return existing
            spec.plan_id = plan_id
        body = {
            "id": plan_id,
            "conversation_id": conversation,
            "revision": intent["revision"],
            "selection_id": selection_id or None,
            "status": "ready",
            "created_at": time.time(),
            "requires_approval": bool(intent.get("require_review")),
            "approved": False,
            "destination": dest,
            "items": preview,
            "spec": spec.model_dump(),
            "steps": [
                "Conferir cada origem selecionada",
                "Consultar espaço para a fila inteira",
                "Copiar cada pasta diretamente para seu destino mostrado",
                "Auditar e reparar diferenças limitadas",
            ],
            "note": "Mantém o nome de cada pasta selecionada; não cria a pasta-pai dentro do destino.",
        }
        self.store.put("plan", plan_id, body)
        self.store.put("latest_plan", conversation, {"id": plan_id})
        return body

    def get(self, plan_id, conversation):
        plan = self.store.get("plan", plan_id)
        if not plan or plan["conversation_id"] != conversation:
            raise DomainError("Plano não encontrado nesta conversa.", 404)
        return plan

    def approve(self, plan_id, conversation):
        plan = self.get(plan_id, conversation)
        intent = self.store.get("intent", conversation, {"revision": 0})
        if plan["revision"] != intent["revision"]:
            raise DomainError("O pedido mudou. Prepare um novo plano antes de aprovar.", 409)
        plan["approved"] = True
        return self.store.put("plan", plan_id, plan)

    async def execute(self, plan_id, conversation):
        plan = self.get(plan_id, conversation)
        job, _ = await self.executor.start(JobInput(**plan["spec"]), "plan:" + plan_id)
        plan.update(status="started", job_id=job["id"])
        self.store.put("plan", plan_id, plan)
        return {
            "job_id": job["id"],
            "status": job["status"],
            "plan_id": plan_id,
            "items": plan["items"],
            "destination": plan["destination"],
        }

    async def preflight(self, plan_id, conversation):
        plan = self.get(plan_id, conversation)
        intent = self.store.get("intent", conversation, {"revision": 0})
        if intent["revision"] != plan["revision"]:
            raise DomainError("O pedido mudou. Prepare um novo plano antes da consulta.")
        if self.store.get("destination", plan["spec"]["destination_id"]) != plan["destination"]:
            raise DomainError("O destino mudou depois do plano. Prepare um novo plano.", 409)
        spec = JobInput(**{**plan["spec"], "mode": "inspect", "plan_id": None})
        job, _ = await self.executor.start(spec, "preflight:" + plan_id)
        plan["preflight_job_id"] = job["id"]
        self.store.put("plan", plan_id, plan)
        return {"job_id": job["id"], "mode": "inspect", "copied": False, "plan_id": plan_id}
