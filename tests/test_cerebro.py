import pytest

from application.services.cerebro_service import CerebroService, termos
from infrastructure.memory.cerebro_store import SqliteCerebroStore


@pytest.fixture
async def cer(tmp_path) -> CerebroService:
    store = SqliteCerebroStore(str(tmp_path / "cerebro.db"))
    await store.init()
    return CerebroService(store)


def _id(saida: str) -> int:
    return int(saida.split("#")[1].split()[0])


async def test_nucleo_vazio_sem_observacoes(cer):
    bloco = await cer.render_compact("oi")
    assert bloco.startswith("Agora: ") and "MEMÓRIA" not in bloco


async def test_perfil_chega_ao_contexto(cer):
    # o furo antigo: o modelo gravava em categorias inventadas e o perfil injetado era VAZIO
    out = await cer.lembrar("se chama Matheus", "nome")
    assert out.startswith("[memória] gravado: Você #")
    bloco = await cer.render_compact("qualquer coisa")
    assert "Sobre o dono:" in bloco and "se chama Matheus" in bloco


async def test_aliases_do_dono_sao_a_mesma_entidade(cer):
    await cer.lembrar("mora em Brasília", "rotina", entidade="eu")
    await cer.lembrar("trabalha com dados", "trabalho", entidade="o usuário")
    bloco = await cer.render_compact("")
    assert "Brasília" in bloco and "dados" in bloco


async def test_igual_e_noop(cer):
    await cer.lembrar("prefere resposta direta", "preferencia")
    out = await cer.lembrar("Prefere  resposta DIRETA", "preferência")
    assert "já estava gravado" in out


async def test_categoria_normalizada(cer):
    await cer.lembrar("prefere resposta direta", "preferência")
    out = await cer.lembrar("gosta de exemplos", "Preferencias")
    assert "[preferencia]" in out


async def test_corrigir_guarda_historico(cer):
    velha = _id(await cer.lembrar("supino com 20 kg", "carga", entidade="Supino reto", tipo="exercicio"))
    out = await cer.lembrar("supino com 22 kg", "carga", entidade="supino RETO", substitui=velha)
    assert "corrigido" in out
    atual = await cer.recordar(entidade="Supino reto")
    assert "22 kg" in atual and "antes: #" in atual          # a velha aparece só como "antes", não como atual
    assert not any(l.startswith("- #") and "20 kg" in l for l in atual.splitlines())
    hist = await cer.recordar(entidade="Supino reto", incluir_antigas=True)
    assert "20 kg" in hist and "[até" in hist


async def test_substitui_invalido_nao_grava(cer):
    out = await cer.lembrar("algo", "nota", substitui=999)
    assert out.startswith("[erro]") and "nada foi gravado" in out
    assert "algo" not in await cer.render_compact("")


async def test_substitui_de_outra_entidade_nao_grava(cer):
    a = _id(await cer.lembrar("dói o ombro", "saude"))
    out = await cer.lembrar("3x12", "carga", entidade="Supino reto", tipo="exercicio", substitui=a)
    assert out.startswith("[erro]")


async def test_busca_por_qualquer_palavra_sem_acento(cer):
    await cer.lembrar("ombro dói acima de 60 kg", "execucao", entidade="Supino reto", tipo="exercicio")
    out = await cer.recordar(busca="quais exercicios machucam meu ombro")
    assert "Supino reto" in out and "ombro" in out


async def test_busca_pelo_nome_da_entidade(cer):
    await cer.lembrar("pegada média", "execucao", entidade="Supino reto", tipo="exercicio")
    assert "pegada" in await cer.recordar(busca="supino")


async def test_relacao_aparece_na_ficha(cer):
    out = await cer.lembrar("barra, desce até o peito", "execucao", entidade="Supino reto", tipo="exercicio",
                            relacao="grupo", com="Peito")
    assert "—grupo→ Peito" in out
    ficha = await cer.recordar(entidade="peito")
    assert "Supino reto —grupo→ Peito" in ficha


async def test_relevantes_entram_no_contexto(cer):
    await cer.lembrar("se chama Matheus", "nome")
    await cer.lembrar("prova dia 26/11", "prova", entidade="Cálculo", tipo="disciplina")
    bloco = await cer.render_compact("quando é a prova de calculo?")
    assert "Relacionado ao pedido:" in bloco and "Cálculo (disciplina)" in bloco
    assert "26/11" not in await cer.render_compact("bom dia")


