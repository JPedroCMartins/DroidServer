import json
import logging
import os
import socket
import urllib.error
import sys
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

import pytest

from app import create_app, opcoes_servidor, socketio


def _routes():
    return sys.modules["app.routes"]


@pytest.fixture(scope="module")
def app_instance():
    app = create_app()
    app.config["TESTING"] = True
    # Os testes do protocolo de sync não passam pelo cadastro; os testes de
    # pareamento ligam a exigência explicitamente (fixture "cadastro_on").
    app.config["CADASTRO_OBRIGATORIO"] = False
    return app


@pytest.fixture
def client(app_instance, monkeypatch, tmp_path):
    r = _routes()
    monkeypatch.setattr(r, "CADASTRO_ARQUIVO", str(tmp_path / "nodes.json"))
    r.nodes_conectados.clear()
    r.historico.clear()
    r.cadastro.clear()
    yield app_instance.test_client()
    r.nodes_conectados.clear()
    r.historico.clear()
    r.cadastro.clear()


@pytest.fixture
def cadastro_on(app_instance):
    app_instance.config["CADASTRO_OBRIGATORIO"] = True
    yield
    app_instance.config["CADASTRO_OBRIGATORIO"] = False


@pytest.fixture
def app_ctx(app_instance):
    _routes().nodes_conectados.clear()
    yield app_instance
    _routes().nodes_conectados.clear()


def test_dashboard(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"DroidServer" in resp.data


def test_create_app_configura_logging_em_arquivo(app_instance):
    handlers = [h for h in app_instance.logger.handlers if isinstance(h, RotatingFileHandler)]
    assert handlers, "create_app deve registrar um RotatingFileHandler"
    assert app_instance.logger.level <= logging.INFO


def test_api_nodes_vazio(client):
    resp = client.get("/api/nodes")
    assert resp.status_code == 200
    assert resp.get_json() == {}


def test_node_sync_registra_node(client):
    resp = client.post("/api/node_sync", json={
        "ip": "10.0.0.5", "status": "Online", "workers": ["w1", "w2"],
        "cpu": 37.5, "mem": {"total": 8000000000, "usado": 4000000000, "percent": 50.0},
    })
    assert resp.status_code == 200
    # 1º contato: o painel também pede o histórico gravado no celular
    assert resp.get_json() == {"status": "ok", "tarefas": [], "pedir_historico": True}

    nodes = client.get("/api/nodes").get_json()
    assert "10.0.0.5" in nodes
    assert nodes["10.0.0.5"]["workers"] == ["w1", "w2"]
    assert nodes["10.0.0.5"]["status"] == "Online"
    assert nodes["10.0.0.5"]["cpu"] == 37.5
    assert nodes["10.0.0.5"]["mem"]["percent"] == 50.0


def test_node_sync_armazena_uso_sem_cpu(client):
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": [], "mem": None})
    nodes = client.get("/api/nodes").get_json()
    assert nodes["10.0.0.5"]["cpu"] is None
    assert nodes["10.0.0.5"]["mem"] is None


def test_node_sync_exige_ip(client):
    resp = client.post("/api/node_sync", json={"status": "Online"})
    assert resp.status_code == 400


def test_node_sync_atualiza_workers(client):
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": ["w1"]})
    resp = client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": ["w1", "w2"]})
    assert resp.status_code == 200

    nodes = client.get("/api/nodes").get_json()
    assert nodes["10.0.0.5"]["workers"] == ["w1", "w2"]


def test_node_sync_entrega_tarefas_pendentes(client):
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": []})
    client.post("/deploy_worker", data={"ip": "10.0.0.5", "alias": "worker_x"})

    # deploy NÃO adiciona otimistamente à lista: quem manda é o node
    nodes = client.get("/api/nodes").get_json()
    assert nodes["10.0.0.5"]["workers"] == []

    resp = client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": []})
    tarefas = resp.get_json()["tarefas"]
    assert tarefas == [{"acao": "criar_worker", "imagem": "alpine", "alias": "worker_x", "isolado": True}]

    resp2 = client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": []})
    assert resp2.get_json()["tarefas"] == []


def test_deploy_worker_em_node_desconhecido(client):
    resp = client.post("/deploy_worker", data={"ip": "10.0.0.99", "alias": "w1"})
    assert resp.status_code == 404
    assert resp.get_json()["ok"] is False
    assert client.get("/api/nodes").get_json() == {}


def test_deploy_worker_rejeita_alias_invalido(client):
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": []})
    client.post("/deploy_worker", data={"ip": "10.0.0.5", "alias": "../etc/../ bomba"})
    resp = client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": []})
    assert resp.get_json()["tarefas"] == []


def test_deploy_worker_nao_duplica_worker_existente(client):
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": ["w1"]})
    client.post("/deploy_worker", data={"ip": "10.0.0.5", "alias": "w1"})
    resp = client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": ["w1"]})
    assert resp.get_json()["tarefas"] == []


def test_delete_worker_enfileira_tarefa(client):
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": ["w1"]})
    # GET não apaga nada (pré-carregamento, robôs, <img src>)
    assert client.get("/node/10.0.0.5/worker/w1/delete").status_code == 405
    resp = client.post("/node/10.0.0.5/worker/w1/delete")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}

    # delete NÃO remove otimistamente da lista
    nodes = client.get("/api/nodes").get_json()
    assert "w1" in nodes["10.0.0.5"]["workers"]

    resp = client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": ["w1"]})
    assert resp.get_json()["tarefas"] == [{"acao": "deletar_worker", "alias": "w1"}]


