import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt, io, base64


def render_math(content: str, title: str | None = None) -> str:
    """LaTeX/texto (linhas separadas por \\n) → PNG data URI. mathtext cobre \\frac \\sqrt \\lim \\int \\sum ^_ grego."""
    linhas = content.split("\n")
    fig = plt.figure(figsize=(7, 0.9 + 0.7*len(linhas))); fig.patch.set_facecolor("white")
    y = 0.9
    if title:
        fig.text(0.5, y, title, fontsize=18, ha="center", weight="bold"); y -= 0.18
    for ln in linhas:
        fig.text(0.06, y, f"${ln}$", fontsize=18, va="center"); y -= 0.7/(0.9+0.7*len(linhas))
    buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()