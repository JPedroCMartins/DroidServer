#!/usr/bin/env bash
#
# DroidServer — Configuração de primeiro uso no celular (Termux + proot-distro)
#
# Execute dentro do Termux, a partir do repositório clonado:
#   bash android/setup.sh
#
# O que este script faz:
#   1. Detecta o ambiente Termux e inicia o log (setup-<data>.log)
#   2. Instala os pacotes base (git, python, proot-distro) — cada um de forma isolada
#   3. Instala o Supervisor (pip como fonte primária; pkg do Termux como fallback)
#   4. Gera/ajusta o supervisord.conf e inicia o supervisord
#   5. Instala as dependências Python do agente (python-socketio, requests)
#   6. Salva a conexão com o host em ~/.config/droidserver/env e testa o contato
#   7. (Opcional) instala um container Alpine de teste
#   8. (Opcional) inicia o agente automaticamente ao ligar o celular (Termux:Boot)
#
# Pode ser executado de novo sem problema: o script reaproveita o que já existe
# e usa a configuração anterior como valor padrão.
#
# Todo o output vai para o terminal E para o arquivo de log, para análise futura.
#
set -u   # apenas variáveis não definidas abortam; falhas de comando são tratadas etapa a etapa

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DROID_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

CONF_DIR="$HOME/.config/droidserver"
LOG_DIR="$CONF_DIR/logs"
ENV_FILE="$CONF_DIR/env"
SUP_CONF="$PREFIX/etc/supervisord.conf"
SUP_CONFD="$PREFIX/etc/supervisor/conf.d"

# Evita prompts interativos do dpkg (conflitos de arquivos de configuração) no upgrade
export DEBIAN_FRONTEND=noninteractive

# --- helpers ------------------------------------------------------------------
c_ok=$'\e[1;32m'; c_info=$'\e[1;34m'; c_warn=$'\e[1;33m'; c_err=$'\e[1;31m'; c_res=$'\e[0m'
info() { printf '%s[*]%s %s\n' "$c_info" "$c_res" "$*"; }
ok()   { printf '%s[+]%s %s\n' "$c_ok" "$c_res" "$*"; }
warn() { printf '%s[!]%s %s\n' "$c_warn" "$c_res" "$*" >&2; }
fail() { printf '%s[-]%s %s\n' "$c_err" "$c_res" "$*" >&2; }

installed() { command -v "$1" >/dev/null 2>&1; }

# --- ambiente -----------------------------------------------------------------
if [ ! -d "$PREFIX/bin" ]; then
    fail "Ambiente Termux não detectado (PREFIX=$PREFIX)." ; fail "Rode este script dentro do Termux." ; exit 1
fi
if ! installed pkg; then
    fail "Comando 'pkg' não encontrado. Rode este script dentro do Termux." ; exit 1
fi

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/setup-$(date +%Y%m%d-%H%M%S).log"
# Redireciona stdout+stderr para o terminal e para o log (sem os códigos de cor no arquivo)
exec > >(tee >(sed -u 's/\x1b\[[0-9;]*m//g' >> "$LOG_FILE")) 2>&1
trap 'warn "Log completo desta execução: $LOG_FILE"' EXIT

fail_exit() {
    fail "$*"
    exit 1
}

echo
info "=== DroidServer — Setup do Node (Termux + proot-distro) ==="
info "Log desta execução: $LOG_FILE"
echo

# --- 1. pacotes base ------------------------------------------------------------
info "Atualizando listas e pacotes do Termux..."
if pkg update -y; then ok "pkg update concluído"; else warn "pkg update falhou (seguindo mesmo assim)"; fi
if pkg upgrade -y -o Dpkg::Options::=--force-confold; then
    ok "pkg upgrade concluído"
else
    warn "pkg upgrade falhou (seguindo mesmo assim)"
fi

