import pytest, asyncio
from domain.tools.base import ToolRegistry
from infrastructure.tools.echo import EchoTool
from pydantic import BaseModel
from domain.tools.base import Tool

class _DeviceIn(BaseModel):
    url: str

class _DeviceTool(Tool):
    name = "open_tab"
    description = "abre aba"
    input_schema = _DeviceIn
    side = "device"
    action_class = "reversible"
    
    async def run(self, payload: BaseModel) -> str:
        return "nunca executado no servidor"

class _SlowIn(BaseModel):
    pass

class _SlowTool(Tool):
    name = "slow"
    description = "trava"
    input_schema = _SlowIn
    timeout_s = 0.05
    
    async def run(self, payload: BaseModel) -> str:
        await asyncio.sleep(1)
        return "nunca"

def _reg() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(EchoTool())
    return reg

def _reg_full():
    reg = ToolRegistry()
    reg.register(EchoTool())
    reg.register(_DeviceTool())
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
    
async def test_timeout_retorna_mensagem():
    reg = ToolRegistry()
    reg.register(_SlowTool())
    assert "[timeout]" in  await reg.run("slow",{})

async def test_device_side_nao_executa_no_servidor():
    reg = _reg_full()
    result = await reg.run("open_tab", {"url":"x"})
    assert "device-side" in  result

async def test_for_device_inclui_server_e_capability():
    sub = _reg_full().for_device(set({"open_tab"}))
    assert "echo" in sub and "open_tab" in sub

async def test_for_device_exclui_server_e_capability():
    sub = _reg_full().for_device(set())
    assert "echo" in sub and  "open_tab" not in sub

    