import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import aiosqlite
import orjson

from domain.contracts import DeviceRegistry
from domain.entities.device import Device, Localizacao

_COLS = "id, name, status, allowed_tools, created_at, last_seen, plataforma, permissoes, estado, estado_em"

# colunas que entraram depois (P2): o banco antigo ganha cada uma com ALTER TABLE na subida, sem perder nada
_NOVAS = {"plataforma": "TEXT DEFAULT ''", "permissoes": "TEXT DEFAULT '{}'", "estado": "TEXT DEFAULT '{}'",
          "estado_em": "REAL"}


def _row_to_device(row) -> Device:
    """Converte uma row do SQLite para Device entity."""
    return Device(
        id=row[0],
        name=row[1],
        status=row[2],
        allowed_tools=orjson.loads(row[3] or "[]"),
        created_at=row[4],
        last_seen=row[5],
        plataforma=row[6] or "",
        permissoes=orjson.loads(row[7] or "{}"),
        estado=orjson.loads(row[8] or "{}"),
        estado_em=row[9],
    )


def _row_to_loc(row) -> Localizacao:
    return Localizacao(device_id=row[0], lat=row[1], lon=row[2], quando=row[3], precisao_m=row[4],
                       fonte=row[5] or "", origem=row[6] or "")


class SqlLiteDeviceRegistry(DeviceRegistry):
    """Persistência de devices em SQLite — registry real (não mock)."""

    def __init__(self, db_path: str):
        self._db_path: str = db_path

    @asynccontextmanager
    async def _connect(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA journal_mode = WAL")
            await db.execute("PRAGMA foreign_keys = ON")
            yield db

    async def init(self) -> None:
        async with self._connect() as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    allowed_tools TEXT DEFAULT '[]',
                    created_at REAL,
                    last_seen REAL
                )
                """
            )
            existentes = {r[1] for r in await db.execute_fetchall("PRAGMA table_info(devices)")}
            for col, tipo in _NOVAS.items():
                if col not in existentes:
                    await db.execute(f"ALTER TABLE devices ADD COLUMN {col} {tipo}")
            # histórico de posições (o dono decidiu guardar o histórico, não só a última)
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS localizacoes (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id   TEXT NOT NULL,
                    lat         REAL NOT NULL,
                    lon         REAL NOT NULL,
                    quando      REAL NOT NULL,       -- quando o device LEU
                    precisao_m  REAL,
                    fonte       TEXT,
                    origem      TEXT,
                    recebido_em REAL NOT NULL,       -- quando chegou aqui (a fila pode entregar horas depois)
                    UNIQUE(device_id, quando)        -- reenvio da fila (ack perdido) não duplica
                )
                """
            )
            await db.execute("CREATE INDEX IF NOT EXISTS ix_loc_dev ON localizacoes(device_id, quando DESC)")
            await db.commit()

    async def get(self, device_id: str) -> Device | None:
        async with self._connect() as db:
            cursor = await db.execute(f"SELECT {_COLS} FROM devices WHERE id = ?", (device_id,))
            row = await cursor.fetchone()
            return _row_to_device(row) if row else None

    async def upsert(self, device: Device) -> None:
        async with self._connect() as db:
            await db.execute(
                f"INSERT OR REPLACE INTO devices ({_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    device.id,
                    device.name,
                    device.status,
                    orjson.dumps(device.allowed_tools).decode(),
                    device.created_at,
                    device.last_seen,
                    device.plataforma,
                    orjson.dumps(device.permissoes).decode(),
                    orjson.dumps(device.estado).decode(),
                    device.estado_em,
                ),
            )
            await db.commit()

    async def list_all(self) -> list[Device]:
        async with self._connect() as db:
            rows = await db.execute_fetchall(f"SELECT {_COLS} FROM devices")
            return [_row_to_device(r) for r in rows]

    async def set_status(self, device_id: str, status: str) -> None:
        async with self._connect() as db:
            await db.execute("UPDATE devices SET status = ? WHERE id = ?", (status, device_id))
            await db.commit()

    # ── localização ────────────────────────────────────────────────────────────────────────────────────
    async def salvar_localizacoes(self, pontos: list[Localizacao]) -> int:
        """Grava as leituras (ignora as que já existem). Devolve quantas eram novas."""
        agora = time.time()
        async with self._connect() as db:
            antes = db.total_changes
            await db.executemany(
                "INSERT OR IGNORE INTO localizacoes(device_id, lat, lon, quando, precisao_m, fonte, origem, recebido_em)"
                " VALUES (?,?,?,?,?,?,?,?)",
                [(p.device_id, p.lat, p.lon, p.quando, p.precisao_m, p.fonte, p.origem, agora) for p in pontos],
            )
            novas = db.total_changes - antes
            await db.commit()
            return novas

    async def localizacoes(self, device_id: str, desde: float | None = None, limite: int = 500) -> list[Localizacao]:
        """Mais recentes primeiro."""
        async with self._connect() as db:
            rows = await db.execute_fetchall(
                "SELECT device_id, lat, lon, quando, precisao_m, fonte, origem FROM localizacoes"
                " WHERE device_id = ? AND quando >= ? ORDER BY quando DESC LIMIT ?",
                (device_id, desde or 0, limite),
            )
            return [_row_to_loc(r) for r in rows]

    async def ultima_localizacao(self, device_id: str) -> Localizacao | None:
        r = await self.localizacoes(device_id, limite=1)
        return r[0] if r else None
