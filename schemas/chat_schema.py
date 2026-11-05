from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    stream: bool = True
    device_id: str | None = None
    image: str | None = None          # data URL (data:image/...;base64,...) — anexo multimodal
    think: bool = True                # False = desliga o thinking do Qwen3 (enable_thinking=False)
    modo: str | None = None           # "chat" | "tutor" — None = o modo já gravado na sessão (padrão chat)
    titulo: str | None = None         # nome da sessão (ex.: "réplica · Projeto Ágil T1")
    tags: list[str] | None = None     # etiquetas da sessão (ex.: ["replica"]) — filtram o /chat/sessions


class ChatData(BaseModel):
    session_id: str
    reply: str
    