async def test_cache_invalida_ao_gravar(cer):
    b1 = await cer.render_compact("")
    await cer.lembrar("se chama Matheus", "nome")
    assert await cer.render_compact("") != b1


async def test_tipo_plural_vira_singular(cer, tmp_path):
    await cer.lembrar("x", "nota", entidade="Agachamento", tipo="exercícios")
    assert "(exercicio" in await cer.recordar(entidade="Agachamento")


def test_termos_tira_stopwords():
    assert termos("qual foi a última vez no supino?") == ["vez", "supino"]


async def test_avisa_parecida_e_aceita_corrigir_depois(cer):
    velha = _id(await cer.lembrar("prefere resposta direta", "preferencia"))
    out = await cer.lembrar("prefere explicações com exemplos práticos", "preferencia")
    assert "já existia parecido" in out and f"#{velha}" in out
    out2 = await cer.lembrar("prefere explicações com exemplos práticos", "preferencia", substitui=velha)
    assert "corrigido" in out2
    bloco = await cer.render_compact("")
    assert "exemplos" in bloco and "resposta direta" not in bloco


async def test_sem_parecida_sem_aviso(cer):
    await cer.lembrar("se chama Matheus", "nome")
    assert "ATENÇÃO" not in await cer.lembrar("mora em Brasília", "rotina")


async def test_busca_mostra_versao_anterior(cer):
    velha = _id(await cer.lembrar("prefere resposta direta", "preferencia"))
    await cer.lembrar("prefere exemplos práticos", "preferencia", substitui=velha)
    out = await cer.recordar(busca="preferencia exemplos")
    assert "exemplos" in out and "antes: #" in out and "resposta direta" in out


async def test_ficha_mostra_versao_anterior(cer):
    velha = _id(await cer.lembrar("prefere resposta direta", "preferencia"))
    await cer.lembrar("prefere exemplos práticos", "preferencia", substitui=velha)
    out = await cer.recordar(entidade="Você")
    assert "antes: #" in out and "resposta direta" in out


# ── M2: registros ──────────────────────────────────────────────────────────────────────────────────────
import datetime as _dt
from application.services.cerebro_service import quando_de, desde_de, fmt_dados


def test_quando_de_formatos():
    a = _dt.datetime(2026, 11, 4, 7, 40)
    f = lambda t: _dt.datetime.fromtimestamp(quando_de(t, a))
    assert f("") == a
    assert f("ontem 18:40") == _dt.datetime(2026, 11, 3, 18, 40)
    assert f("28/10") == _dt.datetime(2026, 10, 28, 12, 0)
    assert f("2026-10-28 19:05") == _dt.datetime(2026, 10, 28, 19, 5)
    with pytest.raises(ValueError):
        quando_de("semana que vem", a)


def test_desde_mes_e_semana():
    a = _dt.datetime(2026, 11, 4, 7, 40)
    assert _dt.datetime.fromtimestamp(desde_de("mes", a)) == _dt.datetime(2026, 11, 1)
    assert _dt.datetime.fromtimestamp(desde_de("semana", a)) == _dt.datetime(2026, 10, 29)


def test_fmt_dados():
    assert fmt_dados({"series": 3, "reps": 12, "carga_kg": 20}) == "3 séries de 12 repetições com 20 kg"
    assert (fmt_dados({"series": 4, "reps": 6, "carga_kg": 16.0}, "cada lado (32 kg no total)")
            == "4 séries de 6 repetições com 16 kg cada lado (32 kg no total)")


async def test_treino_completo(cer):
    out = await cer.registrar("abrir", "treino", "Peito", quando="28/10 18:40")
    assert "sessão aberta" in out
    # sessão de 28/10 já passou das 6h → não está "em andamento" agora; registra as séries com data explícita
    sid = int(out.rsplit("#", 1)[1].rstrip(")"))
    for ex, d, q in (("Supino reto", {"series": 3, "reps": 12, "carga_kg": 20}, "28/10 18:45"),
                     ("Crucifixo", {"series": 3, "reps": 15, "carga_kg": 10}, "28/10 19:00")):
        await cer._store.registrar("serie", quando_de(q), entidade_id=(await cer._store.entidade(ex, "exercicio")).id,
                                   dados=d, sessao=sid)
    ult = await cer.consultar("treino", "peito", ultimo=True)
    assert "qua 28/10" in ult and "em andamento" not in ult and "Supino reto" in ult and "Crucifixo" in ult
    sup = await cer.consultar("serie", "supino reto", ultimo=True)
    assert "3 séries de 12 repetições com 20 kg" in sup and "Crucifixo" not in sup


