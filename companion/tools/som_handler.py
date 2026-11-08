"""Som no device: gravar o microfone, tocar um áudio (ou bipe/alarme) e mexer no volume — hoje só no Termux.

Gravação: termux-microphone-record grava em arquivo (1 por vez: -q encerra a anterior); o arquivo volta pro
servidor em base64 e vira um file_id. Se o Android bloquear o microfone (tela apagada, permissão), o arquivo
fica vazio/minúsculo e a tool DIZ isso em vez de devolver um áudio mudo.
"""
import asyncio
import base64
import math
import os
import struct
import time
import wave

from companion import DADOS
from companion._json import dumps, loads
from companion.plataform import _IS_TERMUX
from companion.runtime import runtime

PASTA = os.path.join(DADOS, "audio")
_CANAIS = {"musica": "music", "toque": "ring", "notificacao": "notification", "alarme": "alarm",
           "chamada": "call", "sistema": "system"}


async def _cmd(cmd: list[str], timeout: float = 20.0) -> tuple[int, str]:
    """Roda um comando e devolve (código, saída). (O _run_sync do plataform descarta a saída.)"""
    try:
        p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    except FileNotFoundError:
        return 127, f"comando não encontrado: {cmd[0]}"
    try:
        out, _ = await asyncio.wait_for(p.communicate(), timeout)
    except asyncio.TimeoutError:
        p.kill()
        return 124, "timeout"
    return p.returncode or 0, out.decode(errors="replace")


