"""Tests for turn binding fallback logic."""
from __future__ import annotations

from qcviz_mcp.web.routes.compute import _public_plan_dict


class TestTurnIdPropagation:
    def test_turn_id_not_in_public_plan(self):
        plan = {
            "intent": "analyze",
            "_turn_id": "turn-secret",
            "structure_query": "water",
        }
        public = _public_plan_dict(plan)
        assert "_turn_id" not in public

    def test_js_turn_binding_exact_match(self):
        update_turn_id = "turn-abc"
        current_turn_id = "turn-abc"
        job_id = "job-1"
        active_job_id = "job-2"

        if update_turn_id and current_turn_id:
            is_match = update_turn_id == current_turn_id
        elif job_id and active_job_id:
            is_match = job_id == active_job_id
        else:
            is_match = True
        assert is_match is True

    def test_js_turn_binding_mismatch(self):
        update_turn_id = "turn-old"
        current_turn_id = "turn-new"
        job_id = "job-1"
        active_job_id = "job-1"

        if update_turn_id and current_turn_id:
            is_match = update_turn_id == current_turn_id
        elif job_id and active_job_id:
            is_match = job_id == active_job_id
        else:
            is_match = True
        assert is_match is False

    def test_js_fallback_to_job_id(self):
        update_turn_id = ""
        current_turn_id = "turn-new"
        job_id = "job-123"
        active_job_id = "job-123"

        if update_turn_id and current_turn_id:
            is_match = update_turn_id == current_turn_id
        elif job_id and active_job_id:
            is_match = job_id == active_job_id
        else:
            is_match = True
        assert is_match is True

    def test_js_fallback_job_id_mismatch(self):
        update_turn_id = ""
        current_turn_id = "turn-new"
        job_id = "job-old"
        active_job_id = "job-new"

        if update_turn_id and current_turn_id:
            is_match = update_turn_id == current_turn_id
        elif job_id and active_job_id:
            is_match = job_id == active_job_id
        else:
            is_match = True
        assert is_match is False
