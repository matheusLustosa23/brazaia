from pydantic import BaseModel, Field

from domain.tools.base import Tool

class EchoIn(BaseModel):
    text: str = Field(description="texto a ser devolvido")
    
class EchoTool(Tool):
    name = "echo"
    description = "Devolve exatamente o texto recebido. Dummy para testes do loop."
    input_schema = EchoIn
    side = "server"
    action_class = "read"
    
    async def run(self, payload: BaseModel) -> str:
        assert isinstance(payload,EchoIn)
        return f"echo: {payload.text}"