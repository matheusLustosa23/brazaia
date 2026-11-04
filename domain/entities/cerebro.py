# domain/entities/cerebro.py — o "cérebro" do agente: o que ele SABE (entidades + observações + relações).
#
# Modelo (inspirado no Basic Memory, mas em tabelas):
#   Entidade   = uma "coisa" de que se fala: o dono ("Você"), uma pessoa, um exercício, uma disciplina, um projeto.
#   Observação = UMA frase verdadeira sobre uma entidade, com categoria ("[preferencia] prefere resposta direta").
#                Nunca é apagada: quando muda, a velha ganha `invalido_em` e a nova aponta pra ela (`substitui`).
#   Relação    = ligação entre duas entidades ("Supino reto" —grupo→ "Peito").
#   Registro   = (M2) algo que ACONTECEU, com data e números: uma série de supino, um treino, uma sessão de estudo.
#                Observação = o que é verdade ("o ombro dói acima de 60 kg"); registro = o que houve ("ter 3×12 20 kg").
from dataclasses import dataclass

DONO = "Você"          # a entidade do próprio dono: o que estiver nela vira o NÚCLEO (sempre no contexto)
TIPO_DONO = "dono"


@dataclass(slots=True)
class Entidade:
    id: int
    tipo: str
    nome: str
    area: str = "geral"


@dataclass(slots=True)
class Observacao:
    id: int
    entidade_id: int
    entidade: str          # nome da entidade (desnormalizado p/ exibir sem join)
    tipo: str              # tipo da entidade
    categoria: str
    texto: str
    valido_desde: float
    invalido_em: float | None = None
    substitui: int | None = None


@dataclass(slots=True)
class Registro:
    id: int
    tipo: str              # serie | treino | estudo | ... (normalizado)
    quando: float          # quando ACONTECEU (não quando foi gravado)
    entidade: str | None   # o assunto: "Supino reto", "Peito", "Cálculo"
    dados: dict            # números: {"series": 3, "reps": 12, "carga_kg": 20}
    texto: str = ""        # o que foi dito ("a última foi difícil")
    sessao: int | None = None    # id do registro-sessão que agrupa este (as séries dentro do treino do dia)
    fim: float | None = None     # só em sessão: quando terminou (None = em andamento)
    eh_sessao: bool = False
    substitui: int | None = None


@dataclass(slots=True)
class Relacao:
    de: str
    tipo: str
    para: str


def norm(s: str) -> str:
    """Forma canônica p/ comparar nomes/tipos/categorias: minúsculo, sem acento, espaços colapsados.
    'Preferências ' == 'preferencias' · 'Supino  Reto' == 'supino reto'."""
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())
