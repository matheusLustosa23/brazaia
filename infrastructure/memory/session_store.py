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
"""

class InMemorySessionStore:
    
    def __init__(self):
        self._data: dict[str,list[dict]] = {}
    
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
            await db.execute(
                "INSERT OR REPLACE INTO sessions (session_id, history, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (session_id, orjson.dumps(history).decode(), now, now),
            )
            await db.commit()
       

    async def append(self, session_id: str, message: dict) -> None:
        history = await self.get(session_id)
        history.append(message)
        await self.set(session_id,history)