"""companion/ui/hud.py — o PAINEL do modo live (voz ao vivo): orb/radar, esfera com chama, chuva, os 5 estados.

Visual promovido do protótipo proto_voz_hud.py (C:\\Users\\dev\\workspace\\iobraza) SEM mudar o desenho. Stdlib puro
(braille + truecolor) → roda em Linux, Windows e Termux. Quem ALIMENTA o painel é o companion/live.py
(eventos do /ws/voice); aqui só tem desenho + o loop de render.

Demo (simulação, sem server):  python -m companion.ui.hud      # 1-5 estados · espaço pausa · q sai
"""
import sys, os, time, math, random, asyncio

# ── terminal CROSS-PLATFORM (Linux/Termux: termios · Windows: msvcrt + VT ANSI) ──
# sys.platform (não os.name) → o pyright entende o ramo de cada SO. Saída no stdout REAL: dentro do CLI o
# sys.stdout é o proxy do patch_stdout, que mandaria o quadro pro scrollback.
_OUT = sys.__stdout__ or sys.stdout
if sys.platform == "win32":
    import msvcrt, ctypes
    def _enable_vt():
        try:
            k = ctypes.windll.kernel32; h = k.GetStdHandle(-11)          # STD_OUTPUT_HANDLE
            m = ctypes.c_uint32(); k.GetConsoleMode(h, ctypes.byref(m))
            k.SetConsoleMode(h, m.value | 0x0004)                        # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception: pass
else:
    import select, termios, tty

def _term_enter():
    """Entra em alt-screen + esconde cursor + modo raw. Devolve estado p/ restaurar."""
    st = None
    if sys.platform == "win32": _enable_vt()
    else:
        fd = sys.stdin.fileno(); st = (fd, termios.tcgetattr(fd)); tty.setcbreak(fd)
    _OUT.write("\033[?1049h\033[?25l\033[2J"); _OUT.flush()
    return st

def _term_exit(st):
    _OUT.write("\033[0m\033[?25h\033[?1049l"); _OUT.flush()
    if sys.platform != "win32" and st is not None: termios.tcsetattr(st[0], termios.TCSADRAIN, st[1])

def _poll_key():
    """Lê 1 tecla sem bloquear (None se nada). Windows: msvcrt · Unix: select."""
    if sys.platform == "win32":
        try:
            if msvcrt.kbhit(): return msvcrt.getwch()
        except Exception: pass
        return None
    fd=sys.stdin.fileno()                                 # os.read CRU: o sys.stdin bufferizado engolia o resto
    if not select.select([fd], [], [], 0)[0]: return None  # das sequências (\x1b[A) e a seta virava "Esc sozinho"
    return os.read(fd, 64).decode("utf-8", errors="ignore") or None

ESTADOS = ["aguardando","detectando","captando","pensando","falando"]
ROTULO  = {"aguardando":"STANDBY","detectando":"DETECTANDO","captando":"OUVINDO",
           "pensando":"PROCESSANDO","falando":"RESPONDENDO"}
COR_EST = {"aguardando":(64,150,200),"detectando":(70,214,255),"captando":(80,255,180),
           "pensando":(255,197,49),"falando":(120,180,255)}
DUR={"aguardando":2.4,"detectando":2.0,"captando":3.6,"pensando":2.6,"falando":3.6}
CYAN=(70,200,255); CYAN_DIM=(24,90,120); BRANCO=(200,235,255); GRID=(18,54,74)

def clamp(v,a=0.0,b=1.0): return a if v<a else b if v>b else v
def scale(c,k): return (int(clamp(c[0]*k,0,255)),int(clamp(c[1]*k,0,255)),int(clamp(c[2]*k,0,255)))
def mix(a,b,t): return (int(a[0]+(b[0]-a[0])*t),int(a[1]+(b[1]-a[1])*t),int(a[2]+(b[2]-a[2])*t))

