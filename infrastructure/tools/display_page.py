from pydantic import BaseModel, Field
from domain.tools.base import Tool
from domain.tools.guard import GuardResult, ToolCtx
from infrastructure.devices.device_gateway import DeviceGateway
from infrastructure.render.render import render, STYLE_GUIDE     # mesmo motor do render_imagem (pico/livre + KaTeX)
from infrastructure.storage.file_store import FileStore
from infrastructure.tools._util import falha_device


class DisplayPageInput(BaseModel):
    device: str = Field(description=(
        "Nome do device onde MOSTRAR a página (ex.: 'ubuntu', 'celular'). Use SEMPRE o que o dono pediu; "
        "se estiver offline, você recebe um aviso e informa — nunca troque por outro."))
    body_html: str = Field(default="", description=(
        "HTML do CORPO a mostrar no navegador do device (qualquer conteúdo, incl. matemática). "
        "Deixe vazio SE for reusar um HTML já gerado — aí passe 'file_id'. " + STYLE_GUIDE))
    file_id: str | None = Field(default=None, description=(
        "Pra REUSAR um HTML já gerado antes (você recebeu 'file_id=…' no resultado de um display_page/"
        "render_imagem anterior): passe o file_id AQUI e deixe body_html vazio. "
        "NUNCA invente um file_id; só use um que apareceu nesta conversa."))
    title: str | None = Field(default=None, description="Título curto no topo da página.")
    estilo: str = Field(default="livre", description=(
        "SEMPRE 'livre' (você escreve o HTML com o SEU CSS, criatividade total). "
        "SÓ use 'pico' se o dono pedir EXPLICITAMENTE 'usando pico'."))


class DisplayPageTool(Tool[DisplayPageInput]):
    name = "display_page"
    description = (
        "MOSTRA uma página HTML no NAVEGADOR do device (o dono rola, lê e copia na tela). Serve pra "
        "QUALQUER conteúdo: tabela, card, resumo, dashboard, e TAMBÉM fórmula/derivação — o KaTeX vem "
        "embutido, então matemática RENDERIZA aqui mesmo. Você AUTORA o HTML/CSS com criatividade "
        "(estilo 'livre', padrão); só use 'pico' se o dono pedir 'usando pico'.\n"
        "Contraste: pra virar uma IMAGEM (arquivo) do conteúdo pra ENVIAR ou ABRIR em tela cheia → "
        "'render_imagem'. O display_page mostra DIRETO no navegador; não vira arquivo.\n" + STYLE_GUIDE
    )
    input_schema = DisplayPageInput
    side = "server"
    action_class = "reversible"
    timeout_s = 30.0
    router_hint = ("MOSTRAR uma página HTML no navegador do device (tabela, card, resumo, dashboard, "
                   "fórmula/derivação — rolar/ler/copiar). KaTeX embutido; estilo pico ou livre.")

    def __init__(self, gateway: DeviceGateway, store: FileStore) -> None:
        self._gateway = gateway
        self._store = store

    async def run(self, payload: DisplayPageInput, ctx: ToolCtx) -> str:
        corpo = payload.body_html
        if not corpo and payload.file_id:               # reuso: recupera o HTML salvo pelo file_id
            corpo = self._store.read_text(payload.file_id) or ""
            if not corpo:
                return f"[erro] file_id '{payload.file_id}' não encontrado — gere o HTML de novo."
        if not corpo:
            return "[erro] sem conteúdo: passe 'body_html' ou um 'file_id' de um HTML já gerado."
        try:
            html = render(corpo, payload.title, estilo=payload.estilo)
        except Exception as e:
            return f"[erro] render falhou: {e}"
        res = await self._gateway.request(payload.device, "display_page", {"html": html})
        if falha_device(res):
            return res                                  # repassa o erro do device (honesto)
        return f"[ok] página '{payload.title or 'página'}' (estilo {payload.estilo}) aberta no navegador do device '{payload.device}'."

    def before(self, args: dict, ctx: ToolCtx) -> GuardResult:
        device = args.get("device", "")
        conectados = self._gateway.connections.names()
        if not device:
            return GuardResult(ok=False, reason="em qual device é pra mostrar a página?")
        if device not in conectados:
            disp = ", ".join(f"'{d}'" for d in conectados) or "nenhum"
            return GuardResult(ok=False, reason=(
                f"o device '{device}' está offline — não mostrei. Conectados agora: {disp}. "
                f"Quer que eu mostre em um desses?"))
        return GuardResult(ok=True)
