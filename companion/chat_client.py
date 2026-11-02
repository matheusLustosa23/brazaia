# companion/chat_client.py
import os, httpx
from companion._json import loads as _loads     # _json cai em json se orjson faltar (Termux)

def _http_base(ws_url: str) -> str:
    return ws_url.replace("wss://","https://").replace("ws://","http://")

def _headers() -> dict:
    return {"x-api-key": os.getenv("AGENT_API_KEY", "change-me")}

async def listar_sessoes(cfg) -> list[dict]:
    """Sessões com conversa, da mais recente p/ a mais antiga: [{session_id, preview, turnos, updated_at}]."""
    async with httpx.AsyncClient(timeout=15, proxy=os.getenv("SOCKS_PROXY") or None) as http:
        r = await http.get(f"{_http_base(cfg.server_ws_url)}/chat/sessions", headers=_headers())
        r.raise_for_status()
        return _loads(r.content).get("sessions", [])

async def carregar_sessao(cfg, session_id: str) -> dict:
    """Uma sessão p/ retomar: {history, narrative, contexto} — narrative = o que a tela mostrou, por turno."""
    async with httpx.AsyncClient(timeout=20, proxy=os.getenv("SOCKS_PROXY") or None) as http:
        r = await http.get(f"{_http_base(cfg.server_ws_url)}/chat/sessions/{session_id}", headers=_headers())
        r.raise_for_status()
        return _loads(r.content)

async def chat_stream(msg: str, sid: str | None, cfg, image: str | None = None, think: bool = True):
    payload = {"message": msg, "stream": True, "device_id": cfg.device_id, "think": think}
    if sid:
        payload["session_id"] = sid
    if image:
        payload["image"] = image                 # data URL (data:image/...;base64,...) — anexo multimodal
    url = f"{_http_base(cfg.server_ws_url)}/chat"
    # Termux: sai pelo SOCKS5 do tailscaled (mesmo caminho do connect/voz). Desktop: proxy=None (rota direta).
    async with httpx.AsyncClient(timeout=None, proxy=os.getenv("SOCKS_PROXY") or None) as http:
        async with http.stream(
            "POST",
            url,
            json=payload,
            headers={"x-api-key": os.getenv("AGENT_API_KEY","change-me")}
        ) as r:
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                d = _loads(line[5:].strip())
                yield d
