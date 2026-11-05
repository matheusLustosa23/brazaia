from typing import Literal

from pydantic import BaseModel, Field

from application.services.cerebro_service import CerebroService
from domain.tools.base import Tool
from domain.tools.guard import ToolCtx


class LogInput(BaseModel):
    acao: Literal["registrar", "abrir", "fechar"] = Field(default="registrar", description=(
        "abrir = COMEÇOU algo que dura ('vou começar o treino de peito', 'começando a estudar cálculo') · "
        "registrar = UM evento que aconteceu (uma série, um exercício feito); entra sozinho na sessão aberta · "
        "fechar = TERMINOU ('acabei o treino')."))
    tipo: str | None = Field(default=None, description=(
        "O que é: treino (a sessão de academia), serie (um exercício feito), estudo, corrida... "
        "Obrigatório em abrir/registrar."))
    assunto: str | None = Field(default=None, description=(
        "DE QUÊ: o exercício ('Supino reto'), o grupo do treino ('Peito'), a disciplina ('Cálculo'). "
        "Use sempre o MESMO nome pra mesma coisa."))
    dados: dict[str, float | int | str] = Field(default_factory=dict, description=(
        "Os NÚMEROS, com estas chaves quando couber: series, reps, carga_kg, duracao_min, distancia_km. "
        "Ex.: '3 de 12 com 20 quilos' → {\"series\": 3, \"reps\": 12, \"carga_kg\": 20}."))
    texto: str = Field(default="", description="O comentário dele, curto ('a última foi difícil'). Vazio se não houve.")
    quando: str | None = Field(default=None, description=(
        "Só se NÃO foi agora: 'ontem', 'ontem 18:40', '28/10', '2026-10-28 19:00'. Vazio = agora."))
    corrige: int | None = Field(default=None, description=(
        "CORREÇÃO: o #id do registro errado (ele fica no histórico, marcado). Mande o registro certo inteiro."))


class LogTool(Tool[LogInput]):
    name = "log"
    description = (
        "Registra no diário algo que ACONTECEU, com data e números (treino, série de exercício, sessão de "
        "estudo...). É diferente de remember: remember = o que é verdade sobre ele; log = o que ele FEZ.\n"
        "Ex.: 'vou começar o treino de peito' → log(acao=abrir, tipo=treino, assunto=Peito) · "
        "'fiz supino 3 de 12 com 20, a última foi difícil' → log(tipo=serie, assunto=Supino reto, "
        "dados={series:3, reps:12, carga_kg:20}, texto=a última foi difícil) · 'acabei' → log(acao=fechar).\n"
        "NÃO diga que registrou sem CHAMAR — a confirmação vem do resultado."
    )
    input_schema = LogInput
    side = "server"
    action_class = "reversible"
    router_hint = "registrar treino, série, sessão de estudo ou evento com data e números"

    def __init__(self, cerebro: CerebroService) -> None:
        self._cerebro = cerebro

    async def run(self, payload: LogInput, ctx: ToolCtx) -> str:
        return await self._cerebro.registrar(payload.acao, payload.tipo, payload.assunto, dict(payload.dados),
                                             payload.texto, payload.quando, payload.corrige, fonte=ctx.session_id)
