from pydantic import BaseModel, Field
from domain.tools.base import Tool
from domain.tools.guard import GuardResult, ToolCtx
from infrastructure.render.render import render        # mesmo motor do create_file (pico/free + KaTeX)
from infrastructure.render.shot import html_para_png
from infrastructure.storage.file_store import FileStore
from infrastructure.tools._util import id_fantasma


class ScreenshotInput(BaseModel):
    file_id: str = Field(description=(
        "id de um artefato HTML que JÁ existe nesta conversa (apareceu num resultado como "
        "[file_id=… · html · …], de um 'create_file' anterior). Esta tool abre esse HTML e tira um print "
        "— você NÃO reescreve o HTML nem usa see_file. Se o conteúdo é NOVO, crie primeiro com "
        "'create_file' (ext=html) pra ter o file_id, depois chame esta. NUNCA invente um file_id."))
    title: str | None = Field(default=None, description=(
        "Título curto no topo da imagem (opcional — por padrão usa o título guardado do HTML)."))
    desc: str = Field(default="", description=(
        "Descrição curta da imagem (opcional — por padrão herda a do HTML)."))


class ScreenshotTool(Tool[ScreenshotInput]):
    name = "screenshot"
    description = (
        "Tira um PRINT (screenshot) de um artefato HTML (por file_id) e devolve o file_id da IMAGEM (PNG). "
        "Abre o HTML guardado no server e fotografa — não reescreva o HTML, só passe o file_id dele. A "
        "imagem fica GUARDADA (não vai pra device sozinha); pra entregar use depois 'open_file' (tela cheia) "
        "ou 'notify' (envia).\n"
        "Conteúdo NOVO? Crie antes com 'create_file' (ext=html → vira file_id), depois chame esta pelo id. "
        "É ESTÁTICO: se o HTML é interativo (localStorage/form/CRUD), não faz sentido virar imagem — mostre "
        "com 'open_file'."
    )
    input_schema = ScreenshotInput
    side = "server"
    action_class = "read"          # só gera; não tem efeito externo
    timeout_s = 40.0               # o chrome sobe a cada chamada (~1,4 s)
    router_hint = ("tira um PRINT (PNG) de uma PÁGINA HTML existente (file_id) pra depois ABRIR (open_file) ou "
                   "ENVIAR (notify). NÃO escreve HTML; NÃO mostra na tela sozinha.")

    def __init__(self, store: FileStore) -> None:
        self._store = store

    async def run(self, payload: ScreenshotInput, ctx: ToolCtx) -> str:
        kind = self._store.kind(payload.file_id)
        if kind != "html":
            return (f"[erro] file_id '{payload.file_id}' não é uma página HTML ({kind or 'desconhecido'}) — "
                    f"screenshot só fotografa HTML. Crie o HTML com 'create_file' (ext=html) primeiro.")
        corpo = self._store.read_text(payload.file_id)
        if corpo is None:
            return f"[erro] file_id '{payload.file_id}' não encontrado — confira o id."
        meta = self._store.meta(payload.file_id)
        title = payload.title or meta.get("title") or ""
        desc = payload.desc or meta.get("desc") or ""
        try:
            html = render(corpo, title or None, style=meta.get("style") or "free")
            png = await html_para_png(html)
        except Exception as e:
            return f"[erro] screenshot falhou: {e}"         # sem PNG -> NÃO existe imagem; não invente um id de sucesso
        fid = self._store.put(png, device=ctx.device_id, session=ctx.session_id, kind="img", ext=".png",
                              title=title, desc=desc)
        return f"[imagem GERADA] {self._store.marker(fid)} — pronta; use em 'open_file' ou 'notify'."

    def before(self, args: dict, ctx: ToolCtx) -> GuardResult:
        if not (args.get("file_id") or "").strip():
            return GuardResult(ok=False, reason=(
                "me dê o file_id da página HTML a fotografar. Se o conteúdo é novo, crie com 'create_file' "
                "(ext=html) primeiro (ele devolve o file_id), depois chame esta."))
        if id_fantasma(args.get("file_id"), ctx):       # id que não apareceu = inventado
            return GuardResult(ok=False, reason=(
                "esse file_id não apareceu nesta conversa — não invente. Crie a página com create_file "
                "(ext=html) primeiro, depois fotografe pelo id que ele devolver."))
        return GuardResult(ok=True)
