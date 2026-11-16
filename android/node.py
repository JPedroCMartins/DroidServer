import hmac
import json
import logging
import os
import pty
import queue
import re
import select
import signal
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler

import requests
import socketio

import servico
from sysinfo import ProcessCPUMonitor, SystemMonitor

log = logging.getLogger("node")

DEFAULT_HOST_PORT = 5050
# Porta em que o node se anuncia para a varredura do painel e recebe o pareamento.
DESCOBERTA_PORTA = int(os.getenv("DROID_NODE_PORT", "5051"))
# Onde o pareamento feito pelo painel é salvo (host, porta e token deste node).
PAREAMENTO_ARQUIVO = os.getenv("DROID_PAREAMENTO_FILE") or os.path.join(
    os.path.expanduser("~"), ".config", "droidserver", "pareamento.json")
# Token gerado pelo host: hexadecimal, 32 a 128 caracteres.
TOKEN_RE = re.compile(r"^[0-9a-f]{32,128}$")
POLL_INTERVAL = 10
# Distribuições do proot-distro aceitas pelo painel (deve espelhar o host).
# Alpine é a recomendada (rootfs pequeno, instala em segundos); Debian é a
# alternativa. O Arch foi retirado: a imagem oficial não tem build arm64.
IMAGENS_PERMITIDAS = {"alpine", "debian"}
# O rootfs do Debian é bem maior que o do Alpine; 20 min cobre redes lentas.
INSTALL_TIMEOUT = 1200
# Limites por container (aplicados com `ulimit` no serviço do Supervisor).
# Defina como 0 para não limitar. Configuráveis por variável de ambiente.
ULIMIT_NOFILE = servico.ULIMIT_NOFILE  # arquivos abertos (DROID_ULIMIT_NOFILE)
ULIMIT_NPROC = servico.ULIMIT_NPROC    # processos (DROID_ULIMIT_NPROC)
# Alias de container só pode conter caracteres seguros (usado em caminhos,
# nomes de serviço do supervisor e nomes de eventos WebSocket).
ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# PID do programa na saída do `supervisorctl status` ("pid 123, uptime ...")
PID_RE = re.compile(r"\bpid (\d+)")
# `proot-distro remove` falha se uma sessão ainda segura o lock do container.
REMOVE_TENTATIVAS = 5
REMOVE_ESPERA = 2  # segundos entre tentativas
# Remove as cores (códigos ANSI) das mensagens do proot-distro.
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _configurar_logging():
    """Configura o logging do agente: console + arquivo rotativo.

    Arquivo padrão: ~/.config/droidserver/logs/node.log (ou DROID_LOG_FILE).
    """
    log_file = os.getenv("DROID_LOG_FILE") or os.path.join(
        os.path.expanduser("~"), ".config", "droidserver", "logs", "node.log"
    )
    raiz = logging.getLogger("node")
    raiz.setLevel(logging.INFO)

    if not any(isinstance(h, logging.Handler) for h in raiz.handlers):
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

        console = logging.StreamHandler()
        console.setFormatter(fmt)
        raiz.addHandler(console)

        try:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            fh = RotatingFileHandler(log_file, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8")
            fh.setFormatter(fmt)
            # DEBUG no arquivo para capturar os diagnósticos de sysinfo (CPU/mem)
            fh.setLevel(logging.DEBUG)
            raiz.addHandler(fh)
        except OSError as e:
            log.warning("Não foi possível criar o arquivo de log '%s': %s", log_file, e)
            log_file = None

    return log_file


def ler_pareamento(arquivo=None):
    """Lê o pareamento salvo. Devolve {host_ip, host_port, token} ou None."""
    try:
        with open(arquivo or PAREAMENTO_ARQUIVO) as f:
            dados = json.load(f)
        if dados.get("host_ip") and TOKEN_RE.fullmatch(dados.get("token", "")):
            return dados
    except (OSError, ValueError, AttributeError):
        pass
    return None


def salvar_pareamento(dados, arquivo=None):
    arquivo = arquivo or PAREAMENTO_ARQUIVO
    os.makedirs(os.path.dirname(arquivo), exist_ok=True)
    tmp = arquivo + ".tmp"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump(dados, f)
    os.replace(tmp, arquivo)  # o token só fica legível pelo usuário do Termux


class Config:
    """Para qual host o agente sincroniza.

    Ordem de prioridade:
    1. argumentos explícitos (testes);
    2. o pareamento feito pelo painel (pareamento.json);
    3. variáveis de ambiente DROID_HOST_IP / DROID_HOST_PORT / DROID_TOKEN
       (modo antigo, configurado à mão).
    Sem nenhum deles, o node fica "não pareado" e só aguarda o painel.
    """

    def __init__(self, host_ip=None, port=None, token=None, arquivo_pareamento=None, usar_env=True):
        par = None if host_ip else ler_pareamento(arquivo_pareamento)
        # origem: "pareamento" (feito pelo painel), "env" (modo antigo) ou "manual"
        if par:
            self.origem = "pareamento"
            self.host_ip = par["host_ip"]
            self.port = int(par.get("host_port") or DEFAULT_HOST_PORT)
            self.token = par["token"]
        else:
            self.origem = "manual" if host_ip else "env"
            self.host_ip = host_ip or (os.getenv("DROID_HOST_IP", "") if usar_env else "")
            self.port = int(port or os.getenv("DROID_HOST_PORT", DEFAULT_HOST_PORT))
            self.token = token if token is not None else os.getenv("DROID_TOKEN", "")
        self.http_url = f"http://{self.host_ip}:{self.port}/api/node_sync"
        self.ws_url = f"http://{self.host_ip}:{self.port}"

    @property
    def pareado(self):
        return bool(self.host_ip)


def _getprop(nome):
    try:
        return subprocess.run(["getprop", nome], capture_output=True, text=True, timeout=3).stdout.strip()
    except Exception:
        return ""


class Descoberta:
    """Respostas do node à varredura e ao pareamento feitos pelo painel.

    A lógica fica aqui (testável sem rede); o servidor HTTP só a repassa.
      GET  /droidserver -> identificação do node
      POST /parear      -> {host_port, token}: o IP do host é o de quem pediu
      POST /desparear   -> {token}: só o host pareado pode desfazer
    Um node já pareado só aceita novo pareamento vindo do mesmo host, para
    que outra máquina da rede não "sequestre" o node, ou de quem provar ser
    o host pareado mandando o token atual (o PC do painel trocou de IP).
    """

    def __init__(self, agente):
        self.agente = agente

    def info(self):
        cfg = self.agente.config
        return 200, {
            "droidserver": True,
            "versao": 1,
            "ip": self.agente.meu_ip,
            "modelo": f"{_getprop('ro.product.manufacturer')} {_getprop('ro.product.model')}".strip() or socket.gethostname(),
            "android": _getprop("ro.build.version.release"),
            # Só conta como pareado o que foi feito por um painel; a configuração
            # antiga por variável de ambiente não impede o pareamento.
            "pareado": cfg.origem == "pareamento" and cfg.pareado,
            "host": f"{cfg.host_ip}:{cfg.port}" if cfg.origem == "pareamento" and cfg.pareado else None,
        }

    def parear(self, ip_cliente, dados):
        cfg = self.agente.config
        # Só um pareamento feito pelo painel protege o node; a configuração
        # antiga por variável de ambiente (sem token) pode ser substituída.
        token_atual = str(dados.get("token_atual") or "")
        mesmo_host = cfg.host_ip == ip_cliente or (
            bool(cfg.token) and hmac.compare_digest(token_atual, cfg.token))
        if cfg.origem == "pareamento" and not mesmo_host:
            return 409, {"ok": False, "erro": f"Node já pareado com {cfg.host_ip}. Desfaça o pareamento por lá."}
        token = str(dados.get("token", ""))
        try:
            porta = int(dados.get("host_port", DEFAULT_HOST_PORT))
        except (TypeError, ValueError):
            porta = 0
        if not TOKEN_RE.fullmatch(token) or not 1 <= porta <= 65535:
            return 400, {"ok": False, "erro": "Token ou porta inválidos."}
        salvar_pareamento({"host_ip": ip_cliente, "host_port": porta, "token": token,
                           "pareado_em": time.strftime("%Y-%m-%d %H:%M:%S")})
        self.agente.recarregar_config()
        log.info("[+] Pareado com o host %s:%s pelo painel.", ip_cliente, porta)
        return 200, {"ok": True, "ip": self.agente.meu_ip}

    def desparear(self, ip_cliente, dados):
        cfg = self.agente.config
        if not cfg.pareado:
            return 200, {"ok": True}
        if ip_cliente != cfg.host_ip or not hmac.compare_digest(str(dados.get("token", "")), cfg.token or ""):
            return 403, {"ok": False, "erro": "Só o host pareado pode desfazer o pareamento."}
        try:
            os.remove(PAREAMENTO_ARQUIVO)
        except OSError:
            pass
        self.agente.recarregar_config(sem_host=True)
        log.info("[*] Pareamento desfeito pelo host %s.", ip_cliente)
        return 200, {"ok": True}


def iniciar_servidor_descoberta(descoberta, porta=None):
    """Sobe o servidor HTTP de descoberta numa thread daemon."""
    class Handler(BaseHTTPRequestHandler):
        def _responder(self, status, corpo):
            dados = json.dumps(corpo).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)

        def do_GET(self):
            if self.path.rstrip("/") == "/droidserver":
                self._responder(*descoberta.info())
            else:
                self._responder(404, {"erro": "não encontrado"})

        def do_POST(self):
            try:
                tamanho = min(int(self.headers.get("Content-Length", 0)), 4096)
                dados = json.loads(self.rfile.read(tamanho) or b"{}")
                if not isinstance(dados, dict):
                    raise ValueError
            except ValueError:
                return self._responder(400, {"ok": False, "erro": "JSON inválido"})
            rota = self.path.rstrip("/")
            if rota == "/parear":
                self._responder(*descoberta.parear(self.client_address[0], dados))
            elif rota == "/desparear":
                self._responder(*descoberta.desparear(self.client_address[0], dados))
            else:
                self._responder(404, {"erro": "não encontrado"})

        def log_message(self, fmt, *args):
            log.debug("descoberta %s - %s", self.address_string(), fmt % args)

    # porta=0 pede ao sistema uma porta livre (usado nos testes)
    servidor = ThreadingHTTPServer(("0.0.0.0", DESCOBERTA_PORTA if porta is None else porta), Handler)
    servidor.daemon_threads = True
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    log.info("[*] Aguardando o painel na porta %d (descoberta e pareamento).", servidor.server_address[1])
    return servidor


