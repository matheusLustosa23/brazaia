import json
import time

import httpx
import pytest

from domain.tools.guard import ToolCtx
from infrastructure.spotify.cliente import SpotifyCliente
from infrastructure.tools.spotify import SpotifyInput, SpotifyTool

CTX = ToolCtx(fala_do_usuario="")


class FakeSpotify:
    """Responde como a Web API; guarda as chamadas pra conferir."""
    def __init__(self, devices=None, tocando=None, playlists=None, curtidas=None, sem_escopo=False):
        self.curtidas, self.sem_escopo = curtidas or [], sem_escopo
        self.chamadas, self.devices = [], devices if devices is not None else [
            {"id": "d-pc", "name": "DESKTOP", "type": "Computer", "is_active": False},
            {"id": "d-s24", "name": "Galaxy S24 Ultra", "type": "Smartphone", "is_active": False}]
        self.tocando = tocando
        self.playlists = playlists or [{"id": "p1", "name": "Treino Pesado", "uri": "spotify:playlist:p1", "tracks": {"total": 40}}]
        self.refreshes = 0

    def __call__(self, req: httpx.Request) -> httpx.Response:
        caminho, q = req.url.path, dict(req.url.params)
        if "accounts.spotify.com" in str(req.url):          # renovação: corpo é formulário, não JSON
            self.refreshes += 1
            return httpx.Response(200, json={"access_token": "novo", "expires_in": 3600})
        self.chamadas.append((req.method, caminho, q, json.loads(req.content) if req.content else None))
        if caminho == "/v1/me/player/devices":
            return httpx.Response(200, json={"devices": self.devices})
        if caminho == "/v1/search":
            if "naoexiste" in q["q"]:
                return httpx.Response(200, json={q["type"] + "s": {"items": []}})
            item = {"name": q["q"].title(), "uri": f"spotify:{q['type']}:{q['q'][:5]}", "artists": [{"name": "Queen"}]}
            return httpx.Response(200, json={q["type"] + "s": {"items": [item]}})
        if caminho == "/v1/me/tracks":
            if self.sem_escopo:
                return httpx.Response(403, json={"error": {"status": 403, "message": "Insufficient client scope"}})
            off = int(q.get("offset", 0))
            pag = self.curtidas[off:off + 50]
            return httpx.Response(200, json={"items": [{"track": t} for t in pag],
                                             "next": "x" if off + 50 < len(self.curtidas) else None})
        if caminho == "/v1/me/playlists":
            return httpx.Response(200, json={"items": self.playlists})
        if caminho == "/v1/me/player" and req.method == "GET":
            return httpx.Response(200, json=self.tocando) if self.tocando else httpx.Response(204)
        if caminho == "/v1/me":
            return httpx.Response(200, json={"id": "dono"})
        if caminho == "/v1/users/dono/playlists":
            return httpx.Response(201, json={"id": "nova", "name": json.loads(req.content)["name"]})
        return httpx.Response(204)


@pytest.fixture
def tool(tmp_path):
    def fazer(fake, expira_em=3600):
        tok = tmp_path / "tok.json"
        tok.write_text(json.dumps({"access_token": "velho", "refresh_token": "r", "expires_at": time.time() + expira_em}))
        return SpotifyTool(SpotifyCliente("id", "segredo", str(tok), transport=httpx.MockTransport(fake)))
    return fazer


async def test_tocar_musica_no_celular_pelo_nome(tool):
    fake = FakeSpotify()
    out = await tool(fake).run(SpotifyInput(acao="tocar", busca="bohemian rhapsody", dispositivo="celular"), CTX)
    assert out.startswith("[erro] Spotify: não consegui tocar")          # sem álbum: não manda faixa solta (app fica vazio)
    assert not [c for c in fake.chamadas if c[1] == "/v1/me/player/play"]


async def test_playlist_do_dono_vem_antes_da_busca(tool):
    fake = FakeSpotify()
    out = await tool(fake).run(SpotifyInput(acao="tocar", busca="treino", tipo="playlist"), CTX)
    assert "playlist 'Treino Pesado'" in out
    assert not [c for c in fake.chamadas if c[1] == "/v1/search"]
    assert [c for c in fake.chamadas if c[1] == "/v1/me/player/play"][0][3] == {"context_uri": "spotify:playlist:p1"}


async def test_pular_mostra_a_musica_nova(tool):
    fake = FakeSpotify(tocando={"is_playing": True, "item": {"name": "Tempo Perdido", "artists": [{"name": "Legião Urbana"}]},
                                "device": {"name": "Galaxy S24 Ultra"}})
    fake.devices[1]["is_active"] = True
    out = await tool(fake).run(SpotifyInput(acao="proxima"), CTX)
    assert 'pulou no Galaxy S24 Ultra — agora: "Tempo Perdido", de Legião Urbana' in out
    assert ("POST", "/v1/me/player/next") in [(c[0], c[1]) for c in fake.chamadas]


async def test_criar_playlist_avisa_o_que_nao_achou(tool):
    fake = FakeSpotify()
    out = await tool(fake).run(SpotifyInput(acao="criar_playlist", nome_playlist="Foco",
                                            musicas=["clocks coldplay", "naoexiste xyz"]), CTX)
    assert "playlist 'Foco' criada com 1 música(s); não achei: naoexiste xyz" in out
    add = [c for c in fake.chamadas if c[1] == "/v1/playlists/nova/tracks"][0]
    assert add[3] == {"uris": ["spotify:track:clock"]}


async def test_sem_spotify_aberto_explica(tool):
    out = await tool(FakeSpotify(devices=[])).run(SpotifyInput(acao="tocar", busca="x"), CTX)
    assert out.startswith("[erro] Spotify: nenhum Spotify aberto")


