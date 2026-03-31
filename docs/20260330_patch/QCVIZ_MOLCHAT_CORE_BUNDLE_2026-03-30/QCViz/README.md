# QCViz-MCP Enterprise Web

A powerful, natural-language driven quantum chemistry visualization server. Connects PySCF, 3Dmol.js, and LLMs (Google Gemini, OpenAI) to provide an end-to-end web workspace.

## Key Features
* **Natural Language Planning**: Ask "Render ESP map for acetone" and let the AI do the rest.
* **Auto-fit ESP Surfaces**: Academic-grade (Multiwfn style) symmetric color mapping.
* **Dual MO Isosurfaces**: Renders both positive and negative phases of orbitals simultaneously.
* **Real-time WebSockets**: Async jobs with real-time UI updates (progress bars and log events).

## Quick Start (Editable Install)

It is highly recommended to use a virtual environment and perform an editable install.

```bash
# 1. Enter the project root
cd version02

# 2. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # (On Windows: .venv\Scripts\Activate.ps1)

# 3. Upgrade pip and build tools
python -m pip install --upgrade pip setuptools wheel

# 4. Install the package with dependencies
pip install -e ".[llm-gemini]"   # or .[llm-openai]

# 5. Start the server
uvicorn qcviz_mcp.web.app:app --reload
```

## Running Without Installation (Development Mode)
If you just want to run it from the source tree without `pip install -e .`:

```bash
cd version02
export PYTHONPATH=src
uvicorn qcviz_mcp.web.app:app --reload
```

## Environment Variables
Create a `.env` file in the `version02/` directory or export these variables:

```bash
# Optional: Enable LLM Planner (Defaults to heuristic regex parsing if no keys are found)
GEMINI_API_KEY="your_gemini_api_key_here"
# OPENAI_API_KEY="sk-..."

# Server Settings
QCVIZ_APP_TITLE="QCViz-MCP Enterprise"
QCVIZ_MAX_JOBS="200"
QCVIZ_CHAT_WS_POLL_SEC="1.0"
```

## Usage
Once the server is running, navigate to:
**http://127.0.0.1:8000**

Try clicking one of the "Quick Chips" in the chat composer (e.g., *Show HOMO of benzene*), or manually type a request like:
> `Calculate Mulliken charges for water`