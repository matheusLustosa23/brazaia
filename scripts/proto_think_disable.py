"""Acha o jeito CONFIÁVEL de DESLIGAR o thinking do Qwen — testando ALTERNÂNCIA (em curso).

O caso que importa não é começar desligado, é DESLIGAR no meio da conversa (depois de já ter pensado):
o modelo tende a continuar por inércia do contexto. Então pra cada método a gente roda a sequência
ON → OFF → ON → OFF → OFF na MESMA conversa (acumulando o histórico RAW, com o <think> antigo = pior caso)
e marca turno a turno se pensou. O método bom: nos ON pensa (P), e em TODO OFF NÃO pensa (-), rápido.

Fala DIRETO com o vLLM (isola o mecanismo). Rodar onde alcança o vLLM (via tailscale):
  VLLM_BASE_URL=http://iobraza:8002/v1 VLLM_MODEL=<id> uv run python scripts/proto_think_disable.py
"""
import os, sys, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from openai import OpenAI

BASE  = os.getenv("VLLM_BASE_URL", "http://iobraza:8002/v1")
MODEL = os.getenv("VLLM_MODEL", os.getenv("MODEL_NAME", "qwen35-27b-abl"))
KEY   = os.getenv("VLLM_API_KEY", "change-me")
SYS   = "Você é um assistente pessoal local. Responda em português, direto e conciso."

SEQ     = ["ON", "OFF", "ON", "OFF", "OFF"]            # alterna pra ver se desliga EM CURSO
PROMPTS = [
    "Qual a diferença entre clean code e arquitetura hexagonal?",
    "E entre REST e GraphQL?",
    "Pra um app de chat, SQL ou NoSQL? Justifica.",
    "O que é idempotência numa API?",
    "Me explica recursão com um exemplo simples.",
]
METODOS = ["enable_thinking", "/no_think user", "/no_think system", "template+user", "template+system"]
_CT = {"chat_template_kwargs": {"enable_thinking": False}}

def aplica(metodo: str, off: bool):
    """(system, sufixo_user, extra_body) pro turno — só desliga quando off=True."""
    if metodo == "enable_thinking":   return SYS, "", (_CT if off else {})
    if metodo == "/no_think user":    return SYS, (" /no_think" if off else ""), {}
    if metodo == "/no_think system":  return (SYS + "\n/no_think" if off else SYS), "", {}
    if metodo == "template+user":     return SYS, (" /no_think" if off else ""), (_CT if off else {})
    if metodo == "template+system":   return (SYS + "\n/no_think" if off else SYS), "", (_CT if off else {})
    return SYS, "", {}

def roda(client, msgs, extra):
    t0 = time.monotonic(); out = ""
    stream = client.chat.completions.create(
        model=MODEL, messages=msgs, temperature=0.6, max_tokens=1200, stream=True,
        extra_body=(extra or None))
    for ch in stream:
        d = ch.choices[0].delta.content
        if d: out += d
    return out, (time.monotonic() - t0)

def pensou(out: str) -> bool:
    low = out.lower()
    if "<think>" in low or "</think>" in low:
        return True
    cabeca = out[:200].lower()
    return any(s in cabeca for s in ("the user", "the owner", "let me", "i should", "i need to", "okay,"))

def main():
    client = OpenAI(base_url=BASE, api_key=KEY)
    print(f"vLLM {BASE} · {MODEL}  ·  sequência {' '.join(SEQ)}  (P=pensou · -=limpo)\n" + "=" * 86)
    for metodo in METODOS:
        conversa: list[dict] = []                     # histórico RAW acumulado (pior caso: <think> antigo no contexto)
        marcas, t_off, offs_ok = [], [], True
        for i, estado in enumerate(SEQ):
            off = (estado == "OFF")
            sysm, suf, extra = aplica(metodo, off)
            user = PROMPTS[i % len(PROMPTS)] + suf
            msgs = [{"role": "system", "content": sysm}] + conversa + [{"role": "user", "content": user}]
            out, secs = roda(client, msgs, extra)
            p = pensou(out)
            marcas.append("P" if p else "-")
            if off:
                t_off.append(secs)
                if p: offs_ok = False
            conversa += [{"role": "user", "content": user}, {"role": "assistant", "content": out}]
        seqstr = "  ".join(f"{e}:{m}" for e, m in zip(SEQ, marcas))
        avg_off = (sum(t_off) / len(t_off)) if t_off else 0.0
        print(f"{metodo:<18} {seqstr:<42} OFF {'✅ desliga' if offs_ok else '❌ vazou '} ~{avg_off:4.1f}s/off")
    print("=" * 86)
    print("Quero: ON→P, todo OFF→'-' (inclusive depois de ter pensado) e tempo baixo no off. Esse a gente aplica.")

if __name__ == "__main__":
    main()