def test_delete_worker_404_para_worker_desconhecido(client):
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": ["w1"]})
    assert client.post("/node/10.0.0.5/worker/nope/delete").status_code == 404


def test_node_sync_armazena_resultados_e_status(client):
    client.post("/api/node_sync", json={
        "ip": "10.0.0.5", "workers": ["w1"],
        "worker_status": {"w1": "RUNNING"},
        "tarefa_atual": {"acao": "criar_worker", "alias": "w2"},
        "resultados": [{"acao": "criar_worker", "alias": "w2", "ok": True, "msg": "ok", "ts": "12:00:00"}],
    })
    nodes = client.get("/api/nodes").get_json()
    assert nodes["10.0.0.5"]["worker_status"]["w1"] == "RUNNING"
    assert nodes["10.0.0.5"]["tarefa_atual"]["alias"] == "w2"
    assert nodes["10.0.0.5"]["resultados"][0]["ok"] is True


def test_node_detail_desconhecido_serve_spa(client):
    # A SPA é servida para qualquer IP; quem informa "não encontrado" é a API,
    # e o front exibe a mensagem a partir do 404 de /api/node/<ip>.
    resp = client.get("/node/10.0.0.99")
    assert resp.status_code == 200
    assert b"DroidServer" in resp.data
    assert client.get("/api/node/10.0.0.99").status_code == 404


def test_node_detail_200(client):
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": ["w1"]})
    resp = client.get("/node/10.0.0.5")
    assert resp.status_code == 200
    # a listagem é carregada dinamicamente via JS (sem refresh)
    assert b"/api/node/" in resp.data
    assert b"node_updated" in resp.data


def test_api_node_retorna_estado(client):
    client.post("/api/node_sync", json={
        "ip": "10.0.0.5", "workers": ["w1"],
        "worker_status": {"w1": "RUNNING"},
        "resultados": [{"acao": "criar_worker", "alias": "w1", "ok": True, "msg": "ok", "ts": "12:00"}],
    })
    data = client.get("/api/node/10.0.0.5").get_json()
    assert data["workers"] == ["w1"]
    assert data["worker_status"]["w1"] == "RUNNING"
    assert data["resultados"][0]["ok"] is True


def test_api_node_404_para_desconhecido(client):
    assert client.get("/api/node/10.0.0.99").status_code == 404


def test_worker_terminal_serve_spa(client):
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": ["w1"]})
    resp = client.get("/node/10.0.0.5/worker/w1")
    assert resp.status_code == 200
    # a view de terminal usa os eventos Socket.IO do terminal
    assert b"terminal_input" in resp.data
    assert b"output_for_" in resp.data


def test_deploy_worker_rejeita_imagem_invalida(client):
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": []})
    resp = client.post("/deploy_worker", data={"ip": "10.0.0.5", "alias": "w1", "imagem": "windows"})
    assert resp.status_code == 400
    resp = client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": []})
    assert resp.get_json()["tarefas"] == []


def test_deploy_worker_envia_isolado_e_imagem(client):
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": []})
    client.post("/deploy_worker", data={"ip": "10.0.0.5", "alias": "d1", "imagem": "debian", "isolado": "0"})
    tarefas = client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": []}).get_json()["tarefas"]
    assert tarefas == [{"acao": "criar_worker", "imagem": "debian", "alias": "d1", "isolado": False}]


def test_prune_remove_node_offline_por_muito_tempo(client):
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": []})
    _routes().nodes_conectados["10.0.0.5"]["last_seen_ts"] = datetime.now() - timedelta(seconds=999)

    client.get("/api/nodes")
    assert "10.0.0.5" not in _routes().nodes_conectados


def test_prune_mantem_node_offline_com_tarefas_pendentes(client):
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": []})
    _routes().nodes_conectados["10.0.0.5"]["last_seen_ts"] = datetime.now() - timedelta(seconds=999)
    _routes().nodes_conectados["10.0.0.5"]["tarefas_pendentes"].append({"acao": "criar_worker", "alias": "w1"})

    client.get("/api/nodes")
    assert "10.0.0.5" in _routes().nodes_conectados


def test_node_fica_offline_apos_timeout(client):
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": []})

    node = _routes().nodes_conectados["10.0.0.5"]
    node["last_seen_ts"] = datetime.now() - timedelta(seconds=60)

    nodes = client.get("/api/nodes").get_json()
    assert nodes["10.0.0.5"]["status"] == "Offline"


def test_node_volta_a_online_apos_novo_sync(client):
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": []})
    _routes().nodes_conectados["10.0.0.5"]["last_seen_ts"] = datetime.now() - timedelta(seconds=60)

    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": []})
    nodes = client.get("/api/nodes").get_json()
    assert nodes["10.0.0.5"]["status"] == "Online"


NODE_AUTH = {"papel": "node", "ip": "10.0.0.5", "token": ""}


