import os
import sys
from datetime import datetime, timedelta

import pytest

from app import create_app, socketio


def _routes():
    return sys.modules["app.routes"]


@pytest.fixture(scope="module")
def app_instance():
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app_instance):
    _routes().nodes_conectados.clear()
    yield app_instance.test_client()
    _routes().nodes_conectados.clear()


@pytest.fixture
def app_ctx(app_instance):
    _routes().nodes_conectados.clear()
    yield app_instance
    _routes().nodes_conectados.clear()


def test_dashboard(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"DroidServer" in resp.data


def test_api_nodes_vazio(client):
    resp = client.get("/api/nodes")
    assert resp.status_code == 200
    assert resp.get_json() == {}


def test_node_sync_registra_node(client):
    resp = client.post("/api/node_sync", json={
        "ip": "10.0.0.5", "status": "Online", "workers": ["w1", "w2"],
    })
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "tarefas": []}

    nodes = client.get("/api/nodes").get_json()
    assert "10.0.0.5" in nodes
    assert nodes["10.0.0.5"]["workers"] == ["w1", "w2"]
    assert nodes["10.0.0.5"]["status"] == "Online"


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

    resp = client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": []})
    tarefas = resp.get_json()["tarefas"]
    assert tarefas == [{"acao": "criar_worker", "imagem": "alpine", "alias": "worker_x"}]

    resp2 = client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": []})
    assert resp2.get_json()["tarefas"] == []


def test_deploy_worker_em_node_desconhecido(client):
    resp = client.post("/deploy_worker", data={"ip": "10.0.0.99", "alias": "w1"})
    assert resp.status_code == 302
    assert client.get("/api/nodes").get_json() == {}


def test_delete_worker_enfileira_tarefa(client):
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": ["w1"]})
    resp = client.get("/node/10.0.0.5/worker/w1/delete")
    assert resp.status_code == 302

    resp = client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": ["w1"]})
    assert resp.get_json()["tarefas"] == [{"acao": "deletar_worker", "alias": "w1"}]


def test_node_detail_404_para_desconhecido(client):
    resp = client.get("/node/10.0.0.99")
    assert resp.status_code == 404


def test_node_detail_200(client):
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": ["w1"]})
    resp = client.get("/node/10.0.0.5")
    assert resp.status_code == 200
    assert b"w1" in resp.data


def test_worker_terminal_404_para_desconhecido(client):
    resp = client.get("/node/10.0.0.99/worker/w1")
    assert resp.status_code == 404


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


def test_node_sync_sem_token_funciona(client):
    os.environ.pop("DROID_API_TOKEN", None)
    resp = client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": []})
    assert resp.status_code == 200


def test_node_sync_com_token_obrigatorio(client, monkeypatch):
    monkeypatch.setenv("DROID_API_TOKEN", "segredo")

    resp = client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": []})
    assert resp.status_code == 401

    resp2 = client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": [], "token": "segredo"})
    assert resp2.status_code == 200


def test_terminal_input_repassa_evento(app_ctx):
    receiver = socketio.test_client(app_ctx)
    sender = socketio.test_client(app_ctx)
    receiver.get_received()

    sender.emit("terminal_input", {"ip": "10.0.0.5", "alias": "w1", "input": "ls\n"})

    events = receiver.get_received()
    assert any(
        e["name"] == "cmd_to_10.0.0.5_w1" and e["args"][0]["input"] == "ls\n"
        for e in events
    )


def test_terminal_resize_repassa_evento(app_ctx):
    receiver = socketio.test_client(app_ctx)
    sender = socketio.test_client(app_ctx)
    receiver.get_received()

    sender.emit("terminal_resize", {"ip": "10.0.0.5", "alias": "w1", "cols": 120, "rows": 30})

    events = receiver.get_received()
    assert any(
        e["name"] == "resize_to_10.0.0.5_w1"
        and e["args"][0] == {"cols": 120, "rows": 30}
        for e in events
    )


def test_terminal_output_repassa_evento(app_ctx):
    receiver = socketio.test_client(app_ctx)
    sender = socketio.test_client(app_ctx)
    receiver.get_received()

    sender.emit("terminal_output", {"ip": "10.0.0.5", "alias": "w1", "output": "olá"})

    events = receiver.get_received()
    assert any(
        e["name"] == "output_for_10.0.0.5_w1" and e["args"][0]["output"] == "olá"
        for e in events
    )
