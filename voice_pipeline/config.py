"""Configuração central da pipeline de voz.

Edite os defaults aqui, ou sobrescreva por variável de ambiente (as principais têm override).
Tudo num lugar só: modelos, endpoint do vLLM, dispositivos de áudio e botões de latência/qualidade.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field


def _int_env(k, default):
    v = os.getenv(k)
    return int(v) if v not in (None, "") else default


def _opt_int_env(k):
    v = os.getenv(k)
    return int(v) if v not in (None, "") else None


def _float_env(k, default):
    v = os.getenv(k)
    return float(v) if v not in (None, "") else default


def _bool_env(k, default):
    v = os.getenv(k)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "sim", "on")


@dataclass
class AudioCfg:
    sample_rate: int = 16000          # STT trabalha a 16k
    tts_sample_rate: int = 24000      # Kokoro sai a 24k
    frame_ms: int = 20                # tamanho do bloco de captura
    input_device: int | None = None   # None = dispositivo padrão (veja `python -m sounddevice`)
    output_device: int | None = None

    @classmethod
    def load(cls):
        return cls(
            input_device=_opt_int_env("AUDIO_INPUT_DEVICE"),
            output_device=_opt_int_env("AUDIO_OUTPUT_DEVICE"),
        )


@dataclass
class VADCfg:
    rms_threshold: float = 0.015      # abaixo disso = silêncio (validado); ↑ só se ruído for transcrito,
                                      # mas CUIDADO: alto demais corta fala baixa → Whisper "completa" c/ obrigado
    onset_window_s: float = 0.3       # janela de RMS p/ detectar início de fala
    end_silence_s: float = 1.2        # silêncio que fecha o turno
    cont_mult: float = 2.5            # espera mais se a frase terminou em palavra de continuação
    min_speech_s: float = 0.3         # áudio mínimo antes de transcrever
    preroll_s: float = 0.6            # pré-roll mantido p/ não comer o início da fala
    # palavras que indicam "a frase ainda não acabou" → segura o endpoint
    cont_words: frozenset[str] = field(default_factory=lambda: frozenset({
        "em", "de", "do", "da", "dos", "das", "no", "na", "nos", "nas", "com", "e", "ou",
        "a", "o", "os", "as", "que", "para", "pra", "por", "um", "uma", "se", "como",
        "quando", "onde", "meu", "minha", "seu", "sua", "é",
    }))

    @classmethod
    def load(cls):
        return cls(
            rms_threshold=_float_env("VAD_RMS_THRESHOLD", 0.015),
            end_silence_s=_float_env("VAD_END_SILENCE_S", 1.2),
        )


@dataclass
class STTCfg:
    engine: str = "whisper"           # "whisper" (padrão, pronto) | "parakeet" (NeMo, upgrade)
    hop_s: float = 0.5                # a cada quanto re-transcreve o buffer (latência x custo)
    language: str = "pt"
    # faster-whisper
    whisper_model: str = "large-v3-turbo"
    device: str = "auto"              # auto → cuda se o ctranslate2 enxergar GPU, senão cpu+int8
    compute_type: str = ""            # vazio = auto (float16 na GPU, int8 no CPU)
    beam_size: int = 5
    hotwords: str = ""
    # Parakeet (NeMo) — opcional
    parakeet_model: str = "nvidia/parakeet-tdt-0.6b-v3"
    parakeet_stride: float = 0.08     # s/frame (FastConformer 8x subsampling) p/ offsets antigos

    @classmethod
    def load(cls):
        return cls(
            engine=os.getenv("STT_ENGINE", "whisper").lower(),
            hop_s=_float_env("STT_HOP_S", 0.5),
            language=os.getenv("STT_LANGUAGE", "pt"),
            whisper_model=os.getenv("WHISPER_MODEL", "large-v3-turbo"),
            device=os.getenv("STT_DEVICE", "auto"),
            compute_type=os.getenv("STT_COMPUTE", ""),
            parakeet_model=os.getenv("PARAKEET_MODEL", "nvidia/parakeet-tdt-0.6b-v3"),
        )


_DEFAULT_SYSTEM_PROMPT = (
    "Você é um assistente brasileiro num papo por voz. Responda em português do Brasil, natural e "
    "direto, respostas CURTAS (1–3 frases), sem markdown, emoji, listas ou código. Se te interromperem "
    "(verá '…(interrompido)' no seu turno anterior), aja como uma pessoa: responda ao que ele disse agora."
)


@dataclass
class LLMCfg:
    base_url: str = "http://127.0.0.1:8002/v1"
    model: str = "qwen35-27b-abl"
    api_key: str = "change-me"
    temperature: float = 0.6
    max_tokens: int = 400
    history_turns: int = 10           # quantas mensagens recentes enviar
    request_timeout_s: float = 60.0
    system_prompt: str = _DEFAULT_SYSTEM_PROMPT
    disable_thinking: bool = True     # vLLM/Qwen: desliga o <think> pra responder já

    @classmethod
    def load(cls):
        return cls(
            base_url=os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8002/v1"),
            model=os.getenv("VLLM_MODEL", os.getenv("MODEL_NAME", "qwen35-27b-abl")),
            api_key=os.getenv("VLLM_API_KEY", "change-me"),
            temperature=_float_env("LLM_TEMPERATURE", 0.6),
            max_tokens=_int_env("LLM_MAX_TOKENS", 400),
        )


@dataclass
class TTSCfg:
    engine: str = "kokoro"            # kokoro | piper | xtts | chatterbox  (TTS_ENGINE)
    voice: str = "pf_dora"            # kokoro: pf_dora=fem · pm_alex/pm_santa=masc (TTS_VOICE)
    speaker: str = "Ana Florence"     # xtts: speaker PRONTO do XTTS-v2 (TTS_SPEAKER)
    piper_model: str = ""             # piper: caminho do .onnx (PIPER_MODEL)
    lang_code: str = "p"              # 'p' = português no Kokoro
    device: str = "auto"              # auto → cuda se o torch enxergar GPU, senão cpu
    first_chunk_chars: int = 20       # 1º trecho curto → TTFA (time-to-first-audio) baixo
    speed: float = 0.95               # kokoro: <1 fala mais devagar/claro · >1 mais rápido (TTS_SPEED)

    @classmethod
    def load(cls):
        return cls(
            engine=os.getenv("TTS_ENGINE", "kokoro").lower(),
            voice=os.getenv("TTS_VOICE", "pf_dora"),
            speaker=os.getenv("TTS_SPEAKER", "Ana Florence"),
            piper_model=os.getenv("PIPER_MODEL", ""),
            device=os.getenv("TTS_DEVICE", "auto"),
            speed=_float_env("TTS_SPEED", 0.95),
        )


@dataclass
class BargeCfg:
    enabled: bool = True              # False = half-duplex (use se NÃO tiver fone, evita eco)
    poll_s: float = 0.15             # de quanto em quanto checa fala durante a resposta
    frames: int = 2                  # nº de janelas com voz p/ confirmar interrupção

    @classmethod
    def load(cls):
        return cls(
            enabled=_bool_env("BARGE_IN", True),
            poll_s=_float_env("BARGE_POLL_S", 0.15),
            frames=_int_env("BARGE_FRAMES", 2),   # ↑ p/ barge menos sensível (ex.: 3–4)
        )


@dataclass
class Config:
    audio: AudioCfg = field(default_factory=AudioCfg)
    vad: VADCfg = field(default_factory=VADCfg)
    stt: STTCfg = field(default_factory=STTCfg)
    llm: LLMCfg = field(default_factory=LLMCfg)
    tts: TTSCfg = field(default_factory=TTSCfg)
    barge: BargeCfg = field(default_factory=BargeCfg)

    @classmethod
    def load(cls):
        """Monta a config aplicando overrides de ambiente."""
        return cls(
            audio=AudioCfg.load(), vad=VADCfg.load(), stt=STTCfg.load(),
            llm=LLMCfg.load(), tts=TTSCfg.load(), barge=BargeCfg.load(),
        )