async def test_token_vencido_renova_sozinho(tool):
    fake = FakeSpotify()
    await tool(fake, expira_em=-10).run(SpotifyInput(acao="aparelhos"), CTX)
    assert fake.refreshes == 1


async def test_sem_login_diz_como_conectar(tmp_path):
    t = SpotifyTool(SpotifyCliente("", "", str(tmp_path / "nao.json")))
    assert "spotify_login.py" in await t.run(SpotifyInput(acao="tocando"), CTX)


async def test_busca_sem_market_e_403_de_escopo_explica(tool):
    fake = FakeSpotify()
    await tool(fake).run(SpotifyInput(acao="fila", busca="them bones"), CTX)
    busca = [c for c in fake.chamadas if c[1] == "/v1/search"][0]
    assert "market" not in busca[2]                          # market=from_token exige user-read-private

    def recusa(req):
        if "accounts" in str(req.url):
            return httpx.Response(200, json={"access_token": "x", "expires_in": 3600})
        return httpx.Response(403, json={"error": {"status": 403, "message": "Insufficient client scope"}})
    out = await tool(recusa).run(SpotifyInput(acao="aparelhos"), CTX)
    assert "spotify_login.py" in out


async def test_fila_200_sem_json_e_sucesso_e_varias_em_ordem(tool):
    class FilaTexto(FakeSpotify):
        def __call__(self, req):
            if req.url.path == "/v1/me/player/queue" and req.method == "POST":
                self.chamadas.append((req.method, req.url.path, dict(req.url.params), None))
                return httpx.Response(200, text="ok")           # o Spotify real responde 200 com corpo não-JSON
            return super().__call__(req)
    fake = FilaTexto()
    fake.devices[0]["is_active"] = True
    out = await tool(fake).run(SpotifyInput(acao="fila", musicas=["man in the box", "naoexiste", "them bones"]), CTX)
    assert out.startswith('[spotify] na fila, nesta ordem (no DESKTOP): 1. "Man In The Box", de Queen; 2. "Them Bones", de Queen')
    assert "não achei: naoexiste" in out
    filas = [c[2]["uri"] for c in fake.chamadas if c[1] == "/v1/me/player/queue"]
    assert filas == ["spotify:track:man i", "spotify:track:them "]   # uma vez cada, na ordem


async def test_ver_fila(tool):
    class ComFila(FakeSpotify):
        def __call__(self, req):
            if req.url.path == "/v1/me/player/queue" and req.method == "GET":
                return httpx.Response(200, json={"currently_playing": {"name": "Them Bones", "artists": [{"name": "Alice In Chains"}]},
                                                 "queue": [{"name": "Rooster", "artists": [{"name": "Alice In Chains"}]}]})
            return super().__call__(req)
    out = await tool(ComFila()).run(SpotifyInput(acao="ver_fila"), CTX)
    assert out == '[spotify] agora: "Them Bones", de Alice In Chains · a seguir: 1. "Rooster", de Alice In Chains.'



def _faixa(nome, artista, n):
    return {"name": nome, "uri": f"spotify:track:{n}", "artists": [{"name": artista}],
            "album": {"uri": f"spotify:album:{n}", "name": f"Album {n}"}}


async def test_bones_vem_das_curtidas_e_segue_a_lista(tool):
    # 06/11: "toca bones" tocou "HDMI", do artista BONES (1º da busca geral), e parou depois dela
    curt = [_faixa("All These Things I Hate", "Bullet For My Valentine", "a"), _faixa("Man in the Box", "Alice In Chains", "b"),
            _faixa("Them Bones", "Alice In Chains", "c"), _faixa("Dracula", "Tame Impala", "d")]
    fake = FakeSpotify(curtidas=curt)
    out = await tool(fake).run(SpotifyInput(acao="tocar", busca="bones"), CTX)
    assert '"Them Bones", de Alice In Chains das suas Músicas curtidas (segue a lista)' in out
    play = [c for c in fake.chamadas if c[1] == "/v1/me/player/play"][0]
    assert play[3] == {"context_uri": "spotify:user:dono:collection", "offset": {"uri": "spotify:track:c"}}  # contexto, não lista
    assert not [c for c in fake.chamadas if c[1] == "/v1/search"]


async def test_fora_das_curtidas_segue_o_album(tool):
    class ComAlbum(FakeSpotify):
        def __call__(self, req):
            if req.url.path == "/v1/search":
                return httpx.Response(200, json={"tracks": {"items": [
                    _faixa("HDMI", "BONES", "x"), _faixa("Teen Romance", "Lil Peep", "t")]}})
            return super().__call__(req)
    fake = ComAlbum()
    out = await tool(fake).run(SpotifyInput(acao="tocar", busca="teen romance"), CTX)
    assert '"Teen Romance", de Lil Peep (do álbum "Album t", segue o álbum)' in out      # o que mais responde, não o 1º
    play = [c for c in fake.chamadas if c[1] == "/v1/me/player/play"][0]
    assert play[3] == {"context_uri": "spotify:album:t", "offset": {"uri": "spotify:track:t"}}


async def test_sem_permissao_das_curtidas_avisa_e_segue(tool):
    class ComAlbum(FakeSpotify):
        def __call__(self, req):
            if req.url.path == "/v1/search":
                return httpx.Response(200, json={"tracks": {"items": [_faixa("Bohemian Rhapsody", "Queen", "q")]}})
            return super().__call__(req)
    out = await tool(ComAlbum(sem_escopo=True)).run(SpotifyInput(acao="tocar", busca="bohemian rhapsody"), CTX)
    assert "segue o álbum" in out and "spotify_login.py" in out
