from flask import current_app as app
from flask import render_template, request, jsonify, redirect, url_for
from datetime import datetime
from flask_socketio import emit
from . import socketio
nodes_conectados = {}

@app.route('/')
def dashboard():
    return render_template('index.html', nodes=nodes_conectados)

@app.route('/node/<ip>')
def node_detail(ip):
    if ip not in nodes_conectados:
        return "Node não encontrado ou offline.", 404
        
    node_info = nodes_conectados[ip]
    return render_template('node_detail.html', ip=ip, node=node_info)

@app.route('/node/<ip>/worker/<alias>')
def worker_terminal(ip, alias):
    if ip not in nodes_conectados:
        return "Node não encontrado.", 404
        
    return render_template('terminal.html', ip=ip, alias=alias)

@app.route('/node/<ip>/worker/<alias>/delete')
def delete_worker(ip, alias):
    if ip in nodes_conectados and alias in nodes_conectados[ip]["workers"]:
        nodes_conectados[ip]["workers"].remove(alias)
        nova_tarefa = {
            "acao": "deletar_worker",
            "alias": alias
        }
        nodes_conectados[ip]["tarefas_pendentes"].append(nova_tarefa)
    return redirect(url_for('node_detail', ip=ip))

@app.route('/deploy_worker', methods=['POST'])
def deploy_worker():
    ip_alvo = request.form.get('ip')
    alias = request.form.get('alias')
    
    if ip_alvo in nodes_conectados and alias:
        nova_tarefa = {
            "acao": "criar_worker",
            "imagem": "alpine",
            "alias": alias
        }
        nodes_conectados[ip_alvo]["tarefas_pendentes"].append(nova_tarefa)

        if alias not in nodes_conectados[ip_alvo]["workers"]:
            nodes_conectados[ip_alvo]["workers"].append(alias)
            
    return redirect(url_for('node_detail', ip=ip_alvo))

@app.route('/api/node_sync', methods=['POST'])
def node_sync():
    dados = request.get_json()
    if not dados or 'ip' not in dados:
        return jsonify({"erro": "IP ausente"}), 400

    ip_node = dados['ip']
    
    if ip_node not in nodes_conectados:
        nodes_conectados[ip_node] = {
            "status": dados.get("status", "Online"),
            "last_seen": datetime.now().strftime("%H:%M:%S"),
            "tarefas_pendentes": [],
            "workers": dados.get("workers", []) 
        }
    else:
        nodes_conectados[ip_node]["status"] = dados.get("status", "Online")
        nodes_conectados[ip_node]["last_seen"] = datetime.now().strftime("%H:%M:%S")
        if "workers" in dados:
            nodes_conectados[ip_node]["workers"] = dados.get("workers", [])

    tarefas_para_enviar = nodes_conectados[ip_node]["tarefas_pendentes"]
    nodes_conectados[ip_node]["tarefas_pendentes"] = []

    return jsonify({"status": "ok", "tarefas": tarefas_para_enviar}), 200

@socketio.on('connect')
def handle_connect():
    print("[*] Nova conexão WebSocket estabelecida.")

@socketio.on('terminal_input')
def handle_terminal_input(data):
    ip_alvo = data.get('ip')
    comando = data.get('input')
    alias = data.get('alias')

    evento_alvo = f"cmd_to_{ip_alvo}_{alias}"
    socketio.emit(evento_alvo, {'input': comando})

@socketio.on('terminal_output')
def handle_terminal_output(data):
    ip_origem = data.get('ip')
    alias = data.get('alias')
    saida = data.get('output')

    evento_alvo = f"output_for_{ip_origem}_{alias}"
    socketio.emit(evento_alvo, {'output': saida})