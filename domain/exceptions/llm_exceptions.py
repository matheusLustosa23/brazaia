from domain.exceptions.base import AgentError

class LLMError(AgentError):
    """Base de todas as falhas de comunicação com o engine."""
    
    
class LLMUnavailable(LLMError):
    """vLLM fora do ar / 5xx / erro de conexão (esgotou retries)."""


class LLMTimeout(LLMError):
    """Estouro de timeout na chamada ao engine."""