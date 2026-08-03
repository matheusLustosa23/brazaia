"""E2E REAL: bate no endpoint `POST /api/v1/chat` (rota de verdade — DI real, orchestrator
real, router real) e lê a sessão PERSISTIDA pra ver se a tool certa foi chamada.
Nada de espelhar a fiação: exercita o caminho que roda em produção.

Precisa do SERVER de pé (uvicorn na porta configurada) E do vLLM. Uso:
    uv run python scripts/medir_e2e.py
    SERVER_HTTP_URL=http://localhost:8080/api/v1 uv run python scripts/medir_e2e.py
"""
import asyncio, sys, os, json, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import get_settings
from infrastructure.memory.session_store import SqlLiteSessionStore
from application.services.voice_service import VOICE_STYLE

# (fala, tool esperada | None p/ chitchat que NÃO deve chamar tool)
_TESTS = [
    ("renderiza um problema de equação aleatório", "render_math"),
    ("tira uma foto e me manda", "capture_image"),
    ("anota que amanhã tenho médico", "lembrar"),
    ("oi, tudo bem?", None),
    ("me fala as novidades", None),
    ("que horas são?", None),
]


def _post_chat(base: str, key: str, message: str, session_id: str) -> int:
    """POST síncrono (stdlib, sem dep). Passa nosso session_id pra ler a sessão exata depois."""
    data = json.dumps({"message": message, "session_id": session_id, "stream": False}).encode()
    req = urllib.request.Request(
        f"{base}/chat", data=data, method="POST",
        headers={"Content-Type": "application/json", "x-api-key": key},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.status


def _tools_chamadas(hist: list[dict]) -> list[str]:
    """Nomes das tools que o assistant chamou de verdade na sessão (tool_calls persistidos)."""
    nomes: list[str] = []
    for m in hist:
        if m.get("role") != "assistant":
            continue
        for tc in (m.get("tool_calls") or []):
            fn = tc.get("function") if isinstance(tc, dict) else None
            if fn and fn.get("name"):
                nomes.append(fn["name"])
    return nomes


async def medir() -> None:
    s = get_settings()
    base = os.getenv("SERVER_HTTP_URL", f"http://100.72.108.111:8080/api/v1")
    key = s.agent_api_key.get_secret_value()
    store = SqlLiteSessionStore(s.session_db_path)
    await store.init()

    print(f"E2E · {base}/chat · {len(_TESTS)} casos (rota real, lê a sessão persistida)\n")
    ok = 0
    for i, (msg, esp) in enumerate(_TESTS):
        sid = f"e2e-{i}"
        try:
            status = _post_chat(base, key, msg, sid)
            if status != 200:
                print(f"  ✗ {msg[:42]:<42} HTTP {status}"); continue
        except Exception as e:
            print(f"  ✗ {msg[:42]:<42} ERRO POST: {e}"); continue
        tools = _tools_chamadas(await store.get(sid))
        acerto = (esp in tools) if esp else (not tools)   # ação: chamou a certa · chitchat: não chamou nada
        ok += acerto
        print(f"  {'✓' if acerto else '✗'} {msg[:42]:<42} esp={esp or 'prosa':<13} chamou={tools or '—'}")
    print(f"\n  acerto E2E: {ok}/{len(_TESTS)}  (endpoint real → sessão real)")


if __name__ == "__main__":
    asyncio.run(medir())
