"""Reprodução de áudio gapless com suporte a interrupção (barge-in).

Um único `RawOutputStream` aberto; os PCM do TTS entram num buffer que o callback do sounddevice
drena. `clear()` esvazia o buffer na hora → corta a fala instantaneamente quando o usuário interrompe.
"""
from __future__ import annotations
import threading
import sounddevice as sd


class Player:
    def __init__(self, cfg, sample_rate: int = 24000):
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._stream = sd.RawOutputStream(
            samplerate=sample_rate, channels=1, dtype="int16",
            blocksize=0, device=cfg.output_device, callback=self._cb,
        )

    def _cb(self, outdata, frames, t, status):
        need = frames * 2   # int16 = 2 bytes
        with self._lock:
            n = min(need, len(self._buf))
            outdata[:n] = bytes(self._buf[:n])
            del self._buf[:n]
        if n < need:
            outdata[n:] = b"\x00" * (need - n)   # silêncio quando o buffer esvazia

    def start(self):
        self._stream.start()

    def feed(self, pcm: bytes):
        with self._lock:
            self._buf.extend(pcm)

    def clear(self):
        """Barge-in: descarta o áudio pendente imediatamente."""
        with self._lock:
            self._buf.clear()

    def busy(self) -> bool:
        with self._lock:
            return len(self._buf) > 0

    def stop(self):
        try:
            self._stream.stop(); self._stream.close()
        except Exception:
            pass