def nivel_sim(estado,t):
    if estado=="captando":
        fala=max(0,math.sin(t*7.3)+0.35*math.sin(t*13.7)+0.2*math.sin(t*23.1))
        return clamp(0.22+0.35*(0.5+0.5*math.sin(t*2.1))+0.4*fala)
    if estado=="falando":
        env=max(0,math.sin(t*3.0))*max(0,math.sin(t*1.3+0.6)); return clamp(0.18+0.7*env**0.7+0.08*math.sin(t*11))
    if estado=="detectando": return 0.16+0.08*math.sin(t*4.0)
    if estado=="pensando":   return 0.30+0.14*math.sin(t*2.4)
    return 0.06+0.03*math.sin(t*1.4)

POOL="ABCDEF0123456789<>*#%@/\\|=+ｱｲｳｴｷ"
VERDE_RAIN=(20,120,55)
def decode(alvo, frac):                                  # efeito brute-force: resolve a string aos poucos
    n=len(alvo); k=int(n*clamp(frac))
    return alvo[:k]+"".join(random.choice(POOL) for _ in range(max(0,n-k)))

class Rain:
    """Chuva de letras Matrix (fundo discreto — verde escuro, pro HUD azul ficar na frente)."""
    def __init__(self,w,h):
        self.w,self.h=w,h
        self.col=[{"y":random.uniform(0,h),"sp":0.5+random.random()*1.0,"ln":4+int(random.random()*9)} for _ in range(w)]
    def draw(self,tela,dt,spd=1.0):
        for x,c in enumerate(self.col):
            for k in range(c["ln"]):
                yy=int(c["y"])-k
                if 0<=yy<self.h and tela.co[yy][x] is None:
                    a=(1-k/c["ln"])
                    col=(150,235,170) if k==0 else scale(VERDE_RAIN,a)
                    tela.put(x,yy,random.choice(POOL),col)
            c["y"]+=c["sp"]*spd*dt*12
            if c["y"]-c["ln"]>self.h: c["y"]=-random.random()*6; c["sp"]=0.5+random.random()*1.0

def desenha_bruteforce(tela,x,y,w,estado,t):
    """Painel 'DECRYPT' estilo brute-force: linhas de hex embaralhando; ao PROCESSAR, resolvem rápido."""
    h=6; painel(tela,x,y,w,h,"DECRYPT",scale(CYAN,0.8))
    ativo = estado=="pensando"
    for i in range(h-2):
        alvo=f"0x{(0xA17F2C ^ (i*0x9E37)) & 0xFFFFFF:06X}::{['KEY','SIG','MAC','TOK'][i%4]}"
        frac = (0.15 + (t*1.6+i*0.4) % 1.4) if ativo else 0.12+0.05*math.sin(t*2+i)
        s=decode(alvo, clamp(frac))
        ok = ativo and frac>=0.99
        col = scale(COR_EST[estado],1.2) if ok else (scale(CYAN,0.8) if ativo else CYAN_DIM)
        tela.texto(x+2,y+1+i,s[:w-4],col)

# ───────────── buffer de células ─────────────
def _largo(c: str) -> bool:
    """Ocupa 2 colunas? (east-asian wide/fullwidth + emojis). Os katakana meia-largura da chuva (ｱｲｳ) são 1."""
    import unicodedata
    return unicodedata.east_asian_width(c) in ("W", "F") or 0x1F300 <= ord(c) <= 0x1FAFF

class Tela:
    def __init__(self,w,h): self.w,self.h=w,h; self.ch=[[" "]*w for _ in range(h)]; self.co=[[None]*w for _ in range(h)]
    def put(self,x,y,ch,cor):
        if 0<=x<self.w and 0<=y<self.h: self.ch[y][x]=ch; self.co[y][x]=cor
    def texto(self,x,y,s,cor):
        """Caractere LARGO (emoji 🫵🤖, CJK) ocupa 2 colunas no terminal: a célula seguinte vira continuação ("")
        e o frame não escreve nada nela. Sem isso a linha passava da largura, quebrava e o quadro todo descia."""
        for c in s:
            if x >= self.w: break
            if _largo(c):
                if x+1 >= self.w: break                       # não cabe inteiro na borda → corta
                self.put(x,y,c,cor); self.put(x+1,y,"",cor); x+=2
            else:
                self.put(x,y,c,cor); x+=1
    def frame(self):
        out=["\033[H"]
        for y in range(self.h):
            last=None; buf=[]
            for x in range(self.w):
                c=self.co[y][x]
                if c is None:
                    if last is not None: buf.append("\033[0m"); last=None
                    buf.append(" ")
                else:
                    if c!=last: buf.append(f"\033[38;2;{c[0]};{c[1]};{c[2]}m"); last=c
                    buf.append(self.ch[y][x])                     # continuação de largo = "" (não escreve)
            if last is not None: buf.append("\033[0m")
            out.append("".join(buf));
            if y<self.h-1: out.append("\n")
        return "".join(out)

