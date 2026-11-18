"""Workers de banco de dados: PostgreSQL rodando no Termux, fora do proot.

É um *tipo* de Worker sem container. O PostgreSQL não roda dentro do proot:
a emulação de memória compartilhada System V do proot (--sysvipc) trava quando
o postgres é executado pela segunda vez na mesma sessão, e o `initdb` faz isso
várias vezes (testado no moto e40, Debian 13 + PostgreSQL 17). O pacote
`postgresql` do Termux já vem adaptado ao Android (libandroid-shmem) e roda
direto, sem a sobrecarga do proot.

Cada instância é um programa do Supervisor com o alias do worker:

- dados em ~/.local/share/droidserver/bancos/<alias>/dados (initdb);
- configuração e senha em ~/.local/share/droidserver/bancos/<alias>/banco.json (0600);
- usuário `droidserver` (superusuário), banco `postgres`, autenticação
  scram-sha-256 e acesso pela rede (listen_addresses='*');
- porta 5432, ou a próxima livre se já houver outra instância.

A senha é gerada pelo Host e vem na tarefa de criação; ela não sai do agente
no sync, só pela ação `credenciais` da aba Serviço (pedida pelo painel logado).

Uma instância pode ter vários bancos (criar_banco/apagar_banco), cada um com
um usuário dono de mesmo nome e senha gerada no Node, guardada no banco.json.
Sai bem mais barato que uma instância por aplicação (~70 MB cada).

Versão: o Termux empacota só uma versão do PostgreSQL. O pacote fica preso
(`apt-mark hold`) para o `pkg upgrade` do setup.sh não trocar a versão major,
o que deixaria os dados existentes sem subir. Se mesmo assim a major dos
dados (PG_VERSION) diferir da do binário, o banco é marcado como
incompatível e não é iniciado (ver README: atualizar a versão).

Iniciar, parar, reiniciar, autostart/autorestart, logs ao vivo, falhas do dia,
CPU e RAM usam o mesmo caminho dos outros Workers (servico.py).
"""

import json
import logging
import os
import re
import secrets
import shutil
import socket
import subprocess
import time

import servico

log = logging.getLogger("node.banco")

TIPO = "postgres"
USUARIO = "droidserver"
BANCO = "postgres"
PORTA_PADRAO = 5432
PORTA_MAXIMA = 5531           # procura porta livre até aqui
# Memória baixa: o celular divide a RAM com o Android e os outros workers
SHARED_BUFFERS = os.getenv("DROID_PG_SHARED_BUFFERS", "16MB")
MAX_CONNECTIONS = int(os.getenv("DROID_PG_MAX_CONNECTIONS", "20"))
INSTALAR_TIMEOUT = 600
INITDB_TIMEOUT = 300
# Senha gerada pelo Host (secrets.token_urlsafe): só caracteres seguros
SENHA_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
ARQUIVO_INFO = "banco.json"
DIR_DADOS = "dados"
MARCA_CONF = "# --- DroidServer ---"
PACOTE = "postgresql"
# Bancos dentro de uma instância: nome = dono (role) do banco
NOME_BANCO_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
NOMES_RESERVADOS = {"postgres", "template0", "template1", USUARIO, "public"}
PSQL_TIMEOUT = 60

_versao_cache = {}


def base_dir():
    return os.getenv("DROID_BANCOS_DIR") or os.path.join(
        os.path.expanduser("~"), ".local", "share", "droidserver", "bancos")


def diretorio(alias):
    return os.path.join(base_dir(), alias)


def dir_dados(alias):
    return os.path.join(diretorio(alias), DIR_DADOS)


def arquivo_info(alias):
    return os.path.join(diretorio(alias), ARQUIVO_INFO)


def existe(alias):
    return servico.alias_valido(alias) and os.path.isfile(arquivo_info(alias))


def listar():
    """Aliases das instâncias de banco criadas neste Node."""
    try:
        nomes = os.listdir(base_dir())
    except OSError:
        return []
    return sorted(n for n in nomes if existe(n))


def ler_info(alias):
    """Conteúdo do banco.json (com a senha), ou None."""
    try:
        with open(arquivo_info(alias)) as f:
            info = json.load(f)
    except (OSError, ValueError):
        return None
    return info if isinstance(info, dict) else None


def info_publica(alias):
    """O que o painel pode ver no sync: tudo menos a senha."""
    info = ler_info(alias)
    if not info:
        return None
    publica = {k: info.get(k) for k in ("tipo", "porta", "usuario", "banco", "versao")}
    publica["bancos"] = sorted(_bancos(info))
    return publica


