import orjson
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from infrastructure.vision.sources import DeviceCamera

from core.container import Container

router = APIRouter(prefix="/ws", tags=["devices"])


@router.websocket("/device/{device_id}")
async def device_ws(
    ws: WebSocket, 
    device_id: str
) -> None:
    container: Container = ws.app.state.container
    await ws.accept()
    CAM_LABEL = {"back": "traseira", "front": "frontal"}
    cam_sources: list[str] = []
    try:
        all_tools = container.ai.tools.get_all_tool_names()
        meta = await container.device.handshake.execute(ws, device_id, all_tools)
        cameras = meta.get("cameras") or [None]
        for cam in cameras:
            name = device_id if cam is None else f"{device_id}_{CAM_LABEL.get(cam, cam)}"
            ws.app.state.vision.register(DeviceCamera(container.device.gateway, device_id, name=name, camera=cam))
            cam_sources.append(name)
       
        while True:
            msg = await ws.receive_text()
            data = orjson.loads(msg)
            
            await container.device.service.update_heartbeat(device_id)
            
            if "request_id" in data:
                container.device.gateway.rpc.resolve_response(data["request_id"], data)
           
    except WebSocketDisconnect:
        container.device.gateway.connections.unregister(device_id)
        for name in cam_sources:
            ws.app.state.vision.unregister(name)
   
   