import pytest
from domain.tools.base import ToolRegistry
from infrastructure.tools.echo import EchoTool

def _reg() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(EchoTool())
    return reg

async def test_run_echo_retorna_texto():
    assert await _reg().run("echo",{"text":"oi"}) == "echo: oi"
    
async def test_run_ferramenta_desconhecida():
    result = await ToolRegistry().run("nop",{})
    assert "não existe" in result

async def test_run_input_invalido():
    result = await _reg().run("echo",{})
    assert "erro de input" in result

def test_as_openai_tools_formato():
    reg = _reg()
    tools = reg.as_openai_tools()
    assert len(tools) == 1
    assert tools[0]["type"] == "function"
    fn = tools[0]["function"]
    assert fn["name"] == "echo"
    assert fn["parameters"]["properties"]["text"]["type"] == "string"
    
def test_as_openai_tools_filtro_only():
    reg = _reg()
    assert reg.as_openai_tools(only=["echo"]) == reg.as_openai_tools()
    assert reg.as_openai_tools(only=[]) == []
    
def test_describe_all():
    reg = _reg()
    desc = reg.describe_all()
    assert "echo" in desc
    assert "server" in desc
    assert "read" in desc