install_pkg() {
    if pkg install -y "$1"; then
        ok "pacote '$1' instalado"
        return 0
    fi
    warn "pkg não conseguiu instalar '$1'"
    return 1
}

# python é obrigatório
if ! installed python && ! installed python3; then
    install_pkg python || fail_exit "python é obrigatório e não pôde ser instalado"
fi
if installed python; then PY=python; else PY=python3; fi
ok "Python detectado: $PY ($("$PY" --version 2>&1))"

# pip
if ! "$PY" -m pip --version >/dev/null 2>&1; then
    info "pip não encontrado; tentando instalar o pacote python-pip..."
    install_pkg python-pip || fail_exit "pip é necessário para instalar as dependências do agente"
fi

install_pkg git || warn "git não instalado (necessário apenas para atualizar o repositório)"
install_pkg proot-distro || fail_exit "proot-distro é obrigatório e não pôde ser instalado"

# O painel cria workers com 'proot-distro login --isolated'. Versões antigas não têm essa opção.
if proot-distro login --help 2>&1 | grep -q -- '--isolated'; then
    ok "proot-distro suporta --isolated"
else
    warn "Seu proot-distro não parece suportar '--isolated'. Atualize (pkg upgrade proot-distro)"
    warn "ou desmarque 'Isolar do host' ao criar workers no painel."
fi

# --- 2. Supervisor ---------------------------------------------------------------
ensure_supervisor() {
    if installed supervisord && installed supervisorctl; then
        ok "Supervisor já instalado ($(command -v supervisord))"
        return 0
    fi

    info "Instalando Supervisor (tentativa 1: pip — mais confiável no Termux)..."
    if "$PY" -m pip install --break-system-packages supervisor; then
        if installed supervisord; then
            ok "Supervisor instalado via pip"
            return 0
        fi
    fi

    info "Instalando Supervisor (tentativa 2: pacote do Termux)..."
    if pkg install -y supervisor; then
        if installed supervisord; then
            ok "Supervisor instalado via pkg"
            return 0
        fi
    fi

    warn "Não foi possível instalar o Supervisor automaticamente."
    return 1
}
ensure_supervisor || fail_exit "O Supervisor é necessário para gerenciar os workers. Instale manualmente (pip install supervisor) e rode o script de novo."

# --- 3. supervisord.conf ----------------------------------------------------------
mkdir -p "$SUP_CONFD" "$PREFIX/var/run" "$PREFIX/var/log/supervisor"

# No Termux recente o Python não tem os.link(), e o supervisord usa os.link() para criar o
# socket unix ("AttributeError: module 'os' has no attribute 'link'"). Nesse caso o
# supervisor usa o servidor HTTP em 127.0.0.1 (protegido por usuário e senha) no lugar do socket.
if "$PY" -c 'import os, sys; sys.exit(0 if hasattr(os, "link") else 1)'; then
    USE_INET=0
else
    USE_INET=1
    info "Python sem os.link(): o supervisor usará HTTP em 127.0.0.1 em vez de socket unix."
fi
SUP_PORT=9001

