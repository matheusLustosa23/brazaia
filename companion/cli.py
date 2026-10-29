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
from prompt_toolkit.application import get_app
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.styles import Style
from rich.cells import cell_len

from companion.render import md_ansi
from companion.config import load_config, CompanionConfig
from companion.chat_client import chat_stream
from companion.connect import conectar                 # loop de device REAL (handshake + RPC + reconexão)
from companion.state import estado                    # estado.device_online (status no footer)
from companion.plataform import _IS_TERMUX             # adapta o CLI ao Termux (voz AAC, sem anexo/clipboard)

cfg: CompanionConfig = None  # type: ignore[assignment]  # setado no main (load_config)
session_id = None     # capturado do 1º evento do backend
gravando = False      # True enquanto /voz está gravando (LIVRE, até Enter)
voz_prep = False      # True no "preparando microfone…" (antes de começar a gravar)
_grav = None          # GravacaoLivre ativa (start/stop manual, controlado pelo Enter)
pending_image = None  # data URL da imagem anexada (vai na próxima mensagem)
pending_name = None   # nome do arquivo anexado (só p/ exibir no card)
ultima_resposta = ""  # último reply do LLM (limpo, sem barras) — pra /copiar
stream_tail = ""      # "rabo" do bloco sendo DIGITADO (typewriter na região viva do prompt)
tail_think = False    # True quando o rabo é RACIOCÍNIO (<think>), p/ estilo diferente da resposta
aguardando = False    # True entre mandar e o 1º token chegar (TTFT) → mostra "processando…"
think_mode = "off"    # thinking: "off" | "full" (caixa) | "colap" (só resumo). Toggle /think
pensando = False      # colap: True enquanto recebe o <think> (mostra "pensando…" em vez do texto)
think_t0 = 0.0        # início do raciocínio (p/ o tempo no modo colapsado)
turno_t0 = 0.0        # início do turno (p/ o tempo total no rodapé/loader)
tok_count = 0         # contador de tokens da resposta atual (ao vivo, estilo Claude)
ctx_usado = 0; ctx_total = 0; ctx_model = ""; ctx_reservado = 0   # contexto + teto de saída → footer
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
    sys.stdout.write(f" {BAR_TEAL}{BOT}{R}  {BAR_AZUL}companion · online{R}\n"); sys.stdout.flush()
    await asyncio.sleep(0.6)
frame = 0
respondendo = False

def _p(s: str) -> None:
    pf(ANSI(s), end="")

def _prompt_msg() -> StyleAndTextTuples:
    """Rabo do texto sendo digitado (typewriter) ACIMA da caixa de input fixa no rodapé.
    Tudo vive no rodapé, não vai pro histórico."""
    w = _larg()
    linhas: StyleAndTextTuples = []
    if voz_prep:                                               # /voz: preparando o mic
        linhas.append(("bold #e5c07b", "   ⚙ preparando microfone…\n"))
    elif gravando:                                             # /voz: gravando livre até o Enter
        linhas.append(("bold #39d353", "   🎤 gravando… (Enter pra parar e jogar no input)\n"))
    if pensando:                                               # colap: raciocinando (não mostra o texto, só o tempo)
        sp = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[frame % 10]
        secs = (time.monotonic() - think_t0) if think_t0 else 0.0
        linhas.append(("bold #e5c07b", f"   {sp} 💭 pensando… {secs:.0f}s\n"))
    elif aguardando:                                           # mandou e espera o 1º token (TTFT) → não fica card vazio
        sp = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[frame % 10]
        secs = (time.monotonic() - turno_t0) if turno_t0 else 0.0
        linhas.append(("bold #4a9eff", f"   {sp} processando… {secs:.0f}s\n"))
    if stream_tail:                                            # RABO digitando (bg escuro, estilo Ollama)
        cauda = stream_tail[-400:]                              # cap por CHARS: bloco gigante não trava o render
        lim = _larg() - 2
        barra = "#e5c07b" if tail_think else TEAL_HEX           # 💭 raciocínio = âmbar · resposta = verde
        txtcor = "#8a7a52 bg:#15181d" if tail_think else "#7a808c bg:#15181d"
        for ln in cauda.split("\n")[-STREAM_MAX:]:
            linhas.append((barra, "▌"))
            linhas.append((txtcor, (" 💭" if tail_think else " ") + (ln[:lim]).ljust(lim) + "\n"))
    linhas.append((BORDA, "\n╭─ mensagem " + "─" * (w - 12) + "╮\n"))
    linhas += [(BORDA, "│ "), (f"bold {AZUL}", "❯ ")]
    return linhas

