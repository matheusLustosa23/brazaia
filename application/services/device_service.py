from domain.entities.device import Device, Localizacao
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
    
    async def activate_device(self, device_id: str, capabilities: list[str]) -> Device:
        """Ativa device com tools permitidas validadas."""
        device = await self._registry.get(device_id)
        if device is None:
            raise ValueError(f"device '{device_id}' não registrado")
    

        device.allowed_tools = capabilities
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
    
    async def list_all_devices(self) -> list[Device]:
        return await self._registry.list_all()

    async def list_active_devices(self) -> list[Device]:
        devices = await self._registry.list_all()
        return [d for d in devices if d.status == "active"]

    # ── P2: o que o device é/pode e onde está ──────────────────────────────────────────────────────────
    async def atualizar_meta(self, device_id: str, plataforma: str | None, permissoes: dict | None,
                             estado: dict | None) -> None:
        """Handshake: o companion diz a plataforma, as permissões que tem e (se souber) bateria."""
        device = await self.get_device(device_id)
        if device is None:
            return
        if plataforma:
            device.plataforma = plataforma
        if isinstance(permissoes, dict):
            device.permissoes = permissoes
        if isinstance(estado, dict) and estado:
            device.estado, device.estado_em = estado, time.time()
        await self._registry.upsert(device)

    async def atualizar_estado(self, device_id: str, estado: dict, quando: float | None = None) -> None:
        device = await self.get_device(device_id)
        if device is None or not isinstance(estado, dict):
            return
        device.estado, device.estado_em = estado, quando or time.time()
        await self._registry.upsert(device)

    async def salvar_localizacoes(self, device_id: str, pontos: list[dict], origem: str = "periodica") -> int:
        """Pontos vindos do device ({lat, lon, quando, precisao_m, fonte}). Descarta o que não é coordenada válida."""
        validos = []
        for p in pontos or []:
            try:
                lat, lon = float(p["lat"]), float(p["lon"])
                quando = float(p.get("quando") or time.time())
            except (KeyError, TypeError, ValueError):
                continue
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            prec = p.get("precisao_m")
            validos.append(Localizacao(device_id=device_id, lat=lat, lon=lon, quando=quando,
                                       precisao_m=float(prec) if isinstance(prec, (int, float)) else None,
                                       fonte=str(p.get("fonte") or ""), origem=str(p.get("origem") or origem)))
        return await self._registry.salvar_localizacoes(validos) if validos else 0

    async def localizacoes(self, device_id: str, desde: float | None = None, limite: int = 500) -> list[Localizacao]:
        return await self._registry.localizacoes(device_id, desde, limite)

    async def ultima_localizacao(self, device_id: str) -> Localizacao | None:
        return await self._registry.ultima_localizacao(device_id)

