"""companion/cli.py — CLI de chat do brazaia (scrollback B+): CAIXA DE INPUT FIXA no rodapé +
LOADER animando nela, e a conversa em SCROLLBACK NATIVO acima (rola/copia/busca).

Técnica: o prompt_toolkit desenha o prompt+toolbar SEMPRE no rodapé e NUNCA os manda pro histórico.
Então a caixa (borda + input + loader) fica fixa embaixo e não se repete. O loader anima no
cabeçalho da caixa. As respostas são impressas ACIMA via patch_stdout → scrollback.

Uso:  uv run python -m companion.cli     (^C / ^D sai)
"""
import asyncio, base64, mimetypes, os, re, shutil, sys, time
from prompt_toolkit import PromptSession, print_formatted_text as pf
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.formatted_text import ANSI, StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.application import get_app, in_terminal
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.styles import Style
from rich.cells import cell_len

from companion.render import md_ansi, SPIN, decode
from companion.config import load_config, CompanionConfig
from companion.chat_client import chat_stream, listar_sessoes, carregar_sessao, listar_arquivos, baixar_arquivo
from companion.connect import conectar                 # loop de device REAL (handshake + RPC + reconexão)
from companion.state import estado                    # estado.device_online (status no footer)
from companion.plataform import _IS_TERMUX             # adapta o CLI ao Termux (voz AAC, sem anexo/clipboard)

cfg: CompanionConfig = None  # type: ignore[assignment]  # setado no main (load_config)
session_id = None     # capturado do 1º evento do backend
gravando = False      # True enquanto /voz está gravando (LIVRE, até Enter)
voz_prep = False      # True no "preparando microfone…" (antes de começar a gravar)
transcrevendo = False # True entre o Enter e a transcrição chegar (loader "transcrevendo…")
_grav = None          # GravacaoLivre ativa (start/stop manual, controlado pelo Enter)
pending_image = None  # data URL da imagem anexada (vai na próxima mensagem)
pending_name = None   # nome do arquivo anexado (só p/ exibir no card)
ultima_resposta = ""  # último reply do LLM (limpo, sem barras) — pra /copiar
sessoes_cache: list = []  # última listagem de /chat/sessions (mais recente 1º) → /sessao N e o autocomplete
sessoes_tag: str | None = None   # filtro da última listagem (ex.: "replica") — o /sessao N numera NESSA lista
arquivos_cache: list = []  # artefatos da sessão atual (último /arquivos) → /abrir N
modo_sessao = "chat"       # modo da sessão atual: chat | tutor (vem do server ao retomar; /modo troca)
modo_pendente: str | None = None   # /modo escolhido e ainda não enviado (vai na próxima mensagem e fica gravado)
stream_tail = ""      # "rabo" do bloco sendo DIGITADO (typewriter na região viva do prompt)
tail_think = False    # True quando o rabo é RACIOCÍNIO (<think>), p/ estilo diferente da resposta
tool_build: dict = {} # tool_calls sendo MONTADAS ao vivo: index -> {"tool", "args" (JSON cru), "t0"}
aguardando = False    # True entre mandar e o 1º token chegar (TTFT) → mostra "processando…"
think_mode = "off"    # thinking: "off" | "full" (caixa) | "colap" (só resumo). Toggle /think
pensando = False      # colap: True enquanto recebe o <think> (mostra "pensando…" em vez do texto)
think_t0 = 0.0        # início do raciocínio (p/ o tempo no modo colapsado)
turno_t0 = 0.0        # início do turno (p/ o tempo total no rodapé/loader)
last_delta_t = 0.0    # instante do último delta recebido → detecta GAP (tool rodando/entre passos) p/ loader
tok_count = 0         # contador de tokens da resposta atual (ao vivo, estilo Claude)
ctx_usado = 0; ctx_total = 0; ctx_model = ""; ctx_reservado = 0   # contexto + teto de saída → footer
checklist: list = []  # passos (tools) do turno AO VIVO: [{id,desc,tool,estado,det,f0}] — vem dos eventos 'passo'
checklist_base = 0    # nº de itens já fixados no turno → numeração CONTÍNUA entre as rodadas de tools
DIM_A = "\033[38;2;92;99;112m"
TEAL_HEX = "#2da84f"    # cor (prompt) do rabo digitando
STREAM_MAX = 14       # nº de linhas visíveis do rabo (não deixa a caixa crescer sem limite)

# paleta BANDEIRA
DIM = "#5c6370"; AZUL = "#4a9eff"                     # AZUL = cor do ❯ no input
BORDA = "#2da84f"                                    # delimitador da caixa de input (verde)
BAR_TEAL = "\033[38;2;45;168;79m"                    # barra do brazaia (verde bandeira)
BAR_AZUL = "\033[38;2;40;110;190m"                   # barra do você (azul bandeira)
VERDE_A = "\033[38;2;0;200;83m"                      # verde vivo (loader/etapas)
R = "\033[0m"
# card do turno: FAIXA do título (bg da cor) + CORPO (grafite, combina com code one-dark)
BODY_BG = "#282c34"; BODY_RGB = "40;44;52"
SKEL_RGB = "31;35;42"; SKEL_BG = "#1f232a"           # fundo do checklist (recuado vs o corpo) · ANSI e hex (ao vivo)
HBG_USER = "30;96;168";  NM_USER = "235;242;255"    # título · você  → AZUL (bandeira)
HBG_BOT = "45;160;75";   NM_BOT = "235;255;240"     # título · brazaia → VERDE (bandeira)

def _larg() -> int:                                  # largura REAL do terminal (não o fallback)
    try:
        return max(40, get_app().output.get_size().columns)
    except Exception:
        return max(40, shutil.get_terminal_size((100, 24)).columns)

def _titulo(label: str, W: int, bar: str, hbg: str, nm: str) -> str:
    """Faixa do título preenchendo a LINHA INTEIRA, com bg próprio (distinto do corpo)."""
    pad = max(0, (W - 1) - cell_len(" " + label + " "))
    return f"{bar}▌{R}\033[48;2;{hbg}m\033[1m\033[38;2;{nm}m {label} {' ' * pad}{R}"

def _corpo(conteudo: str, vis: int, W: int, bar: str | None, bg: str = BODY_RGB) -> str:
    """Linha do corpo com bg preenchendo a linha. bar=None → SEM ▌ (linhas de status);
    bar=cor → ▌ (checklist de tools)."""
    prefixo = f"{bar}▌{R}" if bar else ""
    pad = max(0, W - (1 if bar else 0) - vis)
    return f"{prefixo}\033[48;2;{bg}m{conteudo}{' ' * pad}{R}"

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

def _pad_top(W: int) -> str:
    """Linha de respiro (bg do corpo) — padding logo abaixo do título."""
    return f"\033[48;2;{BODY_RGB}m{' ' * W}{R}"

def _preserva_quebras(txt: str) -> str:
    """WYSIWYG das quebras: em Markdown \\n simples vira espaço (cola 'A)\\nB)' numa linha só).
    Transforma \\n simples em hard break (2 espaços) pra manter cada linha como o modelo escreveu.
    NÃO toca em blocos ``` (lá a quebra já é literal)."""
    partes = re.split(r"(```.*?```)", txt, flags=re.S)
    for i in range(0, len(partes), 2):                         # só os trechos FORA de fence (índices pares)
        partes[i] = re.sub(r"(?<! )(?<!\n)\n(?!\n)", "  \n", partes[i])
    return "".join(partes)

def _corpo_md(bloco: str, W: int, bar: str) -> str:
    """Markdown como CORPO: SEM a barra ▌ (a seleção copia o conteúdo). Padding à ESQUERDA
    (não fica colado na lateral) — single md_ansi (sem fence-split, que causava a linha pelada)."""
    LEFT = "  "                                                # respiro à esquerda (2 col)
    md = md_ansi(_preserva_quebras(bloco), width=W - len(LEFT), bg=BODY_BG, code_theme="one-dark").rstrip("\n")
    linhas = []
    for ln in md.split("\n"):
        vis = cell_len(_ANSI.sub("", ln))                      # largura visível real
        pad = max(0, W - len(LEFT) - vis)
        linhas.append(f"\033[48;2;{BODY_RGB}m{LEFT}{R}{ln}\033[48;2;{BODY_RGB}m{' ' * pad}{R}")
    return "\n".join(linhas)

# checklist estilo Claude: marca por estado (hex p/ o ao vivo · ANSI p/ o fixado no scrollback)
_MARCA = {"ok": ("✔", "#2da84f", VERDE_A), "err": ("✗", "#e05a5a", "\033[38;2;224;90;90m"),
          "exec": ("▸", "#e5c07b", "\033[38;2;229;192;123m")}

def _aplicar_passo(ev: dict) -> None:
    """Evento 'passo' → executando cria a linha; ok/erro fecha a MESMA linha (casada pelo id da tool_call)."""
    pid, estado = ev.get("id"), ev.get("estado")
    if estado == "executando":
        checklist.append({"id": pid, "desc": (ev.get("porque") or ev.get("tool") or "").strip(),
                          "tool": ev.get("tool"), "estado": "exec", "det": "", "f0": frame})
        return
    for it in checklist:
        if it["id"] == pid:
            it["estado"] = "ok" if estado == "ok" else "err"
            it["det"] = ev.get("detalhe", "")
            return

