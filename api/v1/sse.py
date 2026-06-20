import orjson

def sse_event(data: dict, event: str | None = None) -> str:
    """Formata um evento SSE (text/event-stream). Payload serializado com orjson.
    SSE NÃO usa o envelope ApiResponse — entrega tokens incrementais."""
    prefix = f"event: {event}\n" if event else ""
    return f"{prefix}data: {orjson.dumps(data).decode()}\n\n"