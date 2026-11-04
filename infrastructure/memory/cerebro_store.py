# infrastructure/memory/cerebro_store.py — o cérebro em SQLite (data/cerebro.db).
#
# Tabelas:
#   tipos        nome normalizado + área (voce/academia/estudos/trabalho/...). Aberta: tipo novo entra com área 'geral'
#                e o painel (M3) reclassifica. Normalizar evita 'preferência' × 'preferencias' × 'Preferencias'.
#   entidades    UMA linha por nome (nome_norm UNIQUE) — o modelo se refere às coisas pelo nome.
#   observacoes  frases sobre uma entidade. Nunca DELETE: corrigir = invalido_em na velha + nova com `substitui`.
#   relacoes     ligações entidade→entidade.
#   obs_fts      índice de busca (FTS5) sobre texto + categoria + nome da entidade, sem acento.
#   registros    (M2) o que ACONTECEU: tipo, quando, assunto (entidade), números em JSON. Uma "sessão" (treino do
#                dia) é um registro com eh_sessao=1 e fim=NULL enquanto dura; as séries apontam pra ela em `sessao`.
import json
import time
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

import aiosqlite

from domain.entities.cerebro import DONO, TIPO_DONO, Entidade, Observacao, Registro, Relacao, norm

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
CREATE TABLE IF NOT EXISTS registros (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo        TEXT    NOT NULL,
    quando      REAL    NOT NULL,                 -- quando ACONTECEU
    entidade_id INTEGER REFERENCES entidades(id), -- o assunto ("Supino reto", "Peito")
    dados       TEXT    NOT NULL DEFAULT '{}',    -- JSON com os números
    texto       TEXT    NOT NULL DEFAULT '',
    sessao      INTEGER REFERENCES registros(id),
    eh_sessao   INTEGER NOT NULL DEFAULT 0,
    fim         REAL,                             -- sessão: NULL = em andamento
    fonte       TEXT    NOT NULL DEFAULT '',
    criado_em   REAL    NOT NULL,
    invalido_em REAL,                             -- corrigido → a velha fica, marcada
    substitui   INTEGER REFERENCES registros(id)
);
CREATE INDEX IF NOT EXISTS ix_reg_tipo ON registros(tipo, entidade_id, quando DESC);
CREATE INDEX IF NOT EXISTS ix_reg_sessao ON registros(sessao);

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


_REG_SELECT = """SELECT r.id, r.tipo, r.quando, e.nome, r.dados, r.texto, r.sessao, r.fim, r.eh_sessao, r.substitui
                 FROM registros r LEFT JOIN entidades e ON e.id = r.entidade_id"""


