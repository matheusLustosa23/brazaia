"""O pacote do companion pros devices: versão atual + download do wheel.

Instalar num device:   pip install "<servidor>/api/v1/companion/pacote/<arquivo>[cli]"   (ou o .whl baixado)
O connect compara a versão do welcome com a sua e se atualiza sozinho (companion/connect.py).
Sem autenticação por enquanto (é só o código do companion, sem segredo); entra no login de devices (fase 3).
"""
import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from infrastructure import companion_pacote

router = APIRouter(prefix="/companion", tags=["companion"])


async def atual() -> dict:
    return await asyncio.to_thread(companion_pacote.info)


@router.get("/versao")
async def versao() -> dict:
    return await atual()


@router.get("/pacote/{arquivo}")
async def pacote(arquivo: str):
    a = await atual()
    if arquivo != a["arquivo"]:
        raise HTTPException(404, f"versão antiga ou inexistente — a atual é {a['arquivo']}")
    return FileResponse(f"{companion_pacote.DIST}/{arquivo}", media_type="application/octet-stream", filename=arquivo)
