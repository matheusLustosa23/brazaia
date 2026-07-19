from pydantic import BaseModel, Field
from domain.tools.base import Tool
from infrastructure.devices.device_gateway import DeviceGateway
from infrastructure.render.store import resolve_data_uri
from infrastructure.vision.image_index import ImageIndex


class NotifyInput(BaseModel):
    device: str = Field(description="Nome EXATO do device conectado.")
    title: str = Field(description="Título curto.")
    message: str = Field(default="", description="Mensagem. Unicode math ok (√ ² π ≤ →).")
    image_id: str | None = Field(
        default=None,
        description=("image_id de uma imagem já pronta nesta conversa (ex.: de 'render_math'). "
                     "Omita pra notificação só de texto. NÃO invente o id: use um que apareceu antes."))


class NotifyTool(Tool[NotifyInput]):
    name = "notify"
    description = (
        "Manda uma NOTIFICAÇÃO pra tela de um device conectado. Só texto: passe title/message. "
        "Com imagem: passe também o image_id (de qualquer origem — matemática, foto, arquivo)."
    )
    input_schema = NotifyInput
    side = "server"
    action_class = "reversible"

    def __init__(self, gateway: DeviceGateway, index: ImageIndex) -> None:
        self._gateway = gateway
        self._index = index    
        
    async def run(self, payload: NotifyInput) -> str:
        args:dict = {"title": payload.title, "message": payload.message}
        if payload.image_id:
            data_uri = resolve_data_uri(self._index, payload.image_id)
            if data_uri is None:
                return (f"[erro] image_id '{payload.image_id}' não existe mais — "
                        f"gere de novo (render_math) ou capture/referencie a imagem")
            args["image"] = data_uri
        return await self._gateway.request(payload.device, "notify", args)
    
    def openai_schema(self) -> dict:
        schema = super().openai_schema()
        devs = self._gateway.connections.names()
        device = schema["function"]["parameters"]["properties"]["device"]
        device["enum"] = devs
        device["description"] = f"Device que recebe. CONECTADOS: {devs}. Nome EXATO."
        return schema