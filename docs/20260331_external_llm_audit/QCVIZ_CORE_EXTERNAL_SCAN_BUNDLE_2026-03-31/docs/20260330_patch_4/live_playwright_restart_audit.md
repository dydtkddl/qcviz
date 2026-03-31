# Live Restart + Playwright 20-Case Audit

Date: `2026-03-30`  
Workspace: `D:\20260305_양자화학시각화MCP서버구축\version03`

## Scope

- Restarted `QCViz` on `:8817` and confirmed `boot_matches_current_disk == true`.
- Verified local `MolChat` UI/API on `:3000/molchat` and `:8333/api/v1/health/live`.
- Re-ran the full 20-case browser audit with the existing Playwright harness.
- Saved screenshots and per-case state under `output/playwright_live_restart_20260330/`.

## Verdict Summary

- Result counts: `PASS 20 / FAIL 0 / BLOCKED 0`
- The live service is now stable against the full audited scenario set.
- No remaining blocker was observed in the audited chat, grounding, continuation, or visualization flows.

## What Was Fixed

- Prevented premature WebSocket `completed` status updates from arriving before the terminal result payload.
- Kept final orbital/ESP visualization payloads attached to the terminal `job_update` / `result` path so the browser sees usable `visualization.available` state immediately.
- Hardened semantic candidate ordering so `main component of TNT ...` no longer defaults to unrelated candidates when MolChat returns noisy ranking.
- Preserved same-session semantic grounding context so pronoun and short follow-up requests stay on the previously resolved structure.

## Evidence

- JSON summary: `D:\20260305_양자화학시각화MCP서버구축\version03\output\playwright_live_restart_20260330\live_case_results.json`
- Pre-health snapshot: `D:\20260305_양자화학시각화MCP서버구축\version03\output\playwright_live_restart_20260330\health_snapshot_before_cases.json`
- Post-health snapshot: `D:\20260305_양자화학시각화MCP서버구축\version03\output\playwright_live_restart_20260330\health_snapshot_after_cases.json`

## Audit Matrix

