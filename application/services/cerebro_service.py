# application/services/cerebro_service.py — regras do cérebro (o store só guarda; aqui se decide o que entra
# no contexto, como o modelo se refere às coisas e como a busca é feita).
#
# 3 usos:
#   lembrar()        → tool `remember`: grava observação (+ relação opcional) e devolve uma linha curta pro modelo.
#   recordar()       → tool `recall`: busca por palavras OU tudo de uma entidade (com histórico se pedir).
#   render_compact() → bloco injetado em TODO turno: NÚCLEO (tudo sobre o dono) + o que a fala atual puxa.
#   registrar() / consultar() → (M2) tools `log` / `query_log`: o que ACONTECEU, com data e números.
import datetime as dt
import math
import re
import time

from domain.contracts import CerebroStore
from domain.entities.cerebro import DONO, Observacao, Registro, norm

# o modelo chama o dono de vários jeitos — todos são a mesma entidade
_ALIAS_DONO = {"voce", "eu", "dono", "o dono", "usuario", "o usuario", "mim", "meu", "minha"}

_STOP = set("""
a o as os um uma uns umas de do da dos das no na nos nas em por para pra pro com sem sob sobre ao aos e ou mas
que se nao sim ja la aqui isso isto esse essa este esta aquele aquela eu voce voces ele ela eles elas me te
lhe nos meu minha seu sua teu tua qual quais quando onde como porque pq quem muito mais menos bem tambem
ser estar ter fazer foi era sou esta estou tem tinha vai vou fiz fez faz pode posso quero queria agora hoje
ontem ainda so ate entao tipo coisa coisas cara gente ai la sobre ultimo ultima lembra lembrar sabe
oi ola bom boa dia tarde noite tudo obrigado valeu beleza blz certo ok
""".split())

_DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
_SESSAO_MAX_H = 6            # sessão aberta há mais que isso = esquecida aberta, não "em andamento"
# tipo de registro → tipo da entidade-assunto quando ela ainda não existe (série é de um exercício, etc.)
_ASSUNTO_TIPO = {"serie": "exercicio", "treino": "grupo muscular", "estudo": "disciplina"}

_NUCLEO_MAX_CHARS = 1600     # ≈ 400 tokens: o núcleo vai em TODO turno, tem que ser pequeno
_RELEVANTES = 6              # observações puxadas pela fala atual (além do núcleo)


def termos(texto: str, maximo: int = 12) -> list[str]:
    """Palavras que valem busca: sem acento, ≥3 letras, sem stopword, sem repetir."""
    vistos: list[str] = []
    for p in re.findall(r"\w+", norm(texto)):
        if len(p) >= 3 and p not in _STOP and not p.isdigit() and p not in vistos:
            vistos.append(p)
    return vistos[:maximo]


def _quando(ts: float) -> str:
    return time.strftime("%d/%m/%y", time.localtime(ts))


def _linha(o: Observacao, *, com_entidade: bool = False, com_data: bool = False) -> str:
    ent = f"{o.entidade} ({o.tipo}) " if com_entidade else ""
    data = f" · {_quando(o.valido_desde)}" if com_data else ""
    antiga = f" [até {_quando(o.invalido_em)}]" if o.invalido_em else ""
    return f"- {ent}#{o.id} [{o.categoria}] {o.texto}{data}{antiga}"


def _dia(ts: float) -> str:
    d = dt.datetime.fromtimestamp(ts)
    return f"{_DIAS[d.weekday()]} {d:%d/%m}"


