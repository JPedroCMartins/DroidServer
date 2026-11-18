"""Serviço de cada worker: o que roda (/app/run.sh), como (Supervisor) e os logs.

Cada worker tem um único serviço: o arquivo /app/run.sh dentro do container.
O Supervisor não executa o run.sh diretamente, e sim um *lançador*
(/app/.droidserver/lancador.sh) que espera o run.sh existir e então o executa
em primeiro plano. Assim:

- basta criar o /app/run.sh (pelo painel ou pelo terminal) para o serviço subir;
- o Supervisor vigia o processo do serviço e o reinicia se cair;
- a saída e os erros vão para um único log, que o painel mostra ao vivo.

O rootfs de cada container pertence ao usuário do Termux, então o agente lê e
grava o run.sh e o lançador diretamente, sem abrir uma sessão do proot.
"""

import logging
import os
import re
import signal
import subprocess
import threading
import time

log = logging.getLogger("node.servico")

ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# Nome reservado do programa do Cloudflare Tunnel (tunnel.py): não é um container
TUNNEL = "tunnel"

# Caminhos dentro do container
APP_DIR = "app"
SCRIPT_NOME = "run.sh"
SCRIPT_ANTIGO = "run_server.sh"           # versões anteriores do DroidServer
LANCADOR_REL = ".droidserver/lancador.sh"  # relativo a /app
LANCADOR_INTERNO = "/app/" + LANCADOR_REL

# Marca nos .conf gerados por esta versão (permite migrar os antigos)
CONF_VERSAO = "; droidserver-conf: 3"

# Limites por container (ulimit no serviço). 0 = sem limite.
ULIMIT_NOFILE = int(os.getenv("DROID_ULIMIT_NOFILE", "4096"))  # arquivos abertos
ULIMIT_NPROC = int(os.getenv("DROID_ULIMIT_NPROC", "1024"))    # processos

SCRIPT_MAX = 64 * 1024        # tamanho máximo do run.sh editado pelo painel
LOG_LINHAS_INICIAIS = 200     # linhas enviadas ao abrir os logs
LOG_INTERVALO = 1.0           # segundos entre leituras do log ao vivo
LOG_MAX_BYTES = "1MB"         # rotação do log do serviço (Supervisor)
LOG_BACKUPS = 3

LANCADOR = """#!/bin/sh
# DroidServer - lançador do serviço deste worker. NÃO edite este arquivo:
# o serviço é o /app/run.sh (edite-o pela aba Serviço do painel).
cd /app 2>/dev/null || cd /
if [ ! -f /app/run.sh ]; then
    echo "[DroidServer] Aguardando /app/run.sh - crie o arquivo pela aba Serviço do painel."
    while [ ! -f /app/run.sh ]; do sleep 2; done
fi
echo "[DroidServer] Iniciando /app/run.sh ($(date '+%Y-%m-%d %H:%M:%S'))"
# Com shebang (#!/bin/bash, #!/usr/bin/env python3...) e executável, roda com o
# interpretador indicado; sem shebang, com o sh.
if [ -x /app/run.sh ] && [ "$(head -c 2 /app/run.sh)" = "#!" ]; then
    exec /app/run.sh
fi
exec sh /app/run.sh
"""

# Script ocioso criado por versões anteriores (não é um serviço de verdade)
SCRIPT_OCIOSO_ANTIGO = "while true; do sleep 30; done"

EXEMPLO = """#!/bin/sh
# droidserver: porta=8080
# (a linha acima informa ao painel em que porta o serviço escuta)
# Serviço deste worker. O DroidServer executa este arquivo e o reinicia se ele
# terminar. Regras:
#   - o serviço precisa ficar em PRIMEIRO PLANO (sem "&" nem "nohup");
#   - use "exec" no último comando, para o Supervisor vigiar o processo certo;
#   - a porta aberta aqui fica acessível em http://<ip-do-celular>:<porta>
#     (a rede não é isolada: dois workers não podem usar a mesma porta).
cd /app

# Exemplo: servidor HTTP simples na porta 8080, servindo os arquivos de /app.
# Na primeira execução instala o Python, se faltar (Alpine vem sem ele).
if ! command -v python3 >/dev/null; then
    echo "Instalando python3..."
    if command -v apk >/dev/null; then apk add --no-cache python3
    else apt-get update && apt-get install -y python3-minimal
    fi
fi
exec python3 -m http.server 8080
"""


