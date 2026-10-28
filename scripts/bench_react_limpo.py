"""Benchmark 3/3 — orchestrator LIMPO (ReAct single-pass).

Sem router.plan antes, sem juiz no meio. Só o loop ReAct:
  stream(tools, tool_choice="auto")  → se chamou tool, executa e devolve o resultado → responde.
Conversa = 1 chamada (≈ piso). Tool = 2 chamadas (decide+chama, depois responde).

Formato CLI: o texto é streamado (typewriter) e as function calls aparecem no terminal
conforme o modelo decide. Mede TTFT (1º token/decisão) + total + nº de chamadas de LLM.

Rodar (onde o vLLM estiver acessível):
    VLLM_BASE_URL=http://iobraza:8002/v1 VLLM_MODEL=qwen35-27b-abl python3 scripts/bench_react_limpo.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # raiz no path

from openai import OpenAI
from application.prompts import build_system

BASE = os.getenv("VLLM_BASE_URL", "http://iobraza:8002/v1")
MODEL = os.getenv("VLLM_MODEL", os.getenv("MODEL_NAME", "qwen35-27b-abl"))
KEY = os.getenv("VLLM_API_KEY", "change-me")
NO_THINK = os.getenv("NO_THINK", "1") != "0"
MAX_STEPS = 4

# Ferramentas (schema realista; execução SIMULADA — o foco é a latência do fluxo, não a tool real)
TOOLS = [
    {"type": "function", "function": {
        "name": "lembrar", "description": "Registra/guarda um fato ou memória do usuário (ex.: um treino feito).",
        "parameters": {"type": "object", "properties": {"fato": {"type": "string"}}, "required": ["fato"]}}},
    {"type": "function", "function": {
        "name": "notify", "description": "Envia uma notificação push ao device do usuário.",
        "parameters": {"type": "object", "properties": {"titulo": {"type": "string"}, "corpo": {"type": "string"}},
                       "required": ["titulo", "corpo"]}}},
    {"type": "function", "function": {
        "name": "render_html", "description": "Gera um HTML e abre no navegador do device (ex.: tabela de treino, exercício).",
        "parameters": {"type": "object", "properties": {"titulo": {"type": "string"}, "html": {"type": "string"}},
                       "required": ["titulo", "html"]}}},
]

TOOL_GUIDE = (
    "\n\n[Ferramentas] Você TEM ferramentas: lembrar (registrar fato), notify (notificar), "
    "render_html (gerar HTML e abrir no navegador). Chame UMA quando a ação pedir (ex.: 'registra', "
    "'me avisa', 'gera um html e abre'). Para conversa normal, responda sem tool."
)

TURNOS = [
    "Me explica rapidinho o que é probabilidade condicional.",          # conversa — sem tool
    "Registra que hoje fiz supino reto 4 séries de 10 de 50 quilos.",   # tool: lembrar
    "Agora gera um html com esse treino e abre no navegador do server.",# tool: render_html
    "Beleza. Qual era o tópico de estudo que a gente tava vendo?",       # conversa — sem tool
]


def exec_tool(nome: str, args: dict) -> str:
    """Execução SIMULADA — devolve um 'resultado real' pro modelo seguir (ReAct)."""
    return f"[ok] {nome} executado com sucesso. args={args}"


def _stream_once(client, msgs):
    """Uma passada de stream. Devolve (texto, tool_calls, ttft_ms). Mostra no terminal ao vivo."""
    t0 = time.monotonic()
    ttft = None
    texto = ""
    calls: dict[int, dict] = {}       # index -> {name, args}
    extra = {"chat_template_kwargs": {"enable_thinking": False}} if NO_THINK else {}
    stream = client.chat.completions.create(
        model=MODEL, messages=msgs, tools=TOOLS, tool_choice="auto",
        temperature=0.6, max_tokens=500, stream=True, extra_body=extra)
    for chunk in stream:
        d = chunk.choices[0].delta
        if d.content:
            if ttft is None:
                ttft = (time.monotonic() - t0) * 1000
            texto += d.content
            print(d.content, end="", flush=True)            # typewriter
        if d.tool_calls:
            for tc in d.tool_calls:
                if ttft is None:
                    ttft = (time.monotonic() - t0) * 1000
                slot = calls.setdefault(tc.index, {"name": "", "args": ""})
                if tc.function and tc.function.name:
                    slot["name"] += tc.function.name
                if tc.function and tc.function.arguments:
                    slot["args"] += tc.function.arguments
    return texto, calls, (ttft or 0.0)


def main():
    client = OpenAI(base_url=BASE, api_key=KEY)
    system = build_system("voz") + TOOL_GUIDE
    msgs = [{"role": "system", "content": system}]
    print(f"ReAct LIMPO · {BASE} · {MODEL} · no_think={NO_THINK}\n" + "=" * 74)

    ttfts, totais, chamadas = [], [], []
    for turno in TURNOS:
        msgs.append({"role": "user", "content": turno})
        print(f"\n🫵 {turno}\n🤖 ", end="", flush=True)
        t0 = time.monotonic()
        ttft_turno = None
        n_llm = 0
        for _ in range(MAX_STEPS):
            texto, calls, ttft = _stream_once(client, msgs)
            n_llm += 1
            if ttft_turno is None:
                ttft_turno = ttft
            if calls:                                       # chamou tool → executa e devolve o resultado
                tcs = [{"id": f"call_{i}", "type": "function",
                        "function": {"name": v["name"], "arguments": v["args"]}} for i, v in calls.items()]
                msgs.append({"role": "assistant", "content": texto or None, "tool_calls": tcs})
                for i, v in calls.items():
                    try:
                        args = json.loads(v["args"] or "{}")
                    except Exception:
                        args = {"_raw": v["args"]}
                    print(f"\n   🔧 {v['name']}({json.dumps(args, ensure_ascii=False)})", flush=True)
                    res = exec_tool(v["name"], args)
                    msgs.append({"role": "tool", "tool_call_id": f"call_{i}", "content": res})
                print("🤖 ", end="", flush=True)            # vai responder com o resultado
                continue
            msgs.append({"role": "assistant", "content": texto})
            break
        total = (time.monotonic() - t0) * 1000
        ttfts.append(ttft_turno or 0.0); totais.append(total); chamadas.append(n_llm)
        print(f"\n   ⏱ TTFT {ttft_turno or 0:.0f}ms · total {total:.0f}ms · {n_llm} chamada(s) de LLM")

    n = len(ttfts)
    print("\n" + "=" * 74)
    print(f"MÉDIA ({n} turnos): TTFT {sum(ttfts)/n:.0f}ms · total {sum(totais)/n:.0f}ms · "
          f"{sum(chamadas)/n:.1f} chamadas/turno")
    print("=" * 74)
    print("→ compare: piso (vLLM direto ~2,6s) · ReAct limpo (aqui) · orchestrator atual (27-305s)")


if __name__ == "__main__":
    main()
