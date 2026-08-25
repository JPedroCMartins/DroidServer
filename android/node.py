import logging
import os
import pty
import queue
import select
import socket
import subprocess
import threading
import time

import requests
import socketio

from sysinfo import SystemMonitor

log = logging.getLogger("node")

DEFAULT_HOST_IP = "192.168.1.10"
DEFAULT_HOST_PORT = 5050
POLL_INTERVAL = 10


class Config:
    """Configurações de conexão do agente, lidas de variáveis de ambiente.

    DROID_HOST_IP   -> IP do servidor host
    DROID_HOST_PORT -> porta do servidor host
    DROID_TOKEN     -> token opcional, exigido pelo host se DROID_API_TOKEN estiver definido
    """

    def __init__(self, host_ip=None, port=None, token=None):
        self.host_ip = host_ip or os.getenv("DROID_HOST_IP", DEFAULT_HOST_IP)
        self.port = int(port or os.getenv("DROID_HOST_PORT", DEFAULT_HOST_PORT))
        self.token = token if token is not None else os.getenv("DROID_TOKEN", "")
        self.http_url = f"http://{self.host_ip}:{self.port}/api/node_sync"
        self.ws_url = f"http://{self.host_ip}:{self.port}"


class WorkerManager:
    """Classe utilitária para gerenciar as instâncias do proot-distro no sistema."""

    # Script padrão executado pelo Supervisor dentro de cada worker.
    # Substitua /app/run_server.sh dentro do container pelo seu aplicativo.
    _SCRIPT_PADRAO = """#!/bin/sh
# DroidServer - script padrao do worker.
# Substitua este arquivo pelo seu aplicativo que deve rodar no container.
echo "[DroidServer] Worker iniciado em $(date)"
while true; do sleep 30; done
"""

    @staticmethod
    def get_installed_workers():
        prefix = os.environ.get('PREFIX', '/data/data/com.termux/files/usr')
        rootfs_dir = os.path.join(prefix, 'var/lib/proot-distro/installed-rootfs')
        if not os.path.exists(rootfs_dir):
            return []
        try:
            return os.listdir(rootfs_dir)
        except OSError:
            return []

    @staticmethod
    def criar(alias, imagem):
        log.info("[Deploy] Criando '%s' (%s)...", alias, imagem)

        prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")

        # Onde o arquivo de configuração do serviço vai ficar
        conf_dir = os.path.join(prefix, "etc", "supervisor", "conf.d")
        arquivo_conf = os.path.join(conf_dir, f"{alias}.conf")

        # Onde os logs serão salvos (organizados por nome do container)
        log_out = os.path.join(prefix, "var", "log", f"supervisor_{alias}_out.log")
        log_err = os.path.join(prefix, "var", "log", f"supervisor_{alias}_err.log")

        # Configuração no estilo "systemctl"
        conteudo_conf = f"""[program:{alias}]
            command=proot-distro login {alias} -- /app/run_server.sh
            autostart=true
            autorestart=true
            startsecs=5
            stderr_logfile={log_err}
            stdout_logfile={log_out}
        """

        try:
            # 1. Instala o proot-distro
            subprocess.run(["proot-distro", "install", imagem, "--override-alias", alias], check=True)
            log.info("[+] Container '%s' criado com sucesso!", alias)

            # 2. Garante que as pastas de configuração e logs existam
            os.makedirs(conf_dir, exist_ok=True)
            os.makedirs(os.path.dirname(log_out), exist_ok=True)

            # 3. Cria o arquivo de configuração do Supervisor
            with open(arquivo_conf, "w") as f:
                f.write(conteudo_conf)
            log.info("[+] Arquivo de configuração criado: %s", arquivo_conf)

            # 4. Avisa ao Supervisor que há um novo serviço (equivalente ao systemctl daemon-reload)
            subprocess.run(["supervisorctl", "reread"], check=False, capture_output=True)
            subprocess.run(["supervisorctl", "update"], check=False, capture_output=True)

            log.info("[+] Serviço '%s' registrado e iniciado no Supervisor.", alias)

            # 5. Garante que /app/run_server.sh exista dentro do container
            WorkerManager._injetar_run_server(alias)

        except subprocess.CalledProcessError:
            log.error("[-] Erro ao criar o container '%s'.", alias)
        except Exception as e:
            log.error("[-] Erro inesperado: %s", e)

    @staticmethod
    def _injetar_run_server(alias):
        """Cria /app/run_server.sh dentro do container (via stdin do proot-distro)."""
        try:
            proc = subprocess.Popen(
                ["proot-distro", "login", alias, "--", "sh", "-c",
                 "cat > /app/run_server.sh && chmod +x /app/run_server.sh"],
                stdin=subprocess.PIPE,
            )
            proc.communicate(WorkerManager._SCRIPT_PADRAO.encode(), timeout=120)
            if proc.returncode == 0:
                log.info("[+] /app/run_server.sh criado no container '%s'.", alias)
            else:
                log.warning("[-] proot-distro retornou %s ao criar run_server.sh do '%s'.",
                            proc.returncode, alias)
        except Exception as e:
            log.warning("[-] Não foi possível criar /app/run_server.sh do '%s': %s", alias, e)

    @staticmethod
    def deletar(alias):
        log.info("[Deploy] Deletando '%s'...", alias)

        prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")

        conf_dir = os.path.join(prefix, "etc", "supervisor", "conf.d")
        arquivo_conf = os.path.join(conf_dir, f"{alias}.conf")
        log_out = os.path.join(prefix, "var", "log", f"supervisor_{alias}_out.log")
        log_err = os.path.join(prefix, "var", "log", f"supervisor_{alias}_err.log")

        try:
            # 1. Para o serviço no Supervisor (se estiver rodando) para evitar processos zumbis
            subprocess.run(["supervisorctl", "stop", alias], check=False, capture_output=True)

            # 2. Remove o arquivo de configuração do Supervisor
            if os.path.exists(arquivo_conf):
                os.remove(arquivo_conf)
                log.info("[+] Arquivo de configuração removido: %s", arquivo_conf)

            # 3. Atualiza o Supervisor para remover o serviço da memória
            subprocess.run(["supervisorctl", "reread"], check=False, capture_output=True)
            subprocess.run(["supervisorctl", "update"], check=False, capture_output=True)

            # 4. Remove o container proot-distro
            subprocess.run(["proot-distro", "remove", alias], check=True)
            log.info("[+] Container '%s' deletado com sucesso!", alias)

            # 5. Remove os arquivos de log associados
            if os.path.exists(log_out):
                os.remove(log_out)
            if os.path.exists(log_err):
                os.remove(log_err)
            log.info("[+] Arquivos de log removidos.")

        except subprocess.CalledProcessError:
            log.error("[-] Erro de processo ao tentar deletar '%s'.", alias)
        except Exception as e:
            log.error("[-] Erro inesperado ao deletar: %s", e)