def _prefix():
    return os.environ.get("PREFIX", "/data/data/com.termux/files/usr")


def alias_valido(alias):
    return bool(alias) and bool(ALIAS_RE.fullmatch(str(alias)))


def supervisor_conf():
    return os.path.join(_prefix(), "etc", "supervisord.conf")


def supervisorctl(*args, **kwargs):
    """supervisorctl sempre apontando para o supervisord.conf do Termux."""
    kwargs.setdefault("check", False)
    kwargs.setdefault("capture_output", True)
    return subprocess.run(["supervisorctl", "-c", supervisor_conf(), *args], **kwargs)


def arquivo_conf(alias):
    return os.path.join(_prefix(), "etc", "supervisor", "conf.d", f"{alias}.conf")


def arquivo_log(alias):
    return os.path.join(_prefix(), "var", "log", f"droidserver_{alias}.log")


def logs_antigos(alias):
    base = os.path.join(_prefix(), "var", "log")
    return [os.path.join(base, f"supervisor_{alias}_out.log"),
            os.path.join(base, f"supervisor_{alias}_err.log")]


def rootfs(alias):
    """Diretório raiz do container (layouts novo e antigo do proot-distro)."""
    base = os.path.join(_prefix(), "var", "lib", "proot-distro")
    for caminho in (os.path.join(base, "containers", alias, "rootfs"),
                    os.path.join(base, "installed-rootfs", alias)):
        if os.path.isdir(caminho):
            return caminho
    return None


def caminho_app(alias, *partes):
    raiz = rootfs(alias)
    return os.path.join(raiz, APP_DIR, *partes) if raiz else None


def _dentro_do_container(alias, caminho):
    """True se `caminho` não sai do rootfs por link simbólico.

    O agente acessa o rootfs pelo Termux, fora do proot: um link criado dentro
    do container (ex.: /app/run.sh -> arquivo do Termux) seria seguido aqui e
    furaria o isolamento. Links não são aceitos no caminho do run.sh.
    """
    raiz = rootfs(alias)
    if not raiz or not caminho:
        return False
    raiz_real = os.path.realpath(raiz)
    return os.path.islink(caminho) is False and \
        os.path.realpath(caminho).startswith(raiz_real + os.sep)


# ---------------------------------------------------------------------------
# Supervisor: .conf do serviço
# ---------------------------------------------------------------------------

def prefixo_ulimit(nofile, nproc):
    partes = []
    if nofile > 0:
        partes.append(f"ulimit -n {nofile} 2>/dev/null;")
    if nproc > 0:
        partes.append(f"ulimit -u {nproc} 2>/dev/null;")
    return " ".join(partes) + (" " if partes else "")


def conteudo_conf(alias, isolado=True, autostart=True, autorestart=True, nofile=None, nproc=None):
    nofile = ULIMIT_NOFILE if nofile is None else nofile
    nproc = ULIMIT_NPROC if nproc is None else nproc
    login = "proot-distro login " + ("--isolated " if isolado else "") + alias
    return "\n".join([
        f"[program:{alias}]",
        CONF_VERSAO,
        f"command=sh -c '{prefixo_ulimit(nofile, nproc)}exec {login} -- /bin/sh {LANCADOR_INTERNO}'",
        f"autostart={'true' if autostart else 'false'}",
        f"autorestart={'true' if autorestart else 'false'}",
        "startsecs=5",
        # Tolera um processo anterior que ainda está liberando a porta
        "startretries=5",
        "stopasgroup=true",
        "killasgroup=true",
        "redirect_stderr=true",
        f"stdout_logfile={arquivo_log(alias)}",
        f"stdout_logfile_maxbytes={LOG_MAX_BYTES}",
        f"stdout_logfile_backups={LOG_BACKUPS}",
        "",
    ])


