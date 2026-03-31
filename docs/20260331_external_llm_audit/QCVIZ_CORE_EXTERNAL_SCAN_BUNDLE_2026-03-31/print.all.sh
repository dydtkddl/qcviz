#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# bundle_core.sh — 핵심 소스를 단일 .md 로 묶는 스크립트
# ──────────────────────────────────────────────────────────────

# pipefail은 유지하되, (( )) 산술 문제를 피하기 위해 수정
set -uo pipefail

# ── 현재 스크립트가 있는 디렉토리를 PROJECT_ROOT로 자동 설정 ──
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
OUTPUT="$PROJECT_ROOT/QCVIZ_CORE_BUNDLE_$(date +%Y%m%d_%H%M%S).md"

echo "📂 PROJECT_ROOT = $PROJECT_ROOT"
echo "📄 OUTPUT       = $OUTPUT"
echo ""

# ── 핵심 파일 목록 ──
CORE_FILES=(
  "pyproject.toml"
  "requirements.txt"
  "pytest.ini"
  "run.sh"
  "run_dev.py"
  "start_server.sh"
  "src/qcviz_mcp/__init__.py"
  "src/qcviz_mcp/app.py"
  "src/qcviz_mcp/mcp_server.py"
  "src/qcviz_mcp/config.py"
  "src/qcviz_mcp/errors.py"
  "src/qcviz_mcp/log_config.py"
  "src/qcviz_mcp/observability.py"
  "src/qcviz_mcp/security.py"
  "src/qcviz_mcp/llm/__init__.py"
  "src/qcviz_mcp/llm/agent.py"
  "src/qcviz_mcp/llm/bridge.py"
  "src/qcviz_mcp/llm/pipeline.py"
  "src/qcviz_mcp/llm/providers.py"
  "src/qcviz_mcp/llm/schemas.py"
  "src/qcviz_mcp/llm/prompts.py"
  "src/qcviz_mcp/llm/normalizer.py"
  "src/qcviz_mcp/llm/execution_guard.py"
  "src/qcviz_mcp/llm/grounding_merge.py"
  "src/qcviz_mcp/llm/lane_lock.py"
  "src/qcviz_mcp/llm/rule_provider.py"
  "src/qcviz_mcp/llm/trace.py"
  "src/qcviz_mcp/llm/prompt_assets/action_planner.md"
  "src/qcviz_mcp/llm/prompt_assets/action_planner_repair.md"
  "src/qcviz_mcp/llm/prompt_assets/grounding_decider.md"
  "src/qcviz_mcp/llm/prompt_assets/grounding_decider_repair.md"
  "src/qcviz_mcp/llm/prompt_assets/ingress_rewrite.md"
  "src/qcviz_mcp/llm/prompt_assets/ingress_rewrite_repair.md"
  "src/qcviz_mcp/llm/prompt_assets/semantic_expansion.md"
  "src/qcviz_mcp/llm/prompt_assets/semantic_expansion_repair.md"
  "src/qcviz_mcp/advisor/__init__.py"
  "src/qcviz_mcp/advisor/confidence_scorer.py"
  "src/qcviz_mcp/advisor/literature_validator.py"
  "src/qcviz_mcp/advisor/methods_drafter.py"
  "src/qcviz_mcp/advisor/preset_recommender.py"
  "src/qcviz_mcp/advisor/script_generator.py"
  "src/qcviz_mcp/advisor/execution/cache.py"
  "src/qcviz_mcp/advisor/execution/worker.py"
  "src/qcviz_mcp/advisor/reference_data/__init__.py"
  "src/qcviz_mcp/advisor/reference_data/functional_recommendations.json"
  "src/qcviz_mcp/advisor/reference_data/dft_accuracy_table.json"
  "src/qcviz_mcp/advisor/reference_data/gmtkn55_subset.json"
  "src/qcviz_mcp/advisor/reference_data/nist_bonds.json"
  "src/qcviz_mcp/backends/__init__.py"
  "src/qcviz_mcp/backends/base.py"
  "src/qcviz_mcp/backends/registry.py"
  "src/qcviz_mcp/backends/ase_backend.py"
  "src/qcviz_mcp/backends/cclib_backend.py"
  "src/qcviz_mcp/backends/pyscf_backend.py"
  "src/qcviz_mcp/backends/viz_backend.py"
  "src/qcviz_mcp/compute/pyscf_runner.py"
  "src/qcviz_mcp/compute/job_manager.py"
  "src/qcviz_mcp/compute/disk_cache.py"
  "src/qcviz_mcp/compute/safety_guard.py"
  "src/qcviz_mcp/analysis/__init__.py"
  "src/qcviz_mcp/analysis/charge_transfer.py"
  "src/qcviz_mcp/analysis/fragment_detector.py"
  "src/qcviz_mcp/analysis/sanitize.py"
  "src/qcviz_mcp/execution/__init__.py"
  "src/qcviz_mcp/execution/cache.py"
  "src/qcviz_mcp/execution/worker.py"
  "src/qcviz_mcp/renderers/__init__.py"
  "src/qcviz_mcp/renderers/png_exporter.py"
  "src/qcviz_mcp/renderers/pyvista_renderer.py"
  "src/qcviz_mcp/services/__init__.py"
  "src/qcviz_mcp/services/gemini_agent.py"
  "src/qcviz_mcp/services/structure_resolver.py"
  "src/qcviz_mcp/services/pubchem_client.py"
  "src/qcviz_mcp/services/molchat_client.py"
  "src/qcviz_mcp/services/sdf_converter.py"
  "src/qcviz_mcp/services/ion_pair_handler.py"
  "src/qcviz_mcp/services/ko_aliases.py"
  "src/qcviz_mcp/tools/__init__.py"
  "src/qcviz_mcp/tools/core.py"
  "src/qcviz_mcp/tools/advisor_tools.py"
  "src/qcviz_mcp/tools/health.py"
  "src/qcviz_mcp/web/app.py"
  "src/qcviz_mcp/web/advisor_flow.py"
  "src/qcviz_mcp/web/conversation_state.py"
  "src/qcviz_mcp/web/result_explainer.py"
  "src/qcviz_mcp/web/session_auth.py"
  "src/qcviz_mcp/web/auth_store.py"
  "src/qcviz_mcp/web/job_backend.py"
  "src/qcviz_mcp/web/arq_backend.py"
  "src/qcviz_mcp/web/redis_job_store.py"
  "src/qcviz_mcp/web/runtime_info.py"
  "src/qcviz_mcp/web/routes/chat.py"
  "src/qcviz_mcp/web/routes/compute.py"
  "src/qcviz_mcp/web/templates/index.html"
  "src/qcviz_mcp/web/static/app.js"
  "src/qcviz_mcp/web/static/chat.js"
  "src/qcviz_mcp/web/static/viewer.js"
  "src/qcviz_mcp/web/static/results.js"
  "src/qcviz_mcp/web/static/style.css"
  "src/qcviz_mcp/worker/__init__.py"
  "src/qcviz_mcp/worker/arq_worker.py"
  "README.md"
  "docs/20260330_patch_4/live_playwright_restart_audit.md"
)

