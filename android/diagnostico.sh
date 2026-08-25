#!/usr/bin/env bash
#
# DroidServer — Coleta de diagnóstico do node (rode no Termux e cole a saída)
#
#   bash android/diagnostico.sh
#
set -u

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
LOG="$HOME/.config/droidserver/logs/node.log"

echo "===== AMBIENTE ====="
echo "PREFIX=$PREFIX"
echo "HOME=$HOME"
"$PREFIX/bin/python" --version 2>&1 || python3 --version 2>&1

echo
echo "===== /proc/stat (1a linha) ====="
head -1 /proc/stat 2>&1 || echo "ERRO: /proc/stat ilegível"

echo
echo "===== /proc/meminfo (parcial) ====="
grep -E '^(MemTotal|MemAvailable|MemFree)' /proc/meminfo 2>&1 || echo "ERRO"

echo
echo "===== proot-distro list ====="
proot-distro list 2>&1 || echo "ERRO: proot-distro list -> $?"

echo
echo "===== rootfs instalados (diretórios) ====="
ls -la "$PREFIX/var/lib/proot-distro/installed-rootfs/" 2>&1 || echo "ERRO ou pasta vazia"

echo
echo "===== metadado installed-distros.json ====="
cat "$PREFIX/etc/proot-distro/installed-distros.json" 2>&1 | head -40

echo
echo "===== lock do proot-distro ====="
ls -la "$PREFIX/var/lib/proot-distro/" 2>&1 | grep -i lock || echo "(sem arquivos de lock)"

echo
echo "===== supervisor ====="
supervisorctl -c "$PREFIX/etc/supervisord.conf" status 2>&1 || echo "ERRO: supervisorctl -> $?"

echo
echo "===== confs do supervisor ====="
ls -la "$PREFIX/etc/supervisor/conf.d/" 2>&1

echo
echo "===== node.log (últimas 40 linhas) ====="
tail -40 "$LOG" 2>&1 || echo "node.log não encontrado em $LOG"
