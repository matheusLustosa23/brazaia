# companion/chat_client.py
import os, httpx
from companion._json import loads as _loads     # _json cai em json se orjson faltar (Termux)

def _http_base(ws_url: str) -> str:
    return ws_url.replace("wss://","https://").replace("ws://","http://")

def _headers() -> dict:
    return {"x-api-key": os.getenv("AGENT_API_KEY", "change-me")}

async def listar_sessoes(cfg, tag: str | None = None) -> list[dict]:
    """Sessões com conversa, da mais recente p/ a mais antiga: [{session_id, titulo, tags, modo, preview, turnos,
    updated_at}]. tag filtra (ex.: "replica")."""
    async with httpx.AsyncClient(timeout=15, proxy=os.getenv("SOCKS_PROXY") or None) as http:
        r = await http.get(f"{_http_base(cfg.server_ws_url)}/chat/sessions", headers=_headers(),
                           params={"tag": tag} if tag else None)
        r.raise_for_status()
        return _loads(r.content).get("sessions", [])

async def carregar_sessao(cfg, session_id: str) -> dict:
    """Uma sessão p/ retomar: {history, narrative, contexto} — narrative = o que a tela mostrou, por turno."""
    async with httpx.AsyncClient(timeout=20, proxy=os.getenv("SOCKS_PROXY") or None) as http:
        r = await http.get(f"{_http_base(cfg.server_ws_url)}/chat/sessions/{session_id}", headers=_headers())
        r.raise_for_status()
        return _loads(r.content)

async def listar_arquivos(cfg, session_id: str) -> list[dict]:
    """Artefatos que o agente gerou numa sessão: [{file_id, kind, title, desc, ts, ext, bytes}]."""
    async with httpx.AsyncClient(timeout=15, proxy=os.getenv("SOCKS_PROXY") or None) as http:
        r = await http.get(f"{_http_base(cfg.server_ws_url)}/files", headers=_headers(),
                           params={"session_id": session_id})
        r.raise_for_status()
        return _loads(r.content).get("files", [])

async def baixar_arquivo(cfg, file_id: str) -> tuple[bytes, str]:
    """(conteúdo, nome sugerido pelo server) de um artefato."""
    async with httpx.AsyncClient(timeout=60, proxy=os.getenv("SOCKS_PROXY") or None) as http:
        r = await http.get(f"{_http_base(cfg.server_ws_url)}/files/{file_id}", headers=_headers())
        r.raise_for_status()
        cd = r.headers.get("content-disposition", "")
        nome = cd.split("filename*=utf-8''")[-1] if "filename*=" in cd else (cd.split('filename="')[-1].rstrip('"') if "filename=" in cd else file_id)
        from urllib.parse import unquote
        return r.content, unquote(nome)

async def chat_stream(msg: str, sid: str | None, cfg, image: str | None = None, think: bool = True,
                      modo: str | None = None, titulo: str | None = None, tags: list[str] | None = None):
    payload = {"message": msg, "stream": True, "device_id": cfg.device_id, "think": think}
    for k, v in (("modo", modo), ("titulo", titulo), ("tags", tags)):    # metadados da sessão (só quando vierem)
        if v is not None:
            payload[k] = v
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
