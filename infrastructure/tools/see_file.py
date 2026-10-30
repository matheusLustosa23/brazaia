import base64
import os
from pydantic import BaseModel, Field
from domain.tools.base import Tool
from domain.tools.guard import ToolCtx
from infrastructure.storage.file_store import FileStore

_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


class SeeFileInput(BaseModel):
    file_id: str = Field(description=(
        "id de um artefato já gerado/capturado nesta conversa (apareceu como [file_id=… · tipo · …] "
        "ou [imagem capturada · image_id=…]). NUNCA invente um file_id; só use um que apareceu."))


class SeeFileTool(Tool[SeeFileInput]):
    name = "see_file"
    description = (
        "Traz o CONTEÚDO de um artefato (por file_id) de volta pro SEU contexto pra VOCÊ re-analisar: "
        "imagem → você re-olha os pixels; HTML/texto → você relê o conteúdo. Use em 'olha de novo aquela "
        "foto', 'dá um zoom', 'confere o que tem naquele arquivo'. Resolve o TIPO sozinho. Pra MOSTRAR ao "
        "dono num device (não pra você olhar) → 'open_file'. NUNCA invente um file_id."
    )
    input_schema = SeeFileInput
    side = "server"
    action_class = "read"
    router_hint = "trazer o conteúdo de um artefato (imagem/html) pro contexto pra re-analisar (NÃO mostra no device)"

    def __init__(self, store: FileStore) -> None:
        self._store = store

    async def run(self, payload: SeeFileInput, ctx: ToolCtx) -> str:
        kind = self._store.kind(payload.file_id)
        path = self._store.path(payload.file_id)
        if not kind or not path:
            return f"[erro] file_id '{payload.file_id}' não encontrado — confira o id."
        if kind in ("html", "txt", "json"):                     # texto -> volta como texto (o modelo relê)
            return self._store.read_text(payload.file_id) or ""
        # imagem -> data URI; o orchestrator injeta como bloco de VISÃO (o modelo vê os pixels)
        data = self._store.read_bytes(payload.file_id) or b""
        mime = _MIME.get(os.path.splitext(path)[1].lower(), "image/jpeg")
        return f"data:{mime};base64," + base64.b64encode(data).decode()
