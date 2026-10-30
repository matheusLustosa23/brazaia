"""file_store: armazém ÚNICO de artefatos gerados por TOOL (imagem, html, áudio futuro), no SERVER.

Um id por CONTEÚDO (sha256[:12]) → content-addressable: o id PROVA o conteúdo (dá pra re-hashear e
conferir), gera DEDUP automático (mesmo conteúdo → mesmo id, não reescreve) e é idempotente.
Caminho no server: ~/brazaia/{device}/{session}/{kind}/{id}.{ext}. O device NÃO guarda nada — gera,
manda pro server, server salva, device apaga. Recuperável por file_id no load_file/read_file.

NÃO entra aqui o áudio de voz/turno (transiente: transcrito → vai pro contexto → descartado). Só
artefato de tool (capture_image, render_image, display_page) e, no futuro, a tool de gravar áudio.

Substitui o ImageIndex (imagem vira kind='img') e o FileIndex flat — um store só pra tudo.
`get(id) -> caminho` é mantido por compatibilidade com os callers do ImageIndex durante a migração."""
import hashlib
import os

_RAIZ = os.path.expanduser("~/brazaia")


def file_id_de(data: bytes) -> str:
    """id content-addressable = sha256 do conteúdo, 12 hex (igual ao _img_id de hoje)."""
    return hashlib.sha256(data).hexdigest()[:12]


def file_marker(file_id: str, kind: str, title: str = "", desc: str = "") -> str:
    """Placeholder RICO do artefato (vai no resultado da tool e no histórico) — o modelo sabe o que é
    sem ter o conteúdo, pra escolher o id certo e NÃO abrir o tipo errado. Ex.:
    [file_id=ab12cd · html · "Métodos Ágeis" · guia animado de scrum/kanban]."""
    partes = [f"file_id={file_id}", kind]
    if title:
        partes.append(f'"{title}"')
    if desc:
        partes.append(desc)
    return "[" + " · ".join(partes) + "]"


class FileStore:
    """Índice id→caminho (memória) + escrita no disco do server. Único pra todos os kinds."""

    def __init__(self, raiz: str = _RAIZ) -> None:
        self._raiz = raiz
        self._map: dict[str, str] = {}
        self._meta: dict[str, dict] = {}                           # id -> {kind, title, desc}

    def put(self, data: bytes, *, device: str | None, session: str, kind: str, ext: str,
            title: str = "", desc: str = "") -> str:
        """Salva conteúdo + metadados e devolve o file_id (hash). Dedup: mesmo conteúdo → mesmo id.
        kind/title/desc alimentam o placeholder rico e o roteamento do open_file/see_file (por kind —
        o store decide o tipo, o modelo NÃO)."""
        fid = file_id_de(data)
        self._meta[fid] = {"kind": kind, "title": title, "desc": desc}
        if fid in self._map and os.path.exists(self._map[fid]):
            return fid                                              # já temos esse conteúdo (dedup)
        dev = device or "unknow"                                   # chat sem device → "server"
        if not ext.startswith("."):
            ext = "." + ext
        pasta = os.path.join(self._raiz, dev, session, kind)
        os.makedirs(pasta, exist_ok=True)
        caminho = os.path.join(pasta, f"{fid}{ext}")
        with open(caminho, "wb") as f:
            f.write(data)
        self._map[fid] = caminho
        return fid

    def put_text(self, texto: str, *, device: str | None, session: str, kind: str, ext: str,
                 title: str = "", desc: str = "") -> str:
        return self.put(texto.encode("utf-8"), device=device, session=session, kind=kind, ext=ext,
                        title=title, desc=desc)

    def meta(self, file_id: str) -> dict:
        """Metadados do artefato: {kind, title, desc}. {} se desconhecido."""
        return self._meta.get(file_id, {})

    def kind(self, file_id: str) -> str | None:
        """Tipo guardado (html/img/audio) — roteamento do open_file/see_file. None se desconhecido."""
        m = self._meta.get(file_id)
        return m.get("kind") if m else None

    def path(self, file_id: str) -> str | None:
        """Caminho do artefato, se ainda existe no disco; senão None."""
        p = self._map.get(file_id)
        return p if (p and os.path.exists(p)) else None

    def read_bytes(self, file_id: str) -> bytes | None:
        p = self.path(file_id)
        if p is None:
            return None
        with open(p, "rb") as f:
            return f.read()

    def read_text(self, file_id: str) -> str | None:
        b = self.read_bytes(file_id)
        return b.decode("utf-8", "replace") if b is not None else None

    def get(self, file_id: str) -> str | None:
        """Compat ImageIndex.get — devolve o caminho (migração gradual dos callers)."""
        return self.path(file_id)
