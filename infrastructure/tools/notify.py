from pydantic import BaseModel
from domain.tools.base import Tool


class NotifyInput(BaseModel):
    title: str
    message: str


class NotifyTool(Tool[NotifyInput]):
    """Tool device-side: schema pro LLM, roteada via DeviceGateway."""
    name = "notify"
    description = "Envia uma notificação para o device do usuário"
    input_schema = NotifyInput
    side = "device"
    action_class = "reversible"
    
    async def run(self, payload: NotifyInput) -> str:
        print(f"🔔 {payload.title}: {payload.message}")
        return f"Notificação enviada: {payload.title}"
        
        