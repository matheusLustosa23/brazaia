import dataclasses
import re
import time

from pydantic import BaseModel, Field

from core.datas import desde_de, quando_de
from domain.tools.base import Tool
from domain.tools.guard import ToolCtx
from infrastructure.devices.device_gateway import DeviceGateway


class GetLocationInput(BaseModel):
    device: str | None = Field(default=None, description=(
        "O device cuja posição você quer (ex.: 'S24' — o celular é o que anda com o dono). "
        "Vazio = a ÚLTIMA posição conhecida de todos os devices."))
    desde: str | None = Field(default=None, description=(
        "HISTÓRICO: início do intervalo ('ontem 14:00', 'hoje', 'semana', '28/10'). Com isto você NÃO lê agora: "
        "devolve por onde o device passou no intervalo. Exige device."))
    ate: str | None = Field(default=None, description="Fim do intervalo ('ontem 18:00'). Vazio = até agora.")


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
        "volta a última posição conhecida com a idade. Sem device: a última posição de todos. "
        "Com desde/ate: o HISTÓRICO ('por onde eu passei ontem à tarde' → device=S24, desde='ontem 12:00', "
        "ate='ontem 18:00').\n"
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

    async def _historico(self, device: str, desde: str, ate: str | None) -> str:
        try:
            # com hora ("ontem 14:00") = o instante exato; sem hora ("ontem", "semana") = o começo do período
            ini = quando_de(desde) if re.search(r"\d[:h]\d*", desde) else desde_de(desde)
            fim = quando_de(ate) if ate else time.time()
        except ValueError as e:
            return f"[erro] {e}"
        pts = [p for p in await self._gateway.service.localizacoes(device, desde=ini, limite=20000) if p.quando <= fim]
        if not pts:
            return (f"[localização] nenhuma posição de '{device}' entre {time.strftime('%d/%m %H:%M', time.localtime(ini or 0))}"
                    f" e {time.strftime('%d/%m %H:%M', time.localtime(fim))}.")
        pts.reverse()                                            # cronológico
        passo = max(1, -(-len(pts) // 12))                       # teto: no máximo ~12 linhas pro modelo
        amostra = pts[::passo]
        if amostra[-1] is not pts[-1]:
            amostra.append(pts[-1])
        linhas = [f"- {time.strftime('%d/%m %H:%M', time.localtime(p.quando))} · {p.lat:.5f}, {p.lon:.5f}"
                  + (f" ±{round(p.precisao_m)} m" if p.precisao_m else "") + (f" ({p.fonte})" if p.fonte else "")
                  for p in amostra]
        return (f"[localização] histórico de {device}: {len(pts)} posição(ões) de "
                f"{time.strftime('%d/%m %H:%M', time.localtime(pts[0].quando))} a "
                f"{time.strftime('%d/%m %H:%M', time.localtime(pts[-1].quando))}"
                + (f" (mostrando {len(amostra)})" if len(amostra) < len(pts) else "") + ":\n" + "\n".join(linhas)
                + "\nA trilha completa está no painel (Mapa → device → intervalo).")

    async def run(self, payload: GetLocationInput, ctx: ToolCtx) -> str:
        if payload.desde:
            if not payload.device:
                return "[erro] pra histórico diga de qual device (o celular é o que anda com o dono)."
            return await self._historico(payload.device, payload.desde, payload.ate)
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
