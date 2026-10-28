import asyncio
from collections.abc import AsyncGenerator
import os, wave
from companion.plataform import _IS_TERMUX, _run_sync

SAMPLE_RATE = 16_000
TTS_SAMPLE_RATE = 24_000   # Kokoro (saída do TTS)
CHANNELS = 1
DTYPE = "int16"
_DIR = os.path.expanduser("~/brazaia")
MIC_DEVICE = os.getenv("MIC_DEVICE", "pulse")       # segue o mic padrão do sistema; ou "HyperX"/índice
_MIC_DEV = int(MIC_DEVICE) if MIC_DEVICE.isdigit() else MIC_DEVICE


async def capture_chunks(stop_event: asyncio.Event, chunks_ms: int = 30) -> AsyncGenerator[bytes , None]:
    import sounddevice as sd
    """Gera chunks de áudio do microfone como PCM int16."""
    frames_per_chunks = int(SAMPLE_RATE * chunks_ms / 1000)
    q: asyncio.Queue[bytes] = asyncio.Queue()
    loop = asyncio.get_running_loop()
    
    def callback(indata, frames, time, status):
        loop.call_soon_threadsafe(q.put_nowait, bytes(indata))
    
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE,
        callback=callback,
        blocksize=frames_per_chunks,
        device=_MIC_DEV,
    ):
        while not stop_event.is_set():
            chunk = await q.get()
            yield chunk


            
async def capturar_turno() -> bytes:
    """Grava UM turno do mic até o silêncio. Devolve PCM 16k mono. (desktop)"""
    
    if _IS_TERMUX:
        import uuid
        from datetime import datetime
        os.makedirs(_DIR, exist_ok=True)
        teto = int(os.getenv("TURNO_SEG", "0"))               # 0 = só Enter (sem teto); >0 = para no tempo OU no Enter
        aac = f"{_DIR}/turno-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.aac"   # nome ÚNICO (data+id) → nunca lê arquivo velho
        await _run_sync(["termux-microphone-record", "-q"])   # mata gravação PRESA de antes (Termux só grava 1 por vez)
        await asyncio.sleep(0.2)
        limite = str(teto) if teto > 0 else "300"             # -l do termux: o teto, ou 5min de segurança
        res = await _run_sync(["termux-microphone-record", "-f", aac, "-l", limite, "-e", "aac"])
        if res != "ok":                                       # ex.: "already recording", arg inválido, sem permissão
            raise RuntimeError(f"termux-microphone-record não iniciou: {res}")
        await asyncio.sleep(0.8)                               # warmup do mic — absorve a latência de início
        await _beep()                                         # sonzinho: "estou ouvindo"
        print("🎙  ouvindo — Enter pra enviar" + (f" (máx {teto}s)" if teto else "") + f"  (→ {aac})", flush=True)
        await _esperar_enter(teto)                            # para no Enter OU no teto (o que vier primeiro)
        await _run_sync(["termux-microphone-record", "-q"])   # para → finaliza o container AAC (header/moov)
        await asyncio.sleep(0.3)
        with open(aac, "rb") as f:
            data = f.read()
        if len(data) < 2000:                                  # quase nada gravado → mic/permissão
            raise RuntimeError(f"gravação vazia ({len(data)} bytes) — checa mic/permissão do Termux:API")
        return data
        
    
    from companion.vad import SilenceEndpointer, FRAME_MS
    stop = asyncio.Event()
    ep = SilenceEndpointer(silence_ms=1500)
    buf = bytearray()
    falou = False
    async for chunk in capture_chunks(stop, chunks_ms=FRAME_MS):
        if ep.is_speech(chunk):
            falou = True
        buf.extend(chunk)
        if falou and ep.ended(chunk):
            stop.set()
            break
    return bytes(buf)
        
async def play(audio_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> None:
    """Reproduz PCM int16 no speaker."""
    import numpy as np
    import sounddevice as sd
    audio = np.frombuffer(audio_bytes, dtype=np.int16)
    
    def _play():
        sd.play(audio, samplerate=sample_rate)
        sd.wait()
    
    await asyncio.get_event_loop().run_in_executor(None, _play)
    
async def tocar(pcm: bytes, rate: int) -> None:
    """Toca a resposta — Termux: WAV + termux-media-player. Desktop: sounddevice."""
    if _IS_TERMUX:
        wav = f"{_DIR}/resposta.wav"
        with wave.open(wav, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(pcm)
        await _run_sync(["termux-media-player", "play", wav])
        # termux-media-player 'play' VOLTA NA HORA (toca em background) → espera a duração real,
        # senão o próximo turno grava por cima da fala ainda tocando.
        await asyncio.sleep(len(pcm) / 2 / rate + 0.3)   # int16 mono: bytes/2 = amostras; /rate = segundos
        return
    await play(pcm, rate)


async def _beep() -> None:
    """Sonzinho curto (~0,14s) pra sinalizar 'estou ouvindo'. Sem numpy — roda no Termux."""
    try:
        import math, array
        rate, dur, freq = 16000, 0.14, 660
        n = int(rate * dur)
        pcm = array.array("h", (int(math.sin(2 * math.pi * freq * i / rate) * 0.25 * 32767) for i in range(n)))
        await tocar(pcm.tobytes(), rate)
    except Exception:
        print("\a", end="", flush=True)                       # fallback: bell do terminal


async def _esperar_enter(teto: int) -> None:
    """Segura o turno até o usuário apertar Enter; se teto>0, no máximo 'teto' segundos
    (o que vier primeiro). Usa add_reader pra NÃO deixar thread presa no stdin quando o teto estoura."""
    import sys
    loop = asyncio.get_running_loop()
    ev = asyncio.Event()
    def _ler():
        try: sys.stdin.readline()
        except Exception: pass
        ev.set()
    try:
        loop.add_reader(sys.stdin.fileno(), _ler)
    except (ValueError, OSError):                             # stdin sem fileno/selecionável → cai só no teto
        if teto > 0: await asyncio.sleep(teto)
        return
    try:
        if teto > 0:
            try: await asyncio.wait_for(ev.wait(), timeout=teto)
            except asyncio.TimeoutError: pass
        else:
            await ev.wait()
    finally:
        try: loop.remove_reader(sys.stdin.fileno())
        except Exception: pass

class GaplessPlayer:
    """Saída contínua p/ streaming de TTS — sem gap entre frases. PCM int16 @ rate."""
    def __init__(self, rate: int = TTS_SAMPLE_RATE):
        import sounddevice as sd
        self._stream = sd.OutputStream(samplerate=rate, channels=1, dtype="int16")
        self._stream.start()

    async def write(self, pcm: bytes) -> None:
        import numpy as np
        # write() é blocante (dá backpressure natural) → fora do event loop:
        await asyncio.to_thread(self._stream.write, np.frombuffer(pcm, dtype=np.int16))

    def clear(self) -> None:           # usado no 2.3 (barge-in): corta o que está tocando
        self._stream.abort()           # descarta o buffer pendente na hora
        self._stream.start()           # reabre pro próximo áudio

    def close(self) -> None:
        self._stream.stop(); self._stream.close()

    