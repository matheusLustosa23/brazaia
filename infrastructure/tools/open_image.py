from pydantic import BaseModel, Field
from domain.tools.base import Tool
from infrastructure.devices.device_gateway import DeviceGateway
from infrastructure.render.store import resolve_data_uri
from infrastructure.vision.image_index import ImageIndex

class OpenImageInput(BaseModel):
    device: str = Field(description="Nome EXATO do device conectado.")
    image_id: str = Field(description=(
        "image_id de uma imagem que JÁ apareceu nesta conversa. DUAS origens valem: 'render_math' "
        "(image_id=XXXX) ou uma captura ([imagem capturada · image_id=...]). NÃO invente o id.\n"
        "Se NENHUM image_id apareceu ainda: não gere nem capture por conta própria — diga que não "
        "encontrou imagem e PERGUNTE se quer que gere ou capture.\n"
        "Se o próprio usuário pediu as duas coisas (gerar/capturar E entregar): encadeie — chame a "
        "outra tool, ESPERE o id, só então esta. Nunca as duas no mesmo turno."))


class OpenImageTool(Tool[OpenImageInput]):
    name = "open_image"
    description = (
        "Abre uma imagem em TELA CHEIA no visualizador do device (permite zoom). "
        "Use pra ler com calma; pra um aviso rápido prefira 'notify'."
        "\nEx.: \"abre a última foto (ou a fórmula) em tela cheia no celular\" → open_image(device, o image_id que "
        "apareceu antes na conversa).\n"
        "Contraste: aviso rápido em vez de tela cheia → 'notify'."
    )
    input_schema = OpenImageInput
    side = "server"
    action_class = "reversible"
    router_hint = "abrir uma imagem em tela cheia no device (zoom, ler com calma)"

    def __init__(self, gateway: DeviceGateway, index: ImageIndex) -> None:
        self._gateway = gateway
        self._index = index
        
    async def run(self, payload: OpenImageInput) -> str:
        data_uri = resolve_data_uri(self._index, payload.image_id)
        if data_uri is None:
            return (f"[erro] image_id '{payload.image_id}' não existe. Não invente ids. "
                    f"Se alguma imagem apareceu antes nesta conversa — de 'render_math' "
                    f"(image_id=...) ou de uma captura ([imagem capturada · image_id=...]) — use o id "
                    f"DELA. Se não apareceu nenhuma, AVISE o usuário e PERGUNTE se ele quer que "
                    f"você gere ou capture uma. Não faça por conta própria.")
        return await self._gateway.request(payload.device, "open_image", {"image": data_uri})

    def openai_schema(self) -> dict:
        schema = super().openai_schema()
        devs = self._gateway.connections.names()
        device = schema["function"]["parameters"]["properties"]["device"]
        device["enum"] = devs
        device["description"] = f"Device que recebe. CONECTADOS: {devs}. Nome EXATO."
        return schema