class WorkerManager:
    """Classe utilitária para gerenciar as instâncias do proot-distro no sistema."""

    @staticmethod
    def _alias_valido(alias):
        return bool(alias) and bool(ALIAS_RE.fullmatch(alias))

    @staticmethod
    def comando_login(alias, isolado):
        """Argumentos do `proot-distro login`, com ou sem isolamento do host."""
        cmd = ["proot-distro", "login"]
        if isolado:
            # --isolated: não monta home do Termux, /sdcard nem outros diretórios do host.
            cmd.append("--isolated")
        cmd.append(alias)
        return cmd

    @staticmethod
    def esta_isolado(alias):
        """Lê o .conf do Supervisor para saber se o worker foi criado com --isolated."""
        prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
        arquivo = os.path.join(prefix, "etc", "supervisor", "conf.d", f"{alias}.conf")
        try:
            with open(arquivo) as f:
                return "--isolated" in f.read()
        except OSError:
            return False

    @staticmethod
    def _existe(alias):
        prefix = os.environ.get('PREFIX', '/data/data/com.termux/files/usr')
        base = os.path.join(prefix, 'var/lib/proot-distro')
        return (
            os.path.isdir(os.path.join(base, 'installed-rootfs', alias))
            or os.path.isdir(os.path.join(base, 'containers', alias))
        )

    @staticmethod
    def _supervisor_conf():
        prefix = os.environ.get('PREFIX', '/data/data/com.termux/files/usr')
        return os.path.join(prefix, 'etc', 'supervisord.conf')

    @staticmethod
    def _supervisorctl(*args, **kwargs):
        """supervisorctl sempre com o supervisord.conf do Termux (ver servico.py)."""
        return servico.supervisorctl(*args, **kwargs)

    @staticmethod
    def get_installed_workers():
        """Lista os containers instalados no proot-distro.

        Suporta os dois layouts de armazenamento: o antigo
        (var/lib/proot-distro/installed-rootfs) e o novo
        (var/lib/proot-distro/containers), usado por versões recentes.
        """
        prefix = os.environ.get('PREFIX', '/data/data/com.termux/files/usr')
        base = os.path.join(prefix, 'var/lib/proot-distro')

        nomes = set()
        for sub in ('installed-rootfs', 'containers'):
            diretorio = os.path.join(base, sub)
            if not os.path.isdir(diretorio):
                continue
            try:
                nomes.update(os.listdir(diretorio))
            except OSError:
                pass
        return sorted(nomes)

    @staticmethod
    def get_workers_status():
        """Devolve {alias: status} a partir do `supervisorctl status`."""
        return WorkerManager.get_workers_status_e_pids()[0]

    @staticmethod
    def get_workers_status_e_pids():
        """Devolve ({alias: status}, {alias: pid}) a partir do `supervisorctl status`."""
        st = servico.status_supervisor()
        return ({a: s["estado"] for a, s in st.items()},
                {a: s["pid"] for a, s in st.items() if s["pid"]})

    @staticmethod
    def criar(alias, imagem, isolado=True):
        """Cria o container. Devolve (ok: bool, mensagem: str)."""
        log.info("[Deploy] Criando '%s' (%s, isolado=%s)...", alias, imagem, isolado)

        if not WorkerManager._alias_valido(alias):
            return False, f"Alias inválido: '{alias}'"

        if imagem not in IMAGENS_PERMITIDAS:
            return False, f"Distribuição não suportada: '{imagem}'"


        if WorkerManager._existe(alias):
            return False, f"Container '{alias}' já existe"

        prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")

        # Onde o arquivo de configuração do serviço vai ficar
        conf_dir = os.path.join(prefix, "etc", "supervisor", "conf.d")
        arquivo_conf = os.path.join(conf_dir, f"{alias}.conf")

        try:
            # 0. Limpa artefatos residuais do alias: para o serviço antigo,
            #    remove o .conf e purga o metadado do proot-distro. Isso evita
            #    (a) lock do proot-distro segurado pelo supervisor em loop de
            #    restart e (b) "fantasma" em installed-distros.json quando o
            #    rootfs já não existe.
            WorkerManager._supervisorctl("stop", alias)
            if os.path.exists(arquivo_conf):
                os.remove(arquivo_conf)
                log.info("[+] Removida configuração de serviço antiga: %s", arquivo_conf)
            WorkerManager._supervisorctl("reread")
            WorkerManager._supervisorctl("update", alias)
            subprocess.run(["proot-distro", "remove", alias], check=False, capture_output=True, timeout=120)

            # 1. Instala o proot-distro
            proc = subprocess.run(
                ["proot-distro", "install", imagem, "--override-alias", alias],
                capture_output=True, text=True, timeout=INSTALL_TIMEOUT,
            )
            if proc.returncode != 0:
                erro = (proc.stderr or proc.stdout).strip()[:300]
                log.error("[-] Erro ao instalar '%s': %s", alias, erro)
                return False, f"Falha ao instalar '{alias}': {erro}"
            log.info("[+] Container '%s' criado com sucesso!", alias)

            # 2. Lançador do serviço dentro do container, ANTES de registrar no
            #    Supervisor: ele espera o /app/run.sh existir e o executa. Se o
            #    serviço subisse sem ele, falharia e ficaria FATAL.
            servico.instalar_lancador(alias)

            # 3. Registra o serviço no Supervisor
            servico.gravar_conf(alias, isolado=isolado, nofile=ULIMIT_NOFILE, nproc=ULIMIT_NPROC)
            log.info("[+] Arquivo de configuração criado: %s", arquivo_conf)

            # 4. Avisa ao Supervisor que há um novo serviço (equivalente ao systemctl daemon-reload)
            WorkerManager._supervisorctl("reread")
            WorkerManager._supervisorctl("update", alias)
            log.info("[+] Serviço '%s' registrado no Supervisor (aguardando /app/run.sh).", alias)

            return True, f"Container '{alias}' criado com sucesso. Crie o /app/run.sh pela aba Serviço."

        except subprocess.CalledProcessError as e:
            log.error("[-] Erro ao criar o container '%s'.", alias)
            return False, f"Falha ao instalar '{alias}': {e}"
        except Exception as e:
            log.error("[-] Erro inesperado: %s", e)
            return False, f"Erro ao criar '{alias}': {e}"

    @staticmethod
    def _remover_container(alias, tentativas=REMOVE_TENTATIVAS, espera=REMOVE_ESPERA):
        """Executa `proot-distro remove`, tolerando sessões ainda encerrando.

        O remove exige o lock exclusivo do container e falha na hora (não
        espera) se alguma sessão `login` ainda o segura — o que acontece logo
        após parar o serviço no Supervisor ou fechar o terminal. Por isso:
        encerra as sessões restantes com `proot-distro kill` e tenta de novo
        algumas vezes. Devolve (ok, mensagem_de_erro).
        """
        # Versões antigas não têm o subcomando kill; a falha é ignorada.
        subprocess.run(["proot-distro", "kill", alias], check=False, capture_output=True, timeout=60)

        erro = ""
        for tentativa in range(1, tentativas + 1):
            proc = subprocess.run(["proot-distro", "remove", alias],
                                  capture_output=True, text=True, timeout=300)
            if proc.returncode == 0:
                return True, ""
            erro = ANSI_RE.sub("", (proc.stderr or proc.stdout or "").strip())[-300:]
            log.warning("[-] proot-distro remove '%s' falhou (tentativa %d/%d): %s",
                        alias, tentativa, tentativas, erro)
            if tentativa < tentativas:
                time.sleep(espera)
        return False, erro or "proot-distro remove retornou erro"

    @staticmethod
    def deletar(alias):
        """Remove o container. Devolve (ok: bool, mensagem: str).

        Tolerante: cada passo só acontece se o item correspondente existir.
        """
        log.info("[Deploy] Deletando '%s'...", alias)

        if not WorkerManager._alias_valido(alias):
            return False, f"Alias inválido: '{alias}'"

        prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")

        conf_dir = os.path.join(prefix, "etc", "supervisor", "conf.d")
        arquivo_conf = os.path.join(conf_dir, f"{alias}.conf")
        try:
            # 1. Para o serviço no Supervisor (se estiver rodando) para evitar processos zumbis
            WorkerManager._supervisorctl("stop", alias)

            # 2. Remove o arquivo de configuração do Supervisor
            if os.path.exists(arquivo_conf):
                os.remove(arquivo_conf)
                log.info("[+] Arquivo de configuração removido: %s", arquivo_conf)

            # 3. Atualiza o Supervisor para remover o serviço da memória
            WorkerManager._supervisorctl("reread")
            WorkerManager._supervisorctl("update", alias)

            # 4. Remove o container proot-distro (se existir)
            if WorkerManager._existe(alias):
                ok, erro = WorkerManager._remover_container(alias)
                if not ok:
                    return False, f"Falha ao deletar '{alias}': {erro}"
                log.info("[+] Container '%s' deletado com sucesso!", alias)

            # 5. Remove os logs do serviço (atual, rotações e os de versões antigas)
            atual = servico.arquivo_log(alias)
            for caminho in [atual] + [f"{atual}.{n}" for n in range(1, servico.LOG_BACKUPS + 1)] \
                    + servico.logs_antigos(alias):
                if os.path.exists(caminho):
                    os.remove(caminho)
            log.info("[+] Arquivos de log removidos.")

            return True, f"Container '{alias}' deletado"

        except subprocess.TimeoutExpired:
            log.error("[-] Tempo esgotado ao remover '%s'.", alias)
            return False, f"Tempo esgotado ao remover '{alias}'"
        except subprocess.CalledProcessError as e:
            log.error("[-] Erro de processo ao tentar deletar '%s'.", alias)
            return False, f"Falha ao deletar '{alias}': {e}"
        except Exception as e:
            log.error("[-] Erro inesperado ao deletar: %s", e)
            return False, f"Erro ao deletar '{alias}': {e}"


