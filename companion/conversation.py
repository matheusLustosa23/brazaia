from companion.config import CompanionConfig
from companion.wake import WakeWord
from companion.vad import SilenceEndpointer
from companion.greeting import play_greeting
from companion.audio import capture_chunks, play, TTS_SAMPLE_RATE
import websockets, numpy as np
from websockets.asyncio.client import ClientConnection
from core.config import get_settings
import asyncio, orjson, time


SAMPLE_RATE =  16_000
BAR_WIDTH = 20
RMS_FACTOR = 300

FOLLOW_UP_FRAME_MS = 30

def volume_bar(chunk: bytes, width: int = BAR_WIDTH) -> str:
    audio = np.frombuffer(chunk, dtype=np.int16)
    rms = np.sqrt(np.mean(audio.astype(float) ** 2)) if audio.size else 0.0
    level = min(int(rms / RMS_FACTOR), width)
    pct = min(int(rms / RMS_FACTOR * 100 / width), 100)
    return f"[{'█' * level}{'░' * (width - level)}] {pct}%"


class ConversationSession:
    def __init__(self, cfg: CompanionConfig):
        self.cfg = cfg
        self.url = f"{cfg.server_ws_url}/ws/voice"
        self.wake = WakeWord(cfg.wake_models, cfg.wake_threshold)
        self._endpointer = SilenceEndpointer(silence_ms=cfg.silence_ms)
    
 
        
    async def loop(self):
        while True:
            stop  = asyncio.Event()
            await self.wake.wait_for_trigger(capture_chunks(stop, chunks_ms=80))
            stop.set()
       
            if self.cfg.greeting_enabled:
                await play_greeting(get_settings().voice_tts_voice)
            await self._conversation()
    
    async def _conversation(self):
        async with websockets.connect(self.url, max_size=None) as ws:
            while True:
                texto = await self._run_turn(ws)
                if texto is None:
                    break
                if self._is_end_phrase(texto):
                    break
            await ws.send(orjson.dumps({"type": "conversation_end"}).decode())
            print("Conversa encerrada.\n")
    
    async def _run_turn(self , ws: ClientConnection):
        """Espera a fala (até follow_up_ms), captura até o silêncio, toca a resposta.
        Retorna o texto transcrito, ou None se ninguém falou (encerra a conversa)."""
        stop = asyncio.Event()
        self._endpointer.reset()
        started = False
        waited_ms = 0
        try:
            t0 = time.monotonic()
            async for  chunk in capture_chunks(stop, chunks_ms=FOLLOW_UP_FRAME_MS):
                bar = volume_bar(chunk)
                print(f"\r {bar} | {time.monotonic() - t0:.1f}s ", end="", flush=True)
                if not started:
                    if self._endpointer.is_speech(chunk):
                        started = True
                        await ws.send(
                            orjson.dumps(
                            {
                                "type": "turn_start", 
                                "device_id": self.cfg.device_id,
                                "sample_rate": SAMPLE_RATE
                            }
                            ).decode())
                        await ws.send(chunk)  
                    else:
                        waited_ms += FOLLOW_UP_FRAME_MS
                        if waited_ms >= self.cfg.follow_up_ms:
                            stop.set()
                            return None
                    continue
                
                await ws.send(chunk)
                if self._endpointer.ended(chunk):
                    print("\n[silêncio]")
                    stop.set()
                    break
        finally:
            stop.set()
        
        await ws.send(
            orjson.dumps(
                {
                    "type": "turn_end"
                }
            ).decode()
        )
        return await self._receive_reply(ws)
    
    async def _receive_reply(self, ws: ClientConnection) -> str:
        texto = ""
        async for msg in ws:
            if isinstance(msg , bytes):
                await play(msg, sample_rate=TTS_SAMPLE_RATE)
            else:
                ctrl = orjson.loads(msg)
                if ctrl.get("type") == "turn_done":
                    texto = ctrl.get("text") or ""
                    if ctrl.get("reply"):
                        print(f"IA: {ctrl['reply']}")
                    break
        return texto

    def _is_end_phrase(self, texto: str | None) -> bool:
        t = (texto or "").lower().strip(" .!?")
        return any(p in t for p in self.cfg.end_phrases)
                
        