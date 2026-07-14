from pydantic import BaseModel, Field
from domain.tools.base import Tool
from infrastructure.devices.device_gateway import DeviceGateway

class NotifyTextInput(BaseModel):
    device: str  = Field(description="Nome EXATO do device conectado (ex.: 'celular').")
    title: str   = Field(description="Título curto.")
    message: str = Field(description="Mensagem. Unicode math ok (√ ² π ≤ →).")

class NotifyTextTool(Tool[NotifyTextInput]):
    name = "notify_text"
    description = (
        "Envia NOTIFICAÇÃO DE TEXTO pra tela de um device conectado (ex.: o celular). "
        "Use pra mandar/avisar mensagem curta. Matemática formatada → prefira 'notify_image'."
    )
    input_schema = NotifyTextInput
    side = "server"
    action_class = "reversible"
    
    def __init__(self, gateway: DeviceGateway):
        self._gateway = gateway
    
    async def run(self, payload: NotifyTextInput) -> str:
        return await self._gateway.request(payload.device, "notify", {"title": payload.title, "message": payload.message})

    def openai_schema(self) -> dict:
        schema = super().openai_schema()
        devs = self._gateway.connections.names()
        device = schema["function"]["parameters"]["properties"]["device"]
        device["enum"] = devs
        device["description"] = f"Device que recebe. CONECTADOS: {devs}. Nome EXATO."
        return schema