def _reg(r) -> Registro:
    return Registro(id=r[0], tipo=r[1], quando=r[2], entidade=r[3], dados=json.loads(r[4] or "{}"), texto=r[5],
                    sessao=r[6], fim=r[7], eh_sessao=bool(r[8]), substitui=r[9])


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

    # ── registros (M2) ────────────────────────────────────────────────────────────────────────────────
    async def registrar(self, tipo: str, quando: float, *, entidade_id: int | None, dados: dict, texto: str = "",
                        sessao: int | None = None, eh_sessao: bool = False, substitui: int | None = None,
                        fonte: str = "") -> Registro:
        now = time.time()
        async with self._db() as db:
            if substitui is not None:
                velho = await (await db.execute(
                    "SELECT invalido_em FROM registros WHERE id = ?", (substitui,))).fetchone()
                if velho is None or velho[0] is not None:
                    raise ValueError(f"o registro #{substitui} não existe ou já foi corrigido")
                await db.execute("UPDATE registros SET invalido_em = ? WHERE id = ?", (now, substitui))
            cur = await db.execute(
                "INSERT INTO registros(tipo, quando, entidade_id, dados, texto, sessao, eh_sessao, fonte, criado_em,"
                " substitui) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (norm(tipo), quando, entidade_id, json.dumps(dados, ensure_ascii=False), texto.strip(), sessao,
                 int(eh_sessao), fonte, now, substitui))
            if cur.lastrowid is None:
                raise RuntimeError("INSERT em registros não retornou lastrowid")
            reg_id = cur.lastrowid
            await db.commit()
        reg = await self.registro(reg_id)
        assert reg is not None
        return reg

    async def registro(self, reg_id: int) -> Registro | None:
        async with self._db() as db:
            r = await (await db.execute(_REG_SELECT + " WHERE r.id = ?", (reg_id,))).fetchone()
        return _reg(r) if r else None

    async def fechar_sessao(self, reg_id: int, fim: float) -> None:
        async with self._db() as db:
            await db.execute("UPDATE registros SET fim = ? WHERE id = ? AND fim IS NULL", (fim, reg_id))
            await db.commit()

    async def sessao_aberta(self, desde: float) -> Registro | None:
        """A sessão em andamento mais recente (aberta depois de `desde` — sessão esquecida aberta não vale pra sempre)."""
        async with self._db() as db:
            r = await (await db.execute(
                _REG_SELECT + " WHERE r.eh_sessao = 1 AND r.fim IS NULL AND r.invalido_em IS NULL AND r.quando >= ?"
                " ORDER BY r.quando DESC LIMIT 1", (desde,))).fetchone()
        return _reg(r) if r else None

    async def registros(self, *, tipo: str | None = None, entidade_id: int | None = None, sessao: int | None = None,
                        desde: float | None = None, ate: float | None = None, limite: int = 50) -> list[Registro]:
        """Válidos, mais recentes primeiro. Filtros opcionais e combináveis."""
        onde, args = ["r.invalido_em IS NULL"], []
        for cond, val in (("r.tipo = ?", norm(tipo) if tipo else None), ("r.entidade_id = ?", entidade_id),
                          ("r.sessao = ?", sessao), ("r.quando >= ?", desde), ("r.quando <= ?", ate)):
            if val is not None:
                onde.append(cond)
                args.append(val)
        async with self._db() as db:
            rows = await db.execute_fetchall(
                _REG_SELECT + " WHERE " + " AND ".join(onde) + " ORDER BY r.quando DESC, r.id DESC LIMIT ?",
                (*args, limite))
        return [_reg(r) for r in rows]

    # ── painel (P3): visão geral e gestão pelo dono ───────────────────────────────────────────────────────
    async def tipos(self) -> list[tuple[str, str]]:
        async with self._db() as db:
            return [(r[0], r[1]) for r in await db.execute_fetchall("SELECT nome, area FROM tipos ORDER BY area, nome")]

    async def definir_area(self, tipo: str, area: str) -> None:
        async with self._db() as db:
            t = await self._tipo(db, tipo)
            await db.execute("UPDATE tipos SET area = ? WHERE nome = ?", (norm(area) or "geral", t))
            await db.commit()

    async def entidade_por_id(self, ent_id: int) -> Entidade | None:
        async with self._db() as db:
            r = await (await db.execute(
                "SELECT e.id, e.tipo, e.nome, t.area FROM entidades e JOIN tipos t ON t.nome = e.tipo WHERE e.id = ?",
                (ent_id,))).fetchone()
        return Entidade(id=r[0], tipo=r[1], nome=r[2], area=r[3]) if r else None

    async def panorama(self) -> dict:
        """Tudo que o grafo precisa numa ida: entidades (com contagens), relações válidas e totais."""
        async with self._db() as db:
            ents = list(await db.execute_fetchall(
                """SELECT e.id, e.nome, e.tipo, t.area, e.criado_em, e.atualizado_em,
                          (SELECT COUNT(*) FROM observacoes o WHERE o.entidade_id = e.id AND o.invalido_em IS NULL),
                          (SELECT COUNT(*) FROM registros r WHERE r.entidade_id = e.id AND r.invalido_em IS NULL)
                   FROM entidades e JOIN tipos t ON t.nome = e.tipo ORDER BY e.id"""))
            rels = list(await db.execute_fetchall(
                "SELECT id, de_id, tipo, para_id, criado_em FROM relacoes WHERE invalido_em IS NULL ORDER BY id"))
            tot = await (await db.execute(
                """SELECT (SELECT COUNT(*) FROM observacoes WHERE invalido_em IS NULL),
                          (SELECT COUNT(*) FROM observacoes WHERE invalido_em IS NOT NULL),
                          (SELECT COUNT(*) FROM registros WHERE invalido_em IS NULL)""")).fetchone() or (0, 0, 0)
        return {
            "entidades": [{"id": r[0], "nome": r[1], "tipo": r[2], "area": r[3], "criado_em": r[4],
                           "atualizado_em": r[5], "n_obs": r[6], "n_reg": r[7]} for r in ents],
            "relacoes": [{"id": r[0], "de": r[1], "tipo": r[2], "para": r[3], "criado_em": r[4]} for r in rels],
            "totais": {"entidades": len(ents), "observacoes": tot[0], "historico": tot[1], "registros": tot[2],
                       "relacoes": len(rels)},
        }

    async def relacoes_com_id(self, entidade_id: int) -> list[dict]:
        async with self._db() as db:
            rows = await db.execute_fetchall(
                "SELECT r.id, a.id, a.nome, r.tipo, b.id, b.nome FROM relacoes r"
                " JOIN entidades a ON a.id = r.de_id JOIN entidades b ON b.id = r.para_id"
                " WHERE r.invalido_em IS NULL AND (r.de_id = ? OR r.para_id = ?) ORDER BY r.criado_em",
                (entidade_id, entidade_id))
        return [{"id": r[0], "de_id": r[1], "de": r[2], "tipo": r[3], "para_id": r[4], "para": r[5]} for r in rows]

    async def renomear_entidade(self, ent_id: int, nome: str) -> None:
        nome = nome.strip()
        if not nome:
            raise ValueError("nome vazio")
        async with self._db() as db:
            outro = await (await db.execute("SELECT id FROM entidades WHERE nome_norm = ? AND id <> ?",
                                            (norm(nome), ent_id))).fetchone()
            if outro:
                raise ValueError(f"já existe uma entidade chamada '{nome}'")
            await db.execute("UPDATE entidades SET nome = ?, nome_norm = ?, atualizado_em = ? WHERE id = ?",
                             (nome, norm(nome), time.time(), ent_id))
            # o índice de busca guarda o nome da entidade em cada observação — acompanha o novo nome
            await db.execute("UPDATE obs_fts SET entidade = ? WHERE rowid IN (SELECT id FROM observacoes WHERE entidade_id = ?)",
                             (nome, ent_id))
            await db.commit()

    async def mudar_tipo(self, ent_id: int, tipo: str) -> None:
        async with self._db() as db:
            t = await self._tipo(db, tipo)
            await db.execute("UPDATE entidades SET tipo = ?, atualizado_em = ? WHERE id = ?", (t, time.time(), ent_id))
            await db.commit()

    async def apagar_entidade(self, ent_id: int) -> dict:
        """Apaga DE VEZ a entidade e o que é dela (observações, ligações, registros). Só pelo dono, no painel."""
        async with self._db() as db:
            ids = [r[0] for r in await db.execute_fetchall("SELECT id FROM observacoes WHERE entidade_id = ?", (ent_id,))]
            await db.executemany("DELETE FROM obs_fts WHERE rowid = ?", [(i,) for i in ids])
            await db.execute("UPDATE observacoes SET substitui = NULL WHERE entidade_id = ?", (ent_id,))
            n_obs = (await db.execute("DELETE FROM observacoes WHERE entidade_id = ?", (ent_id,))).rowcount
            n_rel = (await db.execute("DELETE FROM relacoes WHERE de_id = ? OR para_id = ?", (ent_id, ent_id))).rowcount
            await db.execute("UPDATE registros SET sessao = NULL WHERE sessao IN (SELECT id FROM registros WHERE entidade_id = ?)",
                             (ent_id,))
            await db.execute("UPDATE registros SET substitui = NULL WHERE substitui IN (SELECT id FROM registros WHERE entidade_id = ?)",
                             (ent_id,))
            n_reg = (await db.execute("DELETE FROM registros WHERE entidade_id = ?", (ent_id,))).rowcount
            await db.execute("DELETE FROM entidades WHERE id = ?", (ent_id,))
            await db.commit()
        return {"observacoes": n_obs, "relacoes": n_rel, "registros": n_reg}

    async def apagar_observacao(self, obs_id: int) -> bool:
        """De vez (some até do histórico). Invalidar é o caminho normal; isto é pra lixo/erro."""
        async with self._db() as db:
            await db.execute("UPDATE observacoes SET substitui = NULL WHERE substitui = ?", (obs_id,))
            await db.execute("DELETE FROM obs_fts WHERE rowid = ?", (obs_id,))
            ok = (await db.execute("DELETE FROM observacoes WHERE id = ?", (obs_id,))).rowcount > 0
            await db.commit()
            return ok

    async def apagar_relacao(self, rel_id: int) -> bool:
        async with self._db() as db:
            ok = (await db.execute("DELETE FROM relacoes WHERE id = ?", (rel_id,))).rowcount > 0
            await db.commit()
            return ok

    async def invalidar_registro(self, reg_id: int) -> bool:
        async with self._db() as db:
            ok = (await db.execute("UPDATE registros SET invalido_em = ? WHERE id = ? AND invalido_em IS NULL",
                                   (time.time(), reg_id))).rowcount > 0
            await db.commit()
            return ok

    async def observacoes_desde(self, desde: float) -> list[Observacao]:
        """Pra tela Revisar: tudo que entrou (ou foi corrigido) desde `desde`, mais novo primeiro."""
        async with self._db() as db:
            rows = await db.execute_fetchall(
                _OBS_SELECT + " WHERE o.valido_desde >= ? OR o.invalido_em >= ? ORDER BY o.valido_desde DESC LIMIT 300",
                (desde, desde))
        return [_obs(r) for r in rows]
