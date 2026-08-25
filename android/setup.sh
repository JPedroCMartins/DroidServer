#!/usr/bin/env bash
#
# DroidServer — Configuração de primeiro uso no celular (Termux + proot-distro)
#
# Execute dentro do Termux, a partir do repositório clonado:
#   bash android/setup.sh
#
# O que este script faz:
#   1. Instala os pacotes base do Termux (git, python, proot-distro, supervisor)
#   2. Instala as dependências Python do agente (python-socketio, requests)
#   3. Configura o Supervisor para gerenciar os workers (containers proot-distro)
#   4. Salva a conexão com o host (IP/porta/token) em ~/.config/droidserver/env
#   5. Inicia o supervisord e mostra como rodar o agente
#
set -euo pipefail

DROID_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
CONF_DIR="$HOME/.config/droidserver"
ENV_FILE="$CONF_DIR/env"
SUP_CONF="$PREFIX/etc/supervisord.conf"
SUP_CONFD="$PREFIX/etc/supervisor/conf.d"

info() { echo -e "\e[1;34m[*]\e[0m $*"; }
ok()   { echo -e "\e[1;32m[+]\e[0m $*"; }
warn() { echo -e "\e[1;33m[!]\e[0m $*" >&2; }
fail() { echo -e "\e[1;31m[-]\e[0m $*" >&2; exit 1; }

# --- Ambiente ----------------------------------------------------------------
if [ ! -d "$PREFIX/bin" ]; then
    fail "Ambiente Termux não detectado (PREFIX=$PREFIX). Rode este script dentro do Termux."
fi
command -v pkg >/dev/null || fail "Comando 'pkg' não encontrado. Rode este script dentro do Termux."

echo
info "=== DroidServer — Setup do Node (Termux + proot-distro) ==="
echo

# --- 1. Pacotes base ---------------------------------------------------------
info "Atualizando pacotes do Termux..."
pkg update -y
pkg upgrade -y

info "Instalando pacotes: git, python, proot-distro, supervisor..."
pkg install -y git python proot-distro supervisor \
    || fail "Falha ao instalar os pacotes base."

# --- 2. Dependências Python do agente ---------------------------------------
info "Instalando dependências do agente (python-socketio, requests)..."
python -m pip install --break-system-packages --upgrade pip -q
python -m pip install --break-system-packages -q python-socketio requests \
    || fail "Falha ao instalar as dependências Python do agente."

# --- 3. Supervisor -------------------------------------------------------------
info "Configurando o Supervisor..."
mkdir -p "$SUP_CONFD" "$PREFIX/var/log" "$PREFIX/var/run"

if [ ! -f "$SUP_CONF" ]; then
    fail "supervisord.conf não encontrado em $SUP_CONF. Verifique a instalação do pacote 'supervisor'."
fi

# Garante que o supervisord leia os arquivos .conf que o agente cria em conf.d
if grep -q "etc/supervisor/conf.d" "$SUP_CONF"; then
    ok "supervisord.conf já inclui $SUP_CONFD"
else
    if grep -q '^\[include\]' "$SUP_CONF"; then
        warn "Seção [include] já existe em $SUP_CONF."
        warn "Adicione manualmente: files = $SUP_CONFD/*.conf"
    else
        printf '\n[include]\nfiles = %s/etc/supervisor/conf.d/*.conf\n' "$PREFIX" >> "$SUP_CONF"
        ok "Include adicionado ao supervisord.conf"
    fi
fi

if supervisorctl -c "$SUP_CONF" status >/dev/null 2>&1; then
    ok "Supervisor já está rodando"
else
    info "Iniciando supervisord em background..."
    nohup supervisord -c "$SUP_CONF" >/dev/null 2>&1 &
    sleep 3
    if supervisorctl -c "$SUP_CONF" status >/dev/null 2>&1; then
        ok "supervisord iniciado"
    else
        warn "Não foi possível iniciar supervisord. Rode manualmente:"
        warn "    supervisord -c $SUP_CONF"
    fi
fi

# --- 4. Conexão com o host ------------------------------------------------------
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

# --- 5. Teste opcional do proot-distro -------------------------------------------
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

# --- Final -------------------------------------------------------------------------
echo
ok "Instalação concluída!"
echo
echo "  Para iniciar o agente (registra este celular no dashboard do host):"
echo "      bash $DROID_DIR/android/run.sh"
echo
echo "  Painel do host:"
echo "      http://$HOST_IP:$HOST_PORT"
echo
echo "  Observações:"
echo "    - Cada worker criado pelo dashboard executa '/app/run_server.sh' dentro do"
echo "      container proot-distro. O agente instala um script padrão nesse caminho;"
echo "      substitua pelo seu aplicativo quando quiser."
echo "    - Para checar os serviços: supervisorctl -c $SUP_CONF status"