def _uma_linha(s: str, w: int) -> str:
    """Corta pra caber em 1 linha visual — wrap faz o patch_stdout deixar fantasma."""
    if cell_len(s) <= w:
        return s
    while s and cell_len(s + "…") > w:
        s = s[:-1]
    return s + "…"

def _checklist_frags() -> StyleAndTextTuples:
    """Checklist AO VIVO (rodapé): ✔ feito · ✗ erro · ▸ executando (decode + spinner)."""
    fr: StyleAndTextTuples = []
    W = _larg(); w = W - 1
    for i, it in enumerate(checklist, checklist_base + 1):
        m, cor, _ = _MARCA[it["estado"]]
        if it["estado"] == "exec":
            spin = f"   ⚙ {SPIN[frame % len(SPIN)]}"
            linha = _uma_linha(f"   {m} {i}. {decode(it['desc'], frame - it['f0'])}", w - cell_len(spin)) + spin
        else:
            linha = _uma_linha(f"   {m} {i}. {it['desc']}", w)
        fr.append((f"{cor} bg:{SKEL_BG}", linha.ljust(W) + "\n"))
        if it["det"] and it["estado"] != "exec":
            fr.append((f"#5c6370 bg:{SKEL_BG}", _uma_linha(f"       └ {it['det']}", w).ljust(W) + "\n"))
    return fr

def _commit_checklist(W: int) -> None:
    """Fixa o checklist no scrollback (fim de cada rodada de tools) e limpa o ao vivo. Numeração contínua."""
    global checklist_base
    for it in checklist:
        checklist_base += 1
        est = "ok" if it["estado"] == "exec" else it["estado"]      # exec sem fechamento (stream caiu) vira ✔ ao fixar
        m, _, ans = _MARCA[est]
        txt = f" {m} {checklist_base}. {it['desc']}"
        _p(_corpo(f" {ans}{txt[1:]}", cell_len(txt), W, BAR_TEAL, bg=SKEL_RGB) + "\n")
        if it["det"]:
            det = _uma_linha(f"   └ {it['det']}", W - 2)
            _p(_corpo(f"{DIM_A}{det}", cell_len(det), W, BAR_TEAL, bg=SKEL_RGB) + "\n")
    checklist.clear()

def _osc_on() -> None:                       # NÃO força cor de fundo → respeita a TRANSPARÊNCIA do terminal
    sys.stdout.write("\033[2J\033[H"); sys.stdout.flush()    # só limpa a tela

def _osc_off() -> None:
    pass

BOT = "🤖"                                    # emoji do brazaia (troque pelo seu aqui)

def _grad(t: float):                          # gradiente Brasil: azul(topo)→verde→amarelo(baixo)
    stops = [(0.0, (30, 110, 255)), (0.5, (0, 200, 80)), (1.0, (255, 221, 0))]
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        if a <= t <= b:
            u = (t - a) / (b - a) if b > a else 0
            return tuple(int(ca[k] + (cb[k] - ca[k]) * u) for k in range(3))
    return stops[-1][1]

async def _banner() -> None:                 # FIGLET "brazaia" com gradiente Brasil
    try:
        from pyfiglet import Figlet
        arte = Figlet(font="ansi_shadow").renderText("brazaia").rstrip("\n").split("\n")
    except Exception:
        arte = ["  b r a z a i a"]
    L = max(1, len(arte) - 1)
    for i, ln in enumerate(arte):
        r, g, b = _grad(i / L)
        sys.stdout.write(f"\033[1m\033[38;2;{r};{g};{b}m {ln}{R}\n"); sys.stdout.flush()
        await asyncio.sleep(0.05)
    sys.stdout.write(f" {BAR_TEAL}{BOT}{R}  {BAR_AZUL}companion{R}  {DIM_A}(status no rodapé){R}\n"); sys.stdout.flush()
    await asyncio.sleep(0.6)
frame = 0
respondendo = False

def _p(s: str) -> None:
    pf(ANSI(s), end="")

_ESC = re.compile(r'\\(u[0-9a-fA-F]{4}|.)')
_ESC_MAP = {"n": "\n", "t": "  ", "r": "", '"': '"', "\\": "\\", "/": "/"}

def _desescapa(s: str) -> str:
    """JSON PARCIAL dos args → texto legível (\\n vira quebra, \\" vira aspas). Tolerante: o JSON ainda está incompleto."""
    return _ESC.sub(lambda m: chr(int(m.group(1)[1:], 16)) if m.group(1)[0] == "u" and len(m.group(1)) == 5
                    else _ESC_MAP.get(m.group(1), m.group(1)), s)

def _tool_build_frags(w: int) -> StyleAndTextTuples:
    """Tool sendo MONTADA (args streamando): cabeçalho com tamanho/tempo + rabo legível dos args."""
    fr: StyleAndTextTuples = []
    lim = w - 2
    for b in tool_build.values():
        sp = SPIN[frame % len(SPIN)]
        secs = time.monotonic() - b["t0"]
        tam = f"{len(b['args'])} chars · " if len(b["args"]) > 20 else ""   # qwen3_coder só solta o param no fim → até lá, só o tempo
        fr.append(("bold #c678dd", f"   {sp} 🔧 montando {b['tool'] or 'ferramenta'}… {tam}{secs:.0f}s\n"))
        cauda = _desescapa(b["args"][-1500:])
        for ln in cauda.split("\n")[-STREAM_MAX:]:
            fr.append(("#c678dd", "▌"))
            fr.append(("#8c7a96 bg:#15181d", " " + ln[:lim].ljust(lim) + "\n"))
    return fr

def _prompt_msg() -> StyleAndTextTuples:
    """Rabo do texto sendo digitado (typewriter) ACIMA da caixa de input fixa no rodapé.
    Tudo vive no rodapé, não vai pro histórico."""
    w = _larg()
    linhas: StyleAndTextTuples = []
    gap = respondendo and (time.monotonic() - last_delta_t) > 0.4   # stream pausou (tool rodando / entre passos) → loader
    if voz_prep:                                               # /voz: preparando o mic
        linhas.append(("bold #e5c07b", "   ⚙ preparando microfone…\n"))
    elif gravando:                                             # /voz: gravando livre até o Enter
        linhas.append(("bold #39d353", "   🎤 gravando… (Enter pra parar e jogar no input)\n"))
    elif transcrevendo:                                        # Enter→transcrição: loader entre parar o mic e o texto chegar
        sp = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[frame % 10]
        linhas.append(("bold #e5c07b", f"   {sp} transcrevendo áudio…\n"))
    if pensando:                                               # colap: raciocinando (não mostra o texto, só o tempo)
        sp = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[frame % 10]
        secs = (time.monotonic() - think_t0) if think_t0 else 0.0
        linhas.append(("bold #e5c07b", f"   {sp} 💭 pensando… {secs:.0f}s\n"))
    elif tool_build:                                           # args da tool chegando (ex.: HTML do create_file) — já mostra
        linhas += _tool_build_frags(w)
    elif checklist:                                            # tools da rodada atual (ao vivo) — o ▸ já anima
        linhas += _checklist_frags()
    elif aguardando or gap:                                    # TTFT (1º token) OU gap entre passos (tool rodando) → loader, não parecer travado
        sp = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[frame % 10]
        secs = (time.monotonic() - turno_t0) if turno_t0 else 0.0
        linhas.append(("bold #4a9eff", f"   {sp} processando… {secs:.0f}s\n"))
    if stream_tail and not gap:                                # RABO digitando (no gap some o rabo congelado e fica só o loader)
        cauda = stream_tail[-400:]                              # cap por CHARS: bloco gigante não trava o render
        lim = _larg() - 2
        barra = "#e5c07b" if tail_think else TEAL_HEX           # 💭 raciocínio = âmbar · resposta = verde
        txtcor = "#8a7a52 bg:#15181d" if tail_think else "#7a808c bg:#15181d"
        for ln in cauda.split("\n")[-STREAM_MAX:]:
            linhas.append((barra, "▌"))
            linhas.append((txtcor, " " + (ln[:lim]).ljust(lim) + "\n"))
    linhas.append((BORDA, "\n╭─ mensagem " + "─" * max(0, w - 13) + "╮\n"))   # 12 + traços + ╮ = w (não w+1: quebrava)
    linhas += [(BORDA, "│ "), (f"bold {AZUL}", "❯ ")]
    return linhas

