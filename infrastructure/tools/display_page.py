import re
from pydantic import BaseModel, Field
from domain.tools.base import Tool
from domain.tools.guard import GuardResult, ToolCtx
from infrastructure.devices.device_gateway import DeviceGateway
from infrastructure.render.shell import STYLE_GUIDE, wrap_page     # scaffold server-side


_LATEX = re.compile(
    r"\$\$.+?\$\$"                                    # bloco:  $$ ... $$
    r"|\\(?:frac|sqrt|sum|int|prod|lim|cdot|times|div|pm|leq|geq|neq|approx|infty|"
    r"partial|nabla|left|right|begin|end|alpha|beta|gamma|delta|theta|lambda|pi|sigma|phi|omega|hat|vec|overline)\b"
    r"|[\^_]\{",                                      # super/subscrito:  ^{...}  _{...}
    re.DOTALL,
    
)

class DisplayPageInput(BaseModel):
    device: str = Field(
        description=(
            "Nome do device que o dono citou (ex.: 'ubuntu', 'celular'). Use SEMPRE o que ele pediu; "
            "se estiver offline, você recebe um aviso e informa o dono — nunca troque por outro."
        )
    )
    title: str = Field(description="Título curto (aba/topo).")
    body_html: str = Field(description="HTML do corpo. " + STYLE_GUIDE)

class DisplayPageTool(Tool[DisplayPageInput]):
    name = "display_page"
    description = (
        "Abre uma PÁGINA GENÉRICA no navegador do device com HTML que VOCÊ escreve — nota, "
        "tabela, lista, card, resumo, dashboard, comparação. Pra MATEMÁTICA use 'display_math'; "
        "pra aviso curto use 'notify'."
        "\nEx.: \"faz uma tabela dos planos\" / \"um card de boas-vindas\" / \"um resumo em tópicos\" no celular → esta "
        "tool (HTML que VOCÊ escreve).\n"
        "Contraste: matemática → 'display_math'; aviso curto → 'notify'."
    )
    input_schema = DisplayPageInput
    side = "server"
    action_class = "reversible"
    timeout_s = 30.0
    router_hint =  "PÁGINA de conteúdo GENÉRICO (tabela, lista, card, texto). NUNCA matemática/fórmula — não renderiza LaTeX (isso é display_math)."
    
    async def run(self, payload: DisplayPageInput) -> str:
        html = wrap_page(payload.body_html, payload.title)      # injeta o CSS base do brazaia
        return await self._gateway.request(payload.device, "display_page", {"html": html})
    
    def __init__(self, gateway: DeviceGateway) -> None:
        self._gateway = gateway
    
    def before(self, args: dict, ctx: ToolCtx) -> GuardResult:
        device = args.get("device", "")
        conectados = self._gateway.connections.names()
        
        if _LATEX.search(args.get("body_html") or ""):
            return GuardResult(ok=False, reason=(
                "esse conteúdo tem matemática (LaTeX) — display_page não renderiza fórmula, fica quebrado. "
                "Use display_math."))
            
        if not device:
            return GuardResult(ok=False, reason="em qual device é pra mostrar a página?")
        if device not in conectados:
            disp = ", ".join(f"'{d}'" for d in conectados) or "nenhum"
            return GuardResult(ok=False, reason=(
                f"o device '{device}' está offline — não mostrei. Conectados agora: {disp}. "
                f"Quer que eu mostre em um desses?"))
        return GuardResult(ok=True)