def _bancos(info):
    bancos = (info or {}).get("bancos")
    return bancos if isinstance(bancos, dict) else {}


def _gravar_info(alias, info):
    servico._gravar_atomico(arquivo_info(alias), json.dumps(info, indent=2) + "\n", 0o600)


def senha_valida(senha):
    return isinstance(senha, str) and bool(SENHA_RE.fullmatch(senha))


# ---------------------------------------------------------------------------
# Pacote postgresql do Termux
# ---------------------------------------------------------------------------

def instalado():
    return shutil.which("initdb") is not None and shutil.which("postgres") is not None


def versao():
    """Versão do `postgres --version` (em cache pelo caminho do binário)."""
    binario = shutil.which("postgres")
    if not binario:
        return None
    if binario not in _versao_cache:
        try:
            proc = subprocess.run([binario, "--version"], capture_output=True, text=True, timeout=10)
            m = re.search(r"(\d+(?:\.\d+)*)", proc.stdout or "")
            _versao_cache[binario] = m.group(1) if m else None
        except (OSError, subprocess.SubprocessError):
            return None
    return _versao_cache[binario]


def versao_major():
    """Major do binário instalado ("18" de "18.7"), ou None."""
    v = versao()
    return v.split(".")[0] if v else None


def versao_dados(alias):
    """Major com que os dados foram criados (arquivo PG_VERSION do initdb), ou None."""
    try:
        with open(os.path.join(dir_dados(alias), "PG_VERSION")) as f:
            return f.read().strip() or None
    except OSError:
        return None


def incompativel(alias):
    """True se a major dos dados difere da do binário: o postgres não sobe."""
    dados, binario = versao_dados(alias), versao_major()
    return bool(dados and binario and dados != binario)


