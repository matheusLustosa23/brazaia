import webrtcvad

SAMPLE_RATE = 16_000
FRAME_MS = 30  # webrtcvad aceita 10/20/30ms; capture_chunks já entrega 30ms

class SilenceEndpointer:
    """VAD de endpointing (device): sinaliza fim de fala após silêncio contínuo.
    Encapsula o webrtcvad e o acúmulo de silêncio — testável, sem time.monotonic no loop."""
    
    def __init__(self, aggressiveness: int = 2, silence_ms: int = 1500):
        self._vad = webrtcvad.Vad(aggressiveness)
        self._frame_bytes = int(SAMPLE_RATE * FRAME_MS / 1000) * 2
        self._silence_ms = silence_ms
        self._silence_acc = 0
        
    def is_speech(self, chunk: bytes, sample_rate: int = SAMPLE_RATE) -> bool:
        return any(
            self._vad.is_speech(chunk[i: i + self._frame_bytes], sample_rate)
            for i in range(0 , len(chunk) - self._frame_bytes + 1, self._frame_bytes)
        )
    
    def ended(self, chunk: bytes) -> bool:
        """True quando o silêncio acumulado atinge o limite → encerrar o turno."""
        if self.is_speech(chunk):
            self._silence_acc = 0
            return False
        self._silence_acc += FRAME_MS * max(1, len(chunk)  // self._frame_bytes)
        return self._silence_acc >= self._silence_ms
    
    def reset(self) -> None:
        self._silence_acc = 0