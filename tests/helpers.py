from types import SimpleNamespace

from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import (
    Choice as ChunkChoice,
    ChoiceDelta,
    ChoiceDeltaToolCall,
    ChoiceDeltaToolCallFunction,
)


def _stub(create_fn):
    """Substitui o AsyncOpenAI: objeto com .chat.completions.create = create_fn."""
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create_fn)))

def _tcd(name, args="", index=0):
    """Monta um fragmento (delta) de tool-call."""
    return ChoiceDeltaToolCall(
        index=index, id="call_1", type="function",
        function=ChoiceDeltaToolCallFunction(name=name, arguments=args)
    )

def _chunk(content=None, tool_call=None):
    """Monta um ChatCompletionChunk com 1 choice/delta (texto e/ou tool-call)."""
    delta = ChoiceDelta(content=content, tool_calls=[tool_call] if tool_call else None)
    return ChatCompletionChunk(
        id="x", object="chat.completion.chunk", created=0, model="m",
        choices=[ChunkChoice(index=0, delta=delta, finish_reason=None)],
    )