import asyncio, sys
from companion.config import load_config
from companion.voice_turn import turno_unico, enviar_arquivo


if __name__ == "__main__":
    cfg = load_config()
    modo = sys.argv[1] if len(sys.argv) > 1 else "wake"
    if modo == "wake":
        from companion.conversation import ConversationSession
        asyncio.run(ConversationSession(cfg).loop())
    elif modo == "sendfile":
        asyncio.run(enviar_arquivo(cfg, sys.argv[2]))     # ← novo (gravador.sh chama)
    else:
        asyncio.run(turno_unico(cfg))