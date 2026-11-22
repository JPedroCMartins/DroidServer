import io
import os
import zipfile

import pytest
import requests

import arquivos
import node
from arquivos import ErroArquivo

TOKEN = "ab" * 24


@pytest.fixture
def termux(monkeypatch, tmp_path):
    """PREFIX falso com o container 'w1' (layout novo do proot-distro)."""
    monkeypatch.setenv("PREFIX", str(tmp_path / "usr"))
    raiz = tmp_path / "usr/var/lib/proot-distro/containers/w1/rootfs"
    (raiz / "root").mkdir(parents=True)
    (raiz / "etc").mkdir()
    (raiz / "etc/passwd").write_text("root:x:0:0")
    return raiz / "root"


def test_listar_pastas_primeiro_e_links(termux, tmp_path):
    (termux / "b.txt").write_text("oi")
    (termux / "A").mkdir()
    (termux / ".oculto").write_text("x")
    os.symlink("/etc", termux / "fora")          # sai da home: não é seguido
    os.symlink("A", termux / "atalho")             # dentro da home
    r = arquivos.listar("w1")
    nomes = [i["nome"] for i in r["itens"]]
    assert nomes[:2] == ["A", "atalho"]
    por_nome = {i["nome"]: i for i in r["itens"]}
    assert por_nome["b.txt"] == {"nome": "b.txt", "tipo": "arquivo", "tamanho": 2,
                                 "modificado": por_nome["b.txt"]["modificado"], "link": False}
    assert por_nome["atalho"]["tipo"] == "pasta" and por_nome["atalho"]["link"] is True
    assert por_nome["fora"]["tipo"] == "link"
    assert ".oculto" in nomes and r["home"] == "/root" and r["caminho"] == ""


@pytest.mark.parametrize("caminho", ["..", "../etc", "a/../../etc", "x\0y"])
def test_caminho_nao_sai_da_home(termux, caminho):
    with pytest.raises(ErroArquivo):
        arquivos.listar("w1", caminho)


def test_link_para_fora_nao_e_seguido(termux, tmp_path):
    segredo = tmp_path / "segredo"
    segredo.mkdir()
    (segredo / "s.txt").write_text("x")
    os.symlink(segredo, termux / "fuga")
    with pytest.raises(ErroArquivo) as e:
        arquivos.listar("w1", "fuga")
    assert e.value.status == 403
    with pytest.raises(ErroArquivo):
        arquivos.salvar("w1", "fuga/novo.txt", io.BytesIO(b"x"), 1)
    assert not (segredo / "novo.txt").exists()
    # apagar o link remove só o link
    arquivos.apagar("w1", "fuga")
    assert (segredo / "s.txt").exists() and not os.path.lexists(termux / "fuga")


def test_salvar_cria_pastas_e_substitui(termux):
    arquivos.salvar("w1", "proj/src/a.py", io.BytesIO(b"print(1)"), 8)
    assert (termux / "proj/src/a.py").read_bytes() == b"print(1)"
    arquivos.salvar("w1", "proj/src/a.py", io.BytesIO(b"2"), 1)
    assert (termux / "proj/src/a.py").read_bytes() == b"2"
    assert sorted(os.listdir(termux / "proj/src")) == ["a.py"]  # sem temporário


def test_salvar_interrompido_nao_deixa_arquivo(termux):
    with pytest.raises(ErroArquivo):
        arquivos.salvar("w1", "x.bin", io.BytesIO(b"abc"), 10)
    assert os.listdir(termux) == []


def test_salvar_recusa_pasta_existente(termux):
    (termux / "dir").mkdir()
    with pytest.raises(ErroArquivo) as e:
        arquivos.salvar("w1", "dir", io.BytesIO(b"x"), 1)
    assert e.value.status == 409


def test_criar_e_apagar_pasta(termux):
    arquivos.criar_pasta("w1", "nova")
    with pytest.raises(ErroArquivo):
        arquivos.criar_pasta("w1", "nova")
    (termux / "nova/sub").mkdir()
    (termux / "nova/sub/f").write_text("x")
    os.chmod(termux / "nova/sub", 0o555)  # sem escrita, como o cache do go
    arquivos.apagar("w1", "nova")
    assert not (termux / "nova").exists()


