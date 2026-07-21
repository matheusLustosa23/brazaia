import os, glob, base64
from domain.tools.base import Tool
from pydantic import BaseModel, Field
from infrastructure.vision.image_index import ImageIndex
from infrastructure.render.store import resolve_data_uri, _MIME_POR_EXT

BASE = os.path.realpath(os.path.expanduser("~/brazaia"))

class LoadImageInput(BaseModel):
    image_id: str = Field(
        pattern=r"^[0-9a-f]{12}$",              # SÓ 12 hex → "../etc" é rejeitado pelo Pydantic antes de rodar
         description=(
            "image_id de uma imagem que JÁ apareceu nesta conversa — de uma captura "
            "([imagem capturada · image_id=XXXX]) OU do que 'render_math' devolveu (image_id=XXXX)."
        )
    
    )

class LoadImageTool(Tool[LoadImageInput]):
    name = "load_image"
    side = "server"
    action_class = "read"
    input_schema = LoadImageInput
    description = (
        "Traz os PIXELS de uma imagem que JÁ apareceu nesta conversa de volta pro contexto, pra VOCÊ "
        "olhar de novo. O image_id vem de DUAS origens: uma captura ([imagem capturada · image_id=XXXX]) "
        "OU o que 'render_math' devolveu (image_id=XXXX). Use pra reexaminar um detalhe ('olha de novo "
        "aquela foto', 'dá um zoom', 'confere se a fórmula renderizou'). Para uma cena NOVA/ao vivo, use "
        "'capture_image'.\n"
        "NUNCA invente um id. Se nenhum image_id apareceu antes e o usuário não informou um válido, NÃO "
        "chame esta ferramenta: diga que não há imagem nesta conversa e pergunte se deve capturar/gerar."
    )
    
    def __init__(self, index: ImageIndex):
        self._index = index
    
    async def run(self, payload: LoadImageInput) -> str:
        img_id = payload.image_id
        data_uri = resolve_data_uri(self._index, img_id)
        if data_uri is None:
            found = glob.glob(os.path.join(BASE, "**", f"{img_id}.*"), recursive=True)
            if found:
                _raiz, ext = os.path.splitext(found[0])
                mime = _MIME_POR_EXT.get(ext.lower(), "image/jpeg")
                with open(found[0], "rb") as f:
                    data_uri = f"data:{mime};base64," + base64.b64encode(f.read()).decode()
        if data_uri is None:
            return f"[erro] não encontrei imagem com id '{img_id}' — o id pode estar errado."
        return data_uri
                