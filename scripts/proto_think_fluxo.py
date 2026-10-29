"""Valida o fluxo do thinking ponta-a-ponta ANTES de mexer no cli.py.

Manda 5 mensagens ao agente (think=ON), recebe o stream, SEPARA pelo marcador de texto
(RACIOCÍNIO: / RESPOSTA:) e RENDERIZA o card escolhido (🤖 brazaia → caixa 'raciocínio' → resposta).
No fim diz em quantas das 5 o marcador veio certo — é isso que decide se dá pra aplicar no CLI.

Pré: o AGENTE precisa estar reiniciado com a instrução nova (marcador de texto).
Roda (na máquina que acessa o agente):  uv run python scripts/proto_think_fluxo.py
"""
import asyncio, os, re, shutil, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # raiz no path
from companion.config import load_config
from companion.chat_client import chat_stream

W = min(100, max(50, shutil.get_terminal_size((100, 24)).columns))
R = "\033[0m"
BAR_BOT = "\033[38;2;45;168;79m"
HBG_BOT = "\033[48;2;45;160;75m\033[1;38;2;235;255;240m"
AMBAR   = "\033[38;2;229;192;123m"
DIM     = "\033[38;2;140;145;155m"
AZUL    = "\033[38;2;74;158;255m"

MENSAGENS = [
    "Qual a diferença entre clean code e arquitetura hexagonal?",
    "Me explica recursão com um exemplo simples.",
    "Pra um app de chat, SQL ou NoSQL? Justifica.",
    "Me dá 3 nomes pro meu agente local e o porquê de cada.",
    "O que é idempotência e por que importa numa API?",
]

def wrap(t, w):
    out = []
    for para in t.split("\n"):
        ln = ""
        for word in para.split():
            if len(ln) + len(word) + 1 > w: out.append(ln); ln = word
            else: ln = (ln + " " + word).strip()
        out.append(ln)
    return out

def split_marker(full: str) -> tuple[str, str]:
    """(raciocinio, resposta) a partir de RACIOCÍNIO: … RESPOSTA: …"""
    m = re.search(r'RESPOSTA\s*:', full, re.IGNORECASE)
    if not m:
        return "", full.strip()                       # sem marcador → tudo é resposta
    resposta = full[m.end():].strip()
    antes = full[:m.start()]
    r = re.search(r'RACIOC[IÍ]NIO\s*:', antes, re.IGNORECASE)
    raciocinio = (antes[r.end():] if r else antes).strip()
    return raciocinio, resposta

def render_card(pergunta: str, raciocinio: str, resposta: str) -> None:
    # 🫵 você
    print(f"\n{AZUL}▌{R} \033[1;38;2;74;158;255m🫵 você{R}")
    print(f"{AZUL}▌{R} {pergunta}")
    # 🤖 brazaia (header no topo do card)
    label = " 🤖 brazaia"
    print(f"{BAR_BOT}▌{R}{HBG_BOT}{label}{' ' * max(0, W - len(label) - 1)}{R}")
    # caixa do raciocínio (aberta)
    if raciocinio:
        inner = W - 4
        print(f"{AMBAR}  ┌─ 💭 raciocínio " + "─" * (W - 19) + "┐" + R)
        for l in wrap(raciocinio, inner):
            print(f"{AMBAR}  │{R} {DIM}{l}{R}" + " " * max(0, inner - len(l)) + f"{AMBAR} │{R}")
        print(f"{AMBAR}  └" + "─" * (W - 4) + "┘" + R)
    # resposta
    for l in wrap(resposta, W - 2):
        print(f"{BAR_BOT}▌{R} {l}")

async def main() -> None:
    cfg = load_config()
    print(f"→ agente: {cfg.server_ws_url}  ·  think=ON  ·  {len(MENSAGENS)} mensagens\n" + "=" * W)
    sid = None
    ok = 0
    for i, msg in enumerate(MENSAGENS, 1):
        full = []
        try:
            async for ev in chat_stream(msg, sid, cfg, think=True):
                if "session_id" in ev:
                    sid = ev["session_id"]
                elif "delta" in ev:
                    full.append(ev["delta"])
                elif ev.get("success") is False or "error" in ev:
                    print(f"  ⚠ erro do servidor: {ev}")
        except Exception as e:
            print(f"  ⚠ falha no stream: {e}"); continue
        texto = "".join(full)
        raciocinio, resposta = split_marker(texto)
        tem_marcador = bool(raciocinio) and ("RESPOSTA" in texto.upper())
        ok += 1 if tem_marcador else 0
        render_card(msg, raciocinio, resposta)
        print(f"{DIM}   [marcador: {'OK ✓' if tem_marcador else 'FALTOU ✗ (sem RACIOCÍNIO:/RESPOSTA:)'}]{R}")
    print("=" * W + f"\nMarcador presente em {ok}/{len(MENSAGENS)}.  "
          + ("Pode aplicar no CLI. ✅" if ok == len(MENSAGENS) else "Instável — ajustar a instrução antes de aplicar. ⚠"))

if __name__ == "__main__":
    asyncio.run(main())
