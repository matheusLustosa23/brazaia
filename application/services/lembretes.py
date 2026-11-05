"""Lembretes que AVISAM: o dono pede ("me lembra da conta de luz todo dia 10, 2 dias antes"), o agente grava
com a tool remind e um agendador no servidor manda notify pros devices na hora certa.

Regras de tempo (tudo em horário local do servidor):
- `proximo` = quando a coisa VENCE/ACONTECE; o aviso sai em `proximo - antecedencia`.
- `avisado_para` = o `proximo` que já foi avisado — evita avisar duas vezes o mesmo vencimento.
- Recorrente: depois que vence, `proximo` anda pra próxima ocorrência (mensal guarda o DIA original:
  31 → 30/fev 28 → volta a 31, sem "escorregar").
- Nenhum device online na hora → tenta de novo a cada ciclo, até 24 h depois do vencimento.
"""
from __future__ import annotations

import asyncio
import calendar
import datetime as dt
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from domain.entities.cerebro import norm

logger = logging.getLogger(__name__)

REPETICOES = ("", "diaria", "semanal", "mensal", "anual")
_DIAS_SEMANA = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]
_DIA_ABREV = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
_HORA_PADRAO = (9, 0)                       # data sem hora → 09:00 (lembrete às 12h do cérebro não serve aqui)
_TOLERANCIA_S = 24 * 3600                   # vencimento perdido (servidor/devices fora): ainda avisa até 24 h depois


@dataclass(slots=True)
class Lembrete:
    id: int
    texto: str
    proximo: float
    repetir: str = ""
    antecedencia_min: int = 0
    dia: int | None = None                  # mensal/anual: o dia do mês original
    ativo: bool = True
    avisado_para: float | None = None

    @property
    def aviso_em(self) -> float:
        return self.proximo - self.antecedencia_min * 60


# ── datas ───────────────────────────────────────────────────────────────────────────────────────────────
def _hora(t: str) -> tuple[int, int] | None:
    m = re.search(r"\b(\d{1,2})(?::(\d{2})|h(\d{2})?)\b", t)
    if not m:
        return None
    hh, mm = int(m[1]), int(m[2] or m[3] or 0)
    if hh > 23 or mm > 59:
        raise ValueError(f"hora inválida em '{t}'")
    return hh, mm


def quando_futuro(texto: str, agora: dt.datetime | None = None) -> dt.datetime:
    """Quando algo VAI acontecer. Aceita: AAAA-MM-DD [HH:MM] · DD/MM[/AAAA] [HH:MM] · hoje/amanhã/depois de amanhã
    [HH:MM] · dia N [HH:MM] · segunda..domingo [HH:MM] · em N min/horas/dias · HH:MM. Sem hora → 09:00.
    Sempre devolve o PRÓXIMO momento futuro (dia 10 já passou este mês → dia 10 do mês que vem)."""
    agora = (agora or dt.datetime.now()).replace(second=0, microsecond=0)
    t = norm(texto or "")
    if not t:
        raise ValueError("falta a data/hora do lembrete")
    if m := re.search(r"\bem (\d+) ?(min|minuto|minutos|h|hora|horas|dia|dias)\b", t):
        n, u = int(m[1]), m[2]
        delta = dt.timedelta(minutes=n) if u.startswith("min") else (
            dt.timedelta(hours=n) if u.startswith("h") else dt.timedelta(days=n))
        return agora + delta
    hm = _hora(t)
    hh, mm = hm or _HORA_PADRAO

    def _no(d: dt.date) -> dt.datetime:
        return dt.datetime(d.year, d.month, d.day, hh, mm)

    if m := re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t):
        return _no(dt.date(int(m[1]), int(m[2]), int(m[3])))
    if m := re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t):
        ano = (int(m[3]) + (2000 if len(m[3]) == 2 else 0)) if m[3] else agora.year
        alvo = _no(dt.date(ano, int(m[2]), int(m[1])))
        return alvo if m[3] or alvo > agora else _no(dt.date(ano + 1, int(m[2]), int(m[1])))
    if "depois de amanha" in t:
        return _no(agora.date() + dt.timedelta(days=2))
    if "amanha" in t:
        return _no(agora.date() + dt.timedelta(days=1))
    if re.search(r"\bhoje\b", t):
        return _no(agora.date())
    if m := re.search(r"\bdia (\d{1,2})\b", t):
        return proxima_mensal(int(m[1]), hh, mm, depois_de=agora)
    for i, nome in enumerate(_DIAS_SEMANA):
        if re.search(rf"\b{nome}\b", t):
            dias = (i - agora.weekday()) % 7
            alvo = _no(agora.date() + dt.timedelta(days=dias))
            return alvo if alvo > agora else alvo + dt.timedelta(days=7)
    if hm:                                               # só "18:30" → hoje, ou amanhã se já passou
        alvo = _no(agora.date())
        return alvo if alvo > agora else alvo + dt.timedelta(days=1)
    raise ValueError(f"não entendi quando é '{texto}' (ex.: 'amanhã 9h', 'dia 10', 'sexta 18:00', '25/12', 'em 2 horas')")


