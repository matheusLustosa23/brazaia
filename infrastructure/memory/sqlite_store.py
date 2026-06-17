import time
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

import aiosqlite

from domain.entities.memory_fact import MemoryFact

_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS facts (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    category             TEXT    NOT NULL,
    key                  TEXT,
    content              TEXT    NOT NULL,
    source               TEXT    NOT NULL DEFAULT 'agent_detection',
    confidence           REAL    NOT NULL DEFAULT 1.0,
    access_count         INTEGER NOT NULL DEFAULT 0,
    reinforcement_count  INTEGER NOT NULL DEFAULT 0,
    contradiction_count  INTEGER NOT NULL DEFAULT 0,
    retrieval_score_last REAL,
    last_accessed_at     REAL,
    valid_at             REAL    NOT NULL,
    invalid_at           REAL,
    created_at           REAL    NOT NULL,
    updated_at           REAL    NOT NULL,
    UNIQUE(category, key)
);
CREATE INDEX IF NOT EXISTS idx_facts_category ON facts(category);
CREATE INDEX IF NOT EXISTS idx_facts_active   ON facts(invalid_at) WHERE invalid_at IS NULL;

CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
    content,
    content='facts',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS fts_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS fts_au AFTER UPDATE OF content ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, content) VALUES('delete', old.id, old.content);
    INSERT INTO facts_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS fts_ad AFTER DELETE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, content) VALUES('delete', old.id, old.content);
END;

CREATE TABLE IF NOT EXISTS fact_links (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id             INTEGER NOT NULL REFERENCES facts(id),
    to_id               INTEGER NOT NULL REFERENCES facts(id),
    relation            TEXT    NOT NULL,
    strength            REAL    NOT NULL DEFAULT 1.0,
    origin              TEXT    NOT NULL DEFAULT 'inferred',
    co_activation_count INTEGER NOT NULL DEFAULT 0,
    valid_at            REAL    NOT NULL,
    invalid_at          REAL,
    UNIQUE(from_id, to_id, relation)
);

CREATE TABLE IF NOT EXISTS memory_ops_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_id    INTEGER NOT NULL,
    operation  TEXT    NOT NULL CHECK(operation IN ('ADD','UPDATE','NOOP','DELETE')),
    reason     TEXT,
    created_at REAL    NOT NULL
);
"""

_FACT_COLS = (
    "id", "category", "key", "content", "source", "confidence",
    "access_count", "reinforcement_count", "contradiction_count",
    "retrieval_score_last", "last_accessed_at",
    "valid_at", "invalid_at", "created_at", "updated_at",
)

_FACT_SELECT = ", ".join(f"f.{c}" for c in _FACT_COLS)

def _row_to_fact(row: aiosqlite.Row) -> MemoryFact:
    d = dict(row)
    d.pop("bm25_rank",None)
    return MemoryFact(**d)

class SqlLiteMemoryStore:
    def __init__(self, db_path: str) -> None:
        self._path = db_path
    
    @asynccontextmanager
    async def _connect(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        async with aiosqlite.connect(self._path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            yield db
    
    async def init(self) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()
        
    async def upsert_fact(self, fact: MemoryFact) -> tuple[int, str]:
        now = time.time()
        async with self._connect() as db:
            
            row = None
            if fact.key is not None:
                cursor = await db.execute(
                    "SELECT id, content FROM facts WHERE category=? AND key=? AND invalid_at IS NULL",
                    (fact.category,fact.key)
                )
                row = await cursor.fetchone()

            if row is None:
                cur = await db.execute(
                       """INSERT INTO facts
                       (category, key, content, source, confidence, valid_at, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (fact.category, fact.key, fact.content,
                     fact.source, fact.confidence, now, now, now)
                )
                if cur.lastrowid is None:
                    raise RuntimeError("INSERT em facts não retornou lastrowid")
                fact_id = cur.lastrowid
                op = "ADD"
            elif row[1] == fact.content:
                fact_id = row[0]
                op = "NOOP"
            else:
                fact_id = row[0]
                await db.execute(
                    "UPDATE facts SET content=?, confidence=?, updated_at=? WHERE id=?",
                    (fact.content, fact.confidence, now, fact_id)
                )
                op = "UPDATE"
                
            await db.execute(
                "INSERT INTO memory_ops_log (fact_id, operation, reason, created_at) VALUES (?,?,?,?)",
                (fact_id, op, fact.source, now),
            )
            await db.commit()
        return fact_id, op

    async def forget(self, fact_id: int) -> None:
        now = time.time()
        async with self._connect() as db:
            await db.execute(
                "UPDATE facts SET invalid_at=? WHERE id=? AND invalid_at IS NULL",
                (now, fact_id),
            )
            await db.execute(
                "INSERT INTO memory_ops_log (fact_id, operation, reason, created_at) VALUES (?,?,?,?)",
                (fact_id, "DELETE", "soft_delete", now),
            )
            await db.commit()
        
    async def by_category(self, category: str) -> list[MemoryFact]:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                f"SELECT {_FACT_SELECT} FROM facts f"
                " WHERE f.category=? AND f.invalid_at IS NULL"
                " ORDER BY f.updated_at DESC",
                (category,),
            )
            return [_row_to_fact(r) for r in rows]
    
    async def search(self, query: str, limit: int = 10) -> list[MemoryFact]:
        if not query.split():
            return []
        now = time.time()
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                 f"""SELECT {_FACT_SELECT}, bm25(facts_fts) AS bm25_rank
                    FROM facts_fts
                    JOIN facts f ON f.id = facts_fts.rowid
                    WHERE facts_fts MATCH ? AND f.invalid_at IS NULL
                    ORDER BY bm25_rank
                    LIMIT ?""",
                (query, limit),
            )
            if rows:
                ids = [r["id"] for r in rows]
                placeholders = ",".join("?" * len(ids))
                await db.execute(
                    f"UPDATE facts SET access_count=access_count+1, last_accessed_at=?"
                    f" WHERE id IN ({placeholders})",
                    [now, *ids],
                )
                await db.commit()
            return [_row_to_fact(r) for r in rows]
    
    async def link(
        self,
        from_id: int,
        to_id: int,
        relation: str,
        strength: float = 1.0,
        origin: str = "inferred"
    ) -> None:
        now = time.time()
        async with self._connect() as db:
            await db.execute(
                """INSERT INTO fact_links (from_id, to_id, relation, strength, origin, valid_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(from_id, to_id, relation) DO UPDATE SET
                     strength=excluded.strength,
                     co_activation_count=co_activation_count+1""",
                (from_id, to_id, relation, strength, origin, now),
            )
            await db.commit()