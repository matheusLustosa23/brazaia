import dataclasses
import time

from pydantic import BaseModel, Field

from domain.tools.base import Tool
from domain.tools.guard import ToolCtx
from infrastructure.devices.device_gateway import DeviceGateway


class GetLocationInput(BaseModel):
    device: str | None = Field(default=None, description=(
        "O device cuja posição você quer (ex.: 'S24' — o celular é o que anda com o dono). "
        "Vazio = a ÚLTIMA posição conhecida de todos os devices."))


def _idade(ts: float) -> str:
    s = max(0, time.time() - ts)
    if s < 90:
        return "agora"
    if s < 3600:
        return f"há {int(s // 60)} min"
    if s < 86400:
        return f"há {int(s // 3600)} h ({time.strftime('%H:%M', time.localtime(ts))})"
    return time.strftime("em %d/%m %H:%M", time.localtime(ts))


def _linha(nome: str, p: dict) -> str:
    prec = f" ±{round(p['precisao_m'])} m" if p.get("precisao_m") else ""
    fonte = f", {p['fonte']}" if p.get("fonte") else ""
    return (f"- {nome}: {p['lat']:.5f}, {p['lon']:.5f}{prec}{fonte} · {_idade(p['quando'])} · "
            f"mapa: https://www.openstreetmap.org/?mlat={p['lat']:.5f}&mlon={p['lon']:.5f}#map=17/{p['lat']:.5f}/{p['lon']:.5f}")


class GetLocationTool(Tool[GetLocationInput]):
    name = "get_location"
    description = (
        "Onde está um device do dono (latitude/longitude, precisão e QUANDO foi lido) — o celular anda com ele, "
        "então 'onde eu estou' = o celular. Com device: lê AGORA (GPS); se o device estiver offline ou falhar, "
        "volta a última posição conhecida com a idade. Sem device: a última posição de todos.\n"
        "Fale a idade da leitura ('há 2 h'); nunca diga que é a posição de agora se não for. Endereço/bairro "
        "você NÃO sabe — só as coordenadas e o link do mapa."
    )
    input_schema = GetLocationInput
    side = "server"
    action_class = "read"
    timeout_s = 50.0               # o device pode levar ~40 s (GPS → rede → última conhecida)
    router_hint = "saber onde está um device (localização, GPS) ou onde o dono está"

    def __init__(self, gateway: DeviceGateway) -> None:
        self._gateway = gateway

    async def run(self, payload: GetLocationInput, ctx: ToolCtx) -> str:
        if payload.device:
            ponto, motivo = await self._gateway.localizar(payload.device)
            if ponto:
                return "[localização] lida agora:\n" + _linha(payload.device, ponto)
            ultima = await self._gateway.service.ultima_localizacao(payload.device)
            if ultima is None:
                return f"[localização] não consegui ler '{payload.device}' ({motivo}) e não há posição guardada dele."
            return (f"[localização] não li agora ({motivo}); a ÚLTIMA conhecida:\n"
                    + _linha(payload.device, dataclasses.asdict(ultima)))
        itens = [d for d in await self._gateway.listar_status() if d.get("localizacao")]
        if not itens:
            return "[localização] nenhum device mandou posição ainda."
        return "[localização] última posição de cada device:\n" + "\n".join(_linha(d["id"], d["localizacao"]) for d in itens)
