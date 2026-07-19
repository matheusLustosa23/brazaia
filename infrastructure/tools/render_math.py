from pydantic import BaseModel, Field
from domain.tools.base import Tool
from infrastructure.render.page import SINTAXE, render_page
from infrastructure.render.shot import html_para_png
from infrastructure.render.store import stash
from infrastructure.vision.image_index import ImageIndex


class RenderMathInput(BaseModel):
    content: str = Field(description="LaTeX normal: texto corrido e matemática entre $...$.")
    title: str | None = Field(default=None, description="Título curto no topo da imagem.")


class RenderMathTool(Tool[RenderMathInput]):
    name = "render_math"
    description = (
        "Renderiza matemática numa IMAGEM e devolve um image_id. A imagem NÃO vai pra lugar "
        "nenhum sozinha: depois use 'notify' (mandar pro device) ou 'open_image' (tela cheia) "
        "passando o image_id.\n" + SINTAXE       # a sintaxe vem do motor (E1), não daqui
    )
    input_schema = RenderMathInput
    side = "server"
    action_class = "read"          # só gera; não tem efeito externo
    timeout_s = 40.0               # o chrome sobe a cada chamada (~1,4 s)

    def __init__(self, index: ImageIndex) -> None:
        self._index = index
    
    async def run(self, payload: RenderMathInput) -> str:
        try:
            html = render_page(payload.content, payload.title)
            png = await html_para_png(html)
        except Exception as e:
            return f"[erro] render falhou: {e}"
        image_id = stash(self._index, png)
        return f"imagem pronta (image_id={image_id}). Use em 'notify' ou 'open_image'."