class TerminalManager:
    """Gerencia as sessões ativas do terminal via PTY e processos em background."""

    def __init__(self, socket_client, local_ip):
        self.sio = socket_client
        self.local_ip = local_ip
        self.ativos = {}  # Formato: {"alias": master_fd}

    def iniciar_pty(self, alias):
        """Cria um teclado/monitor virtual e roda o Alpine dentro dele."""
        if alias in self.ativos:
            return  # Terminal já está rodando

        log.info("[*] Iniciando PTY (Terminal Virtual) para: %s", alias)
        pid, master_fd = pty.fork()

        if pid == 0:
            # Garante que aplicativos interativos (vim, htop, nano) renderizem corretamente
            os.environ['TERM'] = 'xterm-256color'
            os.execvp("proot-distro", ["proot-distro", "login", alias])
        else:
            self.ativos[alias] = master_fd
            t = threading.Thread(target=self._ler_saida, args=(master_fd, alias), daemon=True)
            t.start()

    def escrever_comando(self, alias, comando):
        """Injeta comandos via WebSocket no PTY correspondente."""
        if alias not in self.ativos:
            self.iniciar_pty(alias)
            time.sleep(0.5)  # Aguarda inicialização

        try:
            os.write(self.ativos[alias], comando.encode('utf-8'))
        except OSError:
            log.debug("PTY do '%s' não está mais disponível.", alias)

    def redimensionar(self, alias, cols, rows):
        """Ajusta o tamanho da janela (TIOCSWINSZ) do PTY para o tamanho do navegador."""
        if alias not in self.ativos:
            return
        try:
            import fcntl
            import struct
            import termios
            fcntl.ioctl(
                self.ativos[alias],
                termios.TIOCSWINSZ,
                struct.pack('HHHH', int(rows), int(cols), 0, 0),
            )
        except (OSError, ValueError):
            log.debug("Falha ao redimensionar PTY do '%s'.", alias)

    def _ler_saida(self, master_fd, alias):
        """Fica lendo a tela do Alpine e enviando pro Flask (Thread)."""
        while True:
            r, _, _ = select.select([master_fd], [], [])
            if master_fd in r:
                try:
                    dados = os.read(master_fd, 1024).decode('utf-8', errors='replace')
                    if not dados:
                        break
                    self.sio.emit('terminal_output', {
                        'ip': self.local_ip,
                        'alias': alias,
                        'output': dados,
                    })
                except OSError:
                    break

        log.info("[*] Sessão do terminal '%s' encerrada.", alias)
        if alias in self.ativos:
            del self.ativos[alias]


