from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = OUT_DIR / "live_case_results.json"
PRE_HEALTH_PATH = OUT_DIR / "health_snapshot_before_cases.json"
POST_HEALTH_PATH = OUT_DIR / "health_snapshot_after_cases.json"

QCVIZ_URL = os.getenv("QCVIZ_URL", "http://127.0.0.1:8817/")
QCVIZ_HEALTH_URL = os.getenv("QCVIZ_HEALTH_URL", "http://127.0.0.1:8817/health")
MOLCHAT_UI_URL = os.getenv("MOLCHAT_UI_URL", "http://127.0.0.1:3000/molchat")
MOLCHAT_LIVE_URL = os.getenv("MOLCHAT_LIVE_URL", "http://127.0.0.1:8333/api/v1/health/live")
MOLCHAT_READY_URL = os.getenv("MOLCHAT_READY_URL", "http://127.0.0.1:8333/api/v1/health/ready")


def health_snapshot() -> dict[str, Any]:
    targets = {
        "qcviz_health": QCVIZ_HEALTH_URL,
        "qcviz_ui": QCVIZ_URL,
        "molchat_live": MOLCHAT_LIVE_URL,
        "molchat_ready": MOLCHAT_READY_URL,
        "molchat_ui": MOLCHAT_UI_URL,
    }
    snap: dict[str, Any] = {"timestamp": time.time(), "targets": {}}
    for name, url in targets.items():
        entry: dict[str, Any] = {"url": url}
        try:
            resp = requests.get(url, timeout=10)
            entry["status_code"] = resp.status_code
            entry["ok"] = resp.ok
            entry["text_preview"] = resp.text[:500]
        except Exception as exc:  # pragma: no cover - runtime capture
            entry["ok"] = False
            entry["error"] = str(exc)
        snap["targets"][name] = entry
    return snap


def _flatten(values: list[Any]) -> list[str]:
    out: list[str] = []
    for value in values:
        if isinstance(value, list):
            out.extend(_flatten(value))
        elif value is not None:
            out.append(str(value))
    return out


