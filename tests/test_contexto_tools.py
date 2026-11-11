from application.services.context_service import ContextManager


class _LLM:
    async def complete(self, *a, **k):
        raise AssertionError("não deveria chamar")


def _ctx():
    # 1 token por caractere: deixa a conta previsível
    return ContextManager(budget=1000, reserved_output=500, count_tokens=lambda ms: sum(len(str(m.get("content", ""))) for m in ms), llm=_LLM())


def test_tools_entram_na_conta_da_saida_e_da_janela():
    c = _ctx()
    tools = [{"type": "function", "function": {"name": "x" * 50, "description": "d" * 200}}]
    t = c.tokens_tools(tools)
    assert t > 250
    msgs = [{"role": "system", "content": "s" * 300}]
    assert c.max_saida(msgs, margem=0, minimo=1) == 500                 # sem as tools: cabe a saída inteira
    assert c.max_saida(msgs, margem=0, minimo=1, extra_tokens=t) == 1000 - 300 - t   # com as tools: encolhe
    hist = [{"role": "user", "content": "h" * 100} for _ in range(5)]
    sem = c.build("s" * 50, "", hist, {"role": "user", "content": "u"})
    com = c.build("s" * 50, "", hist, {"role": "user", "content": "u"}, extra_tokens=t)
    assert len(com) < len(sem)                                          # tira histórico pra caber as tools
