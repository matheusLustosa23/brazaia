from pydantic import BaseModel
from domain.tools.base import Tool
from domain.entities.memory_fact import MemoryFact
from application.services.memory_service import MemoryService

class LembrarInput(BaseModel):
    categoria: str
    chave: str
    conteudo: str
    confianca: float = 1.0


class LembrarTool(Tool[LembrarInput]):
    name = "lembrar"
    description = (
        "Persiste um fato sobre o dono na memória pessoal (nome, preferência, configuração, fato importante). "
        "USE sempre que o dono pedir para lembrar/guardar/anotar algo, ou compartilhar um dado pessoal sobre si. "
        "NÃO diga que lembrou ou guardou sem CHAMAR esta ferramenta — a confirmação vem do resultado dela."
    )
    input_schema = LembrarInput
    side = "server"
    action_class = "reversible"

    def __init__(self, memory: MemoryService) -> None:
        self._memory = memory

    async def run(self, payload: LembrarInput) -> str:
        fact = MemoryFact(
            category=payload.categoria,
            key=payload.chave,
            content=payload.conteudo,
            confidence=payload.confianca,
        )
        _, op = await self._memory.upsert(fact)
        return f"[memória] {op}: {payload.chave} = {payload.conteudo}"