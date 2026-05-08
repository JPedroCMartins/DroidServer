import stat
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
            print(f"[+] Container '{alias}' criado com sucesso!")
            
            # 2. Garante que as pastas de configuração e logs existam
            os.makedirs(conf_dir, exist_ok=True)
            os.makedirs(os.path.dirname(log_out), exist_ok=True)
            
            # 3. Cria o arquivo de configuração do Supervisor
            with open(arquivo_conf, "w") as f:
                f.write(conteudo_conf)
            print(f"[+] Arquivo de configuração criado: {arquivo_conf}")
            
            # 4. Avisa ao Supervisor que há um novo serviço (equivalente ao systemctl daemon-reload)
            # O 'reread' lê os arquivos novos, e o 'update' inicia os serviços pendentes
            subprocess.run(["supervisorctl", "reread"], check=False, capture_output=True)
            subprocess.run(["supervisorctl", "update"], check=False, capture_output=True)
            
            print(f"[+] Serviço '{alias}' registrado e iniciado no Supervisor.")
            
        except subprocess.CalledProcessError:
            print(f"[-] Erro ao criar o container '{alias}'.")
        except Exception as e:
            print(f"[-] Erro inesperado: {e}")

    @staticmethod
    def deletar(alias):
        print(f"[*] Deploy: Deletando '{alias}'...")
        
        prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
        
        # Onde o arquivo de configuração e os logs estão localizados
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
                print(f"[+] Arquivo de configuração removido: {arquivo_conf}")
            
            # 3. Atualiza o Supervisor para remover o serviço da memória
            subprocess.run(["supervisorctl", "reread"], check=False, capture_output=True)
            subprocess.run(["supervisorctl", "update"], check=False, capture_output=True)
            
            # 4. Remove o container proot-distro
            subprocess.run(["proot-distro", "remove", alias], check=True)
            print(f"[+] Container '{alias}' deletado com sucesso!")
            
            # 5. Remove os arquivos de log associados
            if os.path.exists(log_out):
                os.remove(log_out)
            if os.path.exists(log_err):
                os.remove(log_err)
            print(f"[+] Arquivos de log removidos.")

        except subprocess.CalledProcessError:
            print(f"[-] Erro de processo ao tentar deletar '{alias}'.")
        except Exception as e:
            print(f"[-] Erro inesperado ao deletar: {e}")

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