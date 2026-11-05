import json
import sqlite3
import time

import pytest

from application.services.device_service import DeviceService
from domain.tools.base import ToolRegistry
from domain.tools.guard import ToolCtx
from infrastructure.devices.device_registry import SqlLiteDeviceRegistry
from infrastructure.tools.get_location import GetLocationInput, GetLocationTool


@pytest.fixture
async def svc(tmp_path):
    reg = SqlLiteDeviceRegistry(str(tmp_path / "devices.db"))
    await reg.init()
    s = DeviceService(reg, ToolRegistry())
    await s.register_device("S24", "Celular")
    await s.activate_device("S24", ["notify", "get_location"])
    return s


async def test_banco_antigo_ganha_colunas(tmp_path):
    db = str(tmp_path / "velho.db")
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE devices (id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT DEFAULT 'pending',"
              " allowed_tools TEXT DEFAULT '[]', created_at REAL, last_seen REAL)")
    c.execute("INSERT INTO devices VALUES ('S24','Celular','active','[\"notify\"]',1,2)")
    c.commit(); c.close()
    reg = SqlLiteDeviceRegistry(db)
    await reg.init()
    d = await reg.get("S24")
    assert d is not None and d.allowed_tools == ["notify"] and d.plataforma == "" and d.permissoes == {}


async def test_meta_do_handshake(svc):
    await svc.atualizar_meta("S24", "termux", {"camera": "ok", "localizacao": "negada"}, {"bateria": 81, "carregando": False})
    d = await svc.get_device("S24")
    assert d.plataforma == "termux" and d.permissoes["localizacao"] == "negada" and d.estado["bateria"] == 81
    assert d.allowed_tools == ["notify", "get_location"]          # não apagou o que já tinha


async def test_fila_reenviada_nao_duplica_e_descarta_lixo(svc):
    pts = [{"id": "a", "lat": -15.79, "lon": -47.88, "quando": 1000.0, "precisao_m": 20, "fonte": "network"},
           {"id": "b", "lat": 200, "lon": 0, "quando": 1001.0},                 # latitude impossível
           {"id": "c", "lat": "x", "lon": 1}]                                  # lixo
    assert await svc.salvar_localizacoes("S24", pts) == 1
    assert await svc.salvar_localizacoes("S24", pts) == 0                       # ack perdido → reenvio
    hist = await svc.localizacoes("S24")
    assert len(hist) == 1 and hist[0].origem == "periodica" and hist[0].precisao_m == 20


async def test_historico_mais_recente_primeiro(svc):
    agora = time.time()
    await svc.salvar_localizacoes("S24", [{"lat": 1, "lon": 1, "quando": agora - 7200},
                                          {"lat": 2, "lon": 2, "quando": agora - 60}])
    assert (await svc.ultima_localizacao("S24")).lat == 2
    assert len(await svc.localizacoes("S24", desde=agora - 3600)) == 1


class _GW:
    """Gateway fake: device offline (localizar falha) mas com posição guardada."""
    def __init__(self, svc):
        self.service = svc

    async def localizar(self, device_id):
        return None, f"device '{device_id}' offline"

    async def listar_status(self):
        loc = await self.service.ultima_localizacao("S24")
        return [{"id": "S24", "localizacao": loc.__dict__ if loc else None}]


async def test_tool_cai_na_ultima_conhecida_com_idade(svc):
    await svc.salvar_localizacoes("S24", [{"lat": -15.79, "lon": -47.88, "quando": time.time() - 7200, "precisao_m": 15}])
    tool = GetLocationTool(_GW(svc))  # type: ignore[arg-type]
    out = await tool.run(GetLocationInput(device="S24"), ToolCtx(fala_do_usuario=""))
    assert "não li agora" in out and "ÚLTIMA conhecida" in out and "há 2 h" in out and "openstreetmap" in out


async def test_tool_sem_nada(svc):
    tool = GetLocationTool(_GW(svc))  # type: ignore[arg-type]
    out = await tool.run(GetLocationInput(device="S24"), ToolCtx(fala_do_usuario=""))
    assert "não há posição guardada" in out


def test_fila_do_companion(tmp_path, monkeypatch):
    from companion import localizacao as L
    monkeypatch.setattr(L, "FILA", str(tmp_path / "fila.jsonl"))
    L.enfileirar({"lat": 1, "lon": 2, "quando": 10})
    L.enfileirar({"lat": 3, "lon": 4, "quando": 20})
    pend = L.pendentes()
    assert len(pend) == 2 and all(p["origem"] == "periodica" for p in pend)
    L.remover([pend[0]["id"]])                                        # só o que o server confirmou
    resto = L.pendentes()
    assert len(resto) == 1 and resto[0]["lat"] == 3
    with open(L.FILA, "a") as f:                                      # linha cortada no meio (queda)
        f.write('{"lat": 9')
    assert len(L.pendentes()) == 1
    L.remover([resto[0]["id"]])                                       # remover não quebra com a linha cortada
    assert L.pendentes() == []


async def test_tool_historico_no_intervalo(svc):
    import datetime as dt
    ontem = dt.datetime.now() - dt.timedelta(days=1)
    base = ontem.replace(hour=12, minute=0, second=0, microsecond=0).timestamp()
    await svc.salvar_localizacoes("S24", [{"lat": -16.7 - i / 100, "lon": -49.1, "quando": base + i * 900}
                                          for i in range(40)])          # 12:00 → 21:45, a cada 15 min
    tool = GetLocationTool(_GW(svc))  # type: ignore[arg-type]
    out = await tool.run(GetLocationInput(device="S24", desde="ontem 14:00", ate="ontem 18:00"),
                         ToolCtx(fala_do_usuario=""))
    assert "histórico de S24: 17 posição(ões)" in out and "14:00" in out and "18:00" in out
    assert out.count("\n- ") <= 14


async def test_tool_historico_exige_device(svc):
    tool = GetLocationTool(_GW(svc))  # type: ignore[arg-type]
    out = await tool.run(GetLocationInput(desde="ontem"), ToolCtx(fala_do_usuario=""))
    assert out.startswith("[erro]")


def test_importa_linha_do_tempo_google():
    import json as _j
    from infrastructure.devices import google_timeline as g
    a = {"semanticSegments": [{"startTime": "2026-10-01T08:00:00.000-03:00",
                               "timelinePath": [{"point": "-16.7081°, -49.0931°", "time": "2026-10-01T08:10:00.000-03:00"}]},
                              {"startTime": "2026-10-01T09:00:00.000-03:00",
                               "visit": {"topCandidate": {"placeLocation": {"latLng": "-16.80°, -49.20°"}}}}],
         "rawSignals": [{"position": {"LatLng": "-16.81°, -49.21°", "accuracyMeters": 12,
                                      "timestamp": "2026-10-01T13:00:00.000-03:00"}}]}
    pts = g.ler(_j.dumps(a).encode())
    assert [p["fonte"] for p in pts] == ["google-trajeto", "google-visita", "google-gps"]
    assert all(p["origem"] == "google" for p in pts) and pts[2]["precisao_m"] == 12
    c = {"locations": [{"latitudeE7": -167081000, "longitudeE7": -490931000, "timestamp": "2026-10-01T08:00:00Z"}]}
    assert g.ler(_j.dumps(c).encode())[0]["lat"] == -16.7081
