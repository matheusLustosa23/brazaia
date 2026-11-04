# application/services/cerebro_service.py — regras do cérebro (o store só guarda; aqui se decide o que entra
# no contexto, como o modelo se refere às coisas e como a busca é feita).
#
# 3 usos:
#   lembrar()        → tool `remember`: grava observação (+ relação opcional) e devolve uma linha curta pro modelo.
#   recordar()       → tool `recall`: busca por palavras OU tudo de uma entidade (com histórico se pedir).
#   render_compact() → bloco injetado em TODO turno: NÚCLEO (tudo sobre o dono) + o que a fala atual puxa.
import math
import re
import time

from domain.contracts import CerebroStore
from domain.entities.cerebro import DONO, Observacao, norm

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

    # ── contexto (todo turno) ──────────────────────────────────────────────────────────────────────────
    async def render_compact(self, query: str | None = None) -> str:
        chave = query or ""
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
