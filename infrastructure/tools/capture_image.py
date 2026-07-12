from pydantic import BaseModel, Field
from domain.tools.base import Tool
from infrastructure.vision.sources import VisionRegistry

class CaptureImageInput(BaseModel):
    source: str = Field(
        default="webcam",
        description="Fonte da câmera: 'webcam' (câmera do próprio server) OU o NOME EXATO de um device conectado "
                    "(ex.: 'ubuntu-teste'). Se o usuário pedir a câmera de um aparelho específico, use o nome desse device."
    )

class CaptureImageTool(Tool[CaptureImageInput]):
    name = "capture_image"
    description = (
        "Captura uma imagem AO VIVO da câmera neste instante, para VOCÊ analisar. Escolha a 'source'. "
        "A cena é sempre atual e pode ter mudado desde a última vez: SEMPRE que o dono pedir para olhar/ver a "
        "câmera (mesmo repetindo o pedido), chame esta ferramenta DE NOVO para pegar um frame novo. "
        "NUNCA reutilize uma descrição anterior nem diga 'imagem capturada' sem ter chamado esta ferramenta neste turno."
    )
    input_schema = CaptureImageInput
    side = "server"
    action_class = "read"
    
    def __init__(self, registry: VisionRegistry):
        self._registry = registry
    
    async def run(self, payload: CaptureImageInput):
        return await self._registry.capture(payload.source)