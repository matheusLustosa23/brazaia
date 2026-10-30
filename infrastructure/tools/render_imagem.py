from pydantic import BaseModel, Field
from domain.tools.base import Tool
from domain.tools.guard import ToolCtx
from infrastructure.render.render import render, STYLE_GUIDE     # mesmo motor do display_page (pico/livre + KaTeX)
from infrastructure.render.shot import html_para_png
from infrastructure.storage.file_store import FileStore, file_marker


class RenderImagemInput(BaseModel):
    body_html: str = Field(description=(
        "HTML do corpo a virar IMAGEM (qualquer conteúdo, incl. matemática). Escreva o HTML AQUI por "
        "extenso. " + STYLE_GUIDE))
    title: str | None = Field(default=None, description="Título curto no topo da imagem.")
    desc: str = Field(default="", description=(
        "Descrição curta (1 linha) do que é esta imagem — fica no file_id pra você reconhecer depois."))
    estilo: str = Field(default="livre", description=(
        "SEMPRE 'livre' (você escreve o HTML com o SEU CSS). SÓ use 'pico' se o dono pedir 'usando pico'."))


class RenderImagemTool(Tool[RenderImagemInput]):
    name = "render_imagem"
    description = (
        "Tira um 'print' de QUALQUER HTML (fórmula, card, tabela, resumo — não só matemática) virando uma "
        "IMAGEM, e devolve o file_id. A imagem fica GUARDADA — não vai pra device nenhum sozinha. Pra "
        "entregar, use depois 'open_file' (abre em tela cheia) ou 'notify' (envia) com o file_id. Se o dono "
        "pediu só pra GERAR, só informe que está pronta.\n" + STYLE_GUIDE
    )
    input_schema = RenderImagemInput
    side = "server"
    action_class = "read"          # só gera; não tem efeito externo
    timeout_s = 40.0               # o chrome sobe a cada chamada (~1,4 s)
    router_hint = ("gera uma IMAGEM (arquivo) de qualquer HTML pra depois ABRIR (open_file) ou ENVIAR "
                   "(notify). NÃO mostra na tela sozinha.")

    def __init__(self, store: FileStore) -> None:
        self._store = store

    async def run(self, payload: RenderImagemInput, ctx: ToolCtx) -> str:
        if not payload.body_html.strip():
            return "[erro] sem conteúdo: escreva o body_html."
        try:
            html = render(payload.body_html, payload.title, estilo=payload.estilo)
            png = await html_para_png(html)
        except Exception as e:
            return f"[erro] render falhou: {e}"
        title, desc = payload.title or "", payload.desc or ""
        fid = self._store.put(png, device=ctx.device_id, session=ctx.session_id, kind="img", ext=".png",
                              title=title, desc=desc)
        return f"[imagem GERADA] {file_marker(fid, 'img', title, desc)} — pronta; use em 'open_file' ou 'notify'."
