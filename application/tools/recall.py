from pydantic import BaseModel, Field

from application.services.cerebro_service import CerebroService
from domain.tools.base import Tool
from domain.tools.guard import ToolCtx


class RecallInput(BaseModel):
    busca: str | None = Field(default=None, description=(
        "Palavras do que procurar (busca por QUALQUER uma delas). Ex.: 'supino ombro', 'prova cálculo'."))
    entidade: str | None = Field(default=None, description=(
        "Em vez de buscar: TUDO o que se sabe de uma entidade pelo nome ('Você', 'Supino reto'), com as ligações."))
    incluir_antigas: bool = Field(default=False, description=(
        "Com entidade: mostra também o que JÁ FOI verdade e foi corrigido (o histórico). Use pra 'o que mudou'."))


class RecallTool(Tool[RecallInput]):
    name = "recall"
    description = (
        "Consulta o cérebro (o que você sabe do dono e da vida dele). O bloco MEMÓRIA do contexto já traz o "
        "principal; USE esta ferramenta quando o dono perguntar algo do passado/dele que NÃO está lá, ou pedir "
        "'o que você sabe sobre X'. Não achou → diga que não sabe; nunca complete de cabeça."
    )
    input_schema = RecallInput
    side = "server"
    action_class = "read"
    router_hint = "consultar o que já sabe sobre o dono ou algo da vida dele"

    def __init__(self, cerebro: CerebroService) -> None:
        self._cerebro = cerebro

    async def run(self, payload: RecallInput, ctx: ToolCtx) -> str:
        if not payload.busca and not payload.entidade:
            return "[erro] passe busca (palavras) ou entidade (nome)."
        return await self._cerebro.recordar(payload.busca, payload.entidade, payload.incluir_antigas)
