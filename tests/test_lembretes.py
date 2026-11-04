import datetime as dt

import pytest

from application.services.lembretes import Lembrete, antecedencia_de, ciclo, proxima_ocorrencia, quando_futuro
from application.tools.remind import RemindInput, RemindTool
from domain.tools.guard import ToolCtx
from infrastructure.memory.lembrete_store import SqliteLembreteStore

AGORA = dt.datetime(2026, 11, 4, 15, 30)          # quarta


@pytest.mark.parametrize("texto,esperado", [
    ("amanhã 9h", dt.datetime(2026, 11, 5, 9, 0)),
    ("amanha às 15:00", dt.datetime(2026, 11, 5, 15, 0)),
    ("dia 10", dt.datetime(2026, 11, 10, 9, 0)),
    ("dia 2", dt.datetime(2026, 12, 2, 9, 0)),               # já passou este mês → mês que vem
    ("sexta 18:00", dt.datetime(2026, 11, 6, 18, 0)),
    ("quarta 10h", dt.datetime(2026, 11, 11, 10, 0)),        # hoje já passou das 10 → próxima quarta
    ("25/12", dt.datetime(2026, 12, 25, 9, 0)),
    ("01/02", dt.datetime(2027, 2, 1, 9, 0)),
    ("em 2 horas", dt.datetime(2026, 11, 4, 17, 30)),
    ("18:00", dt.datetime(2026, 11, 4, 18, 0)),
    ("2026-12-01 14:00", dt.datetime(2026, 12, 1, 14, 0)),
])
def test_quando_futuro(texto, esperado):
    assert quando_futuro(texto, AGORA) == esperado


def test_quando_invalido():
    with pytest.raises(ValueError):
        quando_futuro("qualquer hora", AGORA)


def test_antecedencia():
    assert antecedencia_de("2 dias") == 2880 and antecedencia_de("1 hora") == 60
    assert antecedencia_de("30 min") == 30 and antecedencia_de("") == 0


def test_mensal_nao_escorrega():
    l = Lembrete(1, "x", dt.datetime(2027, 1, 31, 9).timestamp(), "mensal", dia=31)
    fev = proxima_ocorrencia(l, dt.datetime(2027, 1, 31, 10).timestamp())
    assert dt.datetime.fromtimestamp(fev) == dt.datetime(2027, 2, 28, 9)
    l.proximo = fev
    assert dt.datetime.fromtimestamp(proxima_ocorrencia(l, fev + 60)) == dt.datetime(2027, 3, 31, 9)


@pytest.fixture
async def store(tmp_path):
    s = SqliteLembreteStore(str(tmp_path / "c.db"))
    await s.init()
    return s


async def test_ciclo_avisa_uma_vez_e_anda_o_mensal(store):
    venc = dt.datetime(2026, 11, 10, 9).timestamp()
    l = await store.criar("Conta de luz", venc, "mensal", 2880, dia=10)
    enviados = []

    async def enviar(t, m):
        enviados.append((t, m))
        return True

    assert await ciclo(store, enviar, venc - 3 * 86400) == []                 # cedo demais
    assert await ciclo(store, enviar, venc - 2 * 86400 + 60) == [l.id]        # 2 dias antes → avisa
    assert "Conta de luz" in enviados[0][0] and "vence" in enviados[0][1]
    assert await ciclo(store, enviar, venc - 86400) == []                     # não repete
    await ciclo(store, enviar, venc + 60)                                     # venceu → anda pro mês seguinte
    prox = (await store.pegar(l.id)).proximo
    assert dt.datetime.fromtimestamp(prox) == dt.datetime(2026, 12, 10, 9)
    assert await ciclo(store, enviar, dt.datetime(2026, 12, 8, 9, 1).timestamp()) == [l.id]


async def test_sem_device_tenta_de_novo_e_unico_desativa(store):
    venc = dt.datetime(2026, 11, 5, 9).timestamp()
    l = await store.criar("Ligar pro João", venc)
    online = False

    async def enviar(t, m):
        return online

    assert await ciclo(store, enviar, venc + 60) == []                        # ninguém online: segura
    assert (await store.pegar(l.id)).ativo
    online = True
    assert await ciclo(store, enviar, venc + 600) == [l.id]                   # conectou → avisa atrasado
    assert not (await store.pegar(l.id)).ativo


async def test_tool_cria_lista_cancela(store):
    tool, ctx = RemindTool(store), ToolCtx(fala_do_usuario="")
    out = await tool.run(RemindInput(texto="Pagar conta de luz", quando="dia 10", repetir="mensal", antes="2 dias"), ctx)
    assert out.startswith("[lembretes] criado: #1 Pagar conta de luz") and "todo mês (dia 10)" in out and "2 dias antes" in out
    assert "#1" in await tool.run(RemindInput(acao="listar"), ctx)
    assert "cancelado" in await tool.run(RemindInput(acao="cancelar", id=1), ctx)
    assert "nenhum" in await tool.run(RemindInput(acao="listar"), ctx)
    assert (await tool.run(RemindInput(texto="x", quando="algum dia"), ctx)).startswith("[erro]")


def test_aceita_action_em_ingles():
    assert RemindInput.model_validate({"action": "listar"}).acao == "listar"
    assert RemindInput.model_validate({"acao": "cancelar", "id": 3}).acao == "cancelar"
