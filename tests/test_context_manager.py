from application.services.context_service import ContextManager, _render_turns
from tests.fakes import FakeLLM, fake_count

PROMPT = "voce e um assistente."


def _cm(budget=400, reserved=0, llm=None):
    return ContextManager(
        budget=budget, 
        reserved_output=reserved,
        count_tokens=fake_count, 
        llm=llm or FakeLLM()
    )


def test_build_ordem_canonica_e_prefixo_intacto():
    cm = _cm()
    turno = {"role": "user", "content": "oi"}
    msgs = cm.build(system_static=PROMPT, memory_block="Dono: estuda calculo.",
                    history=[], user_turn=turno)
    assert msgs[0]["role"] == "system" and msgs[0]["content"] == PROMPT
    assert "calculo" in msgs[1]["content"]
    assert msgs[-1] is turno
    assert cm.metrics.static_prefix_tokens > 0

def test_build_corta_historico_no_teto():
    cm = _cm(budget=250, reserved=0)
    history = [{"role": "user", "content": "x" * 40} for _ in range(10)]
    turno = {"role": "user", "content": "agora"}
    msgs = cm.build(system_static="s", memory_block="", history=history, user_turn=turno)
    assert fake_count(msgs) <= cm.input_budget
    assert cm.metrics.dropped_turns > 0
    assert cm.metrics.used_tokens == fake_count(msgs)

async def test_summarize_curto_retorna_sem_chamar_llm():
    llm = FakeLLM()
    cm = _cm(llm=llm)
    raw = "mensagem  qualquer"
    foco = "foco qualquer"
    summary = await cm.summarize(raw=raw, foco=foco)
    assert summary == raw
    assert llm.calls == []

async def test_summarize_longo_chama_llm_e_retorna_resumo():
    llm = FakeLLM()
    cm = _cm(llm=llm)
    raw = "um texto gigante qualquer que consiga estourar o limite" * 1000
    foco = "qualquer"
    summary = await cm.summarize(raw=raw, foco=foco, target_tokens=200)
    assert summary == "RESUMO"
    assert len(llm.calls) == 1

def test_render_turns_serializa():
    out = _render_turns([{"role": "user", "content": "oi"},
                         {"role": "assistant", "content": "ola"}])
    assert out == "user: oi\nassistant: ola"

async def test_roll_summary_sem_dropped_mantem_o_anterior():
    llm = FakeLLM()
    cm = _cm(llm=llm)
    assert await cm.roll_summary("ANTERIOR", dropped=[], foco="x") == "ANTERIOR"
    assert llm.calls == []  

async def test_roll_summary_com_dropped_chama_llm():
    llm = FakeLLM()
    cm = _cm(llm=llm)
    out = await cm.roll_summary("",dropped=[{"role":"user","content":"calculo"}],foco="estudos")
    assert out == "RESUMO" and len(llm.calls) == 1




    