@pytest.fixture
def terminal(app_instance, client):
    """Node 10.0.0.5 autenticado no WebSocket, um navegador com o terminal do w1
    aberto e outro navegador qualquer."""
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": ["w1"]})
    node = socketio.test_client(app_instance, auth=NODE_AUTH)
    dono = socketio.test_client(app_instance)
    outro = socketio.test_client(app_instance)
    dono.emit("terminal_assinar", {"ip": "10.0.0.5", "alias": "w1"})
    for c in (node, dono, outro):
        c.get_received()
    yield node, dono, outro
    for c in (node, dono, outro):
        if c.is_connected():
            c.disconnect()
    _routes().sockets_nodes.clear()


def test_terminal_input_e_resize_vao_so_para_o_node(terminal):
    node, dono, outro = terminal
    dono.emit("terminal_input", {"ip": "10.0.0.5", "alias": "w1", "input": "ls\n"})
    dono.emit("terminal_resize", {"ip": "10.0.0.5", "alias": "w1", "cols": 120, "rows": 30})

    recebidos = {e["name"]: e["args"][0] for e in node.get_received()}
    assert recebidos["cmd_to_10.0.0.5_w1"] == {"input": "ls\n"}
    assert recebidos["resize_to_10.0.0.5_w1"] == {"cols": 120, "rows": 30}
    # o que se digita num terminal não vaza para outros navegadores
    assert outro.get_received() == [] and dono.get_received() == []


def test_saida_do_terminal_so_para_quem_o_abriu(terminal):
    node, dono, outro = terminal
    node.emit("terminal_output", {"ip": "10.0.0.5", "alias": "w1", "output": "olá"})
    assert [e["args"][0] for e in dono.get_received()] == [{"output": "olá"}]
    assert outro.get_received() == []

    # depois de fechar o terminal, não recebe mais
    dono.emit("terminal_cancelar", {"ip": "10.0.0.5", "alias": "w1"})
    node.emit("terminal_output", {"ip": "10.0.0.5", "alias": "w1", "output": "mais"})
    assert dono.get_received() == []


def test_navegador_nao_se_passa_por_node(terminal):
    _, dono, outro = terminal
    outro.emit("terminal_output", {"ip": "10.0.0.5", "alias": "w1", "output": "falso"})
    outro.emit("logs_saida", {"ip": "10.0.0.5", "alias": "w1", "linhas": ["falso"]})
    assert dono.get_received() == []


def test_websocket_de_node_exige_token(app_instance, client, cadastro_on):
    r = _routes()
    r.cadastro["10.0.0.5"] = {"token": "ab" * 24}
    assert not socketio.test_client(app_instance, auth={**NODE_AUTH, "token": "errado"}).is_connected()
    ok = socketio.test_client(app_instance, auth={**NODE_AUTH, "token": "ab" * 24})
    assert ok.is_connected() and "10.0.0.5" in r.sockets_nodes.values()
    ok.disconnect()
    assert r.sockets_nodes == {}
    # navegadores (sem papel de node) conectam normalmente
    nav = socketio.test_client(app_instance)
    assert nav.is_connected()
    nav.disconnect()


def test_servico_sem_node_no_websocket_responde_erro(app_instance, client):
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": ["w1"]})
    nav = socketio.test_client(app_instance)
    nav.emit("servico", {"ip": "10.0.0.5", "alias": "w1", "acao": "iniciar", "req": 1})
    resp = [e["args"][0] for e in nav.get_received() if e["name"] == "servico_resposta"]
    assert resp and resp[0]["ok"] is False and "WebSocket" in resp[0]["msg"]
    nav.disconnect()


# ---------- Configuração do servidor ----------

def _limpa_env(monkeypatch):
    for nome in ("DROID_BIND", "DROID_PORT", "DROID_DEBUG"):
        monkeypatch.delenv(nome, raising=False)


def test_opcoes_servidor_padrao_sem_debug(monkeypatch):
    _limpa_env(monkeypatch)
    op = opcoes_servidor()
    assert op["host"] == "0.0.0.0"
    assert op["port"] == 5050
    assert op["debug"] is False
    # permite subir sem TTY (systemd, nohup)
    assert op["allow_unsafe_werkzeug"] is True


def test_opcoes_servidor_debug_bloqueado_na_rede(monkeypatch):
    _limpa_env(monkeypatch)
    monkeypatch.setenv("DROID_DEBUG", "1")
    assert opcoes_servidor()["debug"] is False


def test_opcoes_servidor_debug_permitido_em_localhost(monkeypatch):
    _limpa_env(monkeypatch)
    monkeypatch.setenv("DROID_DEBUG", "1")
    monkeypatch.setenv("DROID_BIND", "127.0.0.1")
    monkeypatch.setenv("DROID_PORT", "8000")
    op = opcoes_servidor()
    assert op["debug"] is True and op["host"] == "127.0.0.1" and op["port"] == 8000


def test_secret_key_nao_e_fixa(app_instance):
    assert app_instance.config["SECRET_KEY"] != "chave_secreta_tcc"
    assert len(app_instance.config["SECRET_KEY"]) >= 32


def test_node_sync_armazena_cpu_do_termux_e_por_worker(client):
    client.post("/api/node_sync", json={
        "ip": "10.0.0.5", "workers": ["w1"], "cpu": None,
        "cpu_termux": 12.5, "cpu_workers": {"w1": 10.0},
    })
    data = client.get("/api/node/10.0.0.5").get_json()
    assert data["cpu"] is None
    assert data["cpu_termux"] == 12.5
    assert data["cpu_workers"] == {"w1": 10.0}

    # o sync seguinte substitui os valores (worker removido some do mapa)
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": [], "cpu_termux": 0.4, "cpu_workers": {}})
    data = client.get("/api/node/10.0.0.5").get_json()
    assert data["cpu_termux"] == 0.4 and data["cpu_workers"] == {}


