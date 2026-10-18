"""Benchmark 1/3 — vLLM DIRETO: o PISO de latência da voz.

1 chamada streaming por turno, com o prompt de voz, SEM orchestrator (sem router/juiz/tools).
É o "mais rápido possível" — a referência pra comparar depois com:
  - orchestrator ATUAL (lento: 2+ chamadas + router + juiz)   [bench 2]
  - orchestrator LIMPO (a construir)                           [bench 3]

Mede, por turno (conversa multi-turno, contexto crescente):
  TTFT  = tempo até o 1º token  (o "pensar" que o usuário sente antes do áudio)
  total = tempo até a resposta inteira
  tok/s = throughput de geração

Rodar (onde o vLLM estiver acessível):
    VLLM_BASE_URL=http://iobraza:8002/v1 VLLM_MODEL=qwen35-27b-abl python3 scripts/bench_vllm_direto.py
    # no_think desligado p/ comparar: NO_THINK=0 python3 scripts/bench_vllm_direto.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # raiz no path

from openai import OpenAI
from application.prompts import build_system   # mesmo prompt de voz do agente

BASE = os.getenv("VLLM_BASE_URL", "http://iobraza:8002/v1")
MODEL = os.getenv("VLLM_MODEL", os.getenv("MODEL_NAME", "qwen35-27b-abl"))
KEY = os.getenv("VLLM_API_KEY", "change-me")
NO_THINK = os.getenv("NO_THINK", "1") != "0"      # a voz usa no_think; default ligado
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "300"))

# conversa realista de voz (curta, multi-turno — o contexto cresce a cada turno)
TURNOS = [
    "Fala comigo, quais são as novidades?",
    "Me explica rapidinho o que é probabilidade condicional.",
    "E qual a diferença pra probabilidade comum?",
    "Beleza. Me dá um exemplo com baralho.",
    "Entendi. Agora me ajuda a lembrar: qual era o tópico que a gente tava vendo?",
]


def main():
    client = OpenAI(base_url=BASE, api_key=KEY)
    msgs = [{"role": "system", "content": build_system("voz")}]
    extra = {"chat_template_kwargs": {"enable_thinking": False}} if NO_THINK else {}
    print(f"vLLM DIRETO · {BASE} · {MODEL} · no_think={NO_THINK}\n" + "=" * 74)

    ttfts, totais = [], []
    for turno in TURNOS:
        msgs.append({"role": "user", "content": turno})
        print(f"\n🫵 {turno}")
        t0 = time.monotonic()
        ttft = None
        texto = ""
        n_tok = 0
        stream = client.chat.completions.create(
            model=MODEL, messages=msgs, temperature=0.6, max_tokens=MAX_TOKENS,
            stream=True, extra_body=extra)
        for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            if not delta:
                continue
            if ttft is None:
                ttft = (time.monotonic() - t0) * 1000
            texto += delta
            n_tok += 1
        total = (time.monotonic() - t0) * 1000
        msgs.append({"role": "assistant", "content": texto})
        ttfts.append(ttft or 0.0)
        totais.append(total)
        tok_s = n_tok / (total / 1000) if total else 0.0
        print(f"🤖 {texto}")
        print(f"   ⏱ TTFT {ttft or 0:.0f}ms · total {total:.0f}ms · ~{n_tok} tok · {tok_s:.1f} tok/s")

    n = len(ttfts)
    print("\n" + "=" * 74)
    print(f"MÉDIA ({n} turnos): TTFT {sum(ttfts)/n:.0f}ms · total {sum(totais)/n:.0f}ms")
    print(f"PIOR TTFT: {max(ttfts):.0f}ms · MELHOR TTFT: {min(ttfts):.0f}ms")
    print("=" * 74)
    print("→ compare com o TTFT do orchestrator atual (27s–305s nos seus testes de voz).")


if __name__ == "__main__":
    main()
