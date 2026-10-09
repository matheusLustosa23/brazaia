"""
voice_pipeline — pipeline de voz local para agente conversacional (primeira entrega).

Módulos (um por responsabilidade, trocáveis via injeção):
  config     — toda a configuração (modelos, endpoint vLLM, dispositivos de áudio, latência)
  capture    — microfone + buffer de áudio thread-safe
  vad        — detecção de atividade de voz + endpoint (onset/silêncio/semântico)
  stt        — reconhecimento de fala em streaming (faster-whisper | Parakeet) + LocalAgreement-2
  llm        — cliente vLLM (API OpenAI) em streaming — a COSTURA pro agente (entrega 2)
  tts        — síntese por frase (Kokoro) + segmentação de texto
  playback   — reprodução gapless com barge-in
  transcript — transcrição ao vivo (você + agente) no terminal
  pipeline   — orquestração (máquina de estados LISTEN/RESPOND + barge-in)

Rodar:  python -m voice_pipeline
"""
