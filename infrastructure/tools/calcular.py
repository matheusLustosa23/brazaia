from pydantic import BaseModel, Field
from domain.tools.base import Tool

class CalcularInput(BaseModel):
    expressao: str = Field(..., description="Só a expressão, ex.: '2.4 * 8**1.05', 'sqrt(16)+log(100,10)'. Sem '=' nem texto.")

class CalcularTool(Tool[CalcularInput]):
    name = "calcular"
    description = (
        "Avalia uma expressão matemática de forma EXATA (sympy). USE para QUALQUER conta numérica — "
        "potência, raiz, log, fração, fórmula com números (COCOMO a*KLOC**b, PERT, produtividade). "
        "NUNCA calcule de cabeça nem escreva um gabarito/resultado sem CHAMAR esta tool e usar o valor dela. "
        "Operadores: + - * / ** ; funções: sqrt, log(x, base), exp, pi, E."
    )
    input_schema = CalcularInput
    side = "server"
    action_class = "read"
    router_hint = "fazer uma conta/cálculo numérico exato (potência, raiz, log, fórmula)"

    async def run(self, payload: CalcularInput) -> str:
        from sympy.parsing.sympy_parser import parse_expr
        try:
            expr = parse_expr(payload.expressao, evaluate=True)   # parse seguro (só nomes do sympy, sem builtins)
            valor = expr.evalf(10)
        except Exception as e:
            return f"[erro de cálculo] não avaliei '{payload.expressao}': {type(e).__name__}"
        return f"{payload.expressao} = {valor}"
