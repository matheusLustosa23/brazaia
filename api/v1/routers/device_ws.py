import orjson
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.container import Container

router = APIRouter(prefix="/ws", tags=["devices"])


@router.websocket("/device/{device_id}")
async def device_ws(
    ws: WebSocket, 
    device_id: str
) -> None:
    container: Container = ws.app.state.container
    await ws.accept()
    
    try:
       all_tools = container.ai.tools.get_all_tool_names()
       await container.device.handshake.execute(ws, device_id, all_tools)
       
       while True:
           msg = await ws.receive_text()
           data = orjson.loads(msg)
           
           await container.device.service.update_heartbeat(device_id)
           
           if "request_id" in data:
               container.device.gateway.rpc.resolve_response(data["request_id"], data)
           
    except WebSocketDisconnect:
        container.device.gateway.connections.unregister(device_id)
   
   