def test_deploy_worker_rejeita_archlinux(client):
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": []})
    resp = client.post("/deploy_worker", data={"ip": "10.0.0.5", "alias": "a1", "imagem": "archlinux"})
    assert resp.status_code == 400

def test_resultados_ficam_visiveis_apos_o_sync_seguinte(client):
    """O agente envia cada resultado uma vez; o host não pode apagá-lo no sync seguinte."""
    r1 = {"acao": "criar_worker", "alias": "w1", "ok": False, "msg": "falhou", "ts": "12:00:01"}
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "resultados": [r1]})
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "resultados": []})
    assert client.get("/api/node/10.0.0.5").get_json()["resultados"] == [r1]


def test_resultados_reenviados_nao_duplicam_e_tem_limite(client):
    r1 = {"acao": "criar_worker", "alias": "w1", "ok": True, "msg": "ok", "ts": "12:00:01"}
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "resultados": [r1]})
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "resultados": [r1]})  # resposta perdida -> reenvio
    assert len(client.get("/api/node/10.0.0.5").get_json()["resultados"]) == 1

    for i in range(30):
        client.post("/api/node_sync", json={"ip": "10.0.0.5", "resultados": [
            {"acao": "deletar_worker", "alias": f"w{i}", "ok": True, "msg": "ok", "ts": f"12:01:{i:02d}"}]})
    res = client.get("/api/node/10.0.0.5").get_json()["resultados"]
    assert len(res) == 20 and res[-1]["alias"] == "w29"


# ---------- Histórico para o gráfico ----------

def test_historico_acumula_cpu_e_ram_por_sync(client):
    for cpu, ram in ((1.0, 50.0), (25.0, 55.5), (None, 60.0)):
        client.post("/api/node_sync", json={"ip": "10.0.0.5", "cpu_termux": cpu, "mem": {"percent": ram}})
    resp = client.get("/api/node/10.0.0.5/historico")
    assert resp.status_code == 200
    amostras = resp.get_json()["amostras"]
    assert [(a["cpu"], a["ram"]) for a in amostras] == [(1.0, 50.0), (25.0, 55.5), (None, 60.0)]
    assert amostras[0]["t"] <= amostras[-1]["t"]
    # o histórico não vai junto na listagem geral
    assert "historico" not in client.get("/api/nodes").get_json()["10.0.0.5"]


def test_historico_tem_limite_e_404(client, monkeypatch):
    monkeypatch.setattr(_routes(), "MAX_HISTORICO", 5)
    _routes().historico.clear()
    for i in range(12):
        client.post("/api/node_sync", json={"ip": "10.0.0.5", "cpu_termux": float(i), "mem": {"percent": 1.0}})
    amostras = client.get("/api/node/10.0.0.5/historico").get_json()["amostras"]
    assert [a["cpu"] for a in amostras] == [7.0, 8.0, 9.0, 10.0, 11.0]
    assert client.get("/api/node/10.0.0.99/historico").status_code == 404


def test_painel_recem_ligado_pede_o_historico_ao_node(client):
    """O painel pode ser desligado: o histórico vive no celular e volta no sync."""
    r1 = client.post("/api/node_sync", json={"ip": "10.0.0.5", "cpu_termux": 3.0, "mem": {"percent": 50.0}})
    assert r1.get_json().get("pedir_historico") is True
    r2 = client.post("/api/node_sync", json={"ip": "10.0.0.5", "cpu_termux": 4.0, "mem": {"percent": 51.0}})
    assert "pedir_historico" not in r2.get_json()


def test_historico_do_node_substitui_o_cache(client):
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "cpu_termux": 9.0, "mem": {"percent": 1.0}})
    gravado = [{"t": 100.0, "cpu": 1.0, "ram": 40.0}, {"t": 110.0, "cpu": None, "ram": 41.0},
               {"t": "x"}, "lixo", {"t": 120.0, "cpu": True, "ram": "50"}]
    resp = client.post("/api/node_sync", json={"ip": "10.0.0.5", "cpu_termux": 2.0, "mem": {"percent": 42.0},
                                               "historico": gravado})
    assert "pedir_historico" not in resp.get_json()
    amostras = client.get("/api/node/10.0.0.5/historico").get_json()["amostras"]
    assert [(a["cpu"], a["ram"]) for a in amostras] == [(1.0, 40.0), (None, 41.0), (None, None), (2.0, 42.0)]


# ---------- Cadastro de nodes (pareamento pelo painel) ----------

TOKEN = "ab" * 24


def _cadastrar(ip="192.168.1.7", token=TOKEN):
    _routes().cadastro[ip] = {"token": token, "modelo": "Xiaomi 2311DRK48G"}


def test_sync_recusado_para_node_nao_cadastrado(client, cadastro_on):
    resp = client.post("/api/node_sync", json={"ip": "192.168.1.7", "workers": []})
    assert resp.status_code == 401
    resp = client.post("/api/node_sync", json={"ip": "192.168.1.7", "token": TOKEN})
    assert resp.status_code == 401
    assert client.get("/api/nodes").get_json() == {}


