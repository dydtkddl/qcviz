from __future__ import annotations
import threading
import time
import uuid
import pytest
from qcviz_mcp.web.routes import compute as compute_route
pytestmark = [pytest.mark.api]


def _bootstrap_session(client, session_id: str | None = None):
    payload = {}
    if session_id:
        payload["session_id"] = f"{session_id}-{uuid.uuid4().hex[:8]}"
    resp = client.post("/api/session/bootstrap", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"]
    assert data["session_token"]
    return data

def _wait_for_terminal(client, path: str, timeout: float = 3.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        resp = client.get(path)
        assert resp.status_code == 200
        last = resp.json()
        if last["status"] in {"completed", "failed", "error"}:
            return last
        time.sleep(0.02)
    raise AssertionError(f"job did not finish in time; last={last}")

def test_compute_wait_for_result_orbital(client, patch_fake_runners):
    resp = client.post("/api/compute/jobs?wait_for_result=true", json={"message": "벤젠의 HOMO 보여줘"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["result"]["job_type"] == "orbital_preview"
    assert data["result"]["structure_query"].lower() == "benzene"
    assert data["result"]["visualization"]["available"]["orbital"] is True
    assert data["result"]["selected_orbital"]["label"].upper().startswith("HOMO")

def test_compute_result_exposes_scf_history_and_energy_units(client, patch_fake_runners):
    resp = client.post("/api/compute/jobs?wait_for_result=true", json={"message": "water single point"})
    assert resp.status_code == 200
    data = resp.json()
    result = data["result"]
    assert data["status"] == "completed"
    assert len(result["scf_history"]) >= 2
    assert result["n_scf_cycles"] == 4
    assert result["scf_final_delta_e_hartree"] == pytest.approx(-0.03812345)
    assert result["total_energy_hartree"] == pytest.approx(-76.36812345)
    assert result["total_energy_kcal_mol"] == pytest.approx(
        result["total_energy_hartree"] * 627.5094740631,
        rel=1e-6,
    )
    assert result["explanation"]["summary"]
    assert isinstance(result["explanation"]["next_actions"], list)
    assert "advisor_summary" in result

def test_compute_result_contains_advisor_and_explanation_for_orbitals(client, patch_fake_runners):
    resp = client.post("/api/compute/jobs?wait_for_result=true", json={"message": "water HOMO"})
    assert resp.status_code == 200
    data = resp.json()
    result = data["result"]
    assert data["status"] == "completed"
    assert result["job_type"] == "orbital_preview"
    assert result["explanation"]["summary"]
    assert any("gap" in item.lower() or "HOMO" in item for item in result["explanation"]["key_findings"])
    advisor_summary = result["advisor_summary"]
    assert advisor_summary["confidence_score"] is not None
    assert advisor_summary["methods_preview"]

def test_compute_wait_for_result_esp(client, patch_fake_runners):
    resp = client.post("/api/compute/jobs?wait_for_result=true", json={"message": "Render ESP map for acetone using ACS preset"})
    assert resp.status_code == 200
    data = resp.json()
    result = data["result"]
    assert data["status"] == "completed"
    assert result["job_type"] == "esp_map"
    assert result["structure_query"].lower() == "acetone"
    assert result["visualization"]["available"]["esp"] is True
    assert result["visualization"]["available"]["density"] is True
    assert result["esp_auto_range_au"] == pytest.approx(0.055)
    assert result["advisor_focus_tab"] == "esp"


def test_compute_wait_for_result_sequential_workflow_optimize_then_esp(client, patch_fake_runners):
    resp = client.post(
        "/api/compute/jobs?wait_for_result=true",
        json={"message": "methanol optimize and then ESP"},
    )
    assert resp.status_code == 200
    data = resp.json()
    result = data["result"]

    assert data["status"] == "completed"
    assert result["job_type"] == "esp_map"
    assert result["workflow"]["enabled"] is True
    assert result["workflow_step_count"] == 2
    assert set(result["workflow_results"].keys()) == {"s1", "s2"}
    assert result["workflow_results"]["s1"]["job_type"] == "geometry_optimization"
    assert result["workflow_results"]["s2"]["job_type"] == "esp_map"
    assert result["visualization"]["available"]["esp"] is True


def test_prepare_payload_with_action_plan_skips_raw_text_reparsing(monkeypatch):
    def _explode(*args, **kwargs):
        raise AssertionError("normalize_user_text should not run for authoritative action_plan payloads")

    monkeypatch.setattr(compute_route, "normalize_user_text", _explode, raising=False)
    monkeypatch.setattr(
        compute_route,
        "load_conversation_state",
        lambda *args, **kwargs: {
            "last_structure_query": "water",
            "last_job_type": "single_point",
            "last_resolved_artifact": {},
        },
        raising=False,
    )
    monkeypatch.setattr(compute_route, "get_job_manager", lambda: None, raising=False)

    prepared = compute_route._prepare_payload(
        {
            "message": "이번엔 esp",
            "session_id": "plan-follow-up",
            "planner_applied": True,
            "job_type": "esp_map",
            "planner_intent": "esp_map",
            "planner_missing_slots": [],
            "planner_needs_clarification": False,
            "follow_up_mode": "previous_result",
            "action_plan": {
                "mode": "compute",
                "intent": "esp_map",
                "target": {"molecule_text": None, "from_context": True, "resolved_reference": "previous_result"},
                "parameters": {"method": None, "basis": None, "charge": None, "multiplicity": None, "orbital": None, "surface_type": "esp"},
                "comparison": {"enabled": False, "targets": []},
                "follow_up": {"enabled": True, "reference_type": "previous_result", "reference_slot": "latest"},
                "workflow": {"enabled": False, "steps": []},
                "explanation_request": False,
                "needs_clarification": False,
                "clarification_reason": None,
                "confidence": 0.93,
            },
        }
    )

    assert prepared["structure_query"].lower() == "water"
    assert prepared["continuation_context_used"] is True
    assert prepared["job_type"] == "esp_map"

def test_compute_async_submit_then_poll_on_api_alias(client, patch_fake_runners):
    submit = client.post("/api/compute/jobs", json={"message": "물의 Mulliken charge 계산해줘"})
    assert submit.status_code == 200
    job = submit.json()
    assert "job_id" in job
    assert job["session_id"]
    assert job["session_token"]
    terminal = _wait_for_terminal(
        client,
        (
            f"/api/compute/jobs/{job['job_id']}?include_result=true&include_events=true"
            f"&session_id={job['session_id']}&session_token={job['session_token']}"
        ),
    )
    assert terminal["status"] == "completed"
    assert terminal["result"]["job_type"] == "partial_charges"
    assert len(terminal["result"]["partial_charges"]) == 3
    assert any(ev["type"] == "job_completed" for ev in terminal["events"])

def test_compute_primary_and_api_alias_return_same_job_listing(client, patch_fake_runners):
    client.post("/compute/jobs", json={"message": "벤젠의 HOMO 보여줘", "session_id": "sess-a"})
    client.post("/api/compute/jobs", json={"message": "아세톤 ESP 맵 보여줘", "session_id": "sess-b"})
    resp1 = client.get("/compute/jobs")
    resp2 = client.get("/api/compute/jobs")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["count"] == 0
    assert resp2.json()["count"] == 0
    assert "queue" in resp1.json()
    assert "queue" in resp2.json()


def test_compute_jobs_list_can_filter_by_session(client, patch_fake_runners):
    session_a = _bootstrap_session(client, "sess-a")
    session_b = _bootstrap_session(client, "sess-b")
    client.post(
        "/api/compute/jobs",
        headers={"X-QCViz-Session-Id": session_a["session_id"], "X-QCViz-Session-Token": session_a["session_token"]},
        json={"message": "water HOMO", "session_id": session_a["session_id"]},
    )
    client.post(
        "/api/compute/jobs",
        headers={"X-QCViz-Session-Id": session_b["session_id"], "X-QCViz-Session-Token": session_b["session_token"]},
        json={"message": "acetone ESP", "session_id": session_b["session_id"]},
    )

    resp_a = client.get(
        f"/api/compute/jobs?session_id={session_a['session_id']}&session_token={session_a['session_token']}"
    )
    resp_b = client.get(
        f"/api/compute/jobs?session_id={session_b['session_id']}&session_token={session_b['session_token']}"
    )

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    items_a = resp_a.json()["items"]
    items_b = resp_b.json()["items"]
    assert items_a
    assert items_b
    assert all(item["session_id"] == session_a["session_id"] for item in items_a)
    assert all(item["session_id"] == session_b["session_id"] for item in items_b)


def test_compute_job_endpoints_forbid_cross_session_access(client, patch_fake_runners):
    session = _bootstrap_session(client, "owner-a")
    submit = client.post(
        "/api/compute/jobs",
        headers={"X-QCViz-Session-Id": session["session_id"], "X-QCViz-Session-Token": session["session_token"]},
        json={"message": "water HOMO", "session_id": session["session_id"]},
    )
    assert submit.status_code == 200
    job = submit.json()
    job_id = job["job_id"]

    wrong = client.get(f"/api/compute/jobs/{job_id}?session_id=owner-b")
    assert wrong.status_code == 403

    missing = client.get(f"/api/compute/jobs/{job_id}")
    assert missing.status_code == 403

    ok = client.get(
        f"/api/compute/jobs/{job_id}?session_id={session['session_id']}&session_token={session['session_token']}"
    )
    assert ok.status_code == 200
    assert ok.json()["session_id"] == session["session_id"]


def test_compute_cancel_requires_same_session(client, patch_fake_runners):
    session = _bootstrap_session(client, "owner-a")
    submit = client.post(
        "/api/compute/jobs",
        headers={"X-QCViz-Session-Id": session["session_id"], "X-QCViz-Session-Token": session["session_token"]},
        json={"message": "water HOMO", "session_id": session["session_id"]},
    )
    assert submit.status_code == 200
    job = submit.json()
    job_id = job["job_id"]

    forbidden = client.post(f"/api/compute/jobs/{job_id}/cancel?session_id=owner-b")
    assert forbidden.status_code == 403

    allowed = client.post(
        f"/api/compute/jobs/{job_id}/cancel?session_id={session['session_id']}&session_token={session['session_token']}"
    )
    assert allowed.status_code == 200
    assert allowed.json()["session_id"] == session["session_id"]


def test_compute_jobs_list_rejects_session_without_token(client, patch_fake_runners):
    session = _bootstrap_session(client, "owner-a")
    resp = client.get(f"/api/compute/jobs?session_id={session['session_id']}")
    assert resp.status_code == 403

def test_compute_missing_structure_becomes_failed_job_when_waiting(client, patch_fake_runners):
    resp = client.post("/api/compute/jobs?wait_for_result=true", json={"message": "HOMO 보여줘"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert "Structure not recognized" in data["error"]["message"]


def test_compute_follow_up_reuses_previous_session_structure_and_upgrades_basis(client, patch_fake_runners):
    session = _bootstrap_session(client, "compute-followup")
    first = client.post(
        "/api/compute/jobs?wait_for_result=true",
        headers={"X-QCViz-Session-Id": session["session_id"], "X-QCViz-Session-Token": session["session_token"]},
        json={"message": "water single point with def2-SVP", "session_id": session["session_id"]},
    )
    assert first.status_code == 200
    first_data = first.json()
    assert first_data["status"] == "completed"
    assert first_data["result"]["structure_query"].lower() == "water"
    assert first_data["result"]["basis"].lower() == "def2-svp"

    second = client.post(
        "/api/compute/jobs?wait_for_result=true",
        headers={"X-QCViz-Session-Id": session["session_id"], "X-QCViz-Session-Token": session["session_token"]},
        json={"message": "basis만 더 키워봐", "session_id": session["session_id"]},
    )
    assert second.status_code == 200
    second_data = second.json()
    assert second_data["status"] == "completed"
    assert second_data["result"]["structure_query"].lower() == "water"
    assert second_data["result"]["basis"].lower() == "def2-tzvp"


def test_compute_analysis_only_followup_reuses_previous_session_structure(client, patch_fake_runners):
    session = _bootstrap_session(client, "compute-followup-analysis-only")
    first = client.post(
        "/api/compute/jobs?wait_for_result=true",
        headers={"X-QCViz-Session-Id": session["session_id"], "X-QCViz-Session-Token": session["session_token"]},
        json={"message": "뷰타다이엔 구조가궁금", "session_id": session["session_id"]},
    )
    assert first.status_code == 200
    first_data = first.json()
    assert first_data["status"] == "completed"
    assert first_data["result"]["structure_query"].lower() in {"butadiene", "1,3-butadiene"}

    second = client.post(
        "/api/compute/jobs?wait_for_result=true",
        headers={"X-QCViz-Session-Id": session["session_id"], "X-QCViz-Session-Token": session["session_token"]},
        json={"message": "HOMO LUMO ESP가 궁금", "session_id": session["session_id"]},
    )
    assert second.status_code == 200
    second_data = second.json()
    assert second_data["status"] == "completed"
    assert second_data["result"]["structure_query"].lower() in {"butadiene", "1,3-butadiene"}


def test_compute_short_esp_go_go_followup_reuses_previous_session_structure(client, patch_fake_runners):
    session = _bootstrap_session(client, "compute-followup-go-go")
    first = client.post(
        "/api/compute/jobs?wait_for_result=true",
        headers={"X-QCViz-Session-Id": session["session_id"], "X-QCViz-Session-Token": session["session_token"]},
        json={"message": "벤젠의 HOMO 오비탈을 보여줘", "session_id": session["session_id"]},
    )
    assert first.status_code == 200
    first_data = first.json()
    assert first_data["status"] == "completed"
    assert first_data["result"]["structure_query"].lower() == "benzene"

    second = client.post(
        "/api/compute/jobs?wait_for_result=true",
        headers={"X-QCViz-Session-Id": session["session_id"], "X-QCViz-Session-Token": session["session_token"]},
        json={"message": "ESP ㄱㄱ", "session_id": session["session_id"]},
    )
    assert second.status_code == 200
    second_data = second.json()
    assert second_data["status"] == "completed"
    assert second_data["result"]["job_type"] == "esp_map"
    assert second_data["result"]["structure_query"].lower() == "benzene"


def test_compute_explicit_molecule_overrides_previous_session_structure(client, patch_fake_runners):
    session = _bootstrap_session(client, "compute-followup-override")
    first = client.post(
        "/api/compute/jobs?wait_for_result=true",
        headers={"X-QCViz-Session-Id": session["session_id"], "X-QCViz-Session-Token": session["session_token"]},
        json={"message": "methylamine HOMO", "session_id": session["session_id"]},
    )
    assert first.status_code == 200
    first_data = first.json()
    assert first_data["status"] == "completed"
    assert first_data["result"]["structure_query"].lower() == "methylamine"

    second = client.post(
        "/api/compute/jobs?wait_for_result=true",
        headers={"X-QCViz-Session-Id": session["session_id"], "X-QCViz-Session-Token": session["session_token"]},
        json={"message": "뷰타 다이엔 구조만 보여줘", "session_id": session["session_id"]},
    )
    assert second.status_code == 200
    second_data = second.json()
    assert second_data["status"] == "completed"
    assert second_data["result"]["structure_query"].lower() in {"butadiene", "1,3-butadiene"}


def test_compute_batch_multi_molecule_computation(client, patch_fake_runners):
    paragraph = """
    (a) 아민 CH3NH2 (methylamine)
    (b) CH3COOH (acetic acid)
    (c) CH2=CH-CH=CH2 (1,3-뷰타다이엔)
    (d) CH3CHO (acetaldehyde)
    여기에 나오는 물질들 싹다 구조구하고 homo lumo esp다 구해
    """
    resp = client.post("/api/compute/jobs?wait_for_result=true", json={"message": paragraph})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["result"]["batch_request"] is True
    assert len(data["result"]["molecule_results"]) == 4


def test_compute_health_exposes_queue_summary(client):
    resp = client.get("/api/compute/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "queue" in data
    assert data["job_backend"]["name"] == "inmemory-threadpool"
    assert data["queue"]["max_workers"] >= 1
    assert "recovery" in data
    assert "workers" in data
    assert "quota_config" in data


def test_compute_jobs_list_exposes_quota_summary(client, patch_fake_runners):
    session = _bootstrap_session(client, "quota-list")
    resp = client.get(
        f"/api/compute/jobs?session_id={session['session_id']}&session_token={session['session_token']}"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "quota" in data
    assert data["quota"]["session_id"] == session["session_id"]
    assert data["quota"]["max_active_per_session"] >= 0


def test_compute_session_quota_blocks_second_active_job(client, monkeypatch):
    session = _bootstrap_session(client, "quota-session")
    gate = threading.Event()

    def slow_run(payload, progress_callback=None):
        gate.wait(0.5)
        return {
            "success": True,
            "job_type": payload.get("job_type", "single_point"),
            "structure_query": payload.get("structure_query", "water"),
            "visualization": {},
        }

    monkeypatch.setenv("QCVIZ_MAX_ACTIVE_JOBS_PER_SESSION", "1")
    monkeypatch.setattr(compute_route, "_run_direct_compute", slow_run)

    first = client.post(
        "/api/compute/jobs",
        headers={"X-QCViz-Session-Id": session["session_id"], "X-QCViz-Session-Token": session["session_token"]},
        json={"message": "water HOMO", "session_id": session["session_id"]},
    )
    assert first.status_code == 200

    second = client.post(
        "/api/compute/jobs",
        headers={"X-QCViz-Session-Id": session["session_id"], "X-QCViz-Session-Token": session["session_token"]},
        json={"message": "water ESP", "session_id": session["session_id"]},
    )
    gate.set()
    assert second.status_code == 429
    assert "Active job quota exceeded for this session" in second.json()["detail"]
