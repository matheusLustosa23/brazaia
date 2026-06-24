import os
from dataclasses import dataclass


@dataclass
class CompanionConfig:
    server_ws_url: str
    device_id: str
    device_name: str
    token: str | None = None


def load_config() -> CompanionConfig:
    return CompanionConfig(
        server_ws_url=os.getenv("SERVER_WS_URL", "ws://localhost:8000/api/v1/ws/device"),
        device_id=os.getenv("DEVICE_ID", "device_macbook_pro_01"),
        device_name=os.getenv("DEVICE_NAME", "Dispositivo Principal"),
        token=os.getenv("DEVICE_TOKEN"),
    )
