"""Server da pipeline de voz (roda na máquina da GPU).

Reaproveita a MESMA pipeline (VAD/STT/endpoint/LLM/TTS/barge-in) — só troca as pontas de I/O por um
transporte WebSocket. O microfone e o alto-falante ficam no companion (outro device):

  companion → server : binário PCM16 @ 16k (mic, contínuo) · json {"type":"hello"|"bye"}
  server → companion : json (partial/final/thinking/reply_*/interrupt/info/error) + binário PCM16 @ 24k

Os modelos (STT, TTS) carregam UMA vez e são compartilhados pela sessão (uso pessoal = 1 companion).

Rodar (na 2060S):
  CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=1 \
  VLLM_BASE_URL=http://127.0.0.1:8002/v1 VLLM_MODEL=qwen35-27b-abl \
  python -m voice_pipeline.server
"""
from __future__ import annotations
import os
import sys
import json
import asyncio
import collections

try:
    import torch
    if sys.platform == "win32":
        os.add_dll_directory(os.path.join(os.path.dirname(torch.__file__), "lib"))
except Exception:
    pass

import websockets

from .config import Config
from .capture import AudioBuffer
from .stt import make_transcriber
from .llm import VLLMResponder
from .tts import make_synth
from .pipeline import VoicePipeline


class WSOutput:
    """Adaptador que faz as vezes de `player` E de `transcript` da pipeline, enviando pelo WebSocket.

    Os métodos da pipeline são síncronos; aqui eles só ENFILEIRAM mensagens numa deque e sinalizam um
    `sender` assíncrono (mesma loop, sem threads). `clear()` (barge-in) descarta o áudio pendente e
    joga o `interrupt` na frente da fila → corte instantâneo."""

    def __init__(self, ws):
        self.ws = ws
        self._dq: collections.deque = collections.deque()
        self._ev = asyncio.Event()
        self._stop = False

    # --- fila ---
    def _json(self, obj):
        self._dq.append(("j", obj)); self._ev.set()

    # --- interface de transcript ---
    def info(self, msg):         self._json({"type": "info", "text": msg})
    def error(self, msg):        self._json({"type": "error", "text": msg})
    def user_partial(self, text):self._json({"type": "partial", "text": text})
    def user_final(self, text):  self._json({"type": "final", "text": text})
    def thinking(self):          self._json({"type": "thinking"})
    def agent_start(self):       self._json({"type": "reply_start"})
    def agent_delta(self, d):    self._json({"type": "reply_delta", "text": d})
    def agent_final(self):       self._json({"type": "reply_end"})
    def interrupted(self):       self._json({"type": "reply_end"})

    # --- interface de player ---
    def feed(self, pcm):
        self._dq.append(("b", bytes(pcm))); self._ev.set()

    def clear(self):
        # barge-in: joga fora o áudio ainda não enviado e manda o interrupt imediatamente
        self._dq = collections.deque((k, v) for (k, v) in self._dq if k != "b")
        self._dq.appendleft(("j", {"type": "interrupt"}))
        self._ev.set()

    def busy(self):
        return False

    async def run(self):
        while not self._stop:
            await self._ev.wait(); self._ev.clear()
            while self._dq:
                kind, data = self._dq.popleft()
                try:
                    await self.ws.send(data if kind == "b" else json.dumps(data))
                except Exception:
                    return

    def stop(self):
        self._stop = True; self._ev.set()


async def _amain(cfg: Config):
    print("[server] carregando modelos (STT + TTS)…", flush=True)
    transcriber = make_transcriber(cfg.stt)       # carrega UMA vez, compartilhado
    tts = make_synth(cfg.tts, cfg.audio.tts_sample_rate)   # TTS_ENGINE: kokoro|piper|xtts|chatterbox
    host = os.getenv("VOICE_WS_HOST", "0.0.0.0")
    port = int(os.getenv("VOICE_WS_PORT", "8765"))

    async def handler(ws, *_):
        peer = getattr(ws, "remote_address", ("?",))[0]
        print(f"[server] companion {peer} conectado", flush=True)
        buf = AudioBuffer()
        out = WSOutput(ws)
        responder = VLLMResponder(cfg.llm)         # leve: 1 por sessão
        pipe = VoicePipeline(
            cfg, buffer=buf, transcriber=transcriber, responder=responder,
            tts=tts, player=out, transcript=out,
        )
        send_task = asyncio.create_task(out.run())
        proc_task = asyncio.create_task(pipe.run())
        try:
            async for msg in ws:
                if isinstance(msg, (bytes, bytearray)):
                    buf.feed(bytes(msg))           # PCM do mic do companion → buffer da pipeline
                else:
                    try:
                        ctrl = json.loads(msg)
                    except Exception:
                        continue
                    t = ctrl.get("type")
                    if t == "bye":
                        break
                    elif t == "barge":             # client detectou fala no playback → para a geração
                        await pipe.external_barge()
        finally:
            await pipe.shutdown()
            proc_task.cancel()
            out.stop(); send_task.cancel()
            print(f"[server] companion {peer} saiu", flush=True)

    async with websockets.serve(handler, host, port, max_size=None, ping_interval=20):
        print(f"[server] ouvindo em ws://{host}:{port}  (STT={cfg.stt.engine}) — pronto.", flush=True)
        await asyncio.Future()


def main():
    cfg = Config.load()
    try:
        asyncio.run(_amain(cfg))
    except KeyboardInterrupt:
        print("\n[server] encerrado.")


if __name__ == "__main__":
    main()
