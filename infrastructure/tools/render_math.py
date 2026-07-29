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
        "Renderiza matemática numa IMAGEM e devolve um image_id. A imagem fica GUARDADA — "
        "não vai pra device nenhum sozinha. Entregue SÓ SE o usuário pedir: aí use 'notify' "
        "(notificação) ou 'open_image' (tela cheia) com o image_id. Se ele pediu apenas pra "
        "GERAR, só informe que a imagem está pronta.\n" + SINTAXE +
        "\nEx.: \"gera/renderiza a fórmula de X\" → produz a IMAGEM e devolve o image_id; NÃO envia sozinho. "
        "Se pedirem pra ENVIAR ou ABRIR, aí use 'open_image'/'notify' com o id.\n"
        "Contraste: \"MOSTRA uma lista de exercícios no celular pra eu resolver\" NÃO é isto — é PÁGINA, use 'display_math'."
    )
    input_schema = RenderMathInput
    side = "server"
    action_class = "read"          # só gera; não tem efeito externo
    timeout_s = 40.0               # o chrome sobe a cada chamada (~1,4 s)
    router_hint = "gerar/renderizar qualquer conteúdo matemático (equação, expressão, matriz, integral, derivada, sistema) como imagem — ainda sem enviar"

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