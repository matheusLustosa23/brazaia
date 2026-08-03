from  pydantic import BaseModel, Field
from domain.tools.base import Tool
from domain.tools.guard import GuardResult, ToolCtx
from infrastructure.devices.device_gateway import DeviceGateway
from infrastructure.render.page import SINTAXE, render_page

class DisplayMathInput(BaseModel):
    device: str = Field(
    description=(
        "Nome do device que o dono citou (ex.: 'ubuntu', 'celular'). Use SEMPRE o que ele pediu; "
        "se estiver offline, você recebe um aviso e informa o dono — nunca troque por outro."
        )
    )
    title: str = Field(description="Título curto no topo da página.")
    content: str = Field(description="LaTeX normal: texto corrido e matemática entre $...$.")

class DisplayMathTool(Tool[DisplayMathInput]):
    name = "display_math"
    description = (
        "Abre no navegador do device uma PÁGINA de MATEMÁTICA renderizada (o servidor monta o "
        "KaTeX). Use pra lista de exercícios/fórmulas — o usuário rola, seleciona e copia. "
        "Você passa só o LaTeX; as fontes e o motor são injetados no server.\n" + SINTAXE +
        "\nEx.: \"mostra/monta uma lista de exercícios (ou fórmulas) no celular pra eu ler/resolver/copiar\" → esta tool "
        "(PÁGINA no navegador).\n"
        "Contraste: \"gera a fórmula e me MANDA/ABRE\" NÃO é isto — é imagem, use 'render_math' + 'open_image'/'notify'."
    )
    input_schema = DisplayMathInput
    side = "server"
    action_class = "reversible"
    timeout_s = 30.0
    router_hint =  "gera E MOSTRA uma PÁGINA de matemática no navegador do device (KaTeX, pra ler/resolver). Já monta tudo — DISPENSA render_math. ÚNICA pra matemática em página."
    
    def __init__(self, gateway: DeviceGateway) -> None:
        self._gateway = gateway
        
    async def run(self, payload: DisplayMathInput) -> str:
        html = render_page(payload.content, payload.title)     
        return await self._gateway.request(payload.device, "display_page", {"html": html})
    
    def before(self, args: dict, ctx: ToolCtx) -> GuardResult:
        device = args.get("device", "")
        conectados = self._gateway.connections.names()
        if not device:
            return GuardResult(ok=False, reason="em qual device é pra mostrar a matemática?")
        if device not in conectados:
            disp = ", ".join(f"'{d}'" for d in conectados) or "nenhum"
            return GuardResult(ok=False, reason=(
                f"o device '{device}' está offline — não mostrei. Conectados agora: {disp}. "
                f"Quer que eu mostre em um desses?"))
        return GuardResult(ok=True)
    
    