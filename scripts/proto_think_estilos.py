"""Preview do estilo ESCOLHIDO (opção 3: caixa) do bloco de raciocínio no card do brazaia.

Roda:  python scripts/proto_think_estilos.py
Estrutura do card: 🤖 brazaia (topo) → caixa "💭 raciocínio" → resposta. Tudo sob o mesmo header,
pra deixar claro que o raciocínio E a resposta pertencem ao brazaia.
Mostra 2 variantes: (A) caixa aberta  (B) colapsada (1 linha). Me diz qual e eu aplico no cli.py.
"""
import shutil

W = min(100, max(50, shutil.get_terminal_size((100, 24)).columns))
R = "\033[0m"

THINK = ("The user is asking the difference between X and Y. Let me be concise: X is about the "
         "code level, Y about the architecture. I'll give a short, friendly answer with an example.")
REPLY = ("Boa pergunta! Resumindo: **X** cuida de *como* o código é escrito; **Y** cuida de *onde* "
         "cada coisa mora. Juntos > separados. Quer um diagrama?")

# cores do card (mesmas do cli.py)
BAR_BOT = "\033[38;2;45;168;79m"          # barra/texto verde do brazaia
HBG_BOT = "\033[48;2;45;160;75m\033[1;38;2;235;255;240m"   # faixa do título
AMBAR   = "\033[38;2;229;192;123m"        # borda/label do raciocínio
DIM     = "\033[38;2;140;145;155m"        # texto do raciocínio (dim)

def wrap(t, w):
    out, ln = [], ""
    for word in t.split():
        if len(ln) + len(word) + 1 > w: out.append(ln); ln = word
        else: ln = (ln + " " + word).strip()
    if ln: out.append(ln)
    return out

def header_brazaia():
    label = " 🤖 brazaia"
    pad = max(0, W - len(label) - 1)
    print(f"{BAR_BOT}▌{R}{HBG_BOT}{label}{' ' * pad}{R}")

def resposta():
    for l in wrap(REPLY, W - 2):
        print(f"{BAR_BOT}▌{R} {l}")

def caixa_raciocinio():
    inner = W - 4
    print(f"{AMBAR}  ┌─ 💭 raciocínio " + "─" * (W - 19) + "┐" + R)
    for l in wrap(THINK, inner):
        print(f"{AMBAR}  │{R} {DIM}{l}{R}" + " " * (inner - len(l)) + f"{AMBAR} │{R}")
    print(f"{AMBAR}  └" + "─" * (W - 4) + "┘" + R)

# ---------- A) caixa ABERTA ----------
print(f"\n\033[1;38;2;120;130;150m── A) caixa aberta " + "─" * (W - 19) + R)
header_brazaia()
caixa_raciocinio()
resposta()

# ---------- B) COLAPSADA (1 linha; o raciocínio fica escondido) ----------
print(f"\n\033[1;38;2;120;130;150m── B) colapsada (1 linha) " + "─" * (W - 26) + R)
header_brazaia()
n = len(wrap(THINK, W - 4))
print(f"{AMBAR}  💭 raciocínio{R} {DIM}({n} linhas · {len(THINK.split())} palavras) ▸{R}")
resposta()

print(f"\n{R}A = sempre mostra o raciocínio na caixa · B = esconde (só o resumo). Me diz: A ou B?")
