from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(prefix="/ws", tags=["devices"])


@router.websocket("/device/{device_id}")
async def device_ws(ws: WebSocket, device_id: str) -> None:
    """SCAFFOLD: aceita o handshake e fecha limpo. SEM protocolo real
    (registro de capacidades, ações, resultados) — isso vem em feat-companion-actuator.
    Fixa agora a topologia 'cérebro único, braços muitos'.
    Nota: WebSocket NÃO usa o envelope ApiResponse; mensagens via orjson (futuro)."""
    await ws.accept()
    try:
        while True:
            msg = await ws.receive_text()
            await ws.send_text(msg)
    except WebSocketDisconnect:
        return
