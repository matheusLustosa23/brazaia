from companion.runtime import runtime
from companion.plataform import notify, show_html, show_image
import base64, os

_ARQUIVO_NOTIFY = os.path.expanduser("~/brazaia_display.png")

def _bytes_imagem(data_uri: str | None) -> bytes | None:
    """Extrai os bytes de um data URI ('data:image/png;base64,XXXX') ou de um
    base64 puro. partition separa o cabeçalho do payload sem índice mágico."""
    if not data_uri:
        return None
    _cabecalho , tem_virgula, payload = data_uri.partition(",")
    base64_str = payload if tem_virgula else data_uri
    return base64.b64decode(base64_str)

def _salvar_imagem(data_uri: str | None) -> str | None:
    """data URI -> arquivo, pro --image-path da notificação Termux (que LÊ o
    arquivo ele mesmo — não é content://, por isso funciona). NÃO apaga depois:
    o Termux:API ainda pode estar lendo. Sobrescreve no próximo uso."""
    dados = _bytes_imagem(data_uri)
    if dados is None:
        return None
    with open(_ARQUIVO_NOTIFY, "wb") as f:
        f.write(dados)
    return _ARQUIVO_NOTIFY
    
    
@runtime.register_tool("notify")
async def notify_handler(args : dict) -> str:
    return await notify(args.get("title", "Alerta"), args.get("message", ""),  image=_salvar_imagem(args.get("image")))

@runtime.register_tool("display_page")
async def display_page_handler(args: dict) -> str:
    return await show_html(args["html"])

@runtime.register_tool("open_image")
async def open_image_handler(args: dict) -> str:
    png = _bytes_imagem(args.get("image"))
    if png is None:
        return "[erro] sem imagem"
    return await show_image(png) 