def _toolbar() -> StyleAndTextTuples:
    w = _larg()
    status = estado.device_status or ("online" if estado.device_online else "offline")
    dot = {"online": "#2da84f", "reconectando": "#e5c07b", "offline": "#e05a5a"}.get(status, "#e05a5a")
    pct = int(100 * ctx_usado / ctx_total) if ctx_total else 0
    ctx = f" · ctx {ctx_usado}/{ctx_total} ({pct}%)" if ctx_total else ""   # Fase 1: escondido até o backend mandar 'contexto'
    out = f" · ↑{tok_count} · {(time.monotonic() - turno_t0):.0f}s" if (respondendo and turno_t0) else ""
    modelo = (ctx_model or "—").split("/")[-1][:24]
    sid = (session_id or "nova")[:8]
    th = {"off": "💭off", "full": "💭full", "colap": "💭colap"}.get(think_mode, "💭off")
    txt = f" {status} · sessão {sid}{ctx}{out} · {th} · {modelo} "
    fill = max(1, w - len(txt) - 6)
    return [(BORDA, "╰─"), (dot, "●"), (DIM, txt), (BORDA, "─" * fill + "╯")]

def _ponto_flush(buf: str) -> int:
    """Último '\\n\\n' fora de cerca ``` aberta (não corta bloco de código). -1 se não há."""
    idx = buf.rfind("\n\n")
    while idx != -1:
        if buf.count("```", 0, idx) % 2 == 0:
            return idx
        idx = buf.rfind("\n\n", 0, idx)
    return -1

def _tail_parcial(s: str, tag: str) -> int:
    """Nº de chars finais de s que podem ser PREFIXO de tag (carrega p/ o próximo chunk — tag partida)."""
    for k in range(min(len(tag) - 1, len(s)), 0, -1):
        if s.endswith(tag[:k]):
            return k
    return 0

class _SepThink:
    """Separa <think>…</think> (raciocínio) do resto (resposta), tolerando tags partidas entre deltas."""
    def __init__(self) -> None:
        self.modo = "reply"       # "reply" | "think"
        self.pend = ""
    def feed(self, chunk: str) -> list[tuple[str, str]]:
        segs: list[tuple[str, str]] = []
        s = self.pend + chunk; self.pend = ""
        while s:
            if self.modo == "reply":
                i = s.find("<think>")
                if i == -1:
                    k = _tail_parcial(s, "<think>")
                    if k: self.pend = s[-k:]; s = s[:-k]
                    if s: segs.append(("reply", s))
                    break
                if i: segs.append(("reply", s[:i]))
                s = s[i + 7:]; self.modo = "think"
            else:
                j = s.find("</think>")
                if j == -1:
                    k = _tail_parcial(s, "</think>")
                    if k: self.pend = s[-k:]; s = s[:-k]
                    if s: segs.append(("think", s))
                    break
                if j: segs.append(("think", s[:j]))
                s = s[j + 8:]; self.modo = "reply"
        return segs

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

def _commit_pensamento(texto: str, W: int) -> None:
    """Raciocínio FULL (opção escolhida): caixa com borda âmbar + texto dim — distinta da resposta (verde)."""
    inner = W - 6
    _p(f"{_AMBAR}  ┌─ 💭 raciocínio " + "─" * max(0, W - 20) + "┐" + R + "\n")
    for ln in _wrap(texto, inner):
        _p(f"{_AMBAR}  │{R} {DIM_A}{ln}{R}" + " " * max(0, inner - len(ln)) + f" {_AMBAR}│{R}" + "\n")
    _p(f"{_AMBAR}  └" + "─" * max(0, W - 4) + "┘" + R + "\n")

def _commit_colap(texto: str, toks: int, secs: float, W: int) -> None:
    """Raciocínio COLAPSADO: só o resumo (linhas · tokens · tempo) — esconde o texto."""
    nlin = len([l for l in texto.strip().split("\n") if l.strip()])
    _p(f"  {_AMBAR}💭 raciocínio{R} {DIM_A}· {nlin} linhas · {toks} tokens · {secs:.1f}s ▸{R}\n")

def _fecha_raciocinio(texto: str, toks: int, t0: float, W: int) -> None:
    """Fixa o raciocínio no scrollback conforme o modo: full=caixa, colap=resumo."""
    secs = (time.monotonic() - t0) if t0 else 0.0
    if think_mode == "colap":
        _commit_colap(texto, toks, secs, W)
    else:
        _commit_pensamento(texto, W)