# ── 언어 태그 ──
lang_tag() {
  case "${1##*.}" in
    py)        echo "python"     ;;
    js)        echo "javascript" ;;
    sh)        echo "bash"       ;;
    toml)      echo "toml"       ;;
    json)      echo "json"       ;;
    yaml|yml)  echo "yaml"       ;;
    html)      echo "html"       ;;
    css)       echo "css"        ;;
    md)        echo "markdown"   ;;
    ini)       echo "ini"        ;;
    txt)       echo "text"       ;;
    *)         echo ""           ;;
  esac
}

# ── 카운터 (set -e 안전하게) ──
included=0
skipped=0

# ── 헤더 ──
cat > "$OUTPUT" <<EOF
# QCVIZ MCP — Core Source Bundle

> Auto-generated: $(date '+%Y-%m-%d %H:%M:%S')
> Files: ${#CORE_FILES[@]}

---

## Table of Contents

EOF

idx=1
for f in "${CORE_FILES[@]}"; do
  echo "${idx}. \`${f}\`" >> "$OUTPUT"
  idx=$((idx + 1))
done

printf '\n---\n\n' >> "$OUTPUT"

# ── 본문 ──
for f in "${CORE_FILES[@]}"; do
  full="$PROJECT_ROOT/$f"

  printf '## `%s`\n\n' "$f" >> "$OUTPUT"

  if [[ -f "$full" ]]; then
    tag=$(lang_tag "$f")
    printf '```%s\n' "$tag" >> "$OUTPUT"
    cat "$full" >> "$OUTPUT"
    printf '\n```\n' >> "$OUTPUT"
    included=$((included + 1))
    echo "  ✅ $f"
  else
    echo '*⚠️  File not found — skipped*' >> "$OUTPUT"
    skipped=$((skipped + 1))
    echo "  ❌ $f  (NOT FOUND)"
  fi

  printf '\n---\n\n' >> "$OUTPUT"
done

# ── 요약 ──
cat >> "$OUTPUT" <<EOF
## Summary

- **Included**: ${included} files
- **Skipped (not found)**: ${skipped} files
- **Total listed**: ${#CORE_FILES[@]} files
EOF

echo ""
echo "════════════════════════════════════════════"
echo "  ✅ Bundle created!"
echo "  📄 $OUTPUT"
echo "  📦 $(wc -l < "$OUTPUT") lines / $(du -h "$OUTPUT" | cut -f1)"
echo "════════════════════════════════════════════"
