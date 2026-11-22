import os
import threading
import time

import pytest
import requests

import armazenamento
import banco
import node

TOKEN = "cd" * 24


@pytest.fixture
def termux(monkeypatch, tmp_path):
    """PREFIX falso com o container 'w1' e o log do serviço dele."""
    prefix = tmp_path / "usr"
    monkeypatch.setenv("PREFIX", str(prefix))
    raiz = prefix / "var/lib/proot-distro/containers/w1/rootfs"
    (raiz / "etc").mkdir(parents=True)
    (raiz / "etc/a").write_bytes(b"x" * 10000)
    (prefix / "var/log").mkdir(parents=True)
    (prefix / "var/log/droidserver_w1.log").write_bytes(b"y" * 5000)
    (prefix / "var/log/droidserver_w1.log.1").write_bytes(b"y" * 5000)
    return raiz


def test_tamanho_dir_conta_hard_link_uma_vez_e_nao_segue_links(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d/f").write_bytes(b"x" * 8192)
    os.link(tmp_path / "d/f", tmp_path / "d/g")
    fora = tmp_path.parent / (tmp_path.name + "_fora")
    fora.mkdir()
    (fora / "grande").write_bytes(b"z" * 100000)
    os.symlink(fora, tmp_path / "d/link")
    total = armazenamento.tamanho_dir(str(tmp_path / "d"))
    assert 8192 <= total < 100000


def test_tamanho_dir_ignora_pasta_sem_permissao(tmp_path):
    (tmp_path / "ok").write_bytes(b"x" * 4096)
    trancada = tmp_path / "trancada"
    trancada.mkdir()
    (trancada / "s").write_bytes(b"x" * 4096)
    trancada.chmod(0)
    try:
        assert armazenamento.tamanho_dir(str(tmp_path)) >= 4096
    finally:
        trancada.chmod(0o700)


def test_tamanho_dir_inexistente():
    assert armazenamento.tamanho_dir("/nao/existe") == 0


def test_medir_workers_banco_e_droidserver(termux, tmp_path, monkeypatch):
    pg = os.path.join(banco.base_dir(), "pg1")
    os.makedirs(os.path.join(pg, "dados"))
    with open(os.path.join(pg, "dados", "PG_VERSION"), "wb") as f:
        f.write(b"1" * 20000)
    monkeypatch.setattr(banco, "existe", lambda a: a == "pg1")
    cfg = tmp_path / "cfg"
    (cfg / "registro").mkdir(parents=True)
    (cfg / "registro/metricas.jsonl").write_bytes(b"r" * 3000)
    r = armazenamento.medir(["w1", "pg1", "../x"], [str(cfg), str(cfg / "registro"), None])
    w1, pg1 = r["workers"]["w1"], r["workers"]["pg1"]
    assert w1["tipo"] == "linux" and w1["dados"] >= 10000 and w1["logs"] >= 10000
    assert w1["total"] == w1["dados"] + w1["logs"]
    assert pg1["tipo"] == "postgres" and pg1["dados"] >= 20000 and pg1["logs"] == 0
    assert "../x" not in r["workers"]
    assert 3000 <= r["droidserver"] < 6000  # a pasta interna conta uma vez só
    assert r["workers_total"] == w1["total"] + pg1["total"]


def test_disco_da_particao(termux):
    d = armazenamento.disco()
    assert d["total"] > 0 and d["usado"] + d["livre"] <= d["total"] and 0 <= d["percent"] <= 100


def _esperar(condicao, limite=3):
    fim = time.time() + limite
    while time.time() < fim and not condicao():
        time.sleep(0.02)
    return condicao()


def test_medidor_usa_cache_e_mede_uma_vez_por_vez(termux):
    libera, chamadas = threading.Event(), []

    def aliases():
        chamadas.append(1)
        libera.wait(3)
        return ["w1"]

    agora = [1000.0]
    m = armazenamento.Medidor(aliases, intervalo=600, relogio=lambda: agora[0])
    assert m.estado()["medindo"] is True          # primeira leitura dispara a medição
    assert m.recalcular() is False                # já há uma em andamento
    libera.set()
    assert _esperar(lambda: not m.estado()["medindo"])
    e = m.estado()
    assert e["medido_em"] == 1000.0 and "w1" in e["workers"] and len(chamadas) == 1
    agora[0] += 599
    m.estado()
    assert len(chamadas) == 1                     # ainda no cache
    agora[0] += 1
    m.estado()
    assert _esperar(lambda: len(chamadas) == 2)   # velho: mede de novo


def test_medidor_esquecer_worker(termux):
    m = armazenamento.Medidor(lambda: ["w1"])
    m.recalcular()
    assert _esperar(lambda: m.estado()["medido_em"] is not None)
    m.esquecer("w1")
    e = m.estado()
    assert e["workers"] == {} and e["workers_total"] == 0


@pytest.fixture
def servidor(termux, monkeypatch, tmp_path):
    monkeypatch.setattr(node, "PAREAMENTO_ARQUIVO", str(tmp_path / "pareamento.json"))
    for nome in ("DROID_HOST_IP", "DROID_HOST_PORT", "DROID_TOKEN"):
        monkeypatch.delenv(nome, raising=False)
    monkeypatch.setenv("DROID_REGISTRO_DIR", str(tmp_path / "registro"))
    monkeypatch.setattr(node, "_getprop", lambda nome: "")
    agente = node.NodeAgent()
    agente.config = node.Config(host_ip="127.0.0.1", port=5050, token=TOKEN)
    agora = time.time()
    for i in range(5):
        agente.registro.gravar({"t": agora - 50 + i * 10, "cpu_termux": 3.0, "ram_pct": 40.0,
                                "servicos": {"w1": {"estado": "RUNNING"}}})
    srv = node.iniciar_servidor_descoberta(node.Descoberta(agente), porta=0)
    yield f"http://127.0.0.1:{srv.server_address[1]}", agente
    srv.shutdown()


def test_http_estatisticas_exige_token(servidor):
    url, _ = servidor
    assert requests.get(url + "/estatisticas", timeout=3).status_code == 403
    r = requests.get(url + "/estatisticas", headers={"X-Droid-Token": "00" * 24}, timeout=3)
    assert r.status_code == 403
    assert requests.post(url + "/armazenamento/recalcular", timeout=3).status_code == 403


def test_http_estatisticas_com_token(servidor):
    url, _ = servidor
    h = {"X-Droid-Token": TOKEN}
    r = requests.get(url + "/estatisticas", params={"janela": "60"}, headers=h, timeout=5)
    assert r.status_code == 200
    d = r.json()
    assert d["janela_s"] == node.JANELA_MIN_S        # janela pequena demais vira o mínimo
    assert d["amostras_total"] == 5 and d["servicos"]["w1"]["rodando_pct"] == 100.0
    assert d["aparelho"]["nucleos"] and d["agente"]["pid"] == os.getpid()
    assert d["armazenamento"]["disco"]["total"] > 0
    assert "w1" in d["falhas"]
    r = requests.get(url + "/estatisticas", params={"janela": "999999999"}, headers=h, timeout=5)
    assert r.json()["janela_s"] == node.JANELA_MAX_S
    r = requests.post(url + "/armazenamento/recalcular", headers=h, timeout=3)
    assert r.status_code == 200 and r.json()["ok"] is True


def test_caminho_dos_logs_gerais(monkeypatch, tmp_path):
    monkeypatch.setenv("DROID_LOG_FILE", str(tmp_path / "n.log"))
    assert node.NodeAgent._caminho_log("@agente") == str(tmp_path / "n.log")
    assert node.NodeAgent._caminho_log("@supervisord").endswith("supervisord.log")
    assert node.NodeAgent._caminho_log("w1").endswith("droidserver_w1.log")
    assert node.NodeAgent._caminho_log("@outro") is None
    assert node.NodeAgent._caminho_log("../x") is None
