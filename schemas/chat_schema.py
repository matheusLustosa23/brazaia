from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    stream: bool = True
    device_id: str | None = None


class ChatData(BaseModel):
    session_id: str
    reply: str
    