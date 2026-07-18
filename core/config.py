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
    model_name: str = "QuantTrio/Qwen3-VL-30B-A3B-Instruct-AWQ"
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
    
    voice_stt_model: str = "small"       # benchmark: RTF ~0.11; "large-v3-turbo" p/ +qualidade
    voice_beam_size: int = 1
    voice_language: str = "pt"
    voice_sample_rate: int = 16_000
    voice_tts_voice: str = "pm_santa"
    
    vision_default_source: str = "webcam" 


@lru_cache 
def get_settings() -> Settings:
    return Settings()