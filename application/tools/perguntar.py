import json
import os
import time

from pydantic import BaseModel, Field

from domain.tools.base import Tool
from domain.tools.guard import ToolCtx

LOG = os.environ.get("EXP_PERGUNTAR_LOG", "/tmp/perguntar_fluxo.jsonl")


class PerguntarInput(BaseModel):
    pergunta: str = Field(description="A pergunta curta e objetiva ao dono.")


class PerguntarTool(Tool[PerguntarInput]):
    """Tool de PROVA (pesquisa do cérebro): o modelo PERGUNTA ao dono em vez de adivinhar e salvar errado.
    Dar a pergunta como TOOL (e não só instrução) é o que faz o modelo esclarecer o ambíguo (medido)."""
    name = "perguntar"
    description = ("Faz UMA pergunta ao dono e espera a resposta. USE quando o que ele disse tem mais de uma "
                   "leitura, ou falta um detalhe que mudaria o que ficaria guardado — em vez de adivinhar.")
    input_schema = PerguntarInput
    side = "server"
    action_class = "read"
    router_hint = "perguntar ao dono quando o que ele disse é ambíguo"

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run(self, payload: PerguntarInput, ctx: ToolCtx) -> str:
        self.calls.append(payload.pergunta)
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), "fala": ctx.fala_do_usuario, "pergunta": payload.pergunta},
                                   ensure_ascii=False) + "\n")
        except OSError:
            pass
        return f"[pergunta ao dono — aguarde a resposta] {payload.pergunta}"
