import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .safety import DomainError, redact

FINAL = {"success", "failed", "attention", "cancelled", "interrupted"}


def uid():
    return uuid.uuid4().hex


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS documents(kind TEXT, id TEXT, body TEXT NOT NULL,
                    PRIMARY KEY(kind,id));
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, idem TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL, body TEXT NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_job ON jobs((1))
                    WHERE status IN ('pending','running');
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL, body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS events_by_job ON events(job_id,seq);
                CREATE TABLE IF NOT EXISTS claims(target TEXT PRIMARY KEY, source TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY, conversation_id TEXT,
                    request_id TEXT, role TEXT, body TEXT, created REAL,
                    UNIQUE(conversation_id, request_id, role));
            """)

    @contextmanager
    def connect(self):
        with self.lock:
            db = sqlite3.connect(self.path, timeout=15)
            db.row_factory = sqlite3.Row
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    def get(self, kind, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT body FROM documents WHERE kind=? AND id=?", (kind, key)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, kind, key, body):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO documents VALUES(?,?,?)", (kind, key, json.dumps(body)))
        return body

    def list(self, kind):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT body FROM documents WHERE kind=?", (kind,))]

    def delete(self, kind, key):
        with self.connect() as db:
            db.execute("DELETE FROM documents WHERE kind=? AND id=?", (kind, key))

    def delete_conversation(self, conversation):
        with self.connect() as db:
            db.execute("DELETE FROM messages WHERE conversation_id=?", (conversation,))
            db.execute(
                "DELETE FROM documents WHERE kind IN ('conversation','queue') AND id=?", (conversation,)
            )

    def active(self):
        with self.connect() as db:
            row = db.execute("SELECT body FROM jobs WHERE status IN ('pending','running')").fetchone()
        return json.loads(row[0]) if row else None

    def create_job(self, idem, spec):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT body FROM jobs WHERE idem=?", (idem,)).fetchone()
            if old:
                body = json.loads(old[0])
                if body["spec"] != spec:
                    raise DomainError("Esta chave de idempotência já foi usada para outro pedido.", 409)
                return body, False
            active = db.execute("SELECT id FROM jobs WHERE status IN ('pending','running')").fetchone()
            if active:
                raise DomainError("Já existe uma tarefa ativa.", 409, {"job_id": active[0]})
            body = {
                "id": uid(),
                "status": "pending",
                "spec": spec,
                "created_at": time.time(),
                "updated_at": time.time(),
                "revision": 0,
                "items": [],
                "current": 0,
                "stage": "pending",
                "message": "Tarefa preparada.",
                "stats": {},
                "cancel_requested": False,
            }
            db.execute(
                "INSERT INTO jobs VALUES(?,?,?,?)", (body["id"], idem, body["status"], json.dumps(body))
            )
        return body, True

    def job(self, key):
        with self.connect() as db:
            row = db.execute("SELECT body FROM jobs WHERE id=?", (key,)).fetchone()
        if not row:
            raise DomainError("Tarefa não encontrada.", 404)
        return json.loads(row[0])

    def jobs(self):
        with self.connect() as db:
            rows = db.execute("SELECT body FROM jobs ORDER BY rowid DESC LIMIT 100").fetchall()
        return [json.loads(r[0]) for r in rows]

    def update_job(self, key, **changes):
        with self.connect() as db:
            body = json.loads(db.execute("SELECT body FROM jobs WHERE id=?", (key,)).fetchone()[0])
            body.update(changes)
            body["updated_at"] = time.time()
            body["revision"] += 1
            db.execute("UPDATE jobs SET status=?,body=? WHERE id=?", (body["status"], json.dumps(body), key))
            summary = {
                k: body[k]
                for k in ("id", "status", "stage", "current", "message", "revision", "updated_at", "stats")
            }
            db.execute("INSERT INTO events(job_id,body) VALUES(?,?)", (key, json.dumps(redact(summary))))
            if body["revision"] % 60 == 0:
                db.execute(
                    "DELETE FROM events WHERE job_id=? AND seq NOT IN "
                    "(SELECT seq FROM events WHERE job_id=? ORDER BY seq DESC LIMIT 5000)",
                    (key, key),
                )
        return body

    def reconcile(self):
        for job in self.jobs():
            if job["status"] not in FINAL:
                self.update_job(
                    job["id"],
                    status="interrupted",
                    stage="done",
                    message="Executor reiniciado. Revise a tarefa e solicite uma nova tentativa.",
                )

    def claim(self, target, source):
        with self.connect() as db:
            row = db.execute("SELECT source FROM claims WHERE target=?", (target.casefold(),)).fetchone()
            if row and row[0] != source:
                raise DomainError("Este destino já está associado a outra origem. Escolha outro nome.")
            db.execute("INSERT OR IGNORE INTO claims VALUES(?,?)", (target.casefold(), source))

    def add_message(self, conversation, request, role, text, **extra):
        body = redact({"id": uid(), "role": role, "text": text, "created_at": time.time(), **extra})
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO messages VALUES(?,?,?,?,?,?)",
                (body["id"], conversation, request, role, json.dumps(body), body["created_at"]),
            )
        return body

    def messages(self, conversation):
        with self.connect() as db:
            return [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT body FROM messages WHERE conversation_id=? ORDER BY created", (conversation,)
                )
            ]

    def reply(self, conversation, request):
        with self.connect() as db:
            row = db.execute(
                "SELECT body FROM messages WHERE conversation_id=? AND request_id=? AND role='assistant'",
                (conversation, request),
            ).fetchone()
        return json.loads(row[0]) if row else None
