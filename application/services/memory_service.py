import math
import time

from domain.contracts import MemoryStore
from domain.entities.memory_fact import MemoryFact, PROFILE

_MAX_RECALL  = 15   # teto do limit; acima disso token cost > benefício no contexto
_SEARCH_POOL = 60   # pool fixo de candidatos FTS5, independente do limit

def _retrieval_score(fact: MemoryFact) -> float:
    now = time.time()
    anchor = fact.last_accessed_at or fact.created_at or now
    hours_since = (now - anchor) / 3600
    recency = math.exp(-0.005 * hours_since)
    relevance = 1.0
    importance = fact.confidence * (1 + fact.reinforcement_count * 0.1)
    return 0.35 * recency + 0.45 * relevance + 0.20 * importance


class MemoryService:
    """Memória pessoal do dono. Single-user. Depende do contrato MemoryStore."""
    
    def __init__(self, store: MemoryStore) -> None:
        self._store = store 
        self._render_cache: dict[str | None, str] = {}
    
    def _bust_cache(self) -> None:
        self._render_cache.clear()
    
    async def upsert(self, fact: MemoryFact) -> tuple[int, str]:
        result = await self._store.upsert_fact(fact)
        self._bust_cache()
        return result
    
    async def forget(self, fact_id: int) -> None:
        await self._store.forget(fact_id)
        self._bust_cache()
    
    async def get_profile(self) -> list[MemoryFact]:
        return await self._store.by_category(PROFILE)
    
    async def link(
        self,
        from_id: int,
        to_id: int,
        relation: str,
        strength: float = 1.0,
        origin: str = "inferred"
    ) -> None:
        await self._store.link(from_id, to_id, relation, strength, origin)
    
    async def recall(self, query: str, limit: int = 8) -> list[MemoryFact]:
        if limit > _MAX_RECALL:
            limit = _MAX_RECALL
        candidates = await self._store.search(query, limit=_SEARCH_POOL)
        scored = sorted(candidates, key=_retrieval_score, reverse=True)
        return scored[:limit]