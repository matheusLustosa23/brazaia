import asyncio, sys
from companion.config import load_config
from companion.voice_turn import turno_unico, enviar_arquivo
from companion.plataform import _IS_TERMUX


if __name__ == "__main__":
    cfg = load_config()
    modo = sys.argv[1] if len(sys.argv) > 1 else "stream"
    if   modo == "sendfile":
        asyncio.run(enviar_arquivo(cfg, sys.argv[2]))
    elif modo == "wake":
        from companion.conversation import ConversationSession
        asyncio.run(ConversationSession(cfg).loop())
    elif modo == "once":
        if _IS_TERMUX:
            from companion.voice_stream import conversar_termux; asyncio.run(conversar_termux(cfg, once=True))
        else:
            from companion.voice_stream import conversar
            asyncio.run(conversar(cfg, once=True))     
    else:
        if _IS_TERMUX:
            from companion.voice_stream import conversar_termux; asyncio.run(conversar_termux(cfg))
        else:
            from companion.voice_stream import conversar
            asyncio.run(conversar(cfg))
