"""Mede o ROUTER_UPFRONT (planner): o A3B consegue montar o PLANO ordenado de tools que
o pedido exige — incluindo repetição (notify ×2) e término (lista vazia p/ chitchat)?

Usa guided JSON (força a saída a ser {"plano": [<tools válidas>]}). Roda cada pedido N vezes
pra ver consistência. Imprime o plano de cada run + o resumo (distribuição).

Reusa a fiação do medir_toolcall.py. Uso:
    uv run python scripts/medir_planner.py          # N=3
    uv run python scripts/medir_planner.py 5        # N=5
"""
import asyncio, sys, os, json
from collections import Counter
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
from medir_toolcall import _build, _HINTS, _DELAY

_INSTR_PLAN = (
    "Você planeja QUAIS ferramentas o pedido do usuário exige, EM ORDEM de execução.\n"
    "- Liste todas as necessárias, na ordem certa (ex.: gerar antes de enviar).\n"
    "- PODE REPETIR a mesma ferramenta se o pedido pedir a ação mais de uma vez "
    "(ex.: 'avisa X e depois avisa Y' = notify duas vezes).\n"
    "- Se o pedido é conversa/pergunta que se responde falando, o plano é vazio [].\n"
    "Ferramentas:\n{tools}"
)

# (pedido, plano esperado ~ pra você conferir; o teste NÃO usa, só imprime pra comparar)
_TESTES = [
    ("gere um problema de limites e envie pro celular",                      "[render_math, notify]"),
    ("captura uma foto, manda como notificação e abre em tela cheia",        "[capture_image, notify, open_image]"),
    ("renderiza a fórmula de bhaskara e mostra na tela do celular",          "[render_math, display_math] (ambíguo)"),
    ("avisa no celular que o build passou e depois avisa que o deploy subiu", "[notify, notify]  ← o caso do dono"),
    ("renderiza um problema de equação aleatório",                           "[render_math]"),
    ("anota que amanhã tenho médico",                                        "[lembrar]"),
    ("oi, tudo bem?",                                                        "[]"),
    ("que horas são?",                                                       "[]"),
]


async def _plano(llm, active, pedido: str) -> list:
    names = active.get_all_tool_names()
    tools_txt = "\n".join(f"- {n}: {_HINTS[n]}" for n in names)
    # response_format json_schema FORÇA o enum (nomes de tool reais); maxItems evita runaway (loop de repetição)
    schema = {
        "type": "object",
        "properties": {"plano": {"type": "array", "items": {"type": "string", "enum": names}, "maxItems": 5}},
        "required": ["plano"],
    }
    try:
        comp = await llm.complete(
            [{"role": "system", "content": _INSTR_PLAN.format(tools=tools_txt)},
             {"role": "user", "content": pedido}],
            temperature=0.0, max_tokens=64,
            extra_body={"response_format": {"type": "json_schema",
                                            "json_schema": {"name": "plano", "schema": schema}}},
        )
        return json.loads(comp.content or "{}").get("plano", [])
    except Exception as e:
        return [f"ERRO:{type(e).__name__}"]


async def medir(n: int) -> None:
    llm, context, registry, orch = _build()
    active = registry.for_device(None)

    print(f"ROUTER_UPFRONT (planner) · guided JSON · N={n} por pedido\n")
    for pedido, esperado in _TESTES:
        print(f'=== "{pedido}"')
        print(f"    esperado ~ {esperado}")
        planos = []
        for _ in range(n):
            p = await _plano(llm, active, pedido)
            print(f"    plano: {p}", flush=True)
            planos.append(tuple(p))
            await asyncio.sleep(_DELAY)
        print(f"    → distribuição: {dict(Counter(planos))}\n", flush=True)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 3
    asyncio.run(medir(n))
