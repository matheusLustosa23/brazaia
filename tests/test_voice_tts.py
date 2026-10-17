"""Lógica do adapter TTS (infrastructure/voice/tts.py) — sem modelo."""
from infrastructure.voice.tts import mathspeak, para_fala, SentenceChunker


def test_mathspeak():
    assert mathspeak("P(A|B)") == "P de A dado B"
    assert mathspeak("x^2") == "x ao quadrado"
    assert mathspeak("a / b") == "a dividido por b"
    assert mathspeak("√x") == "raiz quadrada de x"


def test_para_fala_tira_markdown_e_fala_math():
    assert para_fala("**nota:** P(A|B) é a condicional") == "nota: P de A dado B é a condicional"


def test_sentence_chunker():
    ch = SentenceChunker(first=20)
    assert ch.push("Oi tudo") == []                     # sem pontuação, curto → não fecha
    assert ch.push(" bem? E você") == ["Oi tudo bem?"]  # fecha na pontuação
    assert ch.flush() == "E você"                       # flush devolve o resto
