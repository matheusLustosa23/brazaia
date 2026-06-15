import pytest
from infrastructure.llm.client import OpenAILLMClient
from tests.helpers import _chunk, _stub, _tcd


async def test_stream_text_e_tool_delta(monkeypatch):
    c = OpenAILLMClient.__new__(OpenAILLMClient)
    c._model = "m"
    async def fake_create(**_):
        async def _chunks():
            yield _chunk(content="olá")
            yield _chunk(tool_call=_tcd("abrir_aba"))
        return _chunks()
    monkeypatch.setattr(c, "_c", _stub(fake_create), raising=False)
    kinds = [k async for k, _ in c.stream(messages=[])]
    assert kinds == ["text","tool_call_delta"]
    

TOOLS = [{
    "type": "function",
    "function": {
        "name": "abrir_aba",
        "description": "Abre uma URL numa nova aba do navegador.",
        "parameters": {"type": "object",
                       "properties": {"url": {"type": "string"}}, "required": ["url"]},
    },
}]

@pytest.mark.integration
async def test_function_calling(live):
    out = await live.complete(
        messages=[{"role":"user","content":"abra o gmail pra mim"}],
        tools=TOOLS, tool_choice="auto"
    )
    assert out.tool_calls and out.tool_calls[0].name == "abrir_aba"
    assert "url" in out.tool_calls[0].arguments
    
@pytest.mark.integration
async def test_stream_texto(live):
    chunks = [
        d 
        async for k,d in live.stream([{"role":"user", "content": "conte ate 3"}]) if k == "text"
    ]
    assert "".join(chunks)