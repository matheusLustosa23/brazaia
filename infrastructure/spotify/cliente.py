"""Cliente da Web API do Spotify (conta Premium do dono) — controla a reprodução em qualquer device com o app aberto.

Por que pela API (e não pelo celular): abrir/controlar app em 2º plano é bloqueado no Android 10+ e com a tela
apagada o Termux nem roda. A API fala com o Spotify Connect: toca/pula/enfileira no celular, PC ou caixa de som,
com a tela apagada, sem o companion no meio.

Login: UMA vez com `ops/spotify_login.py` (OAuth, retorno em 127.0.0.1) → data/spotify_token.json com o
refresh_token. Daqui pra frente o access_token (1 h) é renovado sozinho.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time

import httpx

API = "https://api.spotify.com/v1"
CONTAS = "https://accounts.spotify.com/api/token"
ESCOPOS = ("user-read-playback-state user-modify-playback-state user-read-currently-playing "
           "playlist-read-private playlist-modify-private playlist-modify-public")


class SpotifyErro(Exception):
    """Erro com mensagem pronta pro agente repetir ao dono."""


class SpotifyCliente:
    def __init__(self, client_id: str, client_secret: str, token_path: str,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._id, self._secret, self._path = client_id, client_secret, token_path
        self._transport = transport                         # testes injetam um MockTransport
        self._trava = asyncio.Lock()

    @property
    def configurado(self) -> bool:
        return bool(self._id and self._secret and os.path.exists(self._path))

    # ── token ─────────────────────────────────────────────────────────────────────────────────────────
    def _ler(self) -> dict:
        with open(self._path, encoding="utf-8") as f:
            return json.load(f)

    def _gravar(self, tok: dict) -> None:
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(tok, f)
        os.replace(tmp, self._path)

    def _auth(self) -> str:
        return "Basic " + base64.b64encode(f"{self._id}:{self._secret}".encode()).decode()

    async def _access_token(self, forcar: bool = False) -> str:
        if not self.configurado:
            raise SpotifyErro("o Spotify ainda não foi conectado — no Windows: python ops\\spotify_login.py")
        async with self._trava:
            tok = self._ler()
            if not forcar and tok.get("expires_at", 0) - 60 > time.time():
                return tok["access_token"]
            async with httpx.AsyncClient(timeout=20, transport=self._transport) as c:
                r = await c.post(CONTAS, data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]},
                                 headers={"Authorization": self._auth()})
            if r.status_code != 200:
                raise SpotifyErro(f"o login do Spotify expirou ou foi revogado ({r.status_code}) — "
                                  "rode de novo no Windows: python ops\\spotify_login.py")
            novo = r.json()
            tok.update(access_token=novo["access_token"], expires_at=time.time() + novo.get("expires_in", 3600))
            if novo.get("refresh_token"):                   # o Spotify às vezes gira o refresh_token
                tok["refresh_token"] = novo["refresh_token"]
            self._gravar(tok)
            return tok["access_token"]

    async def trocar_codigo(self, codigo: str, redirect_uri: str) -> None:
        """Usado só pelo ops/spotify_login.py: código do OAuth → tokens no arquivo."""
        async with httpx.AsyncClient(timeout=20, transport=self._transport) as c:
            r = await c.post(CONTAS, data={"grant_type": "authorization_code", "code": codigo,
                                           "redirect_uri": redirect_uri}, headers={"Authorization": self._auth()})
        r.raise_for_status()
        d = r.json()
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        self._gravar({"access_token": d["access_token"], "refresh_token": d["refresh_token"],
                      "expires_at": time.time() + d.get("expires_in", 3600)})

    # ── chamadas ──────────────────────────────────────────────────────────────────────────────────────
    async def req(self, metodo: str, caminho: str, **kw) -> dict | None:
        ultimo = 0
        for tentativa in range(3):
            tok = await self._access_token(forcar=tentativa > 0 and ultimo == 401)
            async with httpx.AsyncClient(timeout=20, transport=self._transport) as c:
                r = await c.request(metodo, API + caminho, headers={"Authorization": f"Bearer {tok}"}, **kw)
            ultimo = r.status_code
            if r.status_code == 401:                        # token venceu no meio: renova e tenta de novo
                continue
            if r.status_code == 429:                        # limite: espera o que o Spotify mandar (até 5 s)
                await asyncio.sleep(min(float(r.headers.get("Retry-After", "1")), 5))
                continue
            if r.status_code in (200, 201) and r.content:
                return r.json()
            if r.status_code in (200, 201, 202, 204):
                return None
            motivo = ""
            try:
                erro = r.json().get("error", {})
                motivo = erro.get("reason") or erro.get("message") or ""
            except ValueError:
                pass
            if motivo == "NO_ACTIVE_DEVICE":
                raise SpotifyErro("nenhum Spotify tocando agora — diga em qual device (ou abra o app uma vez)")
            if motivo == "PREMIUM_REQUIRED":
                raise SpotifyErro("controlar a reprodução exige Spotify Premium nesta conta")
            raise SpotifyErro(f"o Spotify recusou ({r.status_code}{': ' + motivo if motivo else ''})")
        raise SpotifyErro("o Spotify não respondeu depois de 3 tentativas")

    async def devices(self) -> list[dict]:
        return ((await self.req("GET", "/me/player/devices")) or {}).get("devices", [])

    async def tocando(self) -> dict | None:
        return await self.req("GET", "/me/player")

    async def buscar(self, q: str, tipo: str = "track", limite: int = 5) -> list[dict]:
        d = await self.req("GET", "/search", params={"q": q, "type": tipo, "limit": limite, "market": "from_token"})
        return [x for x in ((d or {}).get(tipo + "s", {}).get("items") or []) if x]

    async def tocar(self, device_id: str | None = None, uris: list[str] | None = None,
                    context_uri: str | None = None) -> None:
        corpo = {"uris": uris} if uris else ({"context_uri": context_uri} if context_uri else {})
        await self.req("PUT", "/me/player/play", params={"device_id": device_id} if device_id else None,
                       json=corpo or None)

    async def enfileirar(self, uri: str, device_id: str | None = None) -> None:
        await self.req("POST", "/me/player/queue", params={"uri": uri, **({"device_id": device_id} if device_id else {})})

    async def criar_playlist(self, nome: str, uris: list[str], descricao: str = "") -> dict:
        eu = await self.req("GET", "/me") or {}
        pl = await self.req("POST", f"/users/{eu['id']}/playlists",
                            json={"name": nome, "public": False, "description": descricao}) or {}
        for i in range(0, len(uris), 100):                   # a API aceita até 100 por vez
            await self.req("POST", f"/playlists/{pl['id']}/tracks", json={"uris": uris[i:i + 100]})
        return pl
