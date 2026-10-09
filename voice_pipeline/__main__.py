"""Ponto de entrada: monta a pipeline e roda o loop de conversa.

  python -m voice_pipeline                 # usa os defaults do config.py (+ overrides de ambiente)
  python -m voice_pipeline --no-barge-in   # half-duplex (sem fone)
  python -m voice_pipeline --list-devices  # lista os dispositivos de áudio e sai
"""
from __future__ import annotations
import os
import sys
import asyncio
import argparse

# Windows: garante as DLLs do CUDA do torch no PATH antes de carregar os modelos.
try:
    import torch
    if sys.platform == "win32":
        os.add_dll_directory(os.path.join(os.path.dirname(torch.__file__), "lib"))
except Exception:
    pass

from .config import Config
from .capture import AudioBuffer, Microphone
from .stt import make_transcriber
from .llm import VLLMResponder
from .tts import KokoroTTS
from .playback import Player
from .transcript import Transcript
from .pipeline import VoicePipeline


def _list_devices():
    import sounddevice as sd
    print(sd.query_devices())


async def _amain(cfg: Config):
    tx = Transcript()
    tx.info("carregando modelos (STT + TTS)…")
    transcriber = make_transcriber(cfg.stt)                 # STT (faster-whisper | Parakeet)
    tts = KokoroTTS(cfg.tts, cfg.audio.tts_sample_rate)     # TTS (Kokoro PT-BR)
    responder = VLLMResponder(cfg.llm)                      # LLM (vLLM) — troque pelo agente na entrega 2
    tx.info(f"LLM → {cfg.llm.base_url} (modelo {cfg.llm.model})")

    buf = AudioBuffer()
    player = Player(cfg.audio, cfg.audio.tts_sample_rate)
    player.start()

    # mic contínuo → buffer. Em half-duplex, não escuta enquanto a IA fala (evita eco/auto-barge).
    def on_frame(pcm: bytes):
        if (not cfg.barge.enabled) and player.busy():
            return
        buf.feed(pcm)

    mic = Microphone(cfg.audio, on_frame)

    pipe = VoicePipeline(
        cfg, buffer=buf, transcriber=transcriber, responder=responder,
        tts=tts, player=player, transcript=tx,
    )

    mic.start()
    try:
        await pipe.run()
    finally:
        await pipe.shutdown()
        mic.stop()
        player.stop()


def main():
    ap = argparse.ArgumentParser(description="Pipeline de voz local (captura→VAD→STT→vLLM→TTS→barge-in).")
    ap.add_argument("--no-barge-in", action="store_true", help="half-duplex (use se NÃO tiver fone)")
    ap.add_argument("--list-devices", action="store_true", help="lista dispositivos de áudio e sai")
    a = ap.parse_args()
    if a.list_devices:
        _list_devices()
        return
    cfg = Config.load()
    if a.no_barge_in:
        cfg.barge.enabled = False
    try:
        asyncio.run(_amain(cfg))
    except KeyboardInterrupt:
        pass
    print("\n[voz] encerrado.")


if __name__ == "__main__":
    main()
