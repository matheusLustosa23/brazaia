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


def main() -> None:
    chrome = achar_chrome()
    print(f"chrome: {chrome}\n")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        print(f"{'COMBO':<34} {'PNG?':<6} {'rc':<4} detalhe")
        print("-" * 80)
        vencedor = None
        for i, (nome, flags) in enumerate(COMBOS):
            ok, rc, det = roda(chrome, flags, tmp, i)
            print(f"{nome:<34} {'✅' if ok else '❌':<6} {rc:<4} {det}")
            if ok and vencedor is None:
                vencedor = nome
        print("-" * 80)
        print(f"\n>>> PRIMEIRA combo que gerou PNG: {vencedor or 'NENHUMA — colar a saída aqui'}")


if __name__ == "__main__":
    main()