class TerminalManager:
    """Gerencia as sessões ativas do terminal via PTY e processos em background."""

    def __init__(self, socket_client, local_ip):
        self.sio = socket_client
        self.local_ip = local_ip
        self.ativos = {}  # Formato: {"alias": (master_fd, pid)}

    def iniciar_pty(self, alias):
        """Cria um teclado/monitor virtual e roda o Alpine dentro dele."""
        if alias in self.ativos:
            return  # Terminal já está rodando

        log.info("[*] Iniciando PTY (Terminal Virtual) para: %s", alias)
        pid, master_fd = pty.fork()

        if pid == 0:
            # Garante que aplicativos interativos (vim, htop, nano) renderizem corretamente
            os.environ['TERM'] = 'xterm-256color'
            try:
                cmd = WorkerManager.comando_login(alias, WorkerManager.esta_isolado(alias))
                os.execvp(cmd[0], cmd)
            except OSError as e:
                # Sem o exec, este filho seria uma cópia do agente rodando em
                # paralelo: sai na hora, sem executar nada do processo pai.
                try:
                    os.write(2, f"Falha ao abrir o terminal: {e}\r\n".encode())
                finally:
                    os._exit(127)
        else:
            self.ativos[alias] = (master_fd, pid)
            t = threading.Thread(target=self._ler_saida, args=(master_fd, alias, pid), daemon=True)
            t.start()

    def escrever_comando(self, alias, comando):
        """Injeta comandos via WebSocket no PTY correspondente."""
        if alias not in self.ativos:
            self.iniciar_pty(alias)
            time.sleep(0.5)  # Aguarda inicialização

        try:
            os.write(self.ativos[alias][0], comando.encode('utf-8'))
        except OSError:
            log.debug("PTY do '%s' não está mais disponível.", alias)

    def encerrar(self, alias):
        """Encerra a sessão de terminal do worker (usado ao deletar o container).

        Apenas sinaliza o processo: a thread leitora detecta o fim da sessão,
        fecha o descritor do PTY e recolhe o processo (ver _finalizar_sessao).
        """
        if alias not in self.ativos:
            return
        fd, pid = self.ativos.pop(alias)
        try:
            os.write(fd, b'exit\r')
        except OSError:
            pass
        try:
            os.kill(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
        log.info("[*] Sessão de terminal '%s' encerrada manualmente.", alias)

    @staticmethod
    def _finalizar_sessao(master_fd, pid, espera=2.0):
        """Fecha o PTY e recolhe o processo-filho, evitando fd vazado e zumbi."""
        try:
            os.close(master_fd)
        except OSError:
            pass
        limite = time.monotonic() + espera
        while True:
            try:
                recolhido, _ = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                return  # já recolhido (ou não é nosso filho)
            if recolhido:
                return
            if time.monotonic() >= limite:
                break
            time.sleep(0.1)
        # Não saiu com SIGTERM/EOF: força o encerramento e recolhe
        try:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        except (OSError, ChildProcessError):
            pass

    def redimensionar(self, alias, cols, rows):
        """Ajusta o tamanho da janela (TIOCSWINSZ) do PTY para o tamanho do navegador.

        O navegador envia o tamanho assim que a tela do terminal se conecta; se
        ainda não há sessão, ela é aberta aqui. Assim o shell já está pronto (com
        o prompt na tela) quando o usuário digitar, em vez de iniciar na primeira
        tecla e perder/duplicar o que foi digitado durante a inicialização.
        """
        if alias not in self.ativos:
            if not WorkerManager._alias_valido(alias):
                return
            self.iniciar_pty(alias)
            if alias not in self.ativos:
                return
        try:
            import fcntl
            import struct
            import termios
            fcntl.ioctl(
                self.ativos[alias][0],
                termios.TIOCSWINSZ,
                struct.pack('HHHH', int(rows), int(cols), 0, 0),
            )
        except (OSError, ValueError):
            log.debug("Falha ao redimensionar PTY do '%s'.", alias)

    def _ler_saida(self, master_fd, alias, pid=None):
        """Fica lendo a tela do container e enviando pro Flask (Thread)."""
        while True:
            try:
                r, _, _ = select.select([master_fd], [], [])
            except (OSError, ValueError):
                break
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
        # Só remove o registro se ainda for esta sessão (pode já haver uma nova)
        if self.ativos.get(alias, (None,))[0] == master_fd:
            del self.ativos[alias]
        if pid is not None:
            self._finalizar_sessao(master_fd, pid)


class NodeAgent:
    """Classe principal que orquestra a comunicação de rede e delega tarefas."""

    def __init__(self, host_ip=None, port=None):
        self.config = Config(host_ip=host_ip, port=port)
        self.meu_ip = self._get_local_ip()

        self.sio = socketio.Client()
        self.terminal = TerminalManager(self.sio, self.meu_ip)
        self.monitor = SystemMonitor()
        # CPU dos processos do Termux (total e por worker): funciona sem root
        self.cpu_processos = ProcessCPUMonitor()
        # Logs do serviço de cada worker, enviados ao painel enquanto alguém assiste
        self.logs = servico.LogsAoVivo(self._enviar_logs)

        # Resultado das tarefas executadas, enviado no próximo sync.
        # Escrito pela thread de tarefas e lido/limpo pela thread de polling.
        self._resultados = []
        self._lock_resultados = threading.Lock()
        # Tarefa atualmente em execução na thread de background.
        self._tarefa_atual = None

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

    def _atualizar_ip(self):
        """Detecta de novo o IP da rede (o DHCP pode trocá-lo, ex.: Wi-Fi religado).

        O IP vai no sync e forma os nomes dos eventos (cmd_to_<ip>_...); com o IP
        novo, o host reconhece o node pelo token e move o cadastro para ele.
        """
        novo = self._get_local_ip()
        if novo != self.meu_ip and novo != "127.0.0.1":
            log.info("[*] IP do node mudou: %s -> %s", self.meu_ip, novo)
            self.meu_ip = novo
            self.terminal.local_ip = novo
        return self.meu_ip

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
                if not WorkerManager._alias_valido(alias):
                    return
                comando = dados.get('input', '')
                self.terminal.escrever_comando(alias, comando)
                return

            if evento == f"servico_to_{self.meu_ip}":
                threading.Thread(target=self._comando_servico, args=(dados or {},), daemon=True).start()
                return

            if evento == f"logs_to_{self.meu_ip}":
                alias = (dados or {}).get("alias")
                if (dados or {}).get("acao") == "cancelar":
                    self.logs.cancelar(alias)
                else:
                    threading.Thread(target=self.logs.assinar, args=(alias,), daemon=True).start()
                return

            prefixo_resize = f"resize_to_{self.meu_ip}_"
            if evento.startswith(prefixo_resize):
                alias = evento.replace(prefixo_resize, "")
                if not WorkerManager._alias_valido(alias):
                    return
                self.terminal.redimensionar(alias, dados.get('cols'), dados.get('rows'))

    def _enviar_logs(self, alias, linhas, inicial):
        try:
            self.sio.emit('logs_saida', {'ip': self.meu_ip, 'alias': alias,
                                         'linhas': linhas, 'inicial': inicial})
        except Exception as e:
            log.debug("Falha ao enviar logs de '%s': %s", alias, e)

    def _comando_servico(self, dados):
        """Executa um comando da aba Serviço e responde ao navegador que pediu."""
        alias, acao = dados.get("alias"), dados.get("acao")
        try:
            ok, msg, extra = servico.executar(alias, acao, dados.get("dados") or {})
        except Exception as e:
            log.exception("Erro no comando de serviço %s/%s", alias, acao)
            ok, msg, extra = False, f"Erro inesperado: {e}", {}
        log.info("[Serviço] %s %s -> %s (%s)", alias, acao, "ok" if ok else "falhou", msg)
        try:
            self.sio.emit('servico_resposta', {
                'ip': self.meu_ip, 'alias': alias, 'acao': acao, 'sid': dados.get("sid"),
                'req': dados.get("req"), 'ok': ok, 'msg': msg, 'dados': extra,
                'servico': servico.estado_servicos([alias]).get(alias),
            })
        except Exception as e:
            log.warning("Falha ao responder comando de serviço: %s", e)

    def recarregar_config(self, sem_host=False):
        """Relê o pareamento (chamado quando o painel pareia ou despareia).

        Depois de um despareamento, as variáveis DROID_HOST_IP do modo antigo
        são ignoradas: o node fica aguardando o painel.
        """
        self.config = Config(usar_env=not sem_host)
        # Força o WebSocket a reconectar no host novo no próximo ciclo
        if self.sio.connected:
            try:
                self.sio.disconnect()
            except Exception:
                pass

    def _conectar_ws(self):
        """Mantém a conexão WebSocket ativa; não bloqueia se já estiver conectado.

        O reconnect do socketio-client só atua após uma conexão inicial bem-sucedida,
        então tentamos novamente em cada ciclo do loop.
        """
        if self.sio.connected:
            return True
        if not self.config.pareado:
            return False
        try:
            self.sio.connect(self.config.ws_url)
            return True
        except Exception as e:
            log.warning("[-] WebSocket indisponível (%s). Nova tentativa no próximo ciclo.", e)
            return False

    def _poll_once(self):
        """Sincroniza com o host uma única vez e devolve as tarefas pendentes."""
        with self._lock_resultados:
            enviados = list(self._resultados)
        status_sup = servico.status_supervisor()
        worker_status = {a: s["estado"] for a, s in status_sup.items()}
        worker_pids = {a: s["pid"] for a, s in status_sup.items() if s["pid"]}
        workers = WorkerManager.get_installed_workers()
        payload = {
            "ip": self.meu_ip,
            "status": "Online",
            "workers": workers,
            "servicos": servico.estado_servicos(workers, status_sup),
            "worker_status": worker_status,
            "tarefa_atual": self._tarefa_atual,
            "resultados": enviados,
            # logs que este agente está acompanhando: o host reconcilia com
            # quem está assistindo (ex.: depois de o agente reiniciar)
            "logs_ativos": sorted(self.logs.ativos()),
        }
        uso = self.monitor.sample()
        payload["cpu"] = uso["cpu"]
        payload["mem"] = uso["mem"]
        cpu_proc = self.cpu_processos.sample(self._grupos_de_processos(worker_pids))
        payload["cpu_termux"] = cpu_proc["total"]
        payload["cpu_workers"] = cpu_proc["grupos"]
        if self.config.token:
            payload["token"] = self.config.token

        try:
            resposta = requests.post(self.config.http_url, json=payload, timeout=5)
            if resposta.status_code == 200:
                # Remove só o que foi enviado: resultados registrados durante o
                # POST ficam para o próximo sync em vez de serem descartados.
                ids_enviados = {id(r) for r in enviados}
                with self._lock_resultados:
                    self._resultados[:] = [r for r in self._resultados if id(r) not in ids_enviados]
                tarefas = resposta.json().get("tarefas", [])
                mem_pct = payload["mem"]["percent"] if payload.get("mem") else None
                log.info("Sync OK com host (cpu=%s%%, cpu_termux=%s%%, mem=%s%%, workers=%s, %d tarefa(s))",
                         payload.get("cpu"), payload.get("cpu_termux"), mem_pct,
                         payload.get("cpu_workers"), len(tarefas))
                return tarefas
            if resposta.status_code == 401:
                log.warning("[-] O host %s não reconhece este node (token inválido ou node removido). "
                            "Adicione-o de novo pelo painel.", self.config.host_ip)
            else:
                log.warning("[-] Host respondeu com status %s.", resposta.status_code)
        except requests.exceptions.RequestException as e:
            log.warning("[-] Erro ao sincronizar com o host: %s", e)
        return []

    def _grupos_de_processos(self, worker_pids):
        """{alias: [pids raiz]}: o serviço no Supervisor e a sessão de terminal, se houver."""
        grupos = {alias: [pid] for alias, pid in worker_pids.items()}
        for alias, (_, pid) in list(self.terminal.ativos.items()):
            grupos.setdefault(alias, []).append(pid)
        return grupos

    def _processa_fila(self):
        """Consome as tarefas da fila em background (thread daemon)."""
        while True:
            tarefa = self._fila_tarefas.get()
            self._tarefa_atual = tarefa
            try:
                self._executar_tarefa(tarefa)
            except Exception as e:
                log.error("[-] Erro ao executar tarefa %s: %s", tarefa, e)
            finally:
                self._tarefa_atual = None

    def _registrar_resultado(self, acao, alias, ok, msg):
        with self._lock_resultados:
            self._resultados.append({
                "acao": acao,
                "alias": alias,
                "ok": bool(ok),
                "msg": msg,
                "ts": time.strftime("%H:%M:%S"),
            })
            # Mantém apenas os últimos resultados (evita payload gigante)
            del self._resultados[:-10]
        if ok:
            log.info("[+] Tarefa OK: %s", msg)
        else:
            log.error("[-] Tarefa FALHOU: %s", msg)

    def _executar_tarefa(self, tarefa):
        acao = tarefa.get("acao")
        if acao == "criar_worker":
            alias = tarefa.get("alias", "worker_padrao")
            imagem = tarefa.get("imagem", "alpine")
            isolado = bool(tarefa.get("isolado", True))
            try:
                ok, msg = WorkerManager.criar(alias, imagem, isolado)
            except Exception as e:
                ok, msg = False, f"Erro inesperado ao criar '{alias}': {e}"
            self._registrar_resultado(acao, alias, ok, msg)

        elif acao == "deletar_worker":
            alias = tarefa.get("alias")
            if not alias:
                self._registrar_resultado(acao, None, False, "Alias ausente na tarefa")
                return
            self.terminal.encerrar(alias)
            self.logs.cancelar(alias)
            try:
                ok, msg = WorkerManager.deletar(alias)
            except Exception as e:
                ok, msg = False, f"Erro inesperado ao deletar '{alias}': {e}"
            self._registrar_resultado(acao, alias, ok, msg)

        else:
            log.warning("Tarefa desconhecida ignorada: %s", tarefa)

    def _loop(self):
        """Loop principal de Polling e manutenção da conexão WebSockets."""
        log.info("[*] Node Agent iniciado. IP: %s | Host: %s", self.meu_ip,
                 self.config.http_url if self.config.pareado else "nenhum (aguardando pareamento)")

        avisou = False
        while True:
            if not self.config.pareado:
                if not avisou:
                    log.info("[*] Node não pareado. Adicione o IP %s pelo painel do DroidServer.", self.meu_ip)
                    avisou = True
                time.sleep(POLL_INTERVAL)
                continue
            avisou = False
            self._atualizar_ip()
            self._conectar_ws()
            tarefas = self._poll_once()
            for tarefa in tarefas:
                log.info("Tarefa recebida: %s", tarefa)
                self._fila_tarefas.put(tarefa)
            time.sleep(POLL_INTERVAL)

    def iniciar(self):
        # Workers criados por versões anteriores passam a usar o lançador /app/run.sh
        try:
            migrados = servico.migrar_todos(WorkerManager.get_installed_workers())
            if migrados:
                log.info("[+] Serviços migrados para /app/run.sh: %s", ", ".join(migrados))
        except Exception:
            log.exception("[-] Falha ao migrar os serviços dos workers")
        try:
            self.servidor_descoberta = iniciar_servidor_descoberta(Descoberta(self))
        except OSError as e:
            log.error("[-] Não foi possível abrir a porta %d de descoberta: %s", DESCOBERTA_PORTA, e)
        self._loop()


if __name__ == "__main__":
    log_file = _configurar_logging()
    log.info("[*] Node Agent iniciando. Log de arquivo: %s", log_file or "desativado")
    NodeAgent().iniciar()
