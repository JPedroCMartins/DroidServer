import time
import socket
import subprocess
import os
import pty
import select
import threading
import requests
import socketio

HOST_IP = "192.168.1.10"
HOST_PORT = 5050

class Config:
    """Armazena as configurações globais de conexão do agente."""
    def __init__(self, host_ip=HOST_IP, port=HOST_PORT):
        self.host_ip = host_ip
        self.port = port
        self.http_url = f"http://{self.host_ip}:{self.port}/api/node_sync"
        self.ws_url = f"http://{self.host_ip}:{self.port}"

class WorkerManager:
    """Classe utilitária para gerenciar as instâncias do proot-distro no sistema."""
    
    @staticmethod
    def get_installed_workers():
        prefix = os.environ.get('PREFIX', '/data/data/com.termux/files/usr')
        rootfs_dir = os.path.join(prefix, 'var/lib/proot-distro/installed-rootfs')
        if not os.path.exists(rootfs_dir): 
            return []
        try:
            return os.listdir(rootfs_dir)
        except Exception:
            return []

    @staticmethod
    def criar(alias, imagem):
        print(f"[*] Deploy: Criando '{alias}' ({imagem})...")
        try:
            subprocess.run(["proot-distro", "install", imagem, "--override-alias", alias], check=True)
            print(f"[+] Container '{alias}' criado com sucesso!")
        except subprocess.CalledProcessError:
            print(f"[-] Erro ao criar '{alias}'.")

    @staticmethod
    def deletar(alias):
        print(f"[*] Deletando worker '{alias}'...")
        try:
            subprocess.run(["proot-distro", "remove", alias], check=True)
            print(f"[+] Worker '{alias}' deletado com sucesso!")
        except subprocess.CalledProcessError:
            print(f"[-] Erro ao deletar '{alias}'.")

class TerminalManager:
    """Gerencia as sessões ativas do terminal via PTY e processos em background."""
    
    def __init__(self, socket_client, local_ip):
        self.sio = socket_client
        self.local_ip = local_ip
        self.ativos = {}  # Formato: {"alias": master_fd}

    def iniciar_pty(self, alias):
        """Cria um teclado/monitor virtual e roda o Alpine dentro dele."""
        if alias in self.ativos:
            return # Terminal já está rodando
        
        print(f"[*] Iniciando PTY (Terminal Virtual) para: {alias}")
        pid, master_fd = pty.fork()
        
        if pid == 0:
            os.execvp("proot-distro", ["proot-distro", "login", alias])
        else:
            self.ativos[alias] = master_fd
            t = threading.Thread(target=self._ler_saida, args=(master_fd, alias), daemon=True)
            t.start()

    def escrever_comando(self, alias, comando):
        """Injeta comandos via WebSocket no PTY correspondente."""
        if alias not in self.ativos:
            self.iniciar_pty(alias)
            time.sleep(0.5) # Aguarda inicialização
            
        try:
            os.write(self.ativos[alias], comando.encode('utf-8'))
        except OSError:
            pass # Se der erro, o PTY morreu. Ignora.

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
                        'output': dados
                    })
                except OSError:
                    break
                    
        print(f"[*] Sessão do terminal '{alias}' encerrada.")
        if alias in self.ativos:
            del self.ativos[alias]

class NodeAgent:
    """Classe principal que orquestra a comunicação de rede e delega tarefas."""
    
    def __init__(self, host_ip=HOST_IP):
        self.config = Config(host_ip)
        self.meu_ip = self._get_local_ip()
        
        self.sio = socketio.Client()
        self.terminal = TerminalManager(self.sio, self.meu_ip)
        
        self._registrar_eventos_websocket()

    def _get_local_ip(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('10.255.255.255', 1))
            ip = s.getsockname()[0]
        except Exception:
            ip = '127.0.0.1'
        finally:
            s.close()
        return ip

    def _registrar_eventos_websocket(self):
        """Configura os listeners do SocketIO dinamicamente."""
        @self.sio.event
        def connect():
            print("[+] Conectado ao servidor de WebSockets do Host!")

        @self.sio.on('*')
        def catch_all(evento, dados):
            prefixo_evento = f"cmd_to_{self.meu_ip}_"
            if evento.startswith(prefixo_evento):
                alias = evento.replace(prefixo_evento, "")
                comando = dados.get('input', '')
                self.terminal.escrever_comando(alias, comando)

    def _executar_tarefa(self, tarefa):
        acao = tarefa.get("acao")
        if acao == "criar_worker":
            WorkerManager.criar(
                tarefa.get("alias", "worker_padrao"), 
                tarefa.get("imagem", "alpine")
            )
        elif acao == "deletar_worker":
            alias = tarefa.get("alias")
            if alias:
                WorkerManager.deletar(alias)

    def iniciar(self):
        """Inicia o loop principal de Polling e a conexão WebSockets."""
        print(f"[*] Node Agent Iniciado. IP: {self.meu_ip}")
        
        try:
            self.sio.connect(self.config.ws_url)
        except Exception as e:
            print(f"[-] Erro ao conectar WebSockets. O terminal web ficará indisponível: {e}")

        while True:
            payload = {
                "ip": self.meu_ip, 
                "status": "Online",
                "workers": WorkerManager.get_installed_workers()
            }
            
            try:
                resposta = requests.post(self.config.http_url, json=payload, timeout=5)
                if resposta.status_code == 200:
                    tarefas = resposta.json().get("tarefas", [])
                    for tarefa in tarefas:
                        self._executar_tarefa(tarefa)
            except requests.exceptions.RequestException:
                pass 
                
            time.sleep(10)


if __name__ == "__main__":
    # Inicializa a classe principal e roda o loop do agente
    agente = NodeAgent(host_ip=HOST_IP)
    agente.iniciar()