def test_sync_aceito_com_token_do_cadastro(client, cadastro_on):
    _cadastrar()
    assert client.post("/api/node_sync", json={"ip": "192.168.1.7", "token": "cd" * 24}).status_code == 401
    assert client.post("/api/node_sync", json={"ip": "192.168.1.7", "token": TOKEN}).status_code == 200
    node = client.get("/api/nodes").get_json()["192.168.1.7"]
    assert node["status"] == "Online" and node["cadastrado"] is True and node["modelo"] == "Xiaomi 2311DRK48G"


def test_node_que_muda_de_ip_e_reconhecido_pelo_token(client, cadastro_on):
    """Reboot com DHCP: o celular volta com outro IP e o mesmo token."""
    _cadastrar("192.168.1.7")
    client.post("/api/node_sync", json={"ip": "192.168.1.7", "token": TOKEN, "cpu_termux": 1.0, "mem": {"percent": 50}})
    client.post("/api/node_sync", json={"ip": "192.168.1.4", "token": TOKEN, "cpu_termux": 2.0, "mem": {"percent": 51}})

    nodes = client.get("/api/nodes").get_json()
    assert list(nodes) == ["192.168.1.4"]
    assert list(_routes().cadastro) == ["192.168.1.4"]
    amostras = client.get("/api/node/192.168.1.4/historico").get_json()["amostras"]
    assert [a["cpu"] for a in amostras] == [1.0, 2.0]  # histórico acompanha
    salvo = json.loads(open(_routes().CADASTRO_ARQUIVO).read())
    assert list(salvo) == ["192.168.1.4"]


@pytest.mark.parametrize("ip_invalido", ["teste", "8.8.8.8", "192.168.1.5/../x", "::1"])
def test_ip_invalido_nao_move_o_cadastro(client, cadastro_on, ip_invalido):
    """Mesmo com o token certo, o cadastro só migra para um IPv4 de rede local."""
    _cadastrar("192.168.1.7")
    resp = client.post("/api/node_sync", json={"ip": ip_invalido, "token": TOKEN})
    assert resp.status_code == 200
    assert list(_routes().cadastro) == ["192.168.1.7"]
    assert list(client.get("/api/nodes").get_json()) == ["192.168.1.7"]


def test_cadastrado_sem_contato_aparece_como_aguardando(client, cadastro_on):
    _cadastrar()
    node = client.get("/api/nodes").get_json()["192.168.1.7"]
    assert node["status"] == "Aguardando" and node["aguardando"] is True
    assert client.get("/api/node/192.168.1.7").status_code == 200


def _node_falso(monkeypatch, parear=(200, {"ok": True}), responde=True):
    """Simula o agente na porta de descoberta; registra as requisições."""
    chamadas = []

    def fake_http(metodo, url, dados=None, timeout=3.0):
        chamadas.append((metodo, url, dados))
        if url.endswith("/droidserver"):
            if not responde:
                return None, {"erro": "timeout"}
            return 200, {"droidserver": True, "modelo": "Xiaomi 2311DRK48G", "android": "16", "pareado": False}
        if url.endswith("/parear"):
            return parear
        if url.endswith("/desparear"):
            return 200, {"ok": True}
        return 404, {}

    monkeypatch.setattr(_routes(), "_http_json", fake_http)
    return chamadas


def test_adicionar_node_pareia_e_salva_cadastro(client, monkeypatch):
    chamadas = _node_falso(monkeypatch)
    resp = client.post("/api/nodes/adicionar", json={"ip": "192.168.1.7"})
    assert resp.status_code == 200 and resp.get_json()["modelo"] == "Xiaomi 2311DRK48G"

    metodo, url, dados = chamadas[-1]
    assert (metodo, url) == ("POST", "http://192.168.1.7:5051/parear")
    assert dados["host_port"] == 5050 and len(dados["token"]) == 48
    entrada = _routes().cadastro["192.168.1.7"]
    assert entrada["token"] == dados["token"]  # o mesmo token enviado ao node
    salvo = json.loads(open(_routes().CADASTRO_ARQUIVO).read())
    assert salvo["192.168.1.7"]["token"] == dados["token"]
    assert oct(os.stat(_routes().CADASTRO_ARQUIVO).st_mode & 0o777) == "0o600"


def test_adicionar_node_erros(client, monkeypatch):
    _node_falso(monkeypatch, responde=False)
    assert client.post("/api/nodes/adicionar", json={"ip": "192.168.1.7"}).status_code == 404
    for ip in ("8.8.8.8", "abc", "", "192.168.1.300"):
        assert client.post("/api/nodes/adicionar", json={"ip": ip}).status_code == 400

    _node_falso(monkeypatch, parear=(409, {"ok": False, "erro": "Node já pareado com 192.168.1.20."}))
    resp = client.post("/api/nodes/adicionar", json={"ip": "192.168.1.7"})
    assert resp.status_code == 409 and "192.168.1.20" in resp.get_json()["erro"]
    assert _routes().cadastro == {}


def test_remover_node_despareia_e_apaga(client, monkeypatch):
    chamadas = _node_falso(monkeypatch)
    _cadastrar()
    client.post("/api/node_sync", json={"ip": "192.168.1.7", "token": TOKEN})
    resp = client.post("/api/nodes/192.168.1.7/remover")
    assert resp.get_json() == {"ok": True, "despareado": True}
    assert chamadas[-1] == ("POST", "http://192.168.1.7:5051/desparear", {"token": TOKEN})
    assert client.get("/api/nodes").get_json() == {}
    assert client.post("/api/nodes/192.168.1.7/remover").status_code == 404


