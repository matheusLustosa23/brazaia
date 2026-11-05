import orjson
from fastapi import WebSocket

from application.services.device_service import DeviceService
from infrastructure.devices.device_gateway import DeviceGateway

class DeviceHandshakeService:
    """Application Service focado: Isola o workflow sequencial de entrada do device."""
    def __init__(
        self,
        device_service: DeviceService,
        gateway: DeviceGateway
    ) -> None:
        self._service = device_service
        self._gateway = gateway
        
    async def execute(
        self,
        ws: WebSocket,
        device_id: str,
        all_tool_names: list[str]
    ) -> dict:
        """Executa a rotina estruturada de conexão, registro e autorização inicial."""
        msg = await ws.receive_text()
        data = orjson.loads(msg)
        device_name = data.get("name", device_id)
        handlers = data.get("handlers") or all_tool_names
        await self._service.register_device(device_id, device_name)
        device = await self._service.activate_device(device_id, handlers)
        # P2: o que este device é e o que o dono permitiu nele (câmera, mic, localização…) + bateria
        await self._service.atualizar_meta(device_id, data.get("plataforma"), data.get("permissoes"),
                                           data.get("estado"))
        self._gateway.connections.register(device_id, ws)
        
        welcome = {
            "type": "welcome",
            "device_id": device_id,
            "tools": device.allowed_tools,
        }
        try:                                              # versão do pacote → o device se atualiza sozinho
            import asyncio
            from infrastructure import companion_pacote
            welcome["companion"] = await asyncio.to_thread(companion_pacote.info)
        except Exception:                                 # pacote não monta = só não avisa (não derruba a conexão)
            pass
        await ws.send_text(orjson.dumps(welcome).decode())
        return data
        