import pytest

from core.config import get_settings


def test_flatten_extrai_texto_de_content_blocks():
    from infrastructure.llm.tokenizer import _flatten
    msgs = [{
        "role": "user", "content": [
            {"type": "text", "text": "o que tem nesse print?"},
            {"type": "image_url", "image_url": {"url": "http://x/p.png"}},
        ],
    }]
    flat = _flatten(msgs)
    assert flat == [{"role": "user", "content": "o que tem nesse print?"}]


@pytest.mark.integration
async def test_count_tokens_coerente_com_servidor(live):
    from infrastructure.llm import tokenizer
    msgs = [{"role": "user", "content": "olá, tudo bem?"}]
    out = await live.complete(msgs)
    assert abs(tokenizer.count_tokens(msgs) - out.usage.prompt_tokens) <= 8
    assert tokenizer.fits(msgs, budget=get_settings().max_context_tokens)
