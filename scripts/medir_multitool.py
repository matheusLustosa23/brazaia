"""Simula o LOOP multi-tool com a estratégia route_next + force-no-miss, COM e SEM voice_style.

Por cenário (que exige VÁRIAS tools em ordem), a cada passo do loop:
  1. auto → chamou uma tool? segue. veio prosa?
  2. route_next(pedido, o_que_já_foi_feito) → próxima tool | NENHUMA
  3. se tool → força a específica ; se NENHUMA → fim (pedido atendido)
  4. resultado sintético da tool entra no histórico → próximo passo
Imprime CADA passo. Compara a sequência produzida COM × SEM voice_style.

Reusa a fiação do medir_toolcall.py (intacto). Uso:
    uv run python scripts/medir_multitool.py         # N=3 por cenário/condição
    uv run python scripts/medir_multitool.py 5       # N=5
"""
import asyncio, sys, os, json
from collections import Counter
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
from medir_toolcall import _build, _HINTS, _MAX_TOKENS, _DELAY, VOICE_STYLE

_MAX_STEPS = 5   # trava anti-loop-infinito

# Cenários que exigem MÚLTIPLAS tools em ordem (os 2 do dono + 1 de matemática)
_CENARIOS = [
    "gere um problema de limites e envie pro celular",
    "captura uma foto, manda como notificação no celular e abre em tela cheia",
    "renderiza a fórmula de bhaskara e mostra na tela do celular",
]

# Resultado SINTÉTICO de cada tool (pro loop poder seguir pro próximo passo)
_RESULT = {
    "render_math":   "imagem pronta (image_id=abc123def456). Use em 'notify' ou 'open_image'.",
    "capture_image": "[imagem capturada · image_id=def456abc123]",
    "notify":        "notificação enviada ao device.",
    "open_image":    "imagem aberta em tela cheia no device.",
    "display_math":  "página de matemática aberta no device.",
    "display_page":  "página aberta no device.",
    "lembrar":       "guardado na memória.",
    "load_image":    "[imagem carregada · image_id=abc123def456]",
}

_INSTR_NEXT = (
    "Você planeja ferramentas passo a passo. Dado o pedido do usuário e o que JÁ foi feito neste "
    "turno, diga a PRÓXIMA ferramenta necessária, ou NENHUMA se o pedido já foi totalmente atendido. "
    "Responda SÓ com o rótulo."
)


async def _complete(llm, messages, tools, tool_choice):
    try:
        return await llm.complete(messages, tools=tools, tool_choice=tool_choice, max_tokens=_MAX_TOKENS)
    except Exception:
        return None


async def _route_next(llm, active, user_msg, done):
    names = active.get_all_tool_names()
    feitas = ", ".join(done) if done else "nenhuma ainda"
    tools_txt = "\n".join(f"- {n}: {_HINTS[n]}" for n in names)
    contexto = f'Pedido: "{user_msg}"\nJá executado neste turno: {feitas}\nFerramentas:\n{tools_txt}'
    try:
        comp = await llm.complete(
            [{"role": "system", "content": _INSTR_NEXT}, {"role": "user", "content": contexto}],
            temperature=0.0, max_tokens=16, extra_body={"guided_choice": names + ["NENHUMA"]},
        )
    except Exception:
        return None
    label = (comp.content or "").strip()
    return None if label == "NENHUMA" or label not in names else label


def _tc_dict(tc, step):
    tid = getattr(tc, "id", None) or f"call_{step}"
    args = getattr(tc, "arguments", None) or "{}"
    if not isinstance(args, str):
        args = json.dumps(args)
    return tid, {"id": tid, "type": "function", "function": {"name": tc.name, "arguments": args}}


async def _loop(llm, active, tools, system, user_msg):
    """Roda o loop multi-tool e imprime cada passo. Retorna a sequência de tools chamadas."""
    convo: list[dict] = []
    done: list[str] = []
    for step in range(1, _MAX_STEPS + 1):
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user_msg}] + convo
        comp = await _complete(llm, messages, tools, "auto")
        tcs = getattr(comp, "tool_calls", None) if comp else None

        if tcs:
            tc = tcs[0]; via = "auto        "
        else:
            hint = await _route_next(llm, active, user_msg, done)
            if hint is None:
                print(f"      passo{step}: auto=prosa    → route_next=NENHUMA → FIM ✅")
                break
            comp = await _complete(llm, messages, tools, {"type": "function", "function": {"name": hint}})
            tcs = getattr(comp, "tool_calls", None) if comp else None
            if not tcs:
                print(f"      passo{step}: auto=prosa    → force({hint}) → VAZIO ✗ (parou)")
                break
            tc = tcs[0]; via = f"force({hint})"
        print(f"      passo{step}: {via} → {tc.name}")
        done.append(tc.name)
        await asyncio.sleep(_DELAY)
        tid, tcd = _tc_dict(tc, step)
        convo.append({"role": "assistant", "content": getattr(comp, "content", "") or "", "tool_calls": [tcd]})
        convo.append({"role": "tool", "tool_call_id": tid, "content": _RESULT.get(tc.name, "ok")})
    else:
        print(f"      ⚠ atingiu MAX_STEPS={_MAX_STEPS} (não terminou)")
    return tuple(done)


async def medir(n: int) -> None:
    llm, context, registry, orch = _build()
    active = registry.for_device(None)
    tools = active.as_openai_tools()
    sys_sem = orch._system_prompt()
    sys_com = sys_sem + "\n\n" + VOICE_STYLE

    print(f"LOOP multi-tool · route_next + force-no-miss · N={n} por condição · MAX_STEPS={_MAX_STEPS}\n")
    for prompt in _CENARIOS:
        print(f'════════ "{prompt}"')
        for nome, system in [("COM voice_style", sys_com), ("SEM voice_style", sys_sem)]:
            print(f"\n  ▶ {nome}")
            seqs = []
            for run in range(1, n + 1):
                print(f"    run {run}:")
                seq = await _loop(llm, active, tools, system, prompt)
                print(f"      ⇒ sequência: {' → '.join(seq) if seq else '(nada)'}")
                seqs.append(seq)
            print(f"    resumo {nome}: {dict(Counter(seqs))}")
        print()


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 3
    asyncio.run(medir(n))
