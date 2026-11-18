import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import time
import urllib.error
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from flask import current_app as app
from flask import redirect, render_template, request, jsonify, session
from flask_socketio import join_room, leave_room
from . import socketio

logger = logging.getLogger("droidserver.routes")

nodes_conectados = {}
# sid do WebSocket -> IP (cadastrado) do node. Só sockets autenticados pelo
# token entram aqui; comandos vão apenas para eles e só eles podem mandar
# saída de terminal, logs e respostas de serviço.
sockets_nodes = {}
# Série temporal de CPU/RAM por node, para o gráfico do painel. Fica fora de
# nodes_conectados para não ir junto em toda chamada de /api/nodes.
# É só um cache: a fonte é o registro local gravado no celular. Quando o
# painel liga (ou o node aparece), ele pede o histórico ao node no sync.
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
# Tipos de worker: "linux" (container do proot-distro com /app/run.sh) ou
# "postgres" (PostgreSQL nativo do Termux, sem container; ver android/banco.py)
TIPOS_WORKER = {"linux", "postgres"}

# Alias de worker: caracteres seguros (usado em caminhos, serviços e eventos WS).
ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Cloudflare Tunnel (cloudflared no Termux, fora do proot): um por node, com o
# nome reservado "tunnel". O token só passa pela fila em memória até o node
# buscá-lo; nunca é gravado no host nem devolvido ao navegador.
TUNNEL = "tunnel"
TUNNEL_TOKEN_RE = re.compile(r"^[A-Za-z0-9+/=_-]{40,4096}$")


def _sem_segredo(tarefa):
    """Cópia da tarefa sem segredos (token do tunnel, senha do banco), para o navegador e os logs."""
    if not isinstance(tarefa, dict):
        return tarefa
    copia = dict(tarefa)
    for chave in ("token", "senha"):
        if chave in copia:
            copia[chave] = "…" + str(copia[chave])[-4:]
    return copia



