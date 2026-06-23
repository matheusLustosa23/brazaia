from domain.entities.device import Device
from domain.contracts import DeviceRegistry
from domain.tools.base import ToolRegistry
import time

class DeviceService:
    """Application service — lógica de negócio de devices.
    Separa WebSocket (transporte) de regras de negócio."""
    
    def __init__(self, registry: DeviceRegistry, tools: ToolRegistry):
        self._registry = registry
        self._tools = tools
    
    async def register_device(self, device_id: str, name: str) -> Device:
        """Registra um device novo (ou retorna existente)."""
        existing = await self._registry.get(device_id)
        if existing:
            return existing
        device =  Device(id=device_id, name=name, status="pending")
        await self._registry.upsert(device)
        return device
    
    async def activate_device(self, device_id: str, allowed_tools: list[str]) -> Device:
        """Ativa device com tools permitidas validadas."""
        device = await self._registry.get(device_id)
        if device is None:
            raise ValueError(f"device '{device_id}' não registrado")
        
        for tool_name in allowed_tools:
            if tool_name not in self._tools:
                raise ValueError(f"tool '{tool_name}' não existe no registry")

        device.allowed_tools = allowed_tools
        device.activate()
        await self._registry.upsert(device)
        return device
    
    async def get_device(self, device_id: str) -> Device | None:
        return await self._registry.get(device_id)
    
    async def update_heartbeat(self, device_id: str) -> None:
        """Atualiza last_seen do device."""
        device = await self.get_device(device_id)
        if device:
            device.last_seen = time.time()
            await self._registry.upsert(device)
    
    async def revoke_device(self, device_id: str) -> None:
        await self._registry.set_status(device_id, "revoked")
    
    async def get_allowed_tools(self, device_id: str) -> set[str]:
        """Retorna tools permitidas para o device."""
        device = await self.get_device(device_id)
        if device is None or device.status != "active":
            return set()
        return set(device.allowed_tools)
    
    async def list_active_devices(self) -> list[Device]:
        devices = await self._registry.list_all()
        return [d for d in devices if d.status == "active"]
        