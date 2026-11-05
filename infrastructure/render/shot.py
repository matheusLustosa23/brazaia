"""HTML -> PNG via chrome headless.

Por que o chrome e não uma lib Python: o MESMO HTML do render_page tem que
virar imagem sem um segundo motor de layout — senão a foto e a página teriam
tipografia diferente e seriam dois bugs pra caçar. O chrome renderiza o KaTeX
igualzinho ao navegador do device.

No Windows o Edge já vem instalado e é Chromium -> na prática, dep zero.
"""

import asyncio
import io
import shutil
import tempfile
from pathlib import Path

_ALTURA_MAX = 4000
_RESPIRO_PX = 24
_bin: str | None = None
_ESPERA_KATEX_MS = 5000     # virtual-time-budget: dá tempo do KaTeX rodar antes do print
_TIMEOUT_S = 60
_ERR_TRUNC = 200
_LARGURA_PADRAO = 760       # largura da página (px) — casa com o max-width do CSS
_ESCALA_PADRAO = 2.0  

_CANDIDATOS = [
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

def _chrome() -> str:
    global _bin
    if _bin is None:
        for c in _CANDIDATOS:
            achado = shutil.which(c) or (c if Path(c).exists() else None)
            if achado:
                _bin = achado
                break
        else:
            raise RuntimeError("chrome/chromium/edge não encontrado no server")
    return _bin

def _cortar(png: bytes) -> bytes:
    """Corta o branco sobrando embaixo.

    O chrome CLI não tem 'full page': renderiza-se numa janela alta fixa e
    corta-se na altura real do conteúdo.
    """
    from  PIL import Image, ImageChops
    imagem = Image.open(io.BytesIO(png)).convert("RGB")
    largura, altura = imagem.size

    fundo_branco = Image.new("RGB", imagem.size, (255, 255, 255))
    conteudo = ImageChops.difference(imagem, fundo_branco).getbbox()   # (esq, topo, dir, base) ou None
    if conteudo:
        _esquerda, _topo, _direita, base_conteudo = conteudo          # só a base interessa
        corte_base = min(base_conteudo + _RESPIRO_PX, altura)         # +folga, sem passar da altura
        imagem = imagem.crop((0, 0, largura, corte_base))   
    
    saida = io.BytesIO()
    imagem.save(saida, format="PNG", optimize=True)
    return saida.getvalue()

def _shot_playwright(html: str, largura: int, escala: float) -> bytes:
    """Screenshot via Playwright (chromium próprio, por CDP). Renderiza OFFSCREEN e captura via DevTools —
    funciona num processo SEM console/janela (agente Hidden/VBS/service), onde o `chrome.exe --screenshot`
    sai rc=0 sem PNG. full_page corta na altura do conteúdo sozinho (não precisa do _cortar)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--disable-gpu", "--no-sandbox"])
        try:
            page = browser.new_page(viewport={"width": largura, "height": 1024}, device_scale_factor=escala)
            page.set_content(html, wait_until="load")
            page.wait_for_timeout(500)                   # deixa o KaTeX/layout assentar antes do print
            return page.screenshot(full_page=True, type="png")
        finally:
            browser.close()


def _shot_sync(html: str, largura: int, escala: float) -> bytes:
    """Playwright (CDP) primeiro — funciona SEM console/janela. Fallback: chrome.exe --screenshot (só
    funciona em contexto COM console, ex.: dev local). Chamado via to_thread (sync em thread evita o
    ProactorEventLoop do Windows). É ~1x por tool call, então uma thread curta é de boa."""
    try:
        return _shot_playwright(html, largura, escala)
    except ImportError:
        pass                                             # playwright não instalado -> tenta o chrome CLI
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:
        origem = Path(tmp) / "p.html"
        origem.write_text(html, encoding="utf-8")
        destino = Path(tmp) / "p.png"
        perfil = Path(tmp) / "ud"                       # user-data-dir PRÓPRIO: sem isso, se já há um Chrome
        try:                                            # aberto (ex.: open_file mostrando páginas), o headless
            # --headless=old (NAO =new): o 'new' nao gera o PNG quando o processo roda SEM console/desktop
            # (agente Hidden/service -> rc=0 sem arquivo). O 'old' renderiza nesse contexto. Ver pesquisa/diag.
            resultado = subprocess.run(
                [_chrome(), "--headless=old", "--disable-gpu", "--no-sandbox",
                 f"--user-data-dir={perfil}", "--no-first-run", "--no-default-browser-check",
                 "--hide-scrollbars", f"--force-device-scale-factor={escala}",
                 f"--window-size={largura},{_ALTURA_MAX}", f"--virtual-time-budget={_ESPERA_KATEX_MS}",
                 "--run-all-compositor-stages-before-draw",   # garante o paint antes do print (timed content/KaTeX)
                 f"--screenshot={destino}", origem.as_uri()],
                capture_output=True,
                timeout=_TIMEOUT_S
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("chrome travou ao gerar o PNG")
        if not destino.exists():
            err = resultado.stderr.decode(errors="replace").strip()[:_ERR_TRUNC]
            out = resultado.stdout.decode(errors="replace").strip()[:_ERR_TRUNC]
            raise RuntimeError(
                f"chrome não gerou o PNG (rc={resultado.returncode}; bin={_chrome()}; "
                f"stderr={err or '∅'}; stdout={out or '∅'})")
        return _cortar(destino.read_bytes())

async def html_para_png(html: str, largura: int = _LARGURA_PADRAO, escala: float = _ESCALA_PADRAO) -> bytes:
    return await asyncio.to_thread(_shot_sync, html, largura, escala)
    