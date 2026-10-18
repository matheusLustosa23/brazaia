"""Protótipo de VOZ com o orchestrator LIMPO (ReAct single-pass) — standalone.

Pipeline: mic → STT (batch) → ReAct (stream tools=auto, sem router/juiz) → TTS Piper → áudio.
É pra SENTIR a voz com o fluxo novo antes de portar pro service. Tools SIMULADAS (foco: latência/fluxo).

Roda no server (mic + GPU + vLLM):
    VLLM_BASE_URL=http://iobraza:8002/v1 VLLM_MODEL=qwen35-27b-abl uv run python scripts/voz_react_limpo.py
Ctrl+C sai. Fala uma frase e PARA — ele transcreve, pensa e responde falando.
"""
import json
import os
import sys
import threading
import time
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings("ignore")

import numpy as np
import sounddevice as sd
from openai import OpenAI

from core.config import get_settings
from infrastructure.voice.asr import make_asr, is_hallucination
from infrastructure.voice.vad import make_vad, rms
from infrastructure.voice.tts import make_tts, para_fala, SentenceChunker
from application.prompts import build_system

BASE = os.getenv("VLLM_BASE_URL", "http://iobraza:8002/v1")
MODEL = os.getenv("VLLM_MODEL", os.getenv("MODEL_NAME", "qwen35-27b-abl"))
KEY = os.getenv("VLLM_API_KEY", "change-me")
NO_THINK = os.getenv("NO_THINK", "1") != "0"
SR = 16000
MAX_STEPS = 4

TOOLS = [
    {"type": "function", "function": {
        "name": "lembrar", "description": "Registra/guarda um fato ou memória do usuário (ex.: um treino feito).",
        "parameters": {"type": "object", "properties": {"fato": {"type": "string"}}, "required": ["fato"]}}},
    {"type": "function", "function": {
        "name": "notify", "description": "Envia uma notificação push ao device do usuário.",
        "parameters": {"type": "object", "properties": {"titulo": {"type": "string"}, "corpo": {"type": "string"}},
                       "required": ["titulo", "corpo"]}}},
    {"type": "function", "function": {
        "name": "render_html", "description": "Gera um HTML e abre no navegador do device (tabela de treino, exercício, etc.).",
        "parameters": {"type": "object", "properties": {"titulo": {"type": "string"}, "html": {"type": "string"}},
                       "required": ["titulo", "html"]}}},
]
TOOL_GUIDE = (
    "\n\n[Ferramentas] Você tem: lembrar, notify, render_html. Chame UMA só quando a ação pedir "
    "('registra', 'me avisa', 'gera/mostra/abre um html'). Em 'me explica/me diz', responda só em PALAVRAS, "
    "sem tool. O argumento de render_html NÃO é falado — na voz, diga só que abriu/mostrou."
)


class MicBuffer:
    def __init__(self):
        self.buf = np.zeros(0, np.float32)
        self.lock = threading.Lock()
        self.stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32",
                                     blocksize=1600, callback=self._cb)

    def _cb(self, indata, frames, t, status):
        with self.lock:
            self.buf = np.concatenate([self.buf, indata[:, 0].copy()])

    def snapshot(self):
        with self.lock:
            return self.buf.copy()

    def clear(self):
        with self.lock:
            self.buf = np.zeros(0, np.float32)

    def keep_tail(self, n):
        with self.lock:
            self.buf = self.buf[-n:]


def is_speech(vad, s, audio):
    if vad is not None:
        return vad.speech_prob(audio) >= s.voice_vad_prob
    return rms(audio, int(SR * 0.3)) >= s.voice_rms_threshold


def exec_tool(nome, args):
    return f"[ok] {nome} executado com sucesso. args={args}"


