from pydantic import BaseModel
from domain.tools.base import Tool
from domain.tools.guard import ToolCtx
from domain.entities.memory_fact import MemoryFact
from application.services.memory_service import MemoryService

class RememberInput(BaseModel):
    category: str
    key: str
    content: str
    confidence: float = 1.0


class RememberTool(Tool[RememberInput]):
    name = "remember"
    description = (
        "Persiste um fato sobre o dono na memória pessoal (nome, preferência, configuração, fato importante). "
        "USE sempre que o dono pedir para lembrar/guardar/anotar algo, ou compartilhar um dado pessoal sobre si. "
        "NÃO diga que lembrou ou guardou sem CHAMAR esta ferramenta — a confirmação vem do resultado dela."
    )
    input_schema = RememberInput
    side = "server"
    action_class = "reversible"
    router_hint = "anotar, guardar ou lembrar um fato, preferência ou config do dono"

    def __init__(self, memory: MemoryService) -> None:
        self._memory = memory

    async def run(self, payload: RememberInput, ctx: ToolCtx) -> str:
        fact = MemoryFact(
            category=payload.category,
            key=payload.key,
            content=payload.content,
            confidence=payload.confidence,
        )
        _, op = await self._memory.upsert(fact)
        return f"[memória] {op}: {payload.key} = {payload.content}"