async def _responder(msg: str):
    """Consome o stream do backend (chat_stream): session_id + deltas de texto + erro.
    (Fase 1: checklist/eventos entram na Fase 2.)"""
    global respondendo, session_id, pending_image, pending_name, stream_tail, tail_think, tok_count, ultima_resposta, aguardando, pensando, think_t0, turno_t0
    respondendo = True; aguardando = True                            # aguardando = TTFT (mostra "processando…")
    tok_count = 0; full = []; erro = None                            # contador total + reply + erro
    think_toks = 0; think_t0 = 0.0; think_secs = 0.0; pensando = False
    turno_t0 = time.monotonic()
    img = pending_image; pending_image = None                        # consome o anexo (1 vez)
    nome = pending_name; pending_name = None
    W = _larg()
    _p("\n" + _titulo("🫵 você", W, BAR_AZUL, HBG_USER, NM_USER) + "\n" + _pad_top(W) + "\n")
    tag = f"📎 [imagem anexada] {nome}\n" if img else ""             # indicador claro (sem miniatura)
    _p(_corpo_md(tag + msg, W, BAR_AZUL) + "\n")
    _p("\n" + _titulo(f"{BOT} brazaia", W, BAR_TEAL, HBG_BOT, NM_BOT) + "\n")
    buf = ""; topo_feito = False
    sep = _SepThink(); pensamento = ""; pensou = False               # separa <think> (raciocínio) da resposta
    try:
        async for ev in chat_stream(msg, session_id, cfg, image=img, think=(think_mode != "off")):
            if "session_id" in ev:
                session_id = ev["session_id"]                        # lembra a sessão
            elif "delta" in ev:
                tok_count += 1; aguardando = False                   # 1º token chegou → tira o "processando…"
                for modo, txt in sep.feed(ev["delta"]):              # 'think' = raciocínio · 'reply' = resposta
                    if modo == "think":
                        pensamento += txt; think_toks += 1
                        if not think_t0: think_t0 = time.monotonic()
                        if think_mode == "full":
                            stream_tail = pensamento; tail_think = True   # raciocínio digitando (âmbar)
                        else:
                            pensando = True                          # colap: só "pensando…"
                    else:
                        if pensamento and not pensou:                # fecha o raciocínio 1x (full=caixa · colap=resumo)
                            think_secs = (time.monotonic() - think_t0) if think_t0 else 0.0
                            _fecha_raciocinio(pensamento, think_toks, think_t0, W)
                            pensou = True; pensando = False; stream_tail = ""; tail_think = False
                        if not topo_feito:
                            _p(_pad_top(W) + "\n"); topo_feito = True
                        buf += txt; full.append(txt)                 # resposta "real"
                        p = _ponto_flush(buf)                        # solta bloco pronto (fora de cerca)
                        if p == -1 and len(buf) > 2500 and buf.count("```") % 2 == 0:
                            p = len(buf)                             # force-flush: bloco gigante sem \n\n
                        if p != -1:
                            pronto, buf = buf[:p], buf[p + 2:]
                            _p(_corpo_md(pronto, W, BAR_TEAL) + "\n")
                        stream_tail = buf; tail_think = False        # rabo = o que falta → DIGITA no prompt
            elif ev.get("success") is False or "error" in ev or "code" in ev:   # ERRO do servidor (não ficar no escuro)
                erro = str(ev.get("message") or ev.get("error") or ev)[:200]
                m = f" ⚠ erro do servidor: {erro}"
                _p(_corpo(f" \033[1;38;2;255;90;90m{m[1:]}", cell_len(m), W, None) + "\n")
        if pensamento and not pensou:                                # raciocínio sem resposta depois → fixa mesmo assim
            think_secs = (time.monotonic() - think_t0) if think_t0 else 0.0
            _fecha_raciocinio(pensamento, think_toks, think_t0, W)
        pensando = False; stream_tail = ""; tail_think = False        # some o rabo…
        if buf.strip():
            _p(_corpo_md(buf, W, BAR_TEAL) + "\n")                    # …e vira o Markdown final
        total = time.monotonic() - turno_t0
        resp_toks = tok_count - think_toks
        rzn = "ERRO" if erro else "stop"
        th = f" · 💭 {think_toks}tok/{think_secs:.1f}s" if think_toks else ""
        info = f" · fim · {resp_toks} tok · {total:.1f}s{th} · {rzn}"
        _p(_corpo(f" {DIM_A}{info[1:]}", cell_len(info), W, None) + "\n")
    except Exception as e:
        pensando = False; stream_tail = ""; tail_think = False
        _p(_corpo(f" \033[38;2;255;90;90m⚠ falha no stream: {e}",
                  cell_len(f" ⚠ falha no stream: {e}"), W, None) + "\n")
    ultima_resposta = "".join(full)                                  # guarda p/ /copiar
    _p("\n")
    respondendo = False; aguardando = False; pensando = False

