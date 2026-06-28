import logging, time

from domain.voice_contract import VoiceASR
from application.services.orchestrator import Orchestrator
logger = logging.getLogger(__name__)


class VoiceService:
    """Orquestra o ASR para UM turno de voz. Criado por conexão WS (mantém o
    buffer de áudio do turno). O modelo de ASR em si é compartilhado e stateless."""
    
    def __init__(self, asr: VoiceASR, orchestrator: Orchestrator):
        self._asr = asr
        self._audio = bytearray()
        self._orchestrator = orchestrator
        
    
    def feed(self, chunk: bytes) -> None:
        """Acumula o áudio do turno. Instantâneo — NÃO transcreve (não bloqueia o loop)."""
        self._audio.extend(chunk)
    
    async def transcribe(self) -> str | None:
        """Transcrição única do turno inteiro — chamada no turn_end (batch)."""
        if not self._audio:
            return None
        return await self._asr.transcribe(bytes(self._audio))
    
 
    def reset(self) -> None:
        self._audio = bytearray()
    
    async def reply_text(self, text: str) -> str: 
        t0 = time.monotonic()
        tokens = [
            tok 
            async for tok in self._orchestrator.run(
                session_id="voice",
                user_message=text
            )
        ]
        logger.info("voice_reply_text ms=%d chars=%d",
                    round((time.monotonic() - t0) * 1000), len("".join(tokens)))
        return "".join(tokens)
     