def _safe_json(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except Exception:
        return str(value)


def _dump_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass
class AuditPage:
    page: Any
    event_log: list[dict[str, Any]]

    def slice_events(self, start: int) -> list[dict[str, Any]]:
        return self.event_log[start:]


def create_audit_page(browser: Any, url: str) -> AuditPage:
    context = browser.new_context(viewport={"width": 1440, "height": 1200})
    page = context.new_page()
    event_log: list[dict[str, Any]] = []

    def push_event(kind: str, payload: dict[str, Any]) -> None:
        event_log.append({"kind": kind, "payload": _safe_json(payload), "at": time.time()})

    page.on("console", lambda msg: push_event("console", {"type": msg.type, "text": msg.text}))
    page.on("pageerror", lambda exc: push_event("pageerror", {"text": str(exc)}))
    page.on(
        "requestfailed",
        lambda req: push_event(
            "requestfailed",
            {
                "url": req.url,
                "method": req.method,
                "failure": req.failure if isinstance(req.failure, str) else (req.failure or {}).get("errorText"),
            },
        ),
    )
    page.on(
        "response",
        lambda resp: push_event(
            "response",
            {"url": resp.url, "status": resp.status, "ok": resp.ok},
        ),
    )
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    return AuditPage(page=page, event_log=event_log)


def qcviz_state(page: Any) -> dict[str, Any]:
    return page.evaluate(
        """
        () => {
          const app = window.QCVizApp || null;
          const store = app ? app.store : null;
          const msgs = Array.from(document.querySelectorAll('.chat-msg')).map((el) => {
            const classes = Array.from(el.classList || []);
            const text = (el.textContent || '').trim();
            return {
              classes,
              text: text.slice(0, 1500),
              isUser: classes.includes('chat-msg--user'),
              isClarify: classes.includes('chat-msg--clarify'),
              isConfirm: classes.includes('chat-msg--confirm'),
            };
          });
          const clarifies = Array.from(document.querySelectorAll('.chat-msg--clarify')).map((card) => {
            const labels = Array.from(card.querySelectorAll('.clarify-field__label')).map((el) => (el.textContent || '').trim());
            const selects = Array.from(card.querySelectorAll('select')).map((sel) =>
              Array.from(sel.options || []).map((opt) => (opt.value || opt.textContent || '').trim())
            );
            const textInputs = Array.from(card.querySelectorAll('input[type="text"], textarea')).map((el) => ({
              fieldId: el.getAttribute('data-field-id') || '',
              value: el.value || '',
              placeholder: el.placeholder || '',
            }));
            return {
              text: (card.textContent || '').trim().slice(0, 2000),
              labels,
              selects,
              textInputs,
            };
          });
          const confirms = Array.from(document.querySelectorAll('.chat-msg--confirm')).map((card) => ({
            text: (card.textContent || '').trim().slice(0, 2000),
          }));
          const activeResult = store && store.activeResult ? store.activeResult : null;
          const activeSummary = activeResult ? {
            structure_query: activeResult.structure_query || '',
            structure_name: activeResult.structure_name || '',
            job_type: activeResult.job_type || '',
            analysis_bundle: Array.isArray(activeResult.analysis_bundle) ? activeResult.analysis_bundle : [],
            visualization_available: (activeResult.visualization && activeResult.visualization.available) || {},
            orbital: activeResult.orbital || '',
            esp_preset: activeResult.esp_preset || '',
          } : null;
          const jobs = store && store.jobsById ? Object.values(store.jobsById).map((job) => ({
            job_id: job.job_id || '',
            status: job.status || '',
            payload_job_type: (job.payload && job.payload.job_type) || '',
            payload_structure_query: (job.payload && job.payload.structure_query) || '',
          })) : [];
          return {
            title: document.title,
            ws_label: (document.querySelector('#wsStatus .ws-status__label')?.textContent || '').trim(),
            dom_count: msgs.length,
            clarify_count: clarifies.length,
            confirm_count: confirms.length,
            chat_text: (document.querySelector('#chatMessages')?.textContent || '').trim().slice(0, 5000),
            messages: msgs,
            clarifies,
            confirms,
            active_result: activeSummary,
            active_result_sig: activeSummary ? JSON.stringify(activeSummary) : '',
            active_job_id: store ? (store.activeJobId || '') : '',
            jobs_count: jobs.length,
            jobs,
            session_id: store ? (store.sessionId || '') : '',
            last_user_input: store ? (store.lastUserInput || '') : '',
          };
        }
        """
    )


def wait_for_qcviz_ready(page: Any) -> None:
    page.wait_for_selector("#chatInput", timeout=30000)
    try:
        page.wait_for_function(
            "() => (document.querySelector('#wsStatus .ws-status__label')?.textContent || '').toLowerCase().includes('connected')",
            timeout=20000,
        )
    except PlaywrightTimeoutError:
        page.wait_for_timeout(2000)


def wait_for_non_user_followup(page: Any, baseline: dict[str, Any], timeout_ms: int) -> dict[str, Any]:
    timed_out = False
    try:
        page.wait_for_function(
            """
            (prev) => {
              const msgs = Array.from(document.querySelectorAll('.chat-msg'));
              const clarifyCount = document.querySelectorAll('.chat-msg--clarify').length;
              const confirmCount = document.querySelectorAll('.chat-msg--confirm').length;
              if (clarifyCount > prev.clarify_count || confirmCount > prev.confirm_count) return true;
              if (msgs.length > prev.dom_count) {
                const last = msgs[msgs.length - 1];
                return !last.classList.contains('chat-msg--user');
              }
              const app = window.QCVizApp;
              const store = app && app.store ? app.store : null;
              const active = store && store.activeResult ? store.activeResult : null;
              const summary = active ? JSON.stringify({
                structure_query: active.structure_query || '',
                structure_name: active.structure_name || '',
                job_type: active.job_type || '',
                analysis_bundle: Array.isArray(active.analysis_bundle) ? active.analysis_bundle : [],
                visualization_available: (active.visualization && active.visualization.available) || {},
                orbital: active.orbital || '',
                esp_preset: active.esp_preset || '',
              }) : '';
              const jobsCount = store && store.jobsById ? Object.keys(store.jobsById).length : 0;
              return summary !== prev.active_result_sig || jobsCount > prev.jobs_count;
            }
            """,
            arg=baseline,
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        timed_out = True
    state = qcviz_state(page)
    if timed_out:
        state["_timeout_waiting_for_followup"] = True
    return state


def send_prompt(page: Any, prompt: str, timeout_ms: int = 90000) -> dict[str, Any]:
    wait_for_qcviz_ready(page)
    page.locator("#chatInput").fill(prompt)
    page.wait_for_function(
        "() => { const btn = document.querySelector('#chatSend'); return btn && !btn.disabled; }",
        timeout=10000,
    )
    page.locator("#chatSend").click()
    page.wait_for_timeout(300)
    baseline = qcviz_state(page)
    return wait_for_non_user_followup(page, baseline, timeout_ms=timeout_ms)


def wait_for_terminal_state(page: Any, baseline: dict[str, Any], timeout_ms: int) -> dict[str, Any]:
    if baseline.get("clarify_count", 0) or baseline.get("confirm_count", 0):
        return baseline
    timed_out = False
    try:
        page.wait_for_function(
            """
            (prev) => {
              const clarifyCount = document.querySelectorAll('.chat-msg--clarify').length;
              const confirmCount = document.querySelectorAll('.chat-msg--confirm').length;
              if (clarifyCount > prev.clarify_count || confirmCount > prev.confirm_count) return true;
              const app = window.QCVizApp;
              const store = app && app.store ? app.store : null;
              if (!store) return false;
              const jobsById = store.jobsById || {};
              const terminalStates = ['completed', 'failed', 'cancelled'];
              const prevJobs = Array.isArray(prev.jobs) ? prev.jobs : [];
              const prevStatusById = Object.fromEntries(
                prevJobs
                  .filter((job) => job && job.job_id)
                  .map((job) => [job.job_id, String(job.status || '').toLowerCase()])
              );
              if (prev.active_job_id && jobsById[prev.active_job_id]) {
                const status = String(jobsById[prev.active_job_id].status || '').toLowerCase();
                const prevStatus = String(prevStatusById[prev.active_job_id] || '').toLowerCase();
                if (terminalStates.includes(status) && !terminalStates.includes(prevStatus)) return true;
              } else {
                const terminalJob = Object.values(jobsById).some((job) => {
                  const jobId = String(job.job_id || '');
                  const status = String(job.status || '').toLowerCase();
                  const prevStatus = String(prevStatusById[jobId] || '').toLowerCase();
                  return terminalStates.includes(status) && !terminalStates.includes(prevStatus);
                });
                if (terminalJob) return true;
              }
              return false;
            }
            """,
            arg=baseline,
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        timed_out = True
    state = qcviz_state(page)
    if timed_out:
        state["_timeout_waiting_for_terminal"] = True
    return state


def submit_clarify(page: Any, timeout_ms: int = 90000, terminal: bool = False) -> dict[str, Any]:
    card = page.locator(".chat-msg--clarify").last
    card.locator(".clarify-btn--primary").click()
    page.wait_for_timeout(300)
    baseline = qcviz_state(page)
    state = wait_for_non_user_followup(page, baseline, timeout_ms=timeout_ms)
    if terminal:
        state = wait_for_terminal_state(page, state, timeout_ms=timeout_ms)
    return state


def send_prompt_terminal(page: Any, prompt: str, timeout_ms: int = 120000) -> dict[str, Any]:
    state = send_prompt(page, prompt, timeout_ms=timeout_ms)
    return wait_for_terminal_state(page, state, timeout_ms=timeout_ms)


def summarize_actual(state: dict[str, Any]) -> str:
    result = state.get("active_result") or {}
    flat_options = _flatten([c.get("selects", []) for c in state.get("clarifies", [])])
    last_msg = state.get("messages", [])[-1] if state.get("messages") else {}
    return (
        f"ws={state.get('ws_label') or 'n/a'}; "
        f"clarify={state.get('clarify_count', 0)}; "
        f"confirm={state.get('confirm_count', 0)}; "
        f"result={result.get('structure_query') or '-'}::{result.get('job_type') or '-'}; "
        f"viz={json.dumps(result.get('visualization_available') or {}, ensure_ascii=False)}; "
        f"timeout={bool(state.get('_timeout_waiting_for_followup'))}; "
        f"terminal_timeout={bool(state.get('_timeout_waiting_for_terminal'))}; "
        f"last='{str(last_msg.get('text') or '')[:220]}'; "
        f"options={flat_options[:8]}"
    )


def write_case_artifacts(case_id: str, audit_page: AuditPage, state: dict[str, Any], start_event_idx: int) -> list[str]:
    slug = case_id.lower().replace(" ", "_")
    screenshot = OUT_DIR / f"{slug}.png"
    state_path = OUT_DIR / f"{slug}_state.json"
    audit_page.page.screenshot(path=str(screenshot), full_page=True)
    payload = {
        "state": state,
        "events": audit_page.slice_events(start_event_idx),
    }
    _dump_json(state_path, payload)
    return [str(screenshot), str(state_path)]


def has_text(state: dict[str, Any], needle: str) -> bool:
    return needle.lower() in str(state.get("chat_text") or "").lower()


def has_no_raw_option(state: dict[str, Any], raw: str) -> bool:
    options = [opt.strip().lower() for opt in _flatten([c.get("selects", []) for c in state.get("clarifies", [])])]
    return raw.strip().lower() not in options


def active_structure_is(state: dict[str, Any], name: str) -> bool:
    result = state.get("active_result") or {}
    return (result.get("structure_query") or "").strip().lower() == name.strip().lower()


def viz_has(state: dict[str, Any], key: str) -> bool:
    result = state.get("active_result") or {}
    available = result.get("visualization_available") or {}
    return bool(available.get(key))


def latest_clarify_text(state: dict[str, Any]) -> str:
    clarifies = state.get("clarifies") or []
    return str(clarifies[-1]["text"] if clarifies else "")


def case_record(
    *,
    case_id: str,
    precondition: str,
    prompt_sequence: list[str],
    expected: str,
    actual_state: dict[str, Any],
    status: str,
    suspected_layer: str,
    evidence_paths: list[str],
    notes: str = "",
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "precondition": precondition,
        "prompt_sequence": prompt_sequence,
        "expected": expected,
        "actual": summarize_actual(actual_state),
        "status": status,
        "suspected_layer": suspected_layer,
        "evidence_paths": evidence_paths,
        "notes": notes,
    }


def run() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _dump_json(PRE_HEALTH_PATH, health_snapshot())
    results: list[dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            # Case 1: QCViz boot
            qcviz_page = create_audit_page(browser, QCVIZ_URL)
            start_idx = len(qcviz_page.event_log)
            wait_for_qcviz_ready(qcviz_page.page)
            state = qcviz_state(qcviz_page.page)
            evidence = write_case_artifacts("case_01_qcviz_boot", qcviz_page, state, start_idx)
            results.append(
                case_record(
                    case_id="case_01_qcviz_boot",
                    precondition="QCViz restarted from a.sh",
                    prompt_sequence=[],
                    expected="/health 200 and root UI loads",
                    actual_state=state,
                    status="PASS" if state.get("title") == "QCViz-MCP v3" else "FAIL",
                    suspected_layer="Boot",
                    evidence_paths=evidence,
                )
            )
            qcviz_page.page.context.close()

            # Case 2: MolChat availability
            molchat_page = create_audit_page(browser, MOLCHAT_UI_URL)
            start_idx = len(molchat_page.event_log)
            molchat_state = {
                "title": molchat_page.page.title(),
                "chat_text": molchat_page.page.locator("body").inner_text(timeout=10000),
                "clarify_count": 0,
                "confirm_count": 0,
                "messages": [],
                "active_result": None,
                "ws_label": "",
            }
            evidence = write_case_artifacts("case_02_molchat_availability", molchat_page, molchat_state, start_idx)
            backend_ok = requests.get(MOLCHAT_LIVE_URL, timeout=10).status_code == 200
            status = "PASS" if backend_ok and "MolChat" in molchat_state["title"] else "FAIL"
            results.append(
                case_record(
                    case_id="case_02_molchat_availability",
                    precondition="MolChat restarted on local 3000/8333 stack",
                    prompt_sequence=[],
                    expected="Frontend responds and backend live health returns 200",
                    actual_state=molchat_state,
                    status=status,
                    suspected_layer="Boot",
                    evidence_paths=evidence,
                    notes=f"backend_live_ok={backend_ok}",
                )
            )
            molchat_page.page.context.close()

            def single_prompt_case(
                case_id: str,
                prompt: str,
                expected: str,
                evaluator: Callable[[dict[str, Any]], tuple[str, str, str]],
                timeout_ms: int = 110000,
                terminal: bool = False,
            ) -> None:
                audit = create_audit_page(browser, QCVIZ_URL)
                wait_for_qcviz_ready(audit.page)
                start_idx = len(audit.event_log)
                state = send_prompt_terminal(audit.page, prompt, timeout_ms=timeout_ms) if terminal else send_prompt(audit.page, prompt, timeout_ms=timeout_ms)
                status, layer, notes = evaluator(state)
                evidence = write_case_artifacts(case_id, audit, state, start_idx)
                results.append(
                    case_record(
                        case_id=case_id,
                        precondition="Fresh QCViz session",
                        prompt_sequence=[prompt],
                        expected=expected,
                        actual_state=state,
                        status=status,
                        suspected_layer=layer,
                        evidence_paths=evidence,
                        notes=notes,
                    )
                )
                audit.page.context.close()

            single_prompt_case(
                "case_03_benzene_homo",
                "benzene HOMO 보여줘",
                "Direct compute completes for benzene HOMO",
                lambda state: (
                    ("PASS", "Job lifecycle", "") if active_structure_is(state, "benzene") and viz_has(state, "orbital")
                    else ("FAIL", "Job lifecycle", "")
                ),
                terminal=True,
            )

            single_prompt_case(
                "case_04_acetone_esp",
                "Render ESP map for acetone using ACS preset",
                "Direct ESP computation completes for acetone",
                lambda state: (
                    ("PASS", "Job lifecycle", "") if active_structure_is(state, "acetone") and viz_has(state, "esp")
                    else ("FAIL", "Job lifecycle", "")
                ),
                terminal=True,
            )

            single_prompt_case(
                "case_05_water_optimize",
                "water optimize geometry",
                "Geometry optimization completes for water",
                lambda state: (
                    ("PASS", "Job lifecycle", "") if active_structure_is(state, "water")
                    else ("FAIL", "Job lifecycle", "")
                ),
                terminal=True,
            )

            single_prompt_case(
                "case_06_composition_clarification",
                "benzene and toluene HOMO",
                "Composition clarification instead of auto compute",
                lambda state: (
                    ("PASS", "Prompt routing", "") if state.get("clarify_count", 0) >= 1 and not state.get("active_result")
                    else ("FAIL", "Prompt routing", latest_clarify_text(state))
                ),
                timeout_ms=30000,
            )

            single_prompt_case(
                "case_07_homo_concept_chat",
                "HOMO가 뭐야?",
                "Chat-only concept explanation without compute or clarify",
                lambda state: (
                    ("PASS", "Prompt routing", "") if state.get("clarify_count", 0) == 0 and has_text(state, "homo")
                    else ("FAIL", "Prompt routing", "")
                ),
                timeout_ms=30000,
            )

            single_prompt_case(
                "case_08_mea_chat_grounded",
                "MEA 알아?",
                "Semantic grounded direct answer mentioning Ethanolamine",
                lambda state: (
                    ("PASS", "Semantic grounding", "") if state.get("clarify_count", 0) == 0 and has_text(state, "ethanolamine")
                    else ("FAIL", "Semantic grounding", latest_clarify_text(state))
                ),
                timeout_ms=40000,
            )

            single_prompt_case(
                "case_09_mea_compute_requires_grounding",
                "MEA HOMO 보여줘",
                "Grounding clarification, without raw MEA option",
                lambda state: (
                    ("PASS", "Semantic grounding", "") if state.get("clarify_count", 0) >= 1 and has_no_raw_option(state, "MEA")
                    else ("FAIL", "Semantic grounding", latest_clarify_text(state))
                ),
                timeout_ms=40000,
            )

            single_prompt_case(
                "case_10_dma_ambiguous",
                "DMA 알아?",
                "Ambiguous clarification for DMA",
                lambda state: (
                    ("PASS", "Semantic grounding", "") if state.get("clarify_count", 0) >= 1
                    else ("FAIL", "Semantic grounding", latest_clarify_text(state))
                ),
                timeout_ms=40000,
            )

            # Case 11: clarification then submit
            audit = create_audit_page(browser, QCVIZ_URL)
            wait_for_qcviz_ready(audit.page)
            start_idx = len(audit.event_log)
            first = send_prompt(audit.page, "main component of TNT HOMO 보여줘", timeout_ms=50000)
            notes = ""
            if first.get("clarify_count", 0) >= 1:
                second = submit_clarify(audit.page, timeout_ms=120000, terminal=True)
                state = second
                notes = "clarification_submitted=true"
            else:
                state = first
                notes = "clarification_submitted=false"
            evidence = write_case_artifacts("case_11_tnt_grounded_compute", audit, state, start_idx)
            status = "PASS" if has_text(state, "trinitrotoluene") or "trinitrotoluene" in json.dumps(state.get("active_result") or {}, ensure_ascii=False).lower() else "FAIL"
            results.append(
                case_record(
                    case_id="case_11_tnt_grounded_compute",
                    precondition="Fresh QCViz session",
                    prompt_sequence=["main component of TNT HOMO 보여줘"],
                    expected="Grounded candidate flow proceeds without second composition clarification",
                    actual_state=state,
                    status=status,
                    suspected_layer="Semantic grounding" if status == "FAIL" else "Job lifecycle",
                    evidence_paths=evidence,
                    notes=notes,
                )
            )
            audit.page.context.close()

            # Cases 12-17 share one session
            audit = create_audit_page(browser, QCVIZ_URL)
            wait_for_qcviz_ready(audit.page)

            def record_shared(case_id: str, prompt_sequence: list[str], expected: str, state: dict[str, Any], start_idx: int, status: str, layer: str, notes: str = "") -> None:
                evidence = write_case_artifacts(case_id, audit, state, start_idx)
                results.append(
                    case_record(
                        case_id=case_id,
                        precondition="Shared QCViz session after semantic chat grounding",
                        prompt_sequence=prompt_sequence,
                        expected=expected,
                        actual_state=state,
                        status=status,
                        suspected_layer=layer,
                        evidence_paths=evidence,
                        notes=notes,
                    )
                )

            start_idx = len(audit.event_log)
            state_12a = send_prompt(audit.page, "MEA 알아?", timeout_ms=40000)
            state_12b = send_prompt_terminal(audit.page, "ㅇㅇ 그거 HOMO 보여줘", timeout_ms=120000)
            status = "PASS" if active_structure_is(state_12b, "Ethanolamine") and viz_has(state_12b, "orbital") else "FAIL"
            record_shared(
                "case_12_pronoun_homo_followup",
                ["MEA 알아?", "ㅇㅇ 그거 HOMO 보여줘"],
                "Same-session pronoun follow-up reuses Ethanolamine and computes HOMO",
                state_12b,
                start_idx,
                status,
                "Continuation state" if status == "FAIL" else "Job lifecycle",
            )

            start_idx = len(audit.event_log)
            state_13 = send_prompt_terminal(audit.page, "그거 ESP도", timeout_ms=120000)
            status = "PASS" if active_structure_is(state_13, "Ethanolamine") and viz_has(state_13, "esp") else "FAIL"
            record_shared(
                "case_13_pronoun_esp_followup",
                ["그거 ESP도"],
                "Same-session pronoun follow-up adds ESP for Ethanolamine",
                state_13,
                start_idx,
                status,
                "Continuation state" if status == "FAIL" else "Job lifecycle",
            )

            start_idx = len(audit.event_log)
            state_14 = send_prompt_terminal(audit.page, "ESP도", timeout_ms=120000)
            status = "PASS" if active_structure_is(state_14, "Ethanolamine") else "FAIL"
            record_shared(
                "case_14_short_esp_followup",
                ["ESP도"],
                "Short same-session ESP follow-up stays on last structure",
                state_14,
                start_idx,
                status,
                "Continuation state",
            )

            start_idx = len(audit.event_log)
            state_15 = send_prompt_terminal(audit.page, "이번엔 LUMO", timeout_ms=120000)
            status = "PASS" if active_structure_is(state_15, "Ethanolamine") and viz_has(state_15, "orbital") else "FAIL"
            record_shared(
                "case_15_lumo_followup",
                ["이번엔 LUMO"],
                "Same-session LUMO follow-up stays on last structure",
                state_15,
                start_idx,
                status,
                "Continuation state",
            )

            start_idx = len(audit.event_log)
            state_16 = send_prompt_terminal(audit.page, "basis만 더 키워봐", timeout_ms=70000)
            status = "PASS" if active_structure_is(state_16, "Ethanolamine") and state_16.get("clarify_count", 0) == 0 else "FAIL"
            record_shared(
                "case_16_basis_parameter_followup",
                ["basis만 더 키워봐"],
                "Parameter-only follow-up should not lose target structure",
                state_16,
                start_idx,
                status,
                "Prompt routing" if status == "FAIL" else "Continuation state",
            )

            start_idx = len(audit.event_log)
            state_17 = send_prompt_terminal(audit.page, "method를 B3LYP로 바꿔", timeout_ms=70000)
            status = "PASS" if active_structure_is(state_17, "Ethanolamine") and state_17.get("clarify_count", 0) == 0 else "FAIL"
            record_shared(
                "case_17_method_parameter_followup",
                ["method를 B3LYP로 바꿔"],
                "Parameter-only method follow-up should not lose target structure",
                state_17,
                start_idx,
                status,
                "Prompt routing" if status == "FAIL" else "Continuation state",
            )
            audit.page.context.close()

            single_prompt_case(
                "case_18_new_session_pronoun_clarify",
                "그거 HOMO 보여줘",
                "New-session pronoun request clarifies without exposing raw pronoun option",
                lambda state: (
                    ("PASS", "Clarification UI", "") if state.get("clarify_count", 0) >= 1 and has_no_raw_option(state, "그거")
                    else ("FAIL", "Clarification UI", latest_clarify_text(state))
                ),
                timeout_ms=40000,
            )

            single_prompt_case(
                "case_19_new_session_basis_followup",
                "basis 더 키워",
                "New-session parameter-only follow-up asks continuation-targeting clarification",
                lambda state: (
                    ("PASS", "Prompt routing", "") if state.get("clarify_count", 0) >= 1 and has_no_raw_option(state, "basis 더 키워")
                    else ("FAIL", "Prompt routing", latest_clarify_text(state))
                ),
                timeout_ms=40000,
            )

            single_prompt_case(
                "case_20_red_team_input",
                "\"; DROP TABLE molecules; --\nTraceback (most recent call last):\n유니코드깨짐Ω≈ç√∫˜µ≤≥÷",
                "Unsafe input is handled without app crash",
                lambda state: (
                    ("PASS", "Prompt routing", "") if state.get("ws_label", "").lower() == "connected"
                    else ("FAIL", "Prompt routing", latest_clarify_text(state))
                ),
                timeout_ms=40000,
            )

        finally:
            browser.close()

    post = health_snapshot()
    _dump_json(POST_HEALTH_PATH, post)

    summary = {
        "generated_at": time.time(),
        "counts": {
            "pass": sum(1 for item in results if item["status"] == "PASS"),
            "fail": sum(1 for item in results if item["status"] == "FAIL"),
            "blocked": sum(1 for item in results if item["status"] == "BLOCKED"),
        },
        "results": results,
        "pre_health_snapshot": str(PRE_HEALTH_PATH),
        "post_health_snapshot": str(POST_HEALTH_PATH),
    }
    _dump_json(RESULTS_PATH, summary)
    print(json.dumps(summary["counts"], ensure_ascii=False))
    print(str(RESULTS_PATH))


if __name__ == "__main__":
    run()
