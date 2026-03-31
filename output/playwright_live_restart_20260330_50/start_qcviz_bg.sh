#!/usr/bin/env bash
set -euo pipefail

source ~/miniconda3/etc/profile.d/conda.sh
conda activate qcviz

cd /mnt/d/20260305_양자화학시각화MCP서버구축/version03

exec python -m uvicorn qcviz_mcp.web.app:app \
  --host 0.0.0.0 \
  --port 8817 \
  --ws wsproto \
  --app-dir src
