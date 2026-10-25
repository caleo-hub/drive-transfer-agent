"""Scoped filesystem capabilities, backed by structured rclone results."""

from pathlib import Path

from .safety import DomainError, relative_path


class StorageTools:
    def __init__(self, executor, planner):
        self.executor, self.planner = executor, planner

    def target(self, destination_id, path=""):
        dest = self.executor.store.get("destination", destination_id)
        if not dest:
            raise DomainError("Destino desconhecido. Localize ou cadastre a pasta base.")
        path = relative_path(path) if path else ""
        if dest["kind"] == "mega":
            target = "mega:" + "/".join(filter(None, [dest["path"], path]))
        else:
            base = Path(dest["path"]).resolve()
            resolved = (base / path).resolve()
            if not resolved.is_relative_to(base):
                raise DomainError("O caminho deve permanecer dentro do destino cadastrado.")
            target = str(resolved)
        return dest, target

    async def list_entries(self, destination_id, path="", offset=0, limit=100):
        if offset < 0 or not 1 <= limit <= 500:
            raise DomainError("Use offset não negativo e limite de 1 a 500.")
        _, target = self.target(destination_id, path)
        async with self.executor.maintenance:
            self.executor.idle()
            entries = await self.executor.rclone.json(
                ["lsjson", target, "--max-depth", "1", "--retries", "1"], timeout=90
            )
        if not isinstance(entries, list):
            raise DomainError("A listagem não retornou um inventário válido.")
        entries.sort(key=lambda e: (not bool(e.get("IsDir")), e["Name"].casefold()))
        page = [
            {
                "name": e["Name"],
                "kind": "folder" if e.get("IsDir") else "file",
                "id": e.get("ID"),
                "bytes": e.get("Size") if e.get("Size", -1) >= 0 else None,
            }
            for e in entries[offset : offset + limit]
        ]
        more = offset + len(page) < len(entries)
        return {
            "target": target,
            "entries": page,
            "total_entries": len(entries),
            "complete": not more,
            "next_offset": offset + len(page) if more else None,
        }

    async def usage(self, destination_id, path=""):
        _, target = self.target(destination_id, path)
        async with self.executor.maintenance:
            self.executor.idle()
            data = await self.executor.rclone.json(["size", target, "--json", "--retries", "1"], timeout=90)
        if not isinstance(data, dict) or "count" not in data or "bytes" not in data:
            raise DomainError("Não foi possível obter uma medição válida do destino.")
        return {"target": target, "count": data["count"], "bytes": data["bytes"], "copied": False}

    async def mkdir(self, conversation, destination_id, path):
        if self.executor.store.get("intent", conversation, {}).get("destination_must_exist"):
            raise DomainError("O usuário pediu uma pasta existente. Localize-a; não crie outra pasta.")
        if not path:
            raise DomainError("Informe uma subpasta dentro do destino cadastrado.")
        _, target = self.target(destination_id, path)
        async with self.executor.maintenance:
            self.executor.idle()
            code, _, _ = await self.executor.rclone.run(["mkdir", target, "--retries", "1"], timeout=90)
            if code:
                raise DomainError("Não foi possível criar a pasta. Confira o destino e as permissões.")
            stat = await self.executor.rclone.json(["lsjson", target, "--stat", "--retries", "1"], timeout=90)
        if not isinstance(stat, dict) or not stat.get("IsDir"):
            raise DomainError("A criação não foi confirmada como pasta.")
        return {"created": True, "target": target}

    async def search_source(self, parent_ref, query, recursive=False, limit=50):
        if not query.strip() or not 1 <= limit <= 100:
            raise DomainError("Informe texto para busca e um limite de 1 a 100 resultados.")
        pending, seen, matches, pages = [(parent_ref, 0, "")], set(), [], 0
        while pending and pages < 20:
            ref, depth, token = pending.pop(0)
            marker = (ref, token)
            if marker in seen:
                raise DomainError("Paginação repetida durante a busca.")
            seen.add(marker)
            page = await self.planner.browse(ref, token, 1000)
            pages += 1
            for entry in page["entries"]:
                if query.casefold() in entry["name"].casefold():
                    matches.append({**entry, "parent_ref": ref})
                    if len(matches) == limit:
                        return {
                            "entries": matches,
                            "complete": False,
                            "reason": "Limite de resultados atingido.",
                        }
                if recursive and entry["kind"] == "folder":
                    if depth >= 3:
                        return {
                            "entries": matches,
                            "complete": False,
                            "reason": "Profundidade máxima atingida.",
                        }
                    pending.append((entry["source_ref"], depth + 1, ""))
            if page["next_page_token"]:
                pending.insert(0, (ref, depth, page["next_page_token"]))
        return {
            "entries": matches,
            "complete": not pending,
            "reason": "Busca concluída." if not pending else "Limite de páginas atingido.",
        }
