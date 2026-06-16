import pytest
from core.config import get_settings
from infrastructure.llm.client import OpenAILLMClient


@pytest.fixture
async def live():
    """Cliente contra o vLLM real; PULA o teste se o motor estiver fora."""
    c = OpenAILLMClient(get_settings())
    if(await c.health())["vllm"] != "up":
        pytest.skip("cLLM indisponível")
    
    return c