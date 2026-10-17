from functools import lru_cache
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from core.environment import current_env

class Settings(BaseSettings):
    """Config 100% por env — zero hardcode de URL/chave. SecretStr p/ segredos.
    env_file=.env.{env} (dev/prod). get_settings() cacheado p/ injeção."""

    model_config = SettingsConfigDict(
        env_file=f".env.{current_env()}",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # metadados do app (vão p/ FastAPI(title/version/description))
    app_name: str = "Agente API"
    app_version: str = "0.1.0"
    app_description: str = "Assistente pessoal de IA — voz-first, multi-device, local"

    # engine (vLLM nunca exposto — só 127.0.0.1 no WSL)
    vllm_base_url: str = "http://127.0.0.1:8000/v1"
    vllm_api_key: SecretStr = SecretStr("change-me")

    # auth da Agente API (placeholder aqui; política real em feat-access-control)
    agent_api_key: SecretStr = SecretStr("change-me")

    # modelo + orçamento de contexto (defaults travados pela arquitetura)
    model_name: str = "cyankiwi/Qwen3-VL-8B-Instruct-AWQ-4bit"
    # model_name: str = "QuantTrio/Qwen3-VL-30B-A3B-Instruct-AWQ"
    max_context_tokens: int = 45056
    reserved_output_tokens: int =  8192
    
    # resiliência do cliente LLM  (NOVOS — feat-llm-client)
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 3
    llm_backoff_base_s: float = 0.5

    # transporte
    port: int = 8080
    log_level: str = "INFO"
    
    memory_db_path: str = "data/memoria.db"
    session_db_path: str = "data/sessoes.db"
    
    device_db_path: str = "data/devices.db"
    device_ws_timeout: float = 30.0
    
    # voz — STT
    voice_stt_engine: str = "whisper"        # whisper | parakeet
    voice_stt_model: str = "small"           # benchmark: RTF ~0.11; "large-v3-turbo" p/ +qualidade
    voice_stt_device: str = "auto"           # auto | cuda | cpu (rebaixa p/ base+int8 na CPU)
    voice_stt_compute: str = ""              # ""=auto (float16 na GPU, int8 na CPU)
    voice_language: str = "pt"
    voice_beam_size: int = 1
    voice_sample_rate: int = 16_000
    voice_parakeet_model: str = "nvidia/parakeet-tdt-0.6b-v3"
    voice_parakeet_stride: float = 0.08
    # voz — VAD / endpoint
    voice_vad: str = "auto"                  # auto | silero | rms | off
    voice_vad_prob: float = 0.5              # limiar de prob. de fala (silero)
    voice_rms_threshold: float = 0.015       # limiar de energia (fallback rms)
    voice_end_silence_s: float = 1.2         # silêncio p/ fechar turno
    voice_min_speech_s: float = 0.3
    voice_preroll_s: float = 0.6
    voice_hop_s: float = 0.5                 # passo do loop de escuta
    # voz — TTS
    voice_tts_engine: str = "piper"          # piper | kokoro | xtts | chatterbox
    voice_piper_model: str = ""              # resolvido no lifespan (models/)
    voice_tts_voice: str = "pm_santa"        # voz do kokoro (fallback)
    voice_tts_speed: float = 0.95
    voice_tts_device: str = "auto"
    voice_tts_sr: int = 24_000

    vision_default_source: str = "webcam" 


@lru_cache 
def get_settings() -> Settings:
    return Settings()