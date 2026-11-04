# infrastructure/memory/cerebro_store.py — o cérebro em SQLite (data/cerebro.db).
#
# Tabelas:
#   tipos        nome normalizado + área (voce/academia/estudos/trabalho/...). Aberta: tipo novo entra com área 'geral'
#                e o painel (M3) reclassifica. Normalizar evita 'preferência' × 'preferencias' × 'Preferencias'.
#   entidades    UMA linha por nome (nome_norm UNIQUE) — o modelo se refere às coisas pelo nome.
#   observacoes  frases sobre uma entidade. Nunca DELETE: corrigir = invalido_em na velha + nova com `substitui`.
#   relacoes     ligações entidade→entidade.
#   obs_fts      índice de busca (FTS5) sobre texto + categoria + nome da entidade, sem acento.
import time
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

import aiosqlite

from domain.entities.cerebro import DONO, TIPO_DONO, Entidade, Observacao, Relacao, norm

_SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS tipos (
    nome      TEXT PRIMARY KEY,
    area      TEXT NOT NULL DEFAULT 'geral',
    criado_em REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS entidades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo          TEXT NOT NULL REFERENCES tipos(nome),
    nome          TEXT NOT NULL,
    nome_norm     TEXT NOT NULL UNIQUE,
    criado_em     REAL NOT NULL,
    atualizado_em REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS observacoes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    entidade_id  INTEGER NOT NULL REFERENCES entidades(id),
    categoria    TEXT    NOT NULL,
    texto        TEXT    NOT NULL,
    texto_norm   TEXT    NOT NULL,
    fonte        TEXT    NOT NULL DEFAULT '',
    valido_desde REAL    NOT NULL,
    invalido_em  REAL,
    substitui    INTEGER REFERENCES observacoes(id)
);
CREATE INDEX IF NOT EXISTS ix_obs_ent ON observacoes(entidade_id, invalido_em);

