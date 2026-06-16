from application.services.context_service import ContextManager
from tests.fakes import FakeLLM, fake_count

PROMPT = "voce e um assistente."


def _cm(budget=400, reserved=0, llm=None):
    return ContextManager(budget=budget, reserved_output=reserved,
                          count_tokens=fake_count, llm=llm or FakeLLM())


def test_build_ordem_canonica_e_prefixo_intacto():
    cm = _cm()
    turno = {"role": "user", "content": "oi"}
    msgs = cm.build(system_static=PROMPT, memory_block="Dono: estuda calculo.",
                    history=[], user_turn=turno)
    assert msgs[0]["role"] == "system" and msgs[0]["content"] == PROMPT
    assert "calculo" in msgs[1]["content"]
    assert msgs[-1] is turno


def test_build_corta_historico_no_teto():
    cm = _cm(budget=250, reserved=0)
    history = [{"role": "user", "content": "x" * 40} for _ in range(10)]
    turno = {"role": "user", "content": "agora"}
    msgs = cm.build(system_static="s", memory_block="", history=history, user_turn=turno)
    assert fake_count(msgs) <= cm.input_budget
    assert cm.metrics.dropped_turns > 0
    assert cm.metrics.used_tokens == fake_count(msgs)
