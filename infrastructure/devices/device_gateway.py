import asyncio, orjson
from pydantic import BaseModel

from domain.tools.base import Tool
from infrastructure.devices.device_connection import DeviceConnectionManager
from infrastructure.devices.device_rpc import DeviceRPCManager
from application.services.device_service import DeviceService


class DeviceGateway:
    """Facade: Expõe uma interface limpa unificada sem misturar lógicas de transporte e concorrência."""
    def __init__(
        self,
        conn_manager: DeviceConnectionManager,
        rpc_manager: DeviceRPCManager,
        device_service: DeviceService
    ):
        self.connections = conn_manager
        self.rpc = rpc_manager
        self.service = device_service
    
    async def request(self, device_id: str | None, name: str, arguments: dict) -> str:
        if not device_id:
            return "[erro] device_id não fornecido"
        ws = self.connections.get(device_id)
        if not ws:
            return f"[erro] device '{device_id}' offline"
        request_id, future = self.rpc.create_request()
        action = {"request_id": request_id, "name": name, "arguments": arguments}
        try:
            await ws.send_text(orjson.dumps(action).decode())
            return await asyncio.wait_for(future, timeout=self.rpc._timeout)
        except asyncio.TimeoutError:
            return f"[timeout] device '{device_id}' excedeu {self.rpc.timeout}s"
        finally:
            self.rpc.cancel_request(request_id)
        
    async def dispatch(self, device_id, tool, payload):         
        return await self.request(device_id, tool.name, payload.model_dump())
    
    async def capabilities(self, device_id: str | None) -> set[str] | None:
        """Retorna tools permitidas para o device."""
        if not device_id:
            return None
        return await self.service.get_allowed_tools(device_id)
        