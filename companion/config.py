import os
from dataclasses import dataclass, field


def _carregar_env(caminho: str = "~/.brazaia.env") -> None:
    p = os.path.expanduser(caminho)
    if not os.path.exists(p):
        return
    for linha in open(p):
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        linha = linha.removeprefix("export ").strip()
        if "=" in linha:
            k, v = linha.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'")) 


@dataclass
class CompanionConfig:
    server_ws_url: str
    device_id: str
    device_name: str
    token: str | None = None
    wake_models: list[str] = field(default_factory=lambda: ["companion/models/braza.onnx"])
    wake_threshold: float = 0.3
    silence_ms: int = 1000 
    follow_up_ms: int = 7000 
    end_phrases: list[str] = field(default_factory=lambda: ["tchau braza", "encerrar","falow braza"])
    greeting_enabled: bool = True
    greeting_voice: str = "pm_santa" 


def load_config() -> CompanionConfig:
    _carregar_env() 
    return CompanionConfig(
        server_ws_url=os.getenv("SERVER_WS_URL", "ws://localhost:8000/api/v1"),
        device_id=os.getenv("DEVICE_ID", "device_macbook_pro_01"),
        device_name=os.getenv("DEVICE_NAME", "Dispositivo Principal"),
        token=os.getenv("DEVICE_TOKEN"),
        wake_models=os.getenv("WAKE_MODELS", "companion/models/braza.onnx").split(","),
        wake_threshold=float(os.getenv("WAKE_THRESHOLD", "0.3")),
        silence_ms=int(os.getenv("SILENCE_MS","1000")),
        follow_up_ms=int(os.getenv("FOLLOW_UP_MS","7000")),
        end_phrases=os.getenv("END_PHRASES", "tchau braza,encerrar,falou braza").split(","),
        greeting_enabled=bool(os.getenv("GREETING_ENABLED", "True")),
        greeting_voice=os.getenv("VOICE_TTS_VOICE", "pm_santa"),
    )
