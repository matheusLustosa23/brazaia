"""Teste ISOLADO da transcrição — alterna BATCH (default, CPU) × STREAMING (GPU).

Só STT+VAD, SEM agente/TTS. Pode rodar com o server desligado.

  BATCH    : VAD junta a frase inteira e transcreve 1x na pausa. Ideal p/ CPU (RTF>1):
             completo e correto, sem corte; custo = ~1-2s de espera no fim.
  STREAMING: re-transcreve a janela a cada hop + Stabilizer (autocorreção ao vivo).
             Texto crescendo palavra a palavra; só vale com GPU (RTF<1).

Rodar:
    uv run python3 scripts/teste_transcricao.py                 # batch (padrão)
    uv run python3 scripts/teste_transcricao.py streaming       # streaming (server/GPU)
    VOICE_STT_MODEL=base uv run python3 scripts/teste_transcricao.py streaming
"""
import pathlib
import sys
import threading
import time
import warnings

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))   # raiz no path
warnings.filterwarnings("ignore")                                          # silencia o warning do silero

import numpy as np
import sounddevice as sd

from core.config import get_settings
from infrastructure.voice.asr import Stabilizer, is_hallucination, collapse_repeats, make_asr
from infrastructure.voice.vad import Endpointer, rms, make_vad

SR = 16000
MAX_UTT_S = 15.0        # batch: trava de segurança se a fala passar disso sem pausa


class MicBuffer:
    """Buffer do mic preenchido por callback em outra thread. Acesso protegido por lock."""
    def __init__(self):
        self.buf = np.zeros(0, np.float32)
        self.lock = threading.Lock()
        self.stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32",
                                     blocksize=1600, callback=self._cb)

    def _cb(self, indata, frames, time_info, status):
        with self.lock:
            self.buf = np.concatenate([self.buf, indata[:, 0].copy()])

    def snapshot(self) -> np.ndarray:
        with self.lock:
            return self.buf.copy()

    def clear(self):
        with self.lock:
            self.buf = np.zeros(0, np.float32)

    def keep_tail(self, samples: int):
        with self.lock:
            self.buf = self.buf[-samples:]

    def drop_front(self, samples: int):
        with self.lock:
            self.buf = self.buf[samples:]

    def start(self): self.stream.start()
    def stop(self): self.stream.stop()


def is_speech(vad, s, audio: np.ndarray) -> bool:
    if vad is not None:
        return vad.speech_prob(audio) >= s.voice_vad_prob      # silero já olha os últimos 0.5s
    return rms(audio, int(SR * 0.3)) >= s.voice_rms_threshold


# ── BATCH: transcreve a frase inteira 1x na pausa ─────────────────────────────
def loop_batch(s, asr, vad, mic: MicBuffer):
    hop, end_sil = s.voice_hop_s, s.voice_end_silence_s
    falando, silencio, n = False, 0.0, 0
    while True:
        time.sleep(hop)
        audio = mic.snapshot()
        if len(audio) < SR * s.voice_min_speech_s:
            continue
        dur = len(audio) / SR

        if is_speech(vad, s, audio):
            falando, silencio = True, 0.0
            print(f"  🎙️  ouvindo… {dur:4.1f}s", end="\r", flush=True)
        elif falando:
            silencio += hop

        if falando and (silencio >= end_sil or dur >= MAX_UTT_S):
            t0 = time.monotonic()
            palavras = asr.transcribe_words(audio)
            texto = " ".join(p.texto for p in palavras).strip()
            dt = (time.monotonic() - t0) * 1000
            mic.clear()
            falando, silencio = False, 0.0
            if texto and not is_hallucination(texto):
                n += 1
                print(f"\r🫵  [{n}] {texto}".ljust(100))
                print(f"     (fala {dur:.1f}s · STT {dt:.0f}ms · RTF {dt / 1000 / dur:.2f})\n", flush=True)
            else:
                print(f"\r   (descartado: {texto!r})".ljust(100), flush=True)
        elif not falando:
            mic.keep_tail(int(SR * 0.3))                        # nada dito → não acumula silêncio


# ── STREAMING: re-transcreve a janela + Stabilizer (autocorreção ao vivo) ─────
def loop_streaming(s, asr, vad, mic: MicBuffer):
    stab, ep, hop, n = Stabilizer(), Endpointer(s), s.voice_hop_s, 0
    while True:
        time.sleep(hop)
        audio = mic.snapshot()
        if len(audio) < SR * s.voice_min_speech_s:
            continue

        if not is_speech(vad, s, audio):                       # silêncio → endpoint
            ep.add_silence(hop)
            if stab.has_text() and ep.ended(stab.tail_word()):
                final = stab.flush()
                mic.clear()
                ep.reset()
                if final and not is_hallucination(final):
                    n += 1
                    print(f"\r🫵  [{n}] {final}".ljust(100) + "\n", flush=True)
            elif not stab.has_text():
                mic.keep_tail(int(SR * s.voice_preroll_s))
            continue

        ep.reset()                                             # fala → transcreve a janela
        t0 = time.monotonic()
        prompt = " ".join(stab.committed[-40:])
        hyp = asr.transcribe_words(audio, prompt)
        dt = (time.monotonic() - t0) * 1000
        firme, prov, fim = stab.step(hyp)
        if fim > 0.4:
            mic.drop_front(int((fim - 0.3) * SR))
        print(f"  … [STT {dt:4.0f}ms · janela {len(audio) / SR:4.1f}s] {firme} ⟨{prov}⟩"
              .ljust(110), end="\r", flush=True)


def main():
    modo = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ("batch", "streaming") else "batch"
    s = get_settings()
    print(f"carregando STT/VAD (modo {modo.upper()})...", flush=True)
    asr, vad = make_asr(s), make_vad(s)
    print(f"\nmodo {modo.upper()} · hop={s.voice_hop_s}s · end_silence={s.voice_end_silence_s}s · "
          f"vad={'silero' if vad else 'rms'}\n", flush=True)
    mic = MicBuffer()
    mic.start()
    if modo == "batch":
        print("🎙️  fala uma frase e PARA — o texto sai na pausa. (Ctrl+C sai)\n", flush=True)
    else:
        print("🎙️  fala — o texto cresce ao vivo (… firme ⟨provisório⟩). (Ctrl+C sai)\n", flush=True)
    try:
        (loop_batch if modo == "batch" else loop_streaming)(s, asr, vad, mic)
    except KeyboardInterrupt:
        mic.stop()
        print("\n\nfim.")


if __name__ == "__main__":
    main()
