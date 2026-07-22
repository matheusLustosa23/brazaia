from pydantic import BaseModel, Field
from domain.tools.base import Tool
from infrastructure.devices.device_gateway import DeviceGateway
from infrastructure.render.store import resolve_data_uri
from infrastructure.vision.image_index import ImageIndex


class NotifyInput(BaseModel):
    device: str = Field(description="Nome EXATO do device conectado.")
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
            "OPCIONAL — omita pra notificação SÓ DE TEXTO.\n"
            "Pra anexar imagem, use um image_id que JÁ apareceu nesta conversa. DUAS origens "
            "valem: 'render_math' (image_id=XXXX) ou uma captura ([imagem capturada · image_id=...]). "
            "NÃO invente o id.\n"
            "Se NENHUM image_id apareceu ainda: não gere nem capture por conta própria — diga que "
            "não encontrou imagem e PERGUNTE se quer que gere ou capture.\n"
            "Se o próprio usuário pediu as duas coisas (gerar/capturar E entregar): encadeie — "
            "chame a outra tool, ESPERE o id, só então esta. Nunca as duas no mesmo turno."))



class NotifyTool(Tool[NotifyInput]):
    name = "notify"
    description = (
        "Manda uma NOTIFICAÇÃO pra tela de um device conectado. Só texto: passe title/message. "
        "Com imagem: passe também o image_id (de qualquer origem — matemática, foto, arquivo).\n"
        "Ex. só texto: \"avisa no celular que o build terminou\" → notify(device, title, message).\n"
        "Ex. com imagem: \"manda a fórmula que você gerou pro celular\" → notify(device, title, "
        "message=legenda curta em palavras, image_id)."
    )
    input_schema = NotifyInput
    side = "server"
    action_class = "reversible"

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
    
    def openai_schema(self) -> dict:
        schema = super().openai_schema()
        devs = self._gateway.connections.names()
        device = schema["function"]["parameters"]["properties"]["device"]
        device["enum"] = devs
        device["description"] = f"Device que recebe. CONECTADOS: {devs}. Nome EXATO."
        return schema