def antecedencia_de(texto: str | None) -> int:
    """'2 dias' / '1 hora' / '30 min' / '' → minutos."""
    t = norm(texto or "")
    if not t or t in ("0", "na hora", "nenhuma"):
        return 0
    m = re.fullmatch(r"(\d+) ?(min|minuto|minutos|h|hora|horas|dia|dias|semana|semanas)( antes)?", t)
    if not m:
        raise ValueError(f"não entendi a antecedência '{texto}' (ex.: '2 dias', '1 hora', '30 min')")
    n, u = int(m[1]), m[2]
    return n * (1 if u.startswith("min") else 60 if u.startswith("h") else 1440 if u.startswith("dia") else 10080)


def proxima_mensal(dia: int, hh: int, mm: int, depois_de: dt.datetime) -> dt.datetime:
    """O próximo 'dia N' depois de `depois_de` (mês curto → último dia dele)."""
    ano, mes = depois_de.year, depois_de.month
    for _ in range(3):
        d = min(dia, calendar.monthrange(ano, mes)[1])
        alvo = dt.datetime(ano, mes, d, hh, mm)
        if alvo > depois_de:
            return alvo
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    raise AssertionError("inalcançável")


def proxima_ocorrencia(l: Lembrete, depois_de: float) -> float:
    """Anda o vencimento de um recorrente até ficar depois de `depois_de`."""
    base = dt.datetime.fromtimestamp(l.proximo)
    lim = dt.datetime.fromtimestamp(depois_de)
    if l.repetir == "mensal":
        return proxima_mensal(l.dia or base.day, base.hour, base.minute, max(base, lim)).timestamp()
    passo = {"diaria": dt.timedelta(days=1), "semanal": dt.timedelta(days=7)}.get(l.repetir)
    if l.repetir == "anual":
        alvo = base
        while alvo <= lim:
            ano = alvo.year + 1
            alvo = alvo.replace(year=ano, day=min(l.dia or base.day, calendar.monthrange(ano, base.month)[1]))
        return alvo.timestamp()
    if passo is None:
        return l.proximo
    alvo = base
    while alvo <= lim:
        alvo += passo
    return alvo.timestamp()


def fmt_quando(ts: float) -> str:
    d = dt.datetime.fromtimestamp(ts)
    return f"{_DIA_ABREV[d.weekday()]} {d:%d/%m/%Y} às {d:%H:%M}"


def fmt_antes(minutos: int) -> str:
    if not minutos:
        return "na hora"
    for n, nome in ((10080, "semana"), (1440, "dia"), (60, "hora")):
        if minutos % n == 0:
            q = minutos // n
            return f"{q} {nome}{'s' if q > 1 else ''} antes"
    return f"{minutos} min antes"


def fmt_lembrete(l: Lembrete) -> str:
    rep = {"diaria": "todo dia", "semanal": "toda semana", "mensal": f"todo mês (dia {l.dia})",
           "anual": "todo ano"}.get(l.repetir, "uma vez")
    return f"#{l.id} {l.texto} — {fmt_quando(l.proximo)} · {rep} · aviso {fmt_antes(l.antecedencia_min)}"


# ── agendador ───────────────────────────────────────────────────────────────────────────────────────────
Enviar = Callable[[str, str], Awaitable[bool]]


async def ciclo(store, enviar: Enviar, agora: float | None = None) -> list[int]:
    """UMA passada: avisa o que está na hora, anda recorrentes vencidos, desativa únicos vencidos.
    Devolve os ids avisados (pros testes e pro log)."""
    agora = agora or time.time()
    avisados: list[int] = []
    for l in await store.ativos():
        ja_avisado = l.avisado_para is not None and l.avisado_para >= l.proximo
        if not ja_avisado and l.aviso_em <= agora and agora <= l.proximo + _TOLERANCIA_S:
            quando = ("agora" if abs(l.proximo - agora) < 120 else
                      f"vence {fmt_quando(l.proximo)}" if l.proximo > agora else f"era {fmt_quando(l.proximo)}")
            if await enviar(f"🔔 {l.texto}", quando):
                await store.marcar_avisado(l.id, l.proximo)
                avisados.append(l.id)
                ja_avisado = True
        if l.proximo <= agora and (ja_avisado or agora > l.proximo + _TOLERANCIA_S):
            if l.repetir:
                await store.mover(l.id, proxima_ocorrencia(l, agora))
            else:
                await store.desativar(l.id)
    return avisados


async def agendador(store, enviar: Enviar, intervalo_s: float = 30) -> None:
    """Loop de fundo (lifespan). Erro numa passada não mata o loop."""
    while True:
        try:
            ids = await ciclo(store, enviar)
            if ids:
                logger.info("lembretes avisados: %s", ids)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ciclo de lembretes falhou")
        await asyncio.sleep(intervalo_s)
