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
    assert await cer.render_compact("oi") == ""


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
