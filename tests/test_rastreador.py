import json

import pytest

import companion.localizacao as L


class _Parar(Exception):
    pass


def _simular(monkeypatch, tmp_path, leituras: list, ticks: int):
    """Roda o rastreador com relógio falso: cada tick = 30 s; `leituras[i]` = (last, once) do tick i."""
    monkeypatch.setattr(L, "FILA", str(tmp_path / "fila.jsonl"))
    monkeypatch.setattr(L, "PID_RASTREADOR", str(tmp_path / "pid"))
    monkeypatch.setattr(L, "ESTADO", str(tmp_path / "estado.json"))
    monkeypatch.setattr(L, "ler_estado", lambda: {"bateria": 80, "carregando": False})
    relogio = {"t": 1_000_000.0, "tick": 0}
    pedidos = []
    monkeypatch.setattr(L.time, "time", lambda: relogio["t"])

    def fix(prov, modo, timeout):
        last, once = leituras[min(relogio["tick"], len(leituras) - 1)]
        if modo == "last":
            return dict(last, quando=relogio["t"] - last["idade_s"]) if last and prov == "gps" else None
        pedidos.append((relogio["tick"], prov))
        return dict(once, quando=relogio["t"], idade_s=0) if once else None

    def dormir(_):
        relogio["t"] += 30
        relogio["tick"] += 1
        if relogio["tick"] >= ticks:
            raise _Parar

    monkeypatch.setattr(L, "_fix", fix)
    monkeypatch.setattr(L.time, "sleep", dormir)
    with pytest.raises(_Parar):
        L.rastrear()
    fila = [json.loads(l) for l in open(L.FILA)] if (tmp_path / "fila.jsonl").exists() else []
    return fila, pedidos


def _p(lat, idade=5, prec=10):
    return {"lat": lat, "lon": -49.2, "precisao_m": prec, "fonte": "gps", "idade_s": idade}


def test_parado_no_maximo_um_ponto_a_cada_5_min(monkeypatch, tmp_path):
    fila, _ = _simular(monkeypatch, tmp_path, [(_p(-16.8), None)], ticks=21)    # 10 min parado, fix sempre fresco
    assert len(fila) == 3                    # t=0, t=5min, t=10min
    assert all(p["origem"] == "rastreador" for p in fila)


def test_andando_um_ponto_por_tick(monkeypatch, tmp_path):
    leituras = [(_p(-16.8 - i * 0.002), None) for i in range(10)]               # ~220 m a cada 30 s
    fila, pedidos = _simular(monkeypatch, tmp_path, leituras, ticks=10)
    assert len(fila) == 10 and pedidos == []                                   # tudo da "última conhecida", sem ligar GPS


def test_sem_fix_fresco_andando_pede_gps(monkeypatch, tmp_path):
    leituras = [(_p(-16.80), None), (_p(-16.81), None), (_p(-16.81, idade=300), _p(-16.82))]
    fila, pedidos = _simular(monkeypatch, tmp_path, leituras, ticks=4)
    assert (2, "gps") in pedidos and len(fila) >= 3


def test_bateria_salva(monkeypatch, tmp_path):
    _simular(monkeypatch, tmp_path, [(_p(-16.8), None)], ticks=2)
    assert L.estado_salvo()["bateria"] == 80
