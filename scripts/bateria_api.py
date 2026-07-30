"""Bateria de teste do caminho SEM voz (rota real /api/v1/chat).
Cobre TODAS as tools individualmente + combinações (multi-tool) + chitchat.

Pra cada request: POST /chat (session própria) → lê a sessão persistida → imprime a
SEQUÊNCIA de tools que rodou. O DETALHE (router × auto/nudge/force) sai nos LOGS DA API
(os prints do _ensure_tool_call). Rode este script e acompanhe o console da API em paralelo.

⚠️ Antes de rodar: subir a API + CONECTAR os devices (celular, ubuntu, server) — as tools
de device (notify/open_image/display_*) precisam deles pra executar.

Uso:
    uv run python scripts/bateria_api.py
    SERVER_HTTP_URL=http://localhost:8080/api/v1 uv run python scripts/bateria_api.py
"""
import asyncio, sys, os, json, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import get_settings
from infrastructure.memory.session_store import SqlLiteSessionStore

# (rótulo do que esperamos, mensagem)
_REQS = [
    # ── single-tool: uma frase por tool ──
    ("render_math",            "renderiza a fórmula de bhaskara"),
    ("capture_image",          "tira uma foto da câmera"),
    ("lembrar",                "anota que amanhã tenho consulta às 3 da tarde"),
    ("display_math",           "mostra a matéria de derivadas na tela do celular pra eu estudar"),
    ("display_page",           "faz uma tabela comparando os 3 planos e mostra no celular"),
    ("notify (texto)",         "avisa no celular que o deploy terminou"),
    # ── chitchat: NENHUMA tool ──
    ("NENHUMA",                "oi, tudo bem?"),
    ("NENHUMA",                "que horas são?"),
    ("NENHUMA",                "me fala as novidades"),
    # ── combinações (multi-tool, id chaining) ──
    ("render→notify",          "gere a fórmula de limites e envie pro celular"),
    ("render→open",            "renderiza bhaskara e abre em tela cheia no celular"),
    ("capture→notify→open",    "tira uma foto, manda como notificação no celular e abre em tela cheia"),
    ("notify×2",               "avisa no celular que o build passou e depois avisa que o deploy subiu"),
    ("capture→load→display",   "olha pela câmera e monta uma página no celular com o que você vê"),
    ("6 tools",                "gere as fórmulas de fatoração numa imagem, os produtos notáveis noutra, "
                               "captura uma foto frontal, envia a fatoração pro server, envia a captura pro "
                               "ubuntu e abre os produtos notáveis no celular em tela cheia"),
]


def _post(base: str, key: str, message: str, sid: str) -> int:
    data = json.dumps({"message": message, "session_id": sid, "stream": False}).encode()
    req = urllib.request.Request(
        f"{base}/chat", data=data, method="POST",
        headers={"Content-Type": "application/json", "x-api-key": key},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.status


def _seq_tools(hist: list[dict]) -> list[str]:
    seq: list[str] = []
    for m in hist:
        if m.get("role") != "assistant":
            continue
        for tc in (m.get("tool_calls") or []):
            fn = tc.get("function") if isinstance(tc, dict) else None
            if fn and fn.get("name"):
                seq.append(fn["name"])
    return seq


async def main() -> None:
    s = get_settings()
    base = "http://100.72.108.111:8080/api/v1"
    key = s.agent_api_key.get_secret_value()
    store = SqlLiteSessionStore(s.session_db_path)
    await store.init()

    print(f"BATERIA · {base}/chat · {len(_REQS)} requests · SESSÃO ÚNICA")
    print("(o detalhe router×auto está nos LOGS DA API — acompanhe o console do server)\n")
    sid = "bateria-sessao"
    await store.set(sid, [])          # começa limpo (apaga histórico de rodadas anteriores)
    vistos = 0                        # tools já contadas → reporta só as NOVAS de cada request
    for i, (rotulo, msg) in enumerate(_REQS):
        try:
            st = _post(base, key, msg, sid)
            if st != 200:
                print(f"  ✗ [{rotulo}] HTTP {st}\n"); continue
        except Exception as e:
            print(f"  ✗ [{rotulo}] ERRO POST: {type(e).__name__}: {str(e)[:80]}\n"); continue
        todas = _seq_tools(await store.get(sid))
        novas = todas[vistos:]        # só as tools DESTE request (o histórico acumula)
        vistos = len(todas)
        print(f"  [{rotulo}]")
        print(f'     "{msg[:64]}{"..." if len(msg) > 64 else ""}"')
        print(f"     → {' → '.join(novas) if novas else '(prosa, sem tool)'}\n")


if __name__ == "__main__":
    asyncio.run(main())
