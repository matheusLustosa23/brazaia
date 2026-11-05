import asyncio
import hashlib
import base64
import zipfile

import companion
import companion.connect as C
from infrastructure import companion_pacote as P


def test_wheel_valido_e_enxuto(tmp_path):
    whl, v = P.montar(str(tmp_path))
    assert whl.name == f"brazaia_companion-{v}-py3-none-any.whl"
    z = zipfile.ZipFile(whl)
    nomes = z.namelist()
    assert "companion/__init__.py" in nomes and "companion/_versao.py" in nomes
    assert "companion/models/braza.onnx" in nomes and "companion/boot/supervisor.sh" in nomes
    assert not any(n.endswith(".wav") or "__pycache__" in n or n.endswith("braza_logo_full.png") for n in nomes)
    assert whl.stat().st_size < 1_500_000
    assert z.read("companion/_versao.py").decode() == f'VERSAO = "{v}"\n'
    record = z.read(f"brazaia_companion-{v}.dist-info/RECORD").decode().splitlines()
    for linha in record:                                   # pip confere estes hashes na instalação
        nome, h, tam = linha.split(",")
        if h:
            dados = z.read(nome)
            assert h == "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(dados).digest()).rstrip(b"=").decode()
            assert int(tam) == len(dados)


def test_versao_muda_com_o_conteudo():
    arqs = P.arquivos()
    v1 = P.versao(arqs)
    arqs2 = [(r, d + b"#") if r == "connect.py" else (r, d) for r, d in arqs]
    assert P.versao(arqs2) != v1 and P.versao(arqs) == v1


def test_reaproveita_e_limpa_versao_velha(tmp_path):
    (tmp_path / "brazaia_companion-0.0.1+hvelha-py3-none-any.whl").write_bytes(b"x")
    w1, _ = P.montar(str(tmp_path))
    w2, _ = P.montar(str(tmp_path))
    assert w1 == w2 and [p.name for p in tmp_path.glob("*.whl")] == [w1.name]


def test_dev_ou_cli_nunca_se_atualiza(monkeypatch):
    chamou = []
    monkeypatch.setattr(C, "log", lambda *a: chamou.append(a))
    monkeypatch.setattr(companion, "__version__", "dev")
    monkeypatch.setattr(C, "SUPERVISIONADO", True)
    asyncio.run(C._talvez_atualizar(None, {"versao": "1.0.0+hnova", "arquivo": "x.whl", "url": "/x"}))
    monkeypatch.setattr(companion, "__version__", "1.0.0+hvelha")
    monkeypatch.setattr(C, "SUPERVISIONADO", False)           # rodando dentro do CLI
    asyncio.run(C._talvez_atualizar(None, {"versao": "1.0.0+hnova", "arquivo": "x.whl", "url": "/x"}))
    assert chamou == []


def test_texto_sempre_lf_mesmo_vindo_do_windows(tmp_path, monkeypatch):
    raiz = tmp_path / "companion"
    (raiz / "boot").mkdir(parents=True)
    (raiz / "boot" / "x.sh").write_bytes(b"#!/bin/bash\r\necho oi\r\n")
    (raiz / "a.py").write_bytes(b"x = 1\r\n")
    monkeypatch.setattr(P, "RAIZ", raiz)
    arqs = dict(P.arquivos())
    assert b"\r" not in arqs["boot/x.sh"] and b"\r" not in arqs["a.py"]
    (raiz / "a.py").write_bytes(b"x = 1\n")                 # mesmo conteúdo com LF → mesma versão
    assert P.versao() == P.versao([(r, d) for r, d in arqs.items()])
