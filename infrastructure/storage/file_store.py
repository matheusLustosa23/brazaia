"""file_store: armazém ÚNICO de artefatos gerados por TOOL (imagem, html, áudio futuro), no SERVER.

Um id por CONTEÚDO (sha256[:12]) → content-addressable: o id PROVA o conteúdo (dá pra re-hashear e
conferir), gera DEDUP automático (mesmo conteúdo → mesmo id, não reescreve) e é idempotente.
Caminho no server: ~/brazaia/{device}/{session}/{kind}/{id}.{ext}. O device NÃO guarda nada — gera,
manda pro server, server salva, device apaga. Recuperável por file_id no load_file/read_file.

NÃO entra aqui o áudio de voz/turno (transiente: transcrito → vai pro contexto → descartado). Só
artefato de tool (capture_image, render_image, display_page) e, no futuro, a tool de gravar áudio.

Um store só pra tudo (imagem vira kind='img'). Sobrevive a restart: metadados em <id>.meta.json ao lado."""
import hashlib
import json
import os
import time

_RAIZ = os.path.expanduser("~/brazaia")


def file_id_de(data: bytes) -> str:
    """id content-addressable = sha256 do conteúdo, 12 hex (igual ao _img_id de hoje)."""
    return hashlib.sha256(data).hexdigest()[:12]


_KIND_POR_EXT = {
    "html": "html", "htm": "html",
    "json": "json",
    "md": "txt", "markdown": "txt", "txt": "txt", "csv": "txt",
    "log": "txt", "xml": "txt", "yaml": "txt", "yml": "txt",
}


def kind_de_ext(ext: str) -> str:
    """ext (com ou sem ponto) -> kind pro roteamento do open_file/see_file. 'html'/'json' têm cara
    própria; o resto de texto cai em 'txt'. create_file só escreve TEXTO (o LLM digita o corpo)."""
    return _KIND_POR_EXT.get(ext.lower().lstrip("."), "txt")


def file_marker(file_id: str, kind: str, title: str = "", desc: str = "", ts: str = "") -> str:
    """Placeholder RICO do artefato (vai no resultado da tool) — o modelo sabe o que é sem ter o
    conteúdo, pra escolher o id certo e NÃO abrir o tipo errado. O horário ajuda a desambiguar quando
    há vários parecidos ('reabre o treino de antes'). Ex.:
    [file_id=ab12cd · html · 23:25 · "Métodos Ágeis" · guia animado de scrum/kanban]."""
    partes = [f"file_id={file_id}", kind]
    if ts:
        partes.append(ts)
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
        self._meta: dict[str, dict] = {}                           # id -> {kind, title, desc, ts, session, device}
        self._carregar()

    def _carregar(self) -> None:
        """Reconstrói o índice a partir do DISCO (~/brazaia/{device}/{session}/{kind}/{id}.{ext}). Sem isto,
        depois de reiniciar o agente nenhum file_id antigo abria (o índice só vivia em memória). Os metadados
        (título/descrição/horário) vêm do <id>.meta.json ao lado; arquivo antigo sem ele vira kind+mtime."""
        if not os.path.isdir(self._raiz):
            return
        for dev in os.listdir(self._raiz):
            d_dev = os.path.join(self._raiz, dev)
            if not os.path.isdir(d_dev) or dev == "cache":
                continue
            for session in os.listdir(d_dev):
                d_ses = os.path.join(d_dev, session)
                if not os.path.isdir(d_ses):
                    continue
                for kind in os.listdir(d_ses):
                    d_kind = os.path.join(d_ses, kind)
                    if not os.path.isdir(d_kind):
                        continue
                    for nome in os.listdir(d_kind):
                        if nome.endswith(".meta.json"):
                            continue
                        fid = os.path.splitext(nome)[0]
                        caminho = os.path.join(d_kind, nome)
                        meta = {"kind": kind, "title": "", "desc": "", "style": "free",
                                "ts": time.strftime("%d/%m %H:%M", time.localtime(os.path.getmtime(caminho)))}
                        try:
                            with open(os.path.join(d_kind, f"{fid}.meta.json"), encoding="utf-8") as f:
                                meta.update(json.load(f))
                        except (OSError, ValueError):
                            pass
                        meta.update(session=session, device=dev)
                        self._map[fid] = caminho
                        self._meta[fid] = meta

    def listar(self, session: str) -> list[dict]:
        """Artefatos de UMA sessão, do mais antigo pro mais novo: [{file_id, kind, title, desc, ts, ext, bytes}]."""
        itens = []
        for fid, m in self._meta.items():
            caminho = self._map.get(fid)
            if m.get("session") != session or not caminho or not os.path.exists(caminho):
                continue
            itens.append({"file_id": fid, "kind": m.get("kind"), "title": m.get("title") or "",
                          "desc": m.get("desc") or "", "ts": m.get("ts") or "",
                          "ext": os.path.splitext(caminho)[1].lstrip("."), "bytes": os.path.getsize(caminho),
                          "_mtime": os.path.getmtime(caminho)})
        itens.sort(key=lambda x: x.pop("_mtime"))
        return itens

    def put(self, data: bytes, *, device: str | None, session: str, kind: str, ext: str,
            title: str = "", desc: str = "", style: str = "free") -> str:
        """Salva conteúdo + metadados e devolve o file_id (hash). Dedup: mesmo conteúdo → mesmo id.
        kind/title/desc alimentam o placeholder rico e o roteamento do open_file/see_file (por kind —
        o store decide o tipo, o modelo NÃO). style (html) é lembrado pra screenshot/open_file
        renderizarem a página do MESMO jeito que o autor pediu (free/pico)."""
        fid = file_id_de(data)
        dev = device or "unknow"                                   # chat sem device → "server"
        meta = {"kind": kind, "title": title, "desc": desc, "style": style,
                "ts": time.strftime("%d/%m %H:%M")}
        if fid in self._map and os.path.exists(self._map[fid]):
            self._meta[fid] = {**self._meta.get(fid, {}), **meta}  # já temos esse conteúdo (dedup): só atualiza o rótulo
            return fid
        if not ext.startswith("."):
            ext = "." + ext
        pasta = os.path.join(self._raiz, dev, session, kind)
        os.makedirs(pasta, exist_ok=True)
        caminho = os.path.join(pasta, f"{fid}{ext}")
        with open(caminho, "wb") as f:
            f.write(data)
        try:                                                        # metadados ao lado → sobrevivem a reinício
            with open(os.path.join(pasta, f"{fid}.meta.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False)
        except OSError:
            pass
        self._map[fid] = caminho
        self._meta[fid] = {**meta, "session": session, "device": dev}
        return fid

    def put_text(self, texto: str, *, device: str | None, session: str, kind: str, ext: str,
                 title: str = "", desc: str = "", style: str = "free") -> str:
        return self.put(texto.encode("utf-8"), device=device, session=session, kind=kind, ext=ext,
                        title=title, desc=desc, style=style)

    def meta(self, file_id: str) -> dict:
        """Metadados do artefato: {kind, title, desc, ts}. {} se desconhecido."""
        return self._meta.get(file_id, {})

    def marker(self, file_id: str) -> str:
        """Placeholder rico do artefato montado a partir dos metadados guardados (fonte única — assim
        tool e orchestrator não divergem). Inclui o horário pra desambiguar vários parecidos."""
        m = self._meta.get(file_id, {})
        return file_marker(file_id, m.get("kind") or "file", m.get("title") or "",
                           m.get("desc") or "", m.get("ts") or "")

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
        """Caminho do artefato (= path); usado pelo resolve_data_uri do notify."""
        return self.path(file_id)
