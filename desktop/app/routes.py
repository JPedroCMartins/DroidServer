import logging
import os
import re
from datetime import datetime, timedelta

from flask import current_app as app
from flask import render_template, request, jsonify, redirect, url_for
from flask_socketio import emit
from . import socketio

logger = logging.getLogger("droidserver.routes")

nodes_conectados = {}

# Segundos sem contato antes de um node ser marcado como Offline.
# O agente sincroniza a cada 10s, então 25s é tolerante a falhas pontuais.
STALE_TIMEOUT = 25
# Segundos offline sem tarefas pendentes antes do node ser removido do painel.
PRUNE_TIMEOUT = 180

# Alias de worker: caracteres seguros (usado em caminhos, serviços e eventos WS).
ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _authorized(dados):
    """Valida o token opcional. Sem DROID_API_TOKEN no host, nada é exigido."""
    token = os.getenv("DROID_API_TOKEN", "")
    if not token:
        return True
    return dados.get("token") == token


def _alias_valido(alias):
    return bool(alias) and bool(ALIAS_RE.fullmatch(alias))


def _prune_nodes():
    """Remove nodes offline há muito tempo que não tenham tarefas pendentes."""
    agora = datetime.now()
    for ip in list(nodes_conectados):
        node = nodes_conectados[ip]
        ultimo = node.get("last_seen_ts")
        if ultimo is None:
            continue
        offline_muito = (agora - ultimo) > timedelta(seconds=PRUNE_TIMEOUT)
        sem_tarefas = not node.get("tarefas_pendentes")
        if offline_muito and sem_tarefas:
            del nodes_conectados[ip]
            logger.info("Node %s removido do painel (offline há %ds)", ip, int((agora - ultimo).total_seconds()))


def _estado_publico(ip, node):
    """Devolve uma cópia do node com status/último contato calculados no momento."""
    info = dict(node)
    info["ip"] = ip
    info["workers"] = list(node.get("workers", []))

    ultimo = node.get("last_seen_ts")
    if ultimo is None or (datetime.now() - ultimo) > timedelta(seconds=STALE_TIMEOUT):
        info["status"] = "Offline"
    else:
        info["status"] = node.get("status", "Online")

    info["last_seen"] = node.get("last_seen", "—")
    return info


@app.route('/')
def dashboard():
    _prune_nodes()
    nodes = {ip: _estado_publico(ip, node) for ip, node in nodes_conectados.items()}
    return render_template('index.html', nodes=nodes)


@app.route('/node/<ip>')
def node_detail(ip):
    _prune_nodes()
    if ip not in nodes_conectados:
        return "Node não encontrado ou offline.", 404

    node_info = _estado_publico(ip, nodes_conectados[ip])
    return render_template('node_detail.html', ip=ip, node=node_info)


@app.route('/node/<ip>/worker/<alias>')
def worker_terminal(ip, alias):
    if ip not in nodes_conectados:
        return "Node não encontrado.", 404
    if not _alias_valido(alias) or alias not in nodes_conectados[ip]["workers"]:
        return "Worker não encontrado neste node.", 404

    return render_template('terminal.html', ip=ip, alias=alias)


@app.route('/node/<ip>/worker/<alias>/delete')
def delete_worker(ip, alias):
    if ip not in nodes_conectados:
        return "Node não encontrado.", 404
    if not _alias_valido(alias) or alias not in nodes_conectados[ip]["workers"]:
        return "Worker não encontrado neste node.", 404

    # Não remove da lista aqui: a lista é autoritativa do node (via sync).
    nova_tarefa = {
        "acao": "deletar_worker",
        "alias": alias
    }
    nodes_conectados[ip]["tarefas_pendentes"].append(nova_tarefa)
    logger.info("Tarefa enfileirada: deletar worker '%s' do node %s", alias, ip)
    return redirect(url_for('node_detail', ip=ip))


@app.route('/deploy_worker', methods=['POST'])
def deploy_worker():
    ip_alvo = request.form.get('ip')
    alias = request.form.get('alias', '').strip()

    if ip_alvo not in nodes_conectados:
        return redirect(url_for('node_detail', ip=ip_alvo))

    if not _alias_valido(alias):
        logger.warning("Alias inválido rejeitado no deploy: %r", alias)
        return redirect(url_for('node_detail', ip=ip_alvo))

    if alias in nodes_conectados[ip_alvo]["workers"]:
        logger.info("Worker '%s' já existe no node %s; nada a fazer.", alias, ip_alvo)
        return redirect(url_for('node_detail', ip=ip_alvo))

    nova_tarefa = {
        "acao": "criar_worker",
        "imagem": "alpine",
        "alias": alias
    }
    nodes_conectados[ip_alvo]["tarefas_pendentes"].append(nova_tarefa)
    logger.info("Tarefa enfileirada: criar worker '%s' no node %s", alias, ip_alvo)
    return redirect(url_for('node_detail', ip=ip_alvo))