def _toolbar() -> StyleAndTextTuples:
    w = _larg()
    status = estado.device_status or ("online" if estado.device_online else "offline")
    dot = {"online": "#2da84f", "reconectando": "#e5c07b", "offline": "#e05a5a"}.get(status, "#e05a5a")
    pct = int(100 * ctx_usado / ctx_total) if ctx_total else 0
    ctx = f" · ctx {ctx_usado}/{ctx_total} ({pct}%)" if ctx_total else ""   # escondido até o backend mandar 'contexto'
    teto = f"/{ctx_reservado}" if ctx_reservado else ""                     # ↑ tokens da resposta / teto de saída
    out = f" · ↑{tok_count}{teto} · {(time.monotonic() - turno_t0):.0f}s" if (respondendo and turno_t0) else ""
    modelo = (ctx_model or "—").split("/")[-1][:24]
    sid = (session_id or "nova")[:8]
    dev = (cfg.device_id if cfg else "device")
    th = {"off": "💭off", "full": "💭full", "colap": "💭colap"}.get(think_mode, "💭off")
    if modo_sessao == "tutor":
        th = "🎓tutor · " + th
    # tela estreita (celular): vai largando o MENOS importante até caber — modelo, thinking, "sessão", ctx curto
    caber = w - 5                                                            # ╰─ ● … ─╯ ocupam 5 colunas
    opcoes = [f" {status} · {dev} · sessão {sid}{ctx}{out} · {th} · {modelo} ",
              f" {status} · {dev} · sessão {sid}{ctx}{out} · {th} ",
              f" {status} · {dev} · {sid}{ctx}{out} ",
              f" {status} · {dev}" + (f" · ctx {pct}%" if ctx_total else "") + (f" · ↑{tok_count}" if out else "") + " ",
              f" {status} · {dev} "]
    txt = next((o for o in opcoes if cell_len(o) <= caber), opcoes[-1])
    while cell_len(txt) > caber and len(txt) > 1:                            # último recurso: corta
        txt = txt[:-2] + " "
    fill = max(1, w - cell_len(txt) - 4)
    return [(BORDA, "╰─"), (dot, "●"), (DIM, txt), (BORDA, "─" * fill + "╯")]

def _ponto_flush(buf: str) -> int:
    """Último '\\n\\n' fora de cerca ``` aberta (não corta bloco de código). -1 se não há."""
    idx = buf.rfind("\n\n")
    while idx != -1:
        if buf.count("```", 0, idx) % 2 == 0:
            return idx
        idx = buf.rfind("\n\n", 0, idx)
    return -1

_AMBAR = "\033[38;2;229;192;123m"

def _wrap(t: str, w: int) -> list[str]:
    """Quebra por palavra em linhas de até w (p/ a caixa do raciocínio)."""
    out: list[str] = []
    for para in t.strip().split("\n"):
        ln = ""
        for word in para.split():
            if len(ln) + len(word) + 1 > w: out.append(ln); ln = word
            else: ln = (ln + " " + word).strip()
        out.append(ln)
    return out

def _limpa_think(texto: str) -> str:
    """Tira um <think> de abertura residual (às vezes vem no stream) e espaços."""
    t = texto.strip()
    if t.startswith("<think>"): t = t[7:].strip()
    return t

def _commit_pensamento(texto: str, W: int) -> None:
    """Raciocínio FULL (opção escolhida): caixa com borda âmbar + texto dim — distinta da resposta (verde)."""
    texto = _limpa_think(texto)
    inner = W - 6
    _p(f"{_AMBAR}  ┌─ 💭 raciocínio " + "─" * max(0, W - 20) + "┐" + R + "\n")
    for ln in _wrap(texto, inner):
        _p(f"{_AMBAR}  │{R} {DIM_A}{ln}{R}" + " " * max(0, inner - len(ln)) + f" {_AMBAR}│{R}" + "\n")
    _p(f"{_AMBAR}  └" + "─" * max(0, W - 4) + "┘" + R + "\n")

def _commit_colap(texto: str, toks: int, secs: float, W: int) -> None:
    """Raciocínio COLAPSADO: caixa de UMA linha (só o resumo) — mesma estética da aberta, mas sem o texto."""
    nlin = len([l for l in _limpa_think(texto).split("\n") if l.strip()])
    lbl = f"─ 💭 raciocínio · {nlin} linhas · {toks} tok · {secs:.1f}s ▸ "
    _p(f"{_AMBAR}  ┌{lbl}" + "─" * max(0, W - 4 - cell_len(lbl)) + "┐" + R + "\n")
    _p(f"{_AMBAR}  └" + "─" * max(0, W - 4) + "┘" + R + "\n")

def _fecha_raciocinio(texto: str, toks: int, t0: float, W: int) -> None:
    """Fixa o raciocínio no scrollback conforme o modo: full=caixa, colap=resumo."""
    secs = (time.monotonic() - t0) if t0 else 0.0
    if think_mode == "colap":
        _commit_colap(texto, toks, secs, W)
    else:
        _commit_pensamento(texto, W)

def _fecha_escrita(pensamento: str, buf: str, blk_toks: int, think_secs: float, W: int):
    """Antes de uma tool: fixa no scrollback o raciocínio aberto e o texto pendente da chamada,
    pra montagem/checklist virem DEPOIS deles. Devolve o estado zerado (think_secs, pensamento, buf, blk_toks)."""
    global think_t0, pensando, stream_tail, tail_think
    if pensamento:
        think_secs += (time.monotonic() - think_t0) if think_t0 else 0.0
        _fecha_raciocinio(pensamento, blk_toks, think_t0, W)
        think_t0 = 0.0; pensando = False
    if buf.strip():
        _p(_corpo_md(buf, W, BAR_TEAL) + "\n")
    stream_tail = ""; tail_think = False
    return think_secs, "", "", 0

