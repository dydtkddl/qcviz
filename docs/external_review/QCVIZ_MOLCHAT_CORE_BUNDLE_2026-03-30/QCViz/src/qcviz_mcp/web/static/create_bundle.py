import os
from pathlib import Path

# The list of target files to include in the context bundle
TARGET_FILES = [
    "version02/src/qcviz_mcp/web/routes/chat.py",
    "version02/src/qcviz_mcp/web/routes/compute.py",
    "version02/src/qcviz_mcp/compute/pyscf_runner.py",
    "version02/src/qcviz_mcp/compute/job_manager.py",
    "version02/src/qcviz_mcp/web/static/viewer.js",
    "version02/src/qcviz_mcp/web/static/results.js",
    "version02/src/qcviz_mcp/web/static/chat.js",
    "version02/src/qcviz_mcp/web/static/index.html",
    "version02/src/qcviz_mcp/web/static/style.css"
]

OUTPUT_FILE = "version02/src/qcviz_mcp/web/static/qcviz_context_bundle.md"

header = """# QCViz-MCP Enterprise V2 — 50억 달러 마스터 플랜 컨텍스트 번들

> **프로젝트**: 양자화학 시각화 MCP 서버 (Quantum Chemistry Visualization MCP Server)
> **목표**: 일반 실험 연구자가 CLI/터미널 지식 없이, 브라우저 하나로 자연어 입력만으로 양자화학 계산·시각화·분석을 수행하는 완전한 엔터프라이즈급 SaaS
> **아키텍처**: FastAPI + PySCF + 3Dmol.js + WebSocket + LLM (Gemini/OpenAI) Function Calling

이 문서는 AI 에이전트(GPT 등)가 QCViz-MCP의 현재 상태를 정확히 파악하고, LLM Function Calling 전환 및 엣지 시각화 기능(ESP Auto-Fit, IBO, 진동 애니메이션 등)을 개발할 수 있도록 제공되는 핵심 종속 파일 번들입니다.

---

"""

with open(OUTPUT_FILE, 'w', encoding='utf-8') as outfile:
    outfile.write(header)
    
    for filepath in TARGET_FILES:
        path = Path(filepath)
        if not path.exists():
            print(f"Warning: {filepath} not found.")
            continue
            
        extension = path.suffix[1:] if path.suffix else 'txt'
        if extension == 'js':
            lang = 'javascript'
        elif extension == 'py':
            lang = 'python'
        elif extension == 'html':
            lang = 'html'
        elif extension == 'css':
            lang = 'css'
        else:
            lang = 'text'

        outfile.write(f"## [{path.name}]\n")
        outfile.write(f"경로: `{filepath}`\n\n")
        outfile.write(f"```{lang}\n")
        
        try:
            with open(path, 'r', encoding='utf-8') as infile:
                outfile.write(infile.read())
        except Exception as e:
            outfile.write(f"Error reading file: {e}\n")
            
        outfile.write("\n```\n\n")

print(f"Successfully created {OUTPUT_FILE}")
