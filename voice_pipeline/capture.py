"""Captura de áudio do microfone + buffer thread-safe.

O microfone roda num callback do sounddevice (thread própria) e empurra PCM16 pro `AudioBuffer`,
que o resto da pipeline consome como float32. O buffer é o ponto de encontro entre a thread de
áudio e o loop assíncrono.
"""
from __future__ import annotations
import threading
import numpy as np
# `sounddevice` é importado DENTRO do Microphone (lazy): o server usa só o AudioBuffer (numpy puro)
# e não precisa de áudio/PortAudio instalado. Só o companion (I/O) exige sounddevice.


class AudioBuffer:
    """Acumula PCM int16 (bytes) como float32 mono. Seguro entre threads."""

    def __init__(self):
        self._buf = np.zeros(0, np.float32)
        self._lock = threading.Lock()

    def feed(self, pcm_bytes: bytes) -> None:
        a = np.frombuffer(pcm_bytes, np.int16).astype(np.float32) / 32768.0
        with self._lock:
            self._buf = np.concatenate([self._buf, a])

    def snapshot(self) -> np.ndarray:
        with self._lock:
            return self._buf.copy()

    def drop_front(self, n: int) -> None:
        if n <= 0:
            return
        with self._lock:
            self._buf = self._buf[n:]

    def keep_last(self, n: int) -> None:
        with self._lock:
            if len(self._buf) > n:
                self._buf = self._buf[-n:]

    def clear(self) -> None:
        with self._lock:
            self._buf = np.zeros(0, np.float32)

    def __len__(self) -> int:
        with self._lock:
            return len(self._buf)


class Microphone:
    """Stream contínuo do microfone. Chama `on_frame(pcm_bytes)` a cada bloco."""

    def __init__(self, cfg, on_frame):
        import sounddevice as sd            # lazy: só o companion (mic) precisa de sounddevice
        self.cfg = cfg
        self.on_frame = on_frame
        self._stream = sd.RawInputStream(
            samplerate=cfg.sample_rate, channels=1, dtype="int16",
            blocksize=int(cfg.sample_rate * cfg.frame_ms / 1000),
            device=cfg.input_device, callback=self._cb,
        )

    def _cb(self, indata, frames, t, status):
        # status é não-nulo em underruns/overruns; não derruba a pipeline.
        self.on_frame(bytes(indata))

    def start(self):
        self._stream.start()

    def stop(self):
        try:
            self._stream.stop(); self._stream.close()
        except Exception:
            pass