def ler_opcoes(alias):
    """Lê o .conf do worker. Devolve None se não houver serviço registrado."""
    try:
        with open(arquivo_conf(alias)) as f:
            texto = f.read()
    except OSError:
        return None

    def valor(chave, padrao):
        m = re.search(rf"^\s*{chave}\s*=\s*(\w+)", texto, re.M)
        return (m.group(1).lower() == "true") if m else padrao

    return {
        "isolado": "--isolated" in texto,
        "autostart": valor("autostart", True),
        "autorestart": valor("autorestart", True),
        "atual": CONF_VERSAO in texto,
    }


def gravar_conf(alias, **opcoes):
    caminho = arquivo_conf(alias)
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    os.makedirs(os.path.dirname(arquivo_log(alias)), exist_ok=True)
    with open(caminho, "w") as f:
        f.write(conteudo_conf(alias, **opcoes))


# ---------------------------------------------------------------------------
# Arquivos dentro do container
# ---------------------------------------------------------------------------

def _gravar_atomico(caminho, conteudo, modo):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    tmp = caminho + ".tmp"
    with open(tmp, "w") as f:
        f.write(conteudo)
    os.chmod(tmp, modo)
    os.replace(tmp, caminho)


def instalar_lancador(alias):
    """Grava /app/.droidserver/lancador.sh no container. Devolve True se ok."""
    destino = caminho_app(alias, LANCADOR_REL)
    if not destino:
        log.warning("[-] Rootfs de '%s' não encontrado; lançador não instalado.", alias)
        return False
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    if not _dentro_do_container(alias, destino):
        log.warning("[-] '%s': /app/.droidserver aponta para fora do container; lançador não instalado.", alias)
        return False
    try:
        with open(destino) as f:
            if f.read() == LANCADOR:
                return True
    except OSError:
        pass
    _gravar_atomico(destino, LANCADOR, 0o755)
    return True


