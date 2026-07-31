from pydantic import BaseModel, Field
from domain.tools.base import Tool
from domain.tools.guard import GuardResult, ToolCtx
from infrastructure.vision.sources import VisionRegistry

class CaptureImageInput(BaseModel):
    source: str = Field(
        description=(
            "Nome da câmera a capturar — FORME pelo que o dono pediu (convenção):\n"
            "- 'câmera do <device>' → nome do device (ex.: 'câmera do ubuntu' → 'ubuntu')\n"
            "- frontal/traseira → '<device>_frontal' / '<device>_traseira' (ex.: 'frontal do celular' → 'celular_frontal')\n"
            "- 'webcam' / 'aqui' / sem citar device → 'webcam' (câmera do próprio server)\n"
            "Use SEMPRE o device que o DONO pediu. NUNCA substitua por outro só porque está disponível — "
            "se a câmera não existir, você recebe um aviso e confirma com ele."
        )
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
    router_hint = "ver/olhar pela câmera agora, tirar foto,capturar a foto, o que estou vendo ou tem na minha frente"
    
    def __init__(self, registry: VisionRegistry):
        self._registry = registry
    
    async def run(self, payload: CaptureImageInput):
        return await self._registry.capture(payload.source)  
    
    def before(self, args: dict, ctx: ToolCtx) -> GuardResult:
        source = args.get("source", "")
        fontes = self._registry.names()
        if not source:
            return GuardResult(ok=False, reason="informe qual câmera (source).")
        if source not in fontes:
            disp = ", ".join(f"'{f}'" for f in fontes) or "nenhuma"
            return GuardResult(ok=False, reason=(
                f"não encontrei a câmera '{source}'. No momento só tenho {disp} disponível. "
                f"É essa que você quer, ou era outro aparelho?"))
        return GuardResult(ok=True)