def test_varredura_encontra_nodes(client, monkeypatch):
    sondados = []

    def fake_sondar(ip, timeout=0.8):
        sondados.append(ip)
        if ip == "192.168.50.3":
            return {"droidserver": True, "modelo": "Xiaomi", "android": "16", "pareado": True, "host": "192.168.50.1:5050"}
        return None

    monkeypatch.setattr(_routes(), "_sondar_node", fake_sondar)
    _cadastrar("192.168.50.3")
    data = client.post("/api/varredura", json={"rede": "192.168.50.0/29"}).get_json()
    assert data["ok"] is True and data["enderecos"] == 6 and len(sondados) == 6
    assert data["nodes"] == [{"ip": "192.168.50.3", "modelo": "Xiaomi", "android": "16",
                              "pareado": True, "host": "192.168.50.1:5050", "cadastrado": True}]


@pytest.mark.parametrize("rede", ["8.8.8.0/24", "10.0.0.0/16", "banana", "fe80::/64"])
def test_varredura_recusa_redes_invalidas(client, rede):
    assert client.post("/api/varredura", json={"rede": rede}).status_code == 400


def test_api_rede_sugere_a_24_do_host(client, monkeypatch):
    monkeypatch.setattr(_routes(), "_ip_local", lambda: "192.168.1.10")
    assert client.get("/api/rede").get_json() == {"ip_host": "192.168.1.10", "rede": "192.168.1.0/24"}


# ---------- Aba Serviço: comandos e logs ao vivo ----------

def _eventos(cliente, nome):
    return [e["args"][0] for e in cliente.get_received() if e["name"] == nome]


@pytest.fixture
def ambiente_servico(app_instance, client):
    """Um node online (10.0.0.5) e três clientes Socket.IO: o node e dois navegadores."""
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": ["w1"]})
    node = socketio.test_client(app_instance, auth=NODE_AUTH)
    nav_a = socketio.test_client(app_instance)
    nav_b = socketio.test_client(app_instance)
    for c in (node, nav_a, nav_b):
        c.get_received()
    yield node, nav_a, nav_b
    for c in (node, nav_a, nav_b):
        if c.is_connected():
            c.disconnect()
    _routes().assinantes_logs.clear()
    _routes().sockets_nodes.clear()


def test_comando_de_servico_vai_ao_node_e_volta_so_para_quem_pediu(ambiente_servico):
    node, nav_a, nav_b = ambiente_servico
    nav_a.emit("servico", {"ip": "10.0.0.5", "alias": "w1", "acao": "reiniciar", "req": 3})

    pedido = _eventos(node, "servico_to_10.0.0.5")[0]
    assert (pedido["alias"], pedido["acao"], pedido["req"]) == ("w1", "reiniciar", 3)

    node.emit("servico_resposta", {**pedido, "ip": "10.0.0.5", "ok": True, "msg": "Serviço reiniciado.",
                                   "servico": {"estado": "RUNNING", "pid": 99}})
    resposta = _eventos(nav_a, "servico_resposta")
    assert len(resposta) == 1 and resposta[0]["ok"] is True and "sid" not in resposta[0]
    assert _eventos(nav_b, "servico_resposta") == []
    # o estado guardado já reflete a resposta, sem esperar o próximo sync
    assert _routes().nodes_conectados["10.0.0.5"]["servicos"]["w1"]["pid"] == 99


@pytest.mark.parametrize("pedido", [
    {"ip": "10.0.0.99", "alias": "w1", "acao": "iniciar"},    # node offline
    {"ip": "10.0.0.5", "alias": "../x", "acao": "iniciar"},   # alias inválido
    {"ip": "10.0.0.5", "alias": "w1", "acao": "rm -rf"},      # ação desconhecida
])
def test_comando_de_servico_invalido_nao_chega_ao_node(ambiente_servico, pedido):
    node, nav_a, _ = ambiente_servico
    nav_a.emit("servico", {**pedido, "req": 1})
    assert [e for e in node.get_received() if e["name"].startswith("servico_to_")] == []
    assert _eventos(nav_a, "servico_resposta")[0]["ok"] is False


def test_logs_so_para_quem_assina_e_cancelados_quando_todos_saem(ambiente_servico):
    node, nav_a, nav_b = ambiente_servico
    nav_a.emit("logs_assinar", {"ip": "10.0.0.5", "alias": "w1"})
    assert _eventos(node, "logs_to_10.0.0.5") == [{"alias": "w1", "acao": "assinar"}]

    node.emit("logs_saida", {"ip": "10.0.0.5", "alias": "w1", "linhas": ["oi"], "inicial": True})
    assert _eventos(nav_a, "logs_saida") == [{"alias": "w1", "linhas": ["oi"], "inicial": True}]
    assert _eventos(nav_b, "logs_saida") == []

    nav_b.emit("logs_assinar", {"ip": "10.0.0.5", "alias": "w1"})
    node.get_received()
    nav_a.disconnect()                      # um sai: o node continua enviando
    assert _eventos(node, "logs_to_10.0.0.5") == []
    nav_b.emit("logs_cancelar", {"ip": "10.0.0.5", "alias": "w1"})  # o último sai
    assert _eventos(node, "logs_to_10.0.0.5") == [{"alias": "w1", "acao": "cancelar"}]
    assert _routes().assinantes_logs == {}


