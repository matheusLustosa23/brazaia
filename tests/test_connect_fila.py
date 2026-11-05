import asyncio

import companion.connect as C


class _WS:
    def __init__(self):
        self.enviados, self.fechou = [], False

    async def send(self, m):
        self.enviados.append(m)

    async def close(self):
        self.fechou = True


async def test_fila_sobrevive_a_erro_e_fecha_apos_3(monkeypatch):
    chamadas = {"n": 0}

    def pendentes():
        chamadas["n"] += 1
        raise OSError("disco ocupado")

    async def sem_espera(_):
        return None

    monkeypatch.setattr(C.localizacao, "pendentes", pendentes)
    monkeypatch.setattr(C, "log", lambda *_: None)
    monkeypatch.setattr(C.asyncio, "sleep", sem_espera)
    ws = _WS()
    await asyncio.wait_for(C._esvaziar_fila(ws), 2)
    assert chamadas["n"] == 3 and ws.fechou            # não morreu calada: tentou 3x e derrubou a conexão
