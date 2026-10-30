import base64
import os
from pydantic import BaseModel, Field
from domain.tools.base import Tool
from domain.tools.guard import GuardResult, ToolCtx
from infrastructure.devices.device_gateway import DeviceGateway
from infrastructure.render.render import render
from infrastructure.storage.file_store import FileStore
from infrastructure.tools._util import falha_device, id_fantasma

_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


class OpenFileInput(BaseModel):
    device: str = Field(description=(
        "Device onde ABRIR (ex.: 'server', 'celular'). Use SEMPRE o que o dono pediu; se offline, "
        "você recebe aviso e informa — nunca troque por outro."))
    file_id: str = Field(description=(
        "id de um artefato JÁ gerado nesta conversa (apareceu como [file_id=… · tipo · \"título\"]). "
        "NUNCA invente um file_id; só use um que apareceu."))


class OpenFileTool(Tool[OpenFileInput]):
    name = "open_file"
    description = (
        "REABRE no device um artefato que VOCÊ já gerou, pelo file_id. Resolve o TIPO sozinho: HTML → "
        "mostra no navegador; imagem → abre em tela cheia. Use quando o dono quer VER DE NOVO algo já "
        "criado (o id apareceu como [file_id=… · tipo · \"título\"]). Você NÃO precisa ver/reler o arquivo "
        "antes — passe o file_id DIRETO (nada de see_file/capture antes). Pra você MESMO re-analisar o "
        "conteúdo (não mostrar ao dono) → 'see_file'. NUNCA invente um file_id."
    )
    input_schema = OpenFileInput
    side = "server"
    action_class = "reversible"
    router_hint = "reabrir no device (navegador/tela cheia) um artefato já gerado, pelo file_id"

    def __init__(self, gateway: DeviceGateway, store: FileStore) -> None:
        self._gateway = gateway
        self._store = store

    async def run(self, payload: OpenFileInput, ctx: ToolCtx) -> str:
        kind = self._store.kind(payload.file_id)
        path = self._store.path(payload.file_id)
        if not kind or not path:
            return f"[erro] file_id '{payload.file_id}' não encontrado — gere de novo ou confira o id."
        if kind == "html":                                      # roteamento por TIPO GUARDADO (o modelo não escolhe)
            style = self._store.meta(payload.file_id).get("style") or "free"
            html = render(self._store.read_text(payload.file_id) or "", style=style)
            res = await self._gateway.request(payload.device, "display_page", {"html": html})
        else:                                                   # imagem (ou outro binário visual)
            data = self._store.read_bytes(payload.file_id) or b""
            mime = _MIME.get(os.path.splitext(path)[1].lower(), "image/jpeg")
            data_uri = f"data:{mime};base64," + base64.b64encode(data).decode()
            res = await self._gateway.request(payload.device, "open_image", {"image": data_uri})
        if falha_device(res):
            return res                                          # repassa o erro do device (honesto)
        titulo = self._store.meta(payload.file_id).get("title") or payload.file_id
        return f"[ok] '{titulo}' ({kind}) aberto no device '{payload.device}'."

    def before(self, args: dict, ctx: ToolCtx) -> GuardResult:
        device = args.get("device", "")
        conectados = self._gateway.connections.names()
        if id_fantasma(args.get("file_id"), ctx):       # id que não apareceu = inventado
            return GuardResult(ok=False, reason=(
                "esse file_id não apareceu nesta conversa — não invente; use um id que apareceu num "
                "resultado. Se o conteúdo ainda não existe, crie antes com create_file."))
        if not device:
            return GuardResult(ok=False, reason="em qual device é pra abrir?")
        if device not in conectados:
            disp = ", ".join(f"'{d}'" for d in conectados) or "nenhum"
            return GuardResult(ok=False, reason=(
                f"o device '{device}' está offline — não abri. Conectados agora: {disp}. "
                f"Quer que eu abra em um desses?"))
        return GuardResult(ok=True)
