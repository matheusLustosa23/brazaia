"""Importa a Linha do tempo do Google Maps (o arquivo que o dono exporta no celular) → pontos do nosso histórico.

Por que importar arquivo: a Linha do tempo fica no armazenamento PRIVADO do app Maps (sem API, e o Takeout
deixou de exportar quando ela foi pro aparelho). O único caminho é o botão Exportar do próprio Maps
(Configurações → Localização → Serviços de localização → Linha do tempo → Exportar) → Timeline.json.

Formatos aceitos (o Google mudou várias vezes):
  A) export do aparelho (2024+): {"semanticSegments": [...timelinePath/visit/activity], "rawSignals": [...]}
     coordenadas como "-16.7081°, -49.0931°"
  B) export antigo do app (lista): [{"startTime", "visit": {"topCandidate": {"placeLocation": "geo:-16.7,-49.0"}},
     "timelinePath": [{"point": "geo:...", "durationMinutesOffsetFromStartTime": "12"}]}]
  C) Takeout clássico (Records.json): {"locations": [{"latitudeE7", "longitudeE7", "accuracy", "timestamp"}]}
"""
import datetime as dt
import json
import re

_NUM = r"(-?\d+(?:\.\d+)?)"
_COORD = re.compile(_NUM + r"°?\s*,\s*" + _NUM)


def _coord(v) -> tuple[float, float] | None:
    """'-16.7°, -49.0°' | 'geo:-16.7,-49.0' | {'latLng': ...} | {'latitudeE7': ..}."""
    if isinstance(v, dict):
        if "latitudeE7" in v and "longitudeE7" in v:
            return v["latitudeE7"] / 1e7, v["longitudeE7"] / 1e7
        for k in ("latLng", "LatLng", "point", "placeLocation"):
            if k in v:
                return _coord(v[k])
        return None
    if isinstance(v, str):
        m = _COORD.search(v.replace("geo:", ""))
        if m:
            lat, lon = float(m[1]), float(m[2])
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return lat, lon
    return None


def _ts(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v / 1000 if v > 1e11 else float(v)          # ms ou s
    if isinstance(v, str):
        if v.isdigit():
            return _ts(int(v))
        try:
            return dt.datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _ponto(c, quando, precisao=None, fonte="google") -> dict | None:
    if c is None or quando is None:
        return None
    return {"lat": c[0], "lon": c[1], "quando": quando, "precisao_m": precisao, "fonte": fonte, "origem": "google"}


def _segmento(seg: dict) -> list[dict]:
    out: list[dict | None] = []
    ini = _ts(seg.get("startTime"))
    for p in seg.get("timelinePath") or []:
        q = _ts(p.get("time"))
        if q is None and ini is not None and p.get("durationMinutesOffsetFromStartTime") is not None:
            q = ini + float(p["durationMinutesOffsetFromStartTime"]) * 60
        out.append(_ponto(_coord(p.get("point")), q, fonte="google-trajeto"))
    visita = seg.get("visit") or {}
    if visita:
        cand = visita.get("topCandidate") or {}
        out.append(_ponto(_coord(cand.get("placeLocation")), ini, fonte="google-visita"))
    atividade = seg.get("activity") or {}
    if atividade:
        out.append(_ponto(_coord(atividade.get("start")), ini, fonte="google-trajeto"))
        out.append(_ponto(_coord(atividade.get("end")), _ts(seg.get("endTime")), fonte="google-trajeto"))
    return [p for p in out if p]


def ler(conteudo: bytes) -> list[dict]:
    """Pontos {lat, lon, quando, precisao_m, fonte, origem='google'} — sem repetir o mesmo instante."""
    dados = json.loads(conteudo)
    pontos: list[dict | None] = []
    if isinstance(dados, dict) and "locations" in dados:                      # C
        for r in dados["locations"]:
            pontos.append(_ponto(_coord(r), _ts(r.get("timestamp") or r.get("timestampMs")), r.get("accuracy")))
    else:
        segmentos = dados.get("semanticSegments", []) if isinstance(dados, dict) else dados   # A | B
        for seg in segmentos or []:
            if isinstance(seg, dict):
                pontos += _segmento(seg)
        if isinstance(dados, dict):
            for s in dados.get("rawSignals") or []:
                pos = (s or {}).get("position") or {}
                pontos.append(_ponto(_coord(pos), _ts(pos.get("timestamp")), pos.get("accuracyMeters"), "google-gps"))
    vistos, unicos = set(), []
    for p in pontos:
        if p and round(p["quando"]) not in vistos:
            vistos.add(round(p["quando"]))
            unicos.append(p)
    return sorted(unicos, key=lambda p: p["quando"])
