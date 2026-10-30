from pydantic import BaseModel, Field
from domain.tools.base import Tool
from domain.tools.guard import GuardResult, ToolCtx
from infrastructure.devices.device_gateway import DeviceGateway
from infrastructure.render.render import render, STYLE_GUIDE     # mesmo motor do render_imagem (pico/livre + KaTeX)
from infrastructure.tools._util import falha_device, so_file_id


class DisplayPageInput(BaseModel):
    device: str = Field(description=(
        "Nome do device onde MOSTRAR a página (ex.: 'ubuntu', 'celular'). Use SEMPRE o que o dono pediu; "
        "se estiver offline, você recebe um aviso e informa — nunca troque por outro."))
    body_html: str = Field(description=(
        "HTML do CORPO a mostrar no navegador (qualquer conteúdo, incl. matemática). Escreva o HTML AQUI "
        "por extenso — pra REABRIR algo que você já gerou, use 'open_file' com o file_id. " + STYLE_GUIDE))
    title: str | None = Field(default=None, description="Título curto no topo da página.")
    desc: str = Field(default="", description=(
        "Descrição curta (1 linha) do que é esta página — fica no file_id pra você reconhecer depois "
        "(ex.: 'guia animado de métodos ágeis')."))
    estilo: str = Field(default="livre", description=(
        "SEMPRE 'livre' (você escreve o HTML com o SEU CSS, criatividade total). "
        "SÓ use 'pico' se o dono pedir EXPLICITAMENTE 'usando pico'."))


class DisplayPageTool(Tool[DisplayPageInput]):
    name = "display_page"
    description = (
        "MOSTRA uma página HTML no NAVEGADOR do device (o dono rola, lê e copia na tela). Serve pra "
        "QUALQUER conteúdo: tabela, card, resumo, dashboard, e TAMBÉM fórmula/derivação — o KaTeX vem "
        "embutido, então matemática RENDERIZA aqui mesmo. Você AUTORA o HTML/CSS com criatividade "
        "(estilo 'livre', padrão); só 'pico' se o dono pedir 'usando pico'.\n"
        "Contraste: virar IMAGEM (arquivo) do conteúdo pra ENVIAR/ABRIR em tela cheia → 'render_imagem'. "
        "REABRIR algo já gerado → 'open_file'.\n" + STYLE_GUIDE
    )
    input_schema = DisplayPageInput
    side = "server"
    action_class = "reversible"
    timeout_s = 30.0
    router_hint = ("MOSTRAR uma página HTML no navegador do device (tabela, card, resumo, dashboard, "
                   "fórmula/derivação — rolar/ler/copiar). KaTeX embutido; estilo pico ou livre.")

    def __init__(self, gateway: DeviceGateway) -> None:
        self._gateway = gateway

    async def run(self, payload: DisplayPageInput, ctx: ToolCtx) -> str:
        if not payload.body_html.strip():
            return "[erro] sem conteúdo: escreva o body_html (ou use 'open_file' pra reabrir um file_id)."
        try:
            html = render(payload.body_html, payload.title, estilo=payload.estilo)
        except Exception as e:
            return f"[erro] render falhou: {e}"
        res = await self._gateway.request(payload.device, "display_page", {"html": html})
        if falha_device(res):
            return res                                  # repassa o erro do device (honesto)
        return f"[ok] página '{payload.title or 'página'}' (estilo {payload.estilo}) aberta no navegador do device '{payload.device}'."

    def before(self, args: dict, ctx: ToolCtx) -> GuardResult:
        device = args.get("device", "")
        conectados = self._gateway.connections.names()
        if so_file_id(args.get("body_html") or ""):     # colou um [file_id=…] como conteúdo -> não é HTML
            return GuardResult(ok=False, reason=(
                "isso é um file_id (artefato já gerado), não HTML — pra REABRIR no device use "
                "open_file(device, file_id=…); pra VOCÊ re-analisar use see_file(file_id=…)."))
        if not device:
            return GuardResult(ok=False, reason="em qual device é pra mostrar a página?")
        if device not in conectados:
            disp = ", ".join(f"'{d}'" for d in conectados) or "nenhum"
            return GuardResult(ok=False, reason=(
                f"o device '{device}' está offline — não mostrei. Conectados agora: {disp}. "
                f"Quer que eu mostre em um desses?"))
        return GuardResult(ok=True)