def responder(client, msgs, tts, player):
    """ReAct: stream(tools=auto) → tool? executa e devolve → responde falando. Mede TTFT/TTFA/total."""
    t0 = time.monotonic()
    ttft = ttfa = None
    extra = {"chat_template_kwargs": {"enable_thinking": False}} if NO_THINK else {}
    for _ in range(MAX_STEPS):
        chunk = SentenceChunker()
        stream = client.chat.completions.create(
            model=MODEL, messages=msgs, tools=TOOLS, tool_choice="auto",
            temperature=0.6, max_tokens=500, stream=True, extra_body=extra)
        texto = ""
        calls: dict[int, dict] = {}
        print("🤖 ", end="", flush=True)
        for ch in stream:
            d = ch.choices[0].delta
            if d.content:
                if ttft is None:
                    ttft = (time.monotonic() - t0) * 1000
                texto += d.content
                print(d.content, end="", flush=True)
                for frase in chunk.push(d.content):
                    pcm = tts.synth(para_fala(frase))
                    if pcm:
                        if ttfa is None:
                            ttfa = (time.monotonic() - t0) * 1000
                        player.write(np.frombuffer(pcm, np.int16))
            if d.tool_calls:
                for tc in d.tool_calls:
                    slot = calls.setdefault(tc.index, {"name": "", "args": ""})
                    if tc.function and tc.function.name:
                        slot["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["args"] += tc.function.arguments
        if calls:                                           # chamou tool → executa (mock) → feedback
            tcs = [{"id": f"c{i}", "type": "function",
                    "function": {"name": v["name"], "arguments": v["args"]}} for i, v in calls.items()]
            msgs.append({"role": "assistant", "content": texto or None, "tool_calls": tcs})
            for i, v in calls.items():
                try:
                    args = json.loads(v["args"] or "{}")
                except Exception:
                    args = {"_raw": v["args"][:60]}
                resumo = {k: (str(x)[:50] + "…" if len(str(x)) > 50 else x) for k, x in args.items()}
                print(f"\n   🔧 {v['name']}({json.dumps(resumo, ensure_ascii=False)})", flush=True)
                msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": exec_tool(v["name"], args)})
            continue
        resto = chunk.flush()                               # última frase
        if resto:
            pcm = tts.synth(para_fala(resto))
            if pcm:
                if ttfa is None:
                    ttfa = (time.monotonic() - t0) * 1000
                player.write(np.frombuffer(pcm, np.int16))
        msgs.append({"role": "assistant", "content": texto})
        break
    total = (time.monotonic() - t0) * 1000
    print(f"\n   ⏱ pensar(TTFT) {ttft or 0:.0f}ms · 1º áudio(TTFA) {ttfa or 0:.0f}ms · total {total:.0f}ms")


def main():
    s = get_settings()
    print("carregando STT/VAD/TTS...", flush=True)
    asr, vad, tts = make_asr(s), make_vad(s), make_tts(s, s.voice_tts_sr)
    client = OpenAI(base_url=BASE, api_key=KEY)
    msgs = [{"role": "system", "content": build_system("voz") + TOOL_GUIDE}]

    mic = MicBuffer()
    player = sd.OutputStream(samplerate=s.voice_tts_sr, channels=1, dtype="int16")
    mic.stream.start()
    player.start()
    hop, end_sil = s.voice_hop_s, s.voice_end_silence_s
    print(f"\nReAct LIMPO + VOZ · {MODEL}\n🎙️  fala uma frase e PARA. (Ctrl+C sai)\n", flush=True)

    falando = False
    silencio = 0.0
    try:
        while True:
            time.sleep(hop)
            audio = mic.snapshot()
            if len(audio) < SR * s.voice_min_speech_s:
                continue
            if is_speech(vad, s, audio):
                falando = True
                silencio = 0.0
                print(f"  🎙️  ouvindo… {len(audio)/SR:4.1f}s", end="\r", flush=True)
            elif falando:
                silencio += hop
            if falando and silencio >= end_sil:
                t_stt = time.monotonic()
                palavras = asr.transcribe_words(audio)
                texto = " ".join(p.texto for p in palavras).strip()
                stt_ms = (time.monotonic() - t_stt) * 1000
                mic.clear()
                falando = False
                silencio = 0.0
                if not texto or is_hallucination(texto):
                    continue
                print(f"\r🫵  {texto}  (STT {stt_ms:.0f}ms)")
                msgs.append({"role": "user", "content": texto})
                responder(client, msgs, tts, player)
                mic.clear()                                 # descarta o que o mic captou durante a fala do bot
            elif not falando:
                mic.keep_tail(int(SR * 0.3))
    except KeyboardInterrupt:
        mic.stream.stop()
        player.stop()
        print("\nsaindo.")


if __name__ == "__main__":
    main()