# ───────────── canvas BRAILLE (2×4 subpixels/célula) ─────────────
_DOT=[[0x01,0x08],[0x02,0x10],[0x04,0x20],[0x40,0x80]]
class Braille:
    def __init__(self,w,h): self.w,self.h=w,h; self.b=[[0]*w for _ in range(h)]; self.c: list[list[tuple | None]]=[[None]*w for _ in range(h)]
    def set(self,x,y,cor):
        cx,cy=int(x)//2,int(y)//4
        if 0<=cx<self.w and 0<=cy<self.h:
            self.b[cy][cx]|=_DOT[int(y)%4][int(x)%2]
            atual=self.c[cy][cx]
            self.c[cy][cx]=cor if atual is None else (cor if sum(cor)>=sum(atual) else atual)
    def arco(self,cx,cy,r,cor,a0=0,a1=360,passo=None):
        n=passo or max(8,int(r*2))
        for i in range(n+1):
            a=math.radians(a0+(a1-a0)*i/n); self.set(cx+math.cos(a)*r, cy+math.sin(a)*r*1.0, cor)
    def blit(self,tela):
        for cy in range(self.h):
            for cx in range(self.w):
                if self.b[cy][cx]:                       # desenha POR CIMA da chuva (gaps mostram a chuva)
                    tela.put(cx,cy,chr(0x2800+self.b[cy][cx]),self.c[cy][cx])

# ───────────── orb / radar ─────────────
def desenha_orb(br, cx, cy, R, estado, nivel, t):
    acc=COR_EST[estado]
    # anéis concêntricos (grade)
    for f,al in ((1.0,0.9),(0.72,0.5),(0.46,0.35)):
        br.arco(cx,cy,R*f, scale(GRID,1.0), passo=int(R*2.2))
    # anel externo tracejado (ticks)
    for a in range(0,360,6):
        r=math.radians(a); rr=R*1.06
        br.set(cx+math.cos(r)*rr, cy+math.sin(r)*rr*1.0, scale(CYAN_DIM,1.2))
    # anel de nível (preenche conforme o volume) — brilha
    fim=360*clamp(0.05+nivel)
    br.arco(cx,cy,R*0.86, scale(acc,0.9+0.1), a0=-90, a1=-90+fim, passo=int(R*2.4))
    # sweep do radar (linha girando + rastro)
    base=t*90 if estado in("captando","detectando") else t*40
    for k in range(0,26):
        a=math.radians(base-k*2.2); al=1-k/26
        br.set(cx+math.cos(a)*R*0.82, cy+math.sin(a)*R*0.82, scale(acc,al))
        for rr in range(2,int(R*0.82),2):
            if random.random()<0.5*al: br.set(cx+math.cos(a)*rr, cy+math.sin(a)*rr, scale(acc,al*0.5))
    # núcleo pulsante (disco) — tamanho pelo nível
    cr=R*(0.10+0.22*nivel)
    yy=-int(cr*1.0)
    while yy<=int(cr*1.0):
        xx=-int(cr*2)
        while xx<=int(cr*2):
            if (xx/ (cr*2+0.01))**2 + (yy/(cr+0.01))**2 <=1:
                d=math.hypot(xx/2,yy); br.set(cx+xx, cy+yy, mix(BRANCO,acc,clamp(d/cr)))
            xx+=1
        yy+=1
    # partículas orbitando
    for i in range(7):
        a=math.radians(t*(30+i*8) + i*51); rr=R*(0.55+0.12*math.sin(t*2+i))
        br.set(cx+math.cos(a)*rr, cy+math.sin(a)*rr, scale(BRANCO,0.9))

