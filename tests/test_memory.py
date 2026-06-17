import pytest
from application.services.memory_service import MemoryService
from domain.entities.memory_fact import MemoryFact, PROFILE, GOAL
from infrastructure.memory.sqlite_store import SqlLiteMemoryStore

@pytest.fixture
async def mem(tmp_path) -> MemoryService:
    store = SqlLiteMemoryStore(str(tmp_path / "test.db"))
    await store.init()
    return MemoryService(store=store)

async def test_add_novo_fato(mem):
    _, op =await mem.upsert(MemoryFact(category=PROFILE, key="nome", content="Matheus"))
    assert op == "ADD"
   
async def test_update_por_chave(mem):
    await mem.upsert(MemoryFact(category=PROFILE, key="nome", content="Matheus"))
    _, op = await mem.upsert(MemoryFact(category=PROFILE, key="nome", content="Matheus Costa"))
    assert op == "UPDATE"
    perfil = await mem.get_profile()
    assert len(perfil) == 1 and perfil[0].content == "Matheus Costa"
    
async def test_noop_conteudo_identico(mem):
    await mem.upsert(MemoryFact(category=PROFILE, key="nome", content="Matheus"))
    _, op = await mem.upsert(MemoryFact(category=PROFILE, key="nome", content="Matheus"))
    assert op == "NOOP"

async def test_forget_nao_apaga_fisicamente(mem):
    fid, _ = await mem.upsert(MemoryFact(category=PROFILE, key="nome", content="Matheus"))
    await mem.forget(fid)
    perfil = await mem.get_profile()
    assert perfil == []

async def test_link_sem_erro(mem):
    fid1, _ = await mem.upsert(MemoryFact(category=PROFILE, key="ocupacao", content="engenheiro"))
    fid2, _ = await mem.upsert(MemoryFact(category=GOAL, key="estudo", content="aprender ML"))
    await mem.link(fid1, fid2, "precede")