CREATE TABLE IF NOT EXISTS relacoes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    de_id       INTEGER NOT NULL REFERENCES entidades(id),
    tipo        TEXT    NOT NULL,
    para_id     INTEGER NOT NULL REFERENCES entidades(id),
    criado_em   REAL    NOT NULL,
    invalido_em REAL,
    UNIQUE(de_id, tipo, para_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS obs_fts USING fts5(
    texto, categoria, entidade,
    tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS obs_fts_ai AFTER INSERT ON observacoes BEGIN
    INSERT INTO obs_fts(rowid, texto, categoria, entidade)
    VALUES (new.id, new.texto, new.categoria, (SELECT nome FROM entidades WHERE id = new.entidade_id));
END;
"""

# tipos iniciais (área = em qual "frente" do agente a entidade mora). Lista ABERTA: o resto entra como 'geral'.
_TIPOS = {
    TIPO_DONO: "voce", "pessoa": "pessoas", "lugar": "geral", "meta": "geral",
    "exercicio": "academia", "grupo muscular": "academia", "treino": "academia",
    "disciplina": "estudos", "tema": "estudos",
    "projeto": "trabalho", "empresa": "trabalho", "ferramenta": "trabalho", "fluxo": "trabalho",
    "financa": "financas", "geral": "geral",
}

_OBS_SELECT = """SELECT o.id, o.entidade_id, e.nome, e.tipo, o.categoria, o.texto,
                        o.valido_desde, o.invalido_em, o.substitui
                 FROM observacoes o JOIN entidades e ON e.id = o.entidade_id"""


def _obs(r) -> Observacao:
    return Observacao(id=r[0], entidade_id=r[1], entidade=r[2], tipo=r[3], categoria=r[4], texto=r[5],
                      valido_desde=r[6], invalido_em=r[7], substitui=r[8])


class SqliteCerebroStore:
    def __init__(self, db_path: str) -> None:
        self._path = db_path

    @asynccontextmanager
    async def _db(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        async with aiosqlite.connect(self._path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            yield db

    async def init(self) -> None:
        now = time.time()
        async with self._db() as db:
            await db.executescript(_SCHEMA)
            await db.executemany("INSERT OR IGNORE INTO tipos(nome, area, criado_em) VALUES (?,?,?)",
                                 [(t, a, now) for t, a in _TIPOS.items()])
            await db.commit()
        await self.entidade(DONO, TIPO_DONO)              # o dono existe sempre (é o núcleo)

    # ── tipos / entidades ──────────────────────────────────────────────────────────────────────────────
    async def _tipo(self, db: aiosqlite.Connection, tipo: str | None) -> str:
        """Normaliza o tipo e garante que existe. Plural de um tipo conhecido vira o singular ('exercicios')."""
        t = norm(tipo or "geral") or "geral"
        conhecidos = {r[0] for r in await db.execute_fetchall("SELECT nome FROM tipos")}
        if t not in conhecidos and t.endswith("s") and t[:-1] in conhecidos:
            t = t[:-1]
        if t not in conhecidos:
            await db.execute("INSERT INTO tipos(nome, area, criado_em) VALUES (?, 'geral', ?)", (t, time.time()))
        return t

    async def achar_entidade(self, nome: str) -> Entidade | None:
        async with self._db() as db:
            r = await (await db.execute(
                "SELECT e.id, e.tipo, e.nome, t.area FROM entidades e JOIN tipos t ON t.nome = e.tipo"
                " WHERE e.nome_norm = ?", (norm(nome),))).fetchone()
        return Entidade(id=r[0], tipo=r[1], nome=r[2], area=r[3]) if r else None

    async def entidade(self, nome: str, tipo: str | None = None) -> Entidade:
        """Acha pelo nome (sem acento/maiúscula) ou cria. Um nome = uma entidade: o tipo só vale na criação."""
        achada = await self.achar_entidade(nome)
        if achada:
            return achada
        now = time.time()
        async with self._db() as db:
            t = await self._tipo(db, tipo)
            await db.execute("INSERT INTO entidades(tipo, nome, nome_norm, criado_em, atualizado_em)"
                             " VALUES (?,?,?,?,?)", (t, nome.strip(), norm(nome), now, now))
            await db.commit()
        achada = await self.achar_entidade(nome)
        assert achada is not None
        return achada

    # ── observações ────────────────────────────────────────────────────────────────────────────────────
    async def observacao(self, obs_id: int) -> Observacao | None:
        async with self._db() as db:
            r = await (await db.execute(_OBS_SELECT + " WHERE o.id = ?", (obs_id,))).fetchone()
        return _obs(r) if r else None

    async def observar(self, entidade_id: int, categoria: str, texto: str, *, substitui: int | None = None,
                       fonte: str = "") -> tuple[Observacao, str]:
        """Grava uma observação. Retorna (obs, op): op = 'ADD' | 'NOOP' (já sabia, igual) | 'CORRIGE' (substituiu).
        `substitui` precisa ser uma observação VÁLIDA desta mesma entidade — senão ValueError (a tool explica)."""
        now = time.time()
        tnorm = norm(texto)
        cat = norm(categoria).replace(" ", "_") or "geral"
        async with self._db() as db:
            usadas = {r[0] for r in await db.execute_fetchall(
                "SELECT DISTINCT categoria FROM observacoes WHERE entidade_id = ?", (entidade_id,))}
            if cat not in usadas and cat.endswith("s") and cat[:-1] in usadas:
                cat = cat[:-1]
            igual = await (await db.execute(
                "SELECT id FROM observacoes WHERE entidade_id = ? AND texto_norm = ? AND invalido_em IS NULL",
                (entidade_id, tnorm))).fetchone()
            if igual and (substitui is None or substitui == igual[0]):
                obs_id, op = igual[0], "NOOP"
            elif igual:                                   # já gravou a nova e agora diz que ela substitui a velha
                velha = await (await db.execute(
                    "SELECT entidade_id, invalido_em FROM observacoes WHERE id = ?", (substitui,))).fetchone()
                if velha is None or velha[1] is not None or velha[0] != entidade_id:
                    raise ValueError(f"a observação #{substitui} não existe, já foi substituída ou é de outra entidade")
                await db.execute("UPDATE observacoes SET invalido_em = ? WHERE id = ?", (now, substitui))
                await db.execute("UPDATE observacoes SET substitui = ? WHERE id = ?", (substitui, igual[0]))
                obs_id, op = igual[0], "CORRIGE"
            else:
                if substitui is not None:
                    velha = await (await db.execute(
                        "SELECT entidade_id, invalido_em FROM observacoes WHERE id = ?", (substitui,))).fetchone()
                    if velha is None or velha[1] is not None:
                        raise ValueError(f"a observação #{substitui} não existe ou já foi substituída")
                    if velha[0] != entidade_id:
                        raise ValueError(f"a observação #{substitui} é de outra entidade")
                    await db.execute("UPDATE observacoes SET invalido_em = ? WHERE id = ?", (now, substitui))
                cur = await db.execute(
                    "INSERT INTO observacoes(entidade_id, categoria, texto, texto_norm, fonte, valido_desde, substitui)"
                    " VALUES (?,?,?,?,?,?,?)", (entidade_id, cat, texto.strip(), tnorm, fonte, now, substitui))
                if cur.lastrowid is None:
                    raise RuntimeError("INSERT em observacoes não retornou lastrowid")
                obs_id, op = cur.lastrowid, ("CORRIGE" if substitui is not None else "ADD")
                await db.execute("UPDATE entidades SET atualizado_em = ? WHERE id = ?", (now, entidade_id))
            await db.commit()
        obs = await self.observacao(obs_id)
        assert obs is not None
        return obs, op

    async def invalidar(self, obs_id: int) -> bool:
        async with self._db() as db:
            cur = await db.execute("UPDATE observacoes SET invalido_em = ? WHERE id = ? AND invalido_em IS NULL",
                                   (time.time(), obs_id))
            await db.commit()
            return cur.rowcount > 0

    async def da_entidade(self, entidade_id: int, *, incluir_antigas: bool = False) -> list[Observacao]:
        filtro = "" if incluir_antigas else " AND o.invalido_em IS NULL"
        async with self._db() as db:
            rows = await db.execute_fetchall(
                _OBS_SELECT + " WHERE o.entidade_id = ?" + filtro + " ORDER BY o.categoria, o.valido_desde",
                (entidade_id,))
        return [_obs(r) for r in rows]

    # ── relações ───────────────────────────────────────────────────────────────────────────────────────
    async def relacionar(self, de_id: int, tipo: str, para_id: int) -> str:
        async with self._db() as db:
            cur = await db.execute("INSERT OR IGNORE INTO relacoes(de_id, tipo, para_id, criado_em) VALUES (?,?,?,?)",
                                   (de_id, norm(tipo), para_id, time.time()))
            await db.commit()
            return "ADD" if cur.rowcount else "NOOP"

    async def relacoes(self, entidade_id: int) -> list[Relacao]:
        """As duas direções: o que esta entidade aponta e o que aponta pra ela."""
        async with self._db() as db:
            rows = await db.execute_fetchall(
                "SELECT a.nome, r.tipo, b.nome FROM relacoes r"
                " JOIN entidades a ON a.id = r.de_id JOIN entidades b ON b.id = r.para_id"
                " WHERE r.invalido_em IS NULL AND (r.de_id = ? OR r.para_id = ?) ORDER BY r.criado_em",
                (entidade_id, entidade_id))
        return [Relacao(de=r[0], tipo=r[1], para=r[2]) for r in rows]

    # ── busca ──────────────────────────────────────────────────────────────────────────────────────────
    async def buscar(self, termos: list[str], limite: int = 30) -> list[Observacao]:
        """OR dos termos (com prefixo: 'supin' acha 'supino'), só observações válidas, melhor BM25 primeiro.
        OR e não AND: a frase inteira do dono quase nunca está toda numa observação."""
        termos = [t.replace('"', "") for t in termos if t.replace('"', "")]
        if not termos:
            return []
        q = " OR ".join(f'"{t}"*' for t in termos)
        async with self._db() as db:
            rows = await db.execute_fetchall(
                _OBS_SELECT + " JOIN obs_fts ON obs_fts.rowid = o.id"
                " WHERE obs_fts MATCH ? AND o.invalido_em IS NULL ORDER BY bm25(obs_fts) LIMIT ?",
                (q, limite))
        return [_obs(r) for r in rows]