# ---------------------------------------------------------------------------
# Cadastro de nodes: o painel adiciona cada celular (pareamento) e só aceita
# sync de quem foi cadastrado, com o token exclusivo daquele node. O cadastro
# fica em disco para sobreviver a reinícios do host.
# ---------------------------------------------------------------------------
# Porta em que o agente se anuncia (descoberta + pareamento).
NODE_PORTA = int(os.getenv("DROID_NODE_PORT", "5051"))
DATA_DIR = os.getenv("DROID_DATA_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CADASTRO_ARQUIVO = os.path.join(DATA_DIR, "nodes.json")
# Varredura: no máximo uma /22 (1022 endereços) por vez.
MENOR_PREFIXO_VARREDURA = 22


def _carregar_cadastro():
    try:
        with open(CADASTRO_ARQUIVO) as f:
            dados = json.load(f)
        return {ip: e for ip, e in dados.items() if isinstance(e, dict) and e.get("token")}
    except (OSError, ValueError):
        return {}


cadastro = _carregar_cadastro()


def _salvar_cadastro():
    os.makedirs(os.path.dirname(CADASTRO_ARQUIVO), exist_ok=True)
    tmp = CADASTRO_ARQUIVO + ".tmp"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump(cadastro, f, indent=2)
    os.replace(tmp, CADASTRO_ARQUIVO)


def _mover_node(ip_antigo, ip_novo):
    """O node trocou de IP (DHCP): leva cadastro, estado e histórico junto."""
    cadastro[ip_novo] = cadastro.pop(ip_antigo)
    if ip_antigo in nodes_conectados:
        nodes_conectados[ip_novo] = nodes_conectados.pop(ip_antigo)
    if ip_antigo in historico:
        historico[ip_novo] = historico.pop(ip_antigo)
    for sid, ip in list(sockets_nodes.items()):
        if ip == ip_antigo:
            sockets_nodes[sid] = ip_novo
    _salvar_cadastro()
    logger.info("Node mudou de IP: %s -> %s (identificado pelo token)", ip_antigo, ip_novo)


def _autorizar_node(dados):
    """Devolve o IP sob o qual o node está cadastrado, ou None se não autorizado.

    O node é identificado pelo token, não pelo IP: se o mesmo token chegar de
    outro endereço, o cadastro é movido para o IP novo.
    """
    ip = dados.get("ip")
    if not app.config.get("CADASTRO_OBRIGATORIO", True):
        return ip
    token = str(dados.get("token") or "")
    if not token:
        return None
    for ip_cadastrado, entrada in list(cadastro.items()):
        if hmac.compare_digest(str(entrada.get("token", "")), token):
            # Só migra para um IPv4 de rede local válido: o IP vira chave do
            # cadastro, nome de evento e URL do painel.
            if ip and ip != ip_cadastrado and _ip_valido(ip):
                _mover_node(ip_cadastrado, ip)
                return ip
            return ip_cadastrado
    return None


def _http_json(metodo, url, dados=None, timeout=3.0):
    """Requisição JSON simples (urllib). Devolve (status, corpo) ou (None, erro)."""
    corpo = json.dumps(dados).encode() if dados is not None else None
    req = urllib.request.Request(url, data=corpo, method=metodo,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except (OSError, ValueError) as e:
        return None, {"erro": str(e)}


def _ip_local():
    """IP deste host na LAN (o da interface usada para sair da rede)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _ip_valido(ip):
    try:
        endereco = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return endereco.version == 4 and (endereco.is_private or endereco.is_loopback)


def _sondar_node(ip, timeout=0.8):
    """Pergunta a um IP se ele é um node DroidServer. Devolve as infos ou None."""
    status, corpo = _http_json("GET", f"http://{ip}:{NODE_PORTA}/droidserver", timeout=timeout)
    if status == 200 and isinstance(corpo, dict) and corpo.get("droidserver") is True:
        return corpo
    return None


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


def _carregar_historico(ip, amostras):
    """Substitui o cache pelo histórico gravado no celular (vem no sync)."""
    serie = deque(maxlen=MAX_HISTORICO)
    for a in amostras if isinstance(amostras, list) else []:
        if not isinstance(a, dict) or not isinstance(a.get("t"), (int, float)):
            continue
        num = lambda v: v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
        serie.append({"t": round(float(a["t"]), 1), "cpu": num(a.get("cpu")), "ram": num(a.get("ram"))})
    historico[ip] = serie


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
    info["tarefas_pendentes"] = [_sem_segredo(t) for t in node.get("tarefas_pendentes", [])]

    ultimo = node.get("last_seen_ts")
    if ultimo is None or (datetime.now() - ultimo) > timedelta(seconds=STALE_TIMEOUT):
        info["status"] = "Offline"
    else:
        info["status"] = node.get("status", "Online")

    info["last_seen"] = node.get("last_seen", "—")
    return info


# ---------------------------------------------------------------------------
# Proteção contra requisições de outros sites (CSRF)
# ---------------------------------------------------------------------------
def _origem_permitida(origem):
    """A origem (Origin) é o próprio painel? Sem Origin (agente, curl) é aceito."""
    if not origem:
        return True
    from urllib.parse import urlsplit
    return urlsplit(origem).netloc.lower() == (request.host or "").lower()


# ---------------------------------------------------------------------------
# Login do painel (DROID_PANEL_PASSWORD)
#   Navegadores precisam de sessão; os nodes se autenticam pelo token
#   (/api/node_sync e o WebSocket com papel "node").
# ---------------------------------------------------------------------------
# /apresentar_tcc: slides da defesa, públicos e sem link no painel (só pela URL).
ROTAS_LIVRES = ("/login", "/static/", "/api/node_sync", "/socket.io", "/apresentar_tcc")


def _senha_exigida():
    return bool(app.config.get("PANEL_PASSWORD"))


def _logado():
    return not _senha_exigida() or session.get("autenticado") is True


def _destino_seguro(destino):
    """Só caminhos deste painel (evita redirecionar para outro site)."""
    if destino and destino.startswith("/") and not destino.startswith("//") and "\\" not in destino:
        return destino
    return "/"


@app.before_request
def _exigir_login():
    if _logado() or request.path.startswith(ROTAS_LIVRES):
        return None
    if request.method == "GET" and not request.path.startswith("/api/"):
        return redirect(f"/login?proximo={request.full_path.rstrip('?')}")
    return jsonify({"ok": False, "erro": "Faça login no painel."}), 401


@app.route('/login', methods=['GET', 'POST'])
def login():
    if not _senha_exigida():
        return redirect("/")
    destino = _destino_seguro(request.values.get("proximo"))
    erro = None
    if request.method == "POST":
        senha = request.form.get("senha", "")
        if hmac.compare_digest(senha.encode(), app.config["PANEL_PASSWORD"].encode()):
            session.clear()
            session.permanent = True
            session["autenticado"] = True
            logger.info("Login no painel a partir de %s", request.remote_addr)
            return redirect(destino)
        time.sleep(1)  # atrasa tentativas em série
        logger.warning("Senha do painel incorreta (de %s)", request.remote_addr)
        erro = "Senha incorreta."
    return render_template('login.html', erro=erro, proximo=destino), (401 if erro else 200)


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect("/login")


@app.before_request
def _bloquear_outros_sites():
    """Recusa POST vindo de páginas de outros sites.

    O navegador manda o cabeçalho Origin em todo POST; uma página maliciosa
    aberta na mesma rede poderia, sem isto, criar ou apagar workers e
    cadastrar nodes com um simples formulário. O agente (requests) não envia
    Origin e continua aceito; ele é autenticado pelo token.
    """
    if request.method == "POST" and not _origem_permitida(request.headers.get("Origin")):
        logger.warning("POST recusado de outra origem: %s -> %s", request.headers.get("Origin"), request.path)
        return jsonify({"ok": False, "erro": "Origem não permitida."}), 403


# ---------------------------------------------------------------------------
# Páginas: o front é uma SPA (templates/index.html) que resolve a tela
# no cliente a partir da URL e consome as rotas /api/* abaixo.
# ---------------------------------------------------------------------------
@app.route('/')
@app.route('/node/<ip>')
@app.route('/node/<ip>/worker/<alias>')
@app.route('/node/<ip>/worker/<alias>/terminal')
@app.route('/node/<ip>/tunnel')
def spa(ip=None, alias=None):
    return render_template('index.html', senha_exigida=_senha_exigida())


@app.route('/apresentar_tcc')
def apresentar_tcc():
    """Slides da defesa do TCC. Não mostram nada do cluster; por isso dispensam login."""
    return render_template('apresentacao.html')


@app.route('/node/<ip>/worker/<alias>/delete', methods=['POST'])
def delete_worker(ip, alias):
    # POST (não GET): pré-carregamento do navegador, robôs ou um <img src>
    # numa página qualquer não conseguem apagar workers.
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
    tipo = request.form.get('tipo', 'linux').strip().lower()

    if ip_alvo not in nodes_conectados:
        return jsonify({"ok": False, "erro": "Node não encontrado."}), 404

    if tipo not in TIPOS_WORKER:
        logger.warning("Tipo de worker inválido rejeitado no deploy: %r", tipo)
        return jsonify({"ok": False, "erro": "Tipo de worker inválido."}), 400

    if tipo == "linux" and imagem not in IMAGENS_PERMITIDAS:
        logger.warning("Imagem inválida rejeitada no deploy: %r", imagem)
        return jsonify({"ok": False, "erro": "Distribuição inválida."}), 400

    if not _alias_valido(alias):
        logger.warning("Alias inválido rejeitado no deploy: %r", alias)
        return jsonify({"ok": False, "erro": "Alias inválido."}), 400

    if alias == TUNNEL:
        return jsonify({"ok": False, "erro": "O nome 'tunnel' é reservado para o tunnel da Cloudflare."}), 400

    if alias in nodes_conectados[ip_alvo]["workers"]:
        logger.info("Worker '%s' já existe no node %s; nada a fazer.", alias, ip_alvo)
        return jsonify({"ok": False, "erro": "Worker já existe."}), 409

    if tipo == "postgres":
        # A senha nasce aqui e só existe no Node depois; o painel a pede pela
        # ação "credenciais" da aba Serviço (nunca vem no sync)
        nova_tarefa = {"acao": "criar_worker", "tipo": "postgres", "alias": alias,
                       "senha": secrets.token_urlsafe(18)}
        logger.info("Tarefa enfileirada: criar worker de banco '%s' (PostgreSQL) no node %s", alias, ip_alvo)
    else:
        nova_tarefa = {
            "acao": "criar_worker",
            "imagem": imagem,
            "alias": alias,
            "isolado": isolado
        }
        logger.info("Tarefa enfileirada: criar worker '%s' (%s, isolado=%s) no node %s", alias, imagem, isolado, ip_alvo)
    nodes_conectados[ip_alvo]["tarefas_pendentes"].append(nova_tarefa)
    socketio.emit('node_updated', {'ip': ip_alvo})
    return jsonify({"ok": True})


@app.route('/node/<ip>/tunnel', methods=['POST'])
def configurar_tunnel(ip):
    """Enfileira a instalação/configuração do cloudflared com o token colado no painel."""
    _prune_nodes()
    if ip not in nodes_conectados:
        return jsonify({"ok": False, "erro": "Node não encontrado."}), 404
    dados = request.get_json(silent=True) or request.form
    token = (dados.get("token") or "").strip()
    # Aceita o comando inteiro copiado da Cloudflare ("cloudflared ... --token <t>")
    if "--token" in token:
        resto = token.split("--token", 1)[1].split()
        token = resto[0] if resto else ""
    if not TUNNEL_TOKEN_RE.fullmatch(token):
        return jsonify({"ok": False, "erro": "Token inválido. Cole o token do tunnel (ou o comando com --token)."}), 400
    pendentes = [t for t in nodes_conectados[ip]["tarefas_pendentes"]
                 if t.get("acao") not in ("configurar_tunnel", "remover_tunnel")]
    pendentes.append({"acao": "configurar_tunnel", "token": token})
    nodes_conectados[ip]["tarefas_pendentes"] = pendentes
    logger.info("Tarefa enfileirada: configurar o tunnel (token …%s) no node %s", token[-4:], ip)
    socketio.emit('node_updated', {'ip': ip})
    return jsonify({"ok": True, "token_fim": token[-4:]})


@app.route('/node/<ip>/tunnel/delete', methods=['POST'])
def remover_tunnel(ip):
    _prune_nodes()
    if ip not in nodes_conectados:
        return jsonify({"ok": False, "erro": "Node não encontrado."}), 404
    pendentes = [t for t in nodes_conectados[ip]["tarefas_pendentes"]
                 if t.get("acao") not in ("configurar_tunnel", "remover_tunnel")]
    pendentes.append({"acao": "remover_tunnel"})
    nodes_conectados[ip]["tarefas_pendentes"] = pendentes
    logger.info("Tarefa enfileirada: remover o tunnel do node %s", ip)
    socketio.emit('node_updated', {'ip': ip})
    return jsonify({"ok": True})


@app.route('/api/nodes', methods=['GET'])
def api_nodes():
    _prune_nodes()
    nodes = {ip: _estado_publico(ip, node) for ip, node in nodes_conectados.items()}
    # Cadastrados que ainda não sincronizaram (ou saíram do ar) também aparecem
    for ip in cadastro:
        if ip not in nodes:
            nodes[ip] = _estado_aguardando(ip)
    for ip, info in nodes.items():
        info["cadastrado"] = ip in cadastro
        info["modelo"] = cadastro.get(ip, {}).get("modelo")
    return jsonify(nodes)


def _estado_aguardando(ip):
    return {"ip": ip, "status": "Aguardando", "aguardando": True, "workers": [], "worker_status": {},
            "tarefas_pendentes": [], "resultados": [], "last_seen": "—",
            "cpu": None, "cpu_termux": None, "cpu_workers": {}, "mem": None}


@app.route('/api/node/<ip>', methods=['GET'])
def api_node(ip):
    _prune_nodes()
    if ip in nodes_conectados:
        info = _estado_publico(ip, nodes_conectados[ip])
    elif ip in cadastro:
        info = _estado_aguardando(ip)
    else:
        return jsonify({"erro": "Node não encontrado"}), 404
    info["cadastrado"] = ip in cadastro
    info["modelo"] = cadastro.get(ip, {}).get("modelo")
    return jsonify(info)


# ---------------------------------------------------------------------------
# Varredura de rede e cadastro de nodes pelo painel
# ---------------------------------------------------------------------------
@app.route('/api/rede', methods=['GET'])
def api_rede():
    """Rede sugerida para a varredura: a /24 do IP deste host."""
    ip = _ip_local()
    return jsonify({"ip_host": ip, "rede": str(ipaddress.ip_network(f"{ip}/24", strict=False))})


@app.route('/api/varredura', methods=['POST'])
def api_varredura():
    """Procura nodes DroidServer (porta NODE_PORTA) em todos os IPs de uma rede."""
    dados = request.get_json(silent=True) or {}
    texto = (dados.get("rede") or "").strip() or api_rede().get_json()["rede"]
    try:
        rede = ipaddress.ip_network(texto, strict=False)
    except ValueError:
        return jsonify({"ok": False, "erro": "Rede inválida. Use o formato 192.168.1.0/24."}), 400
    if rede.version != 4 or not rede.is_private:
        return jsonify({"ok": False, "erro": "Só redes privadas IPv4 podem ser varridas."}), 400
    if rede.prefixlen < MENOR_PREFIXO_VARREDURA:
        return jsonify({"ok": False, "erro": f"Rede grande demais: use /{MENOR_PREFIXO_VARREDURA} ou menor."}), 400

    inicio = time.monotonic()
    ips = [str(h) for h in rede.hosts()]
    with ThreadPoolExecutor(max_workers=64) as pool:
        respostas = list(pool.map(_sondar_node, ips))
    encontrados = []
    for ip, info in zip(ips, respostas):
        if info:
            encontrados.append({
                "ip": ip,
                "modelo": info.get("modelo"),
                "android": info.get("android"),
                "pareado": bool(info.get("pareado")),
                "host": info.get("host"),
                "cadastrado": ip in cadastro,
            })
    duracao = round(time.monotonic() - inicio, 1)
    logger.info("Varredura de %s: %d node(s) em %ss", rede, len(encontrados), duracao)
    return jsonify({"ok": True, "rede": str(rede), "enderecos": len(ips),
                    "duracao_s": duracao, "nodes": encontrados})


@app.route('/api/nodes/adicionar', methods=['POST'])
def api_adicionar_node():
    """Cadastra um node: confirma que é um DroidServer e envia host + token a ele."""
    dados = request.get_json(silent=True) or request.form
    ip = (dados.get("ip") or "").strip()
    if not _ip_valido(ip):
        return jsonify({"ok": False, "erro": "Informe um IPv4 da rede local."}), 400

    info = _sondar_node(ip, timeout=3)
    if not info:
        return jsonify({"ok": False, "erro": f"Nenhum agente DroidServer respondeu em {ip}:{NODE_PORTA}. "
                                             "O agente está rodando no celular?"}), 404

    token = secrets.token_hex(24)
    porta = int(os.getenv("DROID_PORT", "5050"))
    pedido = {"host_port": porta, "token": token}
    if ip in cadastro:
        # Já cadastrado: o token atual prova que somos o host pareado, mesmo
        # que o IP deste PC tenha mudado (DHCP) desde o pareamento.
        pedido["token_atual"] = cadastro[ip]["token"]
    status, corpo = _http_json("POST", f"http://{ip}:{NODE_PORTA}/parear", pedido, timeout=5)
    if status != 200:
        erro = (corpo or {}).get("erro") or "o node recusou o pareamento"
        return jsonify({"ok": False, "erro": erro}), 409 if status == 409 else 502

    cadastro[ip] = {"token": token, "modelo": info.get("modelo"), "android": info.get("android"),
                    "adicionado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    _salvar_cadastro()
    logger.info("Node %s (%s) adicionado pelo painel", ip, info.get("modelo"))
    socketio.emit('node_updated', {'ip': ip})
    return jsonify({"ok": True, "ip": ip, "modelo": info.get("modelo")})


@app.route('/api/nodes/<ip>/remover', methods=['POST'])
def api_remover_node(ip):
    """Remove o node do painel e pede a ele que desfaça o pareamento."""
    if ip not in cadastro and ip not in nodes_conectados:
        return jsonify({"ok": False, "erro": "Node não encontrado."}), 404
    entrada = cadastro.pop(ip, None)
    nodes_conectados.pop(ip, None)
    historico.pop(ip, None)
    _salvar_cadastro()
    despareado = False
    if entrada:
        status, _ = _http_json("POST", f"http://{ip}:{NODE_PORTA}/desparear",
                               {"token": entrada["token"]}, timeout=3)
        despareado = status == 200
    logger.info("Node %s removido do painel (despareado no celular: %s)", ip, despareado)
    socketio.emit('node_updated', {'ip': ip})
    return jsonify({"ok": True, "despareado": despareado})


class _SemRedirecionar(urllib.request.HTTPRedirectHandler):
    """Um 3xx já prova que o serviço está no ar; segui-lo sairia do Worker."""

    def redirect_request(self, *args, **kwargs):
        return None


_abridor_servico = urllib.request.build_opener(_SemRedirecionar)


def _abrir_servico(url, timeout=3):
    return _abridor_servico.open(url, timeout=timeout)


def _testar_tcp(ip, porta, timeout=3):
    """Banco não fala HTTP: o teste é abrir uma conexão TCP na porta."""
    destino = f"{ip}:{porta}"
    inicio = time.monotonic()
    try:
        with socket.create_connection((ip, porta), timeout=timeout):
            pass
    except (socket.timeout, TimeoutError):
        return {"ok": False, "url": destino, "status": None, "ms": None, "erro": "sem resposta em 3 s."}
    except OSError as e:
        return {"ok": False, "url": destino, "status": None, "ms": None,
                "erro": f"o banco não aceitou conexão em {destino} ({e.strerror or e})."}
    ms = round((time.monotonic() - inicio) * 1000, 1)
    return {"ok": True, "url": destino, "status": "porta aberta", "ms": ms, "erro": None}


@app.route('/api/node/<ip>/worker/<alias>/testar', methods=['POST'])
def api_testar_servico(ip, alias):
    """Testa, a partir do Host, o endereço do serviço (porta declarada no run.sh)."""
    node = nodes_conectados.get(ip)
    if not node or not _alias_valido(alias) or alias not in node.get("workers", []):
        return jsonify({"ok": False, "erro": "Node ou worker não encontrado."}), 404
    sv = (node.get("servicos") or {}).get(alias) or {}
    porta = sv.get("porta")
    # o valor vem do agente: só aceita um inteiro de porta válido
    if isinstance(porta, bool) or not isinstance(porta, int) or not 1 <= porta <= 65535:
        return jsonify({"ok": False, "url": None, "status": None, "ms": None,
                        "erro": "porta não informada: declare '# droidserver: porta=N' no run.sh."})
    if sv.get("tipo") == "postgres":
        return jsonify(_testar_tcp(ip, porta))
    url = f"http://{ip}:{int(porta)}/"
    inicio = time.monotonic()
    status, erro = None, None
    try:
        with _abrir_servico(url, timeout=3) as resp:
            status = resp.status
    except urllib.error.HTTPError as e:
        status = e.code  # respondeu com erro HTTP: o serviço está no ar
    except (socket.timeout, TimeoutError):
        erro = "sem resposta em 3 s."
    except OSError as e:
        erro = f"o serviço não respondeu em {url} ({getattr(e, 'reason', e)})."
    ms = round((time.monotonic() - inicio) * 1000, 1)
    return jsonify({"ok": status is not None, "url": url, "status": status,
                    "ms": ms if status is not None else None, "erro": erro})


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
    ip_node = _autorizar_node(dados)
    if not ip_node:
        logger.warning("Sync recusado de %s: node não cadastrado ou token inválido", dados.get('ip'))
        return jsonify({"erro": "Node não cadastrado. Adicione-o pelo painel."}), 401
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
            "servicos": dados.get("servicos", {}),
            "mem": dados.get("mem"),
            "tunnel": dados.get("tunnel"),
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
        nodes_conectados[ip_node]["servicos"] = dados.get("servicos", {})
        nodes_conectados[ip_node]["mem"] = dados.get("mem")
        nodes_conectados[ip_node]["tunnel"] = dados.get("tunnel")

    # Painel recém-ligado (ou node novo): pede o histórico gravado no celular
    pedir_historico = ip_node not in historico and "historico" not in dados
    if "historico" in dados:
        _carregar_historico(ip_node, dados.get("historico"))
    _registrar_amostra(ip_node, dados)
    _reconciliar_logs(ip_node, dados.get("logs_ativos"))

    # Notifica os painéis abertos para atualizarem sem precisar recarregar a página
    socketio.emit('node_updated', {'ip': ip_node})

    tarefas_para_enviar = nodes_conectados[ip_node]["tarefas_pendentes"]
    nodes_conectados[ip_node]["tarefas_pendentes"] = []

    if tarefas_para_enviar:
        logger.info("Enviadas %d tarefa(s) para o node %s", len(tarefas_para_enviar), ip_node)

    resposta = {"status": "ok", "tarefas": tarefas_para_enviar}
    if pedir_historico:
        resposta["pedir_historico"] = True
    return jsonify(resposta), 200


# ---------------------------------------------------------------------------
# Serviço do worker (aba Serviço): comandos e logs ao vivo
#   navegador --servico--> host --servico_to_<ip>--> node
#   node --servico_resposta--> host --servico_resposta--> só o navegador que pediu
#   navegador --logs_assinar--> host (entra na sala) --logs_to_<ip>--> node
#   node --logs_saida--> host --logs_saida--> só a sala logs:<ip>:<alias>
# ---------------------------------------------------------------------------
ACOES_SERVICO = {"iniciar", "parar", "reiniciar", "ler_script", "salvar_script", "configurar", "exemplo",
                 "credenciais", "criar_banco", "apagar_banco"}
# (ip, alias) -> sids dos navegadores com a aba de logs aberta
assinantes_logs = {}


def _sala_logs(ip, alias):
    return f"logs:{ip}:{alias}"


@socketio.on('servico')
def handle_servico(data):
    data = data if isinstance(data, dict) else {}
    ip, alias, acao = data.get('ip'), data.get('alias'), data.get('acao')
    if ip not in nodes_conectados or not _alias_valido(alias) or acao not in ACOES_SERVICO:
        socketio.emit('servico_resposta', {'ip': ip, 'alias': alias, 'acao': acao, 'req': data.get('req'),
                                           'ok': False, 'msg': 'Node offline ou comando inválido.'},
                      to=request.sid)
        return
    logger.info("servico: node=%s worker=%s acao=%s", ip, alias, acao)
    enviado = _emitir_ao_node(ip, f"servico_to_{ip}", {'alias': alias, 'acao': acao, 'dados': data.get('dados') or {},
                                                      'sid': request.sid, 'req': data.get('req')})
    if not enviado:
        socketio.emit('servico_resposta', {'ip': ip, 'alias': alias, 'acao': acao, 'req': data.get('req'),
                                           'ok': False, 'msg': 'O node não está conectado ao WebSocket.'},
                      to=request.sid)


@socketio.on('servico_resposta')
def handle_servico_resposta(data):
    data = data if isinstance(data, dict) else {}
    sid = data.get('sid')
    ip = _ip_do_node_que_enviou()
    if not sid or not ip:
        return
    data['ip'] = ip
    # Atualiza o estado guardado para o painel não esperar o próximo sync
    alias, est = data.get('alias'), data.get('servico')
    if ip in nodes_conectados and alias == TUNNEL and isinstance(est, dict):
        nodes_conectados[ip]["tunnel"] = est
    elif ip in nodes_conectados and _alias_valido(alias) and isinstance(est, dict):
        nodes_conectados[ip].setdefault("servicos", {})[alias] = est
    socketio.emit('servico_resposta', {k: v for k, v in data.items() if k != 'sid'}, to=sid)


@socketio.on('logs_assinar')
def handle_logs_assinar(data):
    data = data if isinstance(data, dict) else {}
    ip, alias = data.get('ip'), data.get('alias')
    if ip not in nodes_conectados or not _alias_valido(alias):
        return
    join_room(_sala_logs(ip, alias))
    assinantes_logs.setdefault((ip, alias), set()).add(request.sid)
    _emitir_ao_node(ip, f"logs_to_{ip}", {'alias': alias, 'acao': 'assinar'})


def _reconciliar_logs(ip, ativos_no_node):
    """Alinha os logs que o node acompanha com quem está assistindo no painel.

    Se o agente reiniciou, ele esqueceu as assinaturas e os navegadores ficariam
    sem logs novos; se um cancelamento se perdeu, ele leria o arquivo à toa.
    """
    if not isinstance(ativos_no_node, list):
        return  # agente antigo, que não informa
    no_node = {a for a in ativos_no_node if isinstance(a, str)}
    assistidos = {alias for (ip_s, alias), sids in assinantes_logs.items() if ip_s == ip and sids}
    for alias in sorted(assistidos - no_node):
        _emitir_ao_node(ip, f"logs_to_{ip}", {'alias': alias, 'acao': 'assinar'})
    for alias in sorted(no_node - assistidos):
        if _alias_valido(alias):
            _emitir_ao_node(ip, f"logs_to_{ip}", {'alias': alias, 'acao': 'cancelar'})


def _sair_dos_logs(sid, ip, alias):
    chave = (ip, alias)
    sids = assinantes_logs.get(chave)
    if not sids or sid not in sids:
        return
    sids.discard(sid)
    leave_room(_sala_logs(ip, alias), sid=sid)
    if not sids:
        # Ninguém mais assistindo: o node para de ler o arquivo
        assinantes_logs.pop(chave, None)
        _emitir_ao_node(ip, f"logs_to_{ip}", {'alias': alias, 'acao': 'cancelar'})


@socketio.on('logs_cancelar')
def handle_logs_cancelar(data):
    data = data if isinstance(data, dict) else {}
    _sair_dos_logs(request.sid, data.get('ip'), data.get('alias'))


@socketio.on('logs_saida')
def handle_logs_saida(data):
    data = data if isinstance(data, dict) else {}
    ip, alias = _ip_do_node_que_enviou(), data.get('alias')
    if not ip or not _alias_valido(alias):
        return
    socketio.emit('logs_saida', {'alias': alias, 'linhas': data.get('linhas') or [],
                                 'inicial': bool(data.get('inicial'))}, to=_sala_logs(ip, alias))


def _emitir_ao_node(ip, evento, dados):
    """Envia um evento só para o(s) socket(s) do node. Devolve quantos receberam."""
    sids = [sid for sid, ip_node in list(sockets_nodes.items()) if ip_node == ip]
    for sid in sids:
        socketio.emit(evento, dados, to=sid)
    return len(sids)


def _ip_do_node_que_enviou():
    """IP do node dono do socket atual, ou None se quem enviou não é um node.

    O IP vem do cadastro (token), nunca do conteúdo do evento: um navegador
    não consegue se passar por node, nem um node por outro.
    """
    return sockets_nodes.get(request.sid)


def _sala_terminal(ip, alias):
    return f"term:{ip}:{alias}"


@socketio.on('disconnect')
def handle_disconnect(*_):
    ip_node = sockets_nodes.pop(request.sid, None)
    if ip_node:
        logger.info("[-] WebSocket do node %s encerrado.", ip_node)
    for ip, alias in [chave for chave, sids in assinantes_logs.items() if request.sid in sids]:
        _sair_dos_logs(request.sid, ip, alias)


@socketio.on('connect')
def handle_connect(auth=None):
    auth = auth if isinstance(auth, dict) else {}
    if auth.get('papel') != 'node':
        if not _logado():
            logger.warning("WebSocket do painel recusado: sem login.")
            return False
        logger.info("[*] Nova conexão WebSocket (painel).")
        return None
    ip = _autorizar_node({'ip': auth.get('ip'), 'token': auth.get('token')})
    if not ip:
        logger.warning("WebSocket de node recusado (%s): token inválido ou node não cadastrado.", auth.get('ip'))
        return False
    sockets_nodes[request.sid] = ip
    logger.info("[+] WebSocket do node %s autenticado.", ip)
    return None


@socketio.on('terminal_assinar')
def handle_terminal_assinar(data):
    """O navegador abriu o terminal de um worker: passa a receber só a saída dele."""
    data = data if isinstance(data, dict) else {}
    ip, alias = data.get('ip'), data.get('alias')
    if ip in nodes_conectados and _alias_valido(alias):
        join_room(_sala_terminal(ip, alias))


@socketio.on('terminal_cancelar')
def handle_terminal_cancelar(data):
    data = data if isinstance(data, dict) else {}
    ip, alias = data.get('ip'), data.get('alias')
    if _alias_valido(alias):
        leave_room(_sala_terminal(ip, alias))


@socketio.on('terminal_input')
def handle_terminal_input(data):
    data = data if isinstance(data, dict) else {}
    ip_alvo = data.get('ip')
    comando = data.get('input')
    alias = data.get('alias')

    if not _alias_valido(alias) or not isinstance(comando, str):
        return

    logger.debug("terminal_input: node=%s worker=%s", ip_alvo, alias)
    _emitir_ao_node(ip_alvo, f"cmd_to_{ip_alvo}_{alias}", {'input': comando})


@socketio.on('terminal_resize')
def handle_terminal_resize(data):
    data = data if isinstance(data, dict) else {}
    ip_alvo = data.get('ip')
    alias = data.get('alias')
    cols = data.get('cols')
    rows = data.get('rows')

    if not all([ip_alvo, alias, cols, rows]) or not _alias_valido(alias):
        return

    logger.info("terminal_resize: node=%s worker=%s %sx%s", ip_alvo, alias, cols, rows)
    _emitir_ao_node(ip_alvo, f"resize_to_{ip_alvo}_{alias}", {'cols': cols, 'rows': rows})


@socketio.on('terminal_output')
def handle_terminal_output(data):
    data = data if isinstance(data, dict) else {}
    ip_origem = _ip_do_node_que_enviou()
    alias = data.get('alias')
    saida = data.get('output')

    if not ip_origem or not _alias_valido(alias):
        return

    # Só para quem abriu o terminal deste worker
    socketio.emit(f"output_for_{ip_origem}_{alias}", {'output': saida}, to=_sala_terminal(ip_origem, alias))
