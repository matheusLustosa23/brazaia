from pydantic import BaseModel, Field

from application.services.cerebro_service import CerebroService
from domain.tools.base import Tool
from domain.tools.guard import ToolCtx


class RememberInput(BaseModel):
    texto: str = Field(description=(
        "UMA frase curta e autossuficiente, do jeito que vai ser lida depois. "
        "Ex.: 'prefere resposta direta, sem enrolação' · 'trabalha como engenheiro de dados na Disbral'."))
    categoria: str = Field(description=(
        "Rótulo curto do assunto da frase. Prefira: nome, trabalho, estudo, rotina, preferencia, objetivo, saude, "
        "relacao, execucao, observacao. Pode criar outro se nenhum servir."))
    entidade: str = Field(default="Você", description=(
        "DE QUEM/DO QUE é a frase. O próprio dono = 'Você' (padrão). Outra coisa = o nome dela "
        "('Supino reto', 'Projeto Ágil', 'Ana'). Mesmo nome = mesma entidade."))
    tipo: str | None = Field(default=None, description=(
        "Só quando a entidade é NOVA: pessoa, exercicio, grupo muscular, disciplina, tema, projeto, empresa, "
        "ferramenta, fluxo, lugar, meta, financa."))
    substitui: int | None = Field(default=None, description=(
        "CORREÇÃO: o #id da observação que esta frase substitui (está no bloco MEMÓRIA ou num recall). "
        "A antiga não some — fica no histórico. Omita se é algo novo."))
    relacao: str | None = Field(default=None, description=(
        "Opcional: liga a entidade a OUTRA COISA que existe por si (empresa, pessoa, grupo muscular, disciplina). "
        "Ex.: 'trabalha em' + com='Disbral' · 'grupo' + com='Peito'. NÃO use pra atributo (nome, idade, cor)."))
    com: str | None = Field(default=None, description="Opcional, junto com relacao: o nome da outra entidade. Ex.: 'Peito'.")


class RememberTool(Tool[RememberInput]):
    name = "remember"
    description = (
        "Grava no cérebro UMA observação sobre o dono ou sobre algo da vida dele (pessoa, exercício, disciplina, "
        "projeto...). USE quando o dono pedir pra lembrar/guardar/anotar, ou contar algo estável sobre si "
        "(nome, trabalho, rotina, preferência, objetivo). Uma chamada por fato.\n"
        "Mudou algo que você já sabia (está no bloco MEMÓRIA com #id)? → remember(texto=novo, substitui=#id).\n"
        "NÃO diga que guardou sem CHAMAR esta ferramenta — a confirmação vem do resultado dela."
    )
    input_schema = RememberInput
    side = "server"
    action_class = "reversible"
    router_hint = "anotar, guardar ou lembrar um fato, preferência ou dado do dono"

    def __init__(self, cerebro: CerebroService) -> None:
        self._cerebro = cerebro

    async def run(self, payload: RememberInput, ctx: ToolCtx) -> str:
        return await self._cerebro.lembrar(
            payload.texto, payload.categoria, payload.entidade, payload.tipo, payload.substitui,
            payload.relacao, payload.com, fonte=ctx.session_id)
