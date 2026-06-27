import logging

from domain.voice_contract import VoiceASR

logger = logging.getLogger(__name__)


class VoiceService:
    """Orquestra o ASR para UM turno de voz. Criado por conexão WS (mantém o
    buffer de áudio do turno). O modelo de ASR em si é compartilhado e stateless."""
    
    def __init__(self, asr: VoiceASR):
        self._asr = asr
        self._audio = bytearray()
    
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
     