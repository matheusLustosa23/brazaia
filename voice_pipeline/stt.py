"""Reconhecimento de fala (STT) em streaming, com autocorreção.

Duas peças:
  • Transcriber — transcreve um trecho de áudio → [(palavra, início, fim)]. Dois backends atrás da
    mesma interface: faster-whisper (padrão, pronto) e Parakeet/NeMo (upgrade, RNN-T multilíngue).
  • Stabilizer (LocalAgreement-2) — como re-transcrevemos o buffer que cresce a cada hop, só
    "cometemos" as palavras em que DOIS passos seguidos concordaram → o texto para de tremer.

Trocar de backend é só mudar `STT_ENGINE` (ou injetar outro Transcriber na pipeline).
"""
from __future__ import annotations
from typing import Protocol
import numpy as np

Word = tuple[str, float, float]   # (texto, início_s, fim_s)


class Transcriber(Protocol):
    def transcribe(self, audio: np.ndarray, prompt: str) -> list[Word]: ...


class WhisperTranscriber:
    """faster-whisper — rápido na 2060S, multilíngue, já validado no projeto."""

    def __init__(self, cfg):
        from faster_whisper import WhisperModel
        device, compute = cfg.device, cfg.compute_type
        if device in ("auto", "cuda"):                       # ctranslate2 tem CUDA própria (≠ torch)
            try:
                import ctranslate2
                device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            except Exception:
                device = "cpu"
        if device == "cpu" and compute in ("", "float16"):   # CPU não roda float16 → int8
            compute = "int8"
        if not compute:
            compute = "float16"
        print(f"[stt] faster-whisper {cfg.whisper_model} @ {device} ({compute}) ...", flush=True)
        self.cfg = cfg
        self.model = WhisperModel(cfg.whisper_model, device=device,
                                  compute_type=compute, num_workers=1)

    def transcribe(self, audio, prompt):
        segs, _ = self.model.transcribe(
            audio, language=self.cfg.language, beam_size=self.cfg.beam_size,
            word_timestamps=True, condition_on_previous_text=False,
            initial_prompt=prompt or None, hotwords=self.cfg.hotwords or None,
            vad_filter=True, no_repeat_ngram_size=3, temperature=0.0,
            hallucination_silence_threshold=0.5,
        )
        return [(w.word.strip(), w.start, w.end) for s in segs for w in (s.words or [])]


class ParakeetTranscriber:
    """NVIDIA Parakeet TDT 0.6B v3 (NeMo) — RNN-T, PT nativo, >2000x RTFx. Requer nemo_toolkit[asr]."""

    def __init__(self, cfg):
        import nemo.collections.asr as nemo_asr
        print(f"[stt] Parakeet {cfg.parakeet_model} @ cuda ...", flush=True)
        self.cfg = cfg
        self.model = nemo_asr.models.ASRModel.from_pretrained(model_name=cfg.parakeet_model)
        try:
            self.model = self.model.to("cuda").eval()
        except Exception:
            pass
        try:
            from nemo.utils import logging as _nl
            _nl.setLevel("ERROR")
        except Exception:
            pass

    def transcribe(self, audio, prompt):
        # Offline rodando no buffer que cresce (pseudo-streaming); barato pelo RTFx altíssimo.
        try:
            hyps = self.model.transcribe([audio], timestamps=True, batch_size=1, verbose=False)
        except TypeError:
            hyps = self.model.transcribe([audio], timestamps=True)
        if not hyps:
            return []
        h = hyps[0]
        ts = getattr(h, "timestamp", None)
        wlist = ts.get("word") if isinstance(ts, dict) else None
        if wlist:
            out = []
            for w in wlist:
                txt = (w.get("word") or w.get("char") or "").strip()
                if not txt:
                    continue
                st, en = w.get("start"), w.get("end")
                if st is None:                    # NeMo antigo: só offsets de frame
                    st = w.get("start_offset", 0) * self.cfg.parakeet_stride
                    en = w.get("end_offset", 0) * self.cfg.parakeet_stride
                out.append((txt, float(st), float(en)))
            return out
        # sem timestamps → distribui o texto no tempo (p/ o Stabilizer/endpoint)
        text = (h.text if hasattr(h, "text") else str(h)).strip()
        toks = text.split()
        dur = len(audio) / 16000
        step = dur / max(len(toks), 1)
        return [(t, i * step, (i + 1) * step) for i, t in enumerate(toks)]


