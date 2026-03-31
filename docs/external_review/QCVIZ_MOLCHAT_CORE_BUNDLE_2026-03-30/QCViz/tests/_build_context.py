"""Build a comprehensive markdown context document from all core project files."""
import os

BASE = r"D:\20260305_양자화학시각화MCP서버구축\version03"
SRC = os.path.join(BASE, "src", "qcviz_mcp")
OUT = os.path.join(BASE, "MCP_ARCHITECTURE_ANALYSIS.md")

# Core files in logical order
CORE_FILES = [
    # Config
    ("pyproject.toml", os.path.join(BASE, "pyproject.toml")),
    ("config.py", os.path.join(SRC, "config.py")),
    ("app.py", os.path.join(SRC, "app.py")),
    
    # MCP Server
    ("mcp_server.py", os.path.join(SRC, "mcp_server.py")),
    
    # MCP Tools
    ("tools/core.py", os.path.join(SRC, "tools", "core.py")),
    ("tools/advisor_tools.py", os.path.join(SRC, "tools", "advisor_tools.py")),
    ("tools/health.py", os.path.join(SRC, "tools", "health.py")),
    
    # LLM / Agent
    ("llm/agent.py", os.path.join(SRC, "llm", "agent.py")),
    ("llm/bridge.py", os.path.join(SRC, "llm", "bridge.py")),
    ("llm/prompts.py", os.path.join(SRC, "llm", "prompts.py")),
    ("llm/schemas.py", os.path.join(SRC, "llm", "schemas.py")),
    ("llm/providers.py", os.path.join(SRC, "llm", "providers.py")),
    ("llm/rule_provider.py", os.path.join(SRC, "llm", "rule_provider.py")),
    
    # Services
    ("services/gemini_agent.py", os.path.join(SRC, "services", "gemini_agent.py")),
    ("services/structure_resolver.py", os.path.join(SRC, "services", "structure_resolver.py")),
    ("services/pubchem_client.py", os.path.join(SRC, "services", "pubchem_client.py")),
    ("services/molchat_client.py", os.path.join(SRC, "services", "molchat_client.py")),
    ("services/ion_pair_handler.py", os.path.join(SRC, "services", "ion_pair_handler.py")),
    ("services/ko_aliases.py", os.path.join(SRC, "services", "ko_aliases.py")),
    
    # Compute
    ("compute/pyscf_runner.py", os.path.join(SRC, "compute", "pyscf_runner.py")),
    ("compute/job_manager.py", os.path.join(SRC, "compute", "job_manager.py")),
    ("compute/disk_cache.py", os.path.join(SRC, "compute", "disk_cache.py")),
    ("compute/safety_guard.py", os.path.join(SRC, "compute", "safety_guard.py")),
    
    # Web routes
    ("web/routes/chat.py", os.path.join(SRC, "web", "routes", "chat.py")),
    ("web/routes/compute.py", os.path.join(SRC, "web", "routes", "compute.py")),
    
    # Backends
    ("backends/pyscf_backend.py", os.path.join(SRC, "backends", "pyscf_backend.py")),
    ("backends/viz_backend.py", os.path.join(SRC, "backends", "viz_backend.py")),
    ("backends/base.py", os.path.join(SRC, "backends", "base.py")),
    ("backends/registry.py", os.path.join(SRC, "backends", "registry.py")),
    
    # Advisor
    ("advisor/preset_recommender.py", os.path.join(SRC, "advisor", "preset_recommender.py")),
    ("advisor/methods_drafter.py", os.path.join(SRC, "advisor", "methods_drafter.py")),
    ("advisor/confidence_scorer.py", os.path.join(SRC, "advisor", "confidence_scorer.py")),
    
    # Analysis
    ("analysis/charge_transfer.py", os.path.join(SRC, "analysis", "charge_transfer.py")),
    ("analysis/fragment_detector.py", os.path.join(SRC, "analysis", "fragment_detector.py")),
    
    # Other core
    ("errors.py", os.path.join(SRC, "errors.py")),
    ("security.py", os.path.join(SRC, "security.py")),
    ("observability.py", os.path.join(SRC, "observability.py")),
    
    # Frontend
    ("web/templates/index.html", os.path.join(SRC, "web", "templates", "index.html")),
    ("web/static/chat.js", os.path.join(SRC, "web", "static", "chat.js")),
    ("web/static/app.js", os.path.join(SRC, "web", "static", "app.js")),
    ("web/static/viewer.js", os.path.join(SRC, "web", "static", "viewer.js")),
    ("web/static/results.js", os.path.join(SRC, "web", "static", "results.js")),
    ("web/static/style.css", os.path.join(SRC, "web", "static", "style.css")),
]

lines = []
total_bytes = 0
file_count = 0

for label, path in CORE_FILES:
    if not os.path.isfile(path):
        lines.append(f"\n## ⚠️ FILE NOT FOUND: `{label}`\n\n")
        continue
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        lines.append(f"\n## ⚠️ READ ERROR: `{label}` — {e}\n\n")
        continue
    
    ext = os.path.splitext(path)[1].lstrip(".")
    lang_map = {"py": "python", "js": "javascript", "html": "html", "css": "css", "toml": "toml"}
    lang = lang_map.get(ext, ext)
    
    lines.append(f"\n---\n\n## 📄 `{label}`\n\n")
    lines.append(f"**Path**: `{path}`  \n")
    lines.append(f"**Size**: {len(content):,} bytes | {content.count(chr(10))+1} lines\n\n")
    lines.append(f"```{lang}\n{content}\n```\n")
    total_bytes += len(content)
    file_count += 1

body = "".join(lines)

with open(OUT, "w", encoding="utf-8") as f:
    f.write(body)

print(f"✅ Created: {OUT}")
print(f"   Files: {file_count}")
print(f"   Source bytes: {total_bytes:,}")
print(f"   Document size: {len(body):,} bytes ({len(body)/1024:.1f} KB)")
