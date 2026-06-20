from functools import lru_cache

from transformers import AutoTokenizer, PreTrainedTokenizerBase

from core.config import get_settings


@lru_cache(maxsize=2)
def _tok(model: str) -> PreTrainedTokenizerBase:
    # trust_remote_code pode ser necessário p/ o processor do Qwen3-VL
    return AutoTokenizer.from_pretrained(model, trust_remote_code=True)


def _flatten(messages: list[dict]) -> list[dict]:
    """Reduz content multimodal a texto p/ contagem (imagens contam à parte/aprox.)."""
    flat = []
    for m in messages:
        content = m.get("content","") 
        if isinstance(content, list):
            text = " ".join(block.get("text", "") for block in content if block.get("type") == "text")
            flat.append({"role": m["role"], "content": text})
        else:
            flat.append(m)
    return flat


def count_tokens(messages: list[dict], model: str | None = None) -> int:
    model = model or get_settings().model_name
    t = _tok(model)
    conversation = _flatten(messages)
    ids = t.apply_chat_template(conversation, add_generation_prompt=True, return_dict=False)
    return len(ids)


def fits(messages: list[dict], budget: int, model: str | None = None) -> bool:
    return count_tokens(messages, model) <= budget
