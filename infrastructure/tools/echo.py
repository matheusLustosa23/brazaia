from pydantic import BaseModel, Field

from domain.tools.base import Tool

class EchoInput(BaseModel):
    text: str = Field(description="texto a ser devolvido")
    
class EchoTool(Tool[EchoInput]):
    name = "echo"
    description = "Apenas teste interno do loop. NÃO use pra responder o usuário nem pra simular o resultado de outra ação."
    input_schema = EchoInput
    side = "server"
    action_class = "read"
    
    async def run(self, payload: EchoInput) -> str:
        return f"echo: {payload.text}"