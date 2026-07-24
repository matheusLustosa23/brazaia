import asyncio, sys
from companion.config import load_config
from companion.conversation import ConversationSession
from companion.voice_turn import turno_unico

if __name__ == "__main__":
    cfg = load_config()
    modo = sys.argv[1] if len(sys.argv) > 1 else "wake"
    if modo == "wake":
        asyncio.run(ConversationSession(cfg).loop())
    else:
        asyncio.run(turno_unico(cfg))