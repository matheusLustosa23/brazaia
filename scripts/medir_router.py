_TESTS = [
    ("renderiza um problema de equação aleatório", "render_math"),
    ("tira uma foto e me manda", "capture_image"),
    ("o que você tá vendo agora?", "capture_image"),
    ("oi, tudo bem?", "NENHUMA"),
    ("me fala as novidades", "NENHUMA"),
    ("que horas são?", "NENHUMA"),
    ("mostra a fórmula de bhaskara na tela do celular", "display_math"),
    ("anota que amanhã tenho médico", "lembrar"),
    ("abre a última foto em tela cheia", "open_image"),
    ("avisa no celular que o build terminou", "notify"),
]

from api.v1.dependencies import get_orchestrator


        
