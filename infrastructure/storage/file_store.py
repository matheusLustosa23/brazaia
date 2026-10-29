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


class FileStore:
    """Índice id→caminho (memória) + escrita no disco do server. Único pra todos os kinds."""

    def __init__(self, raiz: str = _RAIZ) -> None:
        self._raiz = raiz
        self._map: dict[str, str] = {}

    def put(self, data: bytes, *, device: str | None, session: str, kind: str, ext: str) -> str:
        """Salva o conteúdo e devolve o file_id (hash). Dedup: mesmo conteúdo → mesmo id, não reescreve."""
        fid = file_id_de(data)
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

    def put_text(self, texto: str, *, device: str | None, session: str, kind: str, ext: str) -> str:
        return self.put(texto.encode("utf-8"), device=device, session=session, kind=kind, ext=ext)

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
