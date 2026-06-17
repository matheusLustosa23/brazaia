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