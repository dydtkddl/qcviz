#!/bin/bash
# QCViz-MCP v3 서버 시작 스크립트

export PYTHONPATH="/mnt/d/20260305_양자화학시각화MCP서버구축/version03/src"
export GEMINI_API_KEY="AIzaSyBmsb0NTgIK86xxnLVyIrsrB5SjRMWlDLw"
export QCVIZ_HOST="0.0.0.0"
export QCVIZ_LOG_LEVEL="INFO"

echo "🚀 Starting QCViz-MCP v3 on 0.0.0.0:8223 (root_path=/qcviz)"
echo "   GEMINI_API_KEY: ${GEMINI_API_KEY:0:10}..."
echo "   PYTHONPATH: $PYTHONPATH"

uvicorn qcviz_mcp.web.app:app --host 0.0.0.0 --port 8223 --root-path /qcviz --reload