class NodeAgent:
    """Classe principal que orquestra a comunicação de rede e delega tarefas."""

    def __init__(self, host_ip=None, port=None):
        self.config = Config(host_ip=host_ip, port=port)
        self.meu_ip = self._get_local_ip()

        self.sio = socketio.Client()
        self.terminal = TerminalManager(self.sio, self.meu_ip)
        self.monitor = SystemMonitor()

        # Fila de tarefas processada em segundo plano: instalar um proot-distro
        # pode demorar minutos e não pode travar o polling de sincronização.
        self._fila_tarefas = queue.Queue()
        self._worker_tarefas = threading.Thread(target=self._processa_fila, daemon=True)
        self._worker_tarefas.start()

        self._registrar_eventos_websocket()

    def _get_local_ip(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('10.255.255.255', 1))
            ip = s.getsockname()[0]
        except OSError:
            ip = '127.0.0.1'
        finally:
            s.close()
        return ip

    def _registrar_eventos_websocket(self):
        """Configura os listeners do SocketIO dinamicamente."""
        @self.sio.event
        def connect():
            log.info("[+] Conectado ao servidor de WebSockets do Host!")

        @self.sio.event
        def disconnect():
            log.warning("[-] Conexão WebSocket encerrada. Reconectando no próximo ciclo...")

        @self.sio.on('*')
        def catch_all(evento, dados):
            prefixo_cmd = f"cmd_to_{self.meu_ip}_"
            if evento.startswith(prefixo_cmd):
                alias = evento.replace(prefixo_cmd, "")
                comando = dados.get('input', '')
                self.terminal.escrever_comando(alias, comando)
                return

            prefixo_resize = f"resize_to_{self.meu_ip}_"
            if evento.startswith(prefixo_resize):
                alias = evento.replace(prefixo_resize, "")
                self.terminal.redimensionar(alias, dados.get('cols'), dados.get('rows'))

    def _conectar_ws(self):
        """Mantém a conexão WebSocket ativa; não bloqueia se já estiver conectado.

        O reconnect do socketio-client só atua após uma conexão inicial bem-sucedida,
        então tentamos novamente em cada ciclo do loop.
        """
        if self.sio.connected:
            return True
        try:
            self.sio.connect(self.config.ws_url)
            return True
        except Exception as e:
            log.warning("[-] WebSocket indisponível (%s). Nova tentativa no próximo ciclo.", e)
            return False

    def _poll_once(self):
        """Sincroniza com o host uma única vez e devolve as tarefas pendentes."""
        payload = {
            "ip": self.meu_ip,
            "status": "Online",
            "workers": WorkerManager.get_installed_workers(),
        }
        uso = self.monitor.sample()
        payload["cpu"] = uso["cpu"]
        payload["mem"] = uso["mem"]
        if self.config.token:
            payload["token"] = self.config.token

        try:
            resposta = requests.post(self.config.http_url, json=payload, timeout=5)
            if resposta.status_code == 200:
                return resposta.json().get("tarefas", [])
            log.warning("[-] Host respondeu com status %s.", resposta.status_code)
        except requests.exceptions.RequestException as e:
            log.warning("[-] Erro ao sincronizar com o host: %s", e)
        return []

    def _processa_fila(self):
        """Consome as tarefas da fila em background (thread daemon)."""
        while True:
            tarefa = self._fila_tarefas.get()
            self._executar_tarefa(tarefa)

    def _executar_tarefa(self, tarefa):
        try:
            acao = tarefa.get("acao")
            if acao == "criar_worker":
                WorkerManager.criar(
                    tarefa.get("alias", "worker_padrao"),
                    tarefa.get("imagem", "alpine"),
                )
            elif acao == "deletar_worker":
                alias = tarefa.get("alias")
                if alias:
                    WorkerManager.deletar(alias)
        except Exception as e:
            log.error("[-] Erro ao executar tarefa %s: %s", tarefa, e)

    def _loop(self):
        """Loop principal de Polling e manutenção da conexão WebSockets."""
        log.info("[*] Node Agent iniciado. IP: %s | Host: %s", self.meu_ip, self.config.http_url)

        while True:
            self._conectar_ws()
            tarefas = self._poll_once()
            for tarefa in tarefas:
                log.info("Tarefa recebida: %s", tarefa)
                self._fila_tarefas.put(tarefa)
            time.sleep(POLL_INTERVAL)

    def iniciar(self):
        self._loop()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    NodeAgent().iniciar()
