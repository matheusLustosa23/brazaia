import os 

def current_env() -> str:
    """Ambiente ativo: 'dev' (porta 8081, máquina dev) ou 'prod' (8080, tailnet).
    Seleciona qual .env.{env} o Settings carrega."""
    return os.getenv("APP_ENV","dev").lower()