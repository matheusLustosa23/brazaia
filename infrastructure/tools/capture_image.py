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
        "Captura um frame AO VIVO da câmera neste instante — VOCÊ vê os pixels e a imagem fica "
        "GUARDADA, devolvendo um image_id. Pra ENVIAR essa imagem a um device (tela cheia ou "
        "notificação), use 'open_image'/'notify' com esse image_id.\n"
        "Pra VER/DESCREVER o que tem na câmera, você é OBRIGADO a CHAMAR esta ferramenta e ESPERAR o "
        "resultado — NUNCA descreva a cena de cabeça. NUNCA escreva '[imagem capturada …]' nem diga "
        "que capturou sem ter CHAMADO esta ferramenta NESTE turno. A cena é sempre atual: se pedirem "
        "de novo, capture de novo; nunca reutilize uma descrição anterior."
    )
    input_schema = CaptureImageInput
    side = "server"
    action_class = "read"
    
    def __init__(self, registry: VisionRegistry):
        self._registry = registry
    
    async def run(self, payload: CaptureImageInput):
        return await self._registry.capture(payload.source)
    
    def openai_schema(self) -> dict:
        schema = super().openai_schema()
        sources = self._registry.names()
        src = schema["function"]["parameters"]["properties"]["source"]
        src["enum"] = sources
        src["description"] = (
            f"De qual câmera capturar. Fontes CONECTADAS agora: {sources}. Use o nome EXATO. "
            f"'webcam' = câmera do próprio server; os outros nomes são devices conectados."
        )
        return schema