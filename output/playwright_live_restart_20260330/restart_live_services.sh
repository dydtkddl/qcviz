#!/usr/bin/env bash
set -euo pipefail
SELF="$(readlink -f "$0")"
OUT_DIR="$(dirname "$SELF")"
ROOT="$(dirname "$(dirname "$OUT_DIR")")"
MOLCHAT_ROOT="/mnt/c/Users/user/Desktop/molcaht/molchat/v3"
source /home/yongsang/miniconda3/etc/profile.d/conda.sh

cd "$MOLCHAT_ROOT/backend"
set -a
source .env
set +a
nohup /home/yongsang/miniconda3/envs/molchat/bin/uvicorn app.main:app --host 0.0.0.0 --port 8333 --workers 2 > /tmp/qcviz_live_audit_molchat_backend.log 2>&1 < /dev/null &
echo "MOLCHAT_BACKEND_PID=$!"

cd "$MOLCHAT_ROOT/frontend"
nohup ./node_modules/.bin/next start -H 0.0.0.0 -p 3000 > /tmp/qcviz_live_audit_molchat_frontend.log 2>&1 < /dev/null &
echo "MOLCHAT_FRONTEND_PID=$!"

conda activate qcviz
cd "$ROOT"
export MOLCHAT_BASE_URL='http://127.0.0.1:8333'
nohup bash ./a.sh > /tmp/qcviz_live_audit_qcviz.log 2>&1 < /dev/null &
echo "QCVIZ_PID=$!"
