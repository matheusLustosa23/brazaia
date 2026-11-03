import time

from pydantic import BaseModel

from domain.tools.base import Tool
from domain.tools.guard import ToolCtx
from infrastructure.devices.device_gateway import DeviceGateway


class ListDevicesInput(BaseModel):
    pass


def _hora(ts: float | None) -> str:
    if not ts:
        return "nunca"
    hoje = time.strftime("%d/%m") == time.strftime("%d/%m", time.localtime(ts))
    return time.strftime("hoje %H:%M" if hoje else "%d/%m %H:%M", time.localtime(ts))


class ListDevicesTool(Tool[ListDevicesInput]):
    name = "list_devices"
    description = (
        "Lista os devices do dono (celular, notebook, server…): quais estão CONECTADOS agora (e desde quando) e, "
        "pros desconectados, quando foram vistos pela última vez. Use quando perguntarem quais devices estão "
        "online/conectados, ou ANTES de escolher onde abrir/enviar algo se não souber o que está disponível."
    )
    input_schema = ListDevicesInput
    side = "server"
    action_class = "read"
    router_hint = "ver quais devices estão conectados e quando cada um foi visto"

    def __init__(self, gateway: DeviceGateway) -> None:
        self._gateway = gateway

    async def run(self, payload: ListDevicesInput, ctx: ToolCtx) -> str:
        itens = await self._gateway.listar_status()
        if not itens:
            return "[devices] nenhum device registrado ainda."
        linhas = []
        for d in itens:
            nome = d["id"] if d["nome"] in (d["id"], "", None) else f"{d['id']} ({d['nome']})"
            if d["conectado"]:
                linhas.append(f"- {nome}: CONECTADO desde {_hora(d['conectado_desde'])}")
            else:
                linhas.append(f"- {nome}: offline · visto por último {_hora(d['ultima_vez'])}")
        on = sum(1 for d in itens if d["conectado"])
        return f"[devices] {on} conectado(s) de {len(itens)}:\n" + "\n".join(linhas)