@app.route('/api/nodes', methods=['GET'])
def api_nodes():
    _prune_nodes()
    nodes = {ip: _estado_publico(ip, node) for ip, node in nodes_conectados.items()}
    return jsonify(nodes)


@app.route('/api/node_sync', methods=['POST'])
def node_sync():
    dados = request.get_json()
    if not dados or 'ip' not in dados:
        return jsonify({"erro": "IP ausente"}), 400
    if not _authorized(dados):
        return jsonify({"erro": "Não autorizado"}), 401

    ip_node = dados['ip']
    agora = datetime.now()

    if ip_node not in nodes_conectados:
        nodes_conectados[ip_node] = {
            "status": dados.get("status", "Online"),
            "last_seen_ts": agora,
            "last_seen": agora.strftime("%H:%M:%S"),
            "tarefas_pendentes": [],
            "workers": dados.get("workers", []),
            "worker_status": dados.get("worker_status", {}),
            "tarefa_atual": dados.get("tarefa_atual"),
            "resultados": dados.get("resultados", []),
            "cpu": dados.get("cpu"),
            "mem": dados.get("mem"),
        }
        logger.info("Novo node registrado: %s (workers=%s)", ip_node, dados.get("workers", []))
    else:
        nodes_conectados[ip_node]["status"] = dados.get("status", "Online")
        nodes_conectados[ip_node]["last_seen_ts"] = agora
        nodes_conectados[ip_node]["last_seen"] = agora.strftime("%H:%M:%S")
        if "workers" in dados:
            nodes_conectados[ip_node]["workers"] = dados.get("workers", [])
        nodes_conectados[ip_node]["worker_status"] = dados.get("worker_status", {})
        nodes_conectados[ip_node]["tarefa_atual"] = dados.get("tarefa_atual")
        nodes_conectados[ip_node]["resultados"] = dados.get("resultados", [])
        nodes_conectados[ip_node]["cpu"] = dados.get("cpu")
        nodes_conectados[ip_node]["mem"] = dados.get("mem")

    tarefas_para_enviar = nodes_conectados[ip_node]["tarefas_pendentes"]
    nodes_conectados[ip_node]["tarefas_pendentes"] = []

    if tarefas_para_enviar:
        logger.info("Enviadas %d tarefa(s) para o node %s", len(tarefas_para_enviar), ip_node)

    return jsonify({"status": "ok", "tarefas": tarefas_para_enviar}), 200


@socketio.on('connect')
def handle_connect():
    logger.info("[*] Nova conexão WebSocket estabelecida.")


@socketio.on('terminal_input')
def handle_terminal_input(data):
    ip_alvo = data.get('ip')
    comando = data.get('input')
    alias = data.get('alias')

    if not _alias_valido(alias):
        return

    logger.info("terminal_input: node=%s worker=%s", ip_alvo, alias)
    evento_alvo = f"cmd_to_{ip_alvo}_{alias}"
    socketio.emit(evento_alvo, {'input': comando})


@socketio.on('terminal_resize')
def handle_terminal_resize(data):
    ip_alvo = data.get('ip')
    alias = data.get('alias')
    cols = data.get('cols')
    rows = data.get('rows')

    if not all([ip_alvo, alias, cols, rows]) or not _alias_valido(alias):
        return

    logger.info("terminal_resize: node=%s worker=%s %sx%s", ip_alvo, alias, cols, rows)
    evento_alvo = f"resize_to_{ip_alvo}_{alias}"
    socketio.emit(evento_alvo, {'cols': cols, 'rows': rows})


@socketio.on('terminal_output')
def handle_terminal_output(data):
    ip_origem = data.get('ip')
    alias = data.get('alias')
    saida = data.get('output')

    if not _alias_valido(alias):
        return

    evento_alvo = f"output_for_{ip_origem}_{alias}"
    socketio.emit(evento_alvo, {'output': saida})
