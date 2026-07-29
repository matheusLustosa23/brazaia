"""Teste de EXECUÇÃO plano-dirigida, ponta a ponta:

  1. router monta o PLANO (upfront, response_format+maxItems)
  2. pra cada tool do plano: o LLM emite o tool_call (auto → force-no-miss)
  3. GUARD `before`: valida os args ANTES de executar — o id citado é REAL (∈ ids_reais)
     ou INVENTADO? (é aqui que a honestidade no encadeamento é checada)
  4. executa a tool DE VERDADE (registry.run); degrada p/ resultado sintético se falhar (sem device)
  5. o id REAL produzido (render/capture) entra em ids_reais → o passo seguinte tem que usá-lo

Foca em cadeias que produzem-e-consomem id (render/capture → notify/open). Caminho da voz (com VOICE_STYLE).

Uso:
    uv run python scripts/medir_execucao.py        # N=2 por cenário
    uv run python scripts/medir_execucao.py 3
"""
import asyncio, sys, os, json, re
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
from medir_toolcall import _build, VOICE_STYLE, _MAX_TOKENS, _DELAY
from medir_planner import _plano
from application.services.helpers import persist_image

_CENARIOS = [
    "gere um problema de limites e envie pro celular",
    "renderiza a fórmula de bhaskara e abre em tela cheia no celular",
    "tira uma foto, notifica no celular e abre em tela cheia",
]

# fallback se a execução real falhar (ex.: sem device) — produtores trazem um id
_FALLBACK = {
    "render_math":   "imagem pronta (image_id=abc123def456). Use em 'notify' ou 'open_image'.",
    "capture_image": "frame capturado (image_id=def456abc123).",
    "notify":        "notificação enviada ao device.",
    "open_image":    "imagem aberta em tela cheia no device.",
    "display_math":  "página de matemática aberta.",
    "display_page":  "página aberta.",
    "lembrar":       "guardado na memória.",
    "load_image":    "imagem recarregada (image_id=abc123def456).",
}


def _force(t: str) -> dict:
    return {"type": "function", "function": {"name": t}}


def _args(tc) -> dict:
    a = getattr(tc, "arguments", None) or "{}"
    try:
        return json.loads(a) if isinstance(a, str) else (a or {})
    except Exception:
        return {"_raw_invalido": a}


def _extract_id(result: str):
    m = re.search(r"image_id[=:\s]+([0-9a-f]{12})", result or "")
    return m.group(1) if m else None


def _check_id(tool_name: str, args: dict, ids_reais: set) -> tuple[bool, str]:
    """O que a G3 (before de id, AINDA NÃO implementada nas tools) FARIA: validar id ∈ ids_reais.
    Hoje o tool.before real é default ok=True — quem pega o id inventado é a EXECUÇÃO (o image_index)."""
    for k, v in (args or {}).items():
        if "image_id" in k.lower() and isinstance(v, str) and v:
            if v in ids_reais:
                return True, f"image_id={v} ∈ ids_reais → REAL ✓"
            return False, f"image_id={v} ✗ INVENTADO (não está em ids_reais={ids_reais or '∅'}) → guard BLOQUEIA"
    return True, "sem id pra validar → ok"


async def _emit(llm, messages, tools, expected):
    """auto → se prosa, force a tool esperada. Retorna (comp, tool_call, via)."""
    comp = await llm.complete(messages, tools=tools, tool_choice="auto", max_tokens=_MAX_TOKENS)
    tcs = getattr(comp, "tool_calls", None)
    if tcs:
        return comp, tcs[0], "auto        "
    comp = await llm.complete(messages, tools=tools, tool_choice=_force(expected), max_tokens=_MAX_TOKENS)
    tcs = getattr(comp, "tool_calls", None)
    return (comp, tcs[0], f"force({expected})") if tcs else (comp, None, "VAZIO")


async def _executar(llm, active, tools, system, user_msg, plano, image_index):
    ids_reais: set[str] = set()
    convo: list[dict] = []
    for i, expected in enumerate(plano, 1):
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user_msg}] + convo
        comp, tc, via = await _emit(llm, messages, tools, expected)
        if tc is None:
            print(f"    passo{i}: {via} — sem tool_call, parou"); break

        args = _args(tc)
        print(f"    passo{i}: {via} → {tc.name}  args={args}")

        _, msg = _check_id(tc.name, args, ids_reais)             # o que a G3 FARIA (hoje before real = ok)
        print(f"            check-id (G3 faria) → {msg}")

        try:                                                     # LLM executando a tool de verdade
            result = await active.run(tc.name, args)
            fonte = "REAL"
        except Exception as e:
            result = _FALLBACK.get(tc.name, "ok")
            fonte = f"sintético ({type(e).__name__})"

        # compacta o resultado ANTES do histórico (igual ao orchestrator): imagem → persist → id + placeholder
        if isinstance(result, str) and result.startswith("data:image"):
            img_id = persist_image(result, "test-exec", None, image_index)
            ids_reais.add(img_id)
            hist = f"[imagem capturada · image_id={img_id}]"
            print(f"            exec [{fonte}] → imagem persistida · image_id={img_id}")
        else:
            for m in re.findall(r"image_id[=:\s]+([0-9a-f]{12})", result or ""):
                ids_reais.add(m)
            hist = (result or "")[:200]
            print(f"            exec [{fonte}] → {hist[:72]}")

        tid = getattr(tc, "id", None) or f"call_{i}"
        a = getattr(tc, "arguments", None) or "{}"
        convo.append({"role": "assistant", "content": getattr(comp, "content", "") or "",
                      "tool_calls": [{"id": tid, "type": "function",
                                      "function": {"name": tc.name, "arguments": a if isinstance(a, str) else json.dumps(a)}}]})
        convo.append({"role": "tool", "tool_call_id": tid, "content": hist})
        await asyncio.sleep(_DELAY)


async def medir(n: int) -> None:
    llm, context, registry, orch = _build()
    active = registry.for_device(None)
    tools = active.as_openai_tools()
    system = orch._system_prompt() + "\n\n" + VOICE_STYLE
    image_index = orch._image_index

    print(f"EXECUÇÃO plano-dirigida · plano→auto/force→check-id→exec · N={n} · caminho da voz")
    print("(nota: 'before' real das tools = ok=True; o check-id abaixo é o que a G3 faria)\n")
    for prompt in _CENARIOS:
        print(f'════════ "{prompt}"')
        plano = await _plano(llm, active, prompt)
        print(f"    PLANO (router): {plano}")
        for run in range(1, n + 1):
            print(f"\n  ▶ run {run}")
            await _executar(llm, active, tools, system, prompt, plano, image_index)
        print()


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 2
    asyncio.run(medir(n))
