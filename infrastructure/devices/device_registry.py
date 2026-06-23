import aiosqlite, orjson
from domain.entities.device import Device
from domain.contracts import DeviceRegistry
from contextlib import  asynccontextmanager
from typing import AsyncGenerator

def _row_to_device(row: aiosqlite.Row) -> Device:
    """Converte uma row do SQLite para Device entity."""
    return Device(
        id=row[0],
        name=row[1],
        status=row[2],
        allowed_tools=orjson.loads(row[3]),
        created_at=row[4],
        last_seen=row[5],
    )

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
            await db.commit()
    
    async def get(self, device_id: str) -> Device | None:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT id, name, status, allowed_tools, created_at, last_seen "
                "FROM devices WHERE id = ?", (device_id,)
            ) 
            row = await cursor.fetchone()
            if row is  None:
                return None
            return _row_to_device(row)
    
    async def upsert(self, device: Device) -> None:
        async with self._connect() as db:
            await db.execute(
            "INSERT OR REPLACE INTO devices (id, name, status, allowed_tools, created_at, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                device.id, 
                device.name, 
                device.status,
                orjson.dumps(device.allowed_tools).decode(),
                device.created_at, 
                device.last_seen)
            )
            await db.commit()
    
    async def list_all(self) -> list[Device]:
        async with self._connect() as db:
            cursor = await db.execute( "SELECT id, name, status, allowed_tools, created_at, last_seen FROM devices")
            rows = await cursor.fetchall()
            return [
                _row_to_device(r)
                for r in rows
            ]
    
    async def set_status(self, device_id: str, status: str) -> None:
       async with self._connect() as db:
            await db.execute(
                "UPDATE devices SET status = ? WHERE id = ?", (status, device_id)
            )
            await db.commit()
            
        
    