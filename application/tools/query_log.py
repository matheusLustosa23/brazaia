from pydantic import BaseModel, Field

from application.services.cerebro_service import CerebroService
from domain.tools.base import Tool
from domain.tools.guard import ToolCtx


class QueryLogInput(BaseModel):
    tipo: str | None = Field(default=None, description="treino, serie, estudo... (vazio = qualquer tipo).")
    assunto: str | None = Field(default=None, description="O exercício, grupo ou disciplina: 'Supino reto', 'Peito'.")
    ultimo: bool = Field(default=False, description=(
        "true = só a vez MAIS RECENTE ('último treino de peito', 'última vez no supino')."))
    desde: str | None = Field(default=None, description=(
        "Início do período: hoje, semana, mes, ano, ou uma data (28/10). Pra 'quanto subi este mês' → mes."))
    ate: str | None = Field(default=None, description="Fim do período (data), se ele pediu um intervalo.")


class QueryLogTool(Tool[QueryLogInput]):
    name = "query_log"
    description = (
        "Consulta o diário (o que ele FEZ, com data e números). Ex.: 'qual foi meu último treino de peito' → "
        "query_log(tipo=treino, assunto=Peito, ultimo=true) · 'como foi a última vez no supino' → "
        "query_log(tipo=serie, assunto=Supino reto, ultimo=true) · 'quanto subi no supino este mês' → "
        "query_log(tipo=serie, assunto=Supino reto, desde=mes).\n"
        "Responda SÓ com o que voltar (datas e números exatos); vazio = diga que não tem registro."
    )
    input_schema = QueryLogInput
    side = "server"
    action_class = "read"
    router_hint = "consultar treinos, séries e sessões registradas (último, período, progresso)"

    def __init__(self, cerebro: CerebroService) -> None:
        self._cerebro = cerebro

    async def run(self, payload: QueryLogInput, ctx: ToolCtx) -> str:
        return await self._cerebro.consultar(payload.tipo, payload.assunto, payload.ultimo, payload.desde, payload.ate)