def test_node_sync_guarda_estado_dos_servicos(client):
    servicos = {"w1": {"estado": "RUNNING", "pid": 1, "tem_script": True, "autostart": True}}
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": ["w1"], "servicos": servicos})
    assert client.get("/api/node/10.0.0.5").get_json()["servicos"] == servicos


def test_rota_do_terminal_serve_a_spa(client):
    assert client.get("/node/10.0.0.5/worker/w1/terminal").status_code == 200


def test_sync_reconcilia_logs_depois_de_o_agente_reiniciar(ambiente_servico, client):
    node, nav_a, _ = ambiente_servico
    nav_a.emit("logs_assinar", {"ip": "10.0.0.5", "alias": "w1"})
    node.get_received()

    # agente reiniciou: não acompanha mais nada, e ainda lê um log que ninguém vê
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": ["w1", "w2"], "logs_ativos": ["w2"]})
    pedidos = _eventos(node, "logs_to_10.0.0.5")
    assert {"alias": "w1", "acao": "assinar"} in pedidos
    assert {"alias": "w2", "acao": "cancelar"} in pedidos

    # já alinhado: nada a fazer; agente antigo (sem o campo): idem
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": ["w1"], "logs_ativos": ["w1"]})
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": ["w1"]})
    assert _eventos(node, "logs_to_10.0.0.5") == []


def test_readicionar_node_envia_o_token_atual(client, monkeypatch):
    """Se o PC do painel mudou de IP, o node só aceita o pareamento com o token atual."""
    chamadas = _node_falso(monkeypatch)
    client.post("/api/nodes/adicionar", json={"ip": "192.168.1.7"})
    primeiro = chamadas[-1][2]
    assert "token_atual" not in primeiro          # cadastro novo: não há token anterior

    client.post("/api/nodes/adicionar", json={"ip": "192.168.1.7"})
    segundo = chamadas[-1][2]
    assert segundo["token_atual"] == primeiro["token"]
    assert _routes().cadastro["192.168.1.7"]["token"] == segundo["token"] != primeiro["token"]


def test_painel_nao_depende_de_internet(client):
    """Sem CDNs: numa rede sem internet (laboratório, defesa) o painel abre igual."""
    import re
    html = client.get("/").get_data(as_text=True)
    assert not re.search(r"""(src|href)=["']https?://""", html)
    recursos = re.findall(r"""(?:src|href)=["'](/static/[^"']+)""", html)
    assert len(recursos) >= 6
    for caminho in recursos:
        resp = client.get(caminho)
        assert resp.status_code == 200 and len(resp.data) > 500, caminho
        resp.close()
    css = client.get("/static/vendor/inter.css")
    for fonte in re.findall(r"url\('([^']+)'\)", css.get_data(as_text=True)):
        assert client.get("/static/vendor/" + fonte).status_code == 200


@pytest.mark.parametrize("rota,dados", [
    ("/node/10.0.0.5/worker/w1/delete", None),
    ("/deploy_worker", {"ip": "10.0.0.5", "alias": "w2", "imagem": "alpine"}),
    ("/api/nodes/adicionar", {"ip": "192.168.1.9"}),
])
def test_post_de_outro_site_e_recusado(client, rota, dados):
    """Uma página de outro site não pode apagar/criar workers nem cadastrar nodes (CSRF)."""
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": ["w1"]})
    resp = client.post(rota, data=dados, headers={"Origin": "http://site-malicioso.example"})
    assert resp.status_code == 403
    assert _routes().nodes_conectados["10.0.0.5"]["tarefas_pendentes"] == []


def test_post_do_proprio_painel_e_do_agente_sao_aceitos(client):
    # o agente (requests) não manda Origin; o painel manda a própria origem
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": ["w1"]})
    resp = client.post("/node/10.0.0.5/worker/w1/delete", headers={"Origin": "http://localhost"})
    assert resp.status_code == 200


def test_websocket_recusa_outro_site_e_aceita_o_painel_e_o_agente(client):
    """Handshake do Engine.IO: Origin de outro site é recusado (CORS restrito)."""
    url = "/socket.io/?EIO=4&transport=polling"
    assert client.get(url, headers={"Origin": "http://site-malicioso.example"}).status_code == 400
    assert client.get(url, headers={"Origin": "http://localhost"}).status_code == 200
    assert client.get(url).status_code == 200  # agente: sem Origin


# ---------- Login do painel (DROID_PANEL_PASSWORD) ----------

@pytest.fixture
def com_senha(app_instance, client):
    app_instance.config["PANEL_PASSWORD"] = "segredo-do-tcc"
    yield client
    app_instance.config["PANEL_PASSWORD"] = ""


def test_sem_login_paginas_redirecionam_e_api_responde_401(com_senha):
    c = com_senha
    resp = c.get("/node/10.0.0.5")
    assert resp.status_code == 302 and resp.headers["Location"].startswith("/login?proximo=/node/10.0.0.5")
    assert c.get("/api/nodes").status_code == 401
    assert c.post("/deploy_worker", data={"ip": "x", "alias": "y"}).status_code == 401
    # o que precisa ficar livre: login, arquivos estáticos e o sync dos nodes
    assert c.get("/login").status_code == 200
    assert c.get("/static/vendor/inter.css").status_code == 200
    assert c.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": []}).status_code == 200


