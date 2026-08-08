from pydantic import BaseModel, Field
from domain.tools.base import Tool
from domain.tools.guard import GuardResult, ToolCtx
from infrastructure.devices.device_gateway import DeviceGateway
from infrastructure.render.store import resolve_data_uri, _id_valido
from infrastructure.vision.image_index import ImageIndex


class NotifyInput(BaseModel):
    device: str = Field(
        description=(
            "Nome do device que o dono citou (ex.: 'ubuntu', 'celular'). Use SEMPRE o que ele pediu; "
            "se estiver offline, você recebe um aviso e informa o dono — nunca troque por outro."
        )
    )
    title: str = Field(description="Título curto.")
    message: str = Field(default="", description=(
        "Mensagem em TEXTO PURO pro usuário ler (a notificação NÃO renderiza LaTeX). Unicode ok (√ ² π ≤ →). "
        "Se anexar imagem de fórmula (image_id), o `message` é uma LEGENDA CURTA em palavras — a fórmula já vai "
        "na imagem.\n"
        "Ex.: com a imagem da energia cinética → message: \"Segue a fórmula da energia cinética.\" "
        "(NÃO 'A energia cinética é $E_c = ...$')."))
    image_id: str | None = Field(
        default=None,
        description=(
            "OPCIONAL — o PADRÃO é NÃO anexar. Só use se o dono pediu pra enviar/mostrar uma imagem.\n"
            "Quando anexar, o id tem que JÁ ter aparecido nesta conversa — de 'render_math' (image_id=XXXX) "
            "ou de uma captura ([imagem capturada · image_id=...]). NÃO invente o id.\n"
            "Se NENHUM image_id apareceu ainda: não gere nem capture por conta própria — diga que "
            "não encontrou imagem e PERGUNTE se quer que gere ou capture.\n"
            "Se o próprio usuário pediu as duas coisas (gerar/capturar E entregar): encadeie — "
            "chame a outra tool, ESPERE o id, só então esta. Nunca as duas no mesmo turno."))




class NotifyTool(Tool[NotifyInput]):
    name = "notify"
    description = (
        "Manda uma NOTIFICAÇÃO de TEXTO pra tela de um device. O padrão é SÓ title/message.\n"
        "Anexe image_id APENAS quando o dono pedir explicitamente pra ENVIAR/MOSTRAR uma imagem "
        "('manda a foto', 'envia a fórmula que você gerou'). Aviso de status "
        "('backup terminou', 'sistema online', 'processo concluído') → NUNCA anexa imagem, só texto.\n"
        "Ex. status: \"avisa que o build terminou\" → notify(device, title, message).\n"
        "Ex. com imagem (pedido): \"manda a fórmula pro celular\" → notify(device, title, message=legenda, image_id)."
    )
    input_schema = NotifyInput
    side = "server"
    action_class = "reversible"
    router_hint = "notificar,avisar,enviar algo"

    def __init__(self, gateway: DeviceGateway, index: ImageIndex) -> None:
        self._gateway = gateway
        self._index = index    
        
    async def run(self, payload: NotifyInput) -> str:
        args:dict = {"title": payload.title, "message": payload.message}
        if payload.image_id:
            data_uri = resolve_data_uri(self._index, payload.image_id)
            if data_uri is None:
                return (f"[erro] image_id '{payload.image_id}' não existe mais. Não invente ids. "
                        f"Se outra imagem apareceu nesta conversa, use o id DELA; senão, AVISE o "
                        f"usuário e PERGUNTE se ele quer que você gere ou capture uma.")
            args["image"] = data_uri
        return await self._gateway.request(payload.device, "notify", args)
    
    def before(self, args: dict, ctx: ToolCtx) -> GuardResult:
        device = args.get("device", "")
        image_id = args.get("image_id")
        conectados = self._gateway.connections.names()
        if not device:
            return GuardResult(ok=False, reason="pra qual device é a notificação?")
        if device not in conectados:
            disp = ", ".join(f"'{d}'" for d in conectados) or "nenhum"
            return GuardResult(ok=False, reason=(
                f"o device '{device}' está offline — não enviei. Conectados agora: {disp}. "
                f"Quer que eu envie pra um desses?"))
        if image_id and not _id_valido(self._index, ctx, image_id):
            return GuardResult(ok=False, reason=(
                f"não tenho a imagem '{image_id}' — não foi gerada nem capturada neste turno. "
                "Gere/capture primeiro, ou me diga qual usar."))
        return GuardResult(ok=True)
    
    