import orjson
import pytest

from application.services.cerebro_service import CerebroService
from application.services.registro_estudo import registrar_correcao
from domain.entities.message import Completion
from infrastructure.memory.cerebro_store import SqliteCerebroStore


class _LLM:
    def __init__(self, resposta: dict) -> None:
        self.resposta, self.chamadas = resposta, 0

    async def complete(self, messages, **kw):
        self.chamadas += 1
        assert kw.get("no_think") is True
        return Completion(content=orjson.dumps(self.resposta).decode(), tool_calls=[], finish_reason="stop")


@pytest.fixture
async def cer(tmp_path) -> CerebroService:
    store = SqliteCerebroStore(str(tmp_path / "cerebro.db"))
    await store.init()
    return CerebroService(store)


async def test_correcao_vira_registro_e_dificuldade(cer):
    await cer.registrar("abrir", "estudo", "Métodos Ágeis", texto="Scrum")
    aberta = await cer.sessao_aberta()
    llm = _LLM({"correcao": True, "tema": "Pilares do Scrum", "acertos": 1, "total": 3,
                "dificuldades": ["acha que a inspeção é o Scrum Master cobrando a equipe"]})
    r = await registrar_correcao(llm, cer, "s1", aberta.entidade, "1) ... 2) ... 3) ...?", "minhas respostas",
                                 "1) certo 2) errado 3) incompleto", [])
    assert r == {"tema": "Pilares do Scrum", "acertos": 1, "total": 3,
                 "dificuldades": ["acha que a inspeção é o Scrum Master cobrando a equipe"]}
    hist = await cer.consultar(tipo="exercicios")
    assert "acertou 1 de 3" in hist and "Pilares do Scrum" in hist
    lembr = await cer.recordar(entidade="Pilares do Scrum")
    assert "cobrando" in lembr


async def test_nao_correcao_nao_grava(cer):
    llm = _LLM({"correcao": False})
    assert await registrar_correcao(llm, cer, "s1", None, "explicação", "ok", "mais explicação", []) is None
    assert "nada registrado" in await cer.consultar(tipo="exercicios")


async def test_modelo_ja_registrou_nao_duplica(cer):
    llm = _LLM({"correcao": True, "tema": "X", "acertos": 1, "total": 1, "dificuldades": []})
    turno = [{"role": "assistant", "tool_calls": [{"function": {"name": "log", "arguments": '{"tipo":"exercicios"}'}}]}]
    assert await registrar_correcao(llm, cer, "s1", None, "pergunta?", "resp", "correção", turno) is None
    assert llm.chamadas == 0


async def test_sem_sessao_aberta_abre_estudo(cer):
    llm = _LLM({"correcao": True, "tema": "Pilares do Scrum", "acertos": 2, "total": 3, "dificuldades": []})
    await registrar_correcao(llm, cer, "s1", None, "perguntas?", "resp", "correção", [])
    aberta = await cer.sessao_aberta()
    assert aberta is not None and aberta.tipo == "estudo"
    assert "acertou 2 de 3" in await cer.consultar(tipo="estudo", ultimo=True)
