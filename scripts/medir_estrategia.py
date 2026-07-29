"""Simula a ESTRATÉGIA FINAL ponta a ponta, por tool, N vezes:

  1. router detecta a intenção (guided_choice) → tool_hint
  2. LLM no AUTO → o que ele fez? (chamou a tool certa? narrou em prosa?)
  3. se chamou certo sozinho → conta 'sozinho', próximo
     se veio prosa (miss)   → FORÇA a tool específica (tool_choice={tool_hint}) → 'retry'
  4. FINAL = sozinho + retry (deve dar ~100%, pois force-specific funciona pra qualquer tool)

Reusa a fiação do medir_toolcall.py (que fica intacto). N=10 por tool, todas as tools.

Uso:
    uv run python scripts/medir_estrategia.py            # todas as tools, N=10
    uv run python scripts/medir_estrategia.py 5          # N=5
    FROM=4 uv run python scripts/medir_estrategia.py 10  # retoma da frase 4 (após queda do vLLM)
"""
import asyncio, sys, os
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))   # raiz do projeto
sys.path.insert(0, _HERE)                     # scripts/ (reusa medir_toolcall)
from medir_toolcall import (
    _build, _router, _SEED, _TESTS, _DELAY, _PROMPT_PAUSE, _MAX_TOKENS, VOICE_STYLE,
)


def _force(tool: str) -> dict:
    return {"type": "function", "function": {"name": tool}}


async def _auto(llm, messages, tools) -> str:
    try:
        comp = await llm.complete(messages, tools=tools, tool_choice="auto", max_tokens=_MAX_TOKENS)
    except Exception:
        return "erro"
    tcs = getattr(comp, "tool_calls", None)
    return tcs[0].name if tcs else "prosa"


async def _force_call(llm, messages, tools, tool: str) -> str:
    try:
        comp = await llm.complete(messages, tools=tools, tool_choice=_force(tool), max_tokens=_MAX_TOKENS)
    except Exception:
        return "erro"
    tcs = getattr(comp, "tool_calls", None)
    return tcs[0].name if tcs else "VAZIO"


async def medir(prompts: list[tuple[str, bool]], n: int, start: int = 1) -> None:
    llm, context, registry, orch = _build()
    active = registry.for_device(None)
    tools = active.as_openai_tools()
    system = orch._system_prompt() + "\n\n" + VOICE_STYLE   # caminho REAL da voz

    total = len(prompts)
    print(f"ESTRATÉGIA: router → auto → (miss) força específica · N={n} · começando na frase {start}\n")
    resumo: list[tuple] = []
    dead = 0

    for idx, (prompt, needs_img) in enumerate(prompts, 1):
        if idx < start:
            continue
        r = await _router(llm, active, prompt)
        history = _SEED if needs_img else []
        base = context.build(system, "", history, {"role": "user", "content": prompt})
        is_tool = r != "NENHUMA"

        tag = "  [env: img semeada]" if needs_img else ""
        print(f'=== [{idx}/{total}] "{prompt}"')
        print(f'    router detectou → {r}{tag}')
        sozinho = retry = final = 0
        for i in range(1, n + 1):
            la = await _auto(llm, base, tools)

            if not is_tool:                       # chitchat: prosa é o certo
                ok = la == "prosa"
                sozinho += ok; final += ok
                print(f"   {i:>2}  auto={la:<13} {'✓ (sem tool, certo)' if ok else '✗ chamou tool à toa'}", flush=True)
            elif la == r:                         # auto acertou a tool sozinho
                sozinho += 1; final += 1
                print(f"   {i:>2}  auto={la:<13} ✓ sozinho", flush=True)
            else:                                 # miss (prosa/outra) → força a específica
                lf = await _force_call(llm, base, tools, r)
                ok = lf == r
                retry += ok; final += ok
                print(f"   {i:>2}  auto={la:<13} → força {r} → {lf:<13} {'✓ retry' if ok else '✗ FALHOU'}", flush=True)

            dead = dead + 1 if (la == "erro") else 0
            if dead >= 6:
                print(f"\n⚠ vLLM parece ter CAÍDO na frase [{idx}]. Reinicie e RETOME:")
                print(f"   FROM={idx} uv run python scripts/medir_estrategia.py {n}\n")
                _print_resumo(resumo, n); return
            await asyncio.sleep(_DELAY)

        print(f"   → sozinho {sozinho}/{n} · retry {retry}/{n} · FINAL {final}/{n}\n", flush=True)
        resumo.append((prompt, r, sozinho, retry, final))
        await asyncio.sleep(_PROMPT_PAUSE)

    _print_resumo(resumo, n)


def _print_resumo(resumo: list[tuple], n: int) -> None:
    print("\n===== RESUMO (estratégia final) =====")
    print(f"{'prompt':<40} {'router':>13} {'sozinho':>8} {'retry':>7} {'FINAL':>7}")
    print("─" * 80)
    for prompt, r, sz, rt, fn in resumo:
        print(f"{prompt[:40]:<40} {r:>13} {f'{sz}/{n}':>8} {f'{rt}/{n}':>7} {f'{fn}/{n}':>7}")


if __name__ == "__main__":
    args = sys.argv[1:]
    n = next((int(a) for a in args if a.isdigit()), 10)
    start = int(os.getenv("FROM", "1"))
    asyncio.run(medir(_TESTS, n, start))
