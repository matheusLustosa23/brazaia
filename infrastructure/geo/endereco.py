"""Endereço de uma coordenada (geocodificação reversa) pelo Nominatim do OpenStreetMap.

Política de uso do Nominatim público: no máximo 1 pedido por segundo, User-Agent que identifica a aplicação,
e cache dos resultados. Aqui: cache em memória por coordenada arredondada (~11 m), fila com 1,1 s entre
pedidos e o mesmo UA honesto da pesquisa na web. Só é chamado quando alguém CLICA num ponto do mapa.
"""
import asyncio
import time
from collections import OrderedDict

import httpx

_URL = "https://nominatim.openstreetmap.org/reverse"
_CACHE: "OrderedDict[tuple[float, float], dict]" = OrderedDict()
_CACHE_MAX = 5000
_trava = asyncio.Lock()
_ultimo = 0.0


def _resumo(d: dict) -> dict:
    a = d.get("address") or {}
    rua = a.get("road") or a.get("pedestrian") or a.get("footway") or a.get("path")
    linha1 = ", ".join(x for x in (rua, a.get("house_number")) if x)
    bairro = a.get("suburb") or a.get("neighbourhood") or a.get("quarter") or a.get("city_district")
    cidade = a.get("city") or a.get("town") or a.get("village") or a.get("municipality")
    linha2 = " · ".join(x for x in (bairro, f"{cidade}-{a['ISO3166-2-lvl4'][-2:]}" if cidade and a.get("ISO3166-2-lvl4")
                                     else cidade) if x)
    lugar = d.get("name") if d.get("name") and d.get("name") != rua else None
    return {"lugar": lugar, "linha1": linha1 or None, "linha2": linha2 or None, "completo": d.get("display_name")}


async def endereco(lat: float, lon: float, user_agent: str) -> dict:
    global _ultimo
    chave = (round(lat, 4), round(lon, 4))
    if chave in _CACHE:
        _CACHE.move_to_end(chave)
        return _CACHE[chave]
    async with _trava:                                       # 1 pedido por vez, ≥ 1,1 s entre eles
        if chave in _CACHE:
            return _CACHE[chave]
        espera = 1.1 - (time.monotonic() - _ultimo)
        if espera > 0:
            await asyncio.sleep(espera)
        try:
            async with httpx.AsyncClient(timeout=10, headers={"User-Agent": user_agent}) as c:
                r = await c.get(_URL, params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 18,
                                              "addressdetails": 1, "accept-language": "pt-BR"})
            _ultimo = time.monotonic()
            r.raise_for_status()
            res = _resumo(r.json())
        except (httpx.HTTPError, ValueError) as e:
            _ultimo = time.monotonic()
            return {"erro": f"endereço indisponível ({type(e).__name__})"}
    _CACHE[chave] = res
    if len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return res
