from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from application.services.lembretes import antecedencia_de, fmt_lembrete, quando_futuro
from domain.tools.base import Tool
from domain.tools.guard import ToolCtx


class RemindInput(BaseModel):
    # o modelo chama o campo de "action" (3/3 no teste real, tool com nome em inglês) — aceita os dois nomes
    model_config = ConfigDict(populate_by_name=True)
    acao: Literal["criar", "listar", "cancelar"] = Field(default="criar", validation_alias=AliasChoices("acao", "action"), description=(
        "criar = novo lembrete · listar = os que estão ativos · cancelar = desliga um (#id do listar)."))
    texto: str = Field(default="", description=(
        "O que lembrar, curto e autossuficiente (é o título da notificação). Ex.: 'Pagar conta de luz'."))
    quando: str = Field(default="", description=(
        "Quando a coisa VENCE/ACONTECE, do jeito que ele falou: 'amanhã 9h', 'dia 10', 'sexta 18:00', '25/12', "
        "'em 2 horas', '2026-12-01 14:00'. Sem hora → 9h. Recorrente: a 1ª ocorrência ('dia 10')."))
    repetir: Literal["", "diaria", "semanal", "mensal", "anual"] = Field(default="", description=(
        "'' = uma vez só. 'todo mês' → mensal; 'toda segunda' → semanal; 'todo dia' → diaria."))
    antes: str = Field(default="", description=(
        "Com quanta antecedência avisar ('2 dias', '1 hora', '30 min'). Vazio = na hora."))
    id: int | None = Field(default=None, description="Só pra cancelar: o #id do lembrete.")


class RemindTool(Tool[RemindInput]):
    name = "remind"
    description = (
        "LEMBRETE QUE AVISA: o servidor manda uma notificação pro celular/devices na hora certa (vencimento de "
        "conta, compromisso, remédio...). Use quando ele pedir 'me lembra', 'me avisa', 'não me deixa esquecer'.\n"
        "Ex.: 'a conta de luz vence todo dia 10, me avisa 2 dias antes' → remind(texto='Pagar conta de luz', "
        "quando='dia 10', repetir='mensal', antes='2 dias') · 'me lembra amanhã às 15h de ligar pro João' → "
        "remind(texto='Ligar pro João', quando='amanhã 15:00').\n"
        "Confira no resultado a data calculada e repita pra ele. NÃO diga que criou sem chamar."
    )
    input_schema = RemindInput
    side = "server"
    action_class = "reversible"
    router_hint = "criar, listar ou cancelar lembrete/aviso com data"

    def __init__(self, store) -> None:
        self._store = store

    async def run(self, payload: RemindInput, ctx: ToolCtx) -> str:
        if payload.acao == "listar":
            ativos = await self._store.ativos()
            return ("[lembretes] ativos:\n" + "\n".join(f"- {fmt_lembrete(l)}" for l in ativos)) if ativos \
                else "[lembretes] nenhum lembrete ativo."
        if payload.acao == "cancelar":
            if payload.id is None:
                return "[erro] falta o #id — chame remind(acao=listar) pra ver os ids."
            l = await self._store.pegar(payload.id)
            if l is None or not await self._store.desativar(payload.id):
                return f"[erro] não há lembrete ativo #{payload.id}."
            return f"[lembretes] cancelado: {fmt_lembrete(l)}"
        if not payload.texto.strip():
            return "[erro] falta o texto do lembrete — nada foi criado."
        try:
            alvo = quando_futuro(payload.quando)
            antes = antecedencia_de(payload.antes)
        except ValueError as e:
            return f"[erro] {e} — nada foi criado."
        dia = alvo.day if payload.repetir in ("mensal", "anual") else None
        l = await self._store.criar(payload.texto.strip(), alvo.timestamp(), payload.repetir, antes, dia,
                                    fonte=ctx.session_id or "")
        return f"[lembretes] criado: {fmt_lembrete(l)}. O aviso chega como notificação nos devices conectados."
