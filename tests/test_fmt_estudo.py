from application.services.cerebro_service import fmt_dados


def test_acertos_por_extenso():
    assert fmt_dados({"acertos": 7, "total": 10}) == "acertou 7 de 10"
    assert fmt_dados({"acertos": 3}) == "3 acertos"
    assert fmt_dados({"duracao_min": 40}) == "40 min"
    assert fmt_dados({"series": 4, "reps": 6, "carga_kg": 16}) == "4 séries de 6 repetições com 16 kg"
