# domain/entities/cerebro.py — o "cérebro" do agente: o que ele SABE (entidades + observações + relações).
#
# Modelo (inspirado no Basic Memory, mas em tabelas):
#   Entidade   = uma "coisa" de que se fala: o dono ("Você"), uma pessoa, um exercício, uma disciplina, um projeto.
#   Observação = UMA frase verdadeira sobre uma entidade, com categoria ("[preferencia] prefere resposta direta").
#                Nunca é apagada: quando muda, a velha ganha `invalido_em` e a nova aponta pra ela (`substitui`).
#   Relação    = ligação entre duas entidades ("Supino reto" —grupo→ "Peito").
# Registros com data e números (treino, sessão de estudo) são o M2 — outra tabela, não entram aqui.
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
