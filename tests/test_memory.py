import pytest, asyncio
from application.services.memory_service import MemoryService
from domain.entities.memory_fact import MemoryFact, PROFILE, GOAL, STUDY
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

async def test_recall_sem_match_retorna_vazio(mem):
    await mem.upsert(MemoryFact(category=STUDY, key="curso", content="estuda cálculo"))
    hits = await mem.recall("python programação")
    assert hits == []
    
async def test_recall_reordena_por_score(mem):
    fid_baixo, _ = await mem.upsert(MemoryFact(category=STUDY, key="a", content="estuda cálculo", confidence=0.1))
    fid_alto, _  = await mem.upsert(MemoryFact(category=STUDY, key="b", content="cálculo avançado", confidence=1.0))
    hits = await mem.recall("cálculo")
    assert hits[0].id == fid_alto

async def test_recall_respeita_max_recall(mem):
    for i in range(20):
        await mem.upsert(MemoryFact(category=STUDY, key=f"t{i}", content=f"cálculo tema {i}"))
    hits = await mem.recall("cálculo", limit=20)
    assert len(hits) == 15  # _MAX_RECALL