from pydantic import BaseModel, Field
from domain.tools.base import Tool
from infrastructure.devices.device_gateway import DeviceGateway
from infrastructure.render.store import resolve_data_uri
from infrastructure.vision.image_index import ImageIndex

class OpenImageInput(BaseModel):
    device: str = Field(description="Nome EXATO do device conectado.")
    image_id: str = Field(description="image_id de qualquer imagem pronta (gerada, capturada, referenciada).")


class OpenImageTool(Tool[OpenImageInput]):
    name = "open_image"
    description = (
        "Abre uma imagem em TELA CHEIA no visualizador do device (permite zoom). "
        "Use pra ler com calma; pra um aviso rápido prefira 'notify'."
    )
    input_schema = OpenImageInput
    side = "server"
    action_class = "reversible"

    def __init__(self, gateway: DeviceGateway, index: ImageIndex) -> None:
        self._gateway = gateway
        self._index = index
        
    async def run(self, payload: OpenImageInput) -> str:
        data_uri = resolve_data_uri(self._index, payload.image_id)
        if data_uri is None:
            return f"[erro] image_id '{payload.image_id}' não existe mais — gere/capture de novo"
        return await self._gateway.request(payload.device, "open_image", {"image": data_uri})

    def openai_schema(self) -> dict:
        schema = super().openai_schema()
        devs = self._gateway.connections.names()
        device = schema["function"]["parameters"]["properties"]["device"]
        device["enum"] = devs
        device["description"] = f"Device que recebe. CONECTADOS: {devs}. Nome EXATO."
        return schema