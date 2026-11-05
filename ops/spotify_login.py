"""Conecta o agente à sua conta do Spotify — UMA vez (no Windows, na sua sessão, com navegador).

Antes (uma vez): https://developer.spotify.com/dashboard → Create app
  • Redirect URI: http://127.0.0.1:8899/callback   (exatamente assim; o Spotify só aceita https ou 127.0.0.1)
  • API: Web API
  Copie Client ID e Client Secret pro .env.dev do servidor:
    SPOTIFY_CLIENT_ID=...
    SPOTIFY_CLIENT_SECRET=...

Depois:  .\\.venv\\Scripts\\python.exe ops\\spotify_login.py
Abre o navegador, você autoriza, e o refresh_token fica em data/spotify_token.json (o agente renova sozinho).
"""
import asyncio
import secrets
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.config import get_settings                                    # noqa: E402
from infrastructure.spotify.cliente import ESCOPOS, SpotifyCliente     # noqa: E402

PORTA = 8899
REDIRECT = f"http://127.0.0.1:{PORTA}/callback"


def main() -> None:
    s = get_settings()
    cid, segredo = s.spotify_client_id, s.spotify_client_secret.get_secret_value()
    if not cid or not segredo:
        sys.exit("faltam SPOTIFY_CLIENT_ID e SPOTIFY_CLIENT_SECRET no .env.dev (veja o topo deste arquivo)")
    estado = secrets.token_urlsafe(16)
    url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(
        {"client_id": cid, "response_type": "code", "redirect_uri": REDIRECT, "scope": ESCOPOS, "state": estado})
    recebido: dict = {}

    class Retorno(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            recebido.update({k: v[0] for k, v in q.items()})
            ok = "code" in recebido and recebido.get("state") == estado
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(("<h2>Spotify conectado ao agente. Pode fechar esta aba.</h2>" if ok else
                              "<h2>Não autorizado — veja o terminal.</h2>").encode())

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", PORTA), Retorno)
    print("abrindo o navegador pra você autorizar… (se não abrir, cole este link):\n" + url)
    webbrowser.open(url)
    while "code" not in recebido and "error" not in recebido:
        srv.handle_request()
    if recebido.get("state") != estado or "code" not in recebido:
        sys.exit(f"não autorizado: {recebido.get('error', 'estado inválido')}")
    cli = SpotifyCliente(cid, segredo, s.spotify_token_path)
    asyncio.run(cli.trocar_codigo(recebido["code"], REDIRECT))
    print(f"✅ Spotify conectado — token em {s.spotify_token_path}. Reinicie o agente pra tool entrar.")


if __name__ == "__main__":
    main()
