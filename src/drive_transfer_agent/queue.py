from .models import ItemInput, QueueAction
from .safety import DomainError, label, parse_drive_url
from .store import uid


class Queues:
    def __init__(self, store):
        self.store = store

    def get(self, conversation):
        return self.store.get("queue", conversation, {"items": [], "removed": None})

    def change(self, conversation, action: QueueAction):
        state = self.get(conversation)
        items = state["items"]
        if action.action == "add":
            if len(items) + len(action.items) > 100:
                raise DomainError("A fila aceita até 100 itens.")
            additions = []
            for item in action.items:
                value = item.model_dump()
                if not item.source_ref and not item.drive_url:
                    raise DomainError("Informe um link ou referência de origem.")
                additions.append({"item_id": uid(), **value})
            items.extend(additions)
        elif action.action == "rename":
            item = next((i for i in items if i["item_id"] == action.item_id), None)
            if not item:
                raise DomainError("Item não encontrado na fila atual.")
            item["folder_label"] = label(action.name)
        elif action.action == "remove":
            index = next((n for n, i in enumerate(items) if i["item_id"] == action.item_id), None)
            if index is None:
                raise DomainError("Item não encontrado na fila atual.")
            state["removed"] = {"index": index, "item": items.pop(index)}
        elif action.action == "undo":
            removed = state["removed"]
            if not removed:
                raise DomainError("Não há remoção para desfazer.")
            if len(items) >= 100:
                raise DomainError("A fila já contém 100 itens.")
            items.insert(min(removed["index"], len(items)), removed["item"])
            state["removed"] = None
        elif action.action == "reorder":
            if len(action.order) != len(items) or set(action.order) != {i["item_id"] for i in items}:
                raise DomainError("Informe todos os IDs atuais, uma única vez.")
            indexed = {i["item_id"]: i for i in items}
            state["items"] = [indexed[key] for key in action.order]
        elif action.action == "clear":
            state = {"items": [], "removed": None}
        labels = [i["folder_label"].casefold() for i in state["items"] if i.get("folder_label")]
        if len(set(labels)) != len(labels):
            raise DomainError("Existem nomes de destino repetidos na fila.")
        return self.store.put("queue", conversation, state)

    def import_text(self, conversation, text):
        parsed = []
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            name, url = line.split("|", 1) if "|" in line else (None, line)
            try:
                parse_drive_url(url.strip())
                parsed.append(ItemInput(drive_url=url.strip(), folder_label=name.strip() if name else None))
            except (DomainError, ValueError) as error:
                raise DomainError(f"Linha {number}: {error}") from None
        if not parsed:
            raise DomainError("Nenhum link encontrado.")
        return self.change(conversation, QueueAction(action="add", items=parsed))
