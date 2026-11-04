import pytest

from application.services.cerebro_service import CerebroService
from infrastructure.memory.cerebro_store import SqliteCerebroStore


@pytest.fixture
async def cer(tmp_path) -> CerebroService:
    store = SqliteCerebroStore(str(tmp_path / "cerebro.db"))
    await store.init()
    return CerebroService(store)


async def test_panorama_conta_e_liga(cer):
    await cer.lembrar("dói acima de 60 kg", "saude", entidade="Supino reto", tipo="exercicio", relacao="grupo", com="Peito")
    await cer.registrar(tipo="serie", assunto="Supino reto", dados={"series": 3, "reps": 12, "carga_kg": 20})
    p = await cer.panorama()
    sup = next(e for e in p["entidades"] if e["nome"] == "Supino reto")
    assert sup["n_obs"] == 1 and sup["n_reg"] == 1 and sup["area"] == "academia"
    assert p["relacoes"][0]["tipo"] == "grupo" and p["totais"]["relacoes"] == 1
    assert any(t["nome"] == "exercicio" for t in p["tipos"])


async def test_ficha_tem_historico_e_metricas(cer):
    ent = await cer.criar_entidade("Supino reto", "exercicio")
    r = await cer.nova_observacao(ent["id"], "carga", "20 kg")
    await cer.nova_observacao(ent["id"], "carga", "22 kg", substitui=r["observacao"]["id"])
    await cer.registrar(tipo="serie", assunto="Supino reto", dados={"series": 3, "reps": 12, "carga_kg": 22})
    f = await cer.ficha(ent["id"])
    assert len(f["observacoes"]) == 2 and any(o["invalido_em"] for o in f["observacoes"])
    assert f["metricas"] == ["carga_kg", "reps", "series"]


async def test_renomear_atualiza_busca(cer):
    ent = await cer.criar_entidade("Supino", "exercicio")
    await cer.nova_observacao(ent["id"], "execucao", "pegada média")
    await cer.editar_entidade(ent["id"], nome="Supino reto")
    assert "Supino reto" in await cer.recordar(busca="supino")
    with pytest.raises(ValueError):
        await cer.criar_entidade("supino RETO", None)                    # nome repetido (sem acento/maiúscula)


async def test_mudar_area_do_tipo(cer):
    ent = await cer.criar_entidade("Ana", "pessoa")
    e = await cer.editar_entidade(ent["id"], area="trabalho")
    assert e["area"] == "trabalho"


async def test_dono_nao_apaga_nem_renomeia(cer):
    dono = next(e for e in (await cer.panorama())["entidades"] if e["nome"] == "Você")
    with pytest.raises(ValueError):
        await cer.apagar_entidade(dono["id"])
    with pytest.raises(ValueError):
        await cer.editar_entidade(dono["id"], nome="Eu")


async def test_apagar_entidade_leva_tudo(cer):
    await cer.lembrar("x", "nota", entidade="Teste", tipo="tema", relacao="sobre", com="Cálculo")
    await cer.registrar(tipo="estudo", assunto="Teste", dados={"duracao_min": 30})
    ent = next(e for e in (await cer.panorama())["entidades"] if e["nome"] == "Teste")
    r = await cer.apagar_entidade(ent["id"])
    assert r == {"observacoes": 1, "relacoes": 1, "registros": 1}
    assert "nada encontrado" in await cer.recordar(busca="x teste")


async def test_relacao_cria_alvo_e_apaga(cer):
    ent = await cer.criar_entidade("Supino reto", "exercicio")
    r = await cer.nova_relacao(ent["id"], "grupo", "Peito")
    assert r["para"]["nome"] == "Peito"
    rel = (await cer.ficha(ent["id"]))["relacoes"][0]
    assert await cer.apagar_relacao(rel["id"]) and (await cer.ficha(ent["id"]))["relacoes"] == []


async def test_revisar_e_apagar_observacao(cer):
    ent = await cer.criar_entidade("Lixo", "tema")
    o = await cer.nova_observacao(ent["id"], "nota", "teste qualquer")
    rev = await cer.revisar(1)
    assert any(x["texto"] == "teste qualquer" for x in rev["observacoes"])
    assert await cer.apagar_observacao(o["observacao"]["id"])
    assert "nada encontrado" in await cer.recordar(busca="qualquer")



async def test_alvo_de_ligacao_ganha_tipo_depois(cer):
    await cer.lembrar("COCOMO", "dificuldade", entidade="Medidas", tipo="tema", relacao="parte de", com="Projeto Ágil")
    await cer.lembrar("Manifesto + XP + Scrum", "conteudo", entidade="Projeto Ágil", tipo="disciplina")
    e = next(x for x in (await cer.panorama())["entidades"] if x["nome"] == "Projeto Ágil")
    assert e["tipo"] == "disciplina" and e["area"] == "estudos"