async def _responder(msg: str):
    """Consome o stream do backend (chat_stream): session_id + deltas de texto + eventos
    (contexto → rodapé · etapa/passo → checklist das tools · fim → motivo) + erro."""
    global ctx_usado, ctx_total, ctx_model, ctx_reservado, checklist_base, modo_pendente
    global respondendo, session_id, pending_image, pending_name, stream_tail, tail_think, tok_count, tool_build, ultima_resposta, aguardando, pensando, think_t0, turno_t0, last_delta_t
    respondendo = True; aguardando = True                            # aguardando = TTFT (mostra "processando…")
    tok_count = 0; full = []; erro = None                            # contador total + reply + erro
    think_toks = 0; think_t0 = 0.0; think_secs = 0.0; pensando = False; blk_toks = 0
    turno_t0 = time.monotonic(); last_delta_t = time.monotonic()
    checklist.clear(); checklist_base = 0; motivo = None             # numeração do checklist recomeça a cada turno
    tool_build = {}
    img = pending_image; pending_image = None                        # consome o anexo (1 vez)
    nome = pending_name; pending_name = None
    W = _larg()
    _p("\n" + _titulo("🫵 você", W, BAR_AZUL, HBG_USER, NM_USER) + "\n" + _pad_top(W) + "\n")
    tag = f"📎 [imagem anexada] {nome}\n" if img else ""             # indicador claro (sem miniatura)
    _p(_corpo_md(tag + msg, W, BAR_AZUL) + "\n")
    _p("\n" + _titulo(f"{BOT} brazaia", W, BAR_TEAL, HBG_BOT, NM_BOT) + "\n")
    buf = ""; topo_feito = False
    pensamento = ""   # raciocínio do bloco ATUAL (o server etiqueta think/reply por-chamada; multi-caixa por transição)
    try:
        modo_envio, modo_pendente = modo_pendente, None          # /modo escolhido vai UMA vez; o server grava na sessão
        async for ev in chat_stream(msg, session_id, cfg, image=img, think=(think_mode != "off"), modo=modo_envio):
            if "session_id" in ev:
                session_id = ev["session_id"]                        # lembra a sessão
            elif ev.get("evento") == "contexto":                     # rodapé: prompt real / janela + teto de saída
                ctx_usado = ev.get("usado", 0); ctx_total = ev.get("total", 0)
                ctx_reservado = ev.get("reservado", ctx_reservado)
                ctx_model = ev.get("model", "") or ctx_model
            elif ev.get("evento") == "tool_args":                    # tool sendo MONTADA: mostra os args chegando
                aguardando = False; last_delta_t = time.monotonic()
                if not tool_build:                                   # 1º pedaço: fecha o que a chamada já escreveu
                    think_secs, pensamento, buf, blk_toks = _fecha_escrita(pensamento, buf, blk_toks, think_secs, W)
                b = tool_build.setdefault(ev.get("index", 0), {"tool": "", "args": "", "t0": time.monotonic()})
                b["tool"] = ev.get("tool") or b["tool"]; b["args"] += ev.get("delta", "")
            elif ev.get("evento") == "etapa":
                if ev.get("fase") == "inicio":                       # vai rodar tool: fecha o que a chamada já escreveu,
                    aguardando = False                               # pra o checklist ficar DEPOIS dele no scrollback
                    think_secs, pensamento, buf, blk_toks = _fecha_escrita(pensamento, buf, blk_toks, think_secs, W)
                    tool_build = {}                                  # montagem acabou → vira linha do checklist
                else:                                                # fim da rodada: fixa os passos no scrollback
                    _commit_checklist(W)
                    last_delta_t = time.monotonic()                  # volta pro LLM: loader conta o gap a partir daqui
            elif ev.get("evento") == "passo":
                _aplicar_passo(ev)
            elif ev.get("evento") == "guard":                        # server reprovou o que JÁ foi mostrado (ex.: id inventado)
                if buf.strip():
                    _p(_corpo_md(buf, W, BAR_TEAL) + "\n")
                buf = ""; stream_tail = ""; full.clear()             # /copiar fica só com a resposta válida
                av = (" ⚠ resposta acima descartada pela validação — refazendo" if ev.get("acao") == "refazendo"
                      else " ⚠ a nova tentativa também foi reprovada")
                _p(_corpo(f" \033[1;38;2;255;200;0m{av[1:]}", cell_len(av), W, None) + "\n")
            elif ev.get("evento") == "fim":
                motivo = ev.get("finish_reason")
            elif "delta" in ev:
                tok_count += 1; aguardando = False; last_delta_t = time.monotonic()   # chegou delta → reseta o relógio do gap
                modo = "think" if ev.get("think") else "reply"       # server já etiqueta (separação por-chamada no orchestrator)
                txt = ev["delta"]
                if modo == "think":
                    if think_mode == "off":                          # off: nem deveria vir raciocínio (belt-and-suspenders)
                        continue
                    pensamento += txt; think_toks += 1; blk_toks += 1
                    if not think_t0: think_t0 = time.monotonic()     # início DESTE bloco
                    if think_mode == "full":
                        stream_tail = pensamento; tail_think = True   # raciocínio digitando (âmbar)
                    else:
                        pensando = True                              # colap: só "pensando…"
                else:
                    if pensamento:                                   # transição think→reply: fecha ESTE bloco (multi-caixa)
                        think_secs += (time.monotonic() - think_t0) if think_t0 else 0.0
                        _fecha_raciocinio(pensamento, blk_toks, think_t0, W)
                        pensamento = ""; blk_toks = 0; think_t0 = 0.0
                        pensando = False; stream_tail = ""; tail_think = False
                    if not topo_feito:
                        _p(_pad_top(W) + "\n"); topo_feito = True
                    buf += txt; full.append(txt)                     # resposta "real"
                    p = _ponto_flush(buf)                            # solta bloco pronto (fora de cerca)
                    if p == -1 and len(buf) > 2500 and buf.count("```") % 2 == 0:
                        p = len(buf)                                 # force-flush: bloco gigante sem \n\n
                    if p != -1:
                        pronto, buf = buf[:p], buf[p + 2:]
                        _p(_corpo_md(pronto, W, BAR_TEAL) + "\n")
                    stream_tail = buf; tail_think = False            # rabo = o que falta → DIGITA no prompt
            elif ev.get("success") is False or "error" in ev or "code" in ev:   # ERRO do servidor (não ficar no escuro)
                erro = str(ev.get("message") or ev.get("error") or ev)[:200]
                if checklist:
                    _commit_checklist(W)
                m = f" ⚠ erro do servidor: {erro}"
                _p(_corpo(f" \033[1;38;2;255;90;90m{m[1:]}", cell_len(m), W, None) + "\n")
        if checklist:                                                # stream acabou no meio de uma rodada → fixa o que veio
            _commit_checklist(W)
        tool_build = {}
        if pensamento:                                               # sobrou raciocínio sem resposta depois → fecha a caixa
            think_secs += (time.monotonic() - think_t0) if think_t0 else 0.0
            _fecha_raciocinio(pensamento, blk_toks, think_t0, W)
        pensando = False; stream_tail = ""; tail_think = False        # some o rabo…
        if buf.strip():
            _p(_corpo_md(buf, W, BAR_TEAL) + "\n")                    # …e vira o Markdown final
        total = time.monotonic() - turno_t0
        resp_toks = tok_count - think_toks
        if motivo == "length":                                       # estourou MAX_STEPS no server
            av = " ⚠ limite de passos atingido — resposta parcial"
            _p(_corpo(f" \033[1;38;2;255;200;0m{av[1:]}", cell_len(av), W, None) + "\n")
        rzn = "ERRO" if erro else (motivo or "stop")
        th = f" · 💭 {think_toks}tok/{think_secs:.1f}s" if think_toks else ""
        info = f" · fim · {resp_toks} tok · {total:.1f}s{th} · {rzn}"
        _p(_corpo(f" {DIM_A}{info[1:]}", cell_len(info), W, None) + "\n")
    except Exception as e:
        pensando = False; stream_tail = ""; tail_think = False
        if checklist:
            _commit_checklist(W)
        tool_build = {}
        _p(_corpo(f" \033[38;2;255;90;90m⚠ falha no stream: {e}",
                  cell_len(f" ⚠ falha no stream: {e}"), W, None) + "\n")
    ultima_resposta = "".join(full)                                  # guarda p/ /copiar
    asyncio.create_task(_atualizar_arquivos())                       # o /abrir já sugere o que este turno gerou
    _p("\n")
    respondendo = False; aguardando = False; pensando = False

async def _ticker():
    global frame
    _ult_status = None
    while True:
        frame += 1
        # redesenha com animação viva OU quando o status do device muda (ex.: conectou no boot → vira online
        # sozinho, sem precisar o usuário digitar). Ocioso e estável = sem redraw (a seleção do terminal não some).
        if respondendo or stream_tail or checklist or gravando or voz_prep or transcrevendo or estado.device_status != _ult_status:
            _ult_status = estado.device_status
            try: get_app().invalidate()
            except Exception: pass
        await asyncio.sleep(0.08)

async def _transcrever(audio: bytes) -> str:
    """Manda o turno de áudio pro /ws/transcribe (STT-only) e devolve só o texto.
    (/ws/voice — pipeline completo com TTS — fica pro modo 'conversa por voz', fora do CLI.)"""
    import websockets
    from companion._json import dumps, loads
    url = f"{cfg.server_ws_url}/ws/transcribe"
    async with websockets.connect(url, max_size=None, ping_timeout=120,
                                  proxy=os.getenv("SOCKS_PROXY") or None) as ws:
        await ws.send(dumps({"type": "turn_start", "fmt": ("aac" if _IS_TERMUX else "pcm")}))
        await ws.send(audio)
        await ws.send(dumps({"type": "turn_end"}))
        async for msg in ws:
            if isinstance(msg, (bytes, bytearray)):
                continue                                 # nesse modo não volta áudio
            ev = loads(msg)
            if ev.get("type") == "final":
                return ev.get("text", "")
            if ev.get("type") == "error":
                _p(f"{DIM_A}   ⚠ {ev.get('text','')}{R}\n"); return ""
    return ""

async def _iniciar_voz(app) -> None:                   # /voz — começa a gravar LIVRE (sem suspender o TUI); Enter pára
    global gravando, voz_prep, _grav
    if gravando or voz_prep:
        return
    from companion.audio import GravacaoLivre
    voz_prep = True; app.invalidate()                  # rodapé: "preparando microfone…"
    _grav = GravacaoLivre()
    try:
        await _grav.iniciar()
    except Exception as e:
        voz_prep = False; _grav = None
        _p(f"{DIM_A}   ⚠ voz: {e}{R}\n"); app.invalidate(); return
    voz_prep = False; gravando = True; app.invalidate()  # rodapé: "gravando… (Enter pra parar)"

async def _parar_voz(app) -> None:                     # Enter durante /voz — para, transcreve e JOGA no input (não envia)
    global gravando, transcrevendo, _grav
    if not gravando or _grav is None:
        return
    gravando = False; transcrevendo = True; app.invalidate()   # rodapé: "transcrevendo áudio…" (sem buraco sem sinal)
    try:
        audio = await _grav.parar()
        texto = (await _transcrever(audio)).strip()
    except Exception as e:
        _grav = None; transcrevendo = False
        _p(f"{DIM_A}   ⚠ voz: {e}{R}\n"); app.invalidate(); return
    _grav = None; transcrevendo = False
    if texto:
        app.current_buffer.insert_text(texto.replace("\n", " "))   # → INPUT (sem \n: um \n faria o prompt ENVIAR); você edita/manda
    else:
        _p(f"{DIM_A}   (não entendi o áudio){R}\n")
    app.invalidate()

