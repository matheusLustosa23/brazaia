"""Resolve um file_id de imagem do FileStore em data URI (o notify manda a imagem pro device)."""

import base64
import os

from infrastructure.storage.file_store import FileStore
from domain.tools.guard import ToolCtx

_CACHE = os.path.expanduser("~/brazaia/cache")
_MIME_POR_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
_MIME_PADRAO = "application/octet-stream"
_ID_LEN = 12  

def resolve_data_uri(index: FileStore, img_id: str) -> str | None:
    """id -> data URI (lê o arquivo, infere o mime pela extensão). None se sumiu."""
    caminho = index.get(img_id)
    if not caminho or not os.path.exists(caminho):
        return None
    _raiz, extensao = os.path.splitext(caminho)
    mime = _MIME_POR_EXT.get(extensao.lower(), _MIME_PADRAO)
    with open(caminho, "rb") as f:
        base64_str = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{base64_str}"

def _id_valido(index, ctx: ToolCtx, image_id: str) -> bool:
    return image_id in ctx.ids_reais or resolve_data_uri(index, image_id) is not None