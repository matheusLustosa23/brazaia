import json
import os
import time

from pydantic import BaseModel, Field

from domain.tools.base import Tool
from domain.tools.guard import ToolCtx

# arquivo de observação: cada salvar que DISPAROU de verdade (pelo agente rodando) vira uma linha aqui.
LOG = os.environ.get("EXP_SALVAR_LOG", "/tmp/salvar_fluxo.jsonl")


class SalvarInput(BaseModel):
    texto: str = Field(description="A frase a guardar, autossuficiente e normalizada.")


class SalvarTool(Tool[SalvarInput]):
    """Tool de PROVA (pesquisa do cérebro): grava uma memória em texto livre. Registrada no agente real; cada
    chamada (via run_react, pelo HTTP) é anotada no LOG pra o experimento observar o fluxo verdadeiro."""
    name = "salvar"
    description = ("Grava UMA memória sobre o dono, em texto livre. Chame quando o dono contar um fato da vida "
                   "dele e o significado estiver claro.")
    input_schema = SalvarInput
    side = "server"
    action_class = "reversible"
    router_hint = "guardar/anotar um fato do dono"

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run(self, payload: SalvarInput, ctx: ToolCtx) -> str:
        self.calls.append(payload.texto)
        try:                                       # log é só observação; nunca pode derrubar o save
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), "fala": ctx.fala_do_usuario, "texto": payload.texto},
                                   ensure_ascii=False) + "\n")
        except OSError:
            pass
        return f"[salvo] {payload.texto}"
