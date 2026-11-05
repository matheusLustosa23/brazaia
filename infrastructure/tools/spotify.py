from typing import Literal
import unicodedata

from pydantic import BaseModel, Field

from domain.tools.base import Tool
from domain.tools.guard import ToolCtx
from infrastructure.spotify.cliente import SpotifyCliente, SpotifyErro


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn").strip()


_TIPO = {"musica": "track", "artista": "artist", "album": "album", "playlist": "playlist"}
_APELIDO_TIPO = {"celular": "smartphone", "telefone": "smartphone", "pc": "computer", "computador": "computer",
                 "note": "computer", "notebook": "computer", "caixa": "speaker", "tv": "tv"}


class SpotifyInput(BaseModel):
    acao: Literal["tocar", "fila", "ver_fila", "pausar", "continuar", "proxima", "anterior", "tocando", "volume",
                  "playlists", "criar_playlist", "aparelhos"] = Field(description=(
        "tocar = toca agora pelo nome · fila = põe na fila (uma em busca OU várias em musicas, na ordem) · "
        "ver_fila = o que vem a seguir · pausar/continuar · "
        "proxima/anterior = pula ou volta a música · tocando = o que está tocando · volume (0-100) · "
        "playlists = lista as do dono · criar_playlist = cria uma com as músicas pedidas · aparelhos = onde dá pra tocar"))
    busca: str = Field(default="", description=(
        "O QUE tocar/enfileirar, do jeito que ele falou, com o artista se ele disse: "
        "'Bohemian Rhapsody Queen', 'Treino pesado', 'Acústico MTV Legião Urbana'."))
    tipo: Literal["musica", "artista", "album", "playlist"] = Field(default="musica", description=(
        "O que é a busca: 'toca a playlist Treino' → playlist · 'toca Legião Urbana' (só o artista) → artista."))
    dispositivo: str = Field(default="", description=(
        "Onde tocar, se ele disse: 'celular', 'PC', 'S24', o nome do aparelho no Spotify. Vazio = onde já está tocando."))
    musicas: list[str] = Field(default_factory=list, description=(
        "Pra criar_playlist e pra fila de VÁRIAS: uma música por item, na ordem, com artista "
        "('Tempo Perdido Legião Urbana')."))
    nome_playlist: str = Field(default="", description="Só pra criar_playlist: o nome da playlist nova.")
    volume: int | None = Field(default=None, ge=0, le=100, description="Só pra acao=volume: 0 a 100.")


def _quem(item: dict) -> str:
    artistas = ", ".join(a["name"] for a in item.get("artists") or [] if a.get("name"))
    return f"{item.get('name', '?')}" + (f" — {artistas}" if artistas else "")


