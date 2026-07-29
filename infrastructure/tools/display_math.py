from  pydantic import BaseModel, Field
from domain.tools.base import Tool
from infrastructure.devices.device_gateway import DeviceGateway
from infrastructure.render.page import SINTAXE, render_page

class DisplayMathInput(BaseModel):
    device: str = Field(description="Nome EXATO do device conectado.")
    title: str = Field(description="Título curto no topo da página.")
    content: str = Field(description="LaTeX normal: texto corrido e matemática entre $...$.")

class DisplayMathTool(Tool[DisplayMathInput]):
    name = "display_math"
    description = (
        "Abre no navegador do device uma PÁGINA de MATEMÁTICA renderizada (o servidor monta o "
        "KaTeX). Use pra lista de exercícios/fórmulas — o usuário rola, seleciona e copia. "
        "Você passa só o LaTeX; as fontes e o motor são injetados no server.\n" + SINTAXE +
        "\nEx.: \"mostra/monta uma lista de exercícios (ou fórmulas) no celular pra eu ler/resolver/copiar\" → esta tool "
        "(PÁGINA no navegador).\n"
        "Contraste: \"gera a fórmula e me MANDA/ABRE\" NÃO é isto — é imagem, use 'render_math' + 'open_image'/'notify'."
    )
    input_schema = DisplayMathInput
    side = "server"
    action_class = "reversible"
    timeout_s = 30.0
    router_hint = "mostrar/abrir matemática (equação, fórmula, exercícios) numa página na tela do device"
    
    def __init__(self, gateway: DeviceGateway) -> None:
        self._gateway = gateway
        
    async def run(self, payload: DisplayMathInput) -> str:
        html = render_page(payload.content, payload.title)     
        return await self._gateway.request(payload.device, "display_page", {"html": html})
    
    def openai_schema(self) -> dict:
        schema = super().openai_schema()
        devs = self._gateway.connections.names()
        device = schema["function"]["parameters"]["properties"]["device"]
        device["enum"] = devs
        device["description"] = f"Device que recebe. CONECTADOS: {devs}. Nome EXATO."
        return schema