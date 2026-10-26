#!/usr/bin/env bash
# Sobe o coletor em segundo plano (reinicia se cair) e o painel na porta do Render.
set -u

(
  while true; do
    python -m tuneis coletar
    echo "coletor parou (código $?); reiniciando em 30 s" >&2
    sleep 30
  done
) &

exec streamlit run dashboard/app.py --server.port "${PORT:-8501}" --server.address 0.0.0.0 --server.headless true
