import time
import uuid
import orjson
import aiosqlite
from typing import AsyncGenerator
from contextlib import asynccontextmanager

_SESSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    history    TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS session_narrative (
    session_id TEXT PRIMARY KEY,
    cards      TEXT NOT NULL DEFAULT '[]'
);
"""


_META_COLS = (("titulo", "titulo TEXT"), ("tags", "tags TEXT NOT NULL DEFAULT '[]'"),
              ("modo", "modo TEXT NOT NULL DEFAULT 'chat'"))


def _texto(content) -> str:
    """Texto de um content str ou multimodal (lista de partes)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _resumo(history: list[dict]) -> dict:
    """preview = 1ª fala do usuário numa linha · turnos = nº de falas do usuário (não de mensagens)."""
    users = [m for m in history if m.get("role") == "user"]
    preview = " ".join(_texto(users[0].get("content")).split())[:70] if users else "(sessão vazia)"
    return {"preview": preview, "turnos": len(users)}

class InMemorySessionStore:
    
    def __init__(self):
        self._data: dict[str,list[dict]] = {}
        self._narr: dict[str,list[dict]] = {}
        self._meta: dict[str,dict] = {}
    
    async def create(self) -> str:
        sid = uuid.uuid4().hex
        self._data[sid] = []
        return sid
    
    async def get(self, session_id: str) -> list[dict]:
        return self._data.setdefault(session_id, [])
    
    async def set(self, session_id: str, history: list[dict]) -> None:
        self._data[session_id] = history
    
    async def append(self, session_id: str, message: dict) -> None:
        self._data.setdefault(session_id, []).append(message)

    async def list_sessions(self) -> list[dict]:
        return [{"session_id": sid, **_resumo(h), **await self.get_meta(sid), "created_at": 0.0, "updated_at": 0.0}
                for sid, h in self._data.items()]

    async def get_meta(self, session_id: str) -> dict:
        return {"titulo": None, "tags": [], "modo": "chat", **self._meta.get(session_id, {})}

    async def set_meta(self, session_id: str, *, titulo: str | None = None, tags: list[str] | None = None,
                       modo: str | None = None) -> None:
        m = self._meta.setdefault(session_id, {})
        for k, v in (("titulo", titulo), ("tags", tags), ("modo", modo)):
            if v is not None:
                m[k] = v

    async def get_narrative(self, session_id: str) -> list[dict]:
        return self._narr.get(session_id, [])

    async def append_narrative(self, session_id: str, card: dict) -> None:
        self._narr.setdefault(session_id, []).append(card)
    

class SqlLiteSessionStore:
    
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        
    @asynccontextmanager
    async def _connect(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA journal_mode = WAL")
            await db.execute("PRAGMA foreign_keys = ON")
            yield db
    
    async def init(self) -> None:
        async with self._connect() as db:
            await db.executescript(_SESSION_SCHEMA)
            cols = {r[1] for r in await db.execute_fetchall("PRAGMA table_info(sessions)")}
            for col, ddl in _META_COLS:                     # bancos antigos: acrescenta as colunas de metadado
                if col not in cols:
                    await db.execute(f"ALTER TABLE sessions ADD COLUMN {ddl}")
            await db.commit()
       
    
    async def create(self) -> str:
        sid = uuid.uuid4().hex
        now = time.time()
        async with self._connect() as db:
            await db.execute(
                "INSERT INTO sessions (session_id, history, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (sid, "[]", now, now)
            )
            await db.commit()
        return sid
      

    async def get(self, session_id: str) -> list[dict]:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT history FROM sessions WHERE session_id = ?",
                (session_id,)
            )
            row = await cursor.fetchone()
        if row is None:
            return []
        return orjson.loads(row[0])
    
    async def set(self, session_id: str, history: list[dict]) -> None:
        now = time.time()
        async with self._connect() as db:
            await db.execute(                                   # upsert: preserva o created_at (o REPLACE zerava)
                "INSERT INTO sessions (session_id, history, created_at, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET history = excluded.history, updated_at = excluded.updated_at",
                (session_id, orjson.dumps(history).decode(), now, now),
            )
            await db.commit()
       

    async def append(self, session_id: str, message: dict) -> None:
        history = await self.get(session_id)
        history.append(message)
        await self.set(session_id,history)

    async def list_sessions(self) -> list[dict]:
        """Todas as sessões, da mais recente p/ a mais antiga (por updated_at)."""
        async with self._connect() as db:
            cur = await db.execute(
                "SELECT session_id, history, created_at, updated_at, titulo, tags, modo FROM sessions ORDER BY updated_at DESC"
            )
            rows = await cur.fetchall()
        return [{"session_id": sid, **_resumo(orjson.loads(h)), "created_at": c, "updated_at": u,
                 "titulo": t, "tags": orjson.loads(tg or "[]"), "modo": md or "chat"}
                for sid, h, c, u, t, tg, md in rows]

    async def get_meta(self, session_id: str) -> dict:
        """Metadados da sessão: titulo (nome dado na criação), tags (ex.: ["replica"]) e modo (chat|tutor)."""
        async with self._connect() as db:
            cur = await db.execute("SELECT titulo, tags, modo FROM sessions WHERE session_id = ?", (session_id,))
            row = await cur.fetchone()
        if row is None:
            return {"titulo": None, "tags": [], "modo": "chat"}
        return {"titulo": row[0], "tags": orjson.loads(row[1] or "[]"), "modo": row[2] or "chat"}

    async def set_meta(self, session_id: str, *, titulo: str | None = None, tags: list[str] | None = None,
                       modo: str | None = None) -> None:
        """Grava só o que veio (None = mantém). Cria a linha se a sessão ainda não existir."""
        now = time.time()
        campos = {k: v for k, v in (("titulo", titulo), ("tags", orjson.dumps(tags).decode() if tags is not None else None),
                                      ("modo", modo)) if v is not None}
        async with self._connect() as db:
            await db.execute("INSERT OR IGNORE INTO sessions (session_id, history, created_at, updated_at) VALUES (?, '[]', ?, ?)",
                             (session_id, now, now))
            if campos:
                sets = ", ".join(f"{k} = ?" for k in campos)
                await db.execute(f"UPDATE sessions SET {sets} WHERE session_id = ?", (*campos.values(), session_id))
            await db.commit()

    async def get_narrative(self, session_id: str) -> list[dict]:
        async with self._connect() as db:
            cur = await db.execute("SELECT cards FROM session_narrative WHERE session_id = ?", (session_id,))
            row = await cur.fetchone()
        return orjson.loads(row[0]) if row else []

    async def append_narrative(self, session_id: str, card: dict) -> None:
        cards = await self.get_narrative(session_id)
        cards.append(card)
        async with self._connect() as db:
            await db.execute(
                "INSERT OR REPLACE INTO session_narrative (session_id, cards) VALUES (?, ?)",
                (session_id, orjson.dumps(cards).decode()),
            )
            await db.commit()
