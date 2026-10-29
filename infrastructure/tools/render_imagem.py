from pydantic import BaseModel, Field
from domain.tools.base import Tool
from domain.tools.guard import ToolCtx
from infrastructure.render.render import render, STYLE_GUIDE     # mesmo motor do display_page (pico/livre + KaTeX)
from infrastructure.render.shot import html_para_png
from infrastructure.storage.file_store import FileStore


class RenderImagemInput(BaseModel):
    title: str | None = Field(default=None, description="Título curto no topo da imagem.")
    body_html: str = Field(default="", description=(
        "HTML do corpo a virar imagem (qualquer conteúdo, incl. matemática). Deixe vazio SE for reusar "
        "um HTML já gerado — aí passe 'file_id'. " + STYLE_GUIDE))
    file_id: str | None = Field(default=None, description=(
        "Pra REUSAR um HTML já gerado (você recebeu 'file_id=…' antes): passe aqui e deixe body_html "
        "vazio. NUNCA invente um file_id; só use um que apareceu nesta conversa."))
    estilo: str = Field(default="livre", description=(
        "SEMPRE 'livre' (você escreve o HTML com o SEU CSS). SÓ use 'pico' se o dono pedir 'usando pico'."))


class RenderImagemTool(Tool[RenderImagemInput]):
    name = "render_imagem"
    description = (
        "Renderiza QUALQUER HTML (fórmula, card, tabela, resumo — não só matemática) numa IMAGEM e "
        "devolve um image_id. A imagem fica GUARDADA — não vai pra device nenhum sozinha. Entregue SÓ SE "
        "o dono pedir: aí use 'notify' (notificação) ou 'open_image' (tela cheia) com o image_id. Se ele "
        "pediu apenas pra GERAR, só informe que a imagem está pronta.\n" + STYLE_GUIDE
    )
    input_schema = RenderImagemInput
    side = "server"
    action_class = "read"          # só gera; não tem efeito externo
    timeout_s = 40.0               # o chrome sobe a cada chamada (~1,4 s)
    router_hint = ("gera uma IMAGEM (arquivo) de qualquer HTML pra depois ENVIAR (notify) ou ABRIR "
                   "(open_image). NÃO mostra na tela sozinha.")

    def __init__(self, store: FileStore) -> None:
        self._store = store

    async def run(self, payload: RenderImagemInput, ctx: ToolCtx) -> str:
        corpo = payload.body_html
        if not corpo and payload.file_id:               # reuso: recupera o HTML salvo pelo file_id
            corpo = self._store.read_text(payload.file_id) or ""
            if not corpo:
                return f"[erro] file_id '{payload.file_id}' não encontrado — gere o HTML de novo."
        if not corpo:
            return "[erro] sem conteúdo: passe 'body_html' ou um 'file_id' de um HTML já gerado."
        try:
            html = render(corpo, payload.title, estilo=payload.estilo)
            png = await html_para_png(html)
        except Exception as e:
            return f"[erro] render falhou: {e}"
        # persiste no store unificado (hash, pasta {device}/{session}/img) — device/session vêm do ctx
        image_id = self._store.put(png, device=ctx.device_id, session=ctx.session_id, kind="img", ext=".png")
        titulo = payload.title or "imagem"
        return (
            f"[imagem GERADA (render_imagem · estilo {payload.estilo}) · '{titulo}' · image_id={image_id}] "
            f"— pronta; use em 'notify' ou 'open_image'."
        )
