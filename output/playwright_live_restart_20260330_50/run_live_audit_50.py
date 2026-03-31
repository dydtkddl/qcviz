from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
BASE_SCRIPT = ROOT / "output" / "playwright_live_restart_20260330" / "run_live_audit.py"
OUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = OUT_DIR / "live_case_results_50.json"
PRE_HEALTH_PATH = OUT_DIR / "health_snapshot_before_cases_50.json"
POST_HEALTH_PATH = OUT_DIR / "health_snapshot_after_cases_50.json"


def _load_base_module():
    spec = importlib.util.spec_from_file_location("base_live_audit", BASE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load base audit module from {BASE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.OUT_DIR = OUT_DIR
    module.RESULTS_PATH = RESULTS_PATH
    module.PRE_HEALTH_PATH = PRE_HEALTH_PATH
    module.POST_HEALTH_PATH = POST_HEALTH_PATH
    return module


audit = _load_base_module()


def _dump_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_results() -> dict[str, Any]:
    return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))


def _job_type_is(state: dict[str, Any], value: str) -> bool:
    return str((state.get("active_result") or {}).get("job_type") or "").strip().lower() == value.strip().lower()


def _safe_chat_reply(state: dict[str, Any], *, needle: str | None = None) -> bool:
    if state.get("clarify_count", 0) != 0:
        return False
    if state.get("active_result"):
        return False
    if not str(state.get("chat_text") or "").strip():
        return False
    if needle:
        return audit.has_text(state, needle)
    return True


def _clarifies_without_raw(state: dict[str, Any], raw: str) -> bool:
    return state.get("clarify_count", 0) >= 1 and audit.has_no_raw_option(state, raw)


def _record_case(
    results: list[dict[str, Any]],
    *,
    case_id: str,
    precondition: str,
    prompt_sequence: list[str],
    expected: str,
    state: dict[str, Any],
    start_idx: int,
    audit_page: Any,
    status: str,
    layer: str,
    notes: str = "",
) -> None:
    evidence = audit.write_case_artifacts(case_id, audit_page, state, start_idx)
    results.append(
        audit.case_record(
            case_id=case_id,
            precondition=precondition,
            prompt_sequence=prompt_sequence,
            expected=expected,
            actual_state=state,
            status=status,
            suspected_layer=layer,
            evidence_paths=evidence,
            notes=notes,
        )
    )


def _single_prompt_case(
    browser: Any,
    results: list[dict[str, Any]],
    *,
    case_id: str,
    prompt: str,
    expected: str,
    evaluator: Callable[[dict[str, Any]], tuple[str, str, str]],
    timeout_ms: int = 40000,
    terminal: bool = False,
) -> None:
    audit_page = audit.create_audit_page(browser, audit.QCVIZ_URL)
    try:
        audit.wait_for_qcviz_ready(audit_page.page)
        start_idx = len(audit_page.event_log)
        state = audit.send_prompt_terminal(audit_page.page, prompt, timeout_ms=timeout_ms) if terminal else audit.send_prompt(
            audit_page.page, prompt, timeout_ms=timeout_ms
        )
        status, layer, notes = evaluator(state)
        _record_case(
            results,
            case_id=case_id,
            precondition="Fresh QCViz session",
            prompt_sequence=[prompt],
            expected=expected,
            state=state,
            start_idx=start_idx,
            audit_page=audit_page,
            status=status,
            layer=layer,
            notes=notes,
        )
    finally:
        audit_page.page.context.close()