def test_nao_apaga_a_home(termux):
    with pytest.raises(ErroArquivo) as e:
        arquivos.apagar("w1", "")
    assert e.value.status == 403
    assert termux.is_dir()


def test_worker_inexistente_ou_banco(termux, monkeypatch):
    with pytest.raises(ErroArquivo) as e:
        arquivos.listar("w2")
    assert e.value.status == 404
    with pytest.raises(ErroArquivo):
        arquivos.listar("../w1")
    monkeypatch.setattr(arquivos.banco, "existe", lambda a: True)
    with pytest.raises(ErroArquivo) as e:
        arquivos.listar("w1")
    assert "banco" in str(e.value)


def test_zip_de_pasta_sem_links(termux, tmp_path):
    (termux / "p/sub").mkdir(parents=True)
    (termux / "p/a.txt").write_text("A")
    (termux / "p/vazia").mkdir()
    (termux / "p/sub/b.txt").write_text("B")
    os.symlink("/etc/passwd", termux / "p/link")
    buf = io.BytesIO()
    arquivos.escrever_zip(str(termux / "p"), buf, "p")
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zf:
        assert sorted(zf.namelist()) == ["p/a.txt", "p/sub/b.txt", "p/vazia/"]
        assert zf.read("p/sub/b.txt") == b"B"


# ---------- HTTP (servidor de descoberta) ----------

@pytest.fixture
def servidor(termux, monkeypatch, tmp_path):
    monkeypatch.setattr(node, "PAREAMENTO_ARQUIVO", str(tmp_path / "pareamento.json"))
    for nome in ("DROID_HOST_IP", "DROID_HOST_PORT", "DROID_TOKEN"):
        monkeypatch.delenv(nome, raising=False)
    monkeypatch.setenv("DROID_REGISTRO_DIR", str(tmp_path / "registro"))
    agente = node.NodeAgent()
    agente.config = node.Config(host_ip="127.0.0.1", port=5050, token=TOKEN)
    srv = node.iniciar_servidor_descoberta(node.Descoberta(agente), porta=0)
    yield f"http://127.0.0.1:{srv.server_address[1]}/arquivos"
    srv.shutdown()


def test_http_exige_token(servidor):
    r = requests.get(servidor + "/listar", params={"alias": "w1"}, timeout=3)
    assert r.status_code == 403
    r = requests.get(servidor + "/listar", params={"alias": "w1"},
                     headers={"X-Droid-Token": "00" * 24}, timeout=3)
    assert r.status_code == 403


def test_http_envia_lista_baixa_e_apaga(servidor, termux):
    h = {"X-Droid-Token": TOKEN}
    r = requests.post(servidor + "/enviar", params={"alias": "w1", "caminho": "d/ola.txt"},
                      data=b"ola mundo", headers=h, timeout=3)
    assert r.status_code == 200 and r.json()["ok"]
    assert (termux / "d/ola.txt").read_bytes() == b"ola mundo"

    r = requests.get(servidor + "/listar", params={"alias": "w1", "caminho": "d"}, headers=h, timeout=3)
    assert [i["nome"] for i in r.json()["itens"]] == ["ola.txt"]

    r = requests.get(servidor + "/baixar", params={"alias": "w1", "caminho": "d/ola.txt"}, headers=h, timeout=3)
    assert r.content == b"ola mundo" and r.headers["X-Droid-Nome"] == "ola.txt"

    r = requests.get(servidor + "/baixar", params={"alias": "w1", "caminho": "d"}, headers=h, timeout=3)
    assert r.headers["Content-Type"] == "application/zip" and r.headers["X-Droid-Nome"] == "d.zip"
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert zf.read("d/ola.txt") == b"ola mundo"

    r = requests.post(servidor + "/pasta", params={"alias": "w1", "caminho": "nova"}, headers=h, timeout=3)
    assert r.status_code == 200 and (termux / "nova").is_dir()

    r = requests.post(servidor + "/apagar", params={"alias": "w1", "caminho": "d"}, headers=h, timeout=3)
    assert r.status_code == 200 and not (termux / "d").exists()

    r = requests.post(servidor + "/apagar", params={"alias": "w1", "caminho": "d"}, headers=h, timeout=3)
    assert r.status_code == 404 and r.json()["erro"]