# ───────────── painéis (chrome do HUD) ─────────────
def painel(tela,x,y,w,h,titulo,cor):
    for j in range(h):                                   # limpa o interior (a chuva não vaza dentro)
        for i in range(w): tela.put(x+i,y+j," ",None)
    tela.put(x,y,"╭",cor); tela.put(x+w-1,y,"╮",cor); tela.put(x,y+h-1,"╰",cor); tela.put(x+w-1,y+h-1,"╯",cor)
    for i in range(1,w-1): tela.put(x+i,y,"─",cor); tela.put(x+i,y+h-1,"─",cor)
    for j in range(1,h-1): tela.put(x,y+j,"│",cor); tela.put(x+w-1,y+j,"│",cor)
    if titulo: tela.texto(x+2,y,f" {titulo} ",scale(cor,1.3))

def desenha_hud(tela, estado, nivel, t, W, H, reveal=1.0, log="", texto="", reply="", info=None):
    acc=COR_EST[estado]; c=scale(acc,1.2)
    info=info or {}
    if W < 64:                                           # tela ESTREITA (celular em pé): sem os painéis laterais
        _hud_compacto(tela, estado, nivel, W, H, reveal, log, texto, reply, info, acc, c); return
    # cabeçalho
    tela.texto(2,0,"BRAZA//A · ASSISTENTE DE VOZ", scale(CYAN,1.1))
    rel=time.strftime("%H:%M:%S")
    tela.texto(W-len(rel)-2,0,rel,CYAN_DIM)
    # painel esquerdo — status (rótulo resolve via brute-force ao trocar de estado)
    painel(tela,2,2,26,9,"STATUS",scale(CYAN,0.8))
    tela.texto(4,4,"estado", CYAN_DIM); tela.texto(4,5,f"› {decode(ROTULO[estado],reveal)}", c)
    desenha_bruteforce(tela,2,12,26,estado,t)            # painel DECRYPT (brute-force)
    tela.texto(4,7,"sinal", CYAN_DIM)
    bw=18; fill=int(nivel*bw)
    tela.put(4,8,"[",CYAN_DIM)
    for i in range(bw): tela.put(5+i,8,"▮" if i<fill else "·", acc if i<fill else GRID)
    tela.put(5+bw,8,"]",CYAN_DIM)
    # painel direito — telemetria (device REAL)
    painel(tela,W-28,2,26,9,"TELEMETRIA",scale(CYAN,0.8))
    try:
        from companion.state import estado as _est
        dev=_est.device_status or "—"
    except Exception:
        dev="—"
    dev_cor=(80,255,180) if dev=="online" else ((255,197,49) if dev=="reconectando" else (224,90,90))
    linhas=[(f"device {info.get('device','—')}"[:16], dev, dev_cor),("modelo",str(info.get("modelo","—"))[:12], c),
            ("sessão",str(info.get("sessao","nova"))[:8], c),("áudio",str(info.get("audio","—"))[:10], c)]
    for i,(k,v,vc) in enumerate(linhas):
        tela.texto(W-26,4+i,k,CYAN_DIM); tela.texto(W-6-len(v),4+i,v,vc)
    # rodapé — status + CAIXA da conversa (sua última fala + a resposta dela) + dica
    def _corta(s, w): return (s[:w-1]+"…") if len(s)>w else s
    hc = max(4, min(9, H // 4))                                 # altura da caixa
    if log: tela.texto(2, H-2-hc, _corta(f"▸ {log}", W-4), c)
    if texto or reply:
        caixa_conversa(tela, 2, H-1-hc, W-4, hc, texto, reply, c)
    tela.texto(2, H-1, info.get("dica","q / Esc volta pro chat"), CYAN_DIM)

def _quebra(texto: str, largura: int) -> list[str]:
    """Quebra por PALAVRA respeitando a largura em colunas (emoji/CJK = 2)."""
    linhas: list[str] = []
    for para in (texto or "").split("\n"):
        atual, larg = "", 0
        for palavra in para.split(" "):
            lp = sum(2 if _largo(ch) else 1 for ch in palavra)
            if atual and larg + 1 + lp > largura:
                linhas.append(atual); atual, larg = "", 0
            while lp > largura:                                  # palavra maior que a linha: corta
                linhas.append(palavra[:largura]); palavra = palavra[largura:]
                lp = sum(2 if _largo(ch) else 1 for ch in palavra)
            atual, larg = (f"{atual} {palavra}", larg + 1 + lp) if atual else (palavra, lp)
        linhas.append(atual)
    return linhas

def caixa_conversa(tela, x, y, w, h, texto, reply, cor):
    """Caixa "CONVERSA": a SUA última fala e a resposta dele a ELA (nada de turnos anteriores misturados).
    Quebra por palavra; se não couber, mostra o FIM (a resposta chegando), mantendo a 1ª linha da sua fala."""
    painel(tela, x, y, w, h, "CONVERSA", scale(CYAN, 0.8))
    lw, alto = w - 4, h - 2
    voce = _quebra(f"🫵 {texto}", lw) if texto else []
    braza = _quebra(f"🤖 {reply}", lw) if reply else []
    if len(voce) + len(braza) > alto:                           # não cabe: SUA fala inteira (até 3 linhas) + o FIM da resposta
        voce = voce[:3] if len(voce) <= 3 else voce[:2] + ["…"]
        sobra = alto - len(voce) - (1 if braza else 0)
        braza = (["…"] + braza[-sobra:]) if braza and sobra > 0 else braza[-max(0, alto - len(voce)):]
    corpo = [(l, CYAN_DIM) for l in voce] + [(l, scale(CYAN, 1.05)) for l in braza]
    corpo = corpo[-alto:]
    for i, (linha, c) in enumerate(corpo):
        tela.texto(x + 2, y + 1 + i, linha, c)

def _hud_compacto(tela, estado, nivel, W, H, reveal, log, texto, reply, info, acc, c):
    """Celular em pé: cabeçalho + estado/sinal numa linha + rodapé com quebra (o texto não cabe numa linha só)."""
    rel=time.strftime("%H:%M")
    tela.texto(1,0,"BRAZA//A", scale(CYAN,1.1)); tela.texto(W-len(rel)-1,0,rel,CYAN_DIM)
    tela.texto(1,1,f"› {decode(ROTULO[estado],reveal)}", c)
    bw=max(6,W-18); fill=int(nivel*bw); x0=W-bw-2
    tela.put(x0-1,1,"[",CYAN_DIM)
    for i in range(bw): tela.put(x0+i,1,"▮" if i<fill else "·", acc if i<fill else GRID)
    tela.put(x0+bw,1,"]",CYAN_DIM)
    lw=W-2
    for i in range(W): tela.put(i,H-1," ",(0,0,0))
    tela.texto(1, H-1, info.get("dica","q volta pro chat")[:lw], CYAN_DIM)
    hc = max(5, min(14, H // 3))                                # caixa da conversa: ~1/3 da tela em pé
    if texto or reply:
        caixa_conversa(tela, 0, H-1-hc, W, hc, texto, reply, c)
    if log:
        for i in range(W): tela.put(i,H-2-hc," ",(0,0,0))
        tela.texto(1, H-2-hc, (f"▸ {log}")[:lw], c)

# ───────────── chama Brasil (centro, ao FALAR) ─────────────
FLAME_CH=".:!*^vw/|"
def cor_chama_br(f):                                     # base amarela -> meio verde -> topo azul (logo Brasil)
    return mix((255,223,0),(0,168,60),f*2) if f<0.5 else mix((0,168,60),(0,96,230),(f-0.5)*2)

def desenha_chama_centro(tela, cxc, cyc, rbx, rby, niv, t):
    """Fogo saindo da COROA da bolinha central, feito CABELO: base segue a curva do topo do orb,
    em leque cobrindo o topo, tongues que afinam subindo. Dança com o áudio do agente (TTS)."""
    peak = max(5, int(rby*4 + rbx*0.7))                  # altura das mechas
    boost = 0.7 + 0.9*niv
    for xx in range(cxc-rbx, cxc+rbx+1):
        nx=(xx-cxc)/rbx
        if abs(nx) > 0.98: continue
        base_y = int(cyc - rby*math.sqrt(max(0.0, 1-nx*nx)))   # topo da bolinha naquela coluna
        env = (1-nx*nx)**0.6                             # cobre quase todo o topo (cabelo cheio), afina só nas pontas
        flick = 0.55 + 0.45*math.sin(xx*0.8 + t*6) + 0.30*math.sin(xx*1.9 - t*9 + nx*3)
        H = int(peak * env * boost * clamp(0.4+0.7*flick))
        for k in range(H):
            yy = base_y - 1 - k; f = k/max(1,H)
            if abs(nx) > (1-f)*0.95 and random.random() < 0.55: continue   # afina a mecha subindo
            if random.random() < 0.13*f: continue        # ponta "lambendo"
            bri = 0.6 + 0.4*math.sin(xx + t*6 - k*0.5)
            tela.put(xx, yy, random.choice(FLAME_CH), scale(cor_chama_br(f), clamp(bri)))

def desenha_esfera(br, cx, cy, R, cor, niv=0.0, t=0.0):
    """Esfera azul PIXELADA e PARADA (lattice 3D + rim) com rosto: 2 olhos curvos + boca equalizador."""
    y=-int(R)
    while y<=R:                                           # preenchimento em grade (pixelado)
        x=-int(R)
        while x<=R:
            d2=(x*x+y*y)/(R*R)
            if d2<=1.0:
                nz=math.sqrt(1-d2)
                L=clamp(0.22 + 0.75*(nz*0.8 + (-x/R)*0.18 + (-y/R)*0.18))   # luz do alto-esquerda -> 3D
                br.set(cx+x, cy+y, scale(cor, L))
            x+=2
        y+=2
    br.arco(cx,cy,R, scale(cor,1.0), passo=int(R*3))      # rim brilhante
    olho=mix(cor,BRANCO,0.6)                              # OLHOS: menores e mais afastados (feito o robô)
    ew=R*0.19; eh=R*0.23
    cvx, cvy, cvr = ew*1.15, eh*1.15, 1.35                # círculo que esculpe a curva (fundo cheio, topo curvo)
    for lado in (-1,1):
        ox=int(lado*R*0.40); oy=-int(R*0.10)              # +afastados
        yy=-int(eh)
        while yy<=eh:
            xx=-int(ew)
            while xx<=ew:
                dentro = (xx/(ew+1))**2+(yy/(eh+1))**2 <= 1
                corte = ((xx - lado*ew*0.35)/cvx)**2 + ((yy - eh*cvr)/cvy)**2 <= 1
                if dentro and not corte: br.set(cx+ox+xx, cy+oy+yy, olho)
                xx+=1
            yy+=1
    boca=mix(cor,BRANCO,0.45)                              # BOCA = EQUALIZADOR: barras verticais dançando c/ o áudio
    nb=7; sp=max(3,int(R*0.14)); my=cy+int(R*0.34)
    for i in range(nb):
        bx=cx+int((i-(nb-1)/2)*sp)
        hb=R*(0.035 + 0.16*clamp(niv)*(0.62+0.38*abs(math.sin(t*7 + i*1.0))))   # menor e mais uniforme
        yy=-int(hb)
        while yy<=hb:
            for dx in (-1,0): br.set(bx+dx, my+yy, boca)
            yy+=1

# ───────────── compõe 1 quadro (demo e live usam o mesmo) ─────────────
def compor_frame(W,H,rain,estado,niv,t,reveal,dt, log="", texto="", reply="", info=None):
    tela=Tela(W,H); br=Braille(W,H)
    rain.draw(tela, dt, spd=1.4 if estado=="captando" else 1.0)
    R=min(W*0.7, H*0.52*2); cxc=W//2; cyc=int(H*0.52)
    if estado=="falando":                                # FALANDO: esfera azul pixelada PARADA + cabelo de fogo
        Re=R*0.62
        desenha_esfera(br, W, cyc*4, Re, CYAN, niv, t)
        br.blit(tela)
        rbx=max(6,int(Re/2)); rby=max(3,int(Re/4))
        desenha_chama_centro(tela, cxc, cyc, rbx, rby, niv, t)
    else:                                                # demais estados: radar/orb animado
        desenha_orb(br, W, cyc*4, R, estado, niv, t)
        br.blit(tela)
    desenha_hud(tela, estado, niv, t, W, H, reveal, log, texto, reply, info)
    return tela.frame()


# ───────────── estado compartilhado (live.py escreve · render_loop lê) ─────────────
class EstadoVoz:
    def __init__(self):
        self.estado="aguardando"; self.nivel=0.0; self.texto=""; self.reply=""
        self.log="iniciando…"; self.t_estado=time.monotonic(); self.quit=False; self.info={}
        self.teclas: list[str]=[]                        # teclas que não são de sair (ex.: Enter no live do celular)
    def set(self, estado, log=None):
        if estado!=self.estado: self.estado=estado; self.t_estado=time.monotonic()
        if log is not None: self.log=log

def rms(chunk: bytes) -> float:
    """Nível 0..1 de um PCM16 (anima o anel/equalizador). Stdlib (array) → sem numpy."""
    import array
    a=array.array("h"); a.frombytes(chunk[:len(chunk)//2*2])
    if not a: return 0.0
    return clamp(math.sqrt(sum(x*x for x in a)/len(a))/3000.0)

try:                                                     # no celular o VOLTAR do Android manda o mesmo \x1b do Esc:
    from companion.plataform import _IS_TERMUX as _CELULAR  # lá só o q fecha (senão o voltar derrubava o live)
except Exception:
    _CELULAR = False

def _tecla():
    """Teclas digitadas desde a última leitura, SEM as sequências de escape (setas, F1…: \x1b[A, \x1bOP…).
    Esc SOZINHO volta "\x1b". No Windows (msvcrt) as setas vêm como \xe0+letra, não \x1b — nada a filtrar."""
    k=_poll_key()
    if not k or not k.startswith("\x1b"): return k
    if k=="\x1b":
        time.sleep(0.02)                                  # sequência que chegou partida: o resto vem logo
        resto=_poll_key()
        if not resto: return "\x1b"
        k+=resto
    return None                                           # \x1b + algo = sequência (seta etc.) → ignora

async def render_loop(ev: EstadoVoz) -> None:
    """Desenha o painel a ~20 fps até ev.quit (ou q/Esc/Ctrl+C). Escreve no stdout REAL (sys.__stdout__):
    dentro do CLI o sys.stdout é o proxy do patch_stdout, que jogaria o quadro no scrollback."""
    out=_OUT
    st=_term_enter()
    rain=None; t0=time.monotonic(); last=t0; niv=0.0
    try:
        while not ev.quit:
            sz=os.get_terminal_size(); W,H=sz.columns,sz.lines
            if rain is None or rain.w!=W or rain.h!=H: rain=Rain(W,H)
            now=time.monotonic(); dt=min(0.06,now-last); last=now; t=now-t0
            k=_tecla() or ""
            if any(c in k for c in "qQ\x03") or (k=="\x1b" and not _CELULAR): ev.quit=True; break
            if k!="\x1b": ev.teclas.extend(k)
            niv += (ev.nivel-niv)*min(1.0,dt*8)           # suaviza o nível -> fluido
            reveal=clamp((now-ev.t_estado)/0.7)
            out.write(compor_frame(W,H,rain,ev.estado,niv,t,reveal,dt,
                                   log=ev.log, texto=ev.texto, reply=ev.reply, info=ev.info)); out.flush()
            await asyncio.sleep(1/20)
    finally:
        _term_exit(st)

# ───────────── demo (simulação, sem server) ─────────────
async def _demo() -> None:
    ev=EstadoVoz(); ev.info={"device":"demo","modelo":"—","sessao":"demo","audio":"simulado"}
    async def simula():
        ix=0; t0=time.monotonic()
        while not ev.quit:
            est=ESTADOS[ix]; ev.set(est, f"demo · {ROTULO[est].lower()}")
            fim=time.monotonic()+DUR[est]
            while time.monotonic()<fim and not ev.quit:
                ev.nivel=clamp(nivel_sim(est, time.monotonic()-t0)); await asyncio.sleep(0.05)
            ix=(ix+1)%len(ESTADOS)
    tarefa=asyncio.create_task(simula())
    try: await render_loop(ev)
    finally: tarefa.cancel()

if __name__=="__main__":
    try: asyncio.run(_demo())
    except KeyboardInterrupt: pass
