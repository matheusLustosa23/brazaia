import glob, random, soundfile as sf
from companion.audio import play, TTS_SAMPLE_RATE

def get_files(voice: str):
    return sorted(glob.glob(f"companion/assets/greeting_{voice}_*.wav"))

async def play_greeting(voice: str) -> None:
    print(f"play chamadno:{voice}")
    _FILES = get_files(voice)
    if not _FILES:
        return
    file = random.choice(_FILES)
    print(f"File:{file}")
    audio, _ = sf.read(file, dtype="int16")
    await play(audio.tobytes(), sample_rate=TTS_SAMPLE_RATE)
