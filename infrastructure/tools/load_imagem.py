import os, glob, base64
from domain.tools.base import Tool
from pydantic import BaseModel, Field
from infrastructure.vision.image_index import ImageIndex

BASE = os.path.realpath(os.path.expanduser("~/brazaia"))

class LoadImageInput(BaseModel):
    image_id: str = Field(
        pattern=r"^[0-9a-f]{12}$",              # SÓ 12 hex → "../etc" é rejeitado pelo Pydantic antes de rodar
        description="id do placeholder [imagem analisada · id:...] de uma imagem já capturada nesta conversa"
    )

class LoadImageTool(Tool[LoadImageInput]):
    name = "load_image"
    side = "server"
    action_class = "read"
    input_schema = LoadImageInput
    description = (
        "Recarrega uma imagem que VOCÊ JÁ capturou antes nesta conversa (pelo id do placeholder "
        "[imagem analisada · id:...]) para olhar os PIXELS de novo. Use quando o usuário pedir para "
        "rever/examinar um detalhe de uma imagem anterior ('olha de novo aquela foto', 'dá um zoom no "
        "canto', 'que cor era X'). Para uma cena NOVA/ao vivo, use capture_image em vez desta.\n"
        "O 'image_id' vem SOMENTE de um placeholder [imagem analisada · id:...] que apareceu antes no "
        "histórico desta conversa. NUNCA invente um id nem monte um valor. Se NÃO houver nenhum placeholder "
        "no histórico e o usuário não informar um id válido, NÃO chame esta ferramenta: responda que ainda "
        "não há imagem capturada nesta conversa e pergunte se deve capturar uma agora."
    )
    
    def __init__(self, index: ImageIndex):
        self._index = index
    
    async def run(self, payload: LoadImageInput) -> str:
        img_id = payload.image_id
        path = self._index.get(img_id)
        if not path or not os.path.exists(path):
            m = glob.glob(os.path.join(BASE, "**", f"{img_id}.jpg"), recursive=True)
            path = m[0] if m else None
        if not path:
            return f"[erro] não encontrei imagem com id '{img_id}' — o id pode estar errado."
        with open(path, "rb") as f:
            return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()