gerar_supervisord_conf() {
    {
        echo "# Gerado pelo setup.sh do DroidServer"
        if [ "$USE_INET" = 1 ]; then
            local senha
            senha="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(16))')"
            cat <<EOF
[inet_http_server]
port=127.0.0.1:$SUP_PORT
username=droidserver
password=$senha

[supervisorctl]
serverurl=http://127.0.0.1:$SUP_PORT
username=droidserver
password=$senha

EOF
        else
            cat <<EOF
[unix_http_server]
file=$PREFIX/var/run/supervisor.sock
chmod=0700

[supervisorctl]
serverurl=unix://$PREFIX/var/run/supervisor.sock

EOF
        fi
        cat <<EOF
[supervisord]
logfile=$PREFIX/var/log/supervisor/supervisord.log
pidfile=$PREFIX/var/run/supervisord.pid
childlogdir=$PREFIX/var/log/supervisor
logfile_maxbytes=5MB
logfile_backups=5

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[include]
files = $SUP_CONFD/*.conf
EOF
    } > "$SUP_CONF"
    # A senha do supervisor fica neste arquivo: só o seu usuário pode lê-lo
    chmod 600 "$SUP_CONF"
}

# Converte um supervisord.conf já existente (com socket unix) para o servidor HTTP local
migrar_para_inet() {
    info "Ajustando $SUP_CONF para HTTP em 127.0.0.1:$SUP_PORT (backup em $SUP_CONF.bak)..."
    cp "$SUP_CONF" "$SUP_CONF.bak"
    if "$PY" - "$SUP_CONF" "$SUP_PORT" <<'PY'
import sys, secrets, configparser
path, port = sys.argv[1], sys.argv[2]
cp = configparser.RawConfigParser(interpolation=None, strict=False)
cp.optionxform = str
cp.read(path)
senha = secrets.token_urlsafe(16)
cp.remove_section('unix_http_server')
if not cp.has_section('inet_http_server'):
    cp.add_section('inet_http_server')
cp.set('inet_http_server', 'port', '127.0.0.1:' + port)
cp.set('inet_http_server', 'username', 'droidserver')
cp.set('inet_http_server', 'password', senha)
if not cp.has_section('supervisorctl'):
    cp.add_section('supervisorctl')
cp.set('supervisorctl', 'serverurl', 'http://127.0.0.1:' + port)
cp.set('supervisorctl', 'username', 'droidserver')
cp.set('supervisorctl', 'password', senha)
with open(path, 'w') as f:
    cp.write(f)
PY
    then
        chmod 600 "$SUP_CONF"
        ok "supervisord.conf ajustado para HTTP local"
    else
        cp "$SUP_CONF.bak" "$SUP_CONF"
        warn "Não foi possível ajustar o supervisord.conf (arquivo original restaurado)."
    fi
}

ensure_supervisord_conf() {
    if [ ! -f "$SUP_CONF" ]; then
        info "Gerando $SUP_CONF (não existia)..."
        gerar_supervisord_conf
        ok "$SUP_CONF criado"
        return
    fi

    # Conf criado por uma versão anterior (socket unix) num Python sem os.link()
    if [ "$USE_INET" = 1 ] && ! grep -q '^\[inet_http_server\]' "$SUP_CONF"; then
        migrar_para_inet
    fi

    # Ignora linhas comentadas ao procurar o include
    if grep -Eq '^[[:space:]]*[^;#[:space:]].*supervisor/conf\.d' "$SUP_CONF"; then
        ok "supervisord.conf já inclui $SUP_CONFD"
        return
    fi

    info "Adicionando include de $SUP_CONFD ao supervisord.conf (backup em $SUP_CONF.bak)..."
    cp "$SUP_CONF" "$SUP_CONF.bak"
    if "$PY" - "$SUP_CONF" "$SUP_CONFD" <<'PY'
import sys, configparser
path, confd = sys.argv[1], sys.argv[2]
# interpolation=None: o supervisord.conf usa %(here)s etc.
# optionxform=str: preserva maiúsculas/minúsculas das chaves.
cp = configparser.RawConfigParser(interpolation=None, strict=False)
cp.optionxform = str
cp.read(path)
if cp.has_section('include'):
    files = cp.get('include', 'files', fallback='').rstrip('\n')
    cp.set('include', 'files', (files + '\n' if files else '') + confd + '/*.conf')
else:
    cp.add_section('include')
    cp.set('include', 'files', confd + '/*.conf')
with open(path, 'w') as f:
    cp.write(f)
PY
    then
        ok "include adicionado ao supervisord.conf"
    else
        cp "$SUP_CONF.bak" "$SUP_CONF"
        warn "Não foi possível editar o [include] automaticamente (arquivo original restaurado)."
        warn "Adicione manualmente em $SUP_CONF: files = $SUP_CONFD/*.conf"
    fi
}
ensure_supervisord_conf

# --- 4. iniciar o supervisord -------------------------------------------------------
# 'supervisorctl pid' só responde 0 se o supervisord está de pé. Já o 'status' devolve
# código != 0 quando QUALQUER worker está parado, o que enganaria este teste.
sup_vivo() { supervisorctl -c "$SUP_CONF" pid >/dev/null 2>&1; }

if sup_vivo; then
    ok "Supervisor já está rodando"
else
    info "Iniciando supervisord em background..."
    supervisord -c "$SUP_CONF"
    printf '%s[*]%s Aguardando o supervisor responder' "$c_info" "$c_res"
    for _ in $(seq 1 10); do
        if sup_vivo; then
            printf '\n'
            ok "supervisord iniciado"
            break
        fi
        printf '.'
        sleep 1
    done
    if ! sup_vivo; then
        printf '\n'
        warn "supervisord não respondeu. Veja: $PREFIX/var/log/supervisor/supervisord.log"
    fi
fi

# --- 5. dependências do agente --------------------------------------------------------
# O extra [client] traz o websocket-client (sem ele o python-socketio cai para long-polling).
info "Instalando dependências do agente (python-socketio, websocket-client, requests)..."
if "$PY" -m pip install --break-system-packages "python-socketio[client]" requests; then
    ok "Dependências do agente instaladas"
else
    warn "Falha ao instalar as dependências do agente. Rode manualmente:"
    warn "    $PY -m pip install --break-system-packages 'python-socketio[client]' requests"
fi

# Confere se o agente consegue importar tudo que precisa (inclui o sysinfo.py local)
if erro="$(cd "$SCRIPT_DIR" && "$PY" -c 'import socketio, requests, sysinfo' 2>&1)"; then
    ok "Imports do agente OK"
else
    warn "O agente não conseguiu importar suas dependências:"
    printf '%s\n' "$erro" | tail -n 3 | sed 's/^/    /' >&2
    warn "Se o erro citar psutil, instale com: pkg install python-psutil"
fi

# --- 6. conexão com o host ------------------------------------------------------------
mkdir -p "$CONF_DIR"

# Valores atuais (se já configurado) viram o padrão
ATUAL_IP=""; ATUAL_PORT=""; ATUAL_TOKEN=""
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    ATUAL_IP="${DROID_HOST_IP:-}"; ATUAL_PORT="${DROID_HOST_PORT:-}"; ATUAL_TOKEN="${DROID_TOKEN:-}"
fi

read -rp "IP do servidor host [${ATUAL_IP:-192.168.1.10}]: " HOST_IP
HOST_IP="${HOST_IP:-${ATUAL_IP:-192.168.1.10}}"
read -rp "Porta do host [${ATUAL_PORT:-5050}]: " HOST_PORT
HOST_PORT="${HOST_PORT:-${ATUAL_PORT:-5050}}"
if [ -n "$ATUAL_TOKEN" ]; then
    read -rp "Token (Enter mantém o atual; '-' remove): " HOST_TOKEN
    case "$HOST_TOKEN" in
        "") HOST_TOKEN="$ATUAL_TOKEN" ;;
        "-") HOST_TOKEN="" ;;
    esac
else
    read -rp "Token (opcional; deixe vazio se o host não exigir): " HOST_TOKEN
fi

# Validação básica antes de gravar
if ! [[ "$HOST_IP" =~ ^[A-Za-z0-9._-]+$ ]]; then
    fail_exit "IP/host inválido: '$HOST_IP'"
fi
if ! [[ "$HOST_PORT" =~ ^[0-9]+$ ]] || [ "$HOST_PORT" -lt 1 ] || [ "$HOST_PORT" -gt 65535 ]; then
    fail_exit "Porta inválida: '$HOST_PORT'"
fi

# printf %q escapa aspas, $ e espaços — o token pode ter qualquer caractere
{
    printf 'export DROID_HOST_IP=%q\n' "$HOST_IP"
    printf 'export DROID_HOST_PORT=%q\n' "$HOST_PORT"
    printf 'export DROID_TOKEN=%q\n' "$HOST_TOKEN"
} > "$ENV_FILE"
chmod 600 "$ENV_FILE"
ok "Configuração salva em $ENV_FILE"

# Testa o contato com o host (não aborta: o host pode ainda não estar no ar)
info "Testando conexão com http://$HOST_IP:$HOST_PORT ..."
if "$PY" - "$HOST_IP" "$HOST_PORT" <<'PY' 2>/dev/null
import sys, requests
r = requests.get(f"http://{sys.argv[1]}:{sys.argv[2]}/api/nodes", timeout=5)
sys.exit(0 if r.status_code == 200 else 1)
PY
then
    ok "Host respondeu."
else
    warn "Não consegui falar com o host. Verifique se ele está rodando, se o IP/porta estão"
    warn "certos e se o celular está na mesma rede. A configuração foi salva mesmo assim."
fi

# --- 7. teste opcional do proot-distro ------------------------------------------------
read -rp "Instalar um container Alpine de teste agora? (s/N) " INSTALAR_TESTE
case "${INSTALAR_TESTE:-n}" in
    s|S|y|Y)
        info "Instalando container Alpine de teste (alias: alpine_teste)..."
        if proot-distro install alpine --override-alias alpine_teste; then
            ok "Container alpine_teste instalado."
            info "Ele aparece no painel como 'sem serviço' (só workers criados pelo painel ganham serviço)."
        else
            warn "Não foi possível instalar o container de teste."
        fi
        ;;
esac

# --- 8. início automático (Termux:Boot) -----------------------------------------------
BOOT_DIR="$HOME/.termux/boot"
read -rp "Iniciar o agente automaticamente ao ligar o celular? Requer o app Termux:Boot (s/N) " AUTO_BOOT
case "${AUTO_BOOT:-n}" in
    s|S|y|Y)
        mkdir -p "$BOOT_DIR"
        cat > "$BOOT_DIR/droidserver.sh" <<EOF
#!$PREFIX/bin/bash
# Gerado pelo setup.sh do DroidServer
termux-wake-lock
bash "$SCRIPT_DIR/run.sh" -d
EOF
        chmod +x "$BOOT_DIR/droidserver.sh"
        ok "Script de boot criado: $BOOT_DIR/droidserver.sh"
        info "Instale o app Termux:Boot (F-Droid) e abra-o uma vez para ativar."
        ;;
esac

# --- final -----------------------------------------------------------------------------
echo
ok "Instalação concluída!"
echo
echo "  Para iniciar o agente (registra este celular no dashboard do host):"
echo "      bash $SCRIPT_DIR/run.sh        # em primeiro plano"
echo "      bash $SCRIPT_DIR/run.sh -d     # em segundo plano"
echo "      bash $SCRIPT_DIR/run.sh stop   # encerrar"
echo
echo "  Painel do host:"
echo "      http://$HOST_IP:$HOST_PORT"
echo
echo "  Logs (para análise futura):"
echo "      - Setup deste run:      $LOG_FILE"
echo "      - Agente (node):        $HOME/.config/droidserver/logs/node.log"
echo "      - Host Flask:           <repositorio>/desktop/logs/droidserver.log"
echo
echo "  Observações:"
echo "    - Cada worker criado pelo dashboard executa '/app/run_server.sh' dentro do"
echo "      container proot-distro. O agente instala um script padrão nesse caminho;"
echo "      substitua pelo seu aplicativo quando quiser."
echo "    - Para checar os serviços: supervisorctl -c $SUP_CONF status"
echo "    - O Android pode encerrar o Termux para poupar bateria. Desative a otimização"
echo "      de bateria para o Termux (Configurações > Apps > Termux > Bateria)."