def make_transcriber(cfg) -> Transcriber:
    if cfg.engine == "parakeet":
        return ParakeetTranscriber(cfg)
    return WhisperTranscriber(cfg)


class Stabilizer:
    """LocalAgreement-2: promove a 'committed' só o prefixo em que o passo atual e o anterior batem."""

    def __init__(self):
        self.committed: list[str] = []
        self.prev: list[Word] = []

    def reset(self):
        self.committed = []
        self.prev = []

    def step(self, hyp: list[Word]) -> tuple[str, str, float]:
        """Retorna (texto_firme, texto_provisório, fim_do_último_firme_em_s)."""
        agreed: list[Word] = []
        for (wa, _, _), (wb, sb, eb) in zip(self.prev, hyp):
            if wa == wb:
                agreed.append((wb, sb, eb))
            else:
                break
        for (w, _, _) in agreed:
            self.committed.append(w)
        self.prev = hyp[len(agreed):]
        agreed_end = agreed[-1][2] if agreed else 0.0
        return " ".join(self.committed), " ".join(w for (w, _, _) in self.prev), agreed_end

    def flush(self) -> str:
        """Fecha o turno: tudo que estava provisório vira firme; devolve o texto final limpo."""
        for (w, _, _) in self.prev:
            self.committed.append(w)
        final = collapse_repeats(" ".join(_dedupe(self.committed))).strip()   # tira alucinação repetida
        self.reset()
        return final

    def tail_word(self) -> str:
        words = self.committed + [w for (w, _, _) in self.prev]
        return words[-1].lower().strip(".,;:!?…") if words else ""

    def has_text(self) -> bool:
        return bool(self.committed or self.prev)


def _dedupe(words: list[str]) -> list[str]:
    out: list[str] = []
    for w in words:
        if out and out[-1].lower() == w.lower():
            continue
        out.append(w)
    return out


_HALUC_WORDS = {"obrigado", "obrigada", "tchau", "valeu", "pessoal", "gente", "muito", "até",
                "logo", "próxima", "amara", "org", "legenda", "legendas", "inscreva-se",
                "compartilhe", "curta"}
_HALUC_FRASES = {"legendas pela comunidade amara.org", "legendas pela comunidade",
                 "obrigado por assistir", "obrigada por assistir"}


def is_hallucination(text: str) -> bool:
    """True se o texto é provável ALUCINAÇÃO do Whisper em silêncio (saudação/agradecimento/legenda
    curta que o modelo inventa quando não há fala). Conservador: só pega frases curtas."""
    t = text.strip().lower().strip(".,;:!?…… ")
    if not t:
        return True
    if t in _HALUC_FRASES:
        return True
    palavras = [w.strip(".,;:!?…") for w in t.split()]
    return len(palavras) <= 4 and all(w in _HALUC_WORDS for w in palavras if w)


def collapse_repeats(text: str) -> str:
    """Colapsa blocos de 1–3 palavras repetidos 3+ vezes seguidas — alucinação do Whisper em ruído
    de fundo ('E aí E aí E aí', 'Eai Eai Eai'). Mantém 1 cópia; conservador (exige 3 repetições)."""
    w = text.split()
    n = len(w)
    out: list[str] = []
    i = 0
    while i < n:
        collapsed = False
        for size in (3, 2, 1):
            if i + size * 3 <= n:                       # precisa de ≥3 repetições do bloco
                block = w[i:i + size]
                j = i + size
                reps = 1
                while j + size <= n and [x.lower() for x in w[j:j + size]] == [x.lower() for x in block]:
                    reps += 1; j += size
                if reps >= 3:
                    out.extend(block); i = j; collapsed = True; break
        if not collapsed:
            out.append(w[i]); i += 1
    return " ".join(out)
