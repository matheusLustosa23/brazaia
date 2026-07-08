from pydantic import BaseModel, Field
from domain.tools.base import Tool
from infrastructure.vision.sources import VisionRegistry

class CaptureImageInput(BaseModel):
    source: str = Field(
        default="webcam",
        description="de onde capturar: webcam | (futuro) celular_traseira | celular_frontal | notebook"
    )

class CaptureImageTool(Tool[CaptureImageInput]):
    name = "capture_image"
    description = (
        "Captura UMA imagem de uma câmera para VOCÊ analisar. Escolha a 'source'. "
        "Use quando o usuário pedir para olhar/avaliar/corrigir algo visual "
        "(ex.: 'olha o quadro', 'tira uma foto com a traseira do celular')."
    )
    input_schema = CaptureImageInput
    side = "server"
    action_class = "read"
    
    def __init__(self, registry: VisionRegistry):
        self._registry = registry
    
    async def run(self, payload: CaptureImageInput):
        return await self._registry.capture(payload.source)