async def _anexar():                                  # /anexo — escolhe imagem (zenity) → base64
    global pending_image, pending_name
    try:
        proc = await asyncio.create_subprocess_exec(
            "zenity", "--file-selection", "--title=Anexar imagem",
            "--file-filter=Imagens | *.png *.jpg *.jpeg *.webp *.gif *.bmp", "--file-filter=Todos | *",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await proc.communicate()
        path = out.decode().strip()
        if not path:
            _p(f"{DIM_A}   anexo cancelado{R}\n"); return
        mime = mimetypes.guess_type(path)[0] or "image/png"
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        pending_image = f"data:{mime};base64,{b64}"
        pending_name = os.path.basename(path)
        kb = len(b64) * 3 // 4 // 1024
        # terminal (GNOME/VTE) não tem protocolo de imagem → sem miniatura, só indicador claro
        _p(f"{VERDE_A}   📎 [imagem anexada] {pending_name} · {kb} KB — mande a mensagem{R}\n")
    except FileNotFoundError:
        _p(f"{DIM_A}   zenity ausente — instale: sudo apt install zenity{R}\n")
    except Exception as e:
        _p(f"{DIM_A}   ⚠ anexo: {e}{R}\n")

async def _run_out(cmd: list) -> bytes | None:
    """Roda um comando e devolve o stdout (bytes) ou None se falhar/ausente."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await proc.communicate()
        return out if proc.returncode == 0 else None
    except FileNotFoundError:
        return None

def _ler_img_arquivo(caminho: str) -> tuple[bytes, str, str] | None:
    """Se 'caminho' (path ou file://) aponta pra um arquivo de imagem existente, lê (bytes, mime, NOME)."""
    if not caminho:
        return None
    p = caminho.strip().strip('"').strip("'")
    if p.startswith("file://"):
        from urllib.parse import unquote, urlparse
        p = unquote(urlparse(p).path)
    p = os.path.expanduser(p)
    mime = mimetypes.guess_type(p)[0] or ""
    if os.path.isfile(p) and mime.startswith("image/"):
        try:
            with open(p, "rb") as f:
                return f.read(), mime, os.path.basename(p)      # nome REAL do arquivo
        except Exception:
            return None
    return None

def _extrai_img_do_texto(msg: str) -> tuple[tuple[bytes, str, str] | None, str]:
    """Se o texto digitado/colado é (ou contém) um caminho de imagem, extrai o arquivo.
    Cobre o Ctrl+V que o terminal cola como TEXTO (caminho) em vez de acionar o handler.
    Retorna ((bytes, mime) ou None, texto_restante)."""
    g = _ler_img_arquivo(msg)                     # mensagem inteira é um caminho (inclui paths com espaço)
    if g:
        return g, ""
    toks = msg.split()
    if len(toks) > 1:
        g = _ler_img_arquivo(toks[0])             # "caminho + pergunta"
        if g:
            return g, " ".join(toks[1:])
        g = _ler_img_arquivo(toks[-1])            # "pergunta + caminho"
        if g:
            return g, " ".join(toks[:-1])
    return None, msg

async def _clip_imagem() -> tuple[bytes, str, str] | None:
    """Imagem do clipboard → (bytes, mime, nome), cobrindo: (1) bytes crus (screenshot / 'copiar imagem'),
    (2) ARQUIVO copiado no gerenciador (gnome-copied-files/uri-list = file://…)."""
    for cmd, mime in [(["wl-paste", "--type", "image/png"], "image/png"),
                      (["wl-paste", "--type", "image/jpeg"], "image/jpeg"),
                      (["xclip", "-selection", "clipboard", "-t", "image/png", "-o"], "image/png"),
                      (["xclip", "-selection", "clipboard", "-t", "image/jpeg", "-o"], "image/jpeg")]:
        out = await _run_out(cmd)
        if out and len(out) > 100:                               # (1) bytes de imagem de verdade (sem nome)
            return out, mime, "colado" + (mimetypes.guess_extension(mime) or ".png")
    for tipo in ["x-special/gnome-copied-files", "text/uri-list"]:   # (2) arquivo copiado no Nautilus/gerenciador
        for cmd in [["wl-paste", "--type", tipo],
                    ["xclip", "-selection", "clipboard", "-t", tipo, "-o"]]:
            out = await _run_out(cmd)
            if out:
                for linha in out.decode(errors="replace").splitlines():   # 1ª linha do gnome pode ser 'copy'/'cut'
                    got = _ler_img_arquivo(linha)
                    if got:
                        return got
    return None

async def _clip_texto() -> str:
    for cmd in [["wl-paste", "-n"], ["xclip", "-selection", "clipboard", "-o"]]:
        out = await _run_out(cmd)
        if out is not None:
            return out.decode(errors="replace")
    return ""

async def _colar(app):                                # Ctrl+V — imagem do clipboard → anexo; senão cola texto
    global pending_image, pending_name
    if respondendo or gravando:
        return
    got = await _clip_imagem()
    if not got:                                                  # (3) o texto do clipboard é um caminho de imagem?
        txt = await _clip_texto()
        got = _ler_img_arquivo(txt)
        if not got:                                              # não é imagem → cola o texto normal
            if txt:
                app.current_buffer.insert_text(txt.replace("\n", " ").strip())
            elif not shutil.which("wl-paste") and not shutil.which("xclip"):
                _p(f"{DIM_A}   colar: instale wl-clipboard (Wayland) ou xclip (X11){R}\n")
            return
    data, mime, nome = got
    pending_image = f"data:{mime};base64," + base64.b64encode(data).decode()
    pending_name = nome
    _p(f"{VERDE_A}   📎 [imagem colada] {nome} · {len(data)//1024} KB — mande a mensagem{R}\n")
    app.invalidate()

def _quando(ts: float) -> str:
    """updated_at → 'há 5 min' / 'há 3 h' / 'ontem 14:02' / '28/10 09:15' (curto, p/ a lista de sessões)."""
    if not ts:
        return "—"
    d = time.time() - ts
    if d < 3600:
        return f"há {max(1, int(d // 60))} min"
    if d < 6 * 3600:
        return f"há {int(d // 3600)} h"
    lt = time.localtime(ts)
    if time.strftime("%d/%m", lt) == time.strftime("%d/%m", time.localtime(time.time() - 86400)):
        return time.strftime("ontem %H:%M", lt)
    return time.strftime("%d/%m %H:%M", lt)

async def _atualizar_sessoes(tag: str | None = None) -> bool:
    """Busca a lista no server (fica em sessoes_cache). tag filtra (ex.: "replica"). False se o server não respondeu."""
    global sessoes_cache, sessoes_tag
    try:
        sessoes_cache = await listar_sessoes(cfg, tag)
        sessoes_tag = tag
        return True
    except Exception as e:
        _p(f"{DIM_A}   ⚠ não consegui listar as sessões: {e}{R}\n")
        return False

def _mostrar_sessoes(page: int = 1) -> None:
    """Lista paginada (10 por página), mais recente primeiro; a atual vem marcada com ●."""
    if not sessoes_cache:
        _p(f"{DIM_A}   (nenhuma sessão com conversa ainda){R}\n"); return
    por = 10
    tot = (len(sessoes_cache) + por - 1) // por
    page = max(1, min(page, tot))
    ini = (page - 1) * por
    filtro = f" · etiqueta {sessoes_tag}" if sessoes_tag else ""
    _p(f"{DIM_A}   ── sessões {ini + 1}–{min(ini + por, len(sessoes_cache))} de {len(sessoes_cache)}{filtro} · pág {page}/{tot} ──{R}\n")
    for i in range(ini, min(ini + por, len(sessoes_cache))):
        s = sessoes_cache[i]
        atual = f"{VERDE_A}●{DIM_A}" if s["session_id"] == session_id else " "
        icone = "🎓 " if s.get("modo") == "tutor" else ""
        nome = s.get("titulo") or s.get("preview", "")              # título (réplicas) ou a 1ª fala
        _p(f"{DIM_A}  {atual}{i + 1:>3}. {_quando(s.get('updated_at', 0)):>12} · {s.get('turnos', 0):>2} turnos · "
           f"{icone}{nome[:60]}{R}\n")
    prox = f"/sessoes {page + 1} → próxima · " if page < tot else ""
    _p(f"{DIM_A}   ({prox}/sessao N retoma · /sessao <busca> + Tab · /nova começa outra){R}\n")

def _texto_de(content) -> str:
    """Texto de um content str ou multimodal (lista) — 📎 se tiver imagem."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        txt = " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
        img = any(isinstance(p, dict) and p.get("type") == "image_url" for p in content)
        return ("📎 [imagem] " if img else "") + txt
    return str(content or "")

def _linha_passo(i: int, desc: str, est: str, det: str, W: int) -> None:
    """Uma linha do checklist FIXADA (mesmo visual do _commit_checklist) — usada no replay."""
    m, _, ans = _MARCA.get(est, _MARCA["ok"])
    txt = f" {m} {i}. {desc}"
    _p(_corpo(f" {ans}{txt[1:]}", cell_len(txt), W, BAR_TEAL, bg=SKEL_RGB) + "\n")
    if det:
        d = _uma_linha(f"   └ {det}", W - 2)
        _p(_corpo(f"{DIM_A}{d}", cell_len(d), W, BAR_TEAL, bg=SKEL_RGB) + "\n")

def _render_narrativa(cards: list) -> None:
    """Replay FIEL (o que a tela mostrou em cada turno): você · checklist das tools · resposta · aviso de limite."""
    W = _larg()
    for card in cards:
        u = ("📎 [imagem anexada]\n" if card.get("image") else "") + (card.get("user") or "")
        _p("\n" + _titulo("🫵 você", W, BAR_AZUL, HBG_USER, NM_USER) + "\n" + _pad_top(W) + "\n")
        _p(_corpo_md(u, W, BAR_AZUL) + "\n")
        _p("\n" + _titulo(f"{BOT} brazaia", W, BAR_TEAL, HBG_BOT, NM_BOT) + "\n")
        for i, it in enumerate(card.get("checklist", []), 1):
            _linha_passo(i, it.get("desc", ""), it.get("estado", "ok"), it.get("det", ""), W)
        if card.get("reply"):
            _p(_pad_top(W) + "\n" + _corpo_md(card["reply"], W, BAR_TEAL) + "\n")
        if card.get("finish_reason") == "length":
            av = " ⚠ limite de passos atingido — resposta parcial"
            _p(_corpo(f" \033[1;38;2;255;200;0m{av[1:]}", cell_len(av), W, None) + "\n")

def _render_historico(history: list) -> None:
    """Replay a partir das MENSAGENS (sessões sem narrativa completa, ex.: turnos por voz)."""
    W = _larg(); n = 0; abertas: dict = {}                    # tool_call id → nº da linha (pra casar o resultado)
    for m in history:
        role, c = m.get("role"), m.get("content")
        if role == "user":
            n = 0
            _p("\n" + _titulo("🫵 você", W, BAR_AZUL, HBG_USER, NM_USER) + "\n" + _pad_top(W) + "\n")
            _p(_corpo_md(_texto_de(c) or "(vazio)", W, BAR_AZUL) + "\n")
            _p("\n" + _titulo(f"{BOT} brazaia", W, BAR_TEAL, HBG_BOT, NM_BOT) + "\n")
        elif role == "assistant":
            for tc in (m.get("tool_calls") or []):
                n += 1
                abertas[tc.get("id")] = (n, (tc.get("function") or {}).get("name", "tool"))
            if c:
                _p(_pad_top(W) + "\n" + _corpo_md(_texto_de(c), W, BAR_TEAL) + "\n")
        elif role == "tool":
            i, nome = abertas.pop(m.get("tool_call_id"), (n, "tool"))
            res = _texto_de(c)
            _linha_passo(i, nome, "err" if res.startswith(("[erro", "[falha", "[timeout", "[loop")) else "ok",
                         " ".join(res.split())[:120], W)

async def _retomar(sid: str) -> None:
    """Troca pra sessão sid: replay do que já foi conversado + rodapé com o contexto dela."""
    global session_id, ctx_usado, ctx_total, ctx_model, ctx_reservado, ultima_resposta, modo_sessao, arquivos_cache
    try:
        data = await carregar_sessao(cfg, sid)
    except Exception as e:
        _p(f"{DIM_A}   ⚠ não consegui abrir a sessão: {e}{R}\n"); return
    session_id = sid; arquivos_cache = []
    meta = data.get("meta") or {}
    modo_sessao = meta.get("modo") or "chat"
    hist, narr = data.get("history", []), data.get("narrative", [])
    nome = f" · {meta['titulo']}" if meta.get("titulo") else ""
    _p(f"\n{VERDE_A}   ↺ sessão {sid[:8]} retomada{nome}{' · 🎓 modo tutor' if modo_sessao == 'tutor' else ''}{R}\n")
    turnos = sum(1 for m in hist if m.get("role") == "user")
    if narr and len(narr) == turnos:                          # narrativa cobre TODOS os turnos → replay fiel
        _render_narrativa(narr)
        ultima_resposta = narr[-1].get("reply", "") or ultima_resposta
    else:                                                     # turnos sem narrativa (voz, versões antigas) → pelas mensagens
        _render_historico(hist)
        for m in reversed(hist):
            if m.get("role") == "assistant" and m.get("content"):
                ultima_resposta = _texto_de(m["content"]); break
    c = data.get("contexto") or {}
    if c:
        ctx_usado, ctx_total = c.get("usado", 0), c.get("total", 0)
        ctx_reservado = c.get("reservado", ctx_reservado); ctx_model = c.get("model", "") or ctx_model
    _p(f"\n{DIM_A}   — fim do histórico · continue de onde parou —{R}\n\n")
    await _atualizar_arquivos()

async def _cmd_sessao(arg: str) -> None:
    """/sessao N (posição na lista) ou /sessao <início do id>."""
    if not sessoes_cache:
        await _atualizar_sessoes()
    alvo = None
    if arg.isdigit() and 1 <= int(arg) <= len(sessoes_cache):
        alvo = sessoes_cache[int(arg) - 1]["session_id"]
    elif arg:
        ids = [s["session_id"] for s in sessoes_cache if s["session_id"].startswith(arg)]
        alvo = ids[0] if len(ids) == 1 else None
    if alvo:
        await _retomar(alvo)
    else:
        _p(f"{DIM_A}   uso: /sessao N  ou  /sessao <início do id>  (veja /sessoes){R}\n")

async def _cmd_live(fone: bool, modo: str = "continuo") -> None:
    """/live [wake|once] [fone] — sai do chat pro PAINEL de voz na MESMA sessão; ao voltar, mostra os turnos falados."""
    global session_id, ctx_usado, ctx_total, ctx_model, ctx_reservado, ultima_resposta
    if modo == "wake" and _IS_TERMUX:
        _p(f"{DIM_A}   /live wake não existe no celular (sem áudio contínuo pra escutar o \"braza\") — use /live ou /live once{R}\n"); return
    antes = 0
    if session_id:                                            # quantos turnos já tinha → depois mostra só os novos
        try:
            antes = len((await carregar_sessao(cfg, session_id)).get("narrative", []))
        except Exception:
            pass
    try:
        from companion.live import rodar_live, rodar_live_termux
        info = {"device": cfg.device_id, "modelo": (ctx_model or "—").split("/")[-1]}
        async with in_terminal():                             # suspende o prompt_toolkit; o painel usa a tela inteira
            if _IS_TERMUX:                                    # celular: por turnos (Enter envia), sem áudio contínuo
                sid = await rodar_live_termux(cfg, session_id, modo=modo, info=info)
            else:
                sid = await rodar_live(cfg, session_id, fone=fone, modo=modo, info=info)
    except ModuleNotFoundError as e:                          # ex.: WSL (venv leve, sem áudio)
        _p(f"{DIM_A}   ⚠ live precisa de áudio ({e.name} não instalado aqui) — use no note ou no Windows (braza cli){R}\n"); return
    except Exception as e:
        _p(f"{DIM_A}   ⚠ live: {type(e).__name__}: {e}{R}\n"); return
    if not sid:
        return
    session_id = sid
    try:
        data = await carregar_sessao(cfg, sid)
    except Exception as e:
        _p(f"{DIM_A}   ⚠ não consegui recarregar a sessão: {e}{R}\n"); return
    novos = (data.get("narrative") or [])[antes:]
    _p(f"\n{VERDE_A}   🎙 voltou do live · {len(novos)} turno(s) falado(s) · sessão {sid[:8]}{R}\n")
    if novos:
        _render_narrativa(novos)
        ultima_resposta = novos[-1].get("reply", "") or ultima_resposta
    c = data.get("contexto") or {}
    if c:
        ctx_usado, ctx_total = c.get("usado", 0), c.get("total", 0)
        ctx_reservado = c.get("reservado", ctx_reservado); ctx_model = c.get("model", "") or ctx_model
    _p("\n")

async def _cmd_sessoes(page: int, tag: str | None = None) -> None:
    if await _atualizar_sessoes(tag):
        _mostrar_sessoes(page)

async def _cmd_pesquisar(termo: str) -> None:
    """/sessoes <termo> — filtra por título, 1ª fala ou etiqueta (sem acento). /sessao N usa ESSA lista."""
    global sessoes_cache, sessoes_tag
    if not await _atualizar_sessoes():
        return
    sessoes_cache = _sessoes_filtradas(termo); sessoes_tag = f'filtro "{termo}"'
    if not sessoes_cache:
        _p(f"{DIM_A}   nenhuma sessão com \"{termo}\"{R}\n"); return
    _mostrar_sessoes(1)

async def _atualizar_arquivos() -> None:
    """Recarrega em silêncio os arquivos da sessão atual (alimenta o menu do /abrir)."""
    global arquivos_cache
    if not session_id:
        arquivos_cache = []; return
    try:
        arquivos_cache = await listar_arquivos(cfg, session_id)
    except Exception:
        pass

async def _cmd_arquivos() -> None:
    """/arquivos — o que o agente gerou NESTA sessão (HTML, imagens…), numerado pro /abrir."""
    global arquivos_cache
    if not session_id:
        _p(f"{DIM_A}   nenhuma sessão aberta (/sessoes · /sessao N){R}\n"); return
    try:
        arquivos_cache = await listar_arquivos(cfg, session_id)
    except Exception as e:
        _p(f"{DIM_A}   ⚠ não consegui listar: {e}{R}\n"); return
    if not arquivos_cache:
        _p(f"{DIM_A}   (esta sessão não gerou arquivos){R}\n"); return
    _p(f"{DIM_A}   ── arquivos da sessão {session_id[:8]} ──{R}\n")
    for i, a in enumerate(arquivos_cache, 1):
        nome = a.get("title") or a["file_id"]
        desc = f" — {a['desc']}" if a.get("desc") else ""
        _p(f"{DIM_A}   {i:>3}. {a.get('ts', ''):>11} · {a.get('ext', ''):>4} · {nome[:50]}{desc[:40]}{R}\n")
    _p(f"{DIM_A}   (/abrir N abre aqui neste device){R}\n")

def _abrir_local(caminho: str) -> None:
    """Abre um arquivo baixado com o app padrão do device (navegador pro HTML, visualizador pra imagem)."""
    import subprocess
    if _IS_TERMUX:
        subprocess.Popen(["termux-open", caminho], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif sys.platform == "win32":
        os.startfile(caminho)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", caminho], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)

async def _cmd_abrir(arg: str) -> None:
    """/abrir N (da lista do /arquivos) ou /abrir <file_id> — baixa do server e abre neste device."""
    if arg.isdigit() and arquivos_cache and 1 <= int(arg) <= len(arquivos_cache):
        fid = arquivos_cache[int(arg) - 1]["file_id"]
    elif arg:
        fid = arg.strip("[]").removeprefix("file_id=")
    else:
        _p(f"{DIM_A}   uso: /abrir N (veja /arquivos) ou /abrir <file_id>{R}\n"); return
    try:
        dados, nome = await baixar_arquivo(cfg, fid)
    except Exception as e:
        _p(f"{DIM_A}   ⚠ não consegui baixar {fid}: {e}{R}\n"); return
    pasta = os.path.expanduser("~/brazaia-arquivos")             # no celular ~/brazaia é o repo → outra pasta
    os.makedirs(pasta, exist_ok=True)
    caminho = os.path.join(pasta, nome)
    with open(caminho, "wb") as f:
        f.write(dados)
    try:
        if _IS_TERMUX:                                          # o navegador do Android NÃO lê arquivo do Termux
            from companion.plataform import show_html, show_image   # (content:// → "não foi possível acessar")
            ext = os.path.splitext(nome)[1].lower()
            r = await (show_html(dados.decode("utf-8", "replace")) if ext in (".html", ".htm") else show_image(dados))
            if r.startswith("[erro"):
                raise RuntimeError(r)
        else:
            _abrir_local(caminho)
        _p(f"{VERDE_A}   ↗ abrindo {nome} ({len(dados) // 1024} KB) · salvo em {caminho}{R}\n")
    except Exception as e:
        _p(f"{DIM_A}   salvo em {caminho}, mas não consegui abrir: {e}{R}\n")

def _sem_acento(t: str) -> str:
    """minúsculas e sem acento — a busca acha "replica" em "réplica"."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", (t or "").lower()) if unicodedata.category(c) != "Mn")