def ler_script(alias):
    """Conteúdo do /app/run.sh, ou None se ainda não existe."""
    caminho = caminho_app(alias, SCRIPT_NOME)
    if not caminho or not _dentro_do_container(alias, caminho):
        return None
    try:
        with open(caminho, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def salvar_script(alias, conteudo):
    """Grava o /app/run.sh (até 64 KB, quebras de linha Unix, executável)."""
    if not isinstance(conteudo, str):
        return False, "Conteúdo inválido."
    conteudo = conteudo.replace("\r\n", "\n").replace("\r", "\n")
    if len(conteudo.encode("utf-8")) > SCRIPT_MAX:
        return False, "O run.sh passa de 64 KB."
    if "\0" in conteudo:
        return False, "O run.sh não pode conter bytes nulos."
    if conteudo and not conteudo.endswith("\n"):
        conteudo += "\n"
    caminho = caminho_app(alias, SCRIPT_NOME)
    if not caminho:
        return False, f"Container '{alias}' não encontrado."
    if not _dentro_do_container(alias, caminho):
        return False, "O /app/run.sh (ou o /app) é um link simbólico; troque-o por um arquivo comum."
    _gravar_atomico(caminho, conteudo, 0o755)
    return True, "run.sh salvo."


def avisos_script(conteudo):
    """Erros comuns de quem escreve um run.sh (mostrados no painel)."""
    avisos = []
    linhas = [l.strip() for l in (conteudo or "").splitlines()
              if l.strip() and not l.strip().startswith("#")]
    if linhas:
        ultima = linhas[-1]
        if ultima.endswith("&") and not ultima.endswith("&&"):
            avisos.append("A última linha termina com '&': o serviço vai para segundo plano, "
                          "o run.sh termina e o DroidServer o reinicia em loop. Remova o '&'.")
        if re.match(r"^(nohup|setsid|disown)\b", ultima):
            avisos.append("O serviço precisa ficar em primeiro plano: não use nohup/setsid.")
    return avisos


# ---------------------------------------------------------------------------
# Migração dos workers criados por versões anteriores
# ---------------------------------------------------------------------------

def migrar(alias):
    """Converte um worker antigo (Supervisor rodando /app/run_server.sh).

    - instala o lançador;
    - se havia um run_server.sh próprio do usuário e ainda não há run.sh, ele
      vira o run.sh (o script ocioso padrão das versões antigas é descartado);
    - reescreve o .conf mantendo isolamento/autostart/autorestart.
    Devolve True se algo mudou (o chamador faz reread/update).
    """
    opcoes = ler_opcoes(alias)
    if opcoes is None or opcoes["atual"] or not rootfs(alias):
        return False

    instalar_lancador(alias)
    antigo = caminho_app(alias, SCRIPT_ANTIGO)
    novo = caminho_app(alias, SCRIPT_NOME)
    try:
        with open(antigo) as f:
            conteudo_antigo = f.read()
    except OSError:
        conteudo_antigo = None
    if conteudo_antigo is not None:
        if SCRIPT_OCIOSO_ANTIGO in conteudo_antigo:
            os.remove(antigo)
        elif not os.path.exists(novo):
            os.replace(antigo, novo)
            os.chmod(novo, 0o755)
            log.info("[+] '%s': /app/run_server.sh migrado para /app/run.sh", alias)

    gravar_conf(alias, isolado=opcoes["isolado"], autostart=opcoes["autostart"],
                autorestart=opcoes["autorestart"])
    log.info("[+] '%s': serviço migrado para o lançador /app/run.sh", alias)
    return True


def precisa_migrar(alias):
    opcoes = ler_opcoes(alias)
    return opcoes is not None and not opcoes["atual"] and rootfs(alias) is not None


def migrar_todos(aliases):
    # O lançador de versões anteriores é atualizado em todos (sem reiniciar:
    # vale a partir da próxima vez que o serviço subir)
    for alias in aliases:
        if alias_valido(alias) and rootfs(alias) and ler_opcoes(alias):
            try:
                instalar_lancador(alias)
            except OSError as e:
                log.warning("[-] '%s': não foi possível atualizar o lançador: %s", alias, e)
    pendentes = [a for a in aliases if alias_valido(a) and precisa_migrar(a)]
    for alias in pendentes:
        # O .conf antigo não mata o grupo de processos ao parar: o programa do
        # usuário (ex.: um servidor na porta 8080) sobrevivia alguns segundos
        # ao proot-distro, e o serviço novo falhava com "Address in use" até
        # ficar FATAL. Por isso o serviço antigo é parado e as sessões do
        # container são encerradas antes da troca.
        supervisorctl("stop", alias, timeout=60)
        subprocess.run(["proot-distro", "kill", alias], check=False, capture_output=True, timeout=60)
    mudou = [a for a in pendentes if migrar(a)]
    if mudou:
        # update só dos migrados: um "update" geral aplicaria também
        # alterações pendentes de outros workers e os reiniciaria
        supervisorctl("reread")
        supervisorctl("update", *mudou)
    return mudou


# ---------------------------------------------------------------------------
# Estado do serviço
# ---------------------------------------------------------------------------

PID_RE = re.compile(r"\bpid (\d+)")
UPTIME_RE = re.compile(r"uptime ((?:\d+ days?, )?\d+:\d{2}:\d{2})")


def status_supervisor():
    """{alias: {estado, pid, uptime, detalhe}} a partir do `supervisorctl status`.

    O supervisorctl 4.x sai com código != 0 sempre que algum programa não está
    RUNNING, mas a saída continua válida; por isso o código é ignorado.
    """
    try:
        proc = supervisorctl("status", text=True, timeout=5)
    except Exception:
        return {}
    status = {}
    for linha in (proc.stdout or "").splitlines():
        partes = linha.split(None, 2)
        if len(partes) < 2 or not alias_valido(partes[0]):
            continue
        resto = partes[2] if len(partes) > 2 else ""
        pid = PID_RE.search(resto)
        uptime = UPTIME_RE.search(resto)
        status[partes[0]] = {
            "estado": partes[1],
            "pid": int(pid.group(1)) if pid else None,
            "uptime": uptime.group(1) if uptime else None,
            "detalhe": "" if pid else resto.strip(),
        }
    return status


# Metadados no próprio run.sh, em comentário: "# droidserver: porta=8080 tipo=api"
METADADOS_RE = re.compile(r"^\s*#\s*droidserver:\s*(.*)$", re.I)
PAR_RE = re.compile(r"(\w+)\s*=\s*(\S+)")


def ler_metadados(conteudo):
    """Lê os metadados do cabeçalho do run.sh. A porta só vale se for 1-65535."""
    pares = {}
    for linha in (conteudo or "").splitlines():
        m = METADADOS_RE.match(linha)
        if m:
            pares.update({k.lower(): v for k, v in PAR_RE.findall(m.group(1))})
    porta = pares.get("porta", "")
    # só dígitos ASCII: "8080²" passa em isdigit() mas quebra o int()
    valida = re.fullmatch(r"[0-9]{1,5}", porta) and 1 <= int(porta) <= 65535
    return {"porta": int(porta) if valida else None}


# Falhas registradas pelo supervisord: "... WARN exited: w1 (exit status 127; not expected)"
# ...também "exited: w1 (terminated by SIGKILL; not expected)", como o Android
# encerra processos por falta de memória
FALHA_RE = re.compile(r"^(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d),\d+ \w+ exited: (\S+) "
                      r"\((?:exit status (\d+)|terminated by (SIG\w+))[^;]*; not expected\)")
MOTIVOS = {126: "sem permissão de execução", 127: "comando não encontrado",
           137: "encerrado pelo sistema (memória ou kill)", 143: "encerrado (SIGTERM)"}


def supervisord_log():
    """Log do supervisord, conforme o logfile= do supervisord.conf."""
    try:
        with open(supervisor_conf(), encoding="utf-8", errors="replace") as f:
            m = re.search(r"^\s*logfile\s*=\s*(\S+)", f.read(), re.M)
        if m:
            return m.group(1)
    except OSError:
        pass
    return os.path.join(_prefix(), "var", "log", "supervisor", "supervisord.log")


def falhas_do_dia(aliases, hoje=None):
    """{alias: {falhas_hoje, ultima_falha}} a partir das saídas inesperadas do dia."""
    hoje = hoje or time.strftime("%Y-%m-%d")
    resultado = {a: {"falhas_hoje": 0, "ultima_falha": None} for a in aliases}
    linhas, _ = ultimas_linhas(supervisord_log(), n=3000)
    for linha in linhas:
        m = FALHA_RE.match(linha)
        if not m or m.group(1) != hoje or m.group(3) not in resultado:
            continue
        if m.group(4) is not None:
            codigo = int(m.group(4))
        else:  # morte por sinal: código de saída equivalente do shell (128 + n)
            try:
                codigo = 128 + signal.Signals[m.group(5)].value
            except KeyError:
                codigo = None
        r = resultado[m.group(3)]
        r["falhas_hoje"] += 1
        r["ultima_falha"] = {"quando": m.group(2), "codigo": codigo,
                             "motivo": MOTIVOS.get(codigo, f"erro no programa (código {codigo})"
                                                   if codigo is not None else f"encerrado por {m.group(5)}")}
    return resultado


_cache_distro = {}


def distro(alias):
    """PRETTY_NAME do os-release do container (em cache por rootfs)."""
    raiz = rootfs(alias)
    if not raiz:
        return None
    if raiz not in _cache_distro:
        nome = None
        for rel in ("etc/os-release", "usr/lib/os-release"):
            try:
                with open(os.path.join(raiz, rel), encoding="utf-8", errors="replace") as f:
                    m = re.search(r'^PRETTY_NAME=["\']?(.*?)["\']?\s*$', f.read(), re.M)
            except OSError:
                continue
            if m:
                nome = m.group(1)
                break
        if nome is None:
            return None  # rootfs ainda sendo extraído: tenta de novo no próximo sync
        _cache_distro[raiz] = nome
    return _cache_distro[raiz]


class DiscoCache:
    """Tamanho do rootfs de cada worker, calculado com `du` em segundo plano.

    O `du` de um Debian leva segundos: nunca roda no caminho do sync. A
    consulta devolve o último valor conhecido (None até o 1º cálculo) e, se
    ele venceu, dispara um novo cálculo numa thread.
    """

    def __init__(self, validade=600, relogio=time.monotonic):
        self.validade, self.relogio = validade, relogio
        self._valores = {}       # rootfs -> (mb ou None, quando)
        self._calculando = set()
        self._lock = threading.Lock()

    def mb(self, alias, raiz=None):
        raiz = raiz or rootfs(alias)
        if not raiz:
            return None
        with self._lock:
            valor, quando = self._valores.get(raiz, (None, None))
            vencido = quando is None or self.relogio() - quando >= self.validade
            if vencido and raiz not in self._calculando:
                self._calculando.add(raiz)
                threading.Thread(target=self._calcular, args=(raiz,), daemon=True).start()
        return valor

    def _calcular(self, raiz):
        anterior = self._valores.get(raiz, (None, None))[0]
        try:
            proc = subprocess.run(["du", "-sk", raiz], capture_output=True, text=True, timeout=300)
            valor = round(int(proc.stdout.split()[0]) / 1024, 1)
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            valor = anterior  # falhou: mantém o último valor conhecido
        with self._lock:
            self._valores[raiz] = (valor, self.relogio())
            self._calculando.discard(raiz)


disco = DiscoCache()


def _salvo_em(alias):
    caminho = caminho_app(alias, SCRIPT_NOME)
    if not caminho or not _dentro_do_container(alias, caminho):
        return None
    try:
        return os.path.getmtime(caminho)
    except OSError:
        return None


def estado_servicos(aliases, status=None):
    """Estado de cada serviço para o painel."""
    import banco  # importado aqui: o banco.py importa este módulo
    status = status if status is not None else status_supervisor()
    try:
        falhas = falhas_do_dia(aliases)
    except Exception:
        log.exception("[-] Falha ao ler o log do supervisord")
        falhas = {}
    falhas = {a: falhas.get(a, {"falhas_hoje": 0, "ultima_falha": None}) for a in aliases}
    resultado = {}
    for alias in aliases:
        opcoes = ler_opcoes(alias)
        st = status.get(alias, {})
        script = caminho_app(alias, SCRIPT_NOME)
        resultado[alias] = {
            "estado": st.get("estado"),
            "pid": st.get("pid"),
            "uptime": st.get("uptime"),
            "detalhe": st.get("detalhe", ""),
            "tem_script": bool(script and os.path.isfile(script)),
            "gerenciado": bool(opcoes and opcoes["atual"]),
            "autostart": opcoes["autostart"] if opcoes else None,
            "autorestart": opcoes["autorestart"] if opcoes else None,
            **falhas[alias],
        }
        if banco.existe(alias):
            resultado[alias].update(banco.extras(alias))
        else:
            resultado[alias].update(_extras_visao_geral(alias))
    return resultado


def _extras_visao_geral(alias):
    """Campos da visão geral; um erro aqui não pode derrubar o sync do Node."""
    extras = {}
    for chave, obter in (("porta", lambda: ler_metadados(ler_script(alias))["porta"]),
                         ("distro", lambda: distro(alias)),
                         ("script_salvo_em", lambda: _salvo_em(alias)),
                         ("disco_mb", lambda: disco.mb(alias))):
        try:
            extras[chave] = obter()
        except Exception:
            log.exception("[-] '%s': falha ao obter %s para a visão geral", alias, chave)
            extras[chave] = None
    return extras


# ---------------------------------------------------------------------------
# Comandos vindos do painel
# ---------------------------------------------------------------------------

ACOES = {"iniciar", "parar", "reiniciar", "ler_script", "salvar_script", "configurar", "exemplo",
         "credenciais", "criar_banco", "apagar_banco"}
# Ações de um worker de banco (banco.py): não há container nem run.sh
ACOES_BANCO = {"iniciar", "parar", "reiniciar", "configurar", "credenciais", "criar_banco", "apagar_banco"}


def _saida(proc):
    """Texto de stdout + stderr de um supervisorctl (rodado com text=True)."""
    return (str(getattr(proc, "stdout", "") or "") + str(getattr(proc, "stderr", "") or "")).strip()


def _falhou(texto):
    """Interpreta a saída do supervisorctl.

    Não são falhas: "ERROR (not running)" de um restart sobre um serviço parado
    ou FATAL (o stop falha, mas o start que vem em seguida funciona) e
    "ERROR (already started)". Se algum programa foi iniciado, deu certo.
    """
    if re.search(r": started\b", texto):
        return False
    erros = [l for l in texto.splitlines()
             if "ERROR" in l and "not running" not in l and "already started" not in l]
    return bool(erros)


def _reiniciar(alias):
    """Reinicia aplicando um .conf alterado (autostart/autorestart), se houver."""
    proc = supervisorctl("reread", text=True, timeout=15)
    if re.search(rf"^{re.escape(alias)}: changed", proc.stdout or "", re.M):
        supervisorctl("update", alias, text=True, timeout=30)
        proc = supervisorctl("start", alias, text=True, timeout=30)
    else:
        proc = supervisorctl("restart", alias, text=True, timeout=30)
    return proc


def executar(alias, acao, dados=None):
    """Executa uma ação do painel. Devolve (ok, mensagem, extra: dict)."""
    dados = dados or {}
    if not alias_valido(alias):
        return False, "Alias inválido.", {}
    if acao not in ACOES:
        return False, f"Ação desconhecida: {acao}", {}
    import banco  # importado aqui: o banco.py importa este módulo
    e_banco = alias != TUNNEL and banco.existe(alias)
    if alias == TUNNEL:
        # O tunnel roda no Termux, sem container nem run.sh (ver tunnel.py)
        if acao not in ("iniciar", "parar", "reiniciar", "configurar"):
            return False, "O tunnel não tem run.sh.", {}
    elif e_banco:
        if acao not in ACOES_BANCO:
            return False, "Este worker é um banco PostgreSQL: não tem run.sh.", {}
    elif not rootfs(alias):
        return False, f"Container '{alias}' não encontrado.", {}

    if acao == "credenciais":
        if not e_banco:
            return False, "Só workers de banco têm credenciais.", {}
        cred = banco.credenciais(alias, dados.get("banco") or None)
        if not cred:
            return False, f"Banco '{dados.get('banco')}' não encontrado.", {}
        return True, "", cred

    if acao in ("criar_banco", "apagar_banco"):
        if not e_banco:
            return False, "Só workers de banco têm bancos.", {}
        funcao = banco.criar_banco if acao == "criar_banco" else banco.apagar_banco
        ok, msg = funcao(alias, dados.get("nome"))
        return ok, msg, {"bancos": (banco.info_publica(alias) or {}).get("bancos", [])}

    if e_banco and acao in ("iniciar", "reiniciar") and banco.incompativel(alias):
        return False, (f"Os dados são do PostgreSQL {banco.versao_dados(alias)}, mas o instalado é o "
                       f"{banco.versao()}: o serviço não sobe. Veja 'Atualizar a versão do PostgreSQL' "
                       "no README."), {}

    if acao == "exemplo":
        return True, "Exemplo", {"conteudo": EXEMPLO}

    if acao == "ler_script":
        conteudo = ler_script(alias)
        return True, "", {"conteudo": conteudo, "existe": conteudo is not None,
                          "avisos": avisos_script(conteudo)}

    if ler_opcoes(alias) is None:
        return False, "Este worker não tem serviço registrado no Supervisor.", {}

    if acao == "salvar_script":
        ok, msg = salvar_script(alias, dados.get("conteudo"))
        if not ok:
            return False, msg, {}
        extra = {"avisos": avisos_script(dados.get("conteudo"))}
        if dados.get("reiniciar"):
            texto = _saida(_reiniciar(alias))
            ok = not _falhou(texto)
            return ok, ("run.sh salvo e serviço reiniciado." if ok else f"run.sh salvo, mas: {texto}"), extra
        return True, "run.sh salvo. Use Reiniciar para aplicar.", extra

    if acao == "configurar":
        opcoes = ler_opcoes(alias)
        for chave in ("autostart", "autorestart"):
            if chave in dados:
                opcoes[chave] = bool(dados[chave])
        if alias == TUNNEL:
            import tunnel  # importado aqui: o tunnel.py importa este módulo
            tunnel.gravar_conf(opcoes["autostart"], opcoes["autorestart"])
        elif e_banco:
            banco.gravar_conf(alias, opcoes["autostart"], opcoes["autorestart"])
        else:
            gravar_conf(alias, isolado=opcoes["isolado"], autostart=opcoes["autostart"],
                        autorestart=opcoes["autorestart"])
        # Só relê: aplicar na hora reiniciaria o serviço. "Iniciar com o celular"
        # vale no próximo boot; "reiniciar se cair" vale na próxima reinicialização.
        supervisorctl("reread", text=True, timeout=15)
        return True, "Configuração salva (vale a partir da próxima reinicialização do serviço).", \
            {"autostart": opcoes["autostart"], "autorestart": opcoes["autorestart"]}

    if acao == "reiniciar":
        proc = _reiniciar(alias)
    elif acao == "iniciar":
        proc = supervisorctl("reread", text=True, timeout=15)
        if re.search(rf"^{re.escape(alias)}: changed", proc.stdout or "", re.M):
            supervisorctl("update", alias, text=True, timeout=30)
        proc = supervisorctl("start", alias, text=True, timeout=30)
    else:  # parar
        proc = supervisorctl("stop", alias, text=True, timeout=30)

    texto = _saida(proc)
    if _falhou(texto):
        return False, texto, {}
    verbo = {"iniciar": "iniciado", "parar": "parado", "reiniciar": "reiniciado"}[acao]
    return True, f"Serviço {verbo}.", {}


# ---------------------------------------------------------------------------
# Logs ao vivo
# ---------------------------------------------------------------------------

def ultimas_linhas(caminho, n=LOG_LINHAS_INICIAIS, bloco=8192):
    """Últimas n linhas de um arquivo (lê de trás para frente)."""
    try:
        with open(caminho, "rb") as f:
            f.seek(0, os.SEEK_END)
            fim = f.tell()
            dados = b""
            pos = fim
            while pos > 0 and dados.count(b"\n") <= n:
                ler = min(bloco, pos)
                pos -= ler
                f.seek(pos)
                dados = f.read(ler) + dados
    except OSError:
        return [], 0
    linhas = dados.decode("utf-8", errors="replace").splitlines()
    return linhas[-n:], fim


class LogsAoVivo:
    """Acompanha o log do serviço de cada worker enquanto alguém assiste.

    `enviar(alias, linhas, inicial)` é chamado com as linhas novas. Ao assinar,
    envia as últimas 200 linhas (inicial=True); depois, só o que for
    acrescentado. Detecta a rotação do arquivo (tamanho diminuiu).
    """

    def __init__(self, enviar, intervalo=LOG_INTERVALO):
        self.enviar = enviar
        self.intervalo = intervalo
        self._ativos = {}  # alias -> threading.Event (parar)
        self._lock = threading.Lock()

    def assinar(self, alias):
        if not alias_valido(alias):
            return
        linhas, posicao = ultimas_linhas(arquivo_log(alias))
        self.enviar(alias, linhas, True)
        with self._lock:
            if alias in self._ativos:
                return
            parar = threading.Event()
            self._ativos[alias] = parar
        threading.Thread(target=self._acompanhar, args=(alias, posicao, parar), daemon=True).start()

    def cancelar(self, alias):
        with self._lock:
            parar = self._ativos.pop(alias, None)
        if parar:
            parar.set()

    def ativos(self):
        with self._lock:
            return set(self._ativos)

    def _acompanhar(self, alias, posicao, parar):
        caminho = arquivo_log(alias)
        resto = b""
        while not parar.wait(self.intervalo):
            try:
                tamanho = os.path.getsize(caminho)
            except OSError:
                continue
            if tamanho < posicao:      # rotação ou arquivo recriado
                posicao, resto = 0, b""
            if tamanho == posicao:
                continue
            try:
                with open(caminho, "rb") as f:
                    f.seek(posicao)
                    novo = f.read(min(tamanho - posicao, 256 * 1024))
                    posicao = f.tell()
            except OSError:
                continue
            dados = resto + novo
            *completas, resto = dados.split(b"\n")
            if completas:
                self.enviar(alias, [l.decode("utf-8", errors="replace") for l in completas], False)