def _run_shared_followup_cases(browser: Any, results: list[dict[str, Any]]) -> None:
    def record_shared(
        *,
        case_id: str,
        prompt_sequence: list[str],
        expected: str,
        state: dict[str, Any],
        start_idx: int,
        audit_page: Any,
        status: str,
        layer: str,
        notes: str = "",
    ) -> None:
        _record_case(
            results,
            case_id=case_id,
            precondition="Shared QCViz session",
            prompt_sequence=prompt_sequence,
            expected=expected,
            state=state,
            start_idx=start_idx,
            audit_page=audit_page,
            status=status,
            layer=layer,
            notes=notes,
        )

    # Shared session A
    audit_page = audit.create_audit_page(browser, audit.QCVIZ_URL)
    try:
        audit.wait_for_qcviz_ready(audit_page.page)

        start_idx = len(audit_page.event_log)
        audit.send_prompt_terminal(audit_page.page, "acetone ESP map 보여줘", timeout_ms=120000)
        state = audit.send_prompt_terminal(audit_page.page, "ACS preset으로 다시", timeout_ms=120000)
        status = "PASS" if audit.active_structure_is(state, "acetone") and audit.viz_has(state, "esp") else "FAIL"
        record_shared(
            case_id="case_39_same_session_acs_preset",
            prompt_sequence=["acetone ESP map 보여줘", "ACS preset으로 다시"],
            expected="Same-session preset-only follow-up reuses acetone and keeps ESP visualization",
            state=state,
            start_idx=start_idx,
            audit_page=audit_page,
            status=status,
            layer="Prompt routing" if status == "FAIL" else "Job lifecycle",
        )

        start_idx = len(audit_page.event_log)
        audit.send_prompt_terminal(audit_page.page, "single point energy for pyridine", timeout_ms=120000)
        state = audit.send_prompt_terminal(audit_page.page, "charge 보여줘", timeout_ms=120000)
        status = "PASS" if audit.active_structure_is(state, "pyridine") and _job_type_is(state, "partial_charges") else "FAIL"
        record_shared(
            case_id="case_40_same_session_charge_followup",
            prompt_sequence=["single point energy for pyridine", "charge 보여줘"],
            expected="Same-session charge follow-up reuses pyridine and routes to partial charges",
            state=state,
            start_idx=start_idx,
            audit_page=audit_page,
            status=status,
            layer="Continuation state" if status == "FAIL" else "Job lifecycle",
        )
    finally:
        audit_page.page.context.close()

    # Shared session B
    audit_page = audit.create_audit_page(browser, audit.QCVIZ_URL)
    try:
        audit.wait_for_qcviz_ready(audit_page.page)

        start_idx = len(audit_page.event_log)
        audit.send_prompt_terminal(audit_page.page, "analyze glycine geometry", timeout_ms=120000)
        state = audit.send_prompt_terminal(audit_page.page, "Optimize it too", timeout_ms=120000)
        status = "PASS" if audit.active_structure_is(state, "glycine") and _job_type_is(state, "geometry_optimization") else "FAIL"
        record_shared(
            case_id="case_41_same_session_optimize_followup",
            prompt_sequence=["analyze glycine geometry", "Optimize it too"],
            expected="Optimization follow-up reuses glycine and routes to geometry optimization",
            state=state,
            start_idx=start_idx,
            audit_page=audit_page,
            status=status,
            layer="Continuation state" if status == "FAIL" else "Job lifecycle",
        )

        start_idx = len(audit_page.event_log)
        audit.send_prompt_terminal(audit_page.page, "single point energy for ethanol", timeout_ms=120000)
        state = audit.send_prompt_terminal(audit_page.page, "HOMO 보여줘", timeout_ms=120000)
        status = "PASS" if audit.active_structure_is(state, "ethanol") and audit.viz_has(state, "orbital") else "FAIL"
        record_shared(
            case_id="case_42_same_session_homo_followup",
            prompt_sequence=["single point energy for ethanol", "HOMO 보여줘"],
            expected="HOMO follow-up reuses ethanol and produces orbital visualization",
            state=state,
            start_idx=start_idx,
            audit_page=audit_page,
            status=status,
            layer="Continuation state" if status == "FAIL" else "Job lifecycle",
        )
    finally:
        audit_page.page.context.close()

    # Shared session C
    audit_page = audit.create_audit_page(browser, audit.QCVIZ_URL)
    try:
        audit.wait_for_qcviz_ready(audit_page.page)

        start_idx = len(audit_page.event_log)
        audit.send_prompt_terminal(audit_page.page, "benzene HOMO 보여줘", timeout_ms=120000)
        state = audit.send_prompt_terminal(audit_page.page, "LUMO도", timeout_ms=120000)
        status = "PASS" if audit.active_structure_is(state, "benzene") and audit.viz_has(state, "orbital") else "FAIL"
        record_shared(
            case_id="case_43_same_session_lumo_followup",
            prompt_sequence=["benzene HOMO 보여줘", "LUMO도"],
            expected="Short LUMO follow-up reuses benzene and stays on orbital visualization",
            state=state,
            start_idx=start_idx,
            audit_page=audit_page,
            status=status,
            layer="Continuation state" if status == "FAIL" else "Job lifecycle",
        )

        start_idx = len(audit_page.event_log)
        audit.send_prompt_terminal(audit_page.page, "single point energy for acetone", timeout_ms=120000)
        state = audit.send_prompt_terminal(audit_page.page, "charge도", timeout_ms=120000)
        status = "PASS" if audit.active_structure_is(state, "acetone") and _job_type_is(state, "partial_charges") else "FAIL"
        record_shared(
            case_id="case_44_same_session_acetone_charge_followup",
            prompt_sequence=["single point energy for acetone", "charge도"],
            expected="Charge follow-up reuses acetone and routes to partial charges",
            state=state,
            start_idx=start_idx,
            audit_page=audit_page,
            status=status,
            layer="Continuation state" if status == "FAIL" else "Job lifecycle",
        )
    finally:
        audit_page.page.context.close()

    # Shared session D
    audit_page = audit.create_audit_page(browser, audit.QCVIZ_URL)
    try:
        audit.wait_for_qcviz_ready(audit_page.page)

        start_idx = len(audit_page.event_log)
        audit.send_prompt(audit_page.page, "MEA 알아?", timeout_ms=40000)
        state = audit.send_prompt_terminal(audit_page.page, "그거 HOMO 보여줘", timeout_ms=120000)
        status = "PASS" if audit.active_structure_is(state, "Ethanolamine") and audit.viz_has(state, "orbital") else "FAIL"
        record_shared(
            case_id="case_45_same_session_mea_pronoun_homo",
            prompt_sequence=["MEA 알아?", "그거 HOMO 보여줘"],
            expected="Pronoun follow-up reuses Ethanolamine and computes HOMO",
            state=state,
            start_idx=start_idx,
            audit_page=audit_page,
            status=status,
            layer="Continuation state" if status == "FAIL" else "Job lifecycle",
        )

        start_idx = len(audit_page.event_log)
        state = audit.send_prompt_terminal(audit_page.page, "그거 ESP도", timeout_ms=120000)
        status = "PASS" if audit.active_structure_is(state, "Ethanolamine") and audit.viz_has(state, "esp") else "FAIL"
        record_shared(
            case_id="case_46_same_session_mea_pronoun_esp",
            prompt_sequence=["그거 ESP도"],
            expected="Pronoun ESP follow-up reuses Ethanolamine and computes ESP",
            state=state,
            start_idx=start_idx,
            audit_page=audit_page,
            status=status,
            layer="Continuation state" if status == "FAIL" else "Job lifecycle",
        )

        start_idx = len(audit_page.event_log)
        state = audit.send_prompt_terminal(audit_page.page, "basis만 더 키워봐", timeout_ms=90000)
        status = "PASS" if audit.active_structure_is(state, "Ethanolamine") and state.get("clarify_count", 0) == 0 else "FAIL"
        record_shared(
            case_id="case_47_same_session_basis_followup",
            prompt_sequence=["basis만 더 키워봐"],
            expected="Basis-only follow-up keeps the current target structure",
            state=state,
            start_idx=start_idx,
            audit_page=audit_page,
            status=status,
            layer="Prompt routing" if status == "FAIL" else "Continuation state",
        )

        start_idx = len(audit_page.event_log)
        state = audit.send_prompt_terminal(audit_page.page, "method를 PBE0로 바꿔", timeout_ms=90000)
        status = "PASS" if audit.active_structure_is(state, "Ethanolamine") and state.get("clarify_count", 0) == 0 else "FAIL"
        record_shared(
            case_id="case_48_same_session_method_followup",
            prompt_sequence=["method를 PBE0로 바꿔"],
            expected="Method-only follow-up keeps the current target structure",
            state=state,
            start_idx=start_idx,
            audit_page=audit_page,
            status=status,
            layer="Prompt routing" if status == "FAIL" else "Continuation state",
        )
    finally:
        audit_page.page.context.close()