# comandos com OPÇÕES em níveis: escolheu o comando → abre o 1º nível; escolheu → abre o próximo.
# Cada nível = [(opção, descrição)]. Enter num comando com nível faltando EXPANDE em vez de executar.
_NIVEIS: dict[str, list[list[tuple[str, str]]]] = {
    "/live": ([[("continuo", "por turnos: Enter envia"), ("once", "um turno e volta")]] if _IS_TERMUX else
              [[("alto-falante", "mic mudo enquanto ele fala"), ("fone", "pode interromper falando")],
               [("continuo", "sempre ouvindo"), ("wake", 'espera "braza"'), ("once", "um turno e volta")]]),
    "/think": [[("off", "desliga"), ("full", "caixa completa"), ("colap", "só o resumo")]],
    "/modo": [[("tutor", "sessão de estudo (metodologia)"), ("chat", "assistente geral")]],
}
_DESC = {"/voz": "fala vira texto no input", "/live": "conversa falada", "/anexo": "imagem", "/think": "raciocínio",
         "/sessoes": "lista; digite pra filtrar", "/sessao": "retomar uma", "/nova": "começar outra", "/modo": "chat ou tutor",
         "/arquivos": "o que a sessão gerou", "/abrir": "abrir um arquivo gerado", "/limpar": "apaga o input",
         "/ajuda": "", "/sair": ""}

