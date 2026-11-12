# core/datas.py — parse de datas/períodos falados → timestamp. Utilitário genérico (sem dependência do cérebro).
# Realocado daqui quando o cérebro foi removido (feat/cerebro); get_location usa quando_de/desde_de.
import datetime as dt
import re
import unicodedata


def norm(s: str) -> str:
    """Forma canônica: minúsculo, sem acento, espaços colapsados."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def quando_de(texto: str | None, agora: dt.datetime | None = None) -> float:
    """Data falada → timestamp. Aceita: vazio (agora) · hoje/ontem/anteontem [HH:MM] · DD/MM [HH:MM] ·
    AAAA-MM-DD [HH:MM] · HH:MM. Sem hora → meio-dia (não cai no dia errado por fuso). Inválido → ValueError."""
    agora = agora or dt.datetime.now()
    t = norm(texto or "")
    if not t or t == "agora":
        return agora.timestamp()
    hora = re.search(r"(\d{1,2})[:h](\d{2})?", t.split()[-1]) if " " in t or ":" in t or t.endswith("h") else None
    hh, mm = (int(hora.group(1)), int(hora.group(2) or 0)) if hora else (12, 0)
    base = t.split()[0] if " " in t else t
    rel = {"hoje": 0, "ontem": 1, "anteontem": 2}
    if base in rel:
        d = (agora - dt.timedelta(days=rel[base])).date()
    elif m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", base):
        d = dt.date(int(m[1]), int(m[2]), int(m[3]))
    elif m := re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", base):
        ano = int(m[3]) + (2000 if m[3] and len(m[3]) == 2 else 0) if m[3] else agora.year
        d = dt.date(ano, int(m[2]), int(m[1]))
    elif hora and base == t.split()[-1]:          # só "18:40" → hoje
        d = agora.date()
    else:
        raise ValueError(f"não entendi a data '{texto}' (use hoje/ontem, DD/MM ou AAAA-MM-DD, com HH:MM opcional)")
    return dt.datetime(d.year, d.month, d.day, hh, mm).timestamp()


def desde_de(texto: str | None, agora: dt.datetime | None = None) -> float | None:
    """Período falado → início. hoje · semana (7 dias) · mes (desde o dia 1) · ano · ou uma data (quando_de)."""
    agora = agora or dt.datetime.now()
    t = norm(texto or "")
    if not t:
        return None
    zero = agora.replace(hour=0, minute=0, second=0, microsecond=0)
    if t == "hoje":
        return zero.timestamp()
    if t in ("semana", "esta semana", "ultima semana", "7 dias"):
        return (zero - dt.timedelta(days=6)).timestamp()
    if t in ("mes", "este mes", "esse mes"):
        return zero.replace(day=1).timestamp()
    if t in ("ultimo mes", "30 dias"):
        return (zero - dt.timedelta(days=29)).timestamp()
    if t in ("ano", "este ano"):
        return zero.replace(month=1, day=1).timestamp()
    return dt.datetime.fromtimestamp(quando_de(t, agora)).replace(hour=0, minute=0).timestamp()
