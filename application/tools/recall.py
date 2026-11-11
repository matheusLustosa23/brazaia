from pydantic import BaseModel, Field

from application.services.cerebro_service import CerebroService
from domain.tools.base import Tool
from domain.tools.guard import ToolCtx


class RecallInput(BaseModel):
    busca: str = Field(description=(
        "O assunto, do jeito que o dono falou — NÃO precisa ser o nome exato de como foi salvo. "
        "Ex.: 'academia', 'tríceps', 'picpay', 'audiência', 'cálculo'. A busca é parcial, sem acento e por área."))
    periodo: str | None = Field(default=None, description=(
        "Só quando a pergunta tem tempo: 'hoje', 'semana', 'mes', 'ano' ou uma data (28/10). Vazio = tudo."))


class RecallTool(Tool[RecallInput]):
    name = "recall"
    description = (
        "A busca na memória do dono: devolve TUDO relacionado ao assunto (o que ele é/sabe E o que ele fez), "
        "agrupado. A 1ª linha diz quantos ASSUNTOS distintos apareceram.\n"
        "USE antes de responder algo do passado/dele, e ANTES de salvar (pra ver o que já existe).\n"
        "DECIDA pela 1ª linha: 1 assunto → responda/aja com o que voltou; 2+ assuntos → PERGUNTE ao dono qual "
        "ele quer, mostrando as opções (nunca escolha sozinho quando há mais de um). Nada encontrado → diga que "
        "não sabe, nunca complete de cabeça."
    )
    input_schema = RecallInput
    side = "server"
    action_class = "read"
    router_hint = "consultar a memória do dono (o que sabe, o que fez, treinos, contas, compromissos)"

    def __init__(self, cerebro: CerebroService) -> None:
        self._cerebro = cerebro

    async def run(self, payload: RecallInput, ctx: ToolCtx) -> str:
        if not payload.busca.strip():
            return "[erro] passe o assunto a buscar."
        return await self._cerebro.buscar_tudo(payload.busca, payload.periodo)