def _tarefa(coro) -> None:
    """Roda um comando em segundo plano MOSTRANDO o erro se ele quebrar (asyncio.create_task engole a exceção:
    o comando simplesmente não fazia nada, sem aviso)."""
    def _fim(t: asyncio.Task) -> None:
        if not t.cancelled() and t.exception():
            e = t.exception()
            _p(f"\033[38;2;255;90;90m   ⚠ {type(e).__name__}: {e}{R}\n")
    asyncio.create_task(coro).add_done_callback(_fim)

def _sessoes_filtradas(termo: str) -> list:
    t = _sem_acento(termo)
    return [s for s in sessoes_cache if not t or t in _sem_acento(
        f"{s.get('titulo') or ''} {s.get('preview', '')} {' '.join(s.get('tags') or [])} {s['session_id']}")]

class _Comp(Completer):
    """Autocomplete em NÍVEIS: só os comandos na raiz; escolheu um → mostra as opções dele, e assim por diante.
    No meio do texto, só os comandos de edição (/voz, /limpar)."""
    CMDS = (["/voz", "/live", "/think", "/sessoes", "/sessao", "/nova", "/modo", "/arquivos", "/abrir", "/limpar", "/ajuda", "/sair"] if _IS_TERMUX
            else ["/voz", "/live", "/anexo", "/think", "/sessoes", "/sessao", "/nova", "/modo", "/arquivos", "/abrir", "/limpar", "/ajuda", "/sair"])

    def get_completions(self, document, complete_event):
        txt = _segmento_comando(document.text_before_cursor)   # comando no INÍCIO ou no FIM de um texto já escrito
        if txt is None:
            return
        partes = txt.split(" ")
        cmd, frag = partes[0], partes[-1]
        if len(partes) == 1:                                    # raiz: cada comando UMA vez
            for c in self.CMDS:
                if c.startswith(cmd):
                    seta = " ›" if c in _NIVEIS else ""
                    yield Completion(c, start_position=-len(cmd), display=f"{c}{seta}" + (f"  ({_DESC[c]})" if _DESC.get(c) else ""))
            return
        if cmd in ("/sessao", "/sessoes"):                     # o que vem depois FILTRA (título, fala, etiqueta, sem acento)
            termo = " ".join(partes[1:])
            for s in _sessoes_filtradas(termo)[:50]:
                i = sessoes_cache.index(s) + 1
                nome = s.get("titulo") or s.get("preview", "")
                disp = f"{i}. {_quando(s.get('updated_at', 0))} · {'🎓 ' if s.get('modo') == 'tutor' else ''}{nome[:45]}"
                if cmd == "/sessao":
                    yield Completion(str(i), start_position=-len(termo), display=disp)
                else:                                           # escolheu no /sessoes → vira "/sessao N" (Enter retoma)
                    yield Completion(f"/sessao {i}", start_position=-len(txt), display=disp)
            return
        if cmd == "/abrir":                                    # os arquivos da sessão (filtra pelo título)
            termo = _sem_acento(" ".join(partes[1:]))
            for i, a in enumerate(arquivos_cache, 1):
                nome = a.get("title") or a["file_id"]
                if not termo or termo in _sem_acento(f"{i} {nome} {a.get('desc', '')} {a['file_id']}"):
                    yield Completion(str(i), start_position=-len(" ".join(partes[1:])),
                                     display=f"{i}. {a.get('ts', '')} · {a.get('ext', '')} · {nome[:50]}")
            return
        niveis = _NIVEIS.get(cmd)
        nivel = len(partes) - 2                                  # 0 = 1º nível de opções
        if niveis and nivel < len(niveis):
            for op, d in niveis[nivel]:
                if op.startswith(frag):
                    yield Completion(op, start_position=-len(frag), display=f"{op}{' ›' if nivel + 1 < len(niveis) else ''}  ({d})")

def _segmento_comando(txt: str) -> str | None:
    """O pedaço que é COMANDO: o texto todo se começa com "/", ou o trecho do último " /<comando>" até o fim
    (ex.: "me explica isso /voz" → "/voz"; "anotei /live fone" → "/live fone"). None = não tem comando."""
    if txt.startswith("/"):
        return txt
    i = txt.rfind(" /")
    while i != -1:
        seg = txt[i + 1:]
        cmd = seg.split(" ")[0]
        if any(c.startswith(cmd) for c in _Comp.CMDS):         # ainda digitando o comando também vale
            return seg
        i = txt.rfind(" /", 0, i)
    return None

def _faltam_opcoes(msg: str) -> bool:
    """Comando com níveis e opção faltando (ex.: "/live" ou "/live fone")? → o Enter EXPANDE em vez de executar."""
    partes = msg.split()
    niveis = _NIVEIS.get(partes[0])
    if not niveis:
        return False
    return len(partes) - 1 < len(niveis)

