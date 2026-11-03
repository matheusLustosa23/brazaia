"""Devices: quem está conectado agora e quando cada um foi visto pela última vez."""
from fastapi import APIRouter, Depends, Request

from api.v1.dependencies import require_api_key

router = APIRouter(prefix="/devices", tags=["devices"])


@router.get("", dependencies=[Depends(require_api_key)])
async def listar(request: Request):
    """[{id, nome, status, conectado, conectado_desde, ultima_vez, registrado_em}] — horários em epoch (segundos).
    Conectados primeiro; depois do visto mais recente pro mais antigo."""
    return {"devices": await request.app.state.container.device.gateway.listar_status()}