def run() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Reuse the validated 20-case baseline first.
    audit.run()
    summary = _load_results()
    results: list[dict[str, Any]] = list(summary.get("results") or [])

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            extra_single_cases = [
                (
                    "case_21_methane_homo",
                    "methane HOMO 보여줘",
                    "Direct HOMO compute completes for methane",
                    lambda state: (("PASS", "Job lifecycle", "") if audit.active_structure_is(state, "methane") and audit.viz_has(state, "orbital") else ("FAIL", "Job lifecycle", "")),
                    120000,
                    True,
                ),
                (
                    "case_22_ethanol_esp",
                    "ethanol ESP map 보여줘",
                    "Direct ESP compute completes for ethanol",
                    lambda state: (("PASS", "Job lifecycle", "") if audit.active_structure_is(state, "ethanol") and audit.viz_has(state, "esp") else ("FAIL", "Job lifecycle", "")),
                    120000,
                    True,
                ),
                (
                    "case_23_pyridine_charges",
                    "partial charges for pyridine",
                    "Direct partial charges compute completes for pyridine",
                    lambda state: (("PASS", "Job lifecycle", "") if audit.active_structure_is(state, "pyridine") and _job_type_is(state, "partial_charges") else ("FAIL", "Job lifecycle", "")),
                    120000,
                    True,
                ),
                (
                    "case_24_glycine_optimize",
                    "glycine optimize geometry",
                    "Geometry optimization completes for glycine",
                    lambda state: (("PASS", "Job lifecycle", "") if audit.active_structure_is(state, "glycine") and _job_type_is(state, "geometry_optimization") else ("FAIL", "Job lifecycle", "")),
                    120000,
                    True,
                ),
                (
                    "case_25_methanol_homo",
                    "methanol HOMO 보여줘",
                    "Direct HOMO compute completes for methanol",
                    lambda state: (("PASS", "Job lifecycle", "") if audit.active_structure_is(state, "methanol") and audit.viz_has(state, "orbital") else ("FAIL", "Job lifecycle", "")),
                    120000,
                    True,
                ),
                (
                    "case_26_water_partial_charges",
                    "partial charges for water",
                    "Direct partial charges compute completes for water",
                    lambda state: (("PASS", "Job lifecycle", "") if audit.active_structure_is(state, "water") and _job_type_is(state, "partial_charges") else ("FAIL", "Job lifecycle", "")),
                    120000,
                    True,
                ),
                (
                    "case_27_acetic_acid_optimize",
                    "acetic acid optimize geometry",
                    "Geometry optimization completes for acetic acid",
                    lambda state: (("PASS", "Job lifecycle", "") if audit.active_structure_is(state, "acetic acid") and _job_type_is(state, "geometry_optimization") else ("FAIL", "Job lifecycle", "")),
                    120000,
                    True,
                ),
                (
                    "case_28_benzene_single_point",
                    "single point energy for benzene",
                    "Single-point energy completes for benzene",
                    lambda state: (("PASS", "Job lifecycle", "") if audit.active_structure_is(state, "benzene") and _job_type_is(state, "single_point") else ("FAIL", "Job lifecycle", "")),
                    120000,
                    True,
                ),
                (
                    "case_29_acetone_homo",
                    "acetone HOMO 보여줘",
                    "Direct HOMO compute completes for acetone",
                    lambda state: (("PASS", "Job lifecycle", "") if audit.active_structure_is(state, "acetone") and audit.viz_has(state, "orbital") else ("FAIL", "Job lifecycle", "")),
                    120000,
                    True,
                ),
                (
                    "case_30_ethanol_single_point",
                    "single point energy for ethanol",
                    "Single-point energy completes for ethanol",
                    lambda state: (("PASS", "Job lifecycle", "") if audit.active_structure_is(state, "ethanol") and _job_type_is(state, "single_point") else ("FAIL", "Job lifecycle", "")),
                    120000,
                    True,
                ),
                (
                    "case_31_lumo_concept_chat",
                    "What is LUMO?",
                    "Concept question stays in chat-only mode",
                    lambda state: (("PASS", "Prompt routing", "") if _safe_chat_reply(state, needle="lumo") else ("FAIL", "Prompt routing", "")),
                    30000,
                    False,
                ),
                (
                    "case_32_basis_concept_chat",
                    "What is a basis set?",
                    "Basis-set question stays in chat-only mode",
                    lambda state: (("PASS", "Prompt routing", "") if _safe_chat_reply(state, needle="basis") else ("FAIL", "Prompt routing", "")),
                    30000,
                    False,
                ),
                (
                    "case_33_esp_concept_chat",
                    "What is an ESP map?",
                    "ESP concept question stays in chat-only mode",
                    lambda state: (("PASS", "Prompt routing", "") if _safe_chat_reply(state, needle="esp") else ("FAIL", "Prompt routing", "")),
                    30000,
                    False,
                ),
                (
                    "case_34_tnt_chat_grounded",
                    "TNT에 들어가는 주물질이 뭐지?",
                    "TNT semantic chat resolves to trinitrotoluene",
                    lambda state: (("PASS", "Semantic grounding", "") if _safe_chat_reply(state, needle="trinitrotoluene") else ("FAIL", "Semantic grounding", "")),
                    40000,
                    False,
                ),
                (
                    "case_35_aminobutylic_homo_autocorrect",
                    "Aminobutylic acid HOMO 보여줘",
                    "Typo-like structure name autocorrects to gamma-aminobutyric acid and computes HOMO",
                    lambda state: (("PASS", "Structure resolution", "") if audit.active_structure_is(state, "gamma-aminobutyric acid") and audit.viz_has(state, "orbital") else ("FAIL", "Structure resolution", "")),
                    120000,
                    True,
                ),
                (
                    "case_36_gaba_esp",
                    "gamma-aminobutyric acid ESP map 보여줘",
                    "Direct ESP compute completes for gamma-aminobutyric acid",
                    lambda state: (("PASS", "Job lifecycle", "") if audit.active_structure_is(state, "gamma-aminobutyric acid") and audit.viz_has(state, "esp") else ("FAIL", "Job lifecycle", "")),
                    120000,
                    True,
                ),
                (
                    "case_37_mea_chat_alias",
                    "MEA는 뭐야?",
                    "MEA semantic chat resolves to Ethanolamine",
                    lambda state: (("PASS", "Semantic grounding", "") if _safe_chat_reply(state, needle="ethanolamine") else ("FAIL", "Semantic grounding", "")),
                    40000,
                    False,
                ),
                (
                    "case_38_dma_compute_ambiguous",
                    "DMA HOMO 보여줘",
                    "Ambiguous acronym compute request asks for clarification without raw DMA option",
                    lambda state: (("PASS", "Semantic grounding", "") if _clarifies_without_raw(state, "DMA") else ("FAIL", "Semantic grounding", audit.latest_clarify_text(state))),
                    40000,
                    False,
                ),
                (
                    "case_49_new_session_pronoun_esp_clarify",
                    "그거 ESP 보여줘",
                    "Fresh-session pronoun request clarifies without exposing raw pronoun option",
                    lambda state: (("PASS", "Clarification UI", "") if _clarifies_without_raw(state, "그거") else ("FAIL", "Clarification UI", audit.latest_clarify_text(state))),
                    40000,
                    False,
                ),
                (
                    "case_50_red_team_unicode_sql",
                    "\"; DROP TABLE jobs; --\n🚨 unicode chaos\n<svg/onload=alert(1)>",
                    "Unsafe mixed input is handled without disconnect or crash",
                    lambda state: (("PASS", "Prompt routing", "") if state.get("ws_label", "").lower() == "connected" else ("FAIL", "Prompt routing", audit.latest_clarify_text(state))),
                    40000,
                    False,
                ),
            ]

            for case_id, prompt, expected, evaluator, timeout_ms, terminal in extra_single_cases:
                _single_prompt_case(
                    browser,
                    results,
                    case_id=case_id,
                    prompt=prompt,
                    expected=expected,
                    evaluator=evaluator,
                    timeout_ms=timeout_ms,
                    terminal=terminal,
                )

            _run_shared_followup_cases(browser, results)

        finally:
            browser.close()

    post = audit.health_snapshot()
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