def _dispatch(msg: str, app) -> None:
    global session_id, think_mode, modo_sessao, modo_pendente, arquivos_cache
    partes = msg.split()
    cmd = partes[0]
    if cmd in ("/sair", "sair"):
        app.exit()
    elif cmd in ("/anexo", "/img"):
        if _IS_TERMUX:
            _p(f"{DIM_A}   /anexo não disponível no Termux (sem zenity/clipboard){R}\n")
        else:
            _tarefa(_anexar())
    elif cmd == "/voz":
        _tarefa(_iniciar_voz(app))
    elif cmd == "/think":
        modos = ["off", "full", "colap"]
        if len(partes) > 1 and partes[1] in modos:
            think_mode = partes[1]
        else:
            think_mode = modos[(modos.index(think_mode) + 1) % 3]    # cicla off → full → colap
        desc = {"off": "desligado", "full": "completo (caixa)", "colap": "colapsado (só resumo)"}[think_mode]
        _p(f"{VERDE_A}   💭 thinking: {think_mode} — {desc}{R}\n")
    elif cmd == "/sessoes":                            # /sessoes [pág] · /sessoes <termo> (filtra: título, fala, etiqueta)
        resto = " ".join(partes[1:])
        if not resto or resto.isdigit():
            _tarefa(_cmd_sessoes(int(resto) if resto else 1))
        else:
            _tarefa(_cmd_pesquisar(resto))
    elif cmd == "/arquivos":
        _tarefa(_cmd_arquivos())
    elif cmd == "/abrir":
        _tarefa(_cmd_abrir(partes[1] if len(partes) > 1 else ""))
    elif cmd == "/modo":                               # chat | tutor — vai na próxima mensagem e fica gravado na sessão
        if len(partes) > 1 and partes[1] in ("chat", "tutor"):
            modo_sessao = modo_pendente = partes[1]
            _p(f"{VERDE_A}   modo {'🎓 tutor (metodologia de estudo)' if modo_sessao == 'tutor' else 'chat'} — vale a partir da próxima mensagem{R}\n")
        else:
            _p(f"{DIM_A}   modo atual: {modo_sessao} · uso: /modo tutor | /modo chat{R}\n")
    elif cmd == "/sessao":
        _tarefa(_cmd_sessao(partes[1] if len(partes) > 1 else ""))
    elif cmd == "/live":                               # painel de voz na mesma sessão (q/Esc volta)
        if respondendo:
            _p(f"{DIM_A}   espere a resposta terminar pra entrar no live{R}\n")
        else:
            args = partes[1:]
            modo = "wake" if "wake" in args else ("once" if "once" in args else "continuo")
            _tarefa(_cmd_live(fone="fone" in args, modo=modo))
    elif cmd == "/nova":                               # próxima mensagem abre sessão nova (o server cria)
        session_id = None
        arquivos_cache = []
        if modo_sessao != "chat" and modo_pendente is None:          # nova sessão volta pro chat (a não ser que /modo antes)
            modo_sessao = "chat"
        _p(f"{VERDE_A}   ✚ nova sessão — a próxima mensagem começa do zero{R}\n")
    elif cmd == "/limpar":                             # o Enter já esvaziou o input
        pass
    elif cmd in ("/ajuda", "/help"):
        extra = "" if _IS_TERMUX else " · /anexo · Ctrl+V cola imagem"
        _p(f"{DIM_A}   comandos: /voz (voz→texto) · /live [wake|once] [fone] (conversa falada; q volta) · /think [off|full|colap] (cicla se sem arg) · /sessoes [filtro] · "
           f"/sessao N|id · /nova · /modo tutor|chat · /arquivos · /abrir N · /limpar (ou Ctrl+U){extra} · /sair{R}\n"
           f"{DIM_A}   comandos com › abrem opções: escolha e o próximo nível aparece. /voz e /limpar valem no fim de um texto já escrito.{R}\n")
    else:
        _p(f"{DIM_A}   comando desconhecido: {cmd} (tente /ajuda){R}\n")

def _device_de_fundo() -> bool:
    """No celular, o supervisor (companion/boot) roda `companion.connect --fg` com o MESMO DEVICE_ID do
    ~/.brazaia.env. Se o CLI também conectasse, tomaria o registro e, ao sair, o agente apagaria o device
    (o de fundo ficaria sem rota). Só no Termux e só se o --device não trocou o nome."""
    if not _IS_TERMUX or os.getenv("BRAZA_DEVICE_EXPLICITO"):
        return False
    try:
        from companion.connect import _pid_salvo, _pid_vivo
        pid = _pid_salvo()
        return bool(pid and _pid_vivo(pid))
    except Exception:
        return False

async def main() -> None:
    kb = KeyBindings()
    @kb.add("c-c")
    @kb.add("c-d")
    def _(e): e.app.exit()
    @kb.add("c-u")                                              # Ctrl+U = apaga o input inteiro
    def _(e): e.app.current_buffer.text = ""
    @kb.add("c-v")                                              # Ctrl+V = cola imagem do clipboard (ou texto)
    def _(e): asyncio.create_task(_colar(e.app))
    @kb.add("enter")
    def _(e):                                                   # Enter = MANDA a mensagem (não fecha o prompt)
        if gravando or voz_prep:                               # Enter durante /voz = PARA a gravação (NUNCA envia)
            if gravando:
                asyncio.create_task(_parar_voz(e.app))
            return
        global pending_image, pending_name
        buf = e.app.current_buffer
        msg = buf.text.strip()
        if not msg:
            return
        if msg == "/abrir" and arquivos_cache:                  # /abrir sem número → mostra os arquivos pra escolher
            buf.text = "/abrir "; buf.cursor_position = len(buf.text)
            buf.start_completion(select_first=False); return
        if msg.startswith("/") and _faltam_opcoes(msg):        # comando com opções faltando → abre o próximo nível
            buf.text = msg + " "; buf.cursor_position = len(buf.text)
            buf.start_completion(select_first=False); return
        seg = None if msg.startswith("/") else _segmento_comando(msg)
        if seg and seg.split(" ")[0] in _Comp.CMDS:            # comando no FIM de um texto já escrito: executa e MANTÉM o texto
            resto = msg[: len(msg) - len(seg)].rstrip()
            cmd = seg.split(" ")[0]
            if cmd == "/limpar":
                buf.text = ""; return
            if _faltam_opcoes(seg):                             # ainda falta opção → abre o próximo nível ali mesmo
                buf.text = f"{resto} {seg} "; buf.cursor_position = len(buf.text)
                buf.start_completion(select_first=False); return
            buf.text = resto + " "; buf.cursor_position = len(buf.text)
            if cmd == "/voz":                                   # dita mais um pedaço: a fala entra depois do texto
                _tarefa(_iniciar_voz(e.app))
            else:
                _dispatch(seg, e.app)
            return
        if respondendo:                                         # respondendo: segura o texto na caixa (não perde)
            return
        buf.text = ""
        got, resto = _extrai_img_do_texto(msg)                 # caminho de imagem (colado como texto) → anexa
        if got:                                                # ANTES do check de comando: paths começam com '/'
            data, mime, nome = got
            pending_image = f"data:{mime};base64," + base64.b64encode(data).decode()
            pending_name = nome
            if resto.strip():
                asyncio.create_task(_responder(resto.strip()))  # tinha pergunta junto → manda já
            else:
                _p(f"{VERDE_A}   📎 [imagem anexada] {nome} · {len(data)//1024} KB — escreva a mensagem{R}\n")
            return
        if msg.startswith("/") or msg == "sair":               # comandos: /sessoes /anexo /sair …
            _dispatch(msg, e.app); return
        asyncio.create_task(_responder(msg))                   # resposta imprime ACIMA (input fica vivo)

    global cfg
    cfg = load_config()                                          # backend REAL (API precisa estar no ar)
    estilo = Style.from_dict({                                    # mata o cinza (reverse) padrão do toolbar
        "bottom-toolbar": "noreverse bg:default",
        "bottom-toolbar.text": "noreverse bg:default",
    })
    session = PromptSession(key_bindings=kb, completer=_Comp(),
                            complete_while_typing=True, style=estilo)
    _osc_on()
    try:
        await _banner()                                         # "brazaia" no startup (colado no fluxo)
        _p(f"{DIM_A}   digite e Enter · /voz · /live{'' if _IS_TERMUX else ' · /anexo · Ctrl+V cola imagem'} · /sessoes · /sair{R}\n")
        if await _atualizar_sessoes() and sessoes_cache:             # só avisa (não despeja a lista no startup)
            ult = sessoes_cache[0]
            _p(f"{DIM_A}   {len(sessoes_cache)} sessões · última {_quando(ult.get('updated_at', 0))}: "
               f"\"{ult.get('preview', '')[:50]}\" → /sessao 1 retoma · /sessoes lista{R}\n")
        asyncio.create_task(_ticker())
        import companion.connect as _dev                        # status vai pro FOOTER, sem spam no topo
        _dev.log = lambda *a, **k: None                          # silencia o log do connect (ele seta estado.device_status)
        if _device_de_fundo():                                  # Termux: o supervisor já mantém ESTE device conectado
            estado.device_online = True; estado.device_status = "online"
            _p(f"{DIM_A}   device {cfg.device_id}: usando o companion de fundo (supervisor){R}\n")
        else:
            asyncio.create_task(conectar(cfg))                  # tools de device REAIS (reconecta sozinho)
        with patch_stdout():
            try:
                await session.prompt_async(_prompt_msg, bottom_toolbar=_toolbar)   # sem refresh_interval: redraw só via _ticker quando há animação (senão a seleção do terminal some)
            except (EOFError, KeyboardInterrupt):
                pass
    finally:
        _osc_off()                                              # restaura o terminal

if __name__ == "__main__":
    asyncio.run(main())