def test_login_errado_e_certo(com_senha, monkeypatch):
    monkeypatch.setattr(_routes().time, "sleep", lambda s: None)
    c = com_senha
    resp = c.post("/login", data={"senha": "chute", "proximo": "/"})
    assert resp.status_code == 401 and "Senha incorreta" in resp.get_data(as_text=True)
    assert c.get("/api/nodes").status_code == 401

    resp = c.post("/login", data={"senha": "segredo-do-tcc", "proximo": "/node/10.0.0.5"})
    assert resp.status_code == 302 and resp.headers["Location"] == "/node/10.0.0.5"
    assert c.get("/api/nodes").status_code == 200
    assert "Sair" in c.get("/").get_data(as_text=True)

    c.post("/logout")
    assert c.get("/api/nodes").status_code == 401


def test_login_nao_redireciona_para_outro_site(com_senha):
    for destino in ("https://site-malicioso.example", "//site-malicioso.example", "/\\\\site.example"):
        resp = com_senha.post("/login", data={"senha": "segredo-do-tcc", "proximo": destino})
        assert resp.headers["Location"] == "/"


def test_websocket_do_painel_exige_login_mas_o_do_node_nao(app_instance, com_senha):
    assert not socketio.test_client(app_instance, flask_test_client=com_senha).is_connected()
    node = socketio.test_client(app_instance, auth=NODE_AUTH)
    assert node.is_connected()
    node.disconnect()
    _routes().sockets_nodes.clear()

    com_senha.post("/login", data={"senha": "segredo-do-tcc"})
    nav = socketio.test_client(app_instance, flask_test_client=com_senha)
    assert nav.is_connected()
    nav.disconnect()


def test_sem_senha_o_painel_fica_aberto(client):
    assert client.get("/").status_code == 200
    assert client.get("/login").status_code == 302
    assert "Sair" not in client.get("/").get_data(as_text=True)


# ---------- Aba Serviço: testar o endereço do serviço ----------

def _sync_com_porta(client, porta):
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": ["w1"],
                                        "servicos": {"w1": {"estado": "RUNNING", "porta": porta}}})


class _Resp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_testar_endereco_ok(client, monkeypatch):
    _sync_com_porta(client, 8080)
    urls = []
    monkeypatch.setattr(_routes(), "_abrir_servico",
                        lambda url, timeout=None: (urls.append((url, timeout)), _Resp())[1])
    r = client.post("/api/node/10.0.0.5/worker/w1/testar").get_json()
    assert r["ok"] is True and r["status"] == 200 and r["ms"] >= 0 and r["erro"] is None
    assert r["url"] == "http://10.0.0.5:8080/" and urls == [("http://10.0.0.5:8080/", 3)]


def test_testar_sem_porta(client):
    _sync_com_porta(client, None)
    r = client.post("/api/node/10.0.0.5/worker/w1/testar").get_json()
    assert r["ok"] is False and r["url"] is None and "porta não informada" in r["erro"]


@pytest.mark.parametrize("exc,trecho", [(ConnectionRefusedError(), "não respondeu"),
                                        (socket.timeout(), "3 s")])
def test_testar_recusado_e_timeout(client, monkeypatch, exc, trecho):
    _sync_com_porta(client, 8080)

    def falha(url, timeout=None):
        raise exc
    monkeypatch.setattr(_routes(), "_abrir_servico", falha)
    r = client.post("/api/node/10.0.0.5/worker/w1/testar").get_json()
    assert r["ok"] is False and trecho in r["erro"]


def test_testar_erro_http_ainda_prova_que_esta_no_ar(client, monkeypatch):
    _sync_com_porta(client, 8080)

    def http_404(url, timeout=None):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    monkeypatch.setattr(_routes(), "_abrir_servico", http_404)
    r = client.post("/api/node/10.0.0.5/worker/w1/testar").get_json()
    assert r["ok"] is True and r["status"] == 404


def test_testar_node_ou_worker_desconhecido(client):
    _sync_com_porta(client, 8080)
    assert client.post("/api/node/10.9.9.9/worker/w1/testar").status_code == 404
    assert client.post("/api/node/10.0.0.5/worker/nope/testar").status_code == 404


def test_testar_nao_segue_redirecionamento(client):
    """Um 302 já prova que o serviço está no ar; seguir o Location sairia do Worker
    (e podia passar de 3 s ou acessar outro endereço a partir do Host)."""
    import http.server
    import threading
    import time as _t

    class Redireciona(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://10.255.255.1:9/")  # não roteável
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Redireciona)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        client.post("/api/node_sync", json={"ip": "127.0.0.1", "workers": ["w1"],
                                            "servicos": {"w1": {"porta": srv.server_address[1]}}})
        t0 = _t.monotonic()
        r = client.post("/api/node/127.0.0.1/worker/w1/testar").get_json()
        assert r["ok"] is True and r["status"] == 302
        assert _t.monotonic() - t0 < 2
    finally:
        srv.shutdown()


def test_testar_porta_invalida_vinda_do_node(client):
    for porta in ("abc", 99999, True):
        client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": ["w1"],
                                            "servicos": {"w1": {"porta": porta}}})
        resp = client.post("/api/node/10.0.0.5/worker/w1/testar")
        assert resp.status_code == 200 and "porta não informada" in resp.get_json()["erro"]