def _wav_bipes(arq: str, bipes: int, dur_s: float, freq: float, pausa_s: float) -> None:
    taxa = 22050
    quadros = bytearray()
    for _ in range(bipes):
        for i in range(int(taxa * dur_s)):
            env = min(1.0, i / 300, (int(taxa * dur_s) - i) / 300)          # sem estalo no começo/fim
            quadros += struct.pack("<h", int(14000 * env * math.sin(2 * math.pi * freq * i / taxa)))
        quadros += b"\0\0" * int(taxa * pausa_s)
    with wave.open(arq, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(taxa); w.writeframes(bytes(quadros))


ESTADO_GRAVACAO = os.path.join(DADOS, "audio", "gravando.json")
MAX_LIVRE_S = 1800            # gravação "até pedir pra parar": teto de 30 min (o servidor recusa mensagem > 16 MB)


def _entregar(arq: str, seg: int) -> str:
    tam = os.path.getsize(arq) if os.path.exists(arq) else 0
    if tam < 2000:                                    # ~0,1 s de AAC: o microfone não gravou de verdade
        return (f"[erro] o microfone não gravou ({tam} bytes em {seg} s) — o Android pode ter bloqueado "
                "(tela apagada ou permissão do Termux:API)")
    dados = open(arq, "rb").read()
    os.remove(arq)
    return dumps({"audio_b64": base64.b64encode(dados).decode(), "ext": ".aac", "segundos": seg, "bytes": tam})


def _gravacao_livre() -> dict | None:
    try:
        return loads(open(ESTADO_GRAVACAO).read())
    except (OSError, ValueError):
        return None


@runtime.register_tool("record_audio")
async def record_audio(args: dict) -> str:
    """acao: gravar (N s) · iniciar (sem tempo, até 'parar'; máx. 30 min) · parar (encerra e entrega) · status."""
    if not _IS_TERMUX:
        return "[erro] gravar áudio só está disponível no celular (Termux) por enquanto"
    acao = args.get("acao") or "gravar"
    os.makedirs(PASTA, exist_ok=True)
    livre = _gravacao_livre()
    if acao == "status":
        return (f"[ok] gravando desde {time.strftime('%H:%M:%S', time.localtime(livre['inicio']))} "
                f"({int(time.time() - livre['inicio'])} s)") if livre else "[ok] nenhuma gravação em andamento"
    if acao == "parar":
        if not livre:
            return "[erro] não há gravação em andamento pra parar"
        await _cmd(["termux-microphone-record", "-q"])
        await asyncio.sleep(1.0)                      # o arquivo fecha depois do -q
        os.remove(ESTADO_GRAVACAO)
        return _entregar(livre["arq"], int(time.time() - livre["inicio"]))
    if livre:                                         # gravar/iniciar com uma livre rodando: não atropela
        return (f"[erro] já há uma gravação em andamento desde "
                f"{time.strftime('%H:%M', time.localtime(livre['inicio']))} — pare ela antes")
    arq = os.path.join(PASTA, f"gravacao-{time.strftime('%Y%m%d-%H%M%S')}.aac")
    await _cmd(["termux-microphone-record", "-q"])                                # só 1 gravação por vez
    if acao == "iniciar":
        rc, out = await _cmd(["termux-microphone-record", "-e", "aac", "-b", "40", "-c", "1",
                              "-l", str(MAX_LIVRE_S), "-f", arq])
        if rc != 0:
            return f"[erro] não consegui começar a gravar: {out.strip()[:120]}"
        with open(ESTADO_GRAVACAO, "w") as f:
            f.write(dumps({"arq": arq, "inicio": time.time()}))
        return f"[ok] gravando desde {time.strftime('%H:%M:%S')} — até pedir pra parar (máximo 30 min)"
    seg = max(1, min(int(args.get("segundos") or 10), 300))
    rc, out = await _cmd(["termux-microphone-record", "-e", "aac", "-l", str(seg), "-f", arq])
    if rc != 0:
        return f"[erro] não consegui começar a gravar: {out.strip()[:120]}"
    await asyncio.sleep(seg + 1.5)
    await _cmd(["termux-microphone-record", "-q"])
    return _entregar(arq, seg)


@runtime.register_tool("play_audio")
async def play_audio(args: dict) -> str:
    if not _IS_TERMUX:
        return "[erro] tocar som só está disponível no celular (Termux) por enquanto"
    os.makedirs(PASTA, exist_ok=True)
    som = args.get("som")
    if args.get("audio_b64"):
        arq = os.path.join(PASTA, "tocar" + (args.get("ext") or ".mp3"))
        with open(arq, "wb") as f:
            f.write(base64.b64decode(args["audio_b64"]))
    elif som in ("bipe", "alarme"):
        arq = os.path.join(PASTA, f"{som}.wav")
        if not os.path.exists(arq):
            _wav_bipes(arq, *((3, 0.18, 880, 0.12) if som == "bipe" else (12, 0.35, 1320, 0.15)))
    else:
        return "[erro] nada pra tocar (mande um áudio ou som=bipe/alarme)"
    await _cmd(["termux-media-player", "stop"])
    rc, out = await _cmd(["termux-media-player", "play", arq])
    if rc != 0 or "error" in out.lower():
        return f"[erro] o player não tocou: {out.strip()[:120]}"
    return f"[ok] tocando {som or 'o áudio'} ({out.strip()[:60]})"


async def _ler_volumes() -> dict:
    rc, out = await _cmd(["termux-volume"])
    try:
        return {v["stream"]: v for v in loads(out)} if rc == 0 else {}
    except (ValueError, TypeError, KeyError):
        return {}


@runtime.register_tool("set_volume")
async def set_volume(args: dict) -> str:
    if not _IS_TERMUX:
        return "[erro] volume só está disponível no celular (Termux) por enquanto"
    canal = args.get("canal") or "musica"
    stream = _CANAIS.get(canal)
    if not stream:
        return f"[erro] canal '{canal}' não existe (use: {', '.join(_CANAIS)})"
    vols = await _ler_volumes()
    atual = vols.get(stream)
    if not atual:
        return "[erro] não consegui ler o volume (Termux:API respondeu?)"
    mx, agora = atual["max_volume"], atual["volume"]
    acao, nivel = args.get("acao") or "definir", args.get("nivel")
    passo = max(1, round(mx * 0.2))                   # aumentar/diminuir = ~20% por vez
    alvo = {"maximo": mx, "mudo": 0, "aumentar": agora + passo, "diminuir": agora - passo}.get(acao)
    if alvo is None:
        if nivel is None:
            return f"[ok] {canal}: {agora}/{mx} ({round(100 * agora / mx)}%)"
        alvo = round(mx * max(0, min(int(nivel), 100)) / 100)
    alvo = max(0, min(mx, alvo))
    await _cmd(["termux-volume", stream, str(alvo)])
    depois = (await _ler_volumes()).get(stream, {}).get("volume", alvo)
    return f"[ok] {canal}: {agora}/{mx} → {depois}/{mx} ({round(100 * depois / mx)}%)"