| case_id | status | suspected_layer | actual |
|---|---|---|---|
| `case_01_qcviz_boot` | `PASS` | `Boot` | ws=Connected; clarify=0; confirm=0; result=-::-; viz={}; timeout=False; terminal_timeout=False; last='Welcome to QCViz-MCP v3. I can run quantum                     chemistry calculations using PySCF with Gemini AI plann |
| `case_02_molchat_availability` | `PASS` | `Boot` | ws=n/a; clarify=0; confirm=0; result=-::-; viz={}; timeout=False; terminal_timeout=False; last=''; options=[] |
| `case_03_benzene_homo` | `PASS` | `Job lifecycle` | ws=Connected; clarify=0; confirm=0; result=benzene::orbital_preview; viz={"orbital": true, "density": false, "esp": false}; timeout=False; terminal_timeout=False; last='계산 완료대기열 비어 있음Completed (100%)Cancel'; options=[] |
| `case_04_acetone_esp` | `PASS` | `Job lifecycle` | ws=Connected; clarify=0; confirm=0; result=acetone::esp_map; viz={"orbital": false, "density": false, "esp": true}; timeout=False; terminal_timeout=False; last='계산 완료대기열 비어 있음Completed (100%)Cancel'; options=[] |
| `case_05_water_optimize` | `PASS` | `Job lifecycle` | ws=Connected; clarify=0; confirm=0; result=water::geometry_optimization; viz={"orbital": false, "density": false, "esp": false}; timeout=False; terminal_timeout=False; last='water의 구조 최적화가 완료되었습니다. 최적화된 좌표와 안정화 경향을 확인할 수 |
| `case_06_composition_clarification` | `PASS` | `Prompt routing` | ws=Connected; clarify=1; confirm=0; result=-::-; viz={}; timeout=True; terminal_timeout=False; last='추가 정보가 필요합니다 / More information needed필요한 항목만 확인하면 바로 계산을 이어서 진행합니다.'benzene and toluene'을(를) 어떻게 해석할까요? / How should t |
| `case_07_homo_concept_chat` | `PASS` | `Prompt routing` | ws=Connected; clarify=0; confirm=0; result=-::-; viz={}; timeout=True; terminal_timeout=False; last='This looks more like a chemistry question than an explicit calculation request.If you want an explanation, ask the conc |
| `case_08_mea_chat_grounded` | `PASS` | `Semantic grounding` | ws=Connected; clarify=0; confirm=0; result=-::-; viz={}; timeout=True; terminal_timeout=False; last='MEA는 보통 Ethanolamine를 의미합니다.분자식: C2H7NOCID: 700근거: resolved from local alias preference for monoethanolamine원하시면 이 분자를  |
| `case_09_mea_compute_requires_grounding` | `PASS` | `Semantic grounding` | ws=Connected; clarify=1; confirm=0; result=-::-; viz={}; timeout=True; terminal_timeout=False; last='설명 기반 후보를 확인해 주세요 / Confirm candidates from the description입력하신 설명을 기반으로 MolChat에서 구조화한 후보를 정리했습니다.분자를 선택해 주세요 / Choose |
| `case_10_dma_ambiguous` | `PASS` | `Semantic grounding` | ws=Connected; clarify=1; confirm=0; result=-::-; viz={}; timeout=False; terminal_timeout=False; last='분자 이름을 조금 더 구체적으로 알려주세요 / Clarify the molecule현재 입력만으로는 하나의 분자를 확정하지 못했습니다. 분자 이름이나 SMILES를 직접 입력해 주세요.분자를 선택해 주세요 / C |
| `case_11_tnt_grounded_compute` | `PASS` | `Job lifecycle` | ws=Connected; clarify=1; confirm=0; result=6-TRINITROTOLUENE::orbital_preview; viz={"orbital": false, "density": false, "esp": false}; timeout=False; terminal_timeout=False; last='지금 계산 중실행 중 1/1Generating cube 1/10 (HOM |
| `case_12_pronoun_homo_followup` | `PASS` | `Job lifecycle` | ws=Connected; clarify=0; confirm=0; result=Ethanolamine::orbital_preview; viz={"orbital": true, "density": false, "esp": false}; timeout=False; terminal_timeout=False; last='계산 완료대기열 비어 있음Completed (100%)Cancel'; options |
| `case_13_pronoun_esp_followup` | `PASS` | `Job lifecycle` | ws=Connected; clarify=0; confirm=0; result=Ethanolamine::esp_map; viz={"orbital": false, "density": false, "esp": true}; timeout=False; terminal_timeout=False; last='계산 완료대기열 비어 있음Completed (100%)Cancel'; options=[] |
| `case_14_short_esp_followup` | `PASS` | `Continuation state` | ws=Connected; clarify=0; confirm=0; result=Ethanolamine::esp_map; viz={"orbital": false, "density": false, "esp": true}; timeout=False; terminal_timeout=False; last='계산 완료대기열 비어 있음Completed (100%)Cancel'; options=[] |
| `case_15_lumo_followup` | `PASS` | `Continuation state` | ws=Connected; clarify=0; confirm=0; result=Ethanolamine::orbital_preview; viz={"orbital": true, "density": false, "esp": false}; timeout=False; terminal_timeout=False; last='계산 완료대기열 비어 있음Completed (100%)Cancel'; options |
| `case_16_basis_parameter_followup` | `PASS` | `Continuation state` | ws=Connected; clarify=0; confirm=0; result=Ethanolamine::orbital_preview; viz={"orbital": true, "density": false, "esp": false}; timeout=False; terminal_timeout=False; last='계산 완료대기열 비어 있음Completed (100%)Cancel'; options |
| `case_17_method_parameter_followup` | `PASS` | `Continuation state` | ws=Connected; clarify=0; confirm=0; result=Ethanolamine::orbital_preview; viz={"orbital": true, "density": false, "esp": false}; timeout=False; terminal_timeout=False; last='계산 완료대기열 비어 있음Completed (100%)Cancel'; options |
| `case_18_new_session_pronoun_clarify` | `PASS` | `Clarification UI` | ws=Connected; clarify=1; confirm=0; result=-::-; viz={}; timeout=True; terminal_timeout=False; last='계산할 분자를 골라 주세요 / Choose a molecule to compute입력 내용만으로는 분자가 특정되지 않아 먼저 후보를 제안합니다.분자를 선택해 주세요 / Choose a molecule물 — 3 at |
| `case_19_new_session_basis_followup` | `PASS` | `Prompt routing` | ws=Connected; clarify=1; confirm=0; result=-::-; viz={}; timeout=False; terminal_timeout=False; last='설명 기반 후보를 확인해 주세요 / Confirm candidates from the description입력하신 설명을 기반으로 MolChat에서 구조화한 후보를 정리했습니다.분자를 선택해 주세요 / Choos |
| `case_20_red_team_input` | `PASS` | `Prompt routing` | ws=Connected; clarify=1; confirm=0; result=-::-; viz={}; timeout=False; terminal_timeout=False; last='분자 이름을 조금 더 구체적으로 알려주세요 / Clarify the molecule현재 입력만으로는 하나의 분자를 확정하지 못했습니다. 분자 이름이나 SMILES를 직접 입력해 주세요.분자를 선택해 주세요 / C |

## Residual Notes

- This report reflects the live stack used for the audit: `QCViz :8817`, `MolChat UI :3000/molchat`, `MolChat API :8333`.
- The audited service path is the browser root `/`; `health` still reports the uvicorn `root-path` setting, but live UI entry for the harness is `/`.
- The browser audit passed without modifying the audit expectations.
