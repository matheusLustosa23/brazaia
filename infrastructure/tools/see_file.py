import base64
import os
from pydantic import BaseModel, Field
from domain.tools.base import Tool
from domain.tools.guard import GuardResult, ToolCtx
from infrastructure.storage.file_store import FileStore
from infrastructure.tools._util import id_fantasma

_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


class SeeFileInput(BaseModel):
    file_id: str = Field(description=(
        "id de um artefato já gerado/capturado nesta conversa (apareceu como [file_id=… · tipo · …] "
        "ou [imagem capturada · image_id=…]). NUNCA invente um file_id; só use um que apareceu."))


class SeeFileTool(Tool[SeeFileInput]):
    name = "see_file"
    description = (
        "Traz o CONTEÚDO de um artefato que JÁ EXISTE (por file_id) pro SEU contexto, pra VOCÊ re-analisar: "
        "imagem → re-olha os pixels; HTML/texto → relê o conteúdo. Ex.: 'confere o que tem naquele arquivo', "
        "'dá um zoom naquela imagem que apareceu'. Resolve o TIPO sozinho.\n"
        "NÃO é pra câmera: 'olha/vê a câmera' é AO VIVO → use 'capture_image' (see_file só mexe em arquivo "
        "que já tem file_id). NÃO precisa antes de mostrar: pra exibir no device é 'open_file' direto. "
        "NUNCA invente um file_id — use um que apareceu num resultado."
    )
    input_schema = SeeFileInput
    side = "server"
    action_class = "read"
    router_hint = "trazer o conteúdo de um artefato (imagem/html) pro contexto pra re-analisar (NÃO mostra no device)"

    def __init__(self, store: FileStore) -> None:
        self._store = store

    def before(self, args: dict, ctx: ToolCtx) -> GuardResult:
        if id_fantasma(args.get("file_id"), ctx):       # id que não apareceu = inventado
            return GuardResult(ok=False, reason=(
                "esse file_id não apareceu nesta conversa — não invente. Pra VER a câmera AO VIVO use "
                "capture_image; pra um arquivo, use um file_id que apareceu num resultado."))
        return GuardResult(ok=True)

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
