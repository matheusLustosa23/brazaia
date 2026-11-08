import base64
import json
import os

import pytest

import companion.tools.som_handler as H
from domain.tools.guard import ToolCtx
from infrastructure.storage.file_store import FileStore
from infrastructure.tools.som import (PlayAudioInput, PlayAudioTool, RecordAudioInput, RecordAudioTool,
                                      SetVolumeInput, SetVolumeTool)


@pytest.fixture
def termux(monkeypatch, tmp_path):
    """Celular falso: guarda os comandos e responde como o Termux:API."""
    estado = {"cmds": [], "vol": {"music": 5, "ring": 0}, "grava_bytes": 40000}
    monkeypatch.setattr(H, "_IS_TERMUX", True)
    monkeypatch.setattr(H, "PASTA", str(tmp_path / "audio"))

    async def cmd(c, timeout=20.0):
        estado["cmds"].append(c)
        if c[:1] == ["termux-volume"] and len(c) == 1:
            return 0, json.dumps([{"stream": s, "volume": v, "max_volume": 15} for s, v in estado["vol"].items()])
        if c[:1] == ["termux-volume"]:
            estado["vol"][c[1]] = int(c[2]); return 0, ""
        if c[:2] == ["termux-microphone-record", "-e"]:
            open(c[-1], "wb").write(b"\xff\xf1" + b"a" * estado["grava_bytes"]); return 0, "Recording started"
        return 0, "Now Playing"

    async def dormir(_):
        return None
    monkeypatch.setattr(H, "_cmd", cmd)
    monkeypatch.setattr(H.asyncio, "sleep", dormir)
    return estado


async def test_volume_aumentar_definir_maximo(termux):
    assert await H.set_volume({"acao": "aumentar"}) == "[ok] musica: 5/15 → 8/15 (53%)"
    assert await H.set_volume({"acao": "definir", "nivel": 100}) == "[ok] musica: 8/15 → 15/15 (100%)"
    assert (await H.set_volume({"canal": "toque", "acao": "definir", "nivel": 70})).endswith("→ 10/15 (67%)")
    assert await H.set_volume({"canal": "alarme"}) == "[erro] não consegui ler o volume (Termux:API respondeu?)"


async def test_gravar_devolve_o_audio_e_detecta_microfone_bloqueado(termux):
    d = json.loads(await H.record_audio({"segundos": 5}))
    assert d["segundos"] == 5 and d["bytes"] > 2000 and base64.b64decode(d["audio_b64"])[:2] == b"\xff\xf1"
    assert ["termux-microphone-record", "-q"] in termux["cmds"]          # 1 por vez: encerra antes
    termux["grava_bytes"] = 10                                          # Android bloqueou: arquivo quase vazio
    assert (await H.record_audio({"segundos": 5})).startswith("[erro] o microfone não gravou")


async def test_bipe_gerado_e_tocado(termux):
    assert (await H.play_audio({"som": "bipe"})).startswith("[ok] tocando bipe")
    assert os.path.getsize(os.path.join(H.PASTA, "bipe.wav")) > 10000


class FakeGW:
    def __init__(self, resposta, caps=("record_audio", "play_audio", "set_volume")):
        self.resposta, self.caps, self.pedidos = resposta, set(caps), []
        self.connections = type("C", (), {"names": lambda s: ["S24"]})()

    async def capabilities(self, d):
        return self.caps

    async def request(self, device, nome, args, timeout=None):
        self.pedidos.append((device, nome, args))
        return self.resposta


async def test_server_guarda_gravacao_e_recusa_offline_ou_companion_antigo(tmp_path):
    store = FileStore(str(tmp_path / "files"))
    resp = json.dumps({"audio_b64": base64.b64encode(b"\xff\xf1audio").decode(), "ext": ".aac", "segundos": 3, "bytes": 8})
    t = RecordAudioTool(FakeGW(resp), store)
    out = await t.run(RecordAudioInput(device="S24", segundos=3), ToolCtx(fala_do_usuario="", session_id="s"))
    assert out.startswith("[áudio gravado]") and "3 s" in out
    assert (await t.run(RecordAudioInput(device="celular2"), ToolCtx(fala_do_usuario=""))).startswith("[erro] o device 'celular2' está offline")
    velho = SetVolumeTool(FakeGW("x", caps=("notify",)))
    assert "ainda não tem essa função" in await velho.run(SetVolumeInput(device="S24", acao="aumentar"), ToolCtx(fala_do_usuario=""))


async def test_server_toca_arquivo_guardado(tmp_path):
    store = FileStore(str(tmp_path / "files"))
    fid = store.put(b"\xff\xf1gravado", device="S24", session="s", kind="audio", ext=".aac")
    gw = FakeGW("[ok] tocando o áudio")
    await PlayAudioTool(gw, store).run(PlayAudioInput(device="S24", som="arquivo", file_id=fid), ToolCtx(fala_do_usuario=""))
    assert gw.pedidos[0][2]["ext"] == ".aac" and base64.b64decode(gw.pedidos[0][2]["audio_b64"]) == b"\xff\xf1gravado"
