# QCViz SVG Diagram Generation Prompt

Date: 2026-03-30

## Purpose

This document is a copy-paste-ready enterprise prompt for another high-end LLM.
Its job is to generate clean, presentation-ready raw SVG diagrams for the current QCViz architecture.

Use this when you want the other LLM to output final SVG code directly, not Mermaid, not pseudo-code, and not a vague design description.

## Copy-Paste Prompt

```md
You are a senior staff-level systems architect and information designer.
Your task is to generate polished, presentation-ready SVG diagrams for a real software system.

You must produce raw standalone SVG code, not Mermaid, not Graphviz, not prose-only descriptions.
Each SVG must be immediately saveable as an `.svg` file and render correctly in modern browsers and PowerPoint/Keynote.

---

# Project Context

The system is called **QCViz**.

QCViz is:
- a web-first conversational computational chemistry platform
- designed for experimental chemists who may not be experts in DFT setup
- intended to unify:
  - natural-language input
  - molecule grounding / structure resolution
  - DFT or related quantum chemistry computation
  - visualization
  - literature-backed preset recommendation

QCViz is **not**:
- not a LangChain application
- not a LangGraph application
- not an MCP-native end-to-end web runtime

The most accurate description is:
- **custom LLM-first orchestration pipeline**
- **FastAPI web runtime**
- **MolChat-based semantic grounding / structure interpretation**
- **PySCF compute backend**
- **literature-backed rule/lookup recommender for basis/functional/preset guidance**
- **optional FastMCP sidecar compatibility layer**

Important architectural truth:
- There is a real FastMCP server in the repo, but the main web runtime does not internally execute the user request via MCP.
- The main web path is a custom pipeline, not an MCP client -> MCP server execution path.

---

# Source-of-Truth Architecture

The current target runtime architecture is a **4-stage LLM-first pipeline**:

1. **Ingress Normalize + Annotate**
   - deterministic cleanup and annotation first
   - optional thin LLM rewrite only for noisy input
   - preserves chemistry tokens such as HOMO, LUMO, ESP, B3LYP, def2-SVP, etc.

2. **Router-Planner**
   - single structured-output LLM call
   - determines lane and extracts slots
   - lane choices:
     - `chat_only`
     - `grounding_required`
     - `compute_ready`
   - may repair once
   - falls back to heuristic planner if needed

3. **Grounding Merge**
   - fully deterministic
   - merges planner result with MolChat grounding candidates
   - produces semantic outcome:
     - `chat_only`
     - `grounded_direct_answer`
     - `single_candidate_confirm`
     - `grounding_clarification`
     - `custom_only_clarification`
     - `compute_ready`

4. **Execution Guard**
   - fully deterministic
   - final gate before compute submission
   - prevents compute when structure is unresolved or clarification is still needed

Supporting concepts:
- `LaneLock` prevents per-turn lane flipping
- heuristic fallback remains alive at all times
- shadow mode can run LLM and heuristic paths in parallel while heuristic still serves users
- canary rollout is planned after shadow evaluation

---

# Chemistry Recommendation Authority

For basis set / functional / preset recommendation:

- The primary authority is **not the LLM**
- The primary authority is **literature-backed rule / lookup tables**
- LLM is allowed to help with:
  - question interpretation
  - clarification
  - explanation of why a recommendation was chosen
  - system / purpose inference support
- LLM is **not** the final authority for scientific preset choice

So the architecture should visually show:
- LLM for interpretation/orchestration
- rule-based recommender for scientific configuration authority
- deterministic guard before execution

---

# Required Deliverables

Generate **3 standalone SVG diagrams**.

## Diagram 1 — High-Level System Architecture

Goal:
- Show the full QCViz system at the platform level

Must include:
- User / Experimental Chemist
- Web UI
- FastAPI web runtime
- Custom LLM-first orchestration pipeline
- MolChat grounding / structure resolution
- Literature-backed preset recommender
- PySCF compute backend
- Visualization / results
- Optional FastMCP sidecar

Must visually communicate:
- Web-first main path
- MCP is optional / sidecar, not the main user request path
- LangChain is not part of the stack

## Diagram 2 — Per-Request Runtime Flow

Goal:
- Show what happens to a single user message from input to result

Must include:
- user message
- ingress normalize + annotate
- router-planner
- lane lock
- MolChat grounding in parallel or merge-adjacent form
- grounding merge
- execution guard
- either:
  - direct answer
  - clarification
  - compute submission
- PySCF execution
- result packaging / visualization
- heuristic fallback path
- shadow mode note

Must visually communicate:
- explanation-style question does not go straight to compute
- ambiguous compute requests go to grounding first
- explicit compute with resolved structure can proceed
- fallback does not wobble or bounce repeatedly

## Diagram 3 — Scientific Recommendation Authority Diagram

Goal:
- Show how basis set / DFT recommendation authority is split

Must include:
- user goal / chemistry task
- LLM interpretation layer
- system type / purpose extraction
- literature-backed lookup / rule engine
- recommended:
  - functional
  - basis
  - rationale
  - references
  - confidence
- warning / conservative fallback for high-risk systems
- final compute settings passed to PySCF

Must visually communicate:
- LLM helps interpret and explain
- rule tables make the scientific recommendation
- deterministic validation still sits before execution

---

# Visual Style Requirements

Design these for a professional technical presentation.

Requirements:
- clean enterprise architecture style
- white or very light background
- high contrast
- readable at presentation size
- no cartoon style
- no playful icons
- no unnecessary gradients
- subtle color system only
- consistent spacing and alignment
- modern sans-serif typography in SVG text

Recommended palette:
- dark text: `#0F172A`
- muted text: `#475569`
- border: `#CBD5E1`
- main architecture blue: `#2563EB`
- deterministic/rules green: `#059669`
- warning/clarification amber: `#D97706`
- compute backend slate: `#334155`
- optional sidecar purple-gray: `#7C3AED` or `#6D28D9` used sparingly

