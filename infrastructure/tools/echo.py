from pydantic import BaseModel, Field

from domain.tools.base import Tool

class EchoInput(BaseModel):
    text: str = Field(description="texto a ser devolvido")
    
class EchoTool(Tool[EchoInput]):
    name = "echo"
    description = "Devolve exatamente o texto recebido. Dummy para testes do loop."
    input_schema = EchoInput
    side = "server"
    action_class = "read"
    
    async def run(self, payload: EchoInput) -> str:
        return f"echo: {payload.text}"