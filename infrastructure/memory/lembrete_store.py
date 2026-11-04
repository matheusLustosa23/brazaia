# infrastructure/memory/lembrete_store.py — lembretes (data/cerebro.db, tabela própria).
import time
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

import aiosqlite

from application.services.lembretes import Lembrete

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lembretes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    texto            TEXT    NOT NULL,
    proximo          REAL    NOT NULL,
    repetir          TEXT    NOT NULL DEFAULT '',
    antecedencia_min INTEGER NOT NULL DEFAULT 0,
    dia              INTEGER,
    ativo            INTEGER NOT NULL DEFAULT 1,
    avisado_para     REAL,
    fonte            TEXT    NOT NULL DEFAULT '',
    criado_em        REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_lembretes_ativo ON lembretes(ativo, proximo);
"""
_COLS = "id, texto, proximo, repetir, antecedencia_min, dia, ativo, avisado_para"


def _row(r) -> Lembrete:
    return Lembrete(id=r[0], texto=r[1], proximo=r[2], repetir=r[3], antecedencia_min=r[4], dia=r[5],
                    ativo=bool(r[6]), avisado_para=r[7])


class SqliteLembreteStore:
    def __init__(self, path: str) -> None:
        self._path = path

    @asynccontextmanager
    async def _db(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        async with aiosqlite.connect(self._path, timeout=10) as db:
            yield db

    async def init(self) -> None:
        async with self._db() as db:
            await db.executescript(_SCHEMA)
            await db.commit()

    async def criar(self, texto: str, proximo: float, repetir: str = "", antecedencia_min: int = 0,
                    dia: int | None = None, fonte: str = "") -> Lembrete:
        async with self._db() as db:
            cur = await db.execute(
                "INSERT INTO lembretes(texto, proximo, repetir, antecedencia_min, dia, fonte, criado_em) "
                "VALUES (?,?,?,?,?,?,?)", (texto, proximo, repetir, antecedencia_min, dia, fonte, time.time()))
            await db.commit()
            return Lembrete(id=cur.lastrowid, texto=texto, proximo=proximo, repetir=repetir,
                            antecedencia_min=antecedencia_min, dia=dia)

    async def ativos(self) -> list[Lembrete]:
        async with self._db() as db:
            rows = await db.execute_fetchall(f"SELECT {_COLS} FROM lembretes WHERE ativo = 1 ORDER BY proximo")
        return [_row(r) for r in rows]

    async def pegar(self, lid: int) -> Lembrete | None:
        async with self._db() as db:
            rows = await db.execute_fetchall(f"SELECT {_COLS} FROM lembretes WHERE id = ?", (lid,))
        return _row(rows[0]) if rows else None

    async def _set(self, sql: str, args: tuple) -> bool:
        async with self._db() as db:
            cur = await db.execute(sql, args)
            await db.commit()
            return cur.rowcount > 0

    async def marcar_avisado(self, lid: int, proximo: float) -> None:
        await self._set("UPDATE lembretes SET avisado_para = ? WHERE id = ?", (proximo, lid))

    async def mover(self, lid: int, proximo: float) -> None:
        await self._set("UPDATE lembretes SET proximo = ? WHERE id = ?", (proximo, lid))

    async def desativar(self, lid: int) -> bool:
        return await self._set("UPDATE lembretes SET ativo = 0 WHERE id = ? AND ativo = 1", (lid,))