def _hora(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%H:%M")


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


def fmt_dados(d: dict) -> str:
    """Números de um registro em fala curta: {series:3, reps:12, carga_kg:20} → '3×12 · 20 kg'."""
    partes, resto = [], dict(d)
    s, r = resto.pop("series", None), resto.pop("reps", None)
    if s is not None and r is not None:
        partes.append(f"{s}×{r}")
    elif r is not None:
        partes.append(f"{r} reps")
    elif s is not None:
        partes.append(f"{s} séries")
    for chave, unidade in (("carga_kg", "kg"), ("peso_kg", "kg"), ("duracao_min", "min"), ("distancia_km", "km")):
        if chave in resto:
            partes.append(f"{resto.pop(chave)} {unidade}")
    partes += [f"{k}: {v}" for k, v in resto.items()]
    return " · ".join(str(p) for p in partes)


def _reg_linha(r: Registro, *, com_dia: bool = True, recuo: str = "- ") -> str:
    quando = f"{_dia(r.quando)} {_hora(r.quando)}" if com_dia else _hora(r.quando)
    if r.eh_sessao:
        if r.fim:
            quando += f"–{_hora(r.fim)}"
        elif time.time() - r.quando < _SESSAO_MAX_H * 3600:     # aberta há muito = esqueceram de fechar
            quando += " (em andamento)"
    partes = [quando, r.tipo] + ([r.entidade] if r.entidade else []) + ([fmt_dados(r.dados)] if r.dados else [])
    texto = f' · "{r.texto}"' if r.texto else ""
    return f"{recuo}{' · '.join(partes)}{texto} (#{r.id})"


class CerebroService:
    def __init__(self, store: CerebroStore) -> None:
        self._store = store
        self._cache: dict[str, str] = {}

    @staticmethod
    def nome_entidade(nome: str | None) -> str:
        """'você'/'eu'/vazio → a entidade do dono. Qualquer outro nome fica como veio."""
        n = (nome or "").strip()
        return DONO if not n or norm(n) in _ALIAS_DONO else n

    # ── escrita (tool remember) ────────────────────────────────────────────────────────────────────────
    async def lembrar(self, texto: str, categoria: str, entidade: str | None = None, tipo: str | None = None,
                      substitui: int | None = None, relacao: str | None = None, com: str | None = None,
                      fonte: str = "") -> str:
        ent = await self._store.entidade(self.nome_entidade(entidade), tipo)
        try:
            obs, op = await self._store.observar(ent.id, categoria, texto, substitui=substitui, fonte=fonte)
        except ValueError as e:
            atuais = await self._store.da_entidade(ent.id)
            lista = "\n".join(_linha(o) for o in atuais[-10:]) or "(nenhuma)"
            return (f"[erro] {e} — nada foi gravado. Observações válidas de '{ent.nome}':\n{lista}\n"
                    f"Use um desses #id em substitui, ou omita substitui se é algo novo.")
        self._cache.clear()
        msg = {"ADD": "gravado", "NOOP": "já estava gravado (igual)",
               "CORRIGE": f"corrigido (a #{substitui} ficou no histórico)"}[op]
        saida = f"[memória] {msg}: {ent.nome} #{obs.id} [{obs.categoria}] {obs.texto}"
        if op == "ADD":
            parecidas = await self._parecidas(obs)
            if parecidas:
                saida += ("\nATENÇÃO, já existia parecido:\n" + "\n".join(_linha(o) for o in parecidas)
                          + f"\nSe a nova SUBSTITUI uma delas (o dono mudou de ideia/corrigiu), chame "
                            f"remember(texto=<o mesmo>, categoria={obs.categoria}, substitui=<#id da antiga>). "
                            f"Se são coisas diferentes, não faça nada.")
        if relacao and com:
            alvo = await self._store.entidade(self.nome_entidade(com))
            r = await self._store.relacionar(ent.id, relacao, alvo.id)
            saida += f" · ligação {ent.nome} —{norm(relacao)}→ {alvo.nome}" + (" (já existia)" if r == "NOOP" else "")
        return saida

    async def _parecidas(self, nova: Observacao) -> list[Observacao]:
        """Observações válidas da MESMA entidade que talvez digam a mesma coisa: mesma categoria ou ≥2 palavras
        em comum. Determinístico e barato; quem decide se substitui é o modelo (ele sabe o que o dono disse)."""
        t_nova = set(termos(nova.texto, 30))
        out = []
        for o in await self._store.da_entidade(nova.entidade_id):
            if o.id == nova.id:
                continue
            if o.categoria == nova.categoria or len(t_nova & set(termos(o.texto, 30))) >= 2:
                out.append(o)
        return out[-5:]

    # ── leitura (tool recall) ──────────────────────────────────────────────────────────────────────────
    async def recordar(self, busca: str | None = None, entidade: str | None = None,
                       incluir_antigas: bool = False) -> str:
        if entidade:
            ent = await self._store.achar_entidade(self.nome_entidade(entidade))
            if ent is None:
                return f"[memória] não sei nada sobre '{entidade}' (nenhuma entidade com esse nome)."
            obs = await self._store.da_entidade(ent.id, incluir_antigas=incluir_antigas)
            rels = await self._store.relacoes(ent.id)
            linhas = [f"[memória] {ent.nome} ({ent.tipo} · {ent.area}):"]
            for o in obs:
                linhas.append(_linha(o, com_data=True))
                if not incluir_antigas:                  # com incluir_antigas as velhas já estão na lista
                    linhas += await self._antes(o)
            if not obs:
                linhas.append("- (sem observações)")
            linhas += [f"- ligação: {r.de} —{r.tipo}→ {r.para}" for r in rels]
            regs = await self._store.registros(entidade_id=ent.id, limite=5)
            if regs:
                linhas.append("Registros recentes:")
                linhas += [_reg_linha(r) for r in regs]
            return "\n".join(linhas)
        achadas = await self._ranquear(busca or "", limite=10)
        if not achadas:
            return f"[memória] nada encontrado sobre '{busca}'."
        linhas = ["[memória] encontrado:"]
        for o in achadas:
            linhas.append(_linha(o, com_entidade=True, com_data=True))
            linhas += await self._antes(o)
        return "\n".join(linhas)

    async def _antes(self, o: Observacao, maximo: int = 3) -> list[str]:
        """A cadeia de versões anteriores (o que esta observação corrigiu) — responde "o que mudou?" sem
        o modelo precisar saber pedir incluir_antigas."""
        out, sid = [], o.substitui
        while sid is not None and len(out) < maximo:
            velha = await self._store.observacao(sid)
            if velha is None:
                break
            out.append(f"    antes: #{velha.id} {velha.texto} [{_quando(velha.valido_desde)} até "
                       f"{_quando(velha.invalido_em or velha.valido_desde)}]")
            sid = velha.substitui
        return out

    async def _ranquear(self, texto: str, limite: int, excluir: set[int] | None = None) -> list[Observacao]:
        """BM25 decide a ordem de relevância; a recência desempata (meia-vida ~3 semanas)."""
        pool = [o for o in await self._store.buscar(termos(texto)) if not excluir or o.id not in excluir]
        if not pool:
            return []
        agora = time.time()
        n = len(pool)

        def score(i_o: tuple[int, Observacao]) -> float:
            i, o = i_o
            relevancia = 1 - i / n
            recencia = math.exp(-(agora - o.valido_desde) / (30 * 86400))
            return 0.7 * relevancia + 0.3 * recencia

        return [o for _, o in sorted(enumerate(pool), key=score, reverse=True)[:limite]]

    # ── registros (tools log / query_log) ──────────────────────────────────────────────────────────────
    async def _sessao_aberta(self) -> Registro | None:
        return await self._store.sessao_aberta(time.time() - _SESSAO_MAX_H * 3600)

    async def registrar(self, acao: str = "registrar", tipo: str | None = None, assunto: str | None = None,
                        dados: dict | None = None, texto: str = "", quando: str | None = None,
                        corrige: int | None = None, fonte: str = "") -> str:
        """acao: abrir (começa a sessão: "vou começar o treino de peito") · registrar (um evento; entra na sessão
        aberta, se houver) · fechar (termina a sessão aberta e resume)."""
        acao = norm(acao or "registrar")
        try:
            ts = quando_de(quando)
        except ValueError as e:
            return f"[erro] {e} — nada foi registrado."
        aberta = await self._sessao_aberta()

        if acao == "fechar":
            if aberta is None:
                return "[registro] não há sessão em andamento pra fechar."
            await self._store.fechar_sessao(aberta.id, ts)
            filhos = await self._store.registros(sessao=aberta.id)
            self._cache.clear()
            return (f"[registro] sessão fechada: {aberta.tipo} · {aberta.entidade or ''} · {_hora(aberta.quando)}–"
                    f"{_hora(ts)} · {len(filhos)} registro(s): "
                    + ("; ".join(f"{r.entidade} {fmt_dados(r.dados)}".strip() for r in reversed(filhos)) or "nenhum"))

        if not tipo:
            return "[erro] falta o tipo (ex.: treino, serie, estudo) — nada foi registrado."
        ent = None
        if assunto:
            ent = await self._store.entidade(self.nome_entidade(assunto), _ASSUNTO_TIPO.get(norm(tipo)))
        aviso = ""
        if acao == "abrir":
            if aberta is not None:                       # abriu outra sem fechar: fecha a anterior agora
                await self._store.fechar_sessao(aberta.id, ts)
                aviso = f" (fechei a anterior: {aberta.tipo} {aberta.entidade or ''} de {_hora(aberta.quando)})"
            sessao, eh_sessao = None, True
        else:
            sessao, eh_sessao = (aberta.id if aberta else None), False
        try:
            reg = await self._store.registrar(tipo, ts, entidade_id=ent.id if ent else None, dados=dados or {},
                                              texto=texto, sessao=sessao, eh_sessao=eh_sessao, substitui=corrige,
                                              fonte=fonte)
        except ValueError as e:
            return f"[erro] {e} — nada foi registrado."
        self._cache.clear()
        verbo = "sessão aberta" if eh_sessao else ("corrigido" if corrige else "registrado")
        dentro = f" · dentro de {aberta.tipo} {aberta.entidade or ''} (#{aberta.id})" if sessao and aberta else ""
        return f"[registro] {verbo}: {_reg_linha(reg, recuo='')}{dentro}{aviso}"

    async def consultar(self, tipo: str | None = None, assunto: str | None = None, ultimo: bool = False,
                        desde: str | None = None, ate: str | None = None, limite: int = 20) -> str:
        """ultimo=True → só a ocorrência mais recente (o treino inteiro, ou todas as séries daquele exercício
        naquele dia). Senão, a lista do período, mais recente primeiro. Sessões vêm com o que houve dentro."""
        try:
            ini, fim = desde_de(desde), (quando_de(ate) if ate else None)
        except ValueError as e:
            return f"[erro] {e}"
        ent_id = None
        if assunto:
            ent = await self._store.achar_entidade(self.nome_entidade(assunto))
            if ent is None:
                return f"[registro] nenhum registro de '{assunto}'."
            ent_id = ent.id
        regs = await self._store.registros(tipo=tipo, entidade_id=ent_id, desde=ini, ate=fim, limite=200)
        if not regs:
            filtro = " · ".join(x for x in (tipo, assunto, desde) if x)
            return f"[registro] nada registrado ({filtro or 'nenhum filtro'})."
        if ultimo:
            r0 = regs[0]
            if r0.sessao is not None:                    # "última vez no supino" = todas as séries daquele treino
                regs = [r for r in regs if r.sessao == r0.sessao]
            else:
                regs = [r for r in regs if _dia(r.quando) == _dia(r0.quando) and r.eh_sessao == r0.eh_sessao]
        linhas = ["[registro]"]
        for r in regs[:limite]:
            linhas.append(_reg_linha(r))
            if r.eh_sessao:
                filhos = await self._store.registros(sessao=r.id)
                linhas += [_reg_linha(f, com_dia=False, recuo="    · ") for f in reversed(filhos)]
        if len(regs) > limite:
            linhas.append(f"(+{len(regs) - limite} mais antigos)")
        return "\n".join(linhas)

    # ── contexto (todo turno) ──────────────────────────────────────────────────────────────────────────
    async def render_compact(self, query: str | None = None) -> str:
        """Agora + sessão em andamento (mudam com o relógio, fora do cache) + núcleo e relevantes (em cache)."""
        agora = time.time()
        topo = [f"Agora: {_dia(agora)} {_hora(agora)}"]
        aberta = await self._sessao_aberta()
        if aberta:
            filhos = await self._store.registros(sessao=aberta.id)
            feitos = ", ".join(dict.fromkeys(r.entidade for r in reversed(filhos) if r.entidade))
            topo.append(f"Em andamento: {aberta.tipo} {aberta.entidade or ''} desde {_hora(aberta.quando)} (#{aberta.id})"
                        f" · {len(filhos)} registro(s)" + (f": {feitos}" if feitos else "")
                        + " — cada exercício que ele contar → chame log(tipo=serie, ...)")
        memoria = await self._memoria(query or "")
        return "\n".join(topo) + ("\n" + memoria if memoria else "")

    async def _memoria(self, chave: str) -> str:
        if chave in self._cache:
            return self._cache[chave]
        dono = await self._store.entidade(DONO)
        nucleo = await self._store.da_entidade(dono.id)
        linhas_nucleo: list[str] = []
        total = 0
        for o in sorted(nucleo, key=lambda o: o.valido_desde, reverse=True):   # estoura o teto → cai o mais velho
            ln = _linha(o)
            if total + len(ln) > _NUCLEO_MAX_CHARS:
                break
            linhas_nucleo.append(ln)
            total += len(ln)
        linhas_nucleo.reverse()
        relevantes = await self._ranquear(chave, _RELEVANTES, excluir={o.id for o in nucleo}) if chave else []

        partes: list[str] = []
        if linhas_nucleo:
            partes.append("Sobre o dono:\n" + "\n".join(linhas_nucleo))
        if relevantes:
            partes.append("Relacionado ao pedido:\n" + "\n".join(_linha(o, com_entidade=True) for o in relevantes))
        bloco = ""
        if partes:
            bloco = ("MEMÓRIA (o que você já sabe; #n = id da observação — pra CORRIGIR uma, "
                     "remember(substitui=n)):\n" + "\n\n".join(partes))
        if len(self._cache) > 64:                 # cada fala é uma chave; não deixa crescer sem fim
            self._cache.clear()
        self._cache[chave] = bloco
        return bloco
