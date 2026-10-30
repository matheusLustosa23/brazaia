"""Diagnóstico do screenshot headless (rodar NO SERVER, ex.: Windows).

Por que: no Windows o chrome sai rc=0 sem gerar o PNG (stderr/stdout vazios). Em vez de chutar flag,
este script tenta várias COMBINAÇÕES de flags pro MESMO HTML e diz qual produz um PNG válido — aí a
gente fixa essa combo no infrastructure/render/shot.py.

Uso (no server):
    uv run --no-sync python ops/diag_chrome.py
    # ou: python ops/diag_chrome.py
"""
import subprocess
import tempfile
from pathlib import Path

_CANDIDATOS = [
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

HTML = "<!doctype html><html><body style='font:48px sans-serif'>DIAG OK ✓<br>αβγ x²</body></html>"


def achar_chrome() -> str:
    import shutil
    for c in _CANDIDATOS:
        achado = shutil.which(c) or (c if Path(c).exists() else None)
        if achado:
            return achado
    raise SystemExit("nenhum chrome/edge encontrado")


# Cada combo: (nome, lista de flags ANTES de --screenshot/url). {ud} = user-data-dir.
COMBOS = [
    ("headless=new (atual)",            ["--headless=new", "--disable-gpu", "--no-sandbox", "--user-data-dir={ud}"]),
    ("headless=new + compositor",       ["--headless=new", "--disable-gpu", "--no-sandbox", "--user-data-dir={ud}",
                                         "--run-all-compositor-stages-before-draw"]),
    ("headless=old",                    ["--headless=old", "--disable-gpu", "--no-sandbox", "--user-data-dir={ud}"]),
    ("headless (bare)",                 ["--headless", "--disable-gpu", "--no-sandbox", "--user-data-dir={ud}"]),
    ("new SEM virtual-time",            ["--headless=new", "--disable-gpu", "--no-sandbox", "--user-data-dir={ud}",
                                         "NO_VTB"]),
    ("new + janela pequena 800x600",    ["--headless=new", "--disable-gpu", "--no-sandbox", "--user-data-dir={ud}",
                                         "SMALL"]),
    ("new SEM user-data-dir",           ["--headless=new", "--disable-gpu", "--no-sandbox"]),
]


def roda(chrome: str, flags: list[str], tmp: Path, i: int) -> tuple[bool, int, str]:
    origem = tmp / f"p{i}.html"; origem.write_text(HTML, encoding="utf-8")
    destino = tmp / f"p{i}.png"
    ud = tmp / f"ud{i}"
    janela = "--window-size=800,600" if "SMALL" in flags else "--window-size=760,4000"
    args = [chrome]
    for f in flags:
        if f in ("NO_VTB", "SMALL"):
            continue
        args.append(f.format(ud=ud))
    if "NO_VTB" not in flags:
        args.append("--virtual-time-budget=5000")
    args += ["--hide-scrollbars", "--force-device-scale-factor=2", janela,
             f"--screenshot={destino}", origem.as_uri()]
    try:
        r = subprocess.run(args, capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        return False, -1, "TIMEOUT"
    ok = destino.exists() and destino.stat().st_size > 0
    tam = destino.stat().st_size if destino.exists() else 0
    err = (r.stderr.decode(errors="replace").strip() or r.stdout.decode(errors="replace").strip())[:120]
    return ok, r.returncode, f"{tam}B · {err or '∅'}"


def _passada(chrome: str, tmp: Path, titulo: str) -> None:
    print(f"\n### {titulo}")
    print(f"{'COMBO':<34} {'PNG?':<6} {'rc':<4} detalhe")
    print("-" * 80)
    for i, (nome, flags) in enumerate(COMBOS):
        ok, rc, det = roda(chrome, flags, tmp, i)
        print(f"{nome:<34} {'✅' if ok else '❌':<6} {rc:<4} {det}")
    print("-" * 80)


def main() -> None:
    import time
    chrome = achar_chrome()
    print(f"chrome: {chrome}")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        _passada(chrome, tmp, "PASSO 1 — Chrome LIMPO (nenhuma janela aberta)")

        # PASSO 2: reproduz a condição REAL — abre um Chrome normal (perfil padrão) e deixa rodando,
        # igual quando o agente mostrou páginas via open_file. Aí testamos de novo.
        print("\n>>> abrindo um Chrome NORMAL (perfil padrão) pra simular o estado real... "
              "(feche essa janela depois)")
        janela = tmp / "aberta.html"; janela.write_text("<h1>janela de teste — pode fechar</h1>", encoding="utf-8")
        proc = subprocess.Popen([chrome, janela.as_uri()])
        time.sleep(4)                                    # dá tempo do Chrome registrar a instância
        _passada(chrome, tmp, "PASSO 2 — COM um Chrome JÁ ABERTO (condição do teste real)")
        try:
            proc.terminate()
        except Exception:
            pass
        print("\n>>> LEIA o PASSO 2: se 'new SEM user-data-dir' deu ❌ e as COM user-data-dir deram ✅,")
        print(">>> então o fix (--user-data-dir no shot.py) é EXATAMENTE o necessário — só reiniciar o agent.")


if __name__ == "__main__":
    main()
