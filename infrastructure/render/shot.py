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

def _shot_sync(html: str, largura: int, escala: float) -> bytes:
    """chrome headless SÍNCRONO (subprocess.run) — chamado via to_thread.

    Por que sync-em-thread e NÃO asyncio.create_subprocess_exec: no Windows o
    create_subprocess_exec exige o ProactorEventLoop; se o uvicorn subir a API
    com outro loop, levanta NotImplementedError. subprocess.run funciona em
    QUALQUER SO/loop, e o to_thread mantém o event loop livre. É render
    server-side (~1x por tool call), então uma thread curta é de boa.
    """
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:
        origem = Path(tmp) / "p.html"
        origem.write_text(html, encoding="utf-8")
        destino = Path(tmp) / "p.png"
        try:
            resultado = subprocess.run(
                [_chrome(), "--headless=new", "--disable-gpu", "--no-sandbox",
                 "--hide-scrollbars", f"--force-device-scale-factor={escala}",
                 f"--window-size={largura},{_ALTURA_MAX}", f"--virtual-time-budget={_ESPERA_KATEX_MS}",
                 f"--screenshot={destino}", origem.as_uri()],
                capture_output=True,
                timeout=_TIMEOUT_S
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("chrome travou ao gerar o PNG")
        if not destino.exists():
            erro = resultado.stderr.decode(errors="replace")[:_ERR_TRUNC]
            raise RuntimeError(f"chrome não gerou o PNG: {erro}")
        return _cortar(destino.read_bytes())

async def html_para_png(html: str, largura: int = _LARGURA_PADRAO, escala: float = _ESCALA_PADRAO) -> bytes:
    return await asyncio.to_thread(_shot_sync, html, largura, escala)
    