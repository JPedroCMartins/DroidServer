import logging
import os
import re
import time
from collections import deque
from datetime import datetime, timedelta

from flask import current_app as app
from flask import render_template, request, jsonify
from . import socketio

logger = logging.getLogger("droidserver.routes")

nodes_conectados = {}
# Série temporal de CPU/RAM por node, para o gráfico do painel. Fica fora de
# nodes_conectados para não ir junto em toda chamada de /api/nodes.
historico = {}

# Segundos sem contato antes de um node ser marcado como Offline.
# O agente sincroniza a cada 10s, então 25s é tolerante a falhas pontuais.
STALE_TIMEOUT = 25
# Segundos offline sem tarefas pendentes antes do node ser removido do painel.
PRUNE_TIMEOUT = 180
# Amostras de CPU/RAM guardadas por node: 180 syncs de 10 s = 30 minutos.
MAX_HISTORICO = 180

# Quantos resultados de operações (✓/✗) o painel guarda por node.
MAX_RESULTADOS = 20

# Distribuições (proot-distro) que podem ser criadas pelo painel.
# Alpine é a recomendada; Debian, a alternativa. Arch foi retirado (sem build arm64).
IMAGENS_PERMITIDAS = {"alpine", "debian"}

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
            historico.pop(ip, None)
            logger.info("Node %s removido do painel (offline há %ds)", ip, int((agora - ultimo).total_seconds()))


def _acumular_resultados(anteriores, novos):
    """Junta os resultados recebidos aos já guardados.

    O agente envia cada resultado uma única vez e o descarta após o sync
    bem-sucedido. Se o host substituísse a lista a cada sync, um ✓/✗ ficaria
    visível só por ~10 s (até o próximo sync, que chega vazio). Reenvios
    (resposta perdida) são ignorados para não duplicar.
    """
    lista = list(anteriores or [])
    vistos = {(r.get("acao"), r.get("alias"), r.get("ts"), r.get("msg")) for r in lista}
    for r in novos or []:
        if not isinstance(r, dict):
            continue
        chave = (r.get("acao"), r.get("alias"), r.get("ts"), r.get("msg"))
        if chave not in vistos:
            vistos.add(chave)
            lista.append(r)
    return lista[-MAX_RESULTADOS:]


def _registrar_amostra(ip, dados):
    """Guarda CPU do DroidServer e RAM do sync no histórico do node."""
    mem = dados.get("mem") or {}
    serie = historico.setdefault(ip, deque(maxlen=MAX_HISTORICO))
    serie.append({
        "t": round(time.time(), 1),
        "cpu": dados.get("cpu_termux"),
        "ram": mem.get("percent") if isinstance(mem, dict) else None,
    })


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


# ---------------------------------------------------------------------------
# Páginas: o front é uma SPA (templates/index.html) que resolve a tela
# no cliente a partir da URL e consome as rotas /api/* abaixo.
# ---------------------------------------------------------------------------
@app.route('/')
@app.route('/node/<ip>')
@app.route('/node/<ip>/worker/<alias>')
def spa(ip=None, alias=None):
    return render_template('index.html')


@app.route('/node/<ip>/worker/<alias>/delete')
def delete_worker(ip, alias):
    _prune_nodes()
    if ip not in nodes_conectados:
        return jsonify({"ok": False, "erro": "Node não encontrado."}), 404
    if not _alias_valido(alias) or alias not in nodes_conectados[ip]["workers"]:
        return jsonify({"ok": False, "erro": "Worker não encontrado neste node."}), 404

    # Não remove da lista aqui: a lista é autoritativa do node (via sync).
    nova_tarefa = {
        "acao": "deletar_worker",
        "alias": alias
    }
    nodes_conectados[ip]["tarefas_pendentes"].append(nova_tarefa)
    logger.info("Tarefa enfileirada: deletar worker '%s' do node %s", alias, ip)
    socketio.emit('node_updated', {'ip': ip})
    return jsonify({"ok": True})


@app.route('/deploy_worker', methods=['POST'])
def deploy_worker():
    ip_alvo = request.form.get('ip')
    alias = request.form.get('alias', '').strip()
    imagem = request.form.get('imagem', 'alpine').strip().lower()
    isolado = request.form.get('isolado', '1') == '1'

    if ip_alvo not in nodes_conectados:
        return jsonify({"ok": False, "erro": "Node não encontrado."}), 404

    if imagem not in IMAGENS_PERMITIDAS:
        logger.warning("Imagem inválida rejeitada no deploy: %r", imagem)
        return jsonify({"ok": False, "erro": "Distribuição inválida."}), 400

    if not _alias_valido(alias):
        logger.warning("Alias inválido rejeitado no deploy: %r", alias)
        return jsonify({"ok": False, "erro": "Alias inválido."}), 400

    if alias in nodes_conectados[ip_alvo]["workers"]:
        logger.info("Worker '%s' já existe no node %s; nada a fazer.", alias, ip_alvo)
        return jsonify({"ok": False, "erro": "Worker já existe."}), 409

    nova_tarefa = {
        "acao": "criar_worker",
        "imagem": imagem,
        "alias": alias,
        "isolado": isolado
    }
    nodes_conectados[ip_alvo]["tarefas_pendentes"].append(nova_tarefa)
    logger.info("Tarefa enfileirada: criar worker '%s' (%s, isolado=%s) no node %s", alias, imagem, isolado, ip_alvo)
    socketio.emit('node_updated', {'ip': ip_alvo})
    return jsonify({"ok": True})


@app.route('/api/nodes', methods=['GET'])
def api_nodes():
    _prune_nodes()
    nodes = {ip: _estado_publico(ip, node) for ip, node in nodes_conectados.items()}
    return jsonify(nodes)


@app.route('/api/node/<ip>', methods=['GET'])
def api_node(ip):
    _prune_nodes()
    if ip not in nodes_conectados:
        return jsonify({"erro": "Node não encontrado"}), 404
    return jsonify(_estado_publico(ip, nodes_conectados[ip]))


@app.route('/api/node/<ip>/historico', methods=['GET'])
def api_node_historico(ip):
    """Série de CPU (DroidServer) e RAM do node: [{t, cpu, ram}], mais antiga primeiro."""
    _prune_nodes()
    if ip not in nodes_conectados:
        return jsonify({"erro": "Node não encontrado"}), 404
    return jsonify({"intervalo_s": 10, "amostras": list(historico.get(ip, []))})


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
            "resultados": _acumular_resultados([], dados.get("resultados")),
            "cpu": dados.get("cpu"),
            "cpu_termux": dados.get("cpu_termux"),
            "cpu_workers": dados.get("cpu_workers", {}),
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
        nodes_conectados[ip_node]["resultados"] = _acumular_resultados(
            nodes_conectados[ip_node].get("resultados"), dados.get("resultados"))
        nodes_conectados[ip_node]["cpu"] = dados.get("cpu")
        nodes_conectados[ip_node]["cpu_termux"] = dados.get("cpu_termux")
        nodes_conectados[ip_node]["cpu_workers"] = dados.get("cpu_workers", {})
        nodes_conectados[ip_node]["mem"] = dados.get("mem")

    _registrar_amostra(ip_node, dados)

    # Notifica os painéis abertos para atualizarem sem precisar recarregar a página
    socketio.emit('node_updated', {'ip': ip_node})

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
