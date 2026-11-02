#!/usr/bin/env bash
#
# DroidServer — inicia o agente do node (android/node.py)
#
# Carrega as configurações salvas pelo setup.sh (IP/porta/token), garante que o
# Supervisor esteja de pé e mantém o agente em execução (reinicia se cair).
#
# Uso:
#   bash run.sh          # roda em primeiro plano (Ctrl+C encerra)
#   bash run.sh -d       # roda em segundo plano (sobrevive ao fechar a sessão do Termux)
#   bash run.sh stop     # encerra o agente em segundo plano
#   bash run.sh status   # mostra se o agente está rodando
#
set -uo pipefail

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
DIR="$(cd "$(dirname "$0")" && pwd)"
CONF_DIR="$HOME/.config/droidserver"
ENV_FILE="$CONF_DIR/env"
LOG_DIR="$CONF_DIR/logs"
PID_FILE="$CONF_DIR/node.pid"
SUP_CONF="$PREFIX/etc/supervisord.conf"

mkdir -p "$LOG_DIR"

uso() {
    sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
}

pid_rodando() {
    [ -f "$PID_FILE" ] || return 1
    local pid
    pid="$(cat "$PID_FILE" 2>/dev/null)"
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

parar() {
    if ! pid_rodando; then
        echo "[*] O agente não está rodando."
        rm -f "$PID_FILE"
        return 0
    fi
    local pid
    pid="$(cat "$PID_FILE")"
    echo "[*] Encerrando o agente (PID $pid)..."
    kill "$pid" 2>/dev/null
    for _ in $(seq 1 10); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
    done
    if kill -0 "$pid" 2>/dev/null; then
        echo "[!] Não encerrou a tempo; forçando."
        kill -9 "$pid" 2>/dev/null
    fi
    rm -f "$PID_FILE"
    echo "[+] Agente encerrado."
}

# --- Argumentos ---------------------------------------------------------------
MODO="fg"
case "${1:-}" in
    "")            MODO="fg" ;;
    -d|--daemon)   MODO="daemon" ;;
    _loop)         MODO="loop" ;;   # uso interno (processo em segundo plano)
    stop)          parar; exit 0 ;;
    status)
        if pid_rodando; then echo "[+] Agente rodando (PID $(cat "$PID_FILE"))."; exit 0; fi
        echo "[-] Agente parado."; exit 1 ;;
    -h|--help)     uso; exit 0 ;;
    *)             uso; exit 1 ;;
esac

# --- Configuração -------------------------------------------------------------
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    . "$ENV_FILE"
fi

if [ -z "${DROID_HOST_IP:-}" ]; then
    echo "[!] Configuração não encontrada. Rode primeiro: bash $DIR/setup.sh"
    exit 1
fi
DROID_HOST_PORT="${DROID_HOST_PORT:-5050}"
export DROID_HOST_IP DROID_HOST_PORT
export DROID_TOKEN="${DROID_TOKEN:-}"

if command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python >/dev/null 2>&1; then PY=python
else echo "[!] Python não encontrado. Rode: bash $DIR/setup.sh"; exit 1; fi

cd "$DIR" || exit 1

# --- Dependências do agente -----------------------------------------------------
if ! erro="$("$PY" -c 'import socketio, requests, sysinfo' 2>&1)"; then
    echo "[!] Dependências do agente ausentes ou com erro:"
    echo "$erro" | tail -n 3 | sed 's/^/    /'
    echo "[!] Rode novamente: bash $DIR/setup.sh"
    exit 1
fi

# --- Supervisor -------------------------------------------------------------------
# Sem o supervisord de pé, os workers não sobem (ex.: depois de reiniciar o celular).
sup_vivo() { supervisorctl -c "$SUP_CONF" pid >/dev/null 2>&1; }

garantir_supervisor() {
    sup_vivo && return 0
    if ! command -v supervisord >/dev/null 2>&1; then
        echo "[!] supervisord não encontrado; os workers não serão gerenciados."
        return 1
    fi
    echo "[*] Iniciando supervisord..."
    local saida
    saida="$(supervisord -c "$SUP_CONF" 2>&1)"
    for _ in $(seq 1 10); do
        sup_vivo && { echo "[+] supervisord iniciado."; return 0; }
        sleep 1
    done
    echo "[!] supervisord não respondeu. Veja: $PREFIX/var/log/supervisor/supervisord.log"
    [ -n "$saida" ] && printf '%s\n' "$saida" | tail -n 3 | sed 's/^/    /'
    if printf '%s' "$saida" | grep -q "has no attribute 'link'"; then
        echo "[!] O Python deste Termux não tem os.link(). Rode de novo: bash $DIR/setup.sh"
    fi
    return 1
}

# --- Loop do agente (reinicia se cair, com espera progressiva) -----------------------
loop_agente() {
    echo $$ > "$PID_FILE"
    CHILD=""
    trap '[ -n "$CHILD" ] && kill "$CHILD" 2>/dev/null; rm -f "$PID_FILE"; exit 0' INT TERM
    trap 'rm -f "$PID_FILE"' EXIT

    command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock

    local espera=2
    while true; do
        garantir_supervisor
        local inicio fim
        inicio=$(date +%s)
        "$PY" node.py &
        CHILD=$!
        wait "$CHILD"
        local codigo=$?
        CHILD=""
        fim=$(date +%s)

        # Se ficou de pé por um bom tempo, volta a espera ao mínimo
        [ $((fim - inicio)) -ge 60 ] && espera=2
        echo "[!] Agente encerrou (código $codigo). Reiniciando em ${espera}s..."
        sleep "$espera"
        espera=$((espera * 2))
        [ "$espera" -gt 60 ] && espera=60
    done
}

# --- Execução ----------------------------------------------------------------------
if [ "$MODO" != "loop" ] && pid_rodando; then
    echo "[!] O agente já está rodando (PID $(cat "$PID_FILE")). Use: bash $0 stop"
    exit 1
fi

case "$MODO" in
    fg)
        echo "[*] Iniciando Node Agent -> host: $DROID_HOST_IP:$DROID_HOST_PORT"
        echo "[*] Log do agente: $LOG_DIR/node.log"
        loop_agente
        ;;
    daemon)
        nohup bash "$DIR/run.sh" _loop >> "$LOG_DIR/agent.out" 2>&1 &
        sleep 1
        echo "[+] Node Agent iniciado em segundo plano -> host: $DROID_HOST_IP:$DROID_HOST_PORT"
        echo "    Acompanhar:  tail -f $LOG_DIR/node.log"
        echo "    Encerrar:    bash $DIR/run.sh stop"
        ;;
    loop)
        loop_agente
        ;;
esac