def segurar_pacote():
    """`apt-mark hold postgresql`: o `pkg upgrade` não troca mais a versão major.

    Sem isso, um upgrade para outra major deixa todos os bancos sem subir. Falhar
    aqui não impede nada: só fica o aviso no log.
    """
    try:
        proc = subprocess.run(["apt-mark", "hold", PACOTE], capture_output=True, text=True,
                              timeout=30, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("[Banco] Não foi possível segurar o pacote %s: %s", PACOTE, e)
        return False
    if proc.returncode != 0:
        log.warning("[Banco] apt-mark hold %s falhou: %s", PACOTE, (proc.stderr or proc.stdout or "").strip())
        return False
    return True


def instalar():
    """`pkg install -y postgresql`. Devolve (ok, mensagem)."""
    log.info("[Banco] Instalando o PostgreSQL do Termux...")
    try:
        proc = subprocess.run(["pkg", "install", "-y", PACOTE], capture_output=True, text=True,
                              timeout=INSTALAR_TIMEOUT, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return False, "Tempo esgotado ao instalar o PostgreSQL."
    except OSError as e:
        return False, f"Não foi possível rodar o pkg: {e}"
    _versao_cache.clear()
    if proc.returncode != 0 or not instalado():
        erro = ((proc.stderr or "") + (proc.stdout or "")).strip()[-300:]
        return False, f"Falha ao instalar o PostgreSQL: {erro}"
    segurar_pacote()
    return True, "PostgreSQL instalado."


# ---------------------------------------------------------------------------
# Porta
# ---------------------------------------------------------------------------

def _porta_livre(porta):
    """Sem root não dá para listar as portas abertas (/proc/net/tcp é negado):
    tenta abrir a porta; se outro processo já a usa, o bind falha."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("0.0.0.0", porta))
        return True
    except OSError:
        return False
    finally:
        s.close()


def escolher_porta():
    """5432, ou a próxima que nenhuma instância reservou e que está livre agora."""
    reservadas = {(ler_info(a) or {}).get("porta") for a in listar()}
    for porta in range(PORTA_PADRAO, PORTA_MAXIMA + 1):
        if porta not in reservadas and _porta_livre(porta):
            return porta
    return None


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------

def conteudo_conf(alias, autostart=True, autorestart=True):
    return "\n".join([
        f"[program:{alias}]",
        servico.CONF_VERSAO,
        f"; droidserver-tipo: {TIPO}",
        f'command=postgres -D "{dir_dados(alias)}"',
        f"autostart={'true' if autostart else 'false'}",
        f"autorestart={'true' if autorestart else 'false'}",
        "startsecs=5",
        "startretries=5",
        # SIGINT = parada rápida: o SIGTERM (padrão) espera os clientes desconectarem
        "stopsignal=INT",
        "stopwaitsecs=30",
        "stopasgroup=true",
        "killasgroup=true",
        "redirect_stderr=true",
        f"stdout_logfile={servico.arquivo_log(alias)}",
        f"stdout_logfile_maxbytes={servico.LOG_MAX_BYTES}",
        f"stdout_logfile_backups={servico.LOG_BACKUPS}",
        "",
    ])


def gravar_conf(alias, autostart=True, autorestart=True):
    os.makedirs(os.path.dirname(servico.arquivo_log(alias)), exist_ok=True)
    servico._gravar_atomico(servico.arquivo_conf(alias), conteudo_conf(alias, autostart, autorestart), 0o644)


# ---------------------------------------------------------------------------
# Criar e remover
# ---------------------------------------------------------------------------

def _anexar(caminho, texto):
    with open(caminho, "a") as f:
        f.write(texto)


def _configurar_cluster(alias, porta):
    """Acesso pela rede com senha e limites de memória baixos."""
    dados = dir_dados(alias)
    _anexar(os.path.join(dados, "postgresql.conf"), "\n".join([
        "", MARCA_CONF,
        "listen_addresses = '*'",
        f"port = {porta}",
        f"shared_buffers = {SHARED_BUFFERS}",
        f"max_connections = {MAX_CONNECTIONS}",
        "",
    ]))
    _anexar(os.path.join(dados, "pg_hba.conf"), "\n".join([
        "", MARCA_CONF,
        "host    all    all    0.0.0.0/0    scram-sha-256",
        "host    all    all    ::/0         scram-sha-256",
        "",
    ]))


def _initdb(alias, senha):
    """Roda o initdb com a senha num arquivo temporário (0600), apagado em seguida."""
    pwfile = os.path.join(diretorio(alias), ".senha")
    servico._gravar_atomico(pwfile, senha + "\n", 0o600)
    try:
        return subprocess.run(
            ["initdb", "-D", dir_dados(alias), "-U", USUARIO, "--pwfile", pwfile,
             "--auth-local=scram-sha-256", "--auth-host=scram-sha-256", "-E", "UTF8", "--no-locale"],
            capture_output=True, text=True, timeout=INITDB_TIMEOUT, stdin=subprocess.DEVNULL)
    finally:
        try:
            os.remove(pwfile)
        except OSError:
            pass


def criar(alias, senha):
    """Cria e inicia uma instância PostgreSQL. Devolve (ok, mensagem)."""
    log.info("[Banco] Criando '%s' (PostgreSQL)...", alias)
    if not servico.alias_valido(alias):
        return False, f"Alias inválido: '{alias}'"
    if alias == servico.TUNNEL:
        return False, f"O nome '{alias}' é reservado para o tunnel da Cloudflare"
    if not senha_valida(senha):
        return False, "Senha do banco inválida."
    if existe(alias) or servico.rootfs(alias) or os.path.exists(servico.arquivo_conf(alias)):
        return False, f"Já existe um worker chamado '{alias}'"

    if not instalado():
        ok, msg = instalar()
        if not ok:
            return False, msg
    else:
        segurar_pacote()  # instalado antes (à mão ou por uma versão antiga do agente)

    porta = escolher_porta()
    if porta is None:
        return False, f"Nenhuma porta livre entre {PORTA_PADRAO} e {PORTA_MAXIMA}."

    # Restos de uma tentativa anterior que falhou no meio
    shutil.rmtree(diretorio(alias), ignore_errors=True)
    os.makedirs(diretorio(alias), mode=0o700)
    try:
        try:
            proc = _initdb(alias, senha)
        except subprocess.TimeoutExpired:
            raise RuntimeError("tempo esgotado no initdb")
        if proc.returncode != 0:
            raise RuntimeError(((proc.stderr or "") + (proc.stdout or "")).strip()[-300:] or "initdb falhou")
        _configurar_cluster(alias, porta)
        _gravar_info(alias, {
            "tipo": TIPO, "porta": porta, "usuario": USUARIO, "banco": BANCO, "senha": senha,
            "versao": versao(), "criado_em": round(time.time()), "bancos": {},
        })
        gravar_conf(alias)
    except Exception as e:
        log.error("[-] Falha ao criar o banco '%s': %s", alias, e)
        shutil.rmtree(diretorio(alias), ignore_errors=True)
        return False, f"Falha ao criar o banco '{alias}': {e}"

    servico.supervisorctl("reread", text=True, timeout=15)
    servico.supervisorctl("update", alias, text=True, timeout=30)  # autostart: já sobe
    log.info("[+] Banco '%s' criado na porta %s.", alias, porta)
    return True, f"PostgreSQL '{alias}' criado na porta {porta}."


def remover(alias):
    """Para a instância e apaga o .conf, os dados e os logs. Devolve (ok, msg)."""
    if not servico.alias_valido(alias):
        return False, f"Alias inválido: '{alias}'"
    log.info("[Banco] Removendo '%s'...", alias)
    servico.supervisorctl("stop", alias, text=True, timeout=60)
    conf = servico.arquivo_conf(alias)
    if os.path.exists(conf):
        os.remove(conf)
    servico.supervisorctl("reread", text=True, timeout=15)
    servico.supervisorctl("update", alias, text=True, timeout=30)
    shutil.rmtree(diretorio(alias), ignore_errors=True)
    if os.path.exists(diretorio(alias)):
        return False, f"Não foi possível apagar os dados de '{alias}'"
    atual = servico.arquivo_log(alias)
    for caminho in [atual] + [f"{atual}.{n}" for n in range(1, servico.LOG_BACKUPS + 1)]:
        if os.path.exists(caminho):
            os.remove(caminho)
    log.info("[+] Banco '%s' removido.", alias)
    return True, f"Banco '{alias}' removido"


# ---------------------------------------------------------------------------
# Bancos dentro da instância
# ---------------------------------------------------------------------------

def nome_banco_valido(nome):
    return isinstance(nome, str) and bool(NOME_BANCO_RE.fullmatch(nome)) and nome not in NOMES_RESERVADOS


def rodando(alias):
    return (servico.status_supervisor().get(alias) or {}).get("estado") == "RUNNING"


def _psql(alias, script, variaveis):
    """Roda um script no psql da instância, como superusuário.

    Os valores entram por `\\set` no próprio script (stdin): não aparecem no
    argv (ps) e o psql os cita com :'var' / :"var", sem SQL montado à mão.
    Só aceita valores já validados (letras, dígitos, _ e -).
    """
    info = ler_info(alias) or {}
    porta = int(info.get("porta") or PORTA_PADRAO)
    cabecalho = "".join(f"\\set {k} '{v}'\n" for k, v in variaveis.items())
    env = {**os.environ, "PGPASSWORD": str(info.get("senha") or "")}
    return subprocess.run(
        ["psql", "-h", "127.0.0.1", "-p", str(porta), "-U", USUARIO, "-d", BANCO,
         "-v", "ON_ERROR_STOP=1", "-X", "-q", "-t", "-A", "-f", "-"],
        input=cabecalho + script, capture_output=True, text=True, timeout=PSQL_TIMEOUT, env=env)


def _erro_psql(proc):
    return ((proc.stderr or "") + (proc.stdout or "")).strip()[-300:] or "psql falhou"


def _pre_banco(alias, nome):
    """Validações comuns de criar_banco/apagar_banco. Devolve a mensagem de erro ou None."""
    if not existe(alias):
        return f"Worker de banco '{alias}' não encontrado."
    if not nome_banco_valido(nome):
        return ("Nome de banco inválido: use letras minúsculas, dígitos e _ "
                "(começando por letra ou _), até 63 caracteres, e não um nome reservado.")
    if incompativel(alias):
        return "Os dados desta instância são de outra versão do PostgreSQL; veja o aviso na Visão geral."
    if not rodando(alias):
        return "Inicie o banco antes de criar ou apagar bancos."
    return None


def criar_banco(alias, nome):
    """Cria um banco e um usuário dono, de mesmo nome, com senha gerada aqui."""
    erro = _pre_banco(alias, nome)
    if erro:
        return False, erro
    info = ler_info(alias)
    if nome in _bancos(info):
        return False, f"O banco '{nome}' já existe."
    try:
        proc = _psql(alias, "SELECT 1 FROM pg_roles WHERE rolname = :'nome' "
                            "UNION ALL SELECT 1 FROM pg_database WHERE datname = :'nome';\n", {"nome": nome})
        if proc.returncode != 0:
            return False, f"Falha ao consultar o banco: {_erro_psql(proc)}"
        if (proc.stdout or "").strip():
            return False, (f"Já existe um banco ou usuário '{nome}' nesta instância "
                           "(criado pelo psql?). Escolha outro nome.")
        senha = secrets.token_urlsafe(18)
        proc = _psql(alias, "\n".join([
            "CREATE ROLE :\"nome\" LOGIN PASSWORD :'senha';",
            "CREATE DATABASE :\"nome\" OWNER :\"nome\";",
            "REVOKE CONNECT, TEMPORARY ON DATABASE :\"nome\" FROM PUBLIC;",
            "",
        ]), {"nome": nome, "senha": senha})
        if proc.returncode != 0:
            erro = _erro_psql(proc)
            # Desfaz o que chegou a ser criado (a consulta acima garantiu que nada era de antes)
            _psql(alias, "DROP DATABASE IF EXISTS :\"nome\" WITH (FORCE);\n"
                         "DROP ROLE IF EXISTS :\"nome\";\n", {"nome": nome})
            return False, f"Falha ao criar o banco '{nome}': {erro}"
    except subprocess.TimeoutExpired:
        return False, "Tempo esgotado falando com o PostgreSQL."
    except OSError as e:
        return False, f"Não foi possível rodar o psql: {e}"

    info = ler_info(alias) or info
    info["bancos"] = {**_bancos(info), nome: {"senha": senha, "criado_em": round(time.time())}}
    _gravar_info(alias, info)
    log.info("[+] Banco '%s' criado na instância '%s'.", nome, alias)
    return True, f"Banco '{nome}' criado (usuário '{nome}'). Use Mostrar senha para ver a senha."


def apagar_banco(alias, nome):
    """Apaga o banco e o usuário dono (desconecta quem estiver usando)."""
    erro = _pre_banco(alias, nome)
    if erro:
        return False, erro
    if nome not in _bancos(ler_info(alias)):
        return False, f"O banco '{nome}' não foi criado pelo painel; apague-o pelo psql."
    try:
        proc = _psql(alias, "DROP DATABASE IF EXISTS :\"nome\" WITH (FORCE);\n"
                            "DROP ROLE IF EXISTS :\"nome\";\n", {"nome": nome})
    except subprocess.TimeoutExpired:
        return False, "Tempo esgotado falando com o PostgreSQL."
    except OSError as e:
        return False, f"Não foi possível rodar o psql: {e}"
    if proc.returncode != 0:
        return False, f"Falha ao apagar o banco '{nome}': {_erro_psql(proc)}"
    info = ler_info(alias) or {}
    info["bancos"] = {k: v for k, v in _bancos(info).items() if k != nome}
    _gravar_info(alias, info)
    log.info("[+] Banco '%s' apagado da instância '%s'.", nome, alias)
    return True, f"Banco '{nome}' apagado."


# ---------------------------------------------------------------------------
# Painel
# ---------------------------------------------------------------------------

disco = servico.DiscoCache()


def extras(alias):
    """Campos da visão geral de um worker de banco (substituem os de container)."""
    info = info_publica(alias) or {}
    v_dados, v_bin = versao_dados(alias), versao_major()
    ruim = bool(v_dados and v_bin and v_dados != v_bin)
    if ruim:
        distro = f"PostgreSQL {versao()} (dados da {v_dados} — incompatível)"
    elif versao():
        distro = f"PostgreSQL {versao()} (Termux)"
    else:
        distro = "PostgreSQL (Termux)"
    return {
        "tipo": TIPO,
        "banco": info,
        "porta": info.get("porta"),
        "versao_dados": v_dados,
        "incompativel": ruim,
        "distro": distro,
        "disco_mb": disco.mb(alias, diretorio(alias)),
        "script_salvo_em": None,
        "tem_script": True,  # não há run.sh: o serviço é o próprio postgres
    }


def credenciais(alias, nome=None):
    """Usuário/senha/banco/porta do admin (nome vazio) ou de um banco criado pelo painel."""
    info = ler_info(alias)
    if not info:
        return None
    if nome and nome != info.get("banco"):
        item = _bancos(info).get(nome)
        if not isinstance(item, dict):
            return None
        return {"usuario": nome, "senha": item.get("senha"), "banco": nome, "porta": info.get("porta")}
    return {k: info.get(k) for k in ("usuario", "senha", "banco", "porta")}


def comando_terminal(alias):
    """Terminal do worker de banco: psql conectado à instância, reabrindo ao sair.

    Devolve (argv, env extra). A senha vai em PGPASSWORD, não na linha de comando.
    """
    info = ler_info(alias) or {}
    porta = int(info.get("porta") or PORTA_PADRAO)
    psql = f"psql -h 127.0.0.1 -p {porta} -U {USUARIO} {BANCO}"
    laco = (f"while true; do {psql}; echo; "
            "echo '[DroidServer] psql encerrado. Enter reconecta (o serviço precisa estar rodando).'; "
            "read _ || exit 0; done")
    return ["sh", "-c", laco], {"PGPASSWORD": str(info.get("senha") or "")}
