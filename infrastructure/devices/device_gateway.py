import asyncio, dataclasses, time, orjson
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
    
    async def listar_status(self) -> list[dict]:
        """Todos os devices já registrados: conectado agora (e desde quando) e a última vez visto.
        Conectados primeiro; depois do visto mais recente pro mais antigo."""
        itens = []
        for d in await self.service.list_all_devices():
            desde = self.connections.desde(d.id)
            loc = await self.service.ultima_localizacao(d.id)
            itens.append({"id": d.id, "nome": d.name, "status": d.status, "conectado": desde is not None,
                          "conectado_desde": desde, "ultima_vez": d.last_seen, "registrado_em": d.created_at,
                          "tools": sorted(d.allowed_tools), "plataforma": d.plataforma,
                          "permissoes": d.permissoes, "estado": d.estado, "estado_em": d.estado_em,
                          "localizacao": dataclasses.asdict(loc) if loc else None})
        itens.sort(key=lambda x: (not x["conectado"], -(x["ultima_vez"] or 0)))
        return itens

    async def request(self, device_id: str | None, name: str, arguments: dict, timeout: float | None = None) -> str:
        if not device_id:
            return "[erro] device_id não fornecido"
        ws = self.connections.get(device_id)
        if not ws:
            return f"[erro] device '{device_id}' offline"
        request_id, future = self.rpc.create_request()
        action = {"request_id": request_id, "name": name, "arguments": arguments}
        try:
            await ws.send_text(orjson.dumps(action).decode())
            return await asyncio.wait_for(future, timeout=timeout or self.rpc._timeout)
        except asyncio.TimeoutError:
            return f"[timeout] device '{device_id}' excedeu {timeout or self.rpc.timeout}s"
        finally:
            self.rpc.cancel_request(request_id)
        
    async def dispatch(self, device_id, tool, payload):         
        return await self.request(device_id, tool.name, payload.model_dump())
    
    async def capabilities(self, device_id: str | None) -> set[str] | None:
        """Retorna tools permitidas para o device."""
        if not device_id:
            return None
        return await self.service.get_allowed_tools(device_id)

    async def localizar(self, device_id: str) -> tuple[dict | None, str]:
        """Pede a posição AGORA ao device (handler get_location) e grava no histórico.
        Devolve (ponto, "") se leu; (None, motivo) se não — quem chama decide se cai na última conhecida."""
        if not self.connections.get(device_id):
            return None, f"device '{device_id}' offline"
        bruto = await self.request(device_id, "get_location", {}, timeout=45)   # GPS frio demora (20+12+6 s no pior caso)
        try:
            dados = orjson.loads(bruto) if isinstance(bruto, str) and bruto.startswith("{") else None
        except orjson.JSONDecodeError:
            dados = None
        if not isinstance(dados, dict) or "lat" not in dados:
            return None, str(bruto)[:200]
        dados.setdefault("quando", time.time())
        dados["origem"] = "pedido"
        await self.service.salvar_localizacoes(device_id, [dados], origem="pedido")
        return dados, ""

