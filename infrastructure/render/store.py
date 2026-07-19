"""stash: escreve bytes de imagem num arquivo de cache e registra no image_index,
devolvendo um id curto (12 hex, compatível com o load_image). Usa o MESMO store
das cap"""

import base64
import os
import uuid

from infrastructure.vision.image_index import ImageIndex

_CACHE = os.path.expanduser("~/brazaia/cache")
_MIME_POR_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
_MIME_PADRAO = "application/octet-stream"
_ID_LEN = 12  

def stash(index: ImageIndex, data: bytes, ext: str = ".png") -> str:
    """bytes -> arquivo de cache -> image_index.put -> id (12 hex)."""
    os.makedirs(_CACHE, exist_ok=True)
    img_id = uuid.uuid4().hex[:_ID_LEN]
    caminho = os.path.join(_CACHE, f"{img_id}{ext}")
    with open(caminho, "wb") as f:
        f.write(data)
    index.put(img_id, caminho)
    return img_id

def resolve_data_uri(index: ImageIndex, img_id: str) -> str | None:
    """id -> data URI (lê o arquivo, infere o mime pela extensão). None se sumiu."""
    caminho = index.get(img_id)
    if not caminho or not os.path.exists(caminho):
        return None
    _raiz, extensao = os.path.splitext(caminho)
    mime = _MIME_POR_EXT.get(extensao.lower(), _MIME_PADRAO)
    with open(caminho, "rb") as f:
        base64_str = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{base64_str}"
