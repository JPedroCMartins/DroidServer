#!/bin/sh
# Encadeia E3 -> E8 -> E7 (24 h) num único processo em segundo plano.
# Uso: DROID_SSH="-p 8022 <ip>" nohup setsid sh bench/rodar_fase3.sh > bench/resultados/fase3.log 2>&1 &
cd "$(dirname "$0")" || exit 1
echo "== E3 $(date -Is)"; uv run e3_sobrecarga_proot.py --worker demo_debian --repeticoes 10
echo "== E8 $(date -Is)"; uv run e8_vazao.py --worker demo_api --porta 8080 --concorrencias 1 10 50 --repeticoes 5 --duracao 20
echo "== E7 $(date -Is)"; uv run e7_disponibilidade.py --worker demo_api --porta 8080 --horas 24
echo "== fim $(date -Is)"
