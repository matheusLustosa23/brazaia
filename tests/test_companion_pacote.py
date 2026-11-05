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


def test_instalar_scripts_troca_so_o_que_mudou(tmp_path, monkeypatch):
    import companion.setup as st
    dados = tmp_path / ".brazaia"
    dados.mkdir()
    (tmp_path / ".termux" / "boot").mkdir(parents=True)
    monkeypatch.setattr(st, "DADOS", str(dados))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))          # no Windows o ~ vem daqui
    primeira = st.instalar_scripts()
    assert sorted(primeira) == ["healthcheck.sh", "localizacao.sh", "supervisor.sh", "termux-boot.sh"]
    assert st.instalar_scripts() == []                       # nada mudou → nada trocado
    (dados / "supervisor.sh").write_text("versao velha")
    assert st.instalar_scripts() == ["supervisor.sh"]
    assert "TSX" in (dados / "supervisor.sh").read_text()
    import os
    assert os.access(dados / "supervisor.sh", os.X_OK)


def test_ssh_so_por_chave_e_sem_duplicar(tmp_path, monkeypatch):
    import companion.setup as st
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    prefix = tmp_path / "usr"
    (prefix / "etc" / "ssh").mkdir(parents=True)
    (prefix / "etc" / "ssh" / "sshd_config").write_text("PrintMotd yes\nPasswordAuthentication yes\n")
    monkeypatch.setenv("PREFIX", str(prefix))
    monkeypatch.setattr(st.shutil, "which", lambda nome: "/bin/" + nome)
    chamados = []
    monkeypatch.setattr(st.subprocess, "run", lambda cmd, **kw: chamados.append(cmd) or type("R", (), {"stdout": "u0_a46"})())
    st.setup_ssh_termux()
    st.setup_ssh_termux()                                     # 2ª vez não duplica
    chaves = (tmp_path / ".ssh" / "authorized_keys").read_text().splitlines()
    assert len(chaves) == 2 and len(set(chaves)) == 2 and all(c.startswith("ssh-") for c in chaves)
    cfg = (prefix / "etc" / "ssh" / "sshd_config").read_text()
    assert "PasswordAuthentication no" in cfg and "PasswordAuthentication yes" not in cfg and "PrintMotd yes" in cfg
    assert ["sshd"] in chamados


def test_scripts_de_boot_nao_dependem_do_repo_antigo():
    # 05/11: o supervisor commitado ainda fazia `cd "$REPO"` (~/brazaia, apagado) → connect nunca subia
    from pathlib import Path
    for sh in (P.RAIZ / "boot").glob("*.sh"):
        texto = sh.read_text()
        assert "$REPO" not in texto and "HOME/brazaia" not in texto, sh.name