async def test_sessao_em_andamento_agrupa_e_aparece_no_contexto(cer):
    await cer.registrar("abrir", "treino", "Peito")
    out = await cer.registrar(tipo="serie", assunto="Supino reto", dados={"series": 3, "reps": 12, "carga_kg": 22},
                              texto="a última foi difícil")
    assert "dentro de treino Peito" in out
    bloco = await cer.render_compact("bora")
    assert "Em andamento: treino Peito" in bloco and "Supino reto" in bloco
    fim = await cer.registrar("fechar")
    assert "sessão fechada" in fim and "Supino reto 3 séries de 12 repetições com 22 kg" in fim
    assert "Em andamento" not in await cer.render_compact("bora")


async def test_abrir_outra_fecha_a_anterior(cer):
    await cer.registrar("abrir", "treino", "Peito")
    out = await cer.registrar("abrir", "treino", "Costas")
    assert "fechei a anterior" in out


async def test_corrigir_registro(cer):
    out = await cer.registrar(tipo="serie", assunto="Supino reto", dados={"series": 3, "reps": 12, "carga_kg": 20})
    rid = int(out.rsplit("#", 1)[1].split(")")[0])
    await cer.registrar(tipo="serie", assunto="Supino reto", dados={"series": 3, "reps": 12, "carga_kg": 25}, corrige=rid)
    res = await cer.consultar("serie", "Supino reto")
    assert "25 kg" in res and "20 kg" not in res


async def test_progresso_no_mes(cer):
    ent = (await cer._store.entidade("Supino reto", "exercicio")).id
    hoje = _dt.datetime.now()
    for dias, kg in ((40, 15), (2, 20), (0, 22)):
        ts = (hoje - _dt.timedelta(days=dias)).timestamp()
        await cer._store.registrar("serie", ts, entidade_id=ent, dados={"series": 3, "reps": 12, "carga_kg": kg})
    res = await cer.consultar("serie", "Supino reto", desde="30 dias")
    assert "22 kg" in res and "20 kg" in res and "15 kg" not in res


async def test_consulta_sem_registro(cer):
    assert "nenhum registro" in await cer.consultar("treino", "Perna", ultimo=True)


async def test_ficha_do_exercicio_mostra_registros(cer):
    await cer.registrar(tipo="serie", assunto="Supino reto", dados={"series": 3, "reps": 12, "carga_kg": 20})
    ficha = await cer.recordar(entidade="Supino reto")
    assert "Registros recentes:" in ficha and "3 séries de 12 repetições com 20 kg" in ficha and "(exercicio" in ficha



def test_fmt_prancha():
    assert fmt_dados({"series": 3, "duracao_s": 60}) == "3 séries de 60 s"


async def test_log_igual_ultima_copia_e_cada_lado(cer):
    # o caso de 04/11: "tríceps e panturrilha mantive o mesmo peso" + "15 kg em cada lado"
    await cer.registrar("registrar", "serie", "Panturrilha em pé", {"series": 4, "reps": 6, "carga_kg": 15},
                        quando="2026-09-07 19:12", cada_lado=True)
    await cer.registrar("registrar", "serie", "Tríceps polia", {"series": 4, "reps": 6, "carga_kg": 20}, quando="2026-09-07 19:40")
    await cer.registrar("abrir", "treino", "Peito")
    r1 = await cer.registrar("registrar", "serie", "Panturrilha em pé", igual_ultima=True)
    r2 = await cer.registrar("registrar", "serie", "Tríceps polia", igual_ultima=True)
    assert "4 séries de 6 repetições com 15 kg cada lado (30 kg no total)" in r1
    assert "4 séries de 6 repetições com 20 kg" in r2 and "cada lado" not in r2
    r3 = await cer.registrar("registrar", "serie", "Peito polia alta", {"series": 4, "reps": 6, "carga_kg": 15}, cada_lado=True)
    assert "15 kg cada lado (30 kg no total)" in r3


async def test_log_igual_ultima_sem_anterior_nao_inventa(cer):
    r = await cer.registrar("registrar", "serie", "Exercício novo", igual_ultima=True)
    assert r.startswith("[erro]") and "Nada foi registrado" in r