async def _ticker():
    global frame
    while True:
        frame += 1
        if respondendo or stream_tail or gravando or voz_prep:       # redesenha SÓ com animação viva
            try: get_app().invalidate()                              # ocioso = sem redraw → seleção do terminal não some
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
    if gravando or voz_prep or respondendo:
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
    global gravando, _grav
    if not gravando or _grav is None:
        return
    gravando = False; app.invalidate()
    try:
        audio = await _grav.parar()
        texto = (await _transcrever(audio)).strip()
    except Exception as e:
        _grav = None; _p(f"{DIM_A}   ⚠ voz: {e}{R}\n"); app.invalidate(); return
    _grav = None
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

class _Comp(Completer):
    """Autocomplete dos slash-commands."""
    CMDS = ["/voz", "/think", "/ajuda", "/sair"] if _IS_TERMUX else ["/voz", "/anexo", "/think", "/ajuda", "/sair"]
    def get_completions(self, document, complete_event):
        txt = document.text_before_cursor
        if not txt.startswith("/"):
            return
        partes = txt.split(" ")
        for c in self.CMDS:                                          # comandos
            if c.startswith(partes[0]):
                yield Completion(c, start_position=-len(partes[0]))

def _dispatch(msg: str, app) -> None:
    global session_id, think_mode
    partes = msg.split()
    cmd = partes[0]
    if cmd in ("/sair", "sair"):
        app.exit()
    elif cmd in ("/anexo", "/img"):
        if _IS_TERMUX:
            _p(f"{DIM_A}   /anexo não disponível no Termux (sem zenity/clipboard){R}\n")
        else:
            asyncio.create_task(_anexar())
    elif cmd == "/voz":
        asyncio.create_task(_iniciar_voz(app))
    elif cmd == "/think":
        modos = ["off", "full", "colap"]
        if len(partes) > 1 and partes[1] in modos:
            think_mode = partes[1]
        else:
            think_mode = modos[(modos.index(think_mode) + 1) % 3]    # cicla off → full → colap
        desc = {"off": "desligado", "full": "completo (caixa)", "colap": "colapsado (só resumo)"}[think_mode]
        _p(f"{VERDE_A}   💭 thinking: {think_mode} — {desc}{R}\n")
    elif cmd in ("/sessoes", "/sessao"):               # Fase 3: backend de sessões (/chat/sessions) ainda não existe
        _p(f"{DIM_A}   sessões chegam na próxima fase (o backend ainda não tem /chat/sessions){R}\n")
    elif cmd in ("/ajuda", "/help"):
        extra = "" if _IS_TERMUX else " · /anexo · Ctrl+V cola imagem"
        _p(f"{DIM_A}   comandos: /voz (voz→texto) · /think [off|full|colap] (cicla se sem arg){extra} · /sair{R}\n")
    else:
        _p(f"{DIM_A}   comando desconhecido: {cmd} (tente /ajuda){R}\n")

async def main() -> None:
    kb = KeyBindings()
    @kb.add("c-c")
    @kb.add("c-d")
    def _(e): e.app.exit()
    @kb.add("c-v")                                              # Ctrl+V = cola imagem do clipboard (ou texto)
    def _(e): asyncio.create_task(_colar(e.app))
    @kb.add("enter")
    def _(e):                                                   # Enter = MANDA a mensagem (não fecha o prompt)
        if gravando or voz_prep:                               # Enter durante /voz = PARA a gravação (NUNCA envia)
            if gravando:
                asyncio.create_task(_parar_voz(e.app))
            return
        global pending_image, pending_name
        msg = e.app.current_buffer.text.strip()
        e.app.current_buffer.text = ""
        if not msg or respondendo:                             # ignora vazio / enquanto responde
            return
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
        _p(f"{DIM_A}   digite e Enter · /voz{'' if _IS_TERMUX else ' · /anexo · Ctrl+V cola imagem'} · /sair{R}\n")
        asyncio.create_task(_ticker())
        import companion.connect as _dev                        # status vai pro FOOTER, sem spam no topo
        _dev.log = lambda *a, **k: None                          # silencia o log do connect (ele seta estado.device_status)
        asyncio.create_task(conectar(cfg))                      # tools de device REAIS (reconecta sozinho)
        with patch_stdout():
            try:
                await session.prompt_async(_prompt_msg, bottom_toolbar=_toolbar)   # sem refresh_interval: redraw só via _ticker quando há animação (senão a seleção do terminal some)
            except (EOFError, KeyboardInterrupt):
                pass
    finally:
        _osc_off()                                              # restaura o terminal

if __name__ == "__main__":
    asyncio.run(main())
