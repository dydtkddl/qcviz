#!/bin/bash
# generate_v3_context.sh
# version03 루트에서 실행: ~/d/20260305_.../version03/

OUTPUT="v3_patch_context.md"

cat > "$OUTPUT" << 'HEADER'
# QCViz Version03 - 패치 대상 핵심 파일 전문 (패치 전 상태)
---

HEADER

# ━━━ 패치 대상 핵심 파일만 (순서대로) ━━━
FILES=(
  # 진입점 / 설정
  "src/qcviz_mcp/config.py"
  "src/qcviz_mcp/app.py"
  "src/qcviz_mcp/web/app.py"
  "src/qcviz_mcp/errors.py"

  # LLM (Gemini 탑재 대상)
  "src/qcviz_mcp/llm/__init__.py"
  "src/qcviz_mcp/llm/agent.py"
  "src/qcviz_mcp/llm/bridge.py"
  "src/qcviz_mcp/llm/prompts.py"
  "src/qcviz_mcp/llm/providers.py"
  "src/qcviz_mcp/llm/rule_provider.py"
  "src/qcviz_mcp/llm/schemas.py"

  # 계산 엔진 (PySCF - 유지하되 수정)
  "src/qcviz_mcp/compute/pyscf_runner.py"
  "src/qcviz_mcp/compute/job_manager.py"
  "src/qcviz_mcp/compute/disk_cache.py"
  "src/qcviz_mcp/compute/safety_guard.py"

  # 웹 라우트 (MolChat 연동 대상)
  "src/qcviz_mcp/web/routes/compute.py"
  "src/qcviz_mcp/web/routes/chat.py"
  "src/qcviz_mcp/web/advisor_flow.py"

  # 프론트엔드
  "src/qcviz_mcp/web/static/chat.js"
  "src/qcviz_mcp/web/static/viewer.js"
  "src/qcviz_mcp/web/static/results.js"
  "src/qcviz_mcp/web/static/app.js"
  "src/qcviz_mcp/web/static/style.css"
  "src/qcviz_mcp/web/templates/index.html"

  # 도구 / MCP
  "src/qcviz_mcp/tools/__init__.py"
  "src/qcviz_mcp/tools/core.py"
  "src/qcviz_mcp/tools/advisor_tools.py"
  "src/qcviz_mcp/tools/health.py"
  "src/qcviz_mcp/mcp_server.py"

  # 백엔드
  "src/qcviz_mcp/backends/__init__.py"
  "src/qcviz_mcp/backends/base.py"
  "src/qcviz_mcp/backends/pyscf_backend.py"
  "src/qcviz_mcp/backends/registry.py"
  "src/qcviz_mcp/backends/viz_backend.py"

  # 분석
  "src/qcviz_mcp/analysis/__init__.py"
  "src/qcviz_mcp/analysis/charge_transfer.py"
  "src/qcviz_mcp/analysis/fragment_detector.py"
  "src/qcviz_mcp/analysis/sanitize.py"

  # 어드바이저
  "src/qcviz_mcp/advisor/__init__.py"
  "src/qcviz_mcp/advisor/confidence_scorer.py"
  "src/qcviz_mcp/advisor/literature_validator.py"
  "src/qcviz_mcp/advisor/methods_drafter.py"
  "src/qcviz_mcp/advisor/preset_recommender.py"
  "src/qcviz_mcp/advisor/script_generator.py"
  "src/qcviz_mcp/advisor/execution/cache.py"
  "src/qcviz_mcp/advisor/execution/worker.py"

  # 기타 핵심
  "src/qcviz_mcp/__init__.py"
  "src/qcviz_mcp/security.py"
  "src/qcviz_mcp/log_config.py"
  "src/qcviz_mcp/observability.py"
  "src/qcviz_mcp/validation/__init__.py"
  "src/qcviz_mcp/utils/__init__.py"

  # 설정 파일 (루트)
  "pyproject.toml"
  "requirements.txt"
  "setup.py"
  "setup.cfg"
  "Dockerfile"
  "docker-compose.yml"
  "docker-compose.yaml"
  ".env"
  ".env.example"
)

FILE_COUNT=0

for f in "${FILES[@]}"; do
  if [ -f "$f" ]; then
    FSIZE=$(wc -c < "$f" 2>/dev/null || echo 0)
    LINES=$(wc -l < "$f" 2>/dev/null || echo 0)

    # 확장자별 언어
    case "$f" in
      *.py)   LANG="python" ;;
      *.js)   LANG="javascript" ;;
      *.css)  LANG="css" ;;
      *.html) LANG="html" ;;
      *.toml) LANG="toml" ;;
      *.yaml|*.yml) LANG="yaml" ;;
      *.txt)  LANG="" ;;
      *)      LANG="" ;;
    esac

    echo "" >> "$OUTPUT"
    echo "## 파일: \`$f\` (${LINES}줄, ${FSIZE}bytes)" >> "$OUTPUT"
    echo "" >> "$OUTPUT"
    echo "\`\`\`${LANG}" >> "$OUTPUT"
    cat "$f" >> "$OUTPUT"
    echo "" >> "$OUTPUT"
    echo '```' >> "$OUTPUT"
    echo "" >> "$OUTPUT"
    echo "---" >> "$OUTPUT"

    FILE_COUNT=$((FILE_COUNT + 1))
  fi
done

# 디렉토리 구조 첨부
echo "" >> "$OUTPUT"
echo "## 전체 디렉토리 구조" >> "$OUTPUT"
echo "" >> "$OUTPUT"
echo '```' >> "$OUTPUT"
find . -type f \
  -not -path './.git/*' \
  -not -path '*/__pycache__/*' \
  -not -path './.venv/*' \
  -not -path './venv/*' \
  | sort >> "$OUTPUT"
echo '```' >> "$OUTPUT"

TOTAL_LINES=$(wc -l < "$OUTPUT")

echo ""
echo "============================================"
echo "✅ $OUTPUT 생성 완료"
echo "   포함 파일: ${FILE_COUNT}개"
echo "   총 라인: ${TOTAL_LINES}"
echo "============================================"

