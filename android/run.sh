#!/usr/bin/env bash
#
# DroidServer — inicia o agente do node (android/node.py)
#
# Carrega as configurações salvas pelo setup.sh (IP/porta/token) e
# mantém o agente em execução no terminal.
#
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$HOME/.config/droidserver/env"

if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    . "$ENV_FILE"
fi

if [ -z "${DROID_HOST_IP:-}" ]; then
    echo "[!] Configuração não encontrada. Rode primeiro: bash $DIR/setup.sh"
    exit 1
fi

echo "[*] Iniciando Node Agent -> host: $DROID_HOST_IP:$DROID_HOST_PORT"
cd "$DIR"
exec python3 node.py
