from pydantic import BaseModel, Field
from domain.tools.base import Tool
from domain.tools.guard import GuardResult, ToolCtx
from infrastructure.render.render import STYLE_GUIDE
from infrastructure.storage.file_store import FileStore, kind_de_ext
from infrastructure.tools._util import eh_placeholder


class CreateFileInput(BaseModel):
    body: str = Field(description=(
        "CONTEÚDO do arquivo, escrito AQUI por extenso (você AUTORA). Pode ser HTML, Markdown, JSON, "
        "texto, CSV… conforme a extensão. Pra HTML, " + STYLE_GUIDE))
    ext: str = Field(default="html", description=(
        "Extensão/tipo do arquivo: 'html', 'md', 'json', 'txt', 'csv'… (padrão 'html'). Define como ele é "
        "aberto depois (html → navegador; imagem vem de screenshot; texto → leitura)."))
    title: str | None = Field(default=None, description="Título curto do arquivo (vai no file_id).")
    desc: str = Field(default="", description=(
        "Descrição curta (1 linha) do que é este arquivo — fica no file_id pra você reconhecer depois "
        "(ex.: 'lista de exercícios de fatoração')."))
    style: str = Field(default="free", description=(
        "Só vale pra HTML: SEMPRE 'free' (você escreve o HTML com o SEU CSS). SÓ 'pico' se o dono pedir."))


class CreateFileTool(Tool[CreateFileInput]):
    name = "create_file"
    description = (
        "CRIA um arquivo de QUALQUER tipo (HTML, Markdown, JSON, texto…) com o conteúdo que VOCÊ escreve, e "
        "devolve o file_id. É só AUTORIA: NÃO mostra em device nenhum e NÃO vira imagem — você escreve uma "
        "vez e depois ATUA pelo file_id:\n"
        "  • 'open_file' (device, file_id) → mostra (HTML no navegador, imagem em tela cheia)\n"
        "  • 'screenshot' (file_id) → vira IMAGEM (PNG) de um HTML\n"
        "  • 'notify' (device, …, file_id) → envia\n"
        "  • 'see_file' (file_id) → você mesmo relê o conteúdo\n"
        "Fluxos: 'mostra uma página' → create_file(ext=html) + open_file. 'faz uma imagem de X' → "
        "create_file(ext=html) + screenshot + open_file/notify. Interativo (localStorage/form/CRUD) é "
        "HTML normal e se MOSTRA com open_file (não vira imagem).\n" + STYLE_GUIDE
    )
    input_schema = CreateFileInput
    side = "server"
    action_class = "read"          # só cria um artefato no server; nenhum efeito externo
    router_hint = ("cria um ARQUIVO (html/md/json/txt…) com o conteúdo que o LLM escreve e devolve o "
                   "file_id, SEM mostrar nem virar imagem — autoria pra depois usar pelo id")

    def __init__(self, store: FileStore) -> None:
        self._store = store

    async def run(self, payload: CreateFileInput, ctx: ToolCtx) -> str:
        corpo = payload.body.strip()
        if not corpo:
            return "[erro] sem conteúdo: escreva o body."
        ext = (payload.ext or "html").lower().lstrip(".")
        kind = kind_de_ext(ext)
        fid = self._store.put_text(corpo, device=ctx.device_id, session=ctx.session_id, kind=kind,
                                   ext="." + ext, title=payload.title or "", desc=payload.desc or "",
                                   style=payload.style)
        return f"[arquivo CRIADO] {self._store.marker(fid)} — agora use em 'open_file', 'screenshot', 'notify' ou 'see_file'."

    def before(self, args: dict, ctx: ToolCtx) -> GuardResult:
        if eh_placeholder(args.get("body") or ""):        # colou marca do histórico -> não é conteúdo
            return GuardResult(ok=False, reason=(
                "o body veio como marcador/placeholder, não como conteúdo — ESCREVA o conteúdo por extenso. "
                "Se é pra reusar um arquivo que já existe, ele já tem file_id; use open_file/screenshot/see_file."))
        return GuardResult(ok=True)
