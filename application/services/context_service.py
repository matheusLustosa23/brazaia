from collections.abc import Callable
from dataclasses import dataclass

from domain.contracts import LLMClient


CountTokens = Callable[[list[dict]], int]

@dataclass(slots=True)
class BuildMetrics:
    budget: int = 0
    used_tokens: int = 0
    dropped_turns: int = 0
    summary_tokens: int = 0
    static_prefix_tokens: int = 0
    
    
class ContextManager:
    """Monta a janela respeitando o orçamento. Serviço de APLICAÇÃO puro: o contador de
    tokens e o contrato LLMClient chegam por INJEÇÃO — sem importar infrastructure/ nem FastAPI/SDK."""
    
    def __init__(
        self,
        budget: int, 
        reserved_output: int,
        count_tokens: CountTokens,
        llm: LLMClient
    ) -> None:
        self._budget = budget
        self._reserved = reserved_output
        self._count = count_tokens
        self._llm = llm
        self.metrics = BuildMetrics(budget=budget)
        
    @property
    def input_budget(self) -> int:
        """Teto real do PROMPT (deixa espaço para a geração)."""
        return self._budget - self._reserved
    
    def build(
        self,
        system_static: str, #preixo estatico imutavel
        memory_block: str, #memoria pessoal (perfil compactado)
        history: list[dict], #historico das conversas
        user_turn: dict, #messagem atual
        rolling_summary: str = "" #conversas compactadas 
    ) -> list[dict]:
        """Ordem canônica: system ESTÁTICO → memória → resumo rolante → histórico → turno atual."""
        head: list[dict] = [{"role": "system", "content": system_static}]
        if memory_block:
            head.append({"role": "system", "content": memory_block})
        if rolling_summary:
            head.append({"role": "system", "content": f"[resumo da conversa]\n{rolling_summary}"})
        tail = [user_turn]
        
        room = self.input_budget - self._count(head + tail)
        recent: list[dict] = []
        dropped = 0
        for msg in reversed(history):
            cost = self._count([msg])
            if room - cost < 0:
                dropped += 1
                continue
            recent.insert(0,msg)
            room  -= cost
        
        messages = head + recent + tail
        self._update_metrics(
            messages,
            head,
            dropped,
            bool(rolling_summary)
        )

        return messages
    
    def _update_metrics(
        self,
        messages: list[dict],
        head: list[dict],
        dropped: int,
        has_summary: bool
    ) -> None:
        self.metrics.used_tokens = self._count(messages)
        self.metrics.dropped_turns = dropped
        self.metrics.static_prefix_tokens = self._count(head[:1])
        self.metrics.summary_tokens = self._count([head[-1]]) if has_summary else 0