class SpotifyTool(Tool[SpotifyInput]):
    name = "spotify"
    description = (
        "Controla o Spotify do dono (Premium) em qualquer aparelho com o app aberto — celular, PC, caixa — mesmo "
        "com a tela apagada: tocar pelo nome, pular/voltar, pausar, fila, volume, ver o que toca, listar e criar "
        "playlists.\nEx.: 'toca Bohemian Rhapsody' → spotify(acao=tocar, busca='Bohemian Rhapsody') · "
        "'pula essa' → spotify(acao=proxima) · 'põe Tempo Perdido na fila' → spotify(acao=fila, busca='Tempo "
        "Perdido Legião Urbana') · 'põe A, B e C na fila' → spotify(acao=fila, musicas=[A, B, C]) (UMA chamada) · "
        "'o que vem depois?' → spotify(acao=ver_fila) · 'toca minha playlist Treino no celular' → spotify(acao=tocar, busca='Treino', "
        "tipo=playlist, dispositivo='celular') · 'cria uma playlist Foco com X, Y e Z' → spotify(acao="
        "criar_playlist, nome_playlist='Foco', musicas=[X, Y, Z]).\n"
        "Diga ao dono o que o RESULTADO disse (a música e o aparelho reais), nunca o que você supôs."
    )
    input_schema = SpotifyInput
    side = "server"
    action_class = "reversible"
    timeout_s = 30.0
    router_hint = "tocar, pular, pausar, enfileirar música ou criar playlist no Spotify"

    def __init__(self, cliente: SpotifyCliente) -> None:
        self._c = cliente

    async def _aparelho(self, nome: str) -> tuple[str | None, str]:
        """(device_id ou None = o ativo, nome pra mostrar). Sem nada ativo e sem nome: o 1º disponível (celular antes)."""
        devs = await self._c.devices()
        if not devs:
            raise SpotifyErro("nenhum Spotify aberto agora — abra o app no celular ou no PC uma vez "
                              "(o Spotify só aparece pra API com o app aberto)")
        if nome:
            alvo = _norm(nome)
            tipo = _APELIDO_TIPO.get(alvo)
            achado = next((d for d in devs if alvo in _norm(d["name"])), None) or \
                next((d for d in devs if tipo and d.get("type", "").lower() == tipo), None)
            if not achado:
                raise SpotifyErro(f"não achei '{nome}' entre os Spotify abertos: "
                                  + ", ".join(f"{d['name']} ({d['type']})" for d in devs))
            return achado["id"], achado["name"]
        ativo = next((d for d in devs if d.get("is_active")), None)
        if ativo:
            return None, ativo["name"]
        d = sorted(devs, key=lambda x: x.get("type", "").lower() != "smartphone")[0]
        return d["id"], d["name"]

    async def _achar(self, busca: str, tipo: str) -> dict:
        if tipo == "playlist":                                # as DO DONO primeiro ("minha playlist Treino")
            minhas = (await self._c.req("GET", "/me/playlists", params={"limit": 50}) or {}).get("items") or []
            alvo = _norm(busca)
            achada = next((p for p in minhas if p and _norm(p["name"]) == alvo), None) or \
                next((p for p in minhas if p and alvo in _norm(p["name"])), None)
            if achada:
                return achada
        itens = await self._c.buscar(busca, _TIPO[tipo], limite=5)
        if not itens:
            raise SpotifyErro(f"não achei '{busca}' no Spotify")
        return itens[0]

    async def run(self, payload: SpotifyInput, ctx: ToolCtx) -> str:
        try:
            return await self._executar(payload)
        except SpotifyErro as e:
            return f"[erro] Spotify: {e}"

    async def _executar(self, p: SpotifyInput) -> str:
        a = p.acao
        if a == "aparelhos":
            devs = await self._c.devices()
            return "[spotify] aparelhos: " + (", ".join(
                f"{d['name']} ({d['type']}{', tocando' if d.get('is_active') else ''})" for d in devs)
                or "nenhum com o app aberto")
        if a == "playlists":
            itens = (await self._c.req("GET", "/me/playlists", params={"limit": 50}) or {}).get("items") or []
            return "[spotify] playlists: " + ("; ".join(
                f"{x['name']} ({(x.get('tracks') or {}).get('total', '?')} músicas)" for x in itens if x) or "nenhuma")
        if a == "tocando":
            st = await self._c.tocando()
            if not st or not st.get("item"):
                return "[spotify] nada tocando agora."
            estado = "tocando" if st.get("is_playing") else "pausado"
            return f"[spotify] {estado}: {_quem(st['item'])} · no {(st.get('device') or {}).get('name', '?')}"
        if a == "criar_playlist":
            if not p.nome_playlist or not p.musicas:
                return "[erro] Spotify: falta o nome da playlist e as músicas."
            uris, faltou = [], []
            for m in p.musicas:
                itens = await self._c.buscar(m, "track", limite=1)
                (uris.append(itens[0]["uri"]) if itens else faltou.append(m))
            if not uris:
                return "[erro] Spotify: não achei nenhuma das músicas — nada foi criado."
            pl = await self._c.criar_playlist(p.nome_playlist, uris, "criada pelo agente")
            return (f"[spotify] playlist '{pl.get('name', p.nome_playlist)}' criada com {len(uris)} música(s)"
                    + (f"; não achei: {', '.join(faltou)}" if faltou else "") + ".")
        if a == "ver_fila":
            f = await self._c.fila()
            prox = [x for x in (f.get("queue") or []) if x][:10]
            atual = f.get("currently_playing")
            if not atual and not prox:
                return "[spotify] fila vazia (nada tocando)."
            return ((f"[spotify] agora: {_quem(atual)}" if atual else "[spotify] nada tocando agora")
                    + (" · a seguir: " + "; ".join(f"{i}. {_quem(x)}" for i, x in enumerate(prox, 1)) if prox
                       else " · fila vazia depois dela") + ".")
        if a == "fila" and p.musicas:                       # várias, NA ORDEM (cada POST vai pro fim da fila)
            dev_id, dev_nome = await self._aparelho(p.dispositivo)
            entraram, faltou = [], []
            for m in p.musicas:
                itens = await self._c.buscar(m, "track", limite=1)
                if not itens:
                    faltou.append(m)
                    continue
                await self._c.enfileirar(itens[0]["uri"], dev_id)
                entraram.append(_quem(itens[0]))
            if not entraram:
                return "[erro] Spotify: não achei nenhuma das músicas — nada entrou na fila."
            return (f"[spotify] na fila, nesta ordem (no {dev_nome}): " + "; ".join(f"{i}. {x}" for i, x in enumerate(entraram, 1))
                    + (f" · não achei: {', '.join(faltou)}" if faltou else "") + ".")
        if a in ("tocar", "fila") and not p.busca.strip():
            if a == "tocar":                                  # "toca" sem dizer o quê = continuar
                a = "continuar"
            else:
                return "[erro] Spotify: falta o que pôr na fila."
        dev_id, dev_nome = await self._aparelho(p.dispositivo)
        if a == "tocar":
            item = await self._achar(p.busca, p.tipo)
            if p.tipo == "musica":
                await self._c.tocar(dev_id, uris=[item["uri"]])
                return f"[spotify] ▶ tocando {_quem(item)} no {dev_nome}."
            await self._c.tocar(dev_id, context_uri=item["uri"])
            return f"[spotify] ▶ tocando {p.tipo} '{item.get('name')}' no {dev_nome}."
        if a == "fila":
            item = await self._achar(p.busca, "musica")
            await self._c.enfileirar(item["uri"], dev_id)
            return f"[spotify] na fila: {_quem(item)} (toca depois da atual, no {dev_nome})."
        params = {"device_id": dev_id} if dev_id else None
        if a == "pausar":
            await self._c.req("PUT", "/me/player/pause", params=params)
            return f"[spotify] ⏸ pausado no {dev_nome}."
        if a == "continuar":
            await self._c.tocar(dev_id)
            return f"[spotify] ▶ continuando no {dev_nome}."
        if a in ("proxima", "anterior"):
            await self._c.req("POST", f"/me/player/{'next' if a == 'proxima' else 'previous'}", params=params)
            st = await self._c.tocando()
            agora = f" — agora: {_quem(st['item'])}" if st and st.get("item") else ""
            return f"[spotify] {'⏭ pulou' if a == 'proxima' else '⏮ voltou'} no {dev_nome}{agora}."
        if a == "volume":
            if p.volume is None:
                return "[erro] Spotify: falta o volume (0 a 100)."
            await self._c.req("PUT", "/me/player/volume", params={"volume_percent": p.volume, **(params or {})})
            return f"[spotify] 🔊 volume {p.volume}% no {dev_nome}."
        return f"[erro] Spotify: ação '{a}' desconhecida."
