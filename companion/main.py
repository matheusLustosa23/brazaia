import asyncio, os, sys, websockets
from companion._json import dumps, loads  
from companion.tools.capture_handler import CAMERAS 
from companion.runtime import runtime


SERVER_WS_URL = os.getenv("SERVER_WS_URL", "ws://localhost:8000/api/v1/ws/device")
DEVICE_ID = os.getenv("DEVICE_ID", "device_macbook_pro_01")
DEVICE_NAME = os.getenv("DEVICE_NAME", "Dispositivo Principal de Trabalho")

async def run_companion_agent(device: str | None = None):
    """Gerencia a conexão ativa, rotina de rede e escuta RPC do Companion."""
    if not device:
        device = DEVICE_ID
    uri = f"{SERVER_WS_URL}/{device}"
    print(f"🚀 Inicializando Companion Client... Conectando a {uri}")
    
    try:
        async with websockets.connect(uri) as ws:
            hs = {"name": DEVICE_NAME, "handlers": runtime.list_tools()}
            if CAMERAS: hs["cameras"] = CAMERAS
            await ws.send(dumps(hs))
            print("🛰️  Metadados de handshake enviados.")
            
            welcome_msg = await ws.recv()
            welcome_data = loads(welcome_msg)
            
            if welcome_data.get("type") == "welcome":
                print("❇️  Handshake aceito pelo Servidor Central!")
                print(f"📋 Contratos permitidos pelo Server: {welcome_data.get('tools')}")
                print(f"🛠️  Handlers locais registrados na memória: {runtime.list_tools()}")
            
            print("\n📥 Monitorando barramento de ações remoto...")
            async for msg in ws:
                action = loads(msg)
                if "request_id" in action and "name" in action:
                    req_id = action["request_id"]
                    tool_name= action["name"]
                    
                    print(f"⚡ Chamada Remota Recebida: [Tool: {tool_name}] (ID: {req_id})")
                    
                    execution_result = await runtime.execute(action)
                    
                    response = {
                        "request_id": req_id,
                        "result": execution_result,
                    }
                    
                    await ws.send(dumps(response))
                    print(f"📤 Resposta enviada. ID: {req_id}")
    except websockets.exceptions.ConnectionClosed:
        print("❌ Conexão WebSocket finalizada pelo servidor.")
    except Exception as e:
        print(f"💥 Falha na runtime do agente: {e}", file=sys.stderr)                

if __name__ == "__main__":
    try:
        device = input("Digite o nome do device:")
        asyncio.run(run_companion_agent(device))
    except KeyboardInterrupt:
        print("\n👋 Companion interrompido pelo usuário.")