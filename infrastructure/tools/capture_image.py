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
        "Captura um frame AO VIVO da câmera. Use SOMENTE quando o dono pedir pra VER/OLHAR/ANALISAR "
        "a câmera. NUNCA acione a câmera por conta própria pra 'verificar/testar se um device está "
        "conectado', confirmar disponibilidade, ou qualquer fim que o dono NÃO pediu — a câmera é "
        "privada e só liga a pedido explícito.\n"
        "VOCÊ vê os pixels e a imagem fica GUARDADA, devolvendo um image_id. Pra ENVIAR a um device "
        "(tela cheia ou notificação), use 'open_image'/'notify' com esse image_id.\n"
        "Pra VER/DESCREVER o que tem na câmera, você é OBRIGADO a CHAMAR esta ferramenta e ESPERAR o "
        "resultado — NUNCA descreva a cena de cabeça. NUNCA escreva '[imagem capturada …]' sem ter "
        "CHAMADO esta ferramenta NESTE turno. A cena é sempre atual: se pedirem de novo, capture de novo."
        "\nEx.: \"o que tem na câmera do celular?\" → chame capture_image, ESPERE o id, e SÓ ENTÃO descreva."
    )
    input_schema = CaptureImageInput
    side = "server"
    action_class = "read"
    router_hint = "ver/olhar pela câmera agora, tirar foto, o que estou vendo ou tem na minha frente"
    
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