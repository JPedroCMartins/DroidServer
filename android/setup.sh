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
#   6. Salva a conexão com o host em ~/.config/droidserver/env
#   7. (Opcional) instala um container Alpine de teste
#
# Todo o output vai para o terminal E para o arquivo de log, para análise futura.
#
set -u   # apenas variáveis não definidas abortam; falhas de comando são tratadas etapa a etapa

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
DROID_DIR="$(cd "$(dirname "$0")/.." && pwd)"

CONF_DIR="$HOME/.config/droidserver"
LOG_DIR="$CONF_DIR/logs"
ENV_FILE="$CONF_DIR/env"
SUP_CONF="$PREFIX/etc/supervisord.conf"
SUP_CONFD="$PREFIX/etc/supervisor/conf.d"

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
# Redireciona stdout+stderr para o terminal e para o log ao mesmo tempo
exec > >(tee -a "$LOG_FILE") 2>&1
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
pkg update -y >/dev/null 2>&1 && ok "pkg update concluído" || warn "pkg update falhou (seguindo mesmo assim)"
pkg upgrade -y >/dev/null 2>&1 && ok "pkg upgrade concluído" || warn "pkg upgrade falhou (seguindo mesmo assim)"

install_pkg() {
    if pkg install -y "$1" >/dev/null 2>&1; then
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

# --- 2. Supervisor ---------------------------------------------------------------
ensure_supervisor() {
    if installed supervisord && installed supervisorctl; then
        ok "Supervisor já instalado ($(command -v supervisord))"
        return 0
    fi

    info "Instalando Supervisor (tentativa 1: pip — mais confiável no Termux)..."
    if "$PY" -m pip install --break-system-packages -q supervisor; then
        if installed supervisord; then
            ok "Supervisor instalado via pip"
            return 0
        fi
    fi

    info "Instalando Supervisor (tentativa 2: pacote do Termux)..."
    if pkg install -y supervisor >/dev/null 2>&1; then
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

ensure_supervisord_conf() {
    if [ ! -f "$SUP_CONF" ]; then
        info "Gerando $SUP_CONF (não existia)..."
        cat > "$SUP_CONF" <<EOF
[unix_http_server]
file=$PREFIX/var/run/supervisor.sock
chmod=0700

[supervisord]
logfile=$PREFIX/var/log/supervisor/supervisord.log
pidfile=$PREFIX/var/run/supervisord.pid
logfile_maxbytes=5MB
logfile_backups=5

[supervisorctl]
serverurl=unix://$PREFIX/var/run/supervisor.sock

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[include]
files = $SUP_CONFD/*.conf
EOF
        ok "$SUP_CONF criado"
        return
    fi

    if grep -q "etc/supervisor/conf.d" "$SUP_CONF"; then
        ok "supervisord.conf já inclui $SUP_CONFD"
        return
    fi

    info "Adicionando include de $SUP_CONFD ao supervisord.conf..."
    if "$PY" - "$SUP_CONF" "$SUP_CONFD" <<'PY'
import sys, configparser
path, confd = sys.argv[1], sys.argv[2]
cp = configparser.ConfigParser()
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
        warn "Não foi possível editar o [include] automaticamente."
        warn "Adicione manualmente em $SUP_CONF: files = $SUP_CONFD/*.conf"
    fi
}
ensure_supervisord_conf

# --- 4. iniciar o supervisord -------------------------------------------------------
if supervisorctl -c "$SUP_CONF" status >/dev/null 2>&1; then
    ok "Supervisor já está rodando"
else
    info "Iniciando supervisord em background..."
    if supervisord -c "$SUP_CONF" >/dev/null 2>&1; then
        sleep 3
        if supervisorctl -c "$SUP_CONF" status >/dev/null 2>&1; then
            ok "supervisord iniciado"
        else
            warn "supervisord executou mas não respondeu. Veja: $PREFIX/var/log/supervisor/supervisord.log"
        fi
    else
        warn "Falha ao iniciar supervisord. Veja: $PREFIX/var/log/supervisor/supervisord.log"
    fi
fi

# --- 5. dependências do agente --------------------------------------------------------
info "Instalando dependências do agente (python-socketio, requests)..."
if "$PY" -m pip install --break-system-packages -q python-socketio requests; then
    ok "Dependências do agente instaladas"
else
    warn "Falha ao instalar as dependências do agente. Rode manualmente:"
    warn "    $PY -m pip install --break-system-packages python-socketio requests"
fi

# --- 6. conexão com o host ------------------------------------------------------------
mkdir -p "$CONF_DIR"

read -rp "IP do servidor host [192.168.1.10]: " HOST_IP
HOST_IP="${HOST_IP:-192.168.1.10}"
read -rp "Porta do host [5050]: " HOST_PORT
HOST_PORT="${HOST_PORT:-5050}"
read -rp "Token (opcional; deixe vazio se o host não exigir): " HOST_TOKEN

cat > "$ENV_FILE" <<EOF
export DROID_HOST_IP="$HOST_IP"
export DROID_HOST_PORT="$HOST_PORT"
export DROID_TOKEN="$HOST_TOKEN"
EOF
chmod 600 "$ENV_FILE"
ok "Configuração salva em $ENV_FILE"

# --- 7. teste opcional do proot-distro ------------------------------------------------
read -rp "Instalar um container Alpine de teste agora? (s/N) " INSTALAR_TESTE
case "${INSTALAR_TESTE:-n}" in
    s|S|y|Y)
        info "Instalando container Alpine de teste (alias: alpine_teste)..."
        if proot-distro install alpine --override-alias alpine_teste; then
            ok "Container alpine_teste instalado."
        else
            warn "Não foi possível instalar o container de teste."
        fi
        ;;
esac

# --- final -----------------------------------------------------------------------------
echo
ok "Instalação concluída!"
echo
echo "  Para iniciar o agente (registra este celular no dashboard do host):"
echo "      bash $DROID_DIR/android/run.sh"
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