Diagram conventions:
- rounded rectangles for components
- arrows with clear direction
- dashed borders or dashed arrows for optional/sidecar/fallback paths
- use labels directly on connectors where useful
- use a small legend only if necessary

---

# Layout Rules

For each SVG:
- aspect ratio should fit a 16:9 presentation slide
- use `viewBox` and explicit width/height
- keep comfortable outer margins
- avoid edge clipping
- avoid tiny text
- keep labels short

Target:
- width around `1600`
- height around `900`
- `viewBox="0 0 1600 900"`

---

# Output Format

Return exactly this structure:

1. short heading: `Diagram 1: High-Level System Architecture`
2. one short sentence describing the diagram
3. one fenced code block containing complete raw SVG

Then repeat the same for Diagram 2 and Diagram 3.

Do not output explanations between SVG blocks beyond one concise sentence per diagram.
Do not output Mermaid.
Do not output pseudo-SVG.
Do not say “here is an example”.
Do not omit closing tags.

---

# Hard Constraints

Do NOT depict the web runtime as:
- `User -> Web App -> MCP Client -> MCP Server -> Compute`

That is not the main runtime path.

Do NOT depict basis/functional selection as:
- “LLM directly chooses best DFT settings”

That is not the intended authority model.

Do NOT include LangChain, LangGraph, or LlamaIndex logos, labels, or boxes.

Do NOT overcomplicate the diagrams with excessive internals.
They should be technically accurate but presentation-friendly.

---

# Preferred Semantic Messaging

The diagrams should reinforce these messages:

- QCViz is a **web-first all-in-one computational chemistry platform**
- The runtime is a **custom LLM-first orchestration pipeline**
- **MolChat grounds structures**
- **PySCF performs the real calculations**
- **Rule-based literature-backed recommendation** governs scientific presets
- **Deterministic guardrails** protect compute execution
- **MCP exists as optional compatibility**, not as the core user-facing runtime path

---

# Optional Nice-to-Have

If space allows, add one subtle note in Diagram 2 indicating:
- `shadow mode: LLM path and heuristic path can run in parallel during rollout`

If space allows, add one subtle note in Diagram 3 indicating:
- `high-risk systems -> conservative preset + warning`

---

# Final Task

Now generate all 3 SVG diagrams.
```

## Suggested Usage

- If you want one-shot output, paste the whole block into the other LLM.
- If you want better control, ask it to generate only `Diagram 1` first, review, then request `Diagram 2` and `Diagram 3`.
- If you want Korean labels instead of English labels inside the SVG, append:

```md
Use Korean labels inside the SVG where natural, but keep technical acronyms such as LLM, PySCF, ESP, HOMO, LUMO, MCP in English.
```

## Reference Facts You Can Send Together

If the other LLM asks for more context, send these facts:

- Main runtime is custom LLM orchestration, not LangChain.
- Web runtime is not MCP-native end-to-end.
- FastMCP exists as optional compatibility layer.
- The compute backend is PySCF.
- MolChat is used for semantic grounding / molecule interpretation.
- Preset recommendation is rule-based and literature-backed.
- Execution guard is deterministic.
- The key runtime lanes are:
  - `chat_only`
  - `grounding_required`
  - `compute_ready`

