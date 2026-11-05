"""Pacote (wheel) do companion, montado pelo SERVIDOR a partir da pasta companion/ — os devices instalam com pip e
se atualizam sozinhos. Antes: cada device clonava o projeto inteiro (5,8 GB) pra usar ~430 KB de código.

Sem ferramenta de build: um wheel é um zip com o código + `<nome>-<versão>.dist-info/` (METADATA, WHEEL, RECORD).
Versão = BASE + hash do CONTEÚDO (mudou um byte do companion → versão nova → os devices atualizam).
Fica de fora o que só o desktop usa e pesa: as saudações gravadas (8,7 MB) e o logo grande (2,5 MB).
"""
import base64
import hashlib
import io
import os
import threading
import zipfile
from pathlib import Path

NOME = "brazaia_companion"
BASE = "1.0.0"
RAIZ = Path(__file__).resolve().parents[1] / "companion"
DEPS = ["websockets", "python-socks", "httpx", "socksio"]
EXTRAS = {"cli": ["rich", "prompt_toolkit", "pylatexenc", "pyfiglet"]}
DIST = "data/companion_dist"
_TEXTO = {".py", ".sh", ".txt", ".md", ".json", ".toml"}
_trava = threading.Lock()


def info(destino: str = DIST) -> dict:
    """O que o servidor anuncia aos devices (welcome do handshake e GET /companion/versao)."""
    whl, v = montar(destino)
    return {"versao": v, "arquivo": whl.name, "url": f"/api/v1/companion/pacote/{whl.name}", "bytes": whl.stat().st_size}


def _fora(rel: str) -> bool:
    nome = rel.rsplit("/", 1)[-1]
    return ("__pycache__" in rel or nome.endswith((".pyc", ".pyo")) or nome == "_versao.py"
            or (rel.startswith("assets/greeting_") and nome.endswith(".wav"))
            or rel == "assets/images/braza_logo_full.png")


def arquivos() -> list[tuple[str, bytes]]:
    out = []
    # ordem pelo TEXTO do caminho: sorted() de Path no Windows ignora maiúsculas ("README.md" mudava de lugar
    # e a versão saía diferente da do Linux com o mesmo conteúdo)
    for p in sorted(RAIZ.rglob("*"), key=lambda x: x.relative_to(RAIZ).as_posix()):
        if p.is_file():
            rel = p.relative_to(RAIZ).as_posix()
            if not _fora(rel):
                dados = p.read_bytes()
                if p.suffix in _TEXTO:          # Windows (autocrlf) deixa CRLF: .sh com \r quebra no bash do Termux,
                    dados = dados.replace(b"\r\n", b"\n")   # e a versão (hash) tem que ser a mesma em qualquer máquina
                out.append((rel, dados))
    return out


def versao(arqs: list[tuple[str, bytes]] | None = None) -> str:
    h = hashlib.sha256()
    for rel, dados in arqs if arqs is not None else arquivos():
        h.update(rel.encode() + b"\0" + dados + b"\0")
    return f"{BASE}+h{h.hexdigest()[:10]}"


def _hash_record(dados: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(dados).digest()).rstrip(b"=").decode()


def montar(destino: str) -> tuple[Path, str]:
    """Gera (ou reaproveita) o wheel da versão atual em `destino`. Devolve (caminho, versão)."""
    with _trava:
        arqs = arquivos()
        v = versao(arqs)
        pasta = Path(destino)
        pasta.mkdir(parents=True, exist_ok=True)
        whl = pasta / f"{NOME}-{v}-py3-none-any.whl"
        if whl.exists():
            return whl, v
        info = f"{NOME}-{v}.dist-info"
        meta = [f"Metadata-Version: 2.1", f"Name: {NOME}", f"Version: {v}",
                "Summary: brazaia companion (device do agente)", "Requires-Python: >=3.10"]
        meta += [f"Requires-Dist: {d}" for d in DEPS]
        for extra, deps in EXTRAS.items():
            meta.append(f"Provides-Extra: {extra}")
            meta += [f'Requires-Dist: {d}; extra == "{extra}"' for d in deps]
        conteudo = [(f"companion/{rel}", dados) for rel, dados in arqs]
        conteudo.append(("companion/_versao.py", f'VERSAO = "{v}"\n'.encode()))
        conteudo += [
            (f"{info}/METADATA", ("\n".join(meta) + "\n").encode()),
            (f"{info}/WHEEL", b"Wheel-Version: 1.0\nGenerator: brazaia\nRoot-Is-Purelib: true\nTag: py3-none-any\n"),
            (f"{info}/entry_points.txt", b"[console_scripts]\nbrazaia-companion = companion.__main__:main\n"),
        ]
        record = [f"{nome},{_hash_record(d)},{len(d)}" for nome, d in conteudo] + [f"{info}/RECORD,,"]
        conteudo.append((f"{info}/RECORD", ("\n".join(record) + "\n").encode()))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for nome, dados in conteudo:
                z.writestr(zipfile.ZipInfo(nome, date_time=(2026, 1, 1, 0, 0, 0)), dados, zipfile.ZIP_DEFLATED)
        tmp = whl.with_suffix(".tmp")
        tmp.write_bytes(buf.getvalue())
        os.replace(tmp, whl)
        for velho in pasta.glob(f"{NOME}-*.whl"):            # guarda só a versão atual
            if velho != whl:
                velho.unlink(missing_ok=True)
        return whl, v
