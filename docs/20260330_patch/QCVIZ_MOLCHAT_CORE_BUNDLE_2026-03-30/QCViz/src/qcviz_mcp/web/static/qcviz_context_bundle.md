# QCViz-MCP Enterprise V2 — 50억 달러 마스터 플랜 컨텍스트 번들

> **프로젝트**: 양자화학 시각화 MCP 서버 (Quantum Chemistry Visualization MCP Server)
> **목표**: 일반 실험 연구자가 CLI/터미널 지식 없이, 브라우저 하나로 자연어 입력만으로 양자화학 계산·시각화·분석을 수행하는 완전한 엔터프라이즈급 SaaS
> **아키텍처**: FastAPI + PySCF + 3Dmol.js + WebSocket + LLM (Gemini/OpenAI) Function Calling

이 문서는 AI 에이전트(GPT 등)가 QCViz-MCP의 현재 상태를 정확히 파악하고, LLM Function Calling 전환 및 엣지 시각화 기능(ESP Auto-Fit, IBO, 진동 애니메이션 등)을 개발할 수 있도록 제공되는 핵심 종속 파일 번들입니다.

---

## [chat.py]

경로: `version02/src/qcviz_mcp/web/routes/chat.py`

```python
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import time
from dataclasses import dataclass, is_dataclass
from datetime import date, datetime
from typing import Any, Mapping, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from qcviz_mcp.compute import pyscf_runner
from qcviz_mcp.compute.job_manager import get_job_manager

try:
    from qcviz_mcp.web.advisor_flow import (
        apply_preset_to_runner_kwargs,
        enrich_result_with_advisor,
        prepare_advisor_plan,
    )
except Exception:  # pragma: no cover
    apply_preset_to_runner_kwargs = None
    enrich_result_with_advisor = None
    prepare_advisor_plan = None

try:
    from qcviz_mcp.web.safety_guard import safety_guard  # type: ignore
except Exception:  # pragma: no cover
    try:
        from qcviz_mcp.safety_guard import safety_guard  # type: ignore
    except Exception:  # pragma: no cover
        safety_guard = None


logger = logging.getLogger("qcviz_mcp.web.routes.chat")
router = APIRouter(tags=["chat"])

_STATUS_ALIASES = {
    "queued": "queued",
    "pending": "queued",
    "submitted": "queued",
    "running": "running",
    "in_progress": "running",
    "processing": "running",
    "done": "completed",
    "success": "completed",
    "completed": "completed",
    "complete": "completed",
    "failed": "error",
    "failure": "error",
    "error": "error",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: Optional[str] = Field(default=None, description="Natural-language chat message")
    query: Optional[str] = Field(default=None, description="Alias for message")
    xyz: Optional[str] = Field(default=None, description="Direct XYZ or atom-spec input")
    charge: int = Field(default=0)
    spin: int = Field(default=0, description="2S value; singlet=0, doublet=1, triplet=2 ...")
    method: Optional[str] = Field(default=None)
    basis: Optional[str] = Field(default=None)
    intent: Optional[str] = Field(default=None)
    display_name: Optional[str] = Field(default=None)

    advisor: bool = Field(default=True)
    include_visualization: Optional[bool] = Field(default=None)
    cube_grid_size: Optional[int] = Field(default=60, ge=30, le=90)

    max_cycle: Optional[int] = Field(default=100)
    max_steps: Optional[int] = Field(default=None)

    wait: bool = Field(default=True)
    timeout_sec: Optional[float] = Field(default=120.0)


@dataclass
class ParsedIntent:
    intent: str
    structure_query: str
    focus_tab: str = "summary"


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _to_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        try:
            return dict(value.__dict__)
        except Exception:
            return {}
    if hasattr(value, "__dict__"):
        try:
            return dict(vars(value))
        except Exception:
            return {}
    return {}


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if is_dataclass(value):
        return _jsonable(value.__dict__)
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
    return str(value)


def _normalize_status(status: Any) -> str:
    raw = str(status or "").strip().lower()
    if not raw:
        return "unknown"
    return _STATUS_ALIASES.get(raw, raw)


def _is_terminal_status(status: Any) -> bool:
    return _normalize_status(status) in {"completed", "error", "cancelled"}


def _prepare_kwargs_for_callable(fn: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    try:
        sig = inspect.signature(fn)
    except Exception:
        return dict(kwargs)

    params = sig.parameters
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return dict(kwargs)

    allowed = set(params.keys())
    return {k: v for k, v in kwargs.items() if k in allowed}


def _merge_unique_warnings(base: list[str], extra: list[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for item in list(base or []) + list(extra or []):
        s = str(item).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _default_focus_tab(intent_name: str, result: Mapping[str, Any]) -> str:
    if intent_name in {"draft_methods"}:
        return "methods"
    if intent_name in {"generate_script"}:
        return "script"
    if intent_name in {"validate"}:
        return "literature"
    if intent_name in {"partial_charges"}:
        return "charges"
    if intent_name in {"orbital", "orbital_preview"}:
        return "orbitals"
    if intent_name in {"esp", "esp_map"}:
        return "esp"
    if intent_name in {"geometry_opt", "geometry_optimization"}:
        return "geometry"

    viz = _to_mapping(result.get("visualization")) if isinstance(result, Mapping) else {}
    if _to_mapping(viz.get("orbitals")).get("available"):
        return "orbitals"
    if _to_mapping(viz.get("esp")).get("available"):
        return "esp"
    return "summary"


# ---------------------------------------------------------------------------
# Intent parsing
# ---------------------------------------------------------------------------


_INTENT_PATTERNS: list[tuple[str, tuple[str, ...], str]] = [
    ("draft_methods", ("methods section", "methods", "메소드 섹션", "작성해줘"), "methods"),
    ("generate_script", ("pyscf script", "generate script", "스크립트", "script"), "script"),
    ("validate", ("literature", "validate", "validation", "문헌 검증", "cccbdb"), "literature"),
    ("partial_charges", ("partial charge", "partial charges", "mulliken", "부분 전하", "charges"), "charges"),
    ("orbital", ("homo", "lumo", "orbital", "frontier orbital", "오비탈"), "orbitals"),
    ("esp", ("electrostatic potential", "esp map", "esp", "mep", "전기정전위"), "esp"),
    ("geometry_opt", ("geometry optimization", "geometry optimise", "optimize geometry", "최적화"), "geometry"),
    ("geometry_analysis", ("geometry analysis", "bond length", "bond angle", "결합 길이", "각도 분석", "geometry"), "geometry"),
    ("resolve", ("resolve structure", "resolve", "xyz 보여", "구조 찾아", "구조 resolve"), "summary"),
    ("single_point", ("single-point", "single point", "energy calculation", "에너지 계산"), "summary"),
]


def _canonical_intent(intent: str) -> str:
    raw = str(intent or "").strip().lower()
    if not raw:
        return ""
    aliases = {
        "orbital_preview": "orbital",
        "geometry_optimization": "geometry_opt",
        "geometry_opt": "geometry_opt",
        "opt": "geometry_opt",
        "analysis": "geometry_analysis",
        "analyze": "geometry_analysis",
        "esp_map": "esp",
        "sp": "single_point",
    }
    return aliases.get(raw, raw)


def _extract_structure_query(text: str, inferred_intent: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""

    cleaned = " " + raw + " "
    replacements = [
        r"\bmethods section\b",
        r"\bmethods\b",
        r"\bpyscf script\b",
        r"\bgenerate script\b",
        r"\bpartial charges?\b",
        r"\bmulliken\b",
        r"\bgeometry optimization\b",
        r"\bgeometry optimise\b",
        r"\boptimi[sz]e geometry\b",
        r"\borbital analysis\b",
        r"\bfrontier orbital\b",
        r"\bhomo\b",
        r"\blumo\b",
        r"\borbital\b",
        r"\belectrostatic potential\b",
        r"\besp map\b",
        r"\besp\b",
        r"\bmep\b",
        r"\bliterature\b",
        r"\bvalidate\b",
        r"\bvalidation\b",
        r"\bresolve structure\b",
        r"\bresolve\b",
        r"\bsingle-point calculation\b",
        r"\bsingle-point\b",
        r"\bsingle point\b",
        r"\benergy calculation\b",
        r"문헌 검증해줘",
        r"검증해줘",
        r"계산해줘",
        r"보여줘",
        r"만들어줘",
        r"작성해줘",
        r"구조 찾아줘",
        r"구조 resolve",
        r"오비탈",
        r"부분 전하",
        r"전기정전위",
        r"최적화",
        r"메소드 섹션",
        r"분석해줘",
        r"분석",
    ]
    for pat in replacements:
        cleaned = re.sub(pat, " ", cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.:;!?()[]{}")
    if cleaned:
        return cleaned
    return raw


def _infer_intent(explicit_intent: str | None, raw_text: str | None) -> ParsedIntent:
    canonical = _canonical_intent(explicit_intent or "")
    text = str(raw_text or "").strip()

    if canonical:
        return ParsedIntent(
            intent=canonical,
            structure_query=_extract_structure_query(text, canonical) or text,
            focus_tab=_default_focus_tab(canonical, {}),
        )

    lowered = text.lower()
    for intent_name, needles, focus_tab in _INTENT_PATTERNS:
        if any(n in lowered for n in needles):
            return ParsedIntent(
                intent=intent_name,
                structure_query=_extract_structure_query(text, intent_name) or text,
                focus_tab=focus_tab,
            )

    return ParsedIntent(
        intent="single_point",
        structure_query=text,
        focus_tab="summary",
    )


def _resolve_runner(intent_name: str):
    intent_name = _canonical_intent(intent_name)

    if intent_name == "resolve":
        return pyscf_runner.run_resolve_structure
    if intent_name in {"geometry_analysis", "analyze", "validate"}:
        return pyscf_runner.run_geometry_analysis
    if intent_name in {"geometry_opt", "geometry_optimization"}:
        return pyscf_runner.run_geometry_optimization
    if intent_name == "partial_charges":
        return pyscf_runner.run_partial_charges
    if intent_name in {"orbital", "orbital_preview"}:
        return pyscf_runner.run_orbital_preview
    if intent_name in {"esp", "esp_map"} and hasattr(pyscf_runner, "run_esp_map"):
        return pyscf_runner.run_esp_map
    return pyscf_runner.run_single_point


def _looks_like_help_only(text: str) -> bool:
    s = str(text or "").strip().lower()
    if not s:
        return True
    return s in {
        "help",
        "도움말",
        "hi",
        "hello",
        "hey",
        "안녕",
        "사용법",
        "?",
    }


def _help_message() -> str:
    return (
        "분자명 또는 XYZ와 함께 요청해 주세요. 예:\n"
        "- benzene single point\n"
        "- water orbital\n"
        "- acetone esp map\n"
        "- ethanol partial charges\n"
        "- XYZ 붙여넣고 geometry optimization"
    )


# ---------------------------------------------------------------------------
# Safety / advisor wrappers
# ---------------------------------------------------------------------------


def _evaluate_safety(payload: Mapping[str, Any]) -> dict[str, Any]:
    if safety_guard is None:
        return {"allowed": True, "warnings": []}

    evaluator = getattr(safety_guard, "evaluate_request", None)
    if not callable(evaluator):
        return {"allowed": True, "warnings": []}

    try:
        verdict = evaluator(_jsonable(payload))
    except Exception as exc:
        logger.warning("Safety evaluation failed; allowing request. error=%s", exc)
        return {"allowed": True, "warnings": [f"Safety evaluator failed: {exc}"]}

    data = _to_mapping(verdict)
    blocked = bool(data.get("blocked") or data.get("reject") or data.get("denied") or (data.get("allowed") is False))
    warnings = data.get("warnings") or []
    if not isinstance(warnings, list):
        warnings = [str(warnings)] if warnings else []

    return {
        "allowed": not blocked,
        "warnings": [str(x) for x in warnings if x],
        "reason": data.get("reason") or data.get("message"),
        "raw": data,
    }


async def _await_maybe(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _run_awaitable_sync(value: Any) -> Any:
    if not inspect.isawaitable(value):
        return value

    try:
        asyncio.get_running_loop()
        loop_running = True
    except RuntimeError:
        loop_running = False

    if not loop_running:
        return asyncio.run(value)

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(value)
    finally:
        loop.close()


async def _prepare_advisor_plan_safe(**kwargs: Any) -> Any:
    if prepare_advisor_plan is None:
        return None

    attempts = [
        lambda: prepare_advisor_plan(**kwargs),
        lambda: prepare_advisor_plan(
            kwargs.get("query"),
            kwargs.get("xyz"),
            kwargs.get("charge"),
            kwargs.get("spin"),
            kwargs.get("intent"),
        ),
        lambda: prepare_advisor_plan(
            query=kwargs.get("query"),
            xyz=kwargs.get("xyz"),
            charge=kwargs.get("charge"),
            spin=kwargs.get("spin"),
        ),
    ]

    last_exc: Exception | None = None
    for attempt in attempts:
        try:
            return await _await_maybe(attempt())
        except TypeError as exc:
            last_exc = exc
            continue
        except Exception as exc:
            logger.warning("prepare_advisor_plan failed: %s", exc)
            return None

    if last_exc:
        logger.debug("prepare_advisor_plan signature mismatch: %s", last_exc)
    return None


def _apply_preset_safe(advisor_plan: Any, runner_kwargs: dict[str, Any]) -> dict[str, Any]:
    if apply_preset_to_runner_kwargs is None or not advisor_plan:
        return runner_kwargs

    attempts = [
        lambda: apply_preset_to_runner_kwargs(advisor_plan, runner_kwargs),
        lambda: apply_preset_to_runner_kwargs(advisor_plan=advisor_plan, runner_kwargs=runner_kwargs),
        lambda: apply_preset_to_runner_kwargs(runner_kwargs, advisor_plan),
    ]

    for attempt in attempts:
        try:
            updated = attempt()
            if isinstance(updated, Mapping):
                return dict(updated)
            return runner_kwargs
        except TypeError:
            continue
        except Exception as exc:
            logger.warning("apply_preset_to_runner_kwargs failed: %s", exc)
            return runner_kwargs

    return runner_kwargs


def _enrich_result_safe(
    result: dict[str, Any],
    *,
    intent_name: str,
    advisor_plan: Any = None,
) -> dict[str, Any]:
    if enrich_result_with_advisor is None:
        return result

    attempts = [
        lambda: enrich_result_with_advisor(result=result, intent=intent_name, advisor_plan=advisor_plan),
        lambda: enrich_result_with_advisor(result=result, intent_name=intent_name, advisor_plan=advisor_plan),
        lambda: enrich_result_with_advisor(result=result),
        lambda: enrich_result_with_advisor(result, intent_name, advisor_plan),
    ]

    for attempt in attempts:
        try:
            enriched = _run_awaitable_sync(attempt())
            if isinstance(enriched, Mapping):
                return dict(enriched)
            return result
        except TypeError:
            continue
        except Exception as exc:
            logger.warning("enrich_result_with_advisor failed: %s", exc)
            return result

    return result


# ---------------------------------------------------------------------------
# Job manager compatibility wrappers
# ---------------------------------------------------------------------------


def _jm_submit(
    jm: Any,
    fn: Any,
    *,
    kwargs: dict[str, Any],
    name: str,
    metadata: Optional[dict[str, Any]] = None,
) -> str:
    metadata = metadata or {}

    attempts = [
        lambda: jm.submit(fn=fn, kwargs=kwargs, name=name, metadata=metadata),
        lambda: jm.submit(func=fn, kwargs=kwargs, name=name, metadata=metadata),
        lambda: jm.submit(target=fn, kwargs=kwargs, name=name, metadata=metadata),
        lambda: jm.submit(fn, kwargs=kwargs, name=name, metadata=metadata),
        lambda: jm.submit(target=fn, kwargs=kwargs, label=name),
        lambda: jm.submit(func=fn, kwargs=kwargs, name=name),
        lambda: jm.submit(fn, kwargs=kwargs, name=name),
        lambda: jm.submit(fn, kwargs=kwargs, label=name),
        lambda: jm.submit(fn, name=name, metadata=metadata, **kwargs),
        lambda: jm.submit(fn, **kwargs),
    ]

    last_exc: Exception | None = None
    for attempt in attempts:
        try:
            value = attempt()
            if isinstance(value, (str, int)):
                return str(value)
            data = _to_mapping(value)
            job_id = data.get("job_id") or data.get("id")
            if job_id is not None:
                return str(job_id)
        except TypeError as exc:
            last_exc = exc
            continue

    raise RuntimeError(f"JobManager.submit signature unsupported: {last_exc}")


def _jm_get(jm: Any, job_id: str) -> Any:
    attempts = []
    if hasattr(jm, "get"):
        attempts.append(lambda: jm.get(job_id))
    if hasattr(jm, "get_job"):
        attempts.append(lambda: jm.get_job(job_id))
    if hasattr(jm, "fetch"):
        attempts.append(lambda: jm.fetch(job_id))

    for attempt in attempts:
        try:
            return attempt()
        except Exception:
            continue
    return None


def _jm_drain_events(jm: Any, job_id: str) -> list[Any]:
    candidates = [
        getattr(jm, "drain_events", None),
        getattr(jm, "get_events", None),
        getattr(jm, "drain", None),
    ]
    for fn in candidates:
        if callable(fn):
            try:
                data = fn(job_id)
                return list(data or [])
            except Exception:
                continue
    return []


def _jm_cancel(jm: Any, job_id: str) -> bool:
    candidates = [
        getattr(jm, "cancel", None),
        getattr(jm, "cancel_job", None),
        getattr(jm, "stop", None),
    ]
    for fn in candidates:
        if callable(fn):
            try:
                value = fn(job_id)
                return bool(True if value is None else value)
            except Exception:
                continue
    return False


def _serialize_job_record(record: Any) -> dict[str, Any]:
    if record is None:
        return {}

    data = _to_mapping(record)
    result = _jsonable(data)

    job_id = result.get("job_id") or result.get("id")
    status = result.get("status") or result.get("state")
    progress = result.get("progress", 0)
    step = result.get("step") or result.get("phase") or ""
    detail = result.get("detail") or result.get("message") or ""

    result["job_id"] = job_id
    result["status"] = _normalize_status(status)
    result["progress"] = _safe_float(progress, 0.0)
    result["step"] = step
    result["detail"] = detail
    return result


def _serialize_event(event: Any) -> dict[str, Any]:
    data = _to_mapping(event)
    data = _jsonable(data)
    if "level" not in data:
        data["level"] = "info"
    if "message" not in data:
        data["message"] = data.get("detail") or data.get("step") or ""
    return data


def _extract_job_result(record: Any) -> dict[str, Any]:
    data = _to_mapping(record)
    if not data:
        return {}

    for key in ("result", "output", "value"):
        val = data.get(key)
        if isinstance(val, Mapping):
            return dict(val)

    payload = data.get("data")
    if isinstance(payload, Mapping):
        if isinstance(payload.get("result"), Mapping):
            return dict(payload["result"])
        if any(k in payload for k in ("xyz", "intent", "visualization", "total_energy_hartree", "partial_charges")):
            return dict(payload)

    if any(k in data for k in ("xyz", "intent", "visualization", "total_energy_hartree", "partial_charges")):
        return dict(data)

    return {}


# ---------------------------------------------------------------------------
# Compute runner wrapper
# ---------------------------------------------------------------------------


def _run_chat_compute_job(
    *,
    intent_name: str,
    original_prompt: str | None,
    structure_query: str | None,
    xyz: str | None,
    charge: int,
    spin: int,
    display_name: str | None,
    method: str | None,
    basis: str | None,
    advisor_enabled: bool,
    advisor_plan: Any = None,
    include_visualization: bool = True,
    cube_grid_size: int = 60,
    max_cycle: Optional[int] = None,
    max_steps: Optional[int] = None,
    progress_callback: Any = None,
    emit_event: Any = None,
    is_cancelled: Any = None,
    **extra: Any,
) -> dict[str, Any]:
    runner = _resolve_runner(intent_name)

    runner_kwargs: dict[str, Any] = {
        "query": structure_query or original_prompt,
        "xyz": xyz,
        "charge": charge,
        "spin": spin,
        "display_name": display_name,
        "method": method,
        "basis": basis,
        "include_visualization": include_visualization,
        "cube_grid_size": cube_grid_size,
        "progress_callback": progress_callback,
        "emit_event": emit_event,
        "is_cancelled": is_cancelled,
    }
    if max_cycle is not None:
        runner_kwargs["max_cycle"] = max_cycle
    if max_steps is not None:
        runner_kwargs["max_steps"] = max_steps
    runner_kwargs.update(extra)

    filtered_runner_kwargs = _prepare_kwargs_for_callable(runner, runner_kwargs)
    result = runner(**filtered_runner_kwargs)
    result = _run_awaitable_sync(result)

    if not isinstance(result, Mapping):
        result = {"value": result}
    else:
        result = dict(result)

    result.setdefault("intent", intent_name)
    result.setdefault("original_prompt", original_prompt)
    result.setdefault("structure_query", structure_query or original_prompt)
    result.setdefault("method", method)
    result.setdefault("basis", basis)
    result.setdefault("charge", charge)
    result.setdefault("spin", spin)
    result["include_visualization"] = include_visualization
    result["cube_grid_size"] = cube_grid_size

    if advisor_plan:
        result["advisor_plan"] = _jsonable(advisor_plan)

    if advisor_enabled:
        result = _enrich_result_safe(result, intent_name=intent_name, advisor_plan=advisor_plan)

    result["advisor_focus_tab"] = _default_focus_tab(intent_name, result)
    return result


# ---------------------------------------------------------------------------
# Assistant text helpers
# ---------------------------------------------------------------------------


def _brief_energy_text(result: Mapping[str, Any]) -> str:
    eh = result.get("total_energy_hartree")
    gap = result.get("orbital_gap_ev")
    parts = []
    try:
        if eh is not None:
            parts.append(f"E = {float(eh):.8f} Ha")
    except Exception:
        pass
    try:
        if gap is not None:
            parts.append(f"gap = {float(gap):.3f} eV")
    except Exception:
        pass
    return ", ".join(parts)


def _assistant_summary(result: Mapping[str, Any], intent_name: str) -> str:
    name = str(result.get("display_name") or result.get("formula") or "molecule")
    base = _brief_energy_text(result)
    viz = _to_mapping(result.get("visualization"))
    orb_ok = bool(_to_mapping(viz.get("orbitals")).get("available"))
    esp_ok = bool(_to_mapping(viz.get("esp")).get("available"))

    if intent_name in {"orbital", "orbital_preview"}:
        if orb_ok:
            return f"{name} 오비탈 데이터를 준비했습니다. Orbitals 탭에서 오비탈을 클릭하면 분자 위에 ± isosurface가 렌더됩니다." + (f" ({base})" if base else "")
        return f"{name} 계산은 완료됐지만 오비탈 시각화 cube 생성은 준비되지 않았습니다." + (f" ({base})" if base else "")

    if intent_name in {"esp", "esp_map"}:
        if esp_ok:
            return f"{name} ESP 표면 데이터를 준비했습니다. ESP 탭에서 preset / iso / opacity / range를 조절해 보세요." + (f" ({base})" if base else "")
        return f"{name} 계산은 완료됐지만 ESP 시각화 데이터는 생성되지 않았습니다." + (f" ({base})" if base else "")

    if intent_name == "partial_charges":
        charges = result.get("partial_charges") or result.get("charges") or []
        n = len(charges) if isinstance(charges, list) else 0
        return f"{name} 부분 전하 계산을 완료했습니다. Charges 탭과 viewer의 charge label 버튼으로 확인할 수 있습니다." + (f" 원자 {n}개." if n else "") + (f" ({base})" if base else "")

    if intent_name in {"geometry_opt", "geometry_optimization"}:
        conv = result.get("converged")
        return f"{name} 구조 최적화 계산을 완료했습니다." + (" 수렴했습니다." if conv is True else " 최종 구조를 확인하세요.") + (f" ({base})" if base else "")

    if intent_name in {"geometry_analysis", "resolve"}:
        return f"{name} 구조 정보를 준비했습니다. Geometry 탭에서 XYZ와 bond 추정을 확인할 수 있습니다."

    return f"{name} 계산을 완료했습니다." + (f" ({base})" if base else "")


def _assistant_suggestions(intent_name: str, result: Mapping[str, Any]) -> list[str]:
    suggestions: list[str] = []
    viz = _to_mapping(result.get("visualization"))
    if _to_mapping(viz.get("orbitals")).get("available"):
        suggestions.append("Orbitals 탭에서 HOMO/LUMO 또는 다른 오비탈을 클릭해 3D surface를 확인해 보세요.")
    if _to_mapping(viz.get("esp")).get("available"):
        suggestions.append("ESP 탭에서 color preset과 range를 바꾸며 표면 분포를 비교해 보세요.")
    if result.get("partial_charges") or result.get("charges"):
        suggestions.append("Charges 버튼을 눌러 원자별 charge label을 viewer 위에 띄울 수 있습니다.")
    if not suggestions:
        suggestions.append("원하면 다음으로 orbital, ESP, charges 중 하나를 이어서 계산할 수 있습니다.")
    return suggestions


def _build_messages(result: Mapping[str, Any], intent_name: str) -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = []
    msgs.append(
        {
            "role": "assistant",
            "kind": "summary",
            "content": _assistant_summary(result, intent_name),
        }
    )

    warnings = result.get("warnings") or []
    if isinstance(warnings, list):
        for w in warnings:
            if w:
                msgs.append(
                    {
                        "role": "warning",
                        "kind": "warning",
                        "content": str(w),
                    }
                )

    suggestions = _assistant_suggestions(intent_name, result)
    if suggestions:
        msgs.append(
            {
                "role": "assistant",
                "kind": "suggestions",
                "content": suggestions,
            }
        )
    return msgs


# ---------------------------------------------------------------------------
# Request preparation
# ---------------------------------------------------------------------------


def _include_visualization_default(intent_name: str) -> bool:
    return intent_name in {
        "single_point",
        "orbital",
        "orbital_preview",
        "partial_charges",
        "esp",
        "esp_map",
    }


def _build_job_label(intent_name: str, display_name: str | None, structure_query: str | None) -> str:
    subject = (display_name or structure_query or "molecule").strip()
    subject = re.sub(r"\s+", " ", subject)[:80]
    return f"chat:{intent_name}:{subject}"


async def _prepare_job_request(
    *,
    message: str,
    xyz: str | None,
    charge: int,
    spin: int,
    method: str | None,
    basis: str | None,
    intent: str | None,
    display_name: str | None,
    advisor: bool,
    include_visualization: bool | None,
    cube_grid_size: int | None,
    max_cycle: int | None,
    max_steps: int | None,
) -> dict[str, Any]:
    raw_prompt = str(message or "").strip()
    parsed = _infer_intent(intent, raw_prompt)

    structure_query = ""
    if xyz and str(xyz).strip():
        structure_query = (display_name or raw_prompt or "direct structure").strip()
    else:
        structure_query = (parsed.structure_query or raw_prompt).strip()

    if not structure_query and not (xyz and str(xyz).strip()):
        if _looks_like_help_only(raw_prompt):
            return {
                "help_only": True,
                "assistant_message": _help_message(),
                "messages": [{"role": "assistant", "kind": "help", "content": _help_message()}],
            }
        raise HTTPException(status_code=422, detail="Provide either a structure query or xyz/atom-spec input.")

    intent_name = parsed.intent
    display_name = (display_name or structure_query or "molecule").strip()

    safety_payload = {
        "prompt": raw_prompt,
        "structure_query": structure_query,
        "xyz": xyz,
        "intent": intent_name,
        "charge": charge,
        "spin": spin,
        "method": method,
        "basis": basis,
    }
    safety = _evaluate_safety(safety_payload)
    if not safety.get("allowed", True):
        raise HTTPException(
            status_code=400,
            detail={
                "message": safety.get("reason") or "Request blocked by safety policy.",
                "warnings": safety.get("warnings", []),
            },
        )

    include_viz = include_visualization if include_visualization is not None else _include_visualization_default(intent_name)
    grid_size = max(30, min(90, int(cube_grid_size or 60)))

    runner_kwargs: dict[str, Any] = {
        "intent_name": intent_name,
        "original_prompt": raw_prompt or structure_query,
        "structure_query": structure_query,
        "xyz": xyz,
        "charge": int(charge or 0),
        "spin": int(spin or 0),
        "display_name": display_name,
        "method": method,
        "basis": basis,
        "advisor_enabled": bool(advisor),
        "include_visualization": bool(include_viz),
        "cube_grid_size": grid_size,
        "max_cycle": max_cycle,
        "max_steps": max_steps,
    }

    advisor_plan = None
    advisor_warnings: list[str] = []
    if advisor:
        advisor_plan = await _prepare_advisor_plan_safe(
            query=structure_query or raw_prompt,
            xyz=xyz,
            charge=charge,
            spin=spin,
            intent=intent_name,
        )
        if advisor_plan:
            runner_kwargs["advisor_plan"] = advisor_plan
            before_method = runner_kwargs.get("method")
            before_basis = runner_kwargs.get("basis")
            runner_kwargs = _apply_preset_safe(advisor_plan, runner_kwargs)
            if before_method != runner_kwargs.get("method") or before_basis != runner_kwargs.get("basis"):
                advisor_warnings.append("Advisor preset applied to method/basis selection.")

    metadata = {
        "intent": intent_name,
        "display_name": display_name,
        "structure_query": structure_query,
        "advisor": bool(advisor),
        "include_visualization": bool(include_viz),
        "cube_grid_size": grid_size,
        "focus_tab": parsed.focus_tab,
        "source": "chat",
    }

    return {
        "help_only": False,
        "intent_name": intent_name,
        "display_name": display_name,
        "structure_query": structure_query,
        "runner_kwargs": runner_kwargs,
        "metadata": metadata,
        "safety": safety,
        "advisor_plan": advisor_plan,
        "advisor_warnings": advisor_warnings,
        "advisor_focus_tab": parsed.focus_tab,
        "include_visualization": bool(include_viz),
        "cube_grid_size": grid_size,
        "label": _build_job_label(intent_name, display_name, structure_query),
    }


# ---------------------------------------------------------------------------
# Job waiting / polling
# ---------------------------------------------------------------------------


async def _wait_for_job(jm: Any, job_id: str, timeout_sec: float = 120.0) -> dict[str, Any]:
    started = time.monotonic()
    while True:
        record = _jm_get(jm, job_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
        data = _serialize_job_record(record)
        if _is_terminal_status(data.get("status")):
            return data
        if timeout_sec > 0 and (time.monotonic() - started) >= timeout_sec:
            data["timed_out"] = True
            return data
        await asyncio.sleep(0.20)


# ---------------------------------------------------------------------------
# REST routes
# ---------------------------------------------------------------------------


@router.post("/chat")
async def chat(req: ChatRequest) -> dict[str, Any]:
    message = (req.message or req.query or "").strip()
    prepared = await _prepare_job_request(
        message=message,
        xyz=req.xyz,
        charge=req.charge,
        spin=req.spin,
        method=req.method,
        basis=req.basis,
        intent=req.intent,
        display_name=req.display_name,
        advisor=bool(req.advisor),
        include_visualization=req.include_visualization,
        cube_grid_size=req.cube_grid_size,
        max_cycle=req.max_cycle,
        max_steps=req.max_steps,
    )

    if prepared.get("help_only"):
        return {
            "ok": True,
            "type": "assistant",
            "assistant_message": prepared["assistant_message"],
            "messages": prepared["messages"],
            "advisor_focus_tab": "summary",
        }

    jm = get_job_manager()
    try:
        job_id = _jm_submit(
            jm,
            _run_chat_compute_job,
            kwargs=prepared["runner_kwargs"],
            name=prepared["label"],
            metadata=prepared["metadata"],
        )
    except Exception as exc:
        logger.exception("Failed to submit chat compute job")
        raise HTTPException(status_code=500, detail=f"Failed to submit job: {exc}") from exc

    base_response = {
        "ok": True,
        "type": "job_submitted",
        "job_id": job_id,
        "label": prepared["label"],
        "intent": prepared["intent_name"],
        "display_name": prepared["display_name"],
        "structure_query": prepared["structure_query"],
        "advisor_focus_tab": prepared["advisor_focus_tab"],
        "include_visualization": prepared["include_visualization"],
        "cube_grid_size": prepared["cube_grid_size"],
        "warnings": list(prepared["safety"].get("warnings", [])) + list(prepared["advisor_warnings"]),
    }

    if not req.wait:
        return base_response

    final_job = await _wait_for_job(jm, job_id, timeout_sec=max(0.0, _safe_float(req.timeout_sec, 120.0)))
    result = _extract_job_result(final_job)
    if isinstance(result, Mapping):
        result = dict(result)
    else:
        result = {}

    if result:
        result.setdefault("advisor_focus_tab", _default_focus_tab(prepared["intent_name"], result))
        result["warnings"] = _merge_unique_warnings(
            list(result.get("warnings", []) if isinstance(result.get("warnings"), list) else []),
            list(prepared["safety"].get("warnings", [])) + list(prepared["advisor_warnings"]),
        )

    assistant_message = _assistant_summary(result, prepared["intent_name"]) if result else (
        final_job.get("detail") or "작업이 종료되었습니다."
    )
    messages = _build_messages(result, prepared["intent_name"]) if result else [
        {"role": "assistant", "kind": "summary", "content": assistant_message}
    ]

    return {
        **base_response,
        "type": "result",
        "job": final_job,
        "result": result,
        "assistant_message": assistant_message,
        "message": assistant_message,
        "messages": messages,
        "advisor_focus_tab": result.get("advisor_focus_tab", prepared["advisor_focus_tab"]) if result else prepared["advisor_focus_tab"],
    }


@router.post("/chat/ask")
async def chat_ask(req: ChatRequest) -> dict[str, Any]:
    return await chat(req)


# ---------------------------------------------------------------------------
# WebSocket route
# ---------------------------------------------------------------------------


async def _ws_send_json(ws: WebSocket, payload: Mapping[str, Any]) -> None:
    await ws.send_text(json.dumps(_jsonable(payload), ensure_ascii=False))


def _parse_ws_payload(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {"message": ""}

    try:
        value = json.loads(text)
        if isinstance(value, Mapping):
            return dict(value)
        if isinstance(value, str):
            return {"message": value}
        return {"message": text}
    except Exception:
        return {"message": text}


@router.websocket("/ws/chat")
async def websocket_chat(ws: WebSocket) -> None:
    await ws.accept()
    jm = get_job_manager()

    await _ws_send_json(
        ws,
        {
            "type": "ready",
            "event": "ready",
            "message": "QCViz chat websocket connected.",
        },
    )

    try:
        while True:
            raw = await ws.receive_text()
            payload = _parse_ws_payload(raw)
            msg_type = str(payload.get("type") or "").strip().lower()

            if msg_type == "ping":
                await _ws_send_json(ws, {"type": "pong", "event": "pong", "ts": time.time()})
                continue

            if msg_type == "cancel":
                job_id = str(payload.get("job_id") or "").strip()
                accepted = _jm_cancel(jm, job_id) if job_id else False
                await _ws_send_json(
                    ws,
                    {
                        "type": "cancelled" if accepted else "cancel_unsupported",
                        "event": "cancel",
                        "job_id": job_id,
                        "accepted": bool(accepted),
                    },
                )
                continue

            message = str(payload.get("message") or payload.get("query") or "").strip()
            xyz = payload.get("xyz")
            charge = _safe_int(payload.get("charge"), 0)
            spin = _safe_int(payload.get("spin"), 0)
            method = payload.get("method")
            basis = payload.get("basis")
            intent = payload.get("intent")
            display_name = payload.get("display_name")
            advisor = bool(payload.get("advisor", True))
            include_visualization = payload.get("include_visualization")
            cube_grid_size = _safe_int(payload.get("cube_grid_size"), 60)
            max_cycle = payload.get("max_cycle")
            max_steps = payload.get("max_steps")

            try:
                prepared = await _prepare_job_request(
                    message=message,
                    xyz=xyz,
                    charge=charge,
                    spin=spin,
                    method=method,
                    basis=basis,
                    intent=intent,
                    display_name=display_name,
                    advisor=advisor,
                    include_visualization=include_visualization if include_visualization is not None else None,
                    cube_grid_size=cube_grid_size,
                    max_cycle=max_cycle,
                    max_steps=max_steps,
                )
            except HTTPException as exc:
                await _ws_send_json(
                    ws,
                    {
                        "type": "error",
                        "event": "error",
                        "status_code": exc.status_code,
                        "detail": exc.detail,
                        "message": exc.detail if isinstance(exc.detail, str) else json.dumps(_jsonable(exc.detail), ensure_ascii=False),
                    },
                )
                continue
            except Exception as exc:
                logger.exception("Failed to prepare websocket chat request")
                await _ws_send_json(
                    ws,
                    {
                        "type": "error",
                        "event": "error",
                        "message": f"Request preparation failed: {exc}",
                    },
                )
                continue

            if prepared.get("help_only"):
                await _ws_send_json(
                    ws,
                    {
                        "type": "assistant",
                        "event": "assistant",
                        "assistant_message": prepared["assistant_message"],
                        "message": prepared["assistant_message"],
                        "messages": prepared["messages"],
                        "advisor_focus_tab": "summary",
                    },
                )
                continue

            await _ws_send_json(
                ws,
                {
                    "type": "ack",
                    "event": "ack",
                    "message": "Request received.",
                    "intent": prepared["intent_name"],
                    "structure_query": prepared["structure_query"],
                    "advisor_focus_tab": prepared["advisor_focus_tab"],
                },
            )

            try:
                job_id = _jm_submit(
                    jm,
                    _run_chat_compute_job,
                    kwargs=prepared["runner_kwargs"],
                    name=prepared["label"],
                    metadata=prepared["metadata"],
                )
            except Exception as exc:
                logger.exception("Failed to submit websocket chat job")
                await _ws_send_json(
                    ws,
                    {
                        "type": "error",
                        "event": "error",
                        "message": f"Failed to submit job: {exc}",
                    },
                )
                continue

            await _ws_send_json(
                ws,
                {
                    "type": "job_submitted",
                    "event": "job_submitted",
                    "job_id": job_id,
                    "label": prepared["label"],
                    "intent": prepared["intent_name"],
                    "display_name": prepared["display_name"],
                    "structure_query": prepared["structure_query"],
                    "advisor_focus_tab": prepared["advisor_focus_tab"],
                    "include_visualization": prepared["include_visualization"],
                    "cube_grid_size": prepared["cube_grid_size"],
                    "warnings": list(prepared["safety"].get("warnings", [])) + list(prepared["advisor_warnings"]),
                },
            )

            last_status = None
            last_progress = None

            while True:
                # stream job events if supported
                try:
                    events = [_serialize_event(ev) for ev in _jm_drain_events(jm, job_id)]
                except Exception:
                    events = []

                for ev in events:
                    await _ws_send_json(
                        ws,
                        {
                            "type": "job_event",
                            "event": "job_event",
                            "job_id": job_id,
                            "payload": ev,
                            "message": ev.get("message") or ev.get("detail") or "",
                        },
                    )

                record = _jm_get(jm, job_id)
                if record is None:
                    await _ws_send_json(
                        ws,
                        {
                            "type": "error",
                            "event": "error",
                            "job_id": job_id,
                            "message": "Job disappeared before completion.",
                        },
                    )
                    break

                job = _serialize_job_record(record)
                status = job.get("status")
                progress = job.get("progress")

                if status != last_status or progress != last_progress:
                    await _ws_send_json(
                        ws,
                        {
                            "type": "job_update",
                            "event": "job_update",
                            "job_id": job_id,
                            "job": job,
                            "status": status,
                            "progress": progress,
                            "step": job.get("step"),
                            "detail": job.get("detail"),
                            "message": job.get("detail") or job.get("step") or "",
                        },
                    )
                    last_status = status
                    last_progress = progress

                if _is_terminal_status(status):
                    result = _extract_job_result(record)
                    if isinstance(result, Mapping):
                        result = dict(result)
                    else:
                        result = {}

                    if result:
                        result.setdefault("advisor_focus_tab", _default_focus_tab(prepared["intent_name"], result))
                        result["warnings"] = _merge_unique_warnings(
                            list(result.get("warnings", []) if isinstance(result.get("warnings"), list) else []),
                            list(prepared["safety"].get("warnings", [])) + list(prepared["advisor_warnings"]),
                        )

                    assistant_message = _assistant_summary(result, prepared["intent_name"]) if result else (
                        job.get("detail") or "작업이 종료되었습니다."
                    )
                    messages = _build_messages(result, prepared["intent_name"]) if result else [
                        {"role": "assistant", "kind": "summary", "content": assistant_message}
                    ]

                    final_payload = {
                        "type": "result" if status == "completed" else status,
                        "event": "result",
                        "job_id": job_id,
                        "job": job,
                        "intent": prepared["intent_name"],
                        "result": result,
                        "assistant_message": assistant_message,
                        "message": assistant_message,
                        "messages": messages,
                        "advisor_focus_tab": result.get("advisor_focus_tab", prepared["advisor_focus_tab"]) if result else prepared["advisor_focus_tab"],
                    }

                    # redundant aliases for frontend compatibility
                    final_payload["data"] = result
                    final_payload["output"] = result
                    final_payload["kind"] = "final"

                    await _ws_send_json(ws, final_payload)
                    break

                await asyncio.sleep(0.20)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: /ws/chat")
    except Exception as exc:
        logger.exception("Unhandled websocket chat error")
        try:
            await _ws_send_json(
                ws,
                {
                    "type": "error",
                    "event": "error",
                    "message": f"Unhandled websocket error: {exc}",
                },
            )
        except Exception:
            pass
        try:
            await ws.close()
        except Exception:
            pass

```

## [compute.py]

경로: `version02/src/qcviz_mcp/web/routes/compute.py`

```python
from __future__ import annotations

import asyncio
import inspect
import logging
import re
import time
from dataclasses import dataclass, is_dataclass
from datetime import date, datetime
from typing import Any, Mapping, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from qcviz_mcp.compute import pyscf_runner
from qcviz_mcp.compute.job_manager import get_job_manager

try:
    from qcviz_mcp.web.advisor_flow import (
        apply_preset_to_runner_kwargs,
        enrich_result_with_advisor,
        prepare_advisor_plan,
    )
except Exception:  # pragma: no cover
    apply_preset_to_runner_kwargs = None
    enrich_result_with_advisor = None
    prepare_advisor_plan = None

try:
    from qcviz_mcp.web.safety_guard import safety_guard  # type: ignore
except Exception:  # pragma: no cover
    try:
        from qcviz_mcp.safety_guard import safety_guard  # type: ignore
    except Exception:  # pragma: no cover
        safety_guard = None


logger = logging.getLogger("qcviz_mcp.web.routes.compute")
router = APIRouter(tags=["compute"])

_TERMINAL_STATUSES = {
    "done",
    "success",
    "completed",
    "complete",
    "failed",
    "error",
    "cancelled",
    "canceled",
}

_STATUS_ALIASES = {
    "queued": "queued",
    "pending": "queued",
    "submitted": "queued",
    "running": "running",
    "in_progress": "running",
    "processing": "running",
    "done": "completed",
    "success": "completed",
    "completed": "completed",
    "complete": "completed",
    "failed": "error",
    "failure": "error",
    "error": "error",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ComputeJobRequest(BaseModel):
    query: Optional[str] = Field(default=None, description="Natural-language prompt or structure query")
    xyz: Optional[str] = Field(default=None, description="Direct XYZ or atom-spec text")
    charge: int = Field(default=0)
    spin: int = Field(default=0, description="2S value; singlet=0, doublet=1, triplet=2 ...")
    method: Optional[str] = Field(default=None)
    basis: Optional[str] = Field(default=None)
    intent: Optional[str] = Field(default=None)
    display_name: Optional[str] = Field(default=None)

    advisor: bool = Field(default=True)
    include_visualization: Optional[bool] = Field(default=None)
    cube_grid_size: Optional[int] = Field(default=60, ge=30, le=90)

    max_cycle: Optional[int] = Field(default=100)
    max_steps: Optional[int] = Field(default=None)

    wait: bool = Field(default=False)
    timeout_sec: Optional[float] = Field(default=0.0)


@dataclass
class ParsedIntent:
    intent: str
    structure_query: str
    focus_tab: str = "summary"


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _to_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        try:
            return dict(value.__dict__)
        except Exception:
            return {}
    if hasattr(value, "__dict__"):
        try:
            return dict(vars(value))
        except Exception:
            return {}
    return {}


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if is_dataclass(value):
        return _jsonable(value.__dict__)
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
    return str(value)


def _normalize_status(status: Any) -> str:
    raw = str(status or "").strip().lower()
    if not raw:
        return "unknown"
    return _STATUS_ALIASES.get(raw, raw)


def _is_terminal_status(status: Any) -> bool:
    return _normalize_status(status) in {
        "completed",
        "error",
        "cancelled",
    }


def _merge_warnings(result: dict[str, Any], extra: list[str]) -> dict[str, Any]:
    if not extra:
        return result
    result.setdefault("warnings", [])
    existing = set(str(x) for x in result.get("warnings", []) if x)
    for w in extra:
        if w and str(w) not in existing:
            result["warnings"].append(str(w))
            existing.add(str(w))
    return result


def _default_focus_tab(intent_name: str, result: Mapping[str, Any]) -> str:
    if intent_name in {"draft_methods"}:
        return "methods"
    if intent_name in {"generate_script"}:
        return "script"
    if intent_name in {"validate"}:
        return "literature"
    if intent_name in {"partial_charges"}:
        return "charges"
    if intent_name in {"orbital", "orbital_preview"}:
        return "orbitals"
    if intent_name in {"esp", "esp_map"}:
        return "esp"
    if intent_name in {"geometry_opt", "geometry_optimization"}:
        return "geometry"

    viz = _to_mapping(result.get("visualization")) if isinstance(result, Mapping) else {}
    if _to_mapping(viz.get("orbitals")).get("available"):
        return "orbitals"
    if _to_mapping(viz.get("esp")).get("available"):
        return "esp"
    return "summary"


def _prepare_kwargs_for_callable(fn: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """
    Filter kwargs to only those accepted by the target callable unless it
    supports **kwargs. This makes compute.py robust against runner signature
    differences across versions.
    """
    try:
        sig = inspect.signature(fn)
    except Exception:
        return dict(kwargs)

    params = sig.parameters
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return dict(kwargs)

    allowed = set(params.keys())
    return {k: v for k, v in kwargs.items() if k in allowed}


# ---------------------------------------------------------------------------
# Intent parsing
# ---------------------------------------------------------------------------


_INTENT_PATTERNS: list[tuple[str, tuple[str, ...], str]] = [
    ("draft_methods", ("methods section", "methods", "메소드 섹션", "methods 작성", "methods section 작성", "작성해줘"), "methods"),
    ("generate_script", ("pyscf script", "generate script", "script 만들어", "스크립트", "script"), "script"),
    ("validate", ("literature", "validate", "validation", "문헌 검증", "검증해줘", "cccbdb"), "literature"),
    ("partial_charges", ("partial charge", "partial charges", "mulliken", "부분 전하", "charges 계산"), "charges"),
    ("orbital", ("homo", "lumo", "orbital", "frontier orbital", "오비탈"), "orbitals"),
    ("esp", ("electrostatic potential", "esp map", "esp", "mep", "전기정전위"), "esp"),
    ("geometry_opt", ("geometry optimization", "geometry optimise", "optimize geometry", "최적화", "geometry opt"), "geometry"),
    ("geometry_analysis", ("geometry analysis", "bond length", "bond angle", "결합 길이", "각도 분석", "geometry"), "geometry"),
    ("resolve", ("resolve structure", "resolve", "xyz 보여", "xyz", "구조 찾아", "구조 resolve"), "summary"),
    ("single_point", ("single-point", "single point", "energy calculation", "single-point calculation", "에너지 계산"), "summary"),
]


def _canonical_intent(intent: str) -> str:
    raw = str(intent or "").strip().lower()
    if not raw:
        return ""
    aliases = {
        "orbital_preview": "orbital",
        "geometry_optimization": "geometry_opt",
        "geometry_opt": "geometry_opt",
        "opt": "geometry_opt",
        "analyze": "geometry_analysis",
        "analysis": "geometry_analysis",
        "esp_map": "esp",
        "sp": "single_point",
    }
    return aliases.get(raw, raw)


def _extract_structure_query(text: str, inferred_intent: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""

    cleaned = " " + raw + " "
    replacements = [
        r"\bmethods section\b",
        r"\bmethods\b",
        r"\bpyscf script\b",
        r"\bgenerate script\b",
        r"\bpartial charges?\b",
        r"\bmulliken\b",
        r"\bgeometry optimization\b",
        r"\bgeometry optimise\b",
        r"\boptimi[sz]e geometry\b",
        r"\bgeometry opt\b",
        r"\borbital analysis\b",
        r"\bfrontier orbital\b",
        r"\bhomo\b",
        r"\blumo\b",
        r"\borbital\b",
        r"\belectrostatic potential\b",
        r"\besp map\b",
        r"\besp\b",
        r"\bmep\b",
        r"\bliterature\b",
        r"\bvalidate\b",
        r"\bvalidation\b",
        r"\bresolve structure\b",
        r"\bresolve\b",
        r"\bsingle-point calculation\b",
        r"\bsingle-point\b",
        r"\bsingle point\b",
        r"\benergy calculation\b",
        r"문헌 검증해줘",
        r"검증해줘",
        r"계산해줘",
        r"보여줘",
        r"만들어줘",
        r"작성해줘",
        r"구조 찾아줘",
        r"구조 resolve",
        r"오비탈",
        r"부분 전하",
        r"전기정전위",
        r"최적화",
        r"메소드 섹션",
        r"분석해줘",
        r"분석",
    ]
    for pat in replacements:
        cleaned = re.sub(pat, " ", cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.:;!?()[]{}")
    if cleaned:
        return cleaned

    return raw


def _infer_intent(explicit_intent: str | None, raw_text: str | None) -> ParsedIntent:
    canonical = _canonical_intent(explicit_intent or "")
    text = str(raw_text or "").strip()

    if canonical:
        return ParsedIntent(
            intent=canonical,
            structure_query=_extract_structure_query(text, canonical) or text,
            focus_tab=_default_focus_tab(canonical, {}),
        )

    lowered = text.lower()
    for intent_name, needles, focus_tab in _INTENT_PATTERNS:
        if any(n in lowered for n in needles):
            return ParsedIntent(
                intent=intent_name,
                structure_query=_extract_structure_query(text, intent_name) or text,
                focus_tab=focus_tab,
            )

    return ParsedIntent(
        intent="single_point",
        structure_query=text,
        focus_tab="summary",
    )


def _resolve_runner(intent_name: str):
    intent_name = _canonical_intent(intent_name)

    if intent_name == "resolve":
        return pyscf_runner.run_resolve_structure
    if intent_name in {"geometry_analysis", "analyze", "validate"}:
        return pyscf_runner.run_geometry_analysis
    if intent_name in {"geometry_opt", "geometry_optimization"}:
        return pyscf_runner.run_geometry_optimization
    if intent_name == "partial_charges":
        return pyscf_runner.run_partial_charges
    if intent_name in {"orbital", "orbital_preview"}:
        return pyscf_runner.run_orbital_preview
    if intent_name in {"esp", "esp_map"} and hasattr(pyscf_runner, "run_esp_map"):
        return pyscf_runner.run_esp_map
    return pyscf_runner.run_single_point


def _build_job_label(intent_name: str, display_name: str | None, structure_query: str | None) -> str:
    subject = (display_name or structure_query or "molecule").strip()
    subject = re.sub(r"\s+", " ", subject)[:80]
    return f"{intent_name}:{subject}"


# ---------------------------------------------------------------------------
# Safety / advisor wrappers
# ---------------------------------------------------------------------------


def _evaluate_safety(payload: Mapping[str, Any]) -> dict[str, Any]:
    if safety_guard is None:
        return {"allowed": True, "warnings": []}

    evaluator = getattr(safety_guard, "evaluate_request", None)
    if not callable(evaluator):
        return {"allowed": True, "warnings": []}

    try:
        verdict = evaluator(_jsonable(payload))
    except Exception as exc:
        logger.warning("Safety evaluation failed; allowing request. error=%s", exc)
        return {"allowed": True, "warnings": [f"Safety evaluator failed: {exc}"]}

    data = _to_mapping(verdict)
    blocked = bool(data.get("blocked") or data.get("reject") or data.get("denied") or (data.get("allowed") is False))
    warnings = data.get("warnings") or []
    if not isinstance(warnings, list):
        warnings = [str(warnings)] if warnings else []

    return {
        "allowed": not blocked,
        "warnings": [str(x) for x in warnings if x],
        "reason": data.get("reason") or data.get("message"),
        "raw": data,
    }


async def _await_maybe(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _run_awaitable_sync(value: Any) -> Any:
    if not inspect.isawaitable(value):
        return value

    try:
        asyncio.get_running_loop()
        loop_running = True
    except RuntimeError:
        loop_running = False

    if not loop_running:
        return asyncio.run(value)

    new_loop = asyncio.new_event_loop()
    try:
        return new_loop.run_until_complete(value)
    finally:
        new_loop.close()


async def _prepare_advisor_plan_safe(**kwargs: Any) -> Any:
    if prepare_advisor_plan is None:
        return None

    attempts = [
        lambda: prepare_advisor_plan(**kwargs),
        lambda: prepare_advisor_plan(
            kwargs.get("query"),
            kwargs.get("xyz"),
            kwargs.get("charge"),
            kwargs.get("spin"),
            kwargs.get("intent"),
        ),
        lambda: prepare_advisor_plan(
            query=kwargs.get("query"),
            xyz=kwargs.get("xyz"),
            charge=kwargs.get("charge"),
            spin=kwargs.get("spin"),
        ),
    ]

    last_exc: Exception | None = None
    for attempt in attempts:
        try:
            return await _await_maybe(attempt())
        except TypeError as exc:
            last_exc = exc
            continue
        except Exception as exc:
            logger.warning("prepare_advisor_plan failed: %s", exc)
            return None

    if last_exc:
        logger.debug("prepare_advisor_plan signature mismatch: %s", last_exc)
    return None


def _apply_preset_safe(advisor_plan: Any, runner_kwargs: dict[str, Any]) -> dict[str, Any]:
    if apply_preset_to_runner_kwargs is None or not advisor_plan:
        return runner_kwargs

    attempts = [
        lambda: apply_preset_to_runner_kwargs(advisor_plan, runner_kwargs),
        lambda: apply_preset_to_runner_kwargs(advisor_plan=advisor_plan, runner_kwargs=runner_kwargs),
        lambda: apply_preset_to_runner_kwargs(runner_kwargs, advisor_plan),
    ]

    for attempt in attempts:
        try:
            updated = attempt()
            if isinstance(updated, Mapping):
                return dict(updated)
            return runner_kwargs
        except TypeError:
            continue
        except Exception as exc:
            logger.warning("apply_preset_to_runner_kwargs failed: %s", exc)
            return runner_kwargs

    return runner_kwargs


def _enrich_result_safe(
    result: dict[str, Any],
    *,
    intent_name: str,
    advisor_plan: Any = None,
) -> dict[str, Any]:
    if enrich_result_with_advisor is None:
        return result

    attempts = [
        lambda: enrich_result_with_advisor(result=result, intent=intent_name, advisor_plan=advisor_plan),
        lambda: enrich_result_with_advisor(result=result, intent_name=intent_name, advisor_plan=advisor_plan),
        lambda: enrich_result_with_advisor(result=result),
        lambda: enrich_result_with_advisor(result, intent_name, advisor_plan),
    ]

    for attempt in attempts:
        try:
            enriched = _run_awaitable_sync(attempt())
            if isinstance(enriched, Mapping):
                return dict(enriched)
            return result
        except TypeError:
            continue
        except Exception as exc:
            logger.warning("enrich_result_with_advisor failed: %s", exc)
            return result

    return result


# ---------------------------------------------------------------------------
# Job manager compatibility wrappers
# ---------------------------------------------------------------------------


def _jm_submit(
    jm: Any,
    fn: Any,
    *,
    kwargs: dict[str, Any],
    name: str,
    metadata: Optional[dict[str, Any]] = None,
) -> str:
    metadata = metadata or {}

    attempts = [
        lambda: jm.submit(fn=fn, kwargs=kwargs, name=name, metadata=metadata),
        lambda: jm.submit(func=fn, kwargs=kwargs, name=name, metadata=metadata),
        lambda: jm.submit(target=fn, kwargs=kwargs, name=name, metadata=metadata),
        lambda: jm.submit(fn, kwargs=kwargs, name=name, metadata=metadata),
        lambda: jm.submit(target=fn, kwargs=kwargs, label=name),
        lambda: jm.submit(func=fn, kwargs=kwargs, name=name),
        lambda: jm.submit(fn, kwargs=kwargs, name=name),
        lambda: jm.submit(fn, kwargs=kwargs, label=name),
        lambda: jm.submit(fn, name=name, metadata=metadata, **kwargs),
        lambda: jm.submit(fn, **kwargs),
    ]

    last_exc: Exception | None = None
    for attempt in attempts:
        try:
            value = attempt()
            if isinstance(value, (str, int)):
                return str(value)
            data = _to_mapping(value)
            job_id = data.get("job_id") or data.get("id")
            if job_id is not None:
                return str(job_id)
        except TypeError as exc:
            last_exc = exc
            continue

    raise RuntimeError(f"JobManager.submit signature unsupported: {last_exc}")


def _jm_get(jm: Any, job_id: str) -> Any:
    attempts = []
    if hasattr(jm, "get"):
        attempts.append(lambda: jm.get(job_id))
    if hasattr(jm, "get_job"):
        attempts.append(lambda: jm.get_job(job_id))
    if hasattr(jm, "fetch"):
        attempts.append(lambda: jm.fetch(job_id))

    for attempt in attempts:
        try:
            return attempt()
        except Exception:
            continue
    return None


def _jm_list(jm: Any) -> list[Any]:
    candidates = [
        getattr(jm, "list_jobs", None),
        getattr(jm, "list", None),
        getattr(jm, "all_jobs", None),
        getattr(jm, "all", None),
    ]
    for fn in candidates:
        if callable(fn):
            try:
                data = fn()
                return list(data or [])
            except Exception:
                continue

    jobs_obj = getattr(jm, "jobs", None)
    if isinstance(jobs_obj, Mapping):
        return list(jobs_obj.values())
    if isinstance(jobs_obj, list):
        return list(jobs_obj)
    return []


def _jm_drain_events(jm: Any, job_id: str) -> list[Any]:
    candidates = [
        getattr(jm, "drain_events", None),
        getattr(jm, "get_events", None),
        getattr(jm, "drain", None),
    ]
    for fn in candidates:
        if callable(fn):
            try:
                data = fn(job_id)
                return list(data or [])
            except Exception:
                continue
    return []


def _jm_cancel(jm: Any, job_id: str) -> bool:
    candidates = [
        getattr(jm, "cancel", None),
        getattr(jm, "cancel_job", None),
        getattr(jm, "stop", None),
    ]
    for fn in candidates:
        if callable(fn):
            try:
                value = fn(job_id)
                return bool(True if value is None else value)
            except Exception:
                continue
    return False


def _serialize_job_record(record: Any) -> dict[str, Any]:
    if record is None:
        return {}

    data = _to_mapping(record)
    result = _jsonable(data)

    job_id = result.get("job_id") or result.get("id")
    status = result.get("status") or result.get("state")
    progress = result.get("progress", 0)
    step = result.get("step") or result.get("phase") or ""
    detail = result.get("detail") or result.get("message") or ""

    result["job_id"] = job_id
    result["status"] = _normalize_status(status)
    result["progress"] = _safe_float(progress, 0.0)
    result["step"] = step
    result["detail"] = detail
    return result


def _serialize_event(event: Any) -> dict[str, Any]:
    data = _to_mapping(event)
    data = _jsonable(data)
    if "level" not in data:
        data["level"] = "info"
    return data


# ---------------------------------------------------------------------------
# Core compute job
# ---------------------------------------------------------------------------


def _run_compute_job(
    *,
    intent_name: str,
    original_prompt: str | None,
    structure_query: str | None,
    xyz: str | None,
    charge: int,
    spin: int,
    display_name: str | None,
    method: str | None,
    basis: str | None,
    advisor_enabled: bool,
    advisor_plan: Any = None,
    include_visualization: bool = True,
    cube_grid_size: int = 60,
    max_cycle: Optional[int] = None,
    max_steps: Optional[int] = None,
    progress_callback: Any = None,
    emit_event: Any = None,
    is_cancelled: Any = None,
    **extra: Any,
) -> dict[str, Any]:
    runner = _resolve_runner(intent_name)

    runner_kwargs: dict[str, Any] = {
        "query": structure_query or original_prompt,
        "xyz": xyz,
        "charge": charge,
        "spin": spin,
        "display_name": display_name,
        "method": method,
        "basis": basis,
        "include_visualization": include_visualization,
        "cube_grid_size": cube_grid_size,
        "progress_callback": progress_callback,
        "emit_event": emit_event,
        "is_cancelled": is_cancelled,
    }
    if max_cycle is not None:
        runner_kwargs["max_cycle"] = max_cycle
    if max_steps is not None:
        runner_kwargs["max_steps"] = max_steps
    runner_kwargs.update(extra)

    filtered_runner_kwargs = _prepare_kwargs_for_callable(runner, runner_kwargs)
    result = runner(**filtered_runner_kwargs)
    result = _run_awaitable_sync(result)

    if not isinstance(result, Mapping):
        result = {"value": result}
    else:
        result = dict(result)

    result.setdefault("intent", intent_name)
    result.setdefault("original_prompt", original_prompt)
    result.setdefault("structure_query", structure_query or original_prompt)
    result.setdefault("method", method)
    result.setdefault("basis", basis)
    result.setdefault("charge", charge)
    result.setdefault("spin", spin)
    result["include_visualization"] = include_visualization
    result["cube_grid_size"] = cube_grid_size

    if advisor_plan:
        result["advisor_plan"] = _jsonable(advisor_plan)

    if advisor_enabled:
        result = _enrich_result_safe(result, intent_name=intent_name, advisor_plan=advisor_plan)

    result["advisor_focus_tab"] = _default_focus_tab(intent_name, result)
    return result


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------


@router.post("/compute/jobs")
async def submit_compute_job(req: ComputeJobRequest) -> dict[str, Any]:
    raw_prompt = (req.query or "").strip()
    parsed = _infer_intent(req.intent, raw_prompt)

    structure_query = ""
    if req.xyz and str(req.xyz).strip():
        structure_query = (req.display_name or raw_prompt or "direct structure").strip()
    else:
        structure_query = (parsed.structure_query or raw_prompt).strip()

    if not structure_query and not (req.xyz and str(req.xyz).strip()):
        raise HTTPException(status_code=422, detail="Provide either query or xyz/atom-spec input.")

    intent_name = parsed.intent
    display_name = (req.display_name or structure_query or "molecule").strip()

    safety_payload = {
        "prompt": raw_prompt,
        "structure_query": structure_query,
        "xyz": req.xyz,
        "intent": intent_name,
        "charge": req.charge,
        "spin": req.spin,
        "method": req.method,
        "basis": req.basis,
    }
    safety = _evaluate_safety(safety_payload)
    if not safety.get("allowed", True):
        raise HTTPException(
            status_code=400,
            detail={
                "message": safety.get("reason") or "Request blocked by safety policy.",
                "warnings": safety.get("warnings", []),
            },
        )

    include_visualization = (
        req.include_visualization
        if req.include_visualization is not None
        else intent_name in {"single_point", "orbital", "orbital_preview", "partial_charges", "esp", "esp_map"}
    )

    runner_kwargs: dict[str, Any] = {
        "intent_name": intent_name,
        "original_prompt": raw_prompt or structure_query,
        "structure_query": structure_query,
        "xyz": req.xyz,
        "charge": int(req.charge or 0),
        "spin": int(req.spin or 0),
        "display_name": display_name,
        "method": req.method,
        "basis": req.basis,
        "advisor_enabled": bool(req.advisor),
        "include_visualization": bool(include_visualization),
        "cube_grid_size": max(30, min(90, int(req.cube_grid_size or 60))),
        "max_cycle": req.max_cycle,
        "max_steps": req.max_steps,
    }

    advisor_plan = None
    advisor_warnings: list[str] = []
    if req.advisor:
        advisor_plan = await _prepare_advisor_plan_safe(
            query=structure_query or raw_prompt,
            xyz=req.xyz,
            charge=req.charge,
            spin=req.spin,
            intent=intent_name,
        )
        if advisor_plan:
            runner_kwargs["advisor_plan"] = advisor_plan
            before_method = runner_kwargs.get("method")
            before_basis = runner_kwargs.get("basis")
            runner_kwargs = _apply_preset_safe(advisor_plan, runner_kwargs)
            if before_method != runner_kwargs.get("method") or before_basis != runner_kwargs.get("basis"):
                advisor_warnings.append("Advisor preset applied to method/basis selection.")

    metadata = {
        "intent": intent_name,
        "display_name": display_name,
        "structure_query": structure_query,
        "advisor": bool(req.advisor),
        "include_visualization": bool(include_visualization),
        "cube_grid_size": runner_kwargs["cube_grid_size"],
        "focus_tab": parsed.focus_tab,
    }

    jm = get_job_manager()
    label = _build_job_label(intent_name, display_name, structure_query)
    try:
        job_id = _jm_submit(
            jm,
            _run_compute_job,
            kwargs=runner_kwargs,
            name=label,
            metadata=metadata,
        )
    except Exception as exc:
        logger.exception("Failed to submit compute job")
        raise HTTPException(status_code=500, detail=f"Failed to submit job: {exc}") from exc

    response = {
        "job_id": job_id,
        "label": label,
        "status": "queued",
        "intent": intent_name,
        "display_name": display_name,
        "structure_query": structure_query,
        "xyz_supplied": bool(req.xyz and str(req.xyz).strip()),
        "method": runner_kwargs.get("method"),
        "basis": runner_kwargs.get("basis"),
        "advisor": bool(req.advisor),
        "include_visualization": bool(include_visualization),
        "cube_grid_size": runner_kwargs["cube_grid_size"],
        "advisor_focus_tab": parsed.focus_tab,
        "warnings": list(safety.get("warnings", [])) + advisor_warnings,
    }

    if req.wait:
        timeout = max(0.0, _safe_float(req.timeout_sec, 0.0))
        started = time.monotonic()
        while True:
            record = _jm_get(jm, job_id)
            data = _serialize_job_record(record)
            status = data.get("status")
            if _is_terminal_status(status):
                response["job"] = data
                return response
            if timeout > 0 and (time.monotonic() - started) >= timeout:
                response["job"] = data
                response["timed_out"] = True
                return response
            await asyncio.sleep(0.20)

    return response


@router.get("/compute/jobs")
async def list_compute_jobs() -> dict[str, Any]:
    jm = get_job_manager()
    jobs = [_serialize_job_record(x) for x in _jm_list(jm)]
    jobs.sort(key=lambda x: str(x.get("updated_at") or x.get("created_at") or ""), reverse=True)
    return {
        "count": len(jobs),
        "items": jobs,
    }


@router.get("/compute/jobs/{job_id}")
async def get_compute_job(
    job_id: str,
    wait: bool = Query(default=False),
    timeout_sec: float = Query(default=0.0, ge=0.0),
) -> dict[str, Any]:
    jm = get_job_manager()

    if wait:
        started = time.monotonic()
        while True:
            record = _jm_get(jm, job_id)
            if record is None:
                raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
            data = _serialize_job_record(record)
            if _is_terminal_status(data.get("status")):
                return data
            if timeout_sec > 0 and (time.monotonic() - started) >= timeout_sec:
                data["timed_out"] = True
                return data
            await asyncio.sleep(0.20)

    record = _jm_get(jm, job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return _serialize_job_record(record)


@router.get("/compute/jobs/{job_id}/events")
async def get_compute_job_events(job_id: str) -> dict[str, Any]:
    jm = get_job_manager()
    record = _jm_get(jm, job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    events = [_serialize_event(ev) for ev in _jm_drain_events(jm, job_id)]
    return {
        "job_id": job_id,
        "count": len(events),
        "items": events,
    }


@router.post("/compute/jobs/{job_id}/cancel")
async def cancel_compute_job(job_id: str) -> dict[str, Any]:
    jm = get_job_manager()
    record = _jm_get(jm, job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    ok = _jm_cancel(jm, job_id)
    return {
        "job_id": job_id,
        "accepted": bool(ok),
        "status": "cancelling" if ok else "cancel_unsupported",
    }

```

## [pyscf_runner.py]

경로: `version02/src/qcviz_mcp/compute/pyscf_runner.py`

```python
from __future__ import annotations

import base64
import logging
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

import numpy as np
from pyscf import dft, gto, scf

try:
    from pyscf.geomopt.geometric_solver import optimize as geometric_optimize
except Exception:  # pragma: no cover
    geometric_optimize = None

try:
    from pyscf.tools import cubegen
except Exception:  # pragma: no cover
    cubegen = None

try:
    from qcviz_mcp.tools.core import MoleculeResolver  # type: ignore
    _MOLECULE_RESOLVER_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover
    MoleculeResolver = None  # type: ignore
    _MOLECULE_RESOLVER_IMPORT_ERROR = exc


logger = logging.getLogger("qcviz_mcp.compute.pyscf_runner")

HARTREE_TO_EV = 27.211386245988
DEFAULT_METHOD = "B3LYP"
DEFAULT_BASIS = "def2-SVP"

_COVALENT_RADII = {
    "H": 0.31,
    "He": 0.28,
    "Li": 1.28,
    "Be": 0.96,
    "B": 0.84,
    "C": 0.76,
    "N": 0.71,
    "O": 0.66,
    "F": 0.57,
    "Ne": 0.58,
    "Na": 1.66,
    "Mg": 1.41,
    "Al": 1.21,
    "Si": 1.11,
    "P": 1.07,
    "S": 1.05,
    "Cl": 1.02,
    "Ar": 1.06,
    "K": 2.03,
    "Ca": 1.76,
    "Sc": 1.70,
    "Ti": 1.60,
    "V": 1.53,
    "Cr": 1.39,
    "Mn": 1.39,
    "Fe": 1.32,
    "Co": 1.26,
    "Ni": 1.24,
    "Cu": 1.32,
    "Zn": 1.22,
    "Ga": 1.22,
    "Ge": 1.20,
    "As": 1.19,
    "Se": 1.20,
    "Br": 1.20,
    "Kr": 1.16,
    "Rb": 2.20,
    "Sr": 1.95,
    "Y": 1.90,
    "Zr": 1.75,
    "Nb": 1.64,
    "Mo": 1.54,
    "Tc": 1.47,
    "Ru": 1.46,
    "Rh": 1.42,
    "Pd": 1.39,
    "Ag": 1.45,
    "Cd": 1.44,
    "In": 1.42,
    "Sn": 1.39,
    "Sb": 1.39,
    "Te": 1.38,
    "I": 1.39,
    "Xe": 1.40,
}

ESP_PRESETS_DATA = {
    "rwb": {"name": "Standard RWB", "gradient_type": "rwb", "colors": []},
    "nature": {"name": "Nature", "gradient_type": "linear", "colors": ["#e91e63", "#ffffff", "#00bcd4"]},
    "acs": {"name": "ACS Gold", "gradient_type": "linear", "colors": ["#e65100", "#fffde7", "#4a148c"]},
    "rsc": {"name": "RSC Pastel", "gradient_type": "linear", "colors": ["#ff8a80", "#f5f5f5", "#82b1ff"]},
    "viridis": {"name": "Viridis", "gradient_type": "linear", "colors": ["#440154", "#31688e", "#21918c", "#35b779", "#fde725"]},
    "inferno": {"name": "Inferno", "gradient_type": "linear", "colors": ["#000004", "#420a68", "#932667", "#dd513a", "#fcffa4"]},
    "spectral": {"name": "Spectral", "gradient_type": "linear", "colors": ["#d53e4f", "#fc8d59", "#fee08b", "#e6f598", "#99d594", "#3288bd"]},
    "grey": {"name": "Greyscale", "gradient_type": "linear", "colors": ["#212121", "#9e9e9e", "#fafafa"]},
    "matdark": {"name": "Materials Dark", "gradient_type": "linear", "colors": ["#ff6f00", "#1a1a2e", "#00e5ff"]},
    "hicon": {"name": "High Contrast", "gradient_type": "linear", "colors": ["#ff1744", "#000000", "#2979ff"]},
}

_BUILTIN_STRUCTURES_XYZ = {
    "water": """3
water
O      0.000000   0.000000   0.000000
H      0.758602   0.000000   0.504284
H     -0.758602   0.000000   0.504284
""",
    "h2o": """3
water
O      0.000000   0.000000   0.000000
H      0.758602   0.000000   0.504284
H     -0.758602   0.000000   0.504284
""",
    "methane": """5
methane
C      0.000000   0.000000   0.000000
H      0.629118   0.629118   0.629118
H     -0.629118  -0.629118   0.629118
H     -0.629118   0.629118  -0.629118
H      0.629118  -0.629118  -0.629118
""",
    "ch4": """5
methane
C      0.000000   0.000000   0.000000
H      0.629118   0.629118   0.629118
H     -0.629118  -0.629118   0.629118
H     -0.629118   0.629118  -0.629118
H      0.629118  -0.629118  -0.629118
""",
    "ammonia": """4
ammonia
N      0.000000   0.000000   0.100000
H      0.000000   0.937700  -0.280000
H      0.811900  -0.468850  -0.280000
H     -0.811900  -0.468850  -0.280000
""",
    "nh3": """4
ammonia
N      0.000000   0.000000   0.100000
H      0.000000   0.937700  -0.280000
H      0.811900  -0.468850  -0.280000
H     -0.811900  -0.468850  -0.280000
""",
    "carbon dioxide": """3
carbon dioxide
O     -1.160000   0.000000   0.000000
C      0.000000   0.000000   0.000000
O      1.160000   0.000000   0.000000
""",
    "co2": """3
carbon dioxide
O     -1.160000   0.000000   0.000000
C      0.000000   0.000000   0.000000
O      1.160000   0.000000   0.000000
""",
    "methanol": """6
methanol
C      0.000000   0.000000   0.000000
O      1.410000   0.000000   0.000000
H     -0.540000   0.935000   0.000000
H     -0.540000  -0.467500   0.809000
H     -0.540000  -0.467500  -0.809000
H      1.815000   0.000000   0.890000
""",
    "ethanol": """9
ethanol
C     -0.925370   0.074208   0.032839
C      0.512318  -0.419182  -0.074315
O      1.377821   0.449379   0.604428
H     -1.022525   1.073072  -0.442857
H     -1.604437  -0.636788  -0.483222
H     -1.223596   0.147243   1.100206
H      0.805780  -0.506016  -1.145105
H      0.585213  -1.427396   0.385335
H      2.495486   0.031525   0.585188
""",
    "benzene": """12
benzene
C      1.396792   0.000000   0.000000
H      2.490298   0.000000   0.000000
C      0.698396   1.209951   0.000000
H      1.245149   2.157087   0.000000
C     -0.698396   1.209951   0.000000
H     -1.245149   2.157087   0.000000
C     -1.396792   0.000000   0.000000
H     -2.490298   0.000000   0.000000
C     -0.698396  -1.209951   0.000000
H     -1.245149  -2.157087   0.000000
C      0.698396  -1.209951   0.000000
H      1.245149  -2.157087   0.000000
""",
    "pyridine": """11
pyridine
N      1.340000   0.000000   0.000000
C      0.671000   1.161000   0.000000
C     -0.671000   1.161000   0.000000
C     -1.340000   0.000000   0.000000
C     -0.671000  -1.161000   0.000000
C      0.671000  -1.161000   0.000000
H      1.229000   2.095000   0.000000
H     -1.229000   2.095000   0.000000
H     -2.420000   0.000000   0.000000
H     -1.229000  -2.095000   0.000000
H      1.229000  -2.095000   0.000000
""",
    "acetamide": """9
acetamide
C     -1.207000   0.000000   0.000000
H     -1.567000  -0.510000   0.889000
H     -1.567000   1.022000   0.000000
H     -1.567000  -0.510000  -0.889000
C      0.287000   0.000000   0.000000
O      0.874000   1.046000   0.000000
N      0.949000  -1.156000   0.000000
H      1.960000  -1.088000   0.000000
H      0.535000  -2.078000   0.000000
""",
    "naphthalene": """18
naphthalene
C      0.000000   1.402720   0.000000
C      1.214790   0.701360   0.000000
C      1.214790  -0.701360   0.000000
C      0.000000  -1.402720   0.000000
C     -1.214790  -0.701360   0.000000
C     -1.214790   0.701360   0.000000
C      2.429580   1.402720   0.000000
C      3.644370   0.701360   0.000000
C      3.644370  -0.701360   0.000000
C      2.429580  -1.402720   0.000000
H      0.000000   2.490290   0.000000
H     -2.156660   1.245140   0.000000
H     -2.156660  -1.245140   0.000000
H      0.000000  -2.490290   0.000000
H      2.429580   2.490290   0.000000
H      4.586240   1.245140   0.000000
H      4.586240  -1.245140   0.000000
H      2.429580  -2.490290   0.000000
""",
}


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _to_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "__dict__"):
        try:
            return dict(vars(value))
        except Exception:
            return {}
    return {}


def _report(
    progress: float,
    step: str,
    detail: str,
    *,
    progress_callback: Any = None,
    emit_event: Any = None,
) -> None:
    pct = max(0.0, min(100.0, float(progress)))
    if callable(progress_callback):
        try:
            progress_callback(pct, step, detail)
        except TypeError:
            try:
                progress_callback(progress=pct, step=step, detail=detail)
            except Exception:
                pass
        except Exception:
            pass
    if callable(emit_event):
        try:
            emit_event({"level": "info", "step": step, "detail": detail, "progress": pct})
        except Exception:
            pass


def _emit_warning(message: str, *, warnings: list[str], emit_event: Any = None) -> None:
    if message:
        warnings.append(message)
        if callable(emit_event):
            try:
                emit_event({"level": "warning", "detail": message})
            except Exception:
                pass


def _check_cancel(is_cancelled: Any) -> None:
    if callable(is_cancelled):
        try:
            if is_cancelled():
                raise RuntimeError("Job cancelled")
        except RuntimeError:
            raise
        except Exception:
            return


# ---------------------------------------------------------------------------
# Structure parsing / normalization
# ---------------------------------------------------------------------------


def _looks_like_xyz(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    lines = [ln.rstrip() for ln in raw.splitlines()]
    if len(lines) < 3:
        return False
    if not lines[0].strip().isdigit():
        return False
    natm = int(lines[0].strip())
    return len([ln for ln in lines[2:] if ln.strip()]) >= natm


def _looks_like_atom_spec(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return False
    for line in lines:
        parts = line.split()
        if len(parts) < 4:
            return False
        if not parts[0][0].isalpha():
            return False
        try:
            float(parts[1]); float(parts[2]); float(parts[3])
        except Exception:
            return False
    return True


def _atom_spec_to_xyz(atom_spec: str, comment: str = "generated from atom spec") -> str:
    lines = [ln.strip() for ln in str(atom_spec or "").splitlines() if ln.strip()]
    return f"{len(lines)}\n{comment}\n" + "\n".join(lines) + "\n"


def _xyz_to_atom_spec(xyz: str) -> str:
    atoms = _parse_xyz_atoms(xyz)
    return "\n".join(f"{a['symbol']} {a['x']:.10f} {a['y']:.10f} {a['z']:.10f}" for a in atoms)


def _normalize_structure_text(text: str, comment: str = "resolved structure") -> str:
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("Empty structure text")
    if _looks_like_xyz(raw):
        return raw if raw.endswith("\n") else (raw + "\n")
    if _looks_like_atom_spec(raw):
        return _atom_spec_to_xyz(raw, comment=comment)
    raise ValueError("Input is neither valid XYZ nor valid atom-spec")


def _parse_xyz_atoms(xyz: str) -> list[dict[str, Any]]:
    raw = str(xyz or "").strip()
    if not raw:
        return []

    lines = [ln.rstrip() for ln in raw.splitlines()]
    if not lines:
        return []

    atoms: list[dict[str, Any]] = []

    if _looks_like_xyz(raw):
        natm = int(lines[0].strip())
        start = 2
        atom_lines = [ln for ln in lines[start:] if ln.strip()][:natm]
    elif _looks_like_atom_spec(raw):
        atom_lines = [ln for ln in lines if ln.strip()]
    else:
        raise ValueError("Cannot parse structure text as XYZ or atom-spec")

    for idx, line in enumerate(atom_lines):
        parts = line.split()
        if len(parts) < 4:
            continue
        atoms.append(
            {
                "index": idx + 1,
                "symbol": parts[0],
                "x": float(parts[1]),
                "y": float(parts[2]),
                "z": float(parts[3]),
            }
        )
    return atoms


def _formula_from_atoms(symbols: Iterable[str]) -> str:
    counts: dict[str, int] = {}
    for sym in symbols:
        counts[sym] = counts.get(sym, 0) + 1

    out: list[str] = []
    for sym in ("C", "H"):
        if sym in counts:
            n = counts.pop(sym)
            out.append(sym if n == 1 else f"{sym}{n}")
    for sym in sorted(counts):
        n = counts[sym]
        out.append(sym if n == 1 else f"{sym}{n}")
    return "".join(out) or "Unknown"


def _formula_from_xyz(xyz: str) -> str:
    atoms = _parse_xyz_atoms(xyz)
    return _formula_from_atoms(a["symbol"] for a in atoms)


def _infer_display_name(query: str | None, xyz: str | None, explicit: str | None = None) -> str:
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    if query and str(query).strip():
        first = str(query).strip().splitlines()[0].strip()
        return first[:120]
    if xyz:
        return _formula_from_xyz(xyz)
    return "Molecule"


def _xyz_from_mol(mol: gto.Mole) -> str:
    coords = mol.atom_coords(unit="Angstrom")
    lines = [str(mol.natm), "generated by PySCF"]
    for i in range(mol.natm):
        sym = mol.atom_symbol(i)
        x, y, z = coords[i]
        lines.append(f"{sym} {x:.10f} {y:.10f} {z:.10f}")
    return "\n".join(lines) + "\n"


def _distance(a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
    dx = float(a["x"]) - float(b["x"])
    dy = float(a["y"]) - float(b["y"])
    dz = float(a["z"]) - float(b["z"])
    return float(math.sqrt(dx * dx + dy * dy + dz * dz))


def _angle(a: Mapping[str, Any], b: Mapping[str, Any], c: Mapping[str, Any]) -> float:
    v1 = np.array([float(a["x"]) - float(b["x"]), float(a["y"]) - float(b["y"]), float(a["z"]) - float(b["z"])], dtype=float)
    v2 = np.array([float(c["x"]) - float(b["x"]), float(c["y"]) - float(b["y"]), float(c["z"]) - float(b["z"])], dtype=float)
    n1 = np.linalg.norm(v1)
    n2 = np.linalg.norm(v2)
    if n1 < 1e-12 or n2 < 1e-12:
        return float("nan")
    cosang = float(np.dot(v1, v2) / (n1 * n2))
    cosang = max(-1.0, min(1.0, cosang))
    return float(np.degrees(np.arccos(cosang)))


def _bond_threshold(sym1: str, sym2: str) -> float:
    r1 = _COVALENT_RADII.get(sym1, 0.77)
    r2 = _COVALENT_RADII.get(sym2, 0.77)
    return 1.25 * (r1 + r2) + 0.10


def _guess_bonds(atoms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bonds: list[dict[str, Any]] = []
    for i in range(len(atoms)):
        for j in range(i + 1, len(atoms)):
            ai = atoms[i]
            aj = atoms[j]
            dist = _distance(ai, aj)
            if dist <= _bond_threshold(ai["symbol"], aj["symbol"]):
                bonds.append(
                    {
                        "i": ai["index"],
                        "j": aj["index"],
                        "label": f"{ai['symbol']}{ai['index']}-{aj['symbol']}{aj['index']}",
                        "pair": f"{ai['index']}-{aj['index']}",
                        "distance_angstrom": dist,
                    }
                )
    return bonds


def _guess_angles(atoms: list[dict[str, Any]], bonds: list[dict[str, Any]], max_angles: int = 240) -> list[dict[str, Any]]:
    neighbors: dict[int, list[int]] = {}
    for b in bonds:
        neighbors.setdefault(int(b["i"]), []).append(int(b["j"]))
        neighbors.setdefault(int(b["j"]), []).append(int(b["i"]))

    by_index = {int(a["index"]): a for a in atoms}
    angles: list[dict[str, Any]] = []

    for center, nbrs in neighbors.items():
        if len(nbrs) < 2:
            continue
        nbrs = sorted(set(nbrs))
        for i in range(len(nbrs)):
            for k in range(i + 1, len(nbrs)):
                a = by_index[nbrs[i]]
                b = by_index[center]
                c = by_index[nbrs[k]]
                ang = _angle(a, b, c)
                if math.isnan(ang):
                    continue
                angles.append(
                    {
                        "label": f"{a['symbol']}{a['index']}-{b['symbol']}{b['index']}-{c['symbol']}{c['index']}",
                        "angle_deg": ang,
                    }
                )
                if len(angles) >= max_angles:
                    return angles
    return angles


def _summarize_geometry(xyz: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, str]:
    atoms = _parse_xyz_atoms(xyz)
    bonds = _guess_bonds(atoms)
    angles = _guess_angles(atoms, bonds)
    formula = _formula_from_atoms(a["symbol"] for a in atoms)
    return bonds, angles, len(atoms), formula


# ---------------------------------------------------------------------------
# Resolver handling
# ---------------------------------------------------------------------------


def _get_molecule_resolver():
    if MoleculeResolver is not None:
        try:
            return MoleculeResolver()
        except Exception:
            pass

    class _FallbackResolver:
        def resolve(self, query: str):
            q = str(query or "").strip()
            if not q:
                raise ValueError("Empty structure query")
            if _looks_like_xyz(q) or _looks_like_atom_spec(q):
                return {
                    "display_name": q.splitlines()[0][:80],
                    "xyz": q if _looks_like_xyz(q) else _atom_spec_to_xyz(q),
                    "warnings": [
                        "MoleculeResolver unavailable; using direct structure text only.",
                    ],
                }

            key = q.lower().strip()
            if key in _BUILTIN_STRUCTURES_XYZ:
                return {
                    "display_name": q,
                    "xyz": _BUILTIN_STRUCTURES_XYZ[key],
                    "warnings": [
                        "Using built-in fallback structure library because MoleculeResolver is unavailable.",
                    ],
                }

            raise ValueError(
                f"Could not resolve '{q}'. Provide XYZ/atom-spec text or restore qcviz_mcp.tools.core MoleculeResolver."
            )

    return _FallbackResolver()


def _extract_resolver_xyz(resolved: Any) -> tuple[Optional[str], Optional[str], list[str]]:
    warnings: list[str] = []

    if isinstance(resolved, str):
        try:
            return _normalize_structure_text(resolved), None, warnings
        except Exception:
            return None, resolved.strip() or None, warnings

    data = _to_mapping(resolved)
    xyz = (
        data.get("xyz")
        or data.get("resolved_xyz")
        or data.get("structure_xyz")
        or data.get("geometry_xyz")
        or data.get("atom_spec")
        or data.get("structure")
    )
    name = data.get("display_name") or data.get("name") or data.get("label")
    wrn = data.get("warnings")
    if isinstance(wrn, list):
        warnings.extend(str(x) for x in wrn if x)
    elif wrn:
        warnings.append(str(wrn))

    if xyz:
        try:
            return _normalize_structure_text(str(xyz)), (str(name) if name else None), warnings
        except Exception:
            pass

    return None, (str(name) if name else None), warnings


def _resolve_structure_input(
    *,
    query: str | None = None,
    xyz: str | None = None,
    display_name: str | None = None,
    warnings: list[str] | None = None,
) -> tuple[str, str, list[str]]:
    out_warnings = warnings if warnings is not None else []

    if xyz and str(xyz).strip():
        normalized = _normalize_structure_text(str(xyz), comment="user provided structure")
        return normalized, _infer_display_name(query, normalized, display_name), out_warnings

    if query and (_looks_like_xyz(query) or _looks_like_atom_spec(query)):
        normalized = _normalize_structure_text(str(query), comment="structure from query")
        return normalized, _infer_display_name(query, normalized, display_name), out_warnings

    if query:
        q = str(query).strip()
        if q.lower() in _BUILTIN_STRUCTURES_XYZ:
            resolved_xyz = _BUILTIN_STRUCTURES_XYZ[q.lower()]
            _emit_warning("Using built-in structure library fallback.", warnings=out_warnings)
            return resolved_xyz, _infer_display_name(q, resolved_xyz, display_name), out_warnings

        resolver = _get_molecule_resolver()
        try:
            if hasattr(resolver, "resolve") and callable(resolver.resolve):
                resolved = resolver.resolve(q)
            elif callable(resolver):
                resolved = resolver(q)
            else:
                raise ValueError("Resolver object is not callable")
        except Exception as exc:
            if _MOLECULE_RESOLVER_IMPORT_ERROR is not None:
                _emit_warning(
                    f"MoleculeResolver import failed earlier: {_MOLECULE_RESOLVER_IMPORT_ERROR}",
                    warnings=out_warnings,
                )
            raise ValueError(f"Failed to resolve structure from query '{q}': {exc}") from exc

        resolved_xyz, resolved_name, resolved_warnings = _extract_resolver_xyz(resolved)
        out_warnings.extend(resolved_warnings)
        if resolved_xyz:
            return resolved_xyz, _infer_display_name(q, resolved_xyz, display_name or resolved_name), out_warnings

    raise ValueError("No structure could be resolved; provide query, XYZ, or atom-spec text.")


# ---------------------------------------------------------------------------
# SCF / PySCF helpers
# ---------------------------------------------------------------------------


def _normalize_method(method: str | None) -> str:
    raw = str(method or DEFAULT_METHOD).strip()
    if not raw:
        return DEFAULT_METHOD
    aliases = {
        "b3lyp-d3bj": "B3LYP",
        "b3lyp-d3": "B3LYP",
        "pbe0-d3bj": "PBE0",
        "wb97x-d": "wB97X-D",
        "wb97xd": "wB97X-D",
        "m06-2x": "M06-2X",
        "hf": "HF",
        "rhf": "HF",
        "uhf": "HF",
    }
    key = raw.lower()
    return aliases.get(key, raw)


def _build_molecule(xyz: str, basis: str, charge: int, spin: int) -> gto.Mole:
    atom_spec = _xyz_to_atom_spec(xyz)
    mol = gto.Mole()
    mol.atom = atom_spec
    mol.unit = "Angstrom"
    mol.basis = basis or DEFAULT_BASIS
    mol.charge = int(charge or 0)
    mol.spin = int(spin or 0)  # 2S
    mol.verbose = 0
    mol.build()
    return mol


def _build_mean_field(
    mol: gto.Mole,
    method: str,
    *,
    max_cycle: int = 100,
    conv_tol: float = 1e-8,
) -> Any:
    normalized = _normalize_method(method)
    key = normalized.strip().lower()

    if key in {"hf", "rhf", "uhf"}:
        mf = scf.RHF(mol) if mol.spin == 0 else scf.UHF(mol)
    else:
        mf = dft.RKS(mol) if mol.spin == 0 else dft.UKS(mol)
        mf.xc = normalized
        try:
            mf.grids.level = 3
        except Exception:
            pass

    mf.max_cycle = int(max_cycle)
    mf.conv_tol = float(conv_tol)
    mf.verbose = 0
    return mf


def _run_scf(
    mf: Any,
    *,
    progress_callback: Any = None,
    emit_event: Any = None,
    is_cancelled: Any = None,
) -> tuple[float, bool, int]:
    cycle_counter = {"n": 0}

    def _callback(envs):
        cycle = _safe_int(envs.get("cycle"), cycle_counter["n"])
        cycle_counter["n"] = cycle
        _check_cancel(is_cancelled)
        _report(
            min(86.0, 20.0 + 3.0 * cycle),
            "scf",
            f"SCF cycle {cycle}",
            progress_callback=progress_callback,
            emit_event=emit_event,
        )

    try:
        mf.callback = _callback
    except Exception:
        pass

    _report(18.0, "scf", "Starting SCF", progress_callback=progress_callback, emit_event=emit_event)
    _check_cancel(is_cancelled)
    energy = float(mf.kernel())
    _check_cancel(is_cancelled)
    converged = bool(getattr(mf, "converged", False))
    cycles = int(cycle_counter["n"] or getattr(mf, "cycles", 0) or 0)
    _report(88.0, "scf", "SCF finished", progress_callback=progress_callback, emit_event=emit_event)
    return energy, converged, cycles


def _compute_gap_ev(mf: Any) -> float | None:
    mo_occ = getattr(mf, "mo_occ", None)
    mo_energy = getattr(mf, "mo_energy", None)
    if mo_occ is None or mo_energy is None:
        return None

    def restricted_gap(occ_arr, ene_arr):
        occ = np.asarray(occ_arr, dtype=float).ravel()
        ene = np.asarray(ene_arr, dtype=float).ravel()
        if occ.size == 0 or ene.size == 0:
            return None
        filled = np.where(occ > 1e-8)[0]
        if filled.size == 0:
            return None
        homo = int(filled.max())
        lumo = homo + 1
        if lumo >= ene.size:
            return None
        return float((ene[lumo] - ene[homo]) * HARTREE_TO_EV)

    if isinstance(mo_occ, (tuple, list)) and len(mo_occ) == 2:
        gaps = [
            restricted_gap(mo_occ[0], mo_energy[0]),
            restricted_gap(mo_occ[1], mo_energy[1]),
        ]
        gaps = [g for g in gaps if g is not None]
        return min(gaps) if gaps else None

    return restricted_gap(mo_occ, mo_energy)


def _compute_spin_data(mf: Any, spin: int) -> tuple[float | None, float | None]:
    expected_s = float(spin) / 2.0
    expected_s2 = expected_s * (expected_s + 1.0)
    actual_s2 = None
    if hasattr(mf, "spin_square"):
        try:
            actual_s2 = float(mf.spin_square()[0])
        except Exception:
            actual_s2 = None
    return expected_s2, actual_s2


def _extract_partial_charges(mf: Any, mol: gto.Mole) -> list[dict[str, Any]]:
    try:
        dm = mf.make_rdm1()
        s = mol.intor("int1e_ovlp")
        _, charges = mf.mulliken_pop(mol, dm=dm, s=s, verbose=0)
        out: list[dict[str, Any]] = []
        for i in range(mol.natm):
            out.append(
                {
                    "atom": i + 1,
                    "symbol": mol.atom_symbol(i),
                    "charge": float(charges[i]),
                }
            )
        return out
    except Exception as exc:
        logger.warning("Mulliken charge extraction failed: %s", exc)
        return [
            {"atom": i + 1, "symbol": mol.atom_symbol(i), "charge": 0.0}
            for i in range(mol.natm)
        ]


def _frontier_indices_from_occ(mo_occ, span: int = 3):
    occ = np.asarray(mo_occ, dtype=float).ravel()
    if occ.size == 0:
        return [], None, None

    filled = np.where(occ > 1e-8)[0]
    if filled.size == 0:
        return list(range(min(len(occ), 2 * span + 1))), None, (0 if len(occ) else None)

    homo = int(filled.max())
    lumo = homo + 1 if homo + 1 < len(occ) else None

    lo = max(0, homo - span)
    hi_center = lumo if lumo is not None else homo
    hi = min(len(occ) - 1, hi_center + span)

    return list(range(lo, hi + 1)), homo, lumo


def _orbital_label(idx: int, homo: int | None, lumo: int | None) -> str:
    if homo is not None and idx == homo:
        return "HOMO"
    if lumo is not None and idx == lumo:
        return "LUMO"
    if homo is not None and idx < homo:
        return f"HOMO-{homo - idx}"
    if lumo is not None and idx > lumo:
        return f"LUMO+{idx - lumo}"
    return f"MO {idx}"


def _extract_orbital_preview(mf: Any, max_items_per_spin: int = 7) -> list[dict[str, Any]]:
    mo_occ = getattr(mf, "mo_occ", None)
    mo_energy = getattr(mf, "mo_energy", None)
    if mo_occ is None or mo_energy is None:
        return []

    items: list[dict[str, Any]] = []

    def emit_channel(spin_name: str, occ_arr, ene_arr):
        indices, homo, lumo = _frontier_indices_from_occ(occ_arr, span=3)
        indices = indices[:max_items_per_spin]
        occ = np.asarray(occ_arr, dtype=float).ravel()
        ene = np.asarray(ene_arr, dtype=float).ravel()

        for idx in indices:
            label = _orbital_label(int(idx), homo, lumo)
            if spin_name and spin_name != "restricted":
                if label.startswith("HOMO") or label.startswith("LUMO"):
                    label = f"{label} ({spin_name[0]})"
                else:
                    label = f"{label} ({spin_name[0]})"
            items.append(
                {
                    "index": f"{spin_name}:{idx}" if spin_name != "restricted" else int(idx),
                    "mo_index": int(idx),
                    "spin": spin_name,
                    "label": label,
                    "occupied": bool(occ[idx] > 1e-8),
                    "occupation": float(occ[idx]),
                    "energy_ev": float(ene[idx] * HARTREE_TO_EV),
                    "energy_hartree": float(ene[idx]),
                }
            )

    if isinstance(mo_occ, (tuple, list)) and len(mo_occ) == 2:
        emit_channel("alpha", mo_occ[0], mo_energy[0])
        emit_channel("beta", mo_occ[1], mo_energy[1])
        items.sort(key=lambda x: float(x.get("energy_ev", 0.0)))
    else:
        emit_channel("restricted", mo_occ, mo_energy)

    return items


def _file_to_b64(path: str | Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def _collapse_density_matrix(dm):
    if isinstance(dm, (tuple, list)) and len(dm) == 2:
        try:
            return np.asarray(dm[0]) + np.asarray(dm[1])
        except Exception:
            return dm[0]
    return dm


def _build_visualization_payload(
    mf: Any,
    mol: gto.Mole,
    *,
    method: str,
    basis: str,
    charge: int,
    spin: int,
    include_visualization: bool = True,
    cube_grid_size: int = 60,
    max_orbitals_per_spin: int = 7,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "skipped",
        "defaults": {
            "orbital_iso": 0.02,
            "orbital_opacity": 0.82,
            "esp_iso": 0.002,
            "esp_opacity": 0.80,
            "esp_range": [-0.05, 0.05],
            "esp_preset": "rwb",
        },
        "orbitals": {
            "available": False,
            "items": [],
            "selected_key": None,
        },
        "esp": {
            "available": False,
            "density_cube_b64": None,
            "potential_cube_b64": None,
            "presets": ESP_PRESETS_DATA,
        },
        "warnings": [],
        "meta": {
            "method": method,
            "basis": basis,
            "charge": charge,
            "spin": spin,
            "grid_size": cube_grid_size,
        },
    }

    if not include_visualization:
        payload["warnings"].append("Visualization payload generation skipped by request.")
        return payload

    payload["status"] = "unavailable"

    if cubegen is None:
        payload["warnings"].append("pyscf.tools.cubegen is unavailable; cube-based visualization was not generated.")
        return payload

    natm = int(getattr(mol, "natm", 0) or 0)
    if natm > 120:
        payload["warnings"].append(f"Visualization skipped for very large system ({natm} atoms).")
        return payload
    if natm > 80:
        payload["warnings"].append(f"Large system detected ({natm} atoms); visualization generation may be slow.")

    cube_grid_size = max(30, min(90, int(cube_grid_size or 60)))

    mo_coeff = getattr(mf, "mo_coeff", None)
    mo_occ = getattr(mf, "mo_occ", None)
    mo_energy = getattr(mf, "mo_energy", None)

    if mo_coeff is None or mo_occ is None or mo_energy is None:
        payload["warnings"].append("MO arrays unavailable for visualization.")
        return payload

    orbital_items: list[dict[str, Any]] = []

    def emit_channel(spin_name: str, coeff_arr, occ_arr, energy_arr) -> None:
        indices, homo, lumo = _frontier_indices_from_occ(occ_arr, span=3)
        indices = indices[:max_orbitals_per_spin]
        if not indices:
            return

        with tempfile.TemporaryDirectory(prefix=f"qcviz_orb_{spin_name}_") as td:
            for idx in indices:
                cube_path = os.path.join(td, f"{spin_name}_{idx}.cube")
                try:
                    cubegen.orbital(
                        mol,
                        cube_path,
                        coeff_arr[:, idx],
                        nx=cube_grid_size,
                        ny=cube_grid_size,
                        nz=cube_grid_size,
                    )
                    energy_h = float(np.asarray(energy_arr, dtype=float).ravel()[idx])
                    occ_v = float(np.asarray(occ_arr, dtype=float).ravel()[idx])
                    orbital_items.append(
                        {
                            "key": f"{spin_name}:{idx}",
                            "spin": spin_name,
                            "mo_index": int(idx),
                            "label": _orbital_label(int(idx), homo, lumo),
                            "energy_hartree": energy_h,
                            "energy_ev": energy_h * HARTREE_TO_EV,
                            "occupation": occ_v,
                            "cube_b64": _file_to_b64(cube_path),
                        }
                    )
                except Exception as exc:
                    payload["warnings"].append(
                        f"Failed to generate orbital cube for {spin_name} orbital {idx}: {exc}"
                    )

    try:
        if isinstance(mo_coeff, (tuple, list)) and len(mo_coeff) == 2:
            emit_channel("alpha", mo_coeff[0], mo_occ[0], mo_energy[0])
            emit_channel("beta", mo_coeff[1], mo_occ[1], mo_energy[1])
            orbital_items.sort(key=lambda x: float(x.get("energy_ev", 0.0)))
        else:
            emit_channel("restricted", mo_coeff, mo_occ, mo_energy)
    except Exception as exc:
        payload["warnings"].append(f"Orbital visualization generation failed: {exc}")

    if orbital_items:
        payload["orbitals"]["available"] = True
        payload["orbitals"]["items"] = orbital_items
        selected_key = None
        for item in orbital_items:
            if str(item.get("label", "")).upper() == "HOMO":
                selected_key = item["key"]
                break
        payload["orbitals"]["selected_key"] = selected_key or orbital_items[0]["key"]

    try:
        dm = _collapse_density_matrix(mf.make_rdm1())
    except Exception as exc:
        dm = None
        payload["warnings"].append(f"Density matrix unavailable for ESP generation: {exc}")

    if dm is not None:
        try:
            with tempfile.TemporaryDirectory(prefix="qcviz_esp_") as td:
                density_path = os.path.join(td, "density.cube")
                potential_path = os.path.join(td, "potential.cube")

                cubegen.density(
                    mol,
                    density_path,
                    dm,
                    nx=cube_grid_size,
                    ny=cube_grid_size,
                    nz=cube_grid_size,
                )

                potential_ok = False
                if hasattr(cubegen, "mep"):
                    try:
                        cubegen.mep(
                            mol,
                            potential_path,
                            dm,
                            nx=cube_grid_size,
                            ny=cube_grid_size,
                            nz=cube_grid_size,
                        )
                        potential_ok = True
                    except Exception as exc:
                        payload["warnings"].append(f"ESP potential cube generation failed: {exc}")
                else:
                    payload["warnings"].append("cubegen.mep is not available in this PySCF build.")

                if os.path.exists(density_path) and potential_ok and os.path.exists(potential_path):
                    payload["esp"]["available"] = True
                    payload["esp"]["density_cube_b64"] = _file_to_b64(density_path)
                    payload["esp"]["potential_cube_b64"] = _file_to_b64(potential_path)
        except Exception as exc:
            payload["warnings"].append(f"ESP cube generation failed: {exc}")

    if payload["orbitals"]["available"] or payload["esp"]["available"]:
        payload["status"] = "ready"

    return payload


def _attach_visualization_payload(
    result: dict[str, Any],
    mf: Any,
    mol: gto.Mole,
    *,
    method: str,
    basis: str,
    charge: int,
    spin: int,
    include_visualization: bool = True,
    cube_grid_size: int = 60,
) -> dict[str, Any]:
    result = dict(result or {})
    viz = _build_visualization_payload(
        mf,
        mol,
        method=method,
        basis=basis,
        charge=charge,
        spin=spin,
        include_visualization=include_visualization,
        cube_grid_size=cube_grid_size,
    )
    result["visualization"] = viz

    if viz.get("warnings"):
        result.setdefault("warnings", [])
        result["warnings"].extend(viz["warnings"])

    if viz.get("orbitals", {}).get("available") and not result.get("orbitals"):
        preview: list[dict[str, Any]] = []
        for item in viz["orbitals"]["items"]:
            occ = item.get("occupation")
            preview.append(
                {
                    "index": item.get("mo_index"),
                    "label": item.get("label"),
                    "occupied": bool(occ is not None and float(occ) > 1e-8),
                    "energy_ev": item.get("energy_ev"),
                }
            )
        result["orbitals"] = preview

    return result


def _make_base_result(
    *,
    job_type: str,
    query: str | None,
    xyz: str,
    display_name: str,
    method: str,
    basis: str,
    charge: int,
    spin: int,
    warnings: list[str],
) -> dict[str, Any]:
    bonds, angles, atom_count, formula = _summarize_geometry(xyz)
    return {
        "job_type": job_type,
        "original_prompt": query,
        "structure_query": query,
        "display_name": display_name,
        "xyz": xyz,
        "atom_count": atom_count,
        "formula": formula,
        "method": method,
        "basis": basis,
        "charge": charge,
        "spin": spin,
        "bonds": bonds,
        "angles": angles,
        "warnings": list(warnings),
    }


# ---------------------------------------------------------------------------
# Public runner functions
# ---------------------------------------------------------------------------


def run_resolve_structure(
    *,
    query: str | None = None,
    xyz: str | None = None,
    charge: int = 0,
    spin: int = 0,
    display_name: str | None = None,
    progress_callback: Any = None,
    emit_event: Any = None,
    is_cancelled: Any = None,
    **_: Any,
) -> dict[str, Any]:
    warnings: list[str] = []
    _report(5, "resolve", "Resolving structure", progress_callback=progress_callback, emit_event=emit_event)
    _check_cancel(is_cancelled)

    resolved_xyz, resolved_name, warnings = _resolve_structure_input(
        query=query,
        xyz=xyz,
        display_name=display_name,
        warnings=warnings,
    )

    bonds, angles, atom_count, formula = _summarize_geometry(resolved_xyz)
    _report(100, "resolve", "Structure ready", progress_callback=progress_callback, emit_event=emit_event)

    return {
        "job_type": "resolve_structure",
        "display_name": resolved_name,
        "xyz": resolved_xyz,
        "atom_count": atom_count,
        "formula": formula,
        "charge": charge,
        "spin": spin,
        "bonds": bonds,
        "angles": angles,
        "warnings": warnings,
        "resolved": True,
    }


def run_geometry_analysis(
    *,
    query: str | None = None,
    xyz: str | None = None,
    charge: int = 0,
    spin: int = 0,
    display_name: str | None = None,
    method: str | None = None,
    basis: str | None = None,
    progress_callback: Any = None,
    emit_event: Any = None,
    is_cancelled: Any = None,
    **_: Any,
) -> dict[str, Any]:
    warnings: list[str] = []
    _report(5, "resolve", "Resolving structure", progress_callback=progress_callback, emit_event=emit_event)
    _check_cancel(is_cancelled)

    resolved_xyz, resolved_name, warnings = _resolve_structure_input(
        query=query,
        xyz=xyz,
        display_name=display_name,
        warnings=warnings,
    )

    _report(55, "geometry", "Analyzing geometry", progress_callback=progress_callback, emit_event=emit_event)
    _check_cancel(is_cancelled)

    bonds, angles, atom_count, formula = _summarize_geometry(resolved_xyz)
    _report(100, "geometry", "Geometry analysis complete", progress_callback=progress_callback, emit_event=emit_event)

    return {
        "job_type": "geometry_analysis",
        "display_name": resolved_name,
        "xyz": resolved_xyz,
        "atom_count": atom_count,
        "formula": formula,
        "method": _normalize_method(method),
        "basis": basis or DEFAULT_BASIS,
        "charge": charge,
        "spin": spin,
        "bonds": bonds,
        "angles": angles,
        "warnings": warnings,
    }


def run_single_point(
    *,
    query: str | None = None,
    xyz: str | None = None,
    charge: int = 0,
    spin: int = 0,
    display_name: str | None = None,
    method: str | None = None,
    basis: str | None = None,
    progress_callback: Any = None,
    emit_event: Any = None,
    is_cancelled: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    warnings: list[str] = []
    method = _normalize_method(method)
    basis = basis or DEFAULT_BASIS

    _report(5, "resolve", "Resolving structure", progress_callback=progress_callback, emit_event=emit_event)
    resolved_xyz, resolved_name, warnings = _resolve_structure_input(
        query=query,
        xyz=xyz,
        display_name=display_name,
        warnings=warnings,
    )

    _check_cancel(is_cancelled)
    _report(12, "build", "Building molecule", progress_callback=progress_callback, emit_event=emit_event)
    mol = _build_molecule(resolved_xyz, basis, charge, spin)

    _check_cancel(is_cancelled)
    _report(16, "build", "Preparing mean-field object", progress_callback=progress_callback, emit_event=emit_event)
    max_cycle = _safe_int(kwargs.get("max_cycle"), 100)
    mf = _build_mean_field(mol, method, max_cycle=max_cycle)

    energy, converged, scf_cycles = _run_scf(
        mf,
        progress_callback=progress_callback,
        emit_event=emit_event,
        is_cancelled=is_cancelled,
    )

    orbitals = _extract_orbital_preview(mf)
    gap_ev = _compute_gap_ev(mf)
    expected_s2, actual_s2 = _compute_spin_data(mf, spin)

    result = _make_base_result(
        job_type="single_point",
        query=query,
        xyz=resolved_xyz,
        display_name=resolved_name,
        method=method,
        basis=basis,
        charge=charge,
        spin=spin,
        warnings=warnings,
    )
    result.update(
        {
            "energy_hartree": energy,
            "converged": converged,
            "scf_cycles": scf_cycles,
            "orbitals": orbitals,
            "gap_ev": gap_ev,
            "expected_s2": expected_s2,
            "actual_s2": actual_s2,
        }
    )

    include_visualization = _safe_bool(kwargs.get("include_visualization"), True)
    cube_grid_size = _safe_int(kwargs.get("cube_grid_size"), 60)
    result = _attach_visualization_payload(
        result,
        mf,
        mol,
        method=method,
        basis=basis,
        charge=charge,
        spin=spin,
        include_visualization=include_visualization,
        cube_grid_size=cube_grid_size,
    )

    _report(100, "done", "Single-point calculation complete", progress_callback=progress_callback, emit_event=emit_event)
    return result


def run_partial_charges(
    *,
    query: str | None = None,
    xyz: str | None = None,
    charge: int = 0,
    spin: int = 0,
    display_name: str | None = None,
    method: str | None = None,
    basis: str | None = None,
    progress_callback: Any = None,
    emit_event: Any = None,
    is_cancelled: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    warnings: list[str] = []
    method = _normalize_method(method)
    basis = basis or DEFAULT_BASIS

    _report(5, "resolve", "Resolving structure", progress_callback=progress_callback, emit_event=emit_event)
    resolved_xyz, resolved_name, warnings = _resolve_structure_input(
        query=query,
        xyz=xyz,
        display_name=display_name,
        warnings=warnings,
    )

    _check_cancel(is_cancelled)
    mol = _build_molecule(resolved_xyz, basis, charge, spin)
    mf = _build_mean_field(mol, method, max_cycle=_safe_int(kwargs.get("max_cycle"), 100))
    energy, converged, scf_cycles = _run_scf(
        mf,
        progress_callback=progress_callback,
        emit_event=emit_event,
        is_cancelled=is_cancelled,
    )

    _check_cancel(is_cancelled)
    _report(90, "charges", "Computing Mulliken charges", progress_callback=progress_callback, emit_event=emit_event)
    partial_charges = _extract_partial_charges(mf, mol)
    orbitals = _extract_orbital_preview(mf)
    gap_ev = _compute_gap_ev(mf)
    expected_s2, actual_s2 = _compute_spin_data(mf, spin)

    result = _make_base_result(
        job_type="partial_charges",
        query=query,
        xyz=resolved_xyz,
        display_name=resolved_name,
        method=method,
        basis=basis,
        charge=charge,
        spin=spin,
        warnings=warnings,
    )
    result.update(
        {
            "energy_hartree": energy,
            "converged": converged,
            "scf_cycles": scf_cycles,
            "partial_charges": partial_charges,
            "orbitals": orbitals,
            "gap_ev": gap_ev,
            "expected_s2": expected_s2,
            "actual_s2": actual_s2,
        }
    )

    include_visualization = _safe_bool(kwargs.get("include_visualization"), True)
    cube_grid_size = _safe_int(kwargs.get("cube_grid_size"), 60)
    result = _attach_visualization_payload(
        result,
        mf,
        mol,
        method=method,
        basis=basis,
        charge=charge,
        spin=spin,
        include_visualization=include_visualization,
        cube_grid_size=cube_grid_size,
    )

    _report(
        100,
        "done",
        "Partial charge analysis complete",
        progress_callback=progress_callback,
        emit_event=emit_event,
    )
    return result


def run_orbital_preview(
    *,
    query: str | None = None,
    xyz: str | None = None,
    charge: int = 0,
    spin: int = 0,
    display_name: str | None = None,
    method: str | None = None,
    basis: str | None = None,
    progress_callback: Any = None,
    emit_event: Any = None,
    is_cancelled: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    kwargs = dict(kwargs or {})
    if "include_visualization" not in kwargs:
        kwargs["include_visualization"] = True

    result = run_single_point(
        query=query,
        xyz=xyz,
        charge=charge,
        spin=spin,
        display_name=display_name,
        method=method,
        basis=basis,
        progress_callback=progress_callback,
        emit_event=emit_event,
        is_cancelled=is_cancelled,
        **kwargs,
    )
    result["job_type"] = "orbital_preview"
    return result


def run_esp_map(
    *,
    query: str | None = None,
    xyz: str | None = None,
    charge: int = 0,
    spin: int = 0,
    display_name: str | None = None,
    method: str | None = None,
    basis: str | None = None,
    progress_callback: Any = None,
    emit_event: Any = None,
    is_cancelled: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    kwargs = dict(kwargs or {})
    if "include_visualization" not in kwargs:
        kwargs["include_visualization"] = True

    result = run_single_point(
        query=query,
        xyz=xyz,
        charge=charge,
        spin=spin,
        display_name=display_name,
        method=method,
        basis=basis,
        progress_callback=progress_callback,
        emit_event=emit_event,
        is_cancelled=is_cancelled,
        **kwargs,
    )
    result["job_type"] = "esp_map"
    return result


def run_geometry_optimization(
    *,
    query: str | None = None,
    xyz: str | None = None,
    charge: int = 0,
    spin: int = 0,
    display_name: str | None = None,
    method: str | None = None,
    basis: str | None = None,
    progress_callback: Any = None,
    emit_event: Any = None,
    is_cancelled: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    warnings: list[str] = []
    method = _normalize_method(method)
    basis = basis or DEFAULT_BASIS

    _report(5, "resolve", "Resolving structure", progress_callback=progress_callback, emit_event=emit_event)
    resolved_xyz, resolved_name, warnings = _resolve_structure_input(
        query=query,
        xyz=xyz,
        display_name=display_name,
        warnings=warnings,
    )

    _check_cancel(is_cancelled)
    _report(12, "build", "Building molecule", progress_callback=progress_callback, emit_event=emit_event)
    mol = _build_molecule(resolved_xyz, basis, charge, spin)

    _check_cancel(is_cancelled)
    mf0 = _build_mean_field(mol, method, max_cycle=_safe_int(kwargs.get("max_cycle"), 100))

    optimization_performed = False
    optimization_success = False
    mol_final = mol

    if geometric_optimize is None:
        _emit_warning(
            "geometric/PySCF geomopt is unavailable; falling back to single-point on initial structure.",
            warnings=warnings,
            emit_event=emit_event,
        )
    else:
        _report(20, "opt", "Starting geometry optimization", progress_callback=progress_callback, emit_event=emit_event)
        try:
            opt_result = geometric_optimize(mf0)
            if isinstance(opt_result, gto.Mole):
                mol_final = opt_result
            elif hasattr(opt_result, "mol") and isinstance(opt_result.mol, gto.Mole):
                mol_final = opt_result.mol
            else:
                _emit_warning(
                    "Geometry optimizer returned an unexpected object; using original geometry.",
                    warnings=warnings,
                    emit_event=emit_event,
                )
                mol_final = mol

            optimization_performed = True
            optimization_success = True
            _report(72, "opt", "Geometry optimization finished", progress_callback=progress_callback, emit_event=emit_event)
        except Exception as exc:
            _emit_warning(
                f"Geometry optimization failed; falling back to single-point: {exc}",
                warnings=warnings,
                emit_event=emit_event,
            )
            mol_final = mol

    _check_cancel(is_cancelled)

    # Rebuild mean-field on final geometry for consistent final properties.
    if optimization_success:
        try:
            final_xyz = _xyz_from_mol(mol_final)
            mol_final = _build_molecule(final_xyz, basis, charge, spin)
        except Exception as exc:
            _emit_warning(
                f"Failed to normalize optimized geometry; using in-memory optimized Mole object directly: {exc}",
                warnings=warnings,
                emit_event=emit_event,
            )

    _report(78, "final_scf", "Running final SCF", progress_callback=progress_callback, emit_event=emit_event)
    mf_final = _build_mean_field(mol_final, method, max_cycle=_safe_int(kwargs.get("max_cycle"), 100))
    energy, converged, scf_cycles = _run_scf(
        mf_final,
        progress_callback=progress_callback,
        emit_event=emit_event,
        is_cancelled=is_cancelled,
    )

    final_xyz = _xyz_from_mol(mol_final)
    orbitals = _extract_orbital_preview(mf_final)
    gap_ev = _compute_gap_ev(mf_final)
    partial_charges = _extract_partial_charges(mf_final, mol_final)
    expected_s2, actual_s2 = _compute_spin_data(mf_final, spin)

    result = _make_base_result(
        job_type="geometry_optimization",
        query=query,
        xyz=final_xyz,
        display_name=resolved_name,
        method=method,
        basis=basis,
        charge=charge,
        spin=spin,
        warnings=warnings,
    )
    result.update(
        {
            "energy_hartree": energy,
            "converged": converged,
            "scf_cycles": scf_cycles,
            "orbitals": orbitals,
            "gap_ev": gap_ev,
            "partial_charges": partial_charges,
            "expected_s2": expected_s2,
            "actual_s2": actual_s2,
            "optimization_performed": optimization_performed,
            "optimization_success": optimization_success,
        }
    )

    include_visualization = _safe_bool(kwargs.get("include_visualization"), False)
    cube_grid_size = _safe_int(kwargs.get("cube_grid_size"), 60)
    if include_visualization:
        result = _attach_visualization_payload(
            result,
            mf_final,
            mol_final,
            method=method,
            basis=basis,
            charge=charge,
            spin=spin,
            include_visualization=True,
            cube_grid_size=cube_grid_size,
        )

    _report(
        100,
        "done",
        "Geometry optimization workflow complete",
        progress_callback=progress_callback,
        emit_event=emit_event,
    )
    return result


def run_analyze(
    *,
    query: str | None = None,
    xyz: str | None = None,
    charge: int = 0,
    spin: int = 0,
    display_name: str | None = None,
    method: str | None = None,
    basis: str | None = None,
    progress_callback: Any = None,
    emit_event: Any = None,
    is_cancelled: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return run_geometry_analysis(
        query=query,
        xyz=xyz,
        charge=charge,
        spin=spin,
        display_name=display_name,
        method=method,
        basis=basis,
        progress_callback=progress_callback,
        emit_event=emit_event,
        is_cancelled=is_cancelled,
        **kwargs,
    )


__all__ = [
    "HARTREE_TO_EV",
    "DEFAULT_METHOD",
    "DEFAULT_BASIS",
    "ESP_PRESETS_DATA",
    "run_resolve_structure",
    "run_geometry_analysis",
    "run_single_point",
    "run_partial_charges",
    "run_orbital_preview",
    "run_esp_map",
    "run_geometry_optimization",
    "run_analyze",
]

```

## [job_manager.py]

경로: `version02/src/qcviz_mcp/compute/job_manager.py`

```python
"""Progress-aware in-process JobManager for QCViz.

This manager is intentionally implemented on top of ThreadPoolExecutor for the
current web alpha phase so that:
1. bound callables and local functions are easy to submit,
2. progress/event callbacks can update shared state without IPC,
3. the WebSocket chat flow can poll status and drain events reliably.

Public API used by the web layer:
- get_job_manager()
- JobManager.submit(...)
- JobManager.get(job_id)
- JobManager.list_jobs()
- JobManager.cancel(job_id)
- JobManager.drain_events(job_id, clear=True)
- JobManager.wait(job_id, timeout=None)
- JobManager.async_wait(job_id, timeout=None, poll_interval=0.2)
- JobManager.shutdown(...)
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import threading
import time
import traceback
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class JobEvent:
    """A lightweight event emitted during job execution."""

    job_id: str
    timestamp: float
    level: str = "info"
    message: str = ""
    step: str = ""
    detail: str = ""
    progress: float = 0.0
    payload: Optional[Dict[str, Any]] = None


@dataclass
class JobRecord:
    """Serializable public job record."""

    job_id: str
    name: str
    label: str
    status: str = "queued"
    progress: float = 0.0
    step: str = ""
    detail: str = ""
    result: Any = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    cancel_requested: bool = False


class JobCancelledError(RuntimeError):
    """Raised when a running job cooperatively acknowledges cancellation."""


class JobManager:
    """Thread-based job manager with progress and event buffering."""

    def __init__(
        self,
        max_workers: Optional[int] = None,
        max_events_per_job: int = 300,
    ) -> None:
        cpu = os.cpu_count() or 2
        self._max_workers = max_workers or max(2, min(4, cpu))
        self._max_events_per_job = max(50, int(max_events_per_job))

        self._executor = ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix="qcviz-job",
        )

        self._lock = threading.RLock()
        self._records: Dict[str, JobRecord] = {}
        self._futures: Dict[str, Future] = {}
        self._events: Dict[str, List[JobEvent]] = {}
        self._cancel_flags: Dict[str, threading.Event] = {}

        logger.info(
            "JobManager initialized (ThreadPoolExecutor, max_workers=%s)",
            self._max_workers,
        )

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def submit(
        self,
        target: Optional[Callable[..., Any]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        label: Optional[str] = None,
        name: Optional[str] = None,
        func: Optional[Callable[..., Any]] = None,
    ) -> str:
        """Submit a background job.

        Compatible with multiple call patterns:
            submit(target=fn, kwargs={...}, label="...")
            submit(func=fn, kwargs={...}, name="...")
        """
        callable_obj = target or func
        if callable_obj is None or not callable(callable_obj):
            raise ValueError("submit() requires a callable target/func")

        job_id = self._new_job_id()
        job_name = str(name or label or getattr(callable_obj, "__name__", "job")).strip() or "job"

        record = JobRecord(
            job_id=job_id,
            name=job_name,
            label=str(label or job_name),
            status="queued",
            progress=0.0,
            step="queued",
            detail="Job queued",
        )

        with self._lock:
            self._records[job_id] = record
            self._events[job_id] = []
            self._cancel_flags[job_id] = threading.Event()

        self._append_event(
            job_id,
            level="info",
            message="Job queued",
            step="queued",
            detail=record.detail,
            progress=0.0,
        )

        future = self._executor.submit(
            self._run_job,
            job_id,
            callable_obj,
            dict(kwargs or {}),
        )

        with self._lock:
            self._futures[job_id] = future

        return job_id

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get a public job record as dict."""
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return None
            return self._record_to_dict(record)

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Alias for compatibility."""
        return self.get(job_id)

    def get_record(self, job_id: str) -> Optional[JobRecord]:
        """Return the internal JobRecord snapshot."""
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return None
            return JobRecord(**asdict(record))

    def list_jobs(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """List jobs sorted by creation time descending."""
        with self._lock:
            records = [self._record_to_dict(rec) for rec in self._records.values()]

        records.sort(key=lambda x: x.get("created_at", 0.0), reverse=True)
        if limit is not None:
            return records[: max(0, int(limit))]
        return records

    def cancel(self, job_id: str) -> Dict[str, Any]:
        """Request job cancellation.

        If the future has not started yet, it may be cancelled immediately.
        If already running, we set a cooperative cancel flag and leave it to the
        runner to stop if it supports cancellation checks.
        """
        with self._lock:
            record = self._records.get(job_id)
            future = self._futures.get(job_id)
            cancel_flag = self._cancel_flags.get(job_id)

        if record is None:
            return {
                "ok": False,
                "job_id": job_id,
                "status": "missing",
                "message": "job not found",
            }

        if cancel_flag is not None:
            cancel_flag.set()

        self._update_record(
            job_id,
            cancel_requested=True,
            detail="Cancellation requested",
        )
        self._append_event(
            job_id,
            level="warning",
            message="Cancellation requested",
            step="cancellation_requested",
            detail="Cancellation requested by user",
            progress=self._get_progress(job_id),
        )

        if future is not None and future.cancel():
            self._finalize_cancelled(job_id, detail="Cancelled before execution")
            return {
                "ok": True,
                "job_id": job_id,
                "status": "cancelled",
                "message": "job cancelled before execution",
            }

        return {
            "ok": True,
            "job_id": job_id,
            "status": "cancellation_requested",
            "message": "cancellation requested",
        }

    def drain_events(self, job_id: str, clear: bool = True) -> List[Dict[str, Any]]:
        """Return buffered events for a job."""
        with self._lock:
            events = self._events.get(job_id, [])
            data = [asdict(ev) for ev in events]
            if clear:
                self._events[job_id] = []
        return data

    def pop_events(self, job_id: str) -> List[Dict[str, Any]]:
        """Alias for compatibility."""
        return self.drain_events(job_id, clear=True)

    def get_events(self, job_id: str, clear: bool = True) -> List[Dict[str, Any]]:
        """Alias for compatibility."""
        return self.drain_events(job_id, clear=clear)

    def wait(self, job_id: str, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Block until a job completes and return its record."""
        with self._lock:
            future = self._futures.get(job_id)

        if future is None:
            return self.get(job_id)

        try:
            future.result(timeout=timeout)
        except FutureTimeoutError:
            raise
        except Exception:
            # Job status/error are already recorded in _run_job
            pass

        return self.get(job_id)

    async def async_wait(
        self,
        job_id: str,
        timeout: Optional[float] = None,
        poll_interval: float = 0.2,
    ) -> Optional[Dict[str, Any]]:
        """Async wait helper suitable for FastAPI routes."""
        start = time.time()
        while True:
            record = self.get(job_id)
            if record is None:
                return None

            if record.get("status") in {"success", "error", "cancelled"}:
                return record

            if timeout is not None and (time.time() - start) > timeout:
                raise TimeoutError(f"Timed out waiting for job {job_id}")

            await asyncio.sleep(poll_interval)

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        """Shutdown executor."""
        logger.info(
            "Shutting down JobManager (wait=%s, cancel_futures=%s)",
            wait,
            cancel_futures,
        )
        self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)

    # -------------------------------------------------------------------------
    # Internal execution
    # -------------------------------------------------------------------------

    def _run_job(
        self,
        job_id: str,
        target: Callable[..., Any],
        kwargs: Dict[str, Any],
    ) -> None:
        """Worker thread entrypoint."""
        self._mark_running(job_id)

        try:
            cancel_flag = self._cancel_flags[job_id]
            if cancel_flag.is_set():
                raise JobCancelledError("Cancelled before start")

            injected = self._build_runtime_injections(job_id)
            call_kwargs = dict(kwargs or {})
            call_kwargs.update(injected)
            filtered_kwargs = self._filter_kwargs_for_callable(target, call_kwargs)

            result = target(**filtered_kwargs)

            # Support async runners if any appear later.
            if inspect.isawaitable(result):
                result = asyncio.run(result)

            if cancel_flag.is_set():
                # If a cooperative runner returned after noticing cancellation,
                # treat it as cancelled rather than success.
                raise JobCancelledError("Cancelled during execution")

            self._finalize_success(job_id, result)

        except JobCancelledError as exc:
            self._finalize_cancelled(job_id, detail=str(exc))

        except Exception as exc:
            tb = traceback.format_exc()
            logger.exception("Job %s failed", job_id)
            self._finalize_error(job_id, error=f"{exc}\n{tb}")

    def _build_runtime_injections(self, job_id: str) -> Dict[str, Any]:
        """Create callbacks/helpers that may be injected into runner functions."""
        cancel_flag = self._cancel_flags[job_id]

        def progress_callback(
            progress: Optional[float] = None,
            step: Optional[str] = None,
            detail: Optional[str] = None,
            message: Optional[str] = None,
            level: str = "info",
            payload: Optional[Dict[str, Any]] = None,
        ) -> None:
            if cancel_flag.is_set():
                raise JobCancelledError("Cancellation acknowledged")

            detail_text = str(detail or message or "")
            if progress is None:
                progress_val = self._get_progress(job_id)
            else:
                progress_val = max(0.0, min(100.0, float(progress)))

            updates: Dict[str, Any] = {"progress": progress_val}
            if step is not None:
                updates["step"] = str(step)
            if detail_text:
                updates["detail"] = detail_text

            self._update_record(job_id, **updates)
            self._append_event(
                job_id,
                level=level,
                message=str(message or detail or step or ""),
                step=str(step or ""),
                detail=detail_text,
                progress=progress_val,
                payload=payload,
            )

        def emit_event(
            message: str = "",
            *,
            level: str = "info",
            step: str = "",
            detail: str = "",
            progress: Optional[float] = None,
            payload: Optional[Dict[str, Any]] = None,
        ) -> None:
            progress_callback(
                progress=progress,
                step=step,
                detail=detail,
                message=message,
                level=level,
                payload=payload,
            )

        def is_cancelled() -> bool:
            return cancel_flag.is_set()

        # A broad set of aliases keeps this compatible with multiple runner styles.
        return {
            "progress_callback": progress_callback,
            "progress_cb": progress_callback,
            "report_progress": progress_callback,
            "job_reporter": progress_callback,
            "emit_event": emit_event,
            "event_callback": emit_event,
            "is_cancelled": is_cancelled,
            "cancel_requested": is_cancelled,
            "job_id": job_id,
        }

    # -------------------------------------------------------------------------
    # Internal state helpers
    # -------------------------------------------------------------------------

    def _new_job_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def _filter_kwargs_for_callable(
        self,
        func: Callable[..., Any],
        kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Drop kwargs that a callable does not accept unless it has **kwargs."""
        try:
            sig = inspect.signature(func)
        except Exception:
            return dict(kwargs)

        params = sig.parameters
        accepts_kwargs = any(
            p.kind == inspect.Parameter.VAR_KEYWORD
            for p in params.values()
        )
        if accepts_kwargs:
            return dict(kwargs)

        allowed = set(params.keys())
        return {
            key: value
            for key, value in kwargs.items()
            if key in allowed
        }

    def _record_to_dict(self, record: JobRecord) -> Dict[str, Any]:
        data = asdict(record)
        return data

    def _get_progress(self, job_id: str) -> float:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return 0.0
            return float(record.progress)

    def _update_record(self, job_id: str, **updates: Any) -> None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return

            for key, value in updates.items():
                if hasattr(record, key):
                    setattr(record, key, value)

            record.updated_at = time.time()

    def _append_event(
        self,
        job_id: str,
        *,
        level: str = "info",
        message: str = "",
        step: str = "",
        detail: str = "",
        progress: float = 0.0,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        event = JobEvent(
            job_id=job_id,
            timestamp=time.time(),
            level=str(level or "info"),
            message=str(message or ""),
            step=str(step or ""),
            detail=str(detail or ""),
            progress=max(0.0, min(100.0, float(progress))),
            payload=payload,
        )

        with self._lock:
            bucket = self._events.setdefault(job_id, [])
            bucket.append(event)
            if len(bucket) > self._max_events_per_job:
                del bucket[: len(bucket) - self._max_events_per_job]

    def _mark_running(self, job_id: str) -> None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return
            record.status = "running"
            record.progress = max(record.progress, 1.0)
            record.step = "running"
            record.detail = "Job started"
            record.started_at = time.time()
            record.updated_at = record.started_at

        self._append_event(
            job_id,
            level="info",
            message="Job started",
            step="running",
            detail="Job started",
            progress=1.0,
        )

    def _finalize_success(self, job_id: str, result: Any) -> None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return
            record.status = "success"
            record.progress = 100.0
            record.step = "completed"
            record.detail = "Job completed successfully"
            record.result = result
            record.error = None
            record.ended_at = time.time()
            record.updated_at = record.ended_at

        self._append_event(
            job_id,
            level="info",
            message="Job completed successfully",
            step="completed",
            detail="Job completed successfully",
            progress=100.0,
        )

    def _finalize_error(self, job_id: str, error: str) -> None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return
            record.status = "error"
            record.step = "error"
            record.detail = "Job failed"
            record.error = str(error)
            record.ended_at = time.time()
            record.updated_at = record.ended_at

        self._append_event(
            job_id,
            level="error",
            message="Job failed",
            step="error",
            detail=str(error),
            progress=self._get_progress(job_id),
        )

    def _finalize_cancelled(self, job_id: str, detail: str = "Cancelled") -> None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return
            record.status = "cancelled"
            record.step = "cancelled"
            record.detail = detail
            record.cancel_requested = True
            record.ended_at = time.time()
            record.updated_at = record.ended_at

        self._append_event(
            job_id,
            level="warning",
            message="Job cancelled",
            step="cancelled",
            detail=detail,
            progress=self._get_progress(job_id),
        )


# -----------------------------------------------------------------------------
# Singleton accessor
# -----------------------------------------------------------------------------

_JOB_MANAGER_SINGLETON: Optional[JobManager] = None
_JOB_MANAGER_SINGLETON_LOCK = threading.Lock()


def get_job_manager() -> JobManager:
    """Return singleton JobManager instance."""
    global _JOB_MANAGER_SINGLETON
    if _JOB_MANAGER_SINGLETON is None:
        with _JOB_MANAGER_SINGLETON_LOCK:
            if _JOB_MANAGER_SINGLETON is None:
                _JOB_MANAGER_SINGLETON = JobManager()
    return _JOB_MANAGER_SINGLETON


def reset_job_manager() -> JobManager:
    """Reset singleton JobManager.

    Useful in tests or during controlled reloads.
    """
    global _JOB_MANAGER_SINGLETON
    with _JOB_MANAGER_SINGLETON_LOCK:
        if _JOB_MANAGER_SINGLETON is not None:
            try:
                _JOB_MANAGER_SINGLETON.shutdown(wait=False, cancel_futures=False)
            except Exception:
                logger.exception("Error while shutting down previous JobManager")
        _JOB_MANAGER_SINGLETON = JobManager()
    return _JOB_MANAGER_SINGLETON
```

## [viewer.js]

경로: `version02/src/qcviz_mcp/web/static/viewer.js`

```javascript
(() => {
  "use strict";

  const DEFAULT_ESP_PRESETS = {
    rwb: { label: "Red-White-Blue", colors: ["#d73027", "#f7f7f7", "#4575b4"] },
    viridis: {
      label: "Viridis",
      colors: ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"],
    },
    inferno: {
      label: "Inferno",
      colors: [
        "#000004",
        "#420a68",
        "#932667",
        "#dd513a",
        "#fba40a",
        "#fcffa4",
      ],
    },
    spectral: {
      label: "Spectral",
      colors: [
        "#9e0142",
        "#f46d43",
        "#fdae61",
        "#ffffbf",
        "#abdda4",
        "#3288bd",
        "#5e4fa2",
      ],
    },
    nature: {
      label: "Nature",
      colors: ["#0b3c5d", "#328cc1", "#d9b310", "#1d2731"],
    },
    acs: { label: "ACS", colors: ["#b2182b", "#f7f7f7", "#2166ac"] },
    rsc: { label: "RSC", colors: ["#ca0020", "#f7f7f7", "#0571b0"] },
    matdark: {
      label: "Material Dark",
      colors: ["#1b1f2a", "#394b59", "#90caf9", "#f48fb1"],
    },
    grey: {
      label: "Greyscale",
      colors: ["#111111", "#666666", "#bbbbbb", "#f5f5f5"],
    },
    hicon: {
      label: "High Contrast",
      colors: ["#0000ff", "#ffffff", "#ff0000"],
    },
  };

  const DEFAULT_PRESET_ORDER = [
    "rwb",
    "viridis",
    "inferno",
    "spectral",
    "nature",
    "acs",
    "rsc",
    "matdark",
    "grey",
    "hicon",
  ];

  const state = {
    viewer: null,
    currentXYZ: "",
    currentResult: null,
    visualization: null,
    currentOrbitalKey: null,
    currentStyle: "ballstick",
    showAtomLabels: false,
    showChargeLabels: false,
    atomLabels: [],
    chargeLabels: [],
    orbitalSurfaceIds: [],
    espSurfaceId: null,
    espVisible: false,
    cache: {
      volumes: new Map(),
    },
    bound: false,
  };

  function $(sel) {
    return document.querySelector(sel);
  }

  function $all(sel) {
    return Array.from(document.querySelectorAll(sel));
  }

  function clamp(v, min, max) {
    const n = Number(v);
    if (!Number.isFinite(n)) return min;
    return Math.max(min, Math.min(max, n));
  }

  function setStatus(text, tone = "muted") {
    const el = $("#viz-status");
    if (!el) return;
    el.textContent = text || "";
    el.dataset.tone = tone;
  }

  function setControlValue(inputId, value, valueId, digits = 3) {
    const input = document.getElementById(inputId);
    if (input && value !== undefined && value !== null && value !== "") {
      input.value = String(value);
    }
    const out = document.getElementById(valueId);
    if (out && value !== undefined && value !== null && value !== "") {
      const num = Number(value);
      out.textContent = Number.isFinite(num)
        ? num.toFixed(digits)
        : String(value);
    }
  }

  function toggleEl(el, show) {
    if (!el) return;
    el.hidden = !show;
    el.style.display = show ? "" : "none";
  }

  function downloadURI(uri, filename) {
    const a = document.createElement("a");
    a.href = uri;
    a.download = filename || "qcviz-view.png";
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  function qcvizNormalizeB64(b64) {
    if (!b64) return "";
    let s = String(b64).trim();
    s = s.replace(/^data:.*?;base64,/, "");
    s = s.replace(/\s+/g, "");
    s = s.replace(/-/g, "+").replace(/_/g, "/");
    const pad = s.length % 4;
    if (pad) s += "=".repeat(4 - pad);
    return s;
  }

  function qcvizDecodeB64Text(b64) {
    const normalized = qcvizNormalizeB64(b64);
    if (!normalized) return "";
    const binary = atob(normalized);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    try {
      return new TextDecoder("utf-8").decode(bytes);
    } catch (_) {
      let out = "";
      for (let i = 0; i < bytes.length; i += 1)
        out += String.fromCharCode(bytes[i]);
      return out;
    }
  }

  function parseXYZAtoms(xyz) {
    const text = String(xyz || "").trim();
    if (!text) return [];
    const lines = text.split(/\r?\n/).filter(Boolean);
    let start = 0;
    if (/^\d+$/.test((lines[0] || "").trim())) start = 2;
    const atoms = [];
    for (let i = start; i < lines.length; i += 1) {
      const p = lines[i].trim().split(/\s+/);
      if (p.length < 4) continue;
      const x = Number(p[1]);
      const y = Number(p[2]);
      const z = Number(p[3]);
      if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z))
        continue;
      atoms.push({ index: atoms.length, elem: p[0], x, y, z });
    }
    return atoms;
  }

  function getViewer() {
    if (state.viewer) return state.viewer;
    const host = $("#v3d");
    if (!host) {
      throw new Error("#v3d container not found");
    }
    if (!window.$3Dmol) {
      throw new Error("3Dmol.js not loaded");
    }
    state.viewer = window.$3Dmol.createViewer(host, {
      backgroundColor: "#ffffff",
      antialias: true,
      id: "qcviz-main-viewer",
    });
    return state.viewer;
  }

  function getStyleSpec(styleName) {
    const style = String(styleName || "ballstick").toLowerCase();
    if (style === "stick") {
      return { stick: { radius: 0.18, colorscheme: "default" } };
    }
    if (style === "sphere") {
      return { sphere: { scale: 0.32, colorscheme: "Jmol" } };
    }
    if (style === "line") {
      return { line: { linewidth: 2 } };
    }
    return {
      stick: { radius: 0.16, colorscheme: "default" },
      sphere: { scale: 0.28, colorscheme: "Jmol" },
    };
  }

  function applyBaseStyle(styleName = state.currentStyle) {
    const viewer = getViewer();
    state.currentStyle = styleName || "ballstick";
    viewer.setStyle({}, getStyleSpec(state.currentStyle));
    viewer.render();
    syncStyleButtonState();
  }

  function syncStyleButtonState() {
    const map = {
      ballstick: "#btn-style-ballstick",
      stick: "#btn-style-stick",
      sphere: "#btn-style-sphere",
    };
    Object.entries(map).forEach(([key, sel]) => {
      const btn = $(sel);
      if (!btn) return;
      btn.classList.toggle("is-active", state.currentStyle === key);
    });
  }

  function clearLabels() {
    const viewer = getViewer();
    [...state.atomLabels, ...state.chargeLabels].forEach((label) => {
      try {
        viewer.removeLabel(label);
      } catch (_) {}
    });
    state.atomLabels = [];
    state.chargeLabels = [];
    viewer.render();
  }

  function renderAtomLabels() {
    const viewer = getViewer();
    const atoms = parseXYZAtoms(state.currentXYZ);
    state.atomLabels.forEach((label) => {
      try {
        viewer.removeLabel(label);
      } catch (_) {}
    });
    state.atomLabels = [];
    atoms.forEach((a) => {
      try {
        const label = viewer.addLabel(`${a.elem}${a.index + 1}`, {
          position: { x: a.x, y: a.y, z: a.z },
          backgroundColor: "rgba(15,23,42,0.85)",
          fontColor: "#ffffff",
          fontSize: 12,
          borderThickness: 0,
          inFront: true,
          screenOffset: { x: 0, y: -10 },
        });
        state.atomLabels.push(label);
      } catch (_) {}
    });
    viewer.render();
  }

  function getChargesArray() {
    const res = state.currentResult || {};
    const charges = res.partial_charges || res.charges || [];
    if (!Array.isArray(charges)) return [];
    return charges;
  }

  function renderChargeLabels() {
    const viewer = getViewer();
    const atoms = parseXYZAtoms(state.currentXYZ);
    const charges = getChargesArray();
    state.chargeLabels.forEach((label) => {
      try {
        viewer.removeLabel(label);
      } catch (_) {}
    });
    state.chargeLabels = [];
    charges.forEach((c, i) => {
      const atom = atoms[i];
      if (!atom) return;
      const q = Number(c?.charge ?? c?.value ?? c);
      if (!Number.isFinite(q)) return;
      try {
        const label = viewer.addLabel(`${q >= 0 ? "+" : ""}${q.toFixed(3)}`, {
          position: { x: atom.x, y: atom.y, z: atom.z },
          backgroundColor: "rgba(255,255,255,0.9)",
          fontColor: q >= 0 ? "#b91c1c" : "#1d4ed8",
          fontSize: 11,
          borderColor: "rgba(148,163,184,0.7)",
          borderThickness: 1,
          inFront: true,
          screenOffset: { x: 0, y: 12 },
        });
        state.chargeLabels.push(label);
      } catch (_) {}
    });
    viewer.render();
  }

  function syncLabels() {
    clearLabels();
    if (state.showAtomLabels) renderAtomLabels();
    if (state.showChargeLabels) renderChargeLabels();
  }

  function safeRemoveSurface(surfaceId) {
    if (!surfaceId) return;
    const viewer = getViewer();
    try {
      viewer.removeSurface(surfaceId);
    } catch (_) {}
  }

  function clearOrbitalSurfaces() {
    state.orbitalSurfaceIds.forEach((id) => safeRemoveSurface(id));
    state.orbitalSurfaceIds = [];
    try {
      getViewer().render();
    } catch (_) {}
  }

  function clearESPSurface() {
    safeRemoveSurface(state.espSurfaceId);
    state.espSurfaceId = null;
    state.espVisible = false;
    try {
      getViewer().render();
    } catch (_) {}
  }

  function clearSurfaces() {
    clearOrbitalSurfaces();
    clearESPSurface();
    setStatus("표면을 지웠습니다.", "muted");
  }

  function loadXYZ(xyz, { keepCamera = false } = {}) {
    const text = String(xyz || "").trim();
    if (!text) return false;

    const viewer = getViewer();
    state.currentXYZ = text;

    viewer.clear();
    viewer.addModel(text, "xyz");
    applyBaseStyle(state.currentStyle);
    if (!keepCamera) viewer.zoomTo();
    viewer.render();

    state.atomLabels = [];
    state.chargeLabels = [];
    state.orbitalSurfaceIds = [];
    state.espSurfaceId = null;
    state.espVisible = false;

    syncLabels();
    setStatus("분자 구조를 불러왔습니다.", "ok");
    return true;
  }

  function volumeCacheKey(prefix, b64) {
    const s = qcvizNormalizeB64(b64);
    return `${prefix}:${s.length}:${s.slice(0, 96)}`;
  }

  function makeVolumeDataFromB64(prefix, b64) {
    const key = volumeCacheKey(prefix, b64);
    if (state.cache.volumes.has(key)) return state.cache.volumes.get(key);

    const cubeText = qcvizDecodeB64Text(b64);
    if (!cubeText) throw new Error(`Empty cube data for ${prefix}`);

    const vol = new window.$3Dmol.VolumeData(cubeText, "cube");
    state.cache.volumes.set(key, vol);
    return vol;
  }

  function pickPresetCatalog() {
    const viz = state.visualization || {};
    const esp = viz.esp || {};
    return esp.presets || DEFAULT_ESP_PRESETS;
  }

  function pickPresetOrder() {
    const viz = state.visualization || {};
    const esp = viz.esp || {};
    return Array.isArray(esp.preset_order) && esp.preset_order.length
      ? esp.preset_order
      : DEFAULT_PRESET_ORDER;
  }

  function syncEspSelectOptions() {
    const sel = $("#sel-esp");
    if (!sel) return;
    const presets = pickPresetCatalog();
    const order = pickPresetOrder();
    const current =
      sel.value || ((state.visualization?.defaults || {}).esp_preset ?? "rwb");

    sel.innerHTML = order
      .filter((k) => presets[k])
      .map((k) => `<option value="${k}">${presets[k].label || k}</option>`)
      .join("");

    if ([...sel.options].some((o) => o.value === current)) {
      sel.value = current;
    } else if (sel.options.length) {
      sel.selectedIndex = 0;
    }
  }

  function makeGradient(presetKey, vmin, vmax) {
    const $3Dmol = window.$3Dmol;
    if (!$3Dmol || !$3Dmol.Gradient) return null;

    const key = String(presetKey || "rwb").toLowerCase();
    const range1 = [vmin, vmax];
    const range2 = { min: vmin, max: vmax };

    const presets = pickPresetCatalog();
    const colors =
      presets[key]?.colors ||
      DEFAULT_ESP_PRESETS[key]?.colors ||
      DEFAULT_ESP_PRESETS.rwb.colors;

    const tryBuilders = [
      () =>
        $3Dmol.Gradient.CustomLinear
          ? new $3Dmol.Gradient.CustomLinear(range1, colors)
          : null,
      () =>
        $3Dmol.Gradient.CustomLinear
          ? new $3Dmol.Gradient.CustomLinear(range2, colors)
          : null,
      () => ($3Dmol.Gradient.RWB ? new $3Dmol.Gradient.RWB(vmin, vmax) : null),
      () => ($3Dmol.Gradient.RWB ? new $3Dmol.Gradient.RWB(range1) : null),
      () =>
        $3Dmol.Gradient.ROYGB ? new $3Dmol.Gradient.ROYGB(vmin, vmax) : null,
      () => ($3Dmol.Gradient.ROYGB ? new $3Dmol.Gradient.ROYGB(range1) : null),
      () =>
        $3Dmol.Gradient.Sinebow
          ? new $3Dmol.Gradient.Sinebow(vmin, vmax)
          : null,
      () =>
        $3Dmol.Gradient.Sinebow ? new $3Dmol.Gradient.Sinebow(range1) : null,
    ];

    if (key === "grey") {
      tryBuilders.unshift(() =>
        $3Dmol.Gradient.CustomLinear
          ? new $3Dmol.Gradient.CustomLinear(range1, ["#111111", "#ffffff"])
          : null,
      );
    }

    for (const build of tryBuilders) {
      try {
        const g = build();
        if (g) return g;
      } catch (_) {}
    }
    return null;
  }

  function setVisualizationData(viz) {
    state.visualization = viz && typeof viz === "object" ? viz : null;
    const defaults = state.visualization?.defaults || {};

    setControlValue(
      "orb-iso-slider",
      defaults.orbital_iso ?? 0.02,
      "orb-iso-value",
      3,
    );
    setControlValue(
      "orb-opa-slider",
      defaults.orbital_opacity ?? 0.78,
      "orb-opa-value",
      2,
    );
    setControlValue(
      "esp-iso-slider",
      defaults.esp_iso ?? 0.03,
      "esp-iso-value",
      3,
    );
    setControlValue(
      "esp-opa-slider",
      defaults.esp_opacity ?? 0.72,
      "esp-opa-value",
      2,
    );
    setControlValue(
      "esp-range-slider",
      defaults.esp_range ?? 0.05,
      "esp-range-value",
      3,
    );

    syncEspSelectOptions();

    const sel = $("#sel-esp");
    if (sel) {
      const preset = defaults.esp_preset || "rwb";
      if ([...sel.options].some((o) => o.value === preset)) sel.value = preset;
    }

    const orbAvail = !!state.visualization?.orbitals?.available;
    const espAvail = !!state.visualization?.esp?.available;
    toggleEl($("#orbital-controls"), orbAvail);
    toggleEl($("#esp-controls"), espAvail);

    state.currentOrbitalKey =
      state.visualization?.orbitals?.selected_key ||
      state.currentOrbitalKey ||
      null;
  }

  function setResultData(result) {
    state.currentResult = result && typeof result === "object" ? result : null;
    if (state.currentResult?.xyz) {
      loadXYZ(state.currentResult.xyz);
    }
    setVisualizationData(state.currentResult?.visualization || null);
    syncLabels();
  }

  function findOrbitalByKey(key) {
    const items = state.visualization?.orbitals?.items || [];
    return items.find((x) => String(x.key) === String(key)) || null;
  }

  function syncOrbitalChipState() {
    $all(".orbital-chip").forEach((btn) => {
      btn.classList.toggle(
        "is-active",
        String(btn.dataset.orbKey) === String(state.currentOrbitalKey),
      );
    });
  }

  function renderOrbital(cubeB64, iso = 0.02, opacity = 0.78, opts = {}) {
    if (!cubeB64) {
      setStatus("오비탈 cube 데이터가 없습니다.", "warn");
      return false;
    }

    const viewer = getViewer();
    clearOrbitalSurfaces();

    const absIso = Math.max(0.001, Math.abs(Number(iso) || 0.02));
    const opa = clamp(opacity, 0.05, 1.0);
    const posColor = opts.positiveColor || "#2563eb";
    const negColor = opts.negativeColor || "#ef4444";

    try {
      const vol = makeVolumeDataFromB64("orb", cubeB64);

      const posId = viewer.addIsosurface(vol, {
        isoval: absIso,
        color: posColor,
        opacity: opa,
        smoothness: 2,
      });

      const negId = viewer.addIsosurface(vol, {
        isoval: -absIso,
        color: negColor,
        opacity: opa,
        smoothness: 2,
      });

      state.orbitalSurfaceIds = [posId, negId].filter(Boolean);
      viewer.render();
      setStatus("오비탈 isosurface를 렌더링했습니다.", "ok");
      return true;
    } catch (err) {
      console.error("renderOrbital failed", err);
      setStatus(`오비탈 렌더 실패: ${err?.message || err}`, "error");
      return false;
    }
  }

  function renderOrbitalByKey(key, iso, opacity) {
    const item = findOrbitalByKey(key);
    if (!item || !item.cube_b64) {
      setStatus("선택한 오비탈 cube 데이터를 찾지 못했습니다.", "warn");
      return false;
    }
    state.currentOrbitalKey = String(item.key);
    syncOrbitalChipState();
    return renderOrbital(item.cube_b64, iso, opacity);
  }

  function renderESP({
    densityCubeB64,
    potentialCubeB64,
    preset,
    iso,
    opacity,
    range,
  } = {}) {
    const viewer = getViewer();
    const viz = state.visualization || {};
    const esp = viz.esp || {};
    const defaults = viz.defaults || {};

    const densityB64 = densityCubeB64 || esp.density_cube_b64;
    const potentialB64 = potentialCubeB64 || esp.potential_cube_b64;
    const absIso = Math.max(
      0.001,
      Math.abs(Number(iso ?? defaults.esp_iso ?? 0.03)),
    );
    const opa = clamp(opacity ?? defaults.esp_opacity ?? 0.72, 0.05, 1.0);
    const rng = Math.max(
      0.001,
      Math.abs(Number(range ?? defaults.esp_range ?? 0.05)),
    );
    const presetKey = String(preset || defaults.esp_preset || "rwb");

    if (!densityB64 || !potentialB64) {
      setStatus("ESP density/potential cube 데이터가 없습니다.", "warn");
      return false;
    }

    clearESPSurface();

    try {
      const densityVol = makeVolumeDataFromB64("esp-density", densityB64);
      const potVol = makeVolumeDataFromB64("esp-pot", potentialB64);
      const volscheme = makeGradient(presetKey, -rng, rng);

      state.espSurfaceId = viewer.addIsosurface(densityVol, {
        isoval: absIso,
        opacity: opa,
        color: "white",
        smoothness: 2,
        voldata: potVol,
        volscheme: volscheme || undefined,
      });

      state.espVisible = true;
      viewer.render();
      setStatus("ESP 표면을 분자 위에 입혔습니다.", "ok");
      return true;
    } catch (err) {
      console.error("renderESP failed", err);
      try {
        const densityVol = makeVolumeDataFromB64(
          "esp-density-fallback",
          densityB64,
        );
        state.espSurfaceId = viewer.addIsosurface(densityVol, {
          isoval: absIso,
          opacity: opa,
          color: "#94a3b8",
          smoothness: 2,
        });
        state.espVisible = true;
        viewer.render();
        setStatus(
          "ESP 컬러맵 적용은 실패했지만 density 표면은 렌더링했습니다.",
          "warn",
        );
        return true;
      } catch (err2) {
        console.error("renderESP fallback failed", err2);
        setStatus(`ESP 렌더 실패: ${err2?.message || err2}`, "error");
        return false;
      }
    }
  }

  function refreshOrbSurfaces() {
    const iso = Number($("#orb-iso-slider")?.value || 0.02);
    const opacity = Number($("#orb-opa-slider")?.value || 0.78);
    setControlValue("orb-iso-slider", iso, "orb-iso-value", 3);
    setControlValue("orb-opa-slider", opacity, "orb-opa-value", 2);

    const key =
      state.currentOrbitalKey ||
      state.visualization?.orbitals?.selected_key ||
      state.visualization?.orbitals?.items?.[0]?.key;

    if (!key) {
      setStatus("렌더할 오비탈이 없습니다.", "warn");
      return false;
    }
    return renderOrbitalByKey(key, iso, opacity);
  }

  function refreshESPSurface() {
    const iso = Number($("#esp-iso-slider")?.value || 0.03);
    const opacity = Number($("#esp-opa-slider")?.value || 0.72);
    const range = Number($("#esp-range-slider")?.value || 0.05);
    const preset = $("#sel-esp")?.value || "rwb";

    setControlValue("esp-iso-slider", iso, "esp-iso-value", 3);
    setControlValue("esp-opa-slider", opacity, "esp-opa-value", 2);
    setControlValue("esp-range-slider", range, "esp-range-value", 3);

    return renderESP({ iso, opacity, range, preset });
  }

  function zoomTo() {
    const viewer = getViewer();
    viewer.zoomTo();
    viewer.render();
  }

  function resetView() {
    clearSurfaces();
    state.showAtomLabels = false;
    state.showChargeLabels = false;
    syncLabels();
    applyBaseStyle("ballstick");
    zoomTo();
    setStatus("뷰를 초기화했습니다.", "ok");
  }

  function bindStaticControls() {
    if (state.bound) return;
    state.bound = true;

    const bind = (sel, evt, fn) => {
      const el = $(sel);
      if (el) el.addEventListener(evt, fn);
    };

    bind("#btn-style-ballstick", "click", () => applyBaseStyle("ballstick"));
    bind("#btn-style-stick", "click", () => applyBaseStyle("stick"));
    bind("#btn-style-sphere", "click", () => applyBaseStyle("sphere"));

    bind("#btn-labels", "click", () => {
      state.showAtomLabels = !state.showAtomLabels;
      syncLabels();
      $("#btn-labels")?.classList.toggle("is-active", state.showAtomLabels);
    });

    bind("#btn-charges", "click", () => {
      state.showChargeLabels = !state.showChargeLabels;
      syncLabels();
      $("#btn-charges")?.classList.toggle("is-active", state.showChargeLabels);
    });

    bind("#btn-reset", "click", () => resetView());

    bind("#btn-screenshot", "click", () => {
      try {
        const uri = getViewer().pngURI();
        downloadURI(uri, `qcviz-${Date.now()}.png`);
      } catch (err) {
        console.error(err);
        setStatus("스크린샷 저장 실패", "error");
      }
    });

    bind("#btn-orb-render", "click", () => refreshOrbSurfaces());
    bind("#btn-orb-clear", "click", () => clearOrbitalSurfaces());

    bind("#btn-esp", "click", () => {
      if (state.espVisible) {
        clearESPSurface();
        setStatus("ESP 표면을 숨겼습니다.", "muted");
      } else {
        refreshESPSurface();
      }
      $("#btn-esp")?.classList.toggle("is-active", state.espVisible);
    });

    bind("#btn-esp-render", "click", () => {
      refreshESPSurface();
      $("#btn-esp")?.classList.toggle("is-active", state.espVisible);
    });

    bind("#btn-esp-clear", "click", () => {
      clearESPSurface();
      $("#btn-esp")?.classList.toggle("is-active", state.espVisible);
    });

    bind("#orb-iso-slider", "input", (e) => {
      setControlValue("orb-iso-slider", e.target.value, "orb-iso-value", 3);
    });
    bind("#orb-opa-slider", "input", (e) => {
      setControlValue("orb-opa-slider", e.target.value, "orb-opa-value", 2);
    });
    bind("#esp-iso-slider", "input", (e) => {
      setControlValue("esp-iso-slider", e.target.value, "esp-iso-value", 3);
    });
    bind("#esp-opa-slider", "input", (e) => {
      setControlValue("esp-opa-slider", e.target.value, "esp-opa-value", 2);
    });
    bind("#esp-range-slider", "input", (e) => {
      setControlValue("esp-range-slider", e.target.value, "esp-range-value", 3);
    });

    bind("#orb-iso-slider", "change", () => refreshOrbSurfaces());
    bind("#orb-opa-slider", "change", () => refreshOrbSurfaces());
    bind("#esp-iso-slider", "change", () => refreshESPSurface());
    bind("#esp-opa-slider", "change", () => refreshESPSurface());
    bind("#esp-range-slider", "change", () => refreshESPSurface());
    bind("#sel-esp", "change", () => refreshESPSurface());

    document.addEventListener("click", (ev) => {
      const btn = ev.target.closest(".orbital-chip");
      if (!btn) return;
      const key = btn.dataset.orbKey;
      if (!key) return;
      state.currentOrbitalKey = key;
      syncOrbitalChipState();
      refreshOrbSurfaces();
    });

    document.addEventListener("keydown", (ev) => {
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "r") {
        ev.preventDefault();
        resetView();
      }
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "e") {
        ev.preventDefault();
        refreshESPSurface();
      }
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "o") {
        ev.preventDefault();
        refreshOrbSurfaces();
      }
    });
  }

  function init() {
    bindStaticControls();
    try {
      if ($("#v3d") && window.$3Dmol) {
        getViewer();
        applyBaseStyle("ballstick");
      }
    } catch (err) {
      console.error(err);
    }
  }

  const api = {
    qcvizGetViewer: getViewer,
    qcvizNormalizeB64,
    qcvizDecodeB64Text,
    setResultData,
    setVisualizationData,
    loadXYZ,
    applyBaseStyle,
    renderOrbital,
    renderOrbitalByKey,
    renderESP,
    refreshOrbSurfaces,
    refreshESPSurface,
    clearOrbitalSurfaces,
    clearESPSurface,
    clearSurfaces,
    zoomTo,
    resetView,
    getState: () => state,
    syncEspSelectOptions,
    syncLabels,
    init,
  };

  window.QCVizViewer = api;
  window.qcvizGetViewer = getViewer;
  window.qcvizNormalizeB64 = qcvizNormalizeB64;
  window.qcvizDecodeB64Text = qcvizDecodeB64Text;
  window.renderOrbital = api.renderOrbital;
  window.renderESP = api.renderESP;
  window.refreshOrbSurfaces = api.refreshOrbSurfaces;
  window.refreshESPSurface = api.refreshESPSurface;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
```

## [results.js]

경로: `version02/src/qcviz_mcp/web/static/results.js`

```javascript
(() => {
  "use strict";

  const state = {
    currentResult: null,
    currentTab: "summary",
    currentJobId: null,
    currentOrbitalKey: null,
  };

  function $(sel) {
    return document.querySelector(sel);
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function prettyJSON(obj) {
    try {
      return JSON.stringify(obj, null, 2);
    } catch (_) {
      return String(obj);
    }
  }

  function toNum(v, fallback = null) {
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  }

  function unwrapResult(payload) {
    if (!payload || typeof payload !== "object") return {};
    if (payload.result && typeof payload.result === "object")
      return payload.result;
    if (
      payload.job &&
      payload.job.result &&
      typeof payload.job.result === "object"
    )
      return payload.job.result;
    if (
      payload.data &&
      payload.data.result &&
      typeof payload.data.result === "object"
    )
      return payload.data.result;
    return payload;
  }

  function getViz(data) {
    return data && data.visualization && typeof data.visualization === "object"
      ? data.visualization
      : {};
  }

  function hasVizOrbitals(data) {
    const viz = getViz(data);
    return !!(
      viz.orbitals &&
      viz.orbitals.available &&
      Array.isArray(viz.orbitals.items) &&
      viz.orbitals.items.length
    );
  }

  function hasVizESP(data) {
    const viz = getViz(data);
    return !!(
      viz.esp &&
      viz.esp.available &&
      viz.esp.density_cube_b64 &&
      viz.esp.potential_cube_b64
    );
  }

  function vizDefaults(data) {
    const d = getViz(data).defaults || {};
    return {
      orbital_iso: toNum(d.orbital_iso, 0.02),
      orbital_opacity: toNum(d.orbital_opacity, 0.78),
      esp_iso: toNum(d.esp_iso, 0.03),
      esp_opacity: toNum(d.esp_opacity, 0.72),
      esp_range: toNum(d.esp_range, 0.05),
      esp_preset: d.esp_preset || "rwb",
    };
  }

  function getCharges(data) {
    const arr = data?.partial_charges || data?.charges || [];
    return Array.isArray(arr) ? arr : [];
  }

  function ensureContainers() {
    let tabs = $("#result-tabs");
    let content = $("#result-content");

    if (!tabs || !content) {
      const host =
        $("#results-console") ||
        $(".results-console") ||
        $("#results-panel") ||
        document.body;

      if (!tabs) {
        tabs = document.createElement("div");
        tabs.id = "result-tabs";
        tabs.className = "result-tabs";
        host.appendChild(tabs);
      }
      if (!content) {
        content = document.createElement("div");
        content.id = "result-content";
        content.className = "result-content";
        host.appendChild(content);
      }
    }

    return { tabs, content };
  }

  function resultTitle(data) {
    return (
      data.display_name ||
      data.name ||
      data.structure_query ||
      data.formula ||
      "Result"
    );
  }

  function energyCard(data) {
    const eh = toNum(data.total_energy_hartree, null);
    const ev = toNum(data.total_energy_ev, null);
    const gap = toNum(data.orbital_gap_ev, null);

    return `
      <div class="metric-grid">
        <div class="metric-card">
          <div class="metric-label">Energy (Ha)</div>
          <div class="metric-value">${eh !== null ? eh.toFixed(8) : "—"}</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">Energy (eV)</div>
          <div class="metric-value">${ev !== null ? ev.toFixed(4) : "—"}</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">HOMO-LUMO Gap</div>
          <div class="metric-value">${gap !== null ? `${gap.toFixed(3)} eV` : "—"}</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">Converged</div>
          <div class="metric-value">${data.converged === true ? "Yes" : data.converged === false ? "No" : "—"}</div>
        </div>
      </div>
    `;
  }

  function warningBlock(data) {
    const warnings = Array.isArray(data?.warnings)
      ? data.warnings.filter(Boolean)
      : [];
    if (!warnings.length) return "";
    return `
      <div class="result-card warning-card">
        <div class="result-card-title">Warnings</div>
        <ul class="warning-list">
          ${warnings.map((w) => `<li>${escapeHtml(w)}</li>`).join("")}
        </ul>
      </div>
    `;
  }

  function summaryTab(data) {
    const title = escapeHtml(resultTitle(data));
    const formula = escapeHtml(data.formula || "—");
    const atomCount = escapeHtml(data.atom_count ?? "—");
    const method = escapeHtml(data.method || "—");
    const basis = escapeHtml(data.basis || "—");
    const charge = escapeHtml(data.charge ?? 0);
    const multiplicity = escapeHtml(data.multiplicity ?? (data.spin ?? 0) + 1);
    const canOrb = hasVizOrbitals(data);
    const canESP = hasVizESP(data);

    return `
      <div class="result-card">
        <div class="result-card-title">Summary</div>
        <div class="summary-grid">
          <div><strong>Name</strong><br>${title}</div>
          <div><strong>Formula</strong><br>${formula}</div>
          <div><strong>Atoms</strong><br>${atomCount}</div>
          <div><strong>Method</strong><br>${method}</div>
          <div><strong>Basis</strong><br>${basis}</div>
          <div><strong>Charge / Multiplicity</strong><br>${charge} / ${multiplicity}</div>
        </div>
      </div>

      ${energyCard(data)}

      <div class="result-card">
        <div class="result-card-title">Visualization</div>
        <div class="chip-row">
          <button class="chip ${canOrb ? "" : "is-disabled"}" data-open-tab="orbitals" ${canOrb ? "" : "disabled"}>
            Orbitals ${canOrb ? "ready" : "unavailable"}
          </button>
          <button class="chip ${canESP ? "" : "is-disabled"}" data-open-tab="esp" ${canESP ? "" : "disabled"}>
            ESP ${canESP ? "ready" : "unavailable"}
          </button>
          <button class="chip" data-open-tab="geometry">Geometry</button>
          <button class="chip" data-open-tab="json">JSON</button>
        </div>
      </div>

      ${warningBlock(data)}
    `;
  }

  function geometryTab(data) {
    const geom = data.geometry_summary || {};
    const bonds = Array.isArray(geom.bonds) ? geom.bonds : [];
    const xyz = escapeHtml(data.xyz || "");

    return `
      <div class="result-card">
        <div class="result-card-title">Geometry</div>
        <div class="summary-grid">
          <div><strong>Formula</strong><br>${escapeHtml(geom.formula || data.formula || "—")}</div>
          <div><strong>Atoms</strong><br>${escapeHtml(geom.atom_count ?? data.atom_count ?? "—")}</div>
          <div><strong>Bonds</strong><br>${escapeHtml(bonds.length)}</div>
        </div>
      </div>

      <div class="result-card">
        <div class="result-card-title">XYZ</div>
        <pre class="code-block"><code>${xyz}</code></pre>
      </div>

      <div class="result-card">
        <div class="result-card-title">Estimated Bonds</div>
        ${
          bonds.length
            ? `
              <div class="table-wrap">
                <table class="data-table">
                  <thead><tr><th>#</th><th>Pair</th><th>Length (Å)</th></tr></thead>
                  <tbody>
                    ${bonds
                      .map(
                        (b, i) => `
                      <tr>
                        <td>${i + 1}</td>
                        <td>${escapeHtml(`${b.a}${b.i + 1} - ${b.b}${b.j + 1}`)}</td>
                        <td>${toNum(b.length_angstrom, null) !== null ? Number(b.length_angstrom).toFixed(4) : "—"}</td>
                      </tr>
                    `,
                      )
                      .join("")}
                  </tbody>
                </table>
              </div>
            `
            : `<div class="empty-state">표시할 bond 추정 결과가 없습니다.</div>`
        }
      </div>
    `;
  }

  function orbitalTab(data) {
    const viz = getViz(data);
    const items = Array.isArray(viz?.orbitals?.items) ? viz.orbitals.items : [];
    const defaults = vizDefaults(data);
    const selectedKey =
      state.currentOrbitalKey ||
      viz?.orbitals?.selected_key ||
      items[0]?.key ||
      "";

    if (!items.length) {
      return `
        <div class="result-card">
          <div class="result-card-title">Orbitals</div>
          <div class="empty-state">오비탈 시각화 데이터가 없습니다.</div>
        </div>
      `;
    }

    return `
      <div class="result-card">
        <div class="result-card-title">Orbital Visualizer</div>
        <div class="card-subtitle">
          오비탈 버튼을 누르면 3D viewer 위에 ± isosurface가 바로 입혀집니다.
        </div>
        <div class="chip-row orbital-chip-row">
          ${items
            .map(
              (item) => `
            <button
              type="button"
              class="orbital-chip ${String(item.key) === String(selectedKey) ? "is-active" : ""}"
              data-orb-key="${escapeHtml(item.key)}"
              title="${escapeHtml(item.label || item.key)}"
            >
              <span class="orbital-chip-label">${escapeHtml(item.label || item.key)}</span>
              <span class="orbital-chip-meta">
                ${toNum(item.energy_ev, null) !== null ? `${Number(item.energy_ev).toFixed(2)} eV` : ""}
              </span>
            </button>
          `,
            )
            .join("")}
        </div>
      </div>

      <div class="result-card">
        <div class="result-card-title">Orbital Controls</div>
        <div class="inline-kv">
          <div>Default iso: <strong>${defaults.orbital_iso.toFixed(3)}</strong></div>
          <div>Default opacity: <strong>${defaults.orbital_opacity.toFixed(2)}</strong></div>
          <div>Surfaces: <strong>positive / negative</strong></div>
        </div>
        <div class="card-subtitle">
          상단 viewer control bar의 Orbital 섹션에서 iso / opacity를 조절하면 바로 재렌더됩니다.
        </div>
      </div>
    `;
  }

  function espTab(data) {
    const viz = getViz(data);
    const esp = viz.esp || {};
    const defaults = vizDefaults(data);
    const presets =
      esp.presets ||
      window.QCVizViewer?.getState()?.visualization?.esp?.presets ||
      {};
    const presetLabel =
      presets[defaults.esp_preset]?.label || defaults.esp_preset;

    if (!hasVizESP(data)) {
      return `
        <div class="result-card">
          <div class="result-card-title">Electrostatic Potential (ESP)</div>
          <div class="empty-state">ESP 시각화 데이터가 없습니다.</div>
        </div>
      `;
    }

    return `
      <div class="result-card">
        <div class="result-card-title">ESP Visualizer</div>
        <div class="card-subtitle">
          상단의 ESP [Toggle] 버튼을 누르거나 Control bar에서 속성을 변경하면 바로 반영됩니다.
        </div>
        <div class="inline-kv mt-sm">
          <div>Density Isovalue: <strong>${defaults.esp_iso.toFixed(3)}</strong></div>
          <div>Opacity: <strong>${defaults.esp_opacity.toFixed(2)}</strong></div>
          <div>Color Range: <strong>±${defaults.esp_range.toFixed(3)}</strong></div>
          <div>Preset: <strong>${escapeHtml(presetLabel)}</strong></div>
        </div>
      </div>
    `;
  }

  function jsonTab(data) {
    return `
      <div class="result-card">
        <div class="result-card-title">Raw JSON</div>
        <pre class="code-block"><code>${escapeHtml(prettyJSON(data))}</code></pre>
      </div>
    `;
  }

  function jobsTab() {
    const jobs = Array.isArray(state.currentJobs) ? state.currentJobs : [];
    if (!jobs.length) {
      return `
        <div class="result-card">
          <div class="result-card-title">Recent Jobs</div>
          <div class="empty-state">최근 실행된 작업이 없습니다.</div>
        </div>
      `;
    }

    return `
      <div class="result-card">
        <div class="result-card-title">Recent Jobs</div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Status</th>
                <th>Phase</th>
                <th>Progress</th>
              </tr>
            </thead>
            <tbody>
              ${jobs
                .map((j) => {
                  const pct = Math.round((j.progress || 0) * 100);
                  return `
                  <tr>
                    <td><span class="mono-text" title="${escapeHtml(j.job_id)}">${escapeHtml(j.job_id.substring(0, 8))}</span></td>
                    <td>
                      <span class="status-badge status-${j.status}">
                        ${escapeHtml(j.status)}
                      </span>
                    </td>
                    <td>${escapeHtml(j.step || j.phase || "—")}</td>
                    <td>
                      <div style="display: flex; align-items: center; gap: 8px;">
                        <progress value="${pct}" max="100" style="width: 60px; height: 6px;"></progress>
                        <span style="font-size: 11px; color: var(--text-muted);">${pct}%</span>
                      </div>
                    </td>
                  </tr>
                `;
                })
                .join("")}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  function renderTabs() {
    const { tabs } = ensureContainers();
    const result = state.currentResult || {};
    const current = state.currentTab;

    const nav = [
      { id: "summary", label: "Summary" },
      { id: "orbitals", label: "Orbitals", disabled: !hasVizOrbitals(result) },
      { id: "esp", label: "ESP Map", disabled: !hasVizESP(result) },
      { id: "geometry", label: "Geometry" },
      { id: "json", label: "JSON" },
      { id: "jobs", label: "Jobs" },
    ];

    tabs.innerHTML = nav
      .map(
        (t) => `
        <button
          class="tab-button ${t.id === current ? "is-active" : ""}"
          data-tab="${t.id}"
          ${t.disabled ? "disabled" : ""}
        >
          ${t.label}
        </button>
      `,
      )
      .join("");
  }

  function _renderActiveTab() {
    const { content } = ensureContainers();
    const data = state.currentResult;
    const tabId = state.currentTab;

    if (tabId === "jobs") {
      content.innerHTML = jobsTab();
      return;
    }

    if (!data) {
      content.innerHTML = `<div class="empty-state">결과 데이터가 없습니다. 계산을 요청해 보세요.</div>`;
      return;
    }

    let html = "";
    switch (tabId) {
      case "orbitals":
        html = orbitalTab(data);
        break;
      case "esp":
        html = espTab(data);
        break;
      case "geometry":
        html = geometryTab(data);
        break;
      case "json":
        html = jsonTab(data);
        break;
      case "summary":
      default:
        html = summaryTab(data);
        break;
    }

    content.innerHTML = html;
  }

  function syncViewer() {
    if (!window.QCVizViewer) return;
    const viewer = window.QCVizViewer;

    if (state.currentResult) {
      viewer.setResultData(state.currentResult);
      if (state.currentOrbitalKey) {
        state.currentResult.visualization =
          state.currentResult.visualization || {};
        state.currentResult.visualization.orbitals =
          state.currentResult.visualization.orbitals || {};
        state.currentResult.visualization.orbitals.selected_key =
          state.currentOrbitalKey;
      }
    }
  }

  function switchTab(tabId) {
    state.currentTab = tabId;
    renderTabs();
    _renderActiveTab();
  }

  function setResult(rawPayload) {
    const data = unwrapResult(rawPayload);
    state.currentResult = data;
    if (data && data.advisor_focus_tab) {
      state.currentTab = data.advisor_focus_tab;
    } else {
      state.currentTab = "summary";
    }

    const viz = getViz(data);
    if (viz?.orbitals?.selected_key) {
      state.currentOrbitalKey = viz.orbitals.selected_key;
    } else if (viz?.orbitals?.items?.[0]?.key) {
      state.currentOrbitalKey = viz.orbitals.items[0].key;
    } else {
      state.currentOrbitalKey = null;
    }

    syncViewer();
    renderTabs();
    _renderActiveTab();

    if (state.currentTab === "orbitals" && window.QCVizViewer) {
      window.QCVizViewer.refreshOrbSurfaces();
    }
  }

  function updateJobs(jobs) {
    state.currentJobs = Array.isArray(jobs) ? jobs : [];
    if (state.currentTab === "jobs") {
      _renderActiveTab();
    }
  }

  function setJobId(jobId) {
    state.currentJobId = jobId;
  }

  function clearResult() {
    state.currentResult = null;
    state.currentJobId = null;
    state.currentOrbitalKey = null;
    state.currentTab = "summary";
    renderTabs();
    _renderActiveTab();
    if (window.QCVizViewer) {
      window.QCVizViewer.setResultData(null);
      window.QCVizViewer.resetView();
    }
  }

  function init() {
    document.addEventListener("click", (e) => {
      const tabBtn = e.target.closest(".tab-button");
      if (tabBtn && tabBtn.dataset.tab) {
        if (!tabBtn.disabled) switchTab(tabBtn.dataset.tab);
        return;
      }

      const openBtn = e.target.closest("[data-open-tab]");
      if (openBtn && openBtn.dataset.openTab) {
        if (!openBtn.disabled) switchTab(openBtn.dataset.openTab);
        return;
      }

      const orbBtn = e.target.closest(".orbital-chip");
      if (orbBtn && orbBtn.dataset.orbKey) {
        state.currentOrbitalKey = orbBtn.dataset.orbKey;
        if (window.QCVizViewer) {
          window.QCVizViewer.getState().currentOrbitalKey =
            state.currentOrbitalKey;
          window.QCVizViewer.refreshOrbSurfaces();
        }
        $all(".orbital-chip").forEach((b) => b.classList.remove("is-active"));
        orbBtn.classList.add("is-active");
      }
    });

    renderTabs();
    _renderActiveTab();
  }

  window.QCVizResults = {
    setResult,
    clearResult,
    setJobId,
    updateJobs,
    switchTab,
    getState: () => state,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
```

## [chat.js]

경로: `version02/src/qcviz_mcp/web/static/chat.js`

```javascript
(function () {
  "use strict";

  function _renderJobProgress(progress, message, step) {
    var jobEvents = _el("jobEvents");
    if (!jobEvents) return;

    // Clear 'No active jobs' empty state if it exists
    var emptyState = jobEvents.querySelector(".empty-state");
    if (emptyState) {
      jobEvents.innerHTML = "";
    }

    var div = document.createElement("div");
    div.className = "job-event-item";
    div.style.padding = "8px 12px";
    div.style.borderBottom = "1px solid rgba(148,163,184,0.15)";
    div.style.fontSize = "12px";
    div.style.color = "var(--qv-text)";

    var timeStr = new Date().toLocaleTimeString();
    var pct = Math.round((progress || 0) * 100);

    div.innerHTML =
      "<div style='display:flex; justify-content:space-between; margin-bottom:4px;'>" +
      "<strong style='color:var(--qv-primary-strong)'>" +
      _escapeHtml(step || "Working") +
      "</strong>" +
      "<span style='color:var(--qv-muted); font-size:11px;'>" +
      timeStr +
      "</span>" +
      "</div>" +
      "<div style='margin-bottom:6px; color:var(--qv-muted);'>" +
      _escapeHtml(message || "Processing...") +
      "</div>" +
      "<div style='display:flex; align-items:center; gap:8px;'>" +
      "<progress value='" +
      pct +
      "' max='100' style='width:100%; height:6px;'></progress>" +
      "<span style='font-size:11px; font-weight:700; width:36px; text-align:right;'>" +
      pct +
      "%</span>" +
      "</div>";

    jobEvents.appendChild(div);
    jobEvents.scrollTop = jobEvents.scrollHeight;
  }

  function appendChatMsg(text, role) {
    var log = document.getElementById("chatLog");
    if (!log) return;
    var div = document.createElement("div");
    div.className = "msg " + (role || "system");
    div.textContent = text;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }

  var _socket = null;
  var _reconnectTimer = null;
  var _reconnectAttempt = 0;
  var _maxReconnectDelayMs = 10000;
  var _lastStatusText = "";
  var _lastProgressToken = "";
  var _lastToastToken = "";
  var _jobsRefreshTimer = null;
  var _observerBound = false;

  function _results() {
    return window.QCVizResults;
  }

  function _viewer() {
    return window.QCVizViewer;
  }

  function _el(id) {
    return document.getElementById(id);
  }

  function _escapeHtml(value) {
    return String(value === undefined || value === null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function _buildWsUrl() {
    var protocol = window.location.protocol === "https:" ? "wss://" : "ws://";
    return protocol + window.location.host + "/ws/chat";
  }

  function _fetchJson(url, options) {
    return fetch(url, options || {}).then(function (resp) {
      if (!resp.ok) {
        return resp.text().then(function (text) {
          throw new Error(text || "HTTP " + resp.status);
        });
      }
      return resp.json();
    });
  }

  function _readValue(id, fallback) {
    var node = _el(id);
    if (!node) {
      return fallback;
    }
    return node.value;
  }

  function _readInt(id, fallback) {
    var raw = _readValue(id, fallback);
    var val = parseInt(raw, 10);
    return isNaN(val) ? fallback : val;
  }

  function _isTypingContext(target) {
    if (!target) return false;
    var tag = (target.tagName || "").toLowerCase();
    return (
      tag === "input" ||
      tag === "textarea" ||
      tag === "select" ||
      target.isContentEditable
    );
  }

  function _injectRuntimeStyles() {
    if (_el("qcvizChatRuntimeStyles")) {
      return;
    }

    var style = document.createElement("style");
    style.id = "qcvizChatRuntimeStyles";
    style.textContent = [
      ".qcviz-toast-root {",
      "  position: fixed;",
      "  right: 18px;",
      "  bottom: 18px;",
      "  z-index: 3000;",
      "  display: flex;",
      "  flex-direction: column;",
      "  gap: 10px;",
      "  align-items: flex-end;",
      "  pointer-events: none;",
      "}",
      ".qcviz-toast {",
      "  min-width: 240px;",
      "  max-width: min(420px, calc(100vw - 32px));",
      "  padding: 12px 14px;",
      "  border-radius: 14px;",
      "  color: #ffffff;",
      "  font-size: 13px;",
      "  font-weight: 700;",
      "  line-height: 1.45;",
      "  box-shadow: 0 16px 36px rgba(15,23,42,0.22);",
      "  transform: translateY(8px);",
      "  opacity: 0;",
      "  transition: transform 0.18s ease, opacity 0.18s ease;",
      "  backdrop-filter: blur(8px);",
      "}",
      ".qcviz-toast.show {",
      "  transform: translateY(0);",
      "  opacity: 1;",
      "}",
      ".qcviz-toast.info { background: rgba(30, 64, 175, 0.94); }",
      ".qcviz-toast.success { background: rgba(22, 101, 52, 0.94); }",
      ".qcviz-toast.warn { background: rgba(146, 64, 14, 0.95); }",
      ".qcviz-toast.error { background: rgba(153, 27, 27, 0.95); }",
      ".qcviz-toast-title {",
      "  font-size: 11px;",
      "  font-weight: 800;",
      "  letter-spacing: 0.08em;",
      "  text-transform: uppercase;",
      "  opacity: 0.82;",
      "  margin-bottom: 4px;",
      "}",
      ".qcviz-tab-pulse {",
      "  animation: qcviz-tab-pulse 0.45s ease;",
      "}",
      "@keyframes qcviz-tab-pulse {",
      "  0% { transform: scale(1); }",
      "  35% { transform: scale(1.06); }",
      "  100% { transform: scale(1); }",
      "}",
      ".qcviz-result-fade {",
      "  animation: qcviz-result-fade 0.28s ease;",
      "}",
      "@keyframes qcviz-result-fade {",
      "  from { opacity: 0.45; transform: translateY(4px); }",
      "  to { opacity: 1; transform: translateY(0); }",
      "}",
      ".qcviz-send-busy {",
      "  opacity: 0.72;",
      "  cursor: wait !important;",
      "}",
    ].join("\n");
    document.head.appendChild(style);
  }

  function _ensureToastRoot() {
    _injectRuntimeStyles();

    var root = _el("qcvizToastRoot");
    if (root) {
      return root;
    }

    root = document.createElement("div");
    root.id = "qcvizToastRoot";
    root.className = "qcviz-toast-root";
    document.body.appendChild(root);
    return root;
  }

  function _toast(message, kind, title, timeoutMs) {
    var text = String(message || "").trim();
    if (!text) return;

    var token = [kind || "info", title || "", text].join("::");
    if (_lastToastToken === token) {
      // suppress immediate duplicates
      return;
    }
    _lastToastToken = token;
    window.setTimeout(function () {
      if (_lastToastToken === token) {
        _lastToastToken = "";
      }
    }, 800);

    var root = _ensureToastRoot();
    var node = document.createElement("div");
    node.className = "toast";
    node.setAttribute("data-tone", kind || "info");
    node.innerHTML =
      (title
        ? '<div class="qcviz-toast-title">' + _escapeHtml(title) + "</div>"
        : "") +
      "<div>" +
      _escapeHtml(text) +
      "</div>";

    root.appendChild(node);

    requestAnimationFrame(function () {
      /* Handled by animation now */
    });

    window.setTimeout(function () {
      node.classList.add("is-leaving");
      window.setTimeout(function () {
        if (node.parentNode) {
          node.parentNode.removeChild(node);
        }
      }, 180);
    }, timeoutMs || 2200);
  }

  function _animateTabTransition(tabName) {
    var content = _el("resultContent");
    var tabs = document.querySelectorAll(".result-tab");
    tabs.forEach(function (btn) {
      if (btn.getAttribute("data-tab") === String(tabName || "")) {
        btn.classList.remove("qcviz-tab-pulse");
        // restart animation
        void btn.offsetWidth;
        btn.classList.add("qcviz-tab-pulse");
      }
    });

    if (content) {
      content.classList.remove("qcviz-result-fade");
      void content.offsetWidth;
      content.classList.add("qcviz-result-fade");
    }
  }

  function _setSendBusy(isBusy) {
    var sendBtn = _el("btnSend");
    var quickSend = _el("btnQuickSend");

    [sendBtn, quickSend].forEach(function (btn) {
      if (!btn) return;
      if (isBusy) {
        btn.classList.add("qcviz-send-busy");
        btn.setAttribute("aria-busy", "true");
      } else {
        btn.classList.remove("qcviz-send-busy");
        btn.removeAttribute("aria-busy");
      }
    });
  }

  function _scheduleJobsRefresh(delayMs) {
    window.clearTimeout(_jobsRefreshTimer);
    _jobsRefreshTimer = window.setTimeout(function () {
      fetchJobs();
    }, delayMs || 120);
  }

  function _announceSystemMessage(text) {
    var results = _results();
    if (results && typeof results.addMessage === "function") {
      appendChatMsg(text, "system");
    }
  }

  function _setStatus(text, options) {
    var results = _results();
    var normalized = String(text || "").trim();
    if (!normalized) return;

    if (normalized === _lastStatusText && !(options && options.force)) {
      return;
    }
    _lastStatusText = normalized;

    if (results && typeof results.setStatus === "function") {
      results.setStatus(normalized);
    }

    if (options && options.toast) {
      _toast(
        normalized,
        options.kind || "info",
        options.title || "STATUS",
        options.timeoutMs,
      );
    }

    if (options && options.chat) {
      _announceSystemMessage(normalized);
    }
  }

  function _patchCopyFeedbackObserver() {
    if (_observerBound) return;
    _observerBound = true;

    var chatLog = _el("chatLog");
    if (!chatLog || !window.MutationObserver) {
      return;
    }

    var observer = new MutationObserver(function (mutations) {
      mutations.forEach(function (mutation) {
        Array.prototype.forEach.call(
          mutation.addedNodes || [],
          function (node) {
            if (!node || node.nodeType !== 1) return;
            if (!node.classList || !node.classList.contains("msg")) return;

            var text = (node.textContent || "").trim();
            if (!text) return;

            if (text.indexOf("복사 완료:") === 0) {
              _toast(text, "success", "COPIED", 1800);
            } else if (text.indexOf("작업이 제출되었습니다:") === 0) {
              _toast(text, "info", "JOB", 1800);
            } else if (text.indexOf("작업 취소를 요청했습니다:") === 0) {
              _toast(text, "warn", "CANCEL", 2200);
            }
          },
        );
      });
    });

    observer.observe(chatLog, { childList: true });
  }

  function fetchJobs() {
    var results = _results();
    return _fetchJson("/api/compute/jobs")
      .then(function (payload) {
        if (results && typeof results.renderJobs === "function") {
          results.renderJobs(payload.jobs || []);
        }
        return payload;
      })
      .catch(function (err) {
        if (results && typeof results.renderError === "function") {
          results.renderError("작업 목록 조회 실패: " + err.message);
        }
        _toast("작업 목록 조회 실패", "error", "JOBS");
      });
  }

  function cancelCurrentJob() {
    var results = _results();
    var jobId =
      results && typeof results.getCurrentJobId === "function"
        ? results.getCurrentJobId()
        : null;

    if (!jobId) {
      if (results && typeof results.renderError === "function") {
        results.renderError("취소할 현재 작업이 없습니다.");
      }
      _toast("취소할 현재 작업이 없습니다.", "warn", "CANCEL");
      return;
    }

    _fetchJson("/api/compute/jobs/" + encodeURIComponent(jobId) + "/cancel", {
      method: "POST",
    })
      .then(function () {
        if (results && typeof results.addMessage === "function") {
          appendChatMsg("작업 취소를 요청했습니다: " + jobId, "system");
        }
        _setStatus("작업 취소 요청 전송됨", {
          toast: true,
          kind: "warn",
          title: "CANCEL",
        });
        _scheduleJobsRefresh(80);
      })
      .catch(function (err) {
        if (results && typeof results.renderError === "function") {
          results.renderError("작업 취소 실패: " + err.message);
        }
        _toast("작업 취소 실패", "error", "CANCEL");
      });
  }

  function _announceFocusedTab(tabName) {
    var results = _results();
    if (!results || !tabName) {
      return;
    }

    if (tabName === "methods") {
      appendChatMsg(
        "advisor Methods 결과가 준비되었습니다. Methods 탭으로 이동했습니다.",
        "system",
      );
      _toast("Methods 결과가 준비되었습니다.", "success", "ADVISOR");
    } else if (tabName === "script") {
      appendChatMsg(
        "advisor Script 결과가 준비되었습니다. Script 탭으로 이동했습니다.",
        "system",
      );
      _toast("Script 결과가 준비되었습니다.", "success", "ADVISOR");
    } else if (tabName === "literature") {
      appendChatMsg(
        "advisor Literature 결과가 준비되었습니다. Literature 탭으로 이동했습니다.",
        "system",
      );
      _toast("Literature 결과가 준비되었습니다.", "success", "ADVISOR");
    } else if (tabName === "confidence") {
      appendChatMsg(
        "advisor Confidence 결과가 준비되었습니다. Confidence 탭으로 이동했습니다.",
        "system",
      );
      _toast("Confidence 결과가 준비되었습니다.", "success", "ADVISOR");
    }
  }

  function _autoFocusAdvisorTab(data) {
    var results = _results();
    if (!results) {
      return;
    }

    var chosen = null;

    if (data && data.advisor_focus_tab) {
      if (typeof results.setActiveTab === "function") {
        results.setActiveTab(data.advisor_focus_tab);
      }
      chosen = data.advisor_focus_tab;
    } else if (typeof results.selectBestTabForResult === "function") {
      chosen = results.selectBestTabForResult(data);
    }

    if (chosen) {
      _animateTabTransition(chosen);
      _announceFocusedTab(chosen);
    }
  }

  function _handleStatusPayload(payload) {
    var text = payload.text || payload.message || "작업 중";
    _setStatus(text);

    var results = _results();
    if (
      results &&
      payload.job_id &&
      typeof results.setCurrentJobId === "function"
    ) {
      results.setCurrentJobId(payload.job_id);
    }

    if (
      payload.advisor_plan &&
      payload.advisor_plan.warnings &&
      payload.advisor_plan.warnings.length
    ) {
      _announceSystemMessage(
        "advisor plan warnings: " + payload.advisor_plan.warnings.join(" / "),
      );
    }
  }

  function _handleProgressPayload(payload) {
    var results = _results();
    if (!results) return;

    var token = [
      payload.job_id || "",
      payload.status || "",
      payload.progress || 0,
      payload.step || "",
      payload.detail || "",
    ].join("::");

    if (token === _lastProgressToken) {
      return;
    }
    _lastProgressToken = token;

    if (payload.job_id && typeof results.setCurrentJobId === "function") {
      results.setCurrentJobId(payload.job_id);
    }

    if (typeof results.setStatus === "function") {
      results.setStatus(
        (payload.label || "작업") + " - " + (payload.status || "running"),
      );
    }
    _renderJobProgress(
      payload.progress || 0,
      payload.detail || "진행 중...",
      payload.step || "Running",
    );
  }

  function _handleErrorPayload(payload) {
    var results = _results();
    var msg = payload.error || payload.message || "오류가 발생했습니다.";

    if (results) {
      if (typeof results.renderError === "function") results.renderError(msg);
      if (typeof results.setProgress === "function") {
        results.setProgress(0, "실패");
      }
    }

    _setSendBusy(false);
    _toast(msg, "error", "ERROR", 2600);
    _scheduleJobsRefresh(100);
  }

  function _handleResultPayload(payload) {
    var resultsObj = _results();
    var viewerObj = _viewer();
    var data = payload.data || payload.result || {};

    if (!data.job_id && payload.job_id) {
      data.job_id = payload.job_id;
    }

    if (viewerObj && data.xyz && typeof viewerObj.renderXYZ === "function") {
      try {
        viewerObj.renderXYZ(data.xyz);
      } catch (err) {
        _toast("3D viewer rendering failed", "error", "VIEWER");
      }
    }

    if (resultsObj) {
      if (data.job_id && typeof resultsObj.setCurrentJobId === "function") {
        resultsObj.setCurrentJobId(data.job_id);
      }
      if (typeof resultsObj.renderResult === "function") {
        resultsObj.renderResult(data);
      }
      if (typeof resultsObj.setStatus === "function") {
        resultsObj.setStatus("완료");
      }
      if (typeof resultsObj.setProgress === "function") {
        resultsObj.setProgress(100, "작업 완료");
      }
    }

    _setSendBusy(false);
    _toast("계산 결과가 도착했습니다.", "success", "RESULT");
    _autoFocusAdvisorTab(data);
    _scheduleJobsRefresh(140);
  }

  function _nextReconnectDelay() {
    var base = Math.min(
      _maxReconnectDelayMs,
      1200 * Math.pow(1.6, _reconnectAttempt),
    );
    return Math.round(base);
  }

  function _connect() {
    var results = _results();

    if (
      _socket &&
      (_socket.readyState === WebSocket.OPEN ||
        _socket.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    window.clearTimeout(_reconnectTimer);
    _setStatus(_reconnectAttempt > 0 ? "재연결 시도 중..." : "연결 중...");

    try {
      _socket = new WebSocket(_buildWsUrl());
    } catch (err) {
      _toast("WebSocket 초기화 실패", "error", "CONNECTION");
      _scheduleReconnect();
      return;
    }

    _socket.onopen = function () {
      _reconnectAttempt = 0;
      _lastStatusText = "";
      _setStatus("연결됨", {
        toast: true,
        kind: "success",
        title: "CONNECTED",
        timeoutMs: 1600,
      });
      _scheduleJobsRefresh(120);

      if (results && typeof results.addMessage === "function") {
        appendChatMsg("QCViz WebSocket session connected.", "system");
      }
    };

    _socket.onclose = function () {
      _setSendBusy(false);
      _setStatus("연결 종료. 재연결 중...");
      _toast(
        "서버 연결이 종료되었습니다. 자동 재연결을 시도합니다.",
        "warn",
        "DISCONNECTED",
        2400,
      );
      _scheduleReconnect();
    };

    _socket.onerror = function () {
      _setStatus("소켓 오류");
      _toast("통신 오류가 감지되었습니다.", "error", "SOCKET", 2200);
    };

    _socket.onmessage = function (evt) {
      var payload = null;

      try {
        payload = JSON.parse(evt.data);
      } catch (err) {
        var resultsObj = _results();
        if (resultsObj) {
          resultsObj.renderError("서버 응답을 JSON으로 해석하지 못했습니다.");
        }
        _toast("서버 응답 파싱 실패", "error", "PARSE");
        return;
      }

      if (!payload || !payload.type) {
        return;
      }

      if (payload.type === "chat") {
        var resultsChat = _results();
        if (resultsChat && typeof resultsChat.addMessage === "function") {
          resultsChat.addMessage(payload.message || payload.text || "", "bot");
        }
        return;
      }

      if (payload.type === "status") {
        _handleStatusPayload(payload);
        return;
      }

      if (payload.type === "job_submitted") {
        var resultsSubmitted = _results();
        if (
          resultsSubmitted &&
          payload.job_id &&
          typeof resultsSubmitted.setCurrentJobId === "function"
        ) {
          resultsSubmitted.setCurrentJobId(payload.job_id);
          resultsSubmitted.addMessage(
            "작업이 제출되었습니다: " + payload.job_id,
            "system",
          );
        }
        _setStatus("작업 제출 완료");
        _toast("백그라운드 작업이 제출되었습니다.", "info", "JOB");
        _setSendBusy(true);
        _scheduleJobsRefresh(80);
        return;
      }

      if (payload.type === "progress") {
        _handleProgressPayload(payload);
        return;
      }

      if (payload.type === "job_event") {
        var resultsEvents = _results();
        if (
          resultsEvents &&
          typeof resultsEvents.appendJobEvent === "function"
        ) {
          resultsEvents.appendJobEvent(payload);
        }
        return;
      }

      if (payload.type === "error") {
        _handleErrorPayload(payload);
        return;
      }

      if (payload.type === "result") {
        _handleResultPayload(payload);
      }
    };
  }

  function _scheduleReconnect() {
    _reconnectAttempt += 1;
    var delay = _nextReconnectDelay();
    window.clearTimeout(_reconnectTimer);
    _reconnectTimer = window.setTimeout(function () {
      _connect();
    }, delay);
  }

  function _sendCurrentMessage() {
    var input = _el("chatInput");
    var results = _results();

    if (!input) {
      return;
    }

    var text = (input.value || "").trim();
    if (!text) {
      _toast("메시지를 입력해 주세요.", "warn", "INPUT");
      return;
    }

    if (!_socket || _socket.readyState !== WebSocket.OPEN) {
      if (results && typeof results.renderError === "function") {
        results.renderError("서버와 연결되어 있지 않습니다.");
      }
      _toast("서버와 연결되어 있지 않습니다.", "error", "CONNECTION");
      return;
    }

    var payload = {
      type: "chat",
      text: text,
      message: text,
      charge: _readInt("chargeInput", 0),
      spin: _readInt("spinInput", 0),
      method: _readValue("methodInput", "") || "",
      basis: _readValue("basisInput", "") || "",
      intent: _readValue("intentInput", "") || "",
      include_advisor: true,
    };

    if (results) {
      appendChatMsg(text, "user");

      var jobEvents = _el("jobEvents");
      if (jobEvents) jobEvents.innerHTML = ""; // Clear log on new request

      _renderJobProgress(0, "작업 제출 준비 중...", "Initializing");
    }

    _setSendBusy(true);
    _socket.send(JSON.stringify(payload));
    input.value = "";
    input.dispatchEvent(new Event("input"));
    _toast("요청이 전송되었습니다.", "info", "REQUEST", 1200);
  }

  function _bindUi() {
    var sendBtn = _el("btnSend");
    var input = _el("chatInput");
    var refreshBtn = _el("btnRefreshJobs");
    var refreshTopBtn = _el("btnRefreshJobsTop");
    var cancelBtn = _el("btnCancelJob");
    var quickSendBtn = _el("btnQuickSend");
    var clearChatBtn = _el("btnClearChat");

    if (clearChatBtn) {
      clearChatBtn.addEventListener("click", function () {
        var log = _el("chatLog");
        if (log) log.innerHTML = "";
      });
    }

    document.addEventListener("click", function (evt) {
      var chip = evt.target.closest(".quick-chip");
      if (chip && chip.dataset.prompt) {
        var input = _el("chatInput");
        if (input) {
          input.value = chip.dataset.prompt;
          _sendCurrentMessage();
        }
      }
    });

    if (sendBtn) {
      sendBtn.addEventListener("click", function () {
        _sendCurrentMessage();
      });
    }

    if (quickSendBtn) {
      quickSendBtn.addEventListener("click", function () {
        _sendCurrentMessage();
      });
    }

    if (input) {
      input.addEventListener("keydown", function (evt) {
        if (evt.key === "Enter" && !evt.shiftKey) {
          evt.preventDefault();
          _sendCurrentMessage();
        }
      });
    }

    document.addEventListener("keydown", function (evt) {
      if (_isTypingContext(evt.target)) return;
      if ((evt.ctrlKey || evt.metaKey) && evt.key === "Enter") {
        evt.preventDefault();
        _sendCurrentMessage();
      }
    });

    if (refreshBtn) {
      refreshBtn.addEventListener("click", function () {
        fetchJobs();
        _toast("작업 목록을 새로고침했습니다.", "info", "JOBS", 1200);
      });
    }

    if (refreshTopBtn) {
      refreshTopBtn.addEventListener("click", function () {
        fetchJobs();
        _toast("작업 목록을 새로고침했습니다.", "info", "JOBS", 1200);
      });
    }

    if (cancelBtn) {
      cancelBtn.addEventListener("click", function () {
        cancelCurrentJob();
      });
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    _injectRuntimeStyles();
    _ensureToastRoot();
    _bindUi();
    _patchCopyFeedbackObserver();
    _connect();
  });

  window.QCVizChat = {
    connect: _connect,
    sendCurrentMessage: _sendCurrentMessage,
    fetchJobs: fetchJobs,
    cancelCurrentJob: cancelCurrentJob,
    toast: _toast,
  };
})();
```

## [index.html]

경로: `version02/src/qcviz_mcp/web/static/index.html`

```html
<!DOCTYPE html>
<html lang="ko">
  <head>
    <meta charset="utf-8" />
    <meta
      name="viewport"
      content="width=device-width, initial-scale=1, viewport-fit=cover"
    />
    <meta
      name="description"
      content="QCViz-MCP Enterprise Web — AI-assisted quantum chemistry workspace with 3D molecular visualization, advisor automation, and reproducible compute workflows."
    />
    <meta name="theme-color" content="#0f172a" />
    <title>QCViz-MCP Enterprise Web</title>

    <!-- 3Dmol.js -->
    <script src="https://3Dmol.org/build/3Dmol-min.js"></script>

    <!-- App stylesheet -->
    <link rel="stylesheet" href="/static/style.css" />

    <!-- Fonts -->
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap"
      rel="stylesheet"
    />
    <link
      href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap"
      rel="stylesheet"
    />

    <!-- Icons -->
    <link
      rel="stylesheet"
      href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@latest/tabler-icons.min.css"
    />

    <style>
      :root {
        color-scheme: light;
      }
    </style>
  </head>

  <body>
    <a class="skip-link" href="#mainContent">본문으로 건너뛰기</a>

    <div class="app-shell-enterprise">
      <header class="enterprise-header" aria-label="Application header">
        <div class="enterprise-header-inner">
          <div class="brand-block">
            <div class="brand-mark" aria-hidden="true">Q</div>
            <div class="brand-copy">
              <div class="brand-title-row">
                <div class="brand-title">QCViz-MCP Enterprise Web</div>
                <span class="brand-badge">PREVIEW</span>
              </div>
              <div class="brand-subtitle">
                Quantum Chemistry Intelligence Workspace
              </div>
            </div>
          </div>

          <div class="header-actions">
            <button class="header-action" type="button" id="btnExportCSV">
              <i class="ti ti-table-export"></i>
              <span>Export Data</span>
            </button>
            <button
              class="header-action primary"
              type="button"
              id="btnNewSession"
            >
              <i class="ti ti-plus"></i>
              <span>New Session</span>
            </button>
          </div>
        </div>
      </header>

      <main class="enterprise-main" id="mainContent">
        <div class="enterprise-grid">
          <!-- Left Column: Chat & Session -->
          <div class="enterprise-column">
            <section class="enterprise-card chat-card">
              <div class="enterprise-card-header">
                <div>
                  <h2 class="enterprise-card-title">Compute Advisor</h2>
                  <p class="enterprise-card-subtitle">
                    AI-assisted simulation guidance
                  </p>
                </div>
                <button
                  class="btn-ghost"
                  type="button"
                  id="btnClearChat"
                  title="Clear History"
                >
                  <i class="ti ti-trash"></i>
                </button>
              </div>

              <div class="enterprise-card-body chat-body">
                <div class="chat-log-shell" id="chatLog">
                  <!-- Messages injected by chat.js -->
                  <div class="msg bot">
                    안녕하세요! 분석하고 싶은 분자 이름이나 SMILES, 또는 좌표
                    데이터를 입력해 주세요. IBO 오비탈 분석이나 ESP 맵 생성도
                    가능합니다.
                  </div>
                </div>

                <div class="chat-composer">
                  <div class="quick-chips">
                    <button class="quick-chip" data-prompt="Water IBO orbitals">
                      <span class="quick-chip-title">Water IBO</span>
                      <span class="quick-chip-desc">오비탈 분석</span>
                    </button>
                    <button
                      class="quick-chip"
                      data-prompt="Caffeine geometry optimization"
                    >
                      <span class="quick-chip-title">Caffeine</span>
                      <span class="quick-chip-desc">구조 최적화</span>
                    </button>
                  </div>

                  <div class="composer-box">
                    <textarea
                      class="composer-textarea"
                      id="chatInput"
                      placeholder="분자 이름을 입력하거나 궁금한 점을 물어보세요..."
                      rows="1"
                    ></textarea>
                    <button
                      class="composer-submit"
                      id="btnSend"
                      title="Send (Enter)"
                    >
                      <i class="ti ti-send"></i>
                    </button>
                  </div>
                </div>
              </div>
            </section>

            <section class="enterprise-card jobs-card">
              <div class="enterprise-card-header">
                <h2 class="enterprise-card-title">Live Job Monitor</h2>
              </div>
              <div class="enterprise-card-body">
                <div class="job-events-shell" id="jobEvents">
                  <div class="empty-state">No active jobs</div>
                </div>
              </div>
            </section>
          </div>

          <!-- Right Column: Visualization & Results -->
          <div class="enterprise-column">
            <section class="enterprise-card viewer-card">
              <div class="enterprise-card-header">
                <div>
                  <h2 class="enterprise-card-title">3D Molecular Stage</h2>
                  <p class="enterprise-card-subtitle" id="viewer-meta">Ready</p>
                </div>
                <div class="viewer-actions">
                  <select class="viewer-style-select" id="viewerStyleSelect">
                    <option value="ballstick">Ball & Stick</option>
                    <option value="stick">Stick Only</option>
                    <option value="sphere">Space Fill</option>
                    <option value="wireframe">Wireframe</option>
                  </select>
                  <button
                    class="viewer-btn"
                    id="btnViewerReset"
                    title="Reset View"
                  >
                    <i class="ti ti-refresh"></i>
                  </button>
                  <button
                    class="viewer-btn"
                    id="btnScreenshot"
                    title="Capture PNG"
                  >
                    <i class="ti ti-camera"></i>
                  </button>
                </div>
              </div>
              <div class="viewer-stage-shell" id="viewerContainer">
                <div class="viewer-toolbar">
                  <div class="toolbar-group">
                    <button
                      id="btn-style-ballstick"
                      class="btn btn-secondary is-active"
                      type="button"
                    >
                      Ball+Stick
                    </button>
                    <button
                      id="btn-style-stick"
                      class="btn btn-secondary"
                      type="button"
                    >
                      Stick
                    </button>
                    <button
                      id="btn-style-sphere"
                      class="btn btn-secondary"
                      type="button"
                    >
                      Sphere
                    </button>
                  </div>

                  <div id="orbital-controls" class="toolbar-group" hidden>
                    <span class="toolbar-label">Orbital</span>

                    <label class="control-inline" for="orb-iso-slider">
                      <span>Iso</span>
                      <input
                        id="orb-iso-slider"
                        type="range"
                        min="0.005"
                        max="0.100"
                        step="0.001"
                        value="0.020"
                      />
                      <span id="orb-iso-value" class="control-value"
                        >0.020</span
                      >
                    </label>

                    <label class="control-inline" for="orb-opa-slider">
                      <span>Opacity</span>
                      <input
                        id="orb-opa-slider"
                        type="range"
                        min="0.10"
                        max="1.00"
                        step="0.01"
                        value="0.78"
                      />
                      <span id="orb-opa-value" class="control-value">0.78</span>
                    </label>

                    <button
                      id="btn-orb-render"
                      class="btn btn-primary"
                      type="button"
                    >
                      Render Orbital
                    </button>
                    <button
                      id="btn-orb-clear"
                      class="btn btn-secondary"
                      type="button"
                    >
                      Clear Orbital
                    </button>
                  </div>

                  <div id="esp-controls" class="toolbar-group" hidden>
                    <span class="toolbar-label">ESP</span>

                    <label class="control-inline" for="sel-esp">
                      <span>Preset</span>
                      <select id="sel-esp">
                        <option value="rwb">Red-White-Blue</option>
                        <option value="viridis">Viridis</option>
                        <option value="inferno">Inferno</option>
                        <option value="spectral">Spectral</option>
                        <option value="nature">Nature</option>
                        <option value="acs">ACS</option>
                        <option value="rsc">RSC</option>
                        <option value="matdark">Material Dark</option>
                        <option value="grey">Greyscale</option>
                        <option value="hicon">High Contrast</option>
                      </select>
                    </label>

                    <label class="control-inline" for="esp-iso-slider">
                      <span>Iso</span>
                      <input
                        id="esp-iso-slider"
                        type="range"
                        min="0.005"
                        max="0.120"
                        step="0.001"
                        value="0.030"
                      />
                      <span id="esp-iso-value" class="control-value"
                        >0.030</span
                      >
                    </label>

                    <label class="control-inline" for="esp-opa-slider">
                      <span>Opacity</span>
                      <input
                        id="esp-opa-slider"
                        type="range"
                        min="0.10"
                        max="1.00"
                        step="0.01"
                        value="0.72"
                      />
                      <span id="esp-opa-value" class="control-value">0.72</span>
                    </label>

                    <label class="control-inline" for="esp-range-slider">
                      <span>Range</span>
                      <input
                        id="esp-range-slider"
                        type="range"
                        min="0.005"
                        max="0.200"
                        step="0.001"
                        value="0.050"
                      />
                      <span id="esp-range-value" class="control-value"
                        >0.050</span
                      >
                    </label>

                    <button id="btn-esp" class="btn btn-primary" type="button">
                      Toggle ESP
                    </button>
                    <button
                      id="btn-esp-render"
                      class="btn btn-primary"
                      type="button"
                    >
                      Render ESP
                    </button>
                    <button
                      id="btn-esp-clear"
                      class="btn btn-secondary"
                      type="button"
                    >
                      Clear ESP
                    </button>
                  </div>

                  <div class="toolbar-group toolbar-group-right">
                    <button
                      id="btn-labels"
                      class="btn btn-secondary"
                      type="button"
                    >
                      Labels
                    </button>
                    <button
                      id="btn-charges"
                      class="btn btn-secondary"
                      type="button"
                    >
                      Charges
                    </button>
                    <button
                      id="btn-screenshot"
                      class="btn btn-secondary"
                      type="button"
                    >
                      Screenshot
                    </button>
                    <button
                      id="btn-reset"
                      class="btn btn-secondary"
                      type="button"
                    >
                      Reset
                    </button>
                  </div>
                </div>

                <div id="viz-status" class="viz-status" aria-live="polite">
                  Ready.
                </div>
                <div
                  id="v3d"
                  style="width: 100%; height: 100%; position: relative;"
                ></div>
              </div>
            </section>

            <section class="enterprise-card results-card">
              <div class="enterprise-card-header">
                <nav class="result-tabs" role="tablist">
                  <button class="result-tab active" data-tab="summary">
                    Summary
                  </button>
                  <button class="result-tab" data-tab="geometry">
                    Geometry
                  </button>
                  <button class="result-tab" data-tab="orbitals">
                    Orbitals
                  </button>
                  <button class="result-tab" data-tab="esp">ESP</button>
                  <button class="result-tab" data-tab="charges">Charges</button>
                  <button class="result-tab" data-tab="advisor">Advisor</button>
                </nav>
              </div>
              <div
                class="enterprise-card-body results-content-shell"
                id="results-console"
              >
                <div id="result-tabs" class="result-tabs"></div>
                <div id="result-content" class="result-content"></div>
              </div>
            </section>
          </div>
        </div>
      </main>
    </div>

    <!-- Toast Container -->
    <div id="qcviz-toast-root" class="qcviz-toast-root"></div>

    <!-- App Scripts -->
    <script src="/static/viewer.js"></script>
    <script src="/static/results.js"></script>
    <script src="/static/chat.js"></script>

    <script>
      (function () {
        "use strict";
        window.addEventListener("DOMContentLoaded", function () {
          // Initialize app if needed
          console.log("QCViz Enterprise Web initialized.");
        });
      })();
    </script>
  </body>
</html>
```

## [style.css]

경로: `version02/src/qcviz_mcp/web/static/style.css`

```css
/* ─────────────────────────────────────────────
   QCViz Enterprise Web — style.css
   Scientific SaaS + Minimal Enterprise Dashboard
   CSS-only redesign for existing HTML/JS
   ───────────────────────────────────────────── */

/* ── Design Tokens ─────────────────────────── */
:root {
  /* ── 배경 계층 (Surface Hierarchy) ── */
  --bg-app: #f1f5fb;
  --bg-app-gradient:
    radial-gradient(
      ellipse at top left,
      rgba(79, 70, 229, 0.07),
      transparent 40%
    ),
    radial-gradient(
      ellipse at bottom right,
      rgba(2, 132, 199, 0.05),
      transparent 35%
    ),
    linear-gradient(180deg, #f8fbff 0%, #f1f5fb 100%);
  --surface-0: rgba(255, 255, 255, 0.85);
  --surface-1: #ffffff;
  --surface-2: #f8fbff;
  --surface-3: linear-gradient(180deg, #f0f4ff 0%, #e8eeff 100%);

  /* ── 텍스트 ── */
  --text-primary: #0f172a;
  --text-secondary: #475569;
  --text-muted: #94a3b8;
  --text-on-brand: #ffffff;

  /* ── 브랜드 (Indigo 계열) ── */
  --brand: #4f46e5;
  --brand-hover: #4338ca;
  --brand-strong: #3730a3;
  --brand-muted: #e0e7ff;
  --brand-subtle: #eef2ff;

  /* ── 보조 액센트 (Cyan/Sky) ── */
  --accent: #0284c7;
  --accent-hover: #0369a1;
  --accent-muted: #e0f2fe;
  --accent-subtle: #f0f9ff;

  /* ── 상태색 (Status) ── */
  --success: #16a34a;
  --success-bg: #f0fdf4;
  --success-border: #bbf7d0;
  --warning: #d97706;
  --warning-bg: #fffbeb;
  --warning-border: #fde68a;
  --danger: #dc2626;
  --danger-bg: #fef2f2;
  --danger-border: #fecaca;
  --info: #0284c7;
  --info-bg: #f0f9ff;
  --info-border: #bae6fd;

  /* ── 보더 & 구분선 ── */
  --border: #dbe4f0;
  --border-strong: #c7d2fe;
  --border-subtle: #e8edf5;
  --divider: rgba(148, 163, 184, 0.18);

  /* ── 그림자 ── */
  --shadow-xs: 0 1px 2px rgba(15, 23, 42, 0.04);
  --shadow-sm: 0 2px 8px rgba(15, 23, 42, 0.05);
  --shadow-md: 0 8px 24px rgba(15, 23, 42, 0.06);
  --shadow-lg:
    0 18px 40px rgba(15, 23, 42, 0.08), 0 6px 16px rgba(15, 23, 42, 0.04);
  --shadow-brand: 0 4px 14px rgba(79, 70, 229, 0.25);

  /* ── 라운딩 ── */
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
  --radius-xl: 20px;
  --radius-full: 9999px;

  /* ── 트랜지션 ── */
  --ease-out: cubic-bezier(0.2, 0.8, 0.2, 1);
  --duration-fast: 150ms;
  --duration-normal: 220ms;
  --duration-slow: 320ms;

  /* ── 타이포그래피 ── */
  --font-sans:
    "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  --font-size-xs: 11px;
  --font-size-sm: 13px;
  --font-size-base: 14px;
  --font-size-md: 15px;
  --font-size-lg: 18px;
  --font-size-xl: 22px;
  --font-size-2xl: 28px;

  /* ── Supplemental tokens ── */
  --transparent: transparent;
  --focus-ring: rgba(79, 70, 229, 0.15);
  --focus-ring-strong: rgba(79, 70, 229, 0.12);
  --surface-overlay: rgba(255, 255, 255, 0.72);
  --surface-overlay-strong: rgba(248, 251, 255, 0.84);
  --pulse-shadow-success: rgba(22, 163, 74, 0.22);
  --pulse-shadow-brand: rgba(79, 70, 229, 0.18);
  --scrollbar-thumb: #dbe4f0;
  --scrollbar-thumb-hover: #cbd5e1;
  --scrollbar-track: transparent;
  --code-bg: #0f172a;
  --code-border: #334155;
  --code-text: #e2e8f0;
  --code-muted: #94a3b8;
  --code-button-bg: rgba(255, 255, 255, 0.08);
  --code-button-border: rgba(255, 255, 255, 0.14);
  --code-button-hover: rgba(255, 255, 255, 0.16);
  --selection-bg: #e0e7ff;
  --selection-text: #312e81;
}

/* ── Reset / Base ─────────────────────────── */
*,
*::before,
*::after {
  box-sizing: border-box;
}

html {
  font-size: 16px;
  scroll-behavior: smooth;
}

html,
body {
  margin: 0;
  padding: 0;
  min-height: 100%;
  font-family: var(--font-sans);
  background: var(--bg-app-gradient);
  color: var(--text-primary);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

body {
  min-height: 100vh;
}

img,
svg,
canvas {
  display: block;
  max-width: 100%;
}

button,
input,
select,
textarea {
  font: inherit;
  color: inherit;
}

a {
  color: inherit;
  text-decoration: none;
}

::selection {
  background: var(--selection-bg);
  color: var(--selection-text);
}

:focus {
  outline: none;
}

:focus-visible {
  box-shadow: 0 0 0 3px var(--focus-ring);
  border-color: var(--brand);
}

::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-track {
  background: var(--scrollbar-track);
}

::-webkit-scrollbar-thumb {
  background: var(--scrollbar-thumb);
  border-radius: var(--radius-full);
}

::-webkit-scrollbar-thumb:hover {
  background: var(--scrollbar-thumb-hover);
}

hr {
  border: 0;
  border-top: 1px solid var(--divider);
  margin: 16px 0;
}

/* ── Typography ───────────────────────────── */
h1,
h2,
h3,
h4,
h5,
h6 {
  margin: 0;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

p {
  margin: 0;
  color: var(--text-secondary);
}

small,
.text-muted {
  color: var(--text-muted);
}

code,
pre,
.code-block,
.mono,
.result-mono,
.numeric {
  font-family: var(--font-mono);
}

/* ── App Shell / Layout ───────────────────── */
.app-shell,
.workspace,
.layout-container,
.main-area {
  width: 100%;
  min-height: 100vh;
}

.app-shell {
  padding: 18px;
  background: var(--transparent);
}

.workspace,
.layout-container,
.main-area {
  display: flex;
  flex-direction: column;
  gap: 16px;
  background: var(--transparent);
}

.content-row {
  display: grid;
  grid-template-columns: minmax(320px, 360px) minmax(0, 1fr) minmax(
      360px,
      420px
    );
  gap: 16px;
  align-items: stretch;
  min-height: calc(100vh - 120px);
}

.content-row > * {
  min-width: 0;
  min-height: 0;
}

/* ── Panel / Card Primitives ──────────────── */
.panel,
.card,
.chat-shell,
.result-shell,
.viewer-shell {
  background: var(--surface-0);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}

.panel,
.card,
.chat-shell,
.result-shell,
.viewer-shell {
  position: relative;
  overflow: hidden;
}

.chat-shell,
.result-shell,
.viewer-shell {
  display: flex;
  flex-direction: column;
}

.panel,
.card {
  padding: 16px;
}

.panel-title,
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--divider);
  font-size: var(--font-size-sm);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-secondary);
}

.result-card,
.metric-card,
.kpi-card,
.result-section,
.score-card,
.callout {
  background: linear-gradient(
    180deg,
    var(--surface-1) 0%,
    var(--surface-2) 100%
  );
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  padding: 16px 18px;
  transition:
    border-color var(--duration-fast) var(--ease-out),
    box-shadow var(--duration-fast) var(--ease-out),
    transform var(--duration-fast) var(--ease-out);
}

.result-card:hover,
.metric-card:hover,
.kpi-card:hover,
.result-section:hover,
.card:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-md);
}

.result-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--divider);
}

.result-section-head h3,
.result-section-head h4 {
  font-size: var(--font-size-sm);
  font-weight: 700;
  color: var(--text-primary);
}

.result-subtitle,
.section-subtitle,
.result-caption {
  font-size: var(--font-size-xs);
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* ── Generic Grids / Lists ────────────────── */
.kpi-grid,
.metrics-grid,
.result-grid,
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
}

.stack,
.result-stack,
.info-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.pill-row,
.badge-row,
.meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.list,
.warning-list,
.recommendation-list,
.result-list,
.jobs-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0;
  padding-left: 18px;
  color: var(--text-secondary);
}

.list li,
.warning-list li,
.recommendation-list li,
.result-list li {
  color: var(--text-secondary);
}

dl,
.definition-list {
  display: grid;
  grid-template-columns: minmax(0, 140px) minmax(0, 1fr);
  gap: 8px 12px;
  margin: 0;
}

dt {
  color: var(--text-muted);
  font-size: var(--font-size-sm);
}

dd {
  margin: 0;
  color: var(--text-primary);
  font-size: var(--font-size-sm);
  font-family: var(--font-mono);
}

/* ── Status / Badges ──────────────────────── */
.status-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 24px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  background: var(--success);
  box-shadow: 0 0 0 0 var(--pulse-shadow-success);
  animation: qcviz-pulse 2s infinite;
  flex: 0 0 auto;
}

.status-dot.is-info {
  background: var(--info);
  box-shadow: 0 0 0 0 var(--pulse-shadow-brand);
}

.status-dot.is-warning {
  background: var(--warning);
  box-shadow: none;
  animation: none;
}

.status-dot.is-danger {
  background: var(--danger);
  box-shadow: none;
  animation: none;
}

.status-text {
  font-size: var(--font-size-sm);
  font-weight: 500;
  color: var(--text-secondary);
}

.badge,
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 24px;
  padding: 3px 10px;
  border-radius: var(--radius-full);
  font-size: var(--font-size-xs);
  font-weight: 700;
  letter-spacing: 0.02em;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text-secondary);
  white-space: nowrap;
}

.badge::before,
.status-badge::before {
  content: "";
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
  background: currentColor;
  flex: 0 0 auto;
}

.badge-success,
.status-success,
.badge.is-success {
  background: var(--success-bg);
  color: var(--success);
  border-color: var(--success-border);
}

.badge-warning,
.status-warning,
.badge.is-warning {
  background: var(--warning-bg);
  color: var(--warning);
  border-color: var(--warning-border);
}

.badge-danger,
.status-error,
.status-danger,
.badge.is-danger,
.badge.is-error {
  background: var(--danger-bg);
  color: var(--danger);
  border-color: var(--danger-border);
}

.badge-info,
.status-info,
.badge.is-info {
  background: var(--info-bg);
  color: var(--info);
  border-color: var(--info-border);
}

/* ── Buttons ──────────────────────────────── */
.btn,
button,
.copy-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 36px;
  padding: 8px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--surface-1);
  color: var(--text-secondary);
  box-shadow: var(--shadow-xs);
  cursor: pointer;
  transition:
    background var(--duration-fast) var(--ease-out),
    border-color var(--duration-fast) var(--ease-out),
    color var(--duration-fast) var(--ease-out),
    box-shadow var(--duration-fast) var(--ease-out),
    transform var(--duration-fast) var(--ease-out);
}

.btn:hover,
button:hover,
.copy-btn:hover {
  border-color: var(--border-strong);
  color: var(--text-primary);
  box-shadow: var(--shadow-sm);
  transform: translateY(-0.5px);
}

.btn:active,
button:active,
.copy-btn:active {
  transform: translateY(0.5px);
  box-shadow: var(--shadow-xs);
}

.btn:disabled,
button:disabled,
.copy-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none;
  box-shadow: var(--shadow-xs);
}

.btn-primary,
button.btn-primary {
  background: var(--brand);
  border-color: var(--brand);
  color: var(--text-on-brand);
}

.btn-primary:hover,
button.btn-primary:hover {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
  color: var(--text-on-brand);
  box-shadow: var(--shadow-brand);
}

.btn-secondary,
button.btn-secondary {
  background: var(--surface-1);
  border-color: var(--border);
  color: var(--text-secondary);
}

.btn-secondary:hover,
button.btn-secondary:hover {
  border-color: var(--brand-muted);
  color: var(--brand);
}

.btn-ghost,
button.btn-ghost {
  background: var(--transparent);
  border-color: var(--transparent);
  color: var(--text-muted);
  box-shadow: none;
}

.btn-ghost:hover,
button.btn-ghost:hover {
  background: var(--brand-subtle);
  border-color: var(--brand-muted);
  color: var(--brand);
  box-shadow: none;
}

.copy-btn {
  padding: 6px 10px;
  font-size: var(--font-size-xs);
  font-weight: 600;
}

/* ── Inputs / Controls ────────────────────── */
input,
select,
textarea {
  width: 100%;
  border: 1.5px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-1);
  color: var(--text-primary);
  padding: 10px 12px;
  box-shadow: var(--shadow-xs);
  transition:
    border-color var(--duration-fast) var(--ease-out),
    box-shadow var(--duration-fast) var(--ease-out),
    background var(--duration-fast) var(--ease-out);
}

input::placeholder,
textarea::placeholder {
  color: var(--text-muted);
}

input:hover,
select:hover,
textarea:hover {
  border-color: var(--border-strong);
}

input:focus,
select:focus,
textarea:focus {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--focus-ring-strong);
}

textarea {
  min-height: 108px;
  resize: vertical;
}

label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
}

.chat-input,
.composer,
.advanced-controls,
.toolbar,
.control-row,
.form-row,
.field-row {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.control-row,
.form-row,
.field-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.composer .btn,
.chat-input .btn,
.toolbar .btn,
.toolbar button,
.toolbar select {
  min-height: 38px;
}

/* ── Chat Shell ───────────────────────────── */
.chat-shell {
  padding: 16px;
  gap: 14px;
}

.chat-shell .panel-title,
.chat-shell .card-header {
  margin-bottom: 0;
}

.chat-messages {
  flex: 1 1 auto;
  min-height: 320px;
  max-height: calc(100vh - 300px);
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-right: 4px;
}

.chat-messages .message,
.chat-messages .chat-message,
.chat-messages .msg,
.chat-messages [data-role],
.chat-messages .bubble {
  max-width: 92%;
  padding: 12px 14px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-subtle);
  background: var(--surface-2);
  color: var(--text-primary);
  box-shadow: var(--shadow-xs);
  word-break: break-word;
  animation: qcviz-fade-up var(--duration-normal) var(--ease-out);
}

.chat-messages .message.user,
.chat-messages .chat-message.user,
.chat-messages .msg.user,
.chat-messages [data-role="user"],
.chat-messages .bubble.user {
  margin-left: auto;
  background: var(--brand);
  border-color: var(--brand);
  color: var(--text-on-brand);
  border-radius: var(--radius-md) var(--radius-md) 4px var(--radius-md);
  box-shadow: var(--shadow-brand);
}

.chat-messages .message.assistant,
.chat-messages .message.system,
.chat-messages .chat-message.assistant,
.chat-messages .chat-message.system,
.chat-messages .msg.assistant,
.chat-messages .msg.system,
.chat-messages [data-role="assistant"],
.chat-messages [data-role="system"],
.chat-messages .bubble.assistant,
.chat-messages .bubble.system {
  margin-right: auto;
  background: var(--surface-2);
  border-color: var(--border-subtle);
  color: var(--text-primary);
  border-radius: var(--radius-md) var(--radius-md) var(--radius-md) 4px;
}

.chat-messages .message .meta,
.chat-messages .chat-message .meta,
.chat-messages .timestamp {
  margin-top: 6px;
  font-size: var(--font-size-xs);
  color: var(--text-muted);
}

.composer {
  border-top: 1px solid var(--divider);
  padding-top: 12px;
}

/* ── Quick Prompts / Chips ────────────────── */
.quick-prompts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.chip,
.quick-prompt {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  background: var(--surface-1);
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
  font-weight: 500;
  cursor: pointer;
  box-shadow: var(--shadow-xs);
  transition:
    background var(--duration-fast) var(--ease-out),
    border-color var(--duration-fast) var(--ease-out),
    color var(--duration-fast) var(--ease-out),
    box-shadow var(--duration-fast) var(--ease-out),
    transform var(--duration-fast) var(--ease-out);
}

.chip:hover,
.quick-prompt:hover {
  background: var(--brand-subtle);
  border-color: var(--brand-muted);
  color: var(--brand);
  box-shadow: var(--shadow-sm);
  transform: translateY(-1px);
}

.chip:active,
.quick-prompt:active {
  transform: translateY(0.5px);
}

/* ── Viewer ───────────────────────────────── */
.viewer-shell {
  padding: 16px;
  gap: 12px;
}

.viewer-shell .panel-title,
.viewer-shell .card-header {
  margin-bottom: 0;
}

.toolbar {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.viewer-container {
  position: relative;
  flex: 1 1 auto;
  min-height: 560px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--border);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
  background: var(--surface-1);
}

#v3d {
  width: 100%;
  height: 100%;
  min-height: 560px;
  border-radius: inherit;
  background: var(--surface-1);
}

.viewer-container canvas,
#v3d canvas {
  width: 100%;
  height: 100%;
}

.viewer-overlay {
  position: absolute;
  inset: 12px 12px auto 12px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  pointer-events: none;
  z-index: 3;
}

.viewer-overlay > * {
  pointer-events: auto;
}

.viewer-overlay .badge,
.viewer-overlay .status-badge,
.viewer-overlay .panel,
.viewer-overlay .card {
  background: var(--surface-overlay-strong);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}

.viewer-shell .toolbar .btn,
.viewer-shell .toolbar button,
.viewer-shell .toolbar select {
  border-radius: var(--radius-full);
}

/* ── Result Shell ─────────────────────────── */
.result-shell {
  padding: 16px;
  gap: 12px;
}

.result-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: nowrap;
  overflow-x: auto;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--divider);
  scrollbar-width: none;
}

.result-tabs::-webkit-scrollbar {
  display: none;
}

.tab-btn,
.result-tab {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 34px;
  padding: 8px 14px;
  border: 1px solid var(--transparent);
  border-radius: var(--radius-full);
  background: var(--transparent);
  color: var(--text-muted);
  font-size: var(--font-size-sm);
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  box-shadow: none;
  transition:
    background var(--duration-fast) var(--ease-out),
    border-color var(--duration-fast) var(--ease-out),
    color var(--duration-fast) var(--ease-out),
    box-shadow var(--duration-fast) var(--ease-out),
    transform var(--duration-fast) var(--ease-out);
}

.tab-btn:hover,
.result-tab:hover {
  color: var(--text-secondary);
  border-color: var(--border);
  background: var(--surface-1);
}

.tab-btn.active,
.result-tab.active,
.tab-btn[aria-selected="true"],
.result-tab[aria-selected="true"] {
  background: var(--surface-3);
  color: var(--brand-strong);
  border-color: var(--border-strong);
  box-shadow: inset 0 0 0 1px var(--focus-ring-strong);
  font-weight: 600;
}

.result-content {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-right: 4px;
}

.result-content > * + * {
  margin-top: 12px;
}

.result-content h2,
.result-content h3,
.result-content h4 {
  margin-bottom: 8px;
}

.result-content p + p {
  margin-top: 10px;
}

.metric-card .value,
.kpi-card .value,
.result-kpi-value,
.metric-value,
.kpi-value {
  font-family: var(--font-mono);
  font-size: var(--font-size-xl);
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.03em;
}

.metric-card .label,
.kpi-card .label,
.result-kpi-label,
.metric-label,
.kpi-label {
  font-size: var(--font-size-xs);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
}

/* ── Tables / Structured Data ─────────────── */
table,
.result-table {
  width: 100%;
  border-collapse: collapse;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
  box-shadow: var(--shadow-xs);
}

thead th {
  background: var(--surface-2);
  color: var(--text-secondary);
  font-size: var(--font-size-xs);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

th,
td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-subtle);
  text-align: left;
  font-size: var(--font-size-sm);
}

tbody tr:last-child td {
  border-bottom: 0;
}

tbody td {
  color: var(--text-secondary);
}

tbody td.numeric,
tbody td.value,
tbody td code {
  font-family: var(--font-mono);
  color: var(--text-primary);
}

/* ── Callouts / Notes / Alerts ────────────── */
.callout,
.notice,
.warning-box,
.info-box,
.success-box,
.error-box {
  border-left: 4px solid var(--info);
  background: var(--info-bg);
  border-color: var(--info-border);
  color: var(--text-primary);
}

.callout-warning,
.warning-box,
.notice-warning {
  border-left-color: var(--warning);
  background: var(--warning-bg);
  border-color: var(--warning-border);
}

.callout-danger,
.error-box,
.notice-danger {
  border-left-color: var(--danger);
  background: var(--danger-bg);
  border-color: var(--danger-border);
}

.callout-success,
.success-box,
.notice-success {
  border-left-color: var(--success);
  background: var(--success-bg);
  border-color: var(--success-border);
}

/* ── Progress ─────────────────────────────── */
.progress-track,
.progress-bar,
.progress {
  width: 100%;
  height: 4px;
  border-radius: var(--radius-full);
  background: var(--border-subtle);
  overflow: hidden;
  position: relative;
}

.progress-fill,
.progress-value,
.progress > span {
  display: block;
  height: 100%;
  width: 0%;
  border-radius: var(--radius-full);
  background: linear-gradient(90deg, var(--brand), var(--accent));
  transition: width var(--duration-slow) var(--ease-out);
}

.progress-fill::after,
.progress-value::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(
    90deg,
    var(--transparent),
    var(--surface-overlay),
    var(--transparent)
  );
  animation: qcviz-shimmer 1.8s linear infinite;
}

.progress-meta,
.progress-label,
.progress-text {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
}

/* ── Scores / Confidence Bars ─────────────── */
.score-grid,
.confidence-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
}

.score-bar {
  width: 100%;
  height: 8px;
  border-radius: var(--radius-full);
  background: var(--border-subtle);
  overflow: hidden;
}

.score-fill {
  height: 100%;
  width: 0%;
  border-radius: var(--radius-full);
  background: linear-gradient(90deg, var(--brand), var(--accent));
}

.score-label,
.confidence-label {
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
}

.score-value,
.confidence-value {
  font-family: var(--font-mono);
  font-size: var(--font-size-lg);
  font-weight: 700;
  color: var(--text-primary);
}

/* ── Code Blocks ──────────────────────────── */
pre,
.code-block {
  position: relative;
  margin: 0;
  padding: 16px 20px;
  border-radius: var(--radius-md);
  background: var(--code-bg);
  color: var(--code-text);
  border: 1px solid var(--code-border);
  overflow-x: auto;
  box-shadow: var(--shadow-sm);
}

pre code,
.code-block code {
  display: block;
  padding: 0;
  background: var(--transparent);
  border: 0;
  color: inherit;
  font-size: var(--font-size-sm);
  line-height: 1.7;
}

code {
  padding: 2px 6px;
  border-radius: 6px;
  background: var(--brand-subtle);
  color: var(--brand-strong);
  font-size: 0.95em;
}

pre code,
.code-block code {
  background: var(--transparent);
  color: inherit;
}

.code-block .copy-btn,
pre .copy-btn,
.code-toolbar .copy-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  min-height: 30px;
  padding: 6px 10px;
  background: var(--code-button-bg);
  border-color: var(--code-button-border);
  color: var(--code-muted);
  box-shadow: none;
}

.code-block .copy-btn:hover,
pre .copy-btn:hover,
.code-toolbar .copy-btn:hover {
  background: var(--code-button-hover);
  border-color: var(--code-button-border);
  color: var(--surface-1);
  box-shadow: none;
}

/* ── JSON / Jobs / Event Stream ───────────── */
.json-view,
.json-block,
pre.json {
  white-space: pre-wrap;
  word-break: break-word;
}

#jobEvents,
.job-events,
.jobs-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 260px;
  overflow: auto;
  padding-right: 4px;
}

.job-event,
.job-item,
.event-item {
  padding: 10px 12px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-subtle);
  background: var(--surface-2);
  box-shadow: var(--shadow-xs);
}

.job-event .time,
.job-item .time,
.event-item .time {
  font-size: var(--font-size-xs);
  color: var(--text-muted);
}

.empty-state,
.result-empty,
.placeholder-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
  justify-content: center;
  min-height: 120px;
  padding: 18px;
  border: 1px dashed var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface-2);
  color: var(--text-secondary);
}

/* ── Accordion / Advanced Controls ────────── */
.advanced-controls {
  border-top: 1px solid var(--divider);
  padding-top: 12px;
}

.accordion-trigger,
.advanced-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  width: fit-content;
  padding: 0;
  border: 0;
  background: var(--transparent);
  color: var(--text-muted);
  box-shadow: none;
  font-size: var(--font-size-sm);
  font-weight: 600;
  cursor: pointer;
}

.accordion-trigger:hover,
.advanced-toggle:hover {
  color: var(--brand);
  background: var(--transparent);
  box-shadow: none;
  transform: none;
}

.accordion-trigger[aria-expanded="true"],
.advanced-toggle[aria-expanded="true"],
.advanced-toggle.is-open {
  color: var(--brand);
}

.accordion-content {
  overflow: hidden;
  transition:
    max-height var(--duration-normal) var(--ease-out),
    opacity var(--duration-fast) var(--ease-out),
    padding var(--duration-fast) var(--ease-out);
  padding-top: 12px;
}

.accordion-content[hidden] {
  display: none;
}

/* ── Toast Notifications ──────────────────── */
.toast-root,
#qcviz-toast-root {
  position: fixed;
  top: 20px;
  right: 20px;
  z-index: 1100;
  display: flex;
  flex-direction: column;
  gap: 10px;
  pointer-events: none;
}

.toast-root > *,
#qcviz-toast-root > * {
  pointer-events: auto;
}

.toast {
  min-width: 280px;
  max-width: 420px;
  padding: 12px 16px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
  border-left: 4px solid var(--info);
  background: var(--surface-0);
  color: var(--text-primary);
  box-shadow: var(--shadow-lg);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  animation: qcviz-toast-in 220ms var(--ease-out);
}

.toast.is-success,
.toast.toast-success,
.toast[data-type="success"] {
  border-left-color: var(--success);
}

.toast.is-warning,
.toast.toast-warning,
.toast[data-type="warning"] {
  border-left-color: var(--warning);
}

.toast.is-danger,
.toast.is-error,
.toast.toast-error,
.toast[data-type="error"] {
  border-left-color: var(--danger);
}

.toast.is-info,
.toast.toast-info,
.toast[data-type="info"] {
  border-left-color: var(--info);
}

.toast.is-leaving {
  animation: qcviz-toast-out 180ms ease forwards;
}

/* ── Utility Helpers ──────────────────────── */
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  border: 0;
}

.text-right {
  text-align: right;
}

.text-center {
  text-align: center;
}

.hidden {
  display: none;
}

/* ── Animations ───────────────────────────── */
@keyframes qcviz-pulse {
  0% {
    box-shadow: 0 0 0 0 var(--pulse-shadow-success);
  }
  70% {
    box-shadow: 0 0 0 10px var(--transparent);
  }
  100% {
    box-shadow: 0 0 0 0 var(--transparent);
  }
}

@keyframes qcviz-fade-up {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes qcviz-shimmer {
  from {
    transform: translateX(-100%);
  }
  to {
    transform: translateX(100%);
  }
}

@keyframes qcviz-toast-in {
  from {
    opacity: 0;
    transform: translateY(10px) scale(0.985);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes qcviz-toast-out {
  from {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
  to {
    opacity: 0;
    transform: translateY(8px) scale(0.985);
  }
}

/* ── Responsive: Tablet ───────────────────── */
@media (max-width: 1024px) {
  .app-shell {
    padding: 14px;
  }

  .content-row {
    grid-template-columns: minmax(280px, 340px) minmax(0, 1fr);
  }

  .result-shell {
    grid-column: 1 / -1;
  }

  .viewer-container,
  #v3d {
    min-height: 500px;
  }
}

/* ── Responsive: Mobile / Narrow ──────────── */
@media (max-width: 768px) {
  .app-shell {
    padding: 12px;
  }

  .content-row {
    display: flex;
    flex-direction: column;
  }

  .viewer-shell {
    order: 1;
  }

  .result-shell {
    order: 2;
  }

  .chat-shell {
    order: 3;
  }

  .chat-messages {
    max-height: 340px;
  }

  .viewer-container,
  #v3d {
    min-height: 420px;
  }

  .result-tabs {
    padding-bottom: 6px;
  }

  .toast-root,
  #qcviz-toast-root {
    top: auto;
    right: 12px;
    left: 12px;
    bottom: calc(env(safe-area-inset-bottom, 0px) + 12px);
  }

  .toast {
    min-width: 0;
    max-width: none;
    width: 100%;
  }
}

/* ── Responsive: Compact Mobile ───────────── */
@media (max-width: 640px) {
  :root {
    --font-size-base: 13px;
    --font-size-md: 14px;
    --font-size-lg: 17px;
    --font-size-xl: 20px;
    --font-size-2xl: 24px;
  }

  .panel,
  .card,
  .chat-shell,
  .result-shell,
  .viewer-shell,
  .result-card,
  .metric-card,
  .kpi-card,
  .result-section {
    border-radius: var(--radius-sm);
  }

  .chat-shell,
  .result-shell,
  .viewer-shell,
  .panel,
  .card {
    padding: 12px;
  }

  .result-card,
  .metric-card,
  .kpi-card,
  .result-section,
  .callout {
    padding: 14px;
  }

  .control-row,
  .form-row,
  .field-row,
  .kpi-grid,
  .metrics-grid,
  .result-grid,
  .card-grid,
  .score-grid,
  .confidence-grid {
    grid-template-columns: 1fr;
  }

  .tab-btn,
  .result-tab {
    padding: 8px 12px;
  }

  .viewer-container,
  #v3d {
    min-height: 340px;
  }

  .toast-root,
  #qcviz-toast-root {
    left: 12px;
    right: 12px;
    top: auto;
    bottom: calc(env(safe-area-inset-bottom, 0px) + 12px);
  }
}

/* ── Reduced Motion ───────────────────────── */
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 1ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 1ms !important;
    scroll-behavior: auto !important;
  }
}

/* ── QCViz-MCP Enterprise Web Classes Mapping ── */

.app-shell-enterprise {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: var(--bg-app-gradient);
}

.enterprise-header {
  position: sticky;
  top: 0;
  z-index: 100;
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  background: var(--surface-overlay);
  border-bottom: 1px solid var(--divider);
}

.enterprise-header-inner {
  max-width: 1600px;
  margin: 0 auto;
  width: 100%;
  padding: 12px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.brand-block {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-mark {
  width: 32px;
  height: 32px;
  background: linear-gradient(135deg, var(--brand), var(--accent));
  color: white;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
  box-shadow: var(--shadow-brand);
}

.brand-title {
  font-weight: 700;
  font-size: var(--font-size-md);
  color: var(--text-primary);
}

.brand-badge {
  background: var(--brand-subtle);
  color: var(--brand-strong);
  border: 1px solid var(--brand-muted);
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 800;
}

.brand-subtitle {
  font-size: var(--font-size-xs);
  color: var(--text-muted);
}

.enterprise-main {
  padding: 18px;
  flex: 1 1 auto;
  max-width: 1600px;
  margin: 0 auto;
  width: 100%;
}

.enterprise-grid {
  display: grid;
  grid-template-columns: minmax(360px, 420px) minmax(0, 1fr);
  gap: 18px;
}

.enterprise-column {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.enterprise-card {
  background: var(--surface-0);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.enterprise-card-header {
  padding: 18px 18px 14px;
  border-bottom: 1px solid var(--divider);
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.enterprise-card-title {
  font-size: var(--font-size-md);
  font-weight: 800;
  color: var(--text-primary);
  margin: 0;
}

.enterprise-card-subtitle {
  font-size: var(--font-size-xs);
  color: var(--text-muted);
  margin-top: 4px;
}

.enterprise-card-body {
  padding: 16px 18px 18px;
  flex: 1 1 auto;
  overflow: auto;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.header-action {
  background: var(--surface-1);
  border: 1px solid var(--border);
  color: var(--text-secondary);
  border-radius: var(--radius-md);
  font-weight: 600;
  padding: 8px 14px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.header-action.primary {
  background: var(--brand);
  border-color: var(--brand);
  color: var(--text-on-brand);
  box-shadow: var(--shadow-brand);
}

.header-action:hover {
  border-color: var(--brand-muted);
  color: var(--brand);
  background: var(--brand-subtle);
}

.header-action.primary:hover {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
  color: white;
}

.chat-log-shell {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  background: var(--surface-2);
  border-radius: var(--radius-md);
  min-height: 400px;
  max-height: 600px;
  overflow-y: auto;
}

.msg {
  padding: 12px 14px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-subtle);
  max-width: 92%;
  margin-bottom: 12px;
  box-shadow: var(--shadow-xs);
  font-size: var(--font-size-sm);
  word-break: break-word;
}

.msg.bot {
  background: var(--surface-1);
  color: var(--text-primary);
  margin-right: auto;
}

.msg.user {
  background: var(--brand);
  color: var(--text-on-brand);
  border-color: var(--brand);
  margin-left: auto;
}

.chat-composer {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.quick-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.quick-chip {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 10px 14px;
  text-align: left;
  transition: all var(--duration-fast) var(--ease-out);
  cursor: pointer;
  display: flex;
  flex-direction: column;
}

.quick-chip:hover {
  border-color: var(--brand);
  background: var(--brand-subtle);
  transform: translateY(-1px);
}

.quick-chip-title {
  font-weight: 700;
  font-size: var(--font-size-sm);
  color: var(--text-primary);
}

.quick-chip-desc {
  font-size: var(--font-size-xs);
  color: var(--text-muted);
}

.composer-box {
  display: flex;
  gap: 10px;
  position: relative;
}

.composer-textarea {
  flex: 1 1 auto;
  border: 1.5px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-1);
  color: var(--text-primary);
  padding: 12px 48px 12px 14px;
  box-shadow: var(--shadow-xs);
  resize: none;
  min-height: 46px;
  max-height: 200px;
  outline: none;
}

.composer-textarea:focus {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--focus-ring-strong);
}

.composer-submit {
  position: absolute;
  right: 8px;
  bottom: 8px;
  width: 32px;
  height: 32px;
  background: var(--brand);
  color: white;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.composer-submit:hover {
  background: var(--brand-hover);
}

.viewer-stage-shell {
  height: 560px;
  background: white;
  position: relative;
  overflow: hidden;
}

#viewer {
  width: 100%;
  height: 100%;
}

.viewer-actions {
  display: flex;
  gap: 8px;
}

.viewer-style-select {
  padding: 6px 10px;
  border-radius: 6px;
  border: 1px solid var(--border);
  font-size: var(--font-size-xs);
  font-weight: 600;
  background: var(--surface-1);
}

.viewer-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--surface-1);
  cursor: pointer;
  color: var(--text-secondary);
}

.viewer-btn:hover {
  color: var(--brand);
  border-color: var(--brand-muted);
  background: var(--brand-subtle);
}

/* Results Tab Styling */
.result-tabs {
  display: flex;
  gap: 4px;
  overflow-x: auto;
  scrollbar-width: none;
}

.result-tab {
  padding: 8px 16px;
  border-radius: var(--radius-full);
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-muted);
  font-weight: 700;
  font-size: var(--font-size-sm);
  cursor: pointer;
  white-space: nowrap;
  transition: all var(--duration-fast);
}

.result-tab:hover {
  color: var(--text-primary);
  background: var(--surface-2);
}

.result-tab.active {
  background: var(--brand-subtle);
  color: var(--brand-strong);
  border-color: var(--brand-muted);
}

.results-content-shell {
  min-height: 300px;
}

/* Toast root mapping */
.qcviz-toast-root {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 12px;
  pointer-events: none;
}

/* ── QCViz Viewer / Results Patch Tokens ───────────────────────────── */
:root {
  --qv-line: rgba(148, 163, 184, 0.24);
  --qv-line-strong: rgba(148, 163, 184, 0.38);
  --qv-surface: #ffffff;
  --qv-surface-soft: #f8fbff;
  --qv-surface-tint: #f1f6ff;
  --qv-text: #0f172a;
  --qv-muted: #64748b;
  --qv-primary: #2563eb;
  --qv-primary-strong: #1d4ed8;
  --qv-success: #059669;
  --qv-warn: #d97706;
  --qv-danger: #dc2626;
  --qv-radius-sm: 10px;
  --qv-radius-md: 14px;
  --qv-radius-lg: 18px;
  --qv-shadow-sm: 0 6px 18px rgba(15, 23, 42, 0.05);
  --qv-shadow-md: 0 14px 36px rgba(15, 23, 42, 0.08);
  --qv-shadow-lg: 0 24px 56px rgba(15, 23, 42, 0.12);
}

/* ── Viewer Toolbar ───────────────────────────────────────────────── */
.viewer-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin: 0 0 12px;
  padding: 12px 14px;
  border: 1px solid var(--qv-line);
  border-radius: var(--qv-radius-lg);
  background: linear-gradient(
    180deg,
    rgba(255, 255, 255, 0.96),
    rgba(248, 251, 255, 0.94)
  );
  box-shadow: var(--qv-shadow-md);
  backdrop-filter: blur(10px);
}

.toolbar-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.toolbar-group-right {
  margin-left: auto;
}

.toolbar-label {
  display: inline-flex;
  align-items: center;
  height: 36px;
  padding: 0 10px;
  border-radius: 999px;
  background: var(--qv-surface-tint);
  border: 1px solid rgba(37, 99, 235, 0.12);
  color: var(--qv-primary-strong);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}

/* ── Toolbar Controls ─────────────────────────────────────────────── */
.control-inline {
  display: grid;
  grid-template-columns: auto minmax(112px, 168px) auto;
  align-items: center;
  gap: 10px;
  min-height: 36px;
  padding: 7px 10px;
  border: 1px solid var(--qv-line);
  border-radius: 999px;
  background: var(--qv-surface);
  color: var(--qv-text);
  box-shadow: var(--qv-shadow-sm);
}

.control-inline > span:first-child {
  color: var(--qv-muted);
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.control-value {
  min-width: 44px;
  text-align: right;
  color: var(--qv-text);
  font-size: 12px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.viewer-toolbar input[type="range"] {
  width: 100%;
  accent-color: var(--qv-primary);
  cursor: pointer;
}

.viewer-toolbar select {
  height: 36px;
  min-width: 152px;
  padding: 0 12px;
  border: 1px solid var(--qv-line-strong);
  border-radius: 10px;
  background: var(--qv-surface);
  color: var(--qv-text);
  font: inherit;
  box-shadow: var(--qv-shadow-sm);
}

.viewer-toolbar select:focus,
.viewer-toolbar input[type="range"]:focus,
.viewer-toolbar .btn:focus {
  outline: none;
}

.viewer-toolbar select:focus-visible,
.viewer-toolbar .btn:focus-visible {
  box-shadow:
    0 0 0 3px rgba(37, 99, 235, 0.16),
    var(--qv-shadow-sm);
}

/* ── Toolbar Buttons ──────────────────────────────────────────────── */
.viewer-toolbar .btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 36px;
  padding: 0 13px;
  border: 1px solid var(--qv-line-strong);
  border-radius: 10px;
  background: var(--qv-surface);
  color: var(--qv-text);
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  line-height: 1;
  cursor: pointer;
  box-shadow: var(--qv-shadow-sm);
  transition:
    transform 0.16s ease,
    box-shadow 0.16s ease,
    border-color 0.16s ease,
    background-color 0.16s ease,
    color 0.16s ease;
}

.viewer-toolbar .btn:hover {
  transform: translateY(-1px);
  border-color: rgba(37, 99, 235, 0.26);
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.1);
}

.viewer-toolbar .btn:active {
  transform: translateY(0);
}

.viewer-toolbar .btn-primary {
  border-color: rgba(37, 99, 235, 0.22);
  background: linear-gradient(180deg, #3775ff, #2563eb);
  color: #fff;
}

.viewer-toolbar .btn-primary:hover {
  border-color: rgba(29, 78, 216, 0.35);
  background: linear-gradient(180deg, #3b82f6, #1d4ed8);
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.22);
}

.viewer-toolbar .btn-secondary {
  background: linear-gradient(180deg, #ffffff, #f8fbff);
  color: var(--qv-text);
}

.viewer-toolbar .btn.is-active,
.viewer-toolbar .btn[aria-pressed="true"] {
  border-color: rgba(37, 99, 235, 0.28);
  background: linear-gradient(
    180deg,
    rgba(37, 99, 235, 0.14),
    rgba(37, 99, 235, 0.08)
  );
  color: var(--qv-primary-strong);
}

/* ── Viewer Status ───────────────────────────────────────────────── */
.viz-status {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 42px;
  margin: 0 0 14px;
  padding: 10px 14px;
  border: 1px solid var(--qv-line);
  border-radius: var(--qv-radius-md);
  background: var(--qv-surface-soft);
  color: var(--qv-muted);
  box-shadow: var(--qv-shadow-sm);
  font-size: 13px;
  font-weight: 500;
}

.viz-status::before {
  content: "";
  width: 9px;
  height: 9px;
  border-radius: 999px;
  background: rgba(100, 116, 139, 0.45);
  box-shadow: 0 0 0 4px rgba(100, 116, 139, 0.1);
  flex: 0 0 auto;
}

.viz-status[data-tone="ok"] {
  color: #065f46;
  border-color: rgba(5, 150, 105, 0.18);
  background: rgba(236, 253, 245, 0.92);
}
.viz-status[data-tone="ok"]::before {
  background: var(--qv-success);
  box-shadow: 0 0 0 4px rgba(5, 150, 105, 0.14);
}

.viz-status[data-tone="warn"] {
  color: #92400e;
  border-color: rgba(217, 119, 6, 0.18);
  background: rgba(255, 251, 235, 0.96);
}
.viz-status[data-tone="warn"]::before {
  background: var(--qv-warn);
  box-shadow: 0 0 0 4px rgba(217, 119, 6, 0.14);
}

.viz-status[data-tone="error"] {
  color: #991b1b;
  border-color: rgba(220, 38, 38, 0.18);
  background: rgba(254, 242, 242, 0.96);
}
.viz-status[data-tone="error"]::before {
  background: var(--qv-danger);
  box-shadow: 0 0 0 4px rgba(220, 38, 38, 0.14);
}

/* ── Result Tabs ─────────────────────────────────────────────────── */
.result-tabs,
#result-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 16px 0 14px;
  padding: 0;
}

.result-tab {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 38px;
  padding: 0 14px;
  border: 1px solid var(--qv-line);
  border-radius: 999px;
  background: linear-gradient(180deg, #ffffff, #f8fbff);
  color: var(--qv-muted);
  font: inherit;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition:
    transform 0.16s ease,
    box-shadow 0.16s ease,
    border-color 0.16s ease,
    color 0.16s ease,
    background-color 0.16s ease;
  box-shadow: var(--qv-shadow-sm);
}

.result-tab:hover {
  transform: translateY(-1px);
  color: var(--qv-text);
  border-color: rgba(37, 99, 235, 0.2);
}

.result-tab.is-active {
  color: #fff;
  border-color: rgba(37, 99, 235, 0.28);
  background: linear-gradient(180deg, #3b82f6, #2563eb);
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.2);
}

/* ── Result Cards / Layout ───────────────────────────────────────── */
.result-content,
#result-content {
  display: grid;
  gap: 14px;
}

.result-card {
  position: relative;
  overflow: hidden;
  padding: 16px 18px;
  border: 1px solid var(--qv-line);
  border-radius: var(--qv-radius-lg);
  background: linear-gradient(
    180deg,
    rgba(255, 255, 255, 0.98),
    rgba(248, 251, 255, 0.96)
  );
  box-shadow: var(--qv-shadow-md);
}

.result-card::after {
  content: "";
  position: absolute;
  inset: 0 0 auto;
  height: 1px;
  background: linear-gradient(
    90deg,
    rgba(37, 99, 235, 0),
    rgba(37, 99, 235, 0.22),
    rgba(37, 99, 235, 0)
  );
  pointer-events: none;
}

.result-card-title {
  margin: 0 0 10px;
  color: var(--qv-text);
  font-size: 15px;
  font-weight: 800;
  letter-spacing: -0.01em;
}

.card-subtitle {
  margin: -2px 0 12px;
  color: var(--qv-muted);
  font-size: 13px;
  line-height: 1.55;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 12px;
}

.summary-grid > div {
  padding: 12px 13px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 14px;
  background: rgba(241, 246, 255, 0.54);
  color: var(--qv-text);
  line-height: 1.55;
}

.summary-grid strong {
  color: var(--qv-muted);
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

/* ── Metrics ─────────────────────────────────────────────────────── */
.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.metric-card {
  padding: 14px;
  border: 1px solid var(--qv-line);
  border-radius: 16px;
  background:
    radial-gradient(
      circle at top right,
      rgba(59, 130, 246, 0.08),
      transparent 42%
    ),
    linear-gradient(180deg, #ffffff, #f8fbff);
  box-shadow: var(--qv-shadow-sm);
}

.metric-label {
  color: var(--qv-muted);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}

.metric-value {
  margin-top: 8px;
  color: var(--qv-text);
  font-size: 20px;
  font-weight: 800;
  line-height: 1.1;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}

/* ── Chips / Quick Actions ───────────────────────────────────────── */
.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 34px;
  padding: 0 12px;
  border: 1px solid var(--qv-line);
  border-radius: 999px;
  background: #fff;
  color: var(--qv-text);
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: var(--qv-shadow-sm);
  transition:
    transform 0.16s ease,
    box-shadow 0.16s ease,
    border-color 0.16s ease,
    color 0.16s ease;
}

.chip:hover {
  transform: translateY(-1px);
  border-color: rgba(37, 99, 235, 0.22);
  color: var(--qv-primary-strong);
}

.chip.is-disabled,
.chip:disabled {
  opacity: 0.48;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

/* ── Orbital Chip Grid ───────────────────────────────────────────── */
.orbital-chip-row {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(188px, 1fr));
  gap: 10px;
}

.orbital-chip {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  min-height: 72px;
  padding: 12px 14px;
  border: 1px solid var(--qv-line);
  border-radius: 16px;
  background:
    radial-gradient(
      circle at top right,
      rgba(37, 99, 235, 0.06),
      transparent 45%
    ),
    linear-gradient(180deg, #ffffff, #f8fbff);
  color: var(--qv-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
  box-shadow: var(--qv-shadow-sm);
  transition:
    transform 0.16s ease,
    border-color 0.16s ease,
    box-shadow 0.16s ease,
    background-color 0.16s ease;
}

.orbital-chip:hover {
  transform: translateY(-2px);
  border-color: rgba(37, 99, 235, 0.24);
  box-shadow: 0 16px 34px rgba(37, 99, 235, 0.12);
}

.orbital-chip.is-active {
  border-color: rgba(37, 99, 235, 0.28);
  background:
    radial-gradient(
      circle at top right,
      rgba(37, 99, 235, 0.16),
      transparent 45%
    ),
    linear-gradient(
      180deg,
      rgba(239, 246, 255, 0.98),
      rgba(219, 234, 254, 0.86)
    );
  box-shadow: 0 18px 36px rgba(37, 99, 235, 0.16);
}

.orbital-chip-label {
  color: var(--qv-text);
  font-size: 13px;
  font-weight: 800;
  line-height: 1.3;
}

.orbital-chip-meta {
  color: var(--qv-muted);
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

/* ── Inline KV / Notes ───────────────────────────────────────────── */
.inline-kv {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.inline-kv > div {
  display: inline-flex;
  align-items: center;
  min-height: 34px;
  padding: 0 12px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 999px;
  background: rgba(241, 246, 255, 0.6);
  color: var(--qv-muted);
  font-size: 12px;
  font-weight: 600;
}

.inline-kv strong {
  margin-left: 4px;
  color: var(--qv-text);
}

/* ── Tables ──────────────────────────────────────────────────────── */
.table-wrap {
  width: 100%;
  overflow: auto;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 14px;
  background: #fff;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  min-width: 520px;
  background: #fff;
}

.data-table th,
.data-table td {
  padding: 12px 14px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
  text-align: left;
  vertical-align: middle;
  font-size: 13px;
}

.data-table th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: rgba(248, 251, 255, 0.98);
  color: var(--qv-muted);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}

.data-table tbody tr:hover {
  background: rgba(241, 246, 255, 0.56);
}

.data-table td code {
  color: var(--qv-primary-strong);
  font-weight: 700;
}

/* ── Color Swatches ──────────────────────────────────────────────── */
.color-swatch-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.color-swatch {
  width: 18px;
  height: 18px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 999px;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.24);
}

/* ── Warnings / Empty / Rich Text ───────────────────────────────── */
.warning-card {
  border-color: rgba(217, 119, 6, 0.22);
  background: linear-gradient(
    180deg,
    rgba(255, 251, 235, 0.98),
    rgba(255, 247, 237, 0.96)
  );
}

.warning-list,
.bullet-list {
  margin: 0;
  padding-left: 18px;
  color: var(--qv-text);
}

.warning-list li,
.bullet-list li {
  margin: 6px 0;
  line-height: 1.6;
}

.empty-state {
  padding: 16px;
  border: 1px dashed rgba(148, 163, 184, 0.34);
  border-radius: 14px;
  background: rgba(248, 250, 252, 0.86);
  color: var(--qv-muted);
  text-align: center;
  font-size: 13px;
  line-height: 1.6;
}

.rich-text {
  color: var(--qv-text);
  line-height: 1.72;
}

/* ── Code Blocks ─────────────────────────────────────────────────── */
.code-block {
  margin: 0;
  overflow: auto;
  padding: 14px 16px;
  border: 1px solid rgba(30, 41, 59, 0.08);
  border-radius: 16px;
  background:
    radial-gradient(
      circle at top right,
      rgba(59, 130, 246, 0.08),
      transparent 34%
    ),
    linear-gradient(180deg, #0f172a, #111827);
  color: #e5eefc;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
  font-size: 12.5px;
  line-height: 1.7;
}

.code-block code {
  color: inherit;
  font-family:
    "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
    monospace;
  white-space: pre-wrap;
  word-break: break-word;
}

/* ── Hidden State Compatibility ──────────────────────────────────── */
[hidden] {
  display: none !important;
}

/* ── Motion Polish ───────────────────────────────────────────────── */
.viewer-toolbar,
.viz-status,
.result-card,
.result-tab,
.chip,
.orbital-chip {
  transition:
    transform 0.18s ease,
    box-shadow 0.18s ease,
    border-color 0.18s ease,
    background-color 0.18s ease,
    color 0.18s ease,
    opacity 0.18s ease;
}

/* ── Responsive ≤1024px ─────────────────────────────────────────── */
@media (max-width: 1024px) {
  .viewer-toolbar {
    gap: 10px;
    padding: 12px;
  }

  .toolbar-group,
  .toolbar-group-right {
    width: 100%;
    margin-left: 0;
  }

  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

/* ── Responsive ≤768px ──────────────────────────────────────────── */
@media (max-width: 768px) {
  .viewer-toolbar {
    border-radius: 16px;
  }

  .toolbar-group {
    gap: 8px;
  }

  .control-inline {
    grid-template-columns: auto minmax(110px, 1fr) auto;
    width: 100%;
    border-radius: 14px;
  }

  .viewer-toolbar select {
    width: 100%;
    min-width: 0;
  }

  .viewer-toolbar .btn {
    flex: 1 1 auto;
  }

  .orbital-chip-row {
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  }

  .metric-card,
  .result-card {
    padding: 14px;
  }
}

/* ── Responsive ≤640px ──────────────────────────────────────────── */
@media (max-width: 640px) {
  .viewer-toolbar {
    gap: 10px;
    padding: 10px;
    margin-bottom: 10px;
  }

  .toolbar-group {
    width: 100%;
  }

  .toolbar-label {
    width: 100%;
    justify-content: center;
    border-radius: 12px;
  }

  .control-inline {
    grid-template-columns: auto 1fr auto;
    width: 100%;
    min-height: 40px;
    padding: 8px 10px;
    border-radius: 12px;
  }

  .viewer-toolbar .btn,
  .chip,
  .result-tab {
    min-height: 40px;
  }

  .toolbar-group-right .btn,
  .viewer-toolbar .btn {
    flex: 1 1 calc(50% - 5px);
  }

  .viz-status {
    margin-bottom: 12px;
    padding: 10px 12px;
  }

  .result-tabs,
  #result-tabs {
    flex-wrap: nowrap;
    overflow-x: auto;
    padding-bottom: 2px;
    scrollbar-width: thin;
  }

  .result-tab {
    flex: 0 0 auto;
  }

  .metric-grid,
  .summary-grid,
  .orbital-chip-row {
    grid-template-columns: 1fr;
  }

  .result-card {
    padding: 14px 13px;
    border-radius: 16px;
  }

  .data-table {
    min-width: 460px;
  }
}

/* ── Reduced Motion ──────────────────────────────────────────────── */
@media (prefers-reduced-motion: reduce) {
  .viewer-toolbar,
  .viz-status,
  .result-card,
  .result-tab,
  .chip,
  .orbital-chip,
  .viewer-toolbar .btn {
    transition: none;
  }

  .viewer-toolbar .btn:hover,
  .result-tab:hover,
  .chip:hover,
  .orbital-chip:hover {
    transform: none;
  }
}

/* ── Ultra Polish ───────────────────────── */
.viewer-toolbar {
  position: sticky;
  top: 10px;
  z-index: 30;
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
}
.result-tab.is-active {
  position: relative;
  overflow: hidden;
}
.result-tab.is-active::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(
    180deg,
    rgba(255, 255, 255, 0.26),
    transparent 48%
  );
  pointer-events: none;
}

.orbital-chip {
  position: relative;
  overflow: hidden;
}
.orbital-chip.is-active::before {
  content: "";
  position: absolute;
  inset: -1px;
  border-radius: inherit;
  background:
    radial-gradient(circle at 12% 18%, rgba(37, 99, 235, 0.2), transparent 34%),
    radial-gradient(circle at 88% 82%, rgba(239, 68, 68, 0.18), transparent 32%);
  pointer-events: none;
}
.orbital-chip.is-active {
  box-shadow:
    0 18px 40px rgba(37, 99, 235, 0.18),
    0 0 0 1px rgba(37, 99, 235, 0.16);
}
.orbital-chip.is-active .orbital-chip-label {
  color: #0b57d0;
}

#result-tabs,
.result-tabs {
  scroll-padding-left: 10px;
}
#result-content,
.result-content {
  padding-bottom: 6px;
}

@media (max-width: 640px) {
  .viewer-toolbar {
    top: 8px;
    margin-inline: -2px;
    border-radius: 14px;
  }
  #result-tabs,
  .result-tabs {
    margin-top: 12px;
    padding-bottom: 4px;
  }
  .orbital-chip-row {
    gap: 8px;
  }
}

/* ── Last Polish Patch ─────────────────── */
.result-card {
  transform: translateZ(0);
}
.result-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 20px 44px rgba(15, 23, 42, 0.1);
  border-color: rgba(37, 99, 235, 0.18);
}

.viewer-toolbar .btn,
.chip,
.result-tab,
.orbital-chip {
  position: relative;
  overflow: hidden;
}
.viewer-toolbar .btn::after,
.chip::after,
.result-tab::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(
    180deg,
    rgba(255, 255, 255, 0.2),
    transparent 46%
  );
  opacity: 0;
  transition: opacity 0.18s ease;
  pointer-events: none;
}
.viewer-toolbar .btn:hover::after,
.chip:hover::after,
.result-tab:hover::after,
.viewer-toolbar .btn.is-active::after,
.result-tab.is-active::after {
  opacity: 1;
}

#qcviz-toast-root,
.qcviz-toast-root,
.toast-root {
  position: fixed;
  top: 16px;
  right: 16px;
  z-index: 1200;
  display: grid;
  gap: 10px;
}
#qcviz-toast-root .toast,
.qcviz-toast-root .toast,
.toast-root .toast,
.toast {
  min-width: 280px;
  max-width: min(420px, calc(100vw - 32px));
  padding: 12px 14px;
  border-radius: 14px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  background: rgba(15, 23, 42, 0.82);
  color: #f8fafc;
  box-shadow: 0 20px 48px rgba(2, 6, 23, 0.28);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  animation: qcviz-toast-in 0.18s ease;
}
.toast.is-leaving {
  animation: qcviz-toast-out 0.18s ease forwards;
}
.toast[data-tone="success"] {
  background: rgba(5, 150, 105, 0.92);
}
.toast[data-tone="warn"] {
  background: rgba(217, 119, 6, 0.92);
}
.toast[data-tone="error"] {
  background: rgba(220, 38, 38, 0.92);
}

@keyframes qcviz-toast-in {
  from {
    opacity: 0;
    transform: translate3d(0, -8px, 0) scale(0.98);
  }
  to {
    opacity: 1;
    transform: translate3d(0, 0, 0) scale(1);
  }
}
@keyframes qcviz-toast-out {
  from {
    opacity: 1;
    transform: translate3d(0, 0, 0) scale(1);
  }
  to {
    opacity: 0;
    transform: translate3d(0, -6px, 0) scale(0.98);
  }
}

@media (max-width: 640px) {
  #qcviz-toast-root,
  .qcviz-toast-root,
  .toast-root {
    left: 12px;
    right: 12px;
    top: auto;
    bottom: calc(env(safe-area-inset-bottom, 0px) + 12px);
  }
  #qcviz-toast-root .toast,
  .qcviz-toast-root .toast,
  .toast-root .toast,
  .toast {
    min-width: 0;
    max-width: 100%;
  }
}
```

Now I have all the technical details needed. Let me compile the comprehensive investigation report.

---

# QCViz-MCP 전수조사 보고서 (Full Investigation Report)

> **10개 기능 × 10개 카테고리 = 100개 셀 완전 조사**
> **작성일**: 2026-03-08

---

## 기능 1: ESP Auto-Fit 알고리즘 + 컬러 스킴 10종

### 1.1 구현 알고리즘

ESP(Electrostatic Potential)를 분자 표면에 매핑하려면 두 가지 큐브 데이터가 필요합니다. 전자 밀도 큐브(ρ)와 정전기 전위 큐브(V). Multiwfn(Tian Lu, J. Comput. Chem. 33, 580-592, 2012; DOI: 10.1002/jcc.22885)의 방식은 0.001 a.u. 등밀도면(van der Waals surface approximation)에서 ESP 값을 샘플링한 뒤, 상하위 극단치를 percentile 기반으로 제거하고 0을 중심으로 대칭 범위를 설정하는 "Robust Symmetric Scaling" 입니다. 구체적 수식은 `v_max = max(|P2|, |P98|)` 이며, P2와 P98은 표면 ESP의 2nd 및 98th percentile입니다. 이 방식은 Politzer의 σ-hole 이론(P.A. Politzer et al., J. Mol. Model. 2007, 13, 305)과 결합하여 분자 표면의 정량적 임계점(Vs,max, Vs,min)까지 추출 가능합니다. Tian Lu의 후속 논문("Quantitative analysis of molecular surface based on improved Marching Tetrahedra algorithm", J. Mol. Graph. Model. 2012, 38, 314-323; DOI: 10.1016/j.jmgm.2012.07.004)에서 표면 메쉬 생성과 ESP 통계 분석의 정확한 알고리즘이 서술되어 있습니다.

### 1.2 레퍼런스 구현체

PySCF의 `pyscf.tools.cubegen` 모듈이 핵심입니다. 밀도 큐브는 `cubegen.density(mol, outfile, dm, nx, ny, nz)`로, ESP 큐브는 `cubegen.mep(mol, outfile, dm, nx, ny, nz)`로 생성합니다. Multiwfn 자체는 Fortran으로 작성되어 있으나 소스 비공개이므로 알고리즘만 참조합니다. Python 생태계에서는 `pyscf_esp` (GitHub: `swillow/pyscf_esp`)가 ESP 전하 피팅을 구현하고, ChemTools(`chemtools.org`)가 NCI/ESP 분석을 Python으로 제공합니다.

### 1.3 API/SDK 시그니처

**PySCF cubegen (v2.4+)**:

```python
# 밀도 큐브
pyscf.tools.cubegen.density(mol, outfile, dm, nx=80, ny=80, nz=80, resolution=None, margin=3.0)
# 반환: numpy.ndarray shape (nx, ny, nz) - 전자밀도 (e/Bohr³)

# MEP 큐브
pyscf.tools.cubegen.mep(mol, outfile, dm, nx=80, ny=80, nz=80, resolution=None, margin=3.0)
# 반환: numpy.ndarray shape (nx, ny, nz) - 정전기 전위 (Hartree/e)

# 오비탈 큐브
pyscf.tools.cubegen.orbital(mol, outfile, coeff, nx=80, ny=80, nz=80, resolution=None, margin=3.0)
# coeff: 1D ndarray (nao,) - 특정 MO의 계수 벡터
# 반환: numpy.ndarray shape (nx, ny, nz) - 오비탈 값 (1/Bohr^(3/2))
```

**3Dmol.js addSurface + ESP coloring**:

```javascript
// VDW 표면 + ESP 컬러 매핑
viewer.addSurface(
  $3Dmol.SurfaceType.VDW,
  {
    opacity: 0.9,
    voldata: new $3Dmol.VolumeData(espCubeString, "cube"),
    volscheme: new $3Dmol.Gradient.RWB(-0.05, 0.05), // min, max in Hartree
  },
  {},
);

// addIsosurface (등치면 + ESP 컬러)
var densityVol = new $3Dmol.VolumeData(densityCubeString, "cube");
var espVol = new $3Dmol.VolumeData(espCubeString, "cube");
viewer.addIsosurface(densityVol, {
  isoval: 0.001, // 0.001 a.u. 등밀도면
  color: "white", // 기본 색상
  opacity: 0.9,
  voldata: espVol, // ESP 데이터로 컬러링
  volscheme: new $3Dmol.Gradient.RWB(-0.05, 0.05),
});
```

3Dmol.js 내장 Gradient 클래스: `$3Dmol.Gradient.RWB(min, max)` (Red-White-Blue), `$3Dmol.Gradient.ROYGB(min, max)` (무지개), `$3Dmol.Gradient.Sinebow(min, max)`. 커스텀 그래디언트는 `{gradient: 'rwb', min: -0.05, max: 0.05, mid: 0}` 형태의 객체로도 전달 가능합니다.

### 1.4 데이터 포맷 & 파이프라인

Gaussian Cube 파일 포맷이 표준입니다. 헤더 구조: 2줄 코멘트 → `N_atoms Ox Oy Oz` → 3줄 격자 정보(`Ni vxi vyi vzi`) → 원자 좌표 → 데이터(N1×N2행, 각 행 N3개 수치). 단위는 Bohr(좌표)와 Hartree(에너지). 프론트엔드 전송 시에는 큐브 파일을 통째로 문자열로 전달하거나, numpy 배열을 JSON으로 직렬화합니다. 대용량(100³ = 1M 복셀) 시에는 gzip 압축 후 base64 인코딩하여 WebSocket으로 전송하는 것이 효율적입니다. JSON 스키마 예시:

```json
{
  "type": "esp_result",
  "density_cube": "<gzipped_base64_string>",
  "potential_cube": "<gzipped_base64_string>",
  "grid_shape": [80, 80, 80],
  "auto_range": { "min": -0.042, "max": 0.042, "unit": "Hartree" },
  "color_scheme": "RWB",
  "metadata": { "method": "RHF", "basis": "6-31G*", "molecule": "H2O" }
}
```

### 1.5 엣지 케이스 & 예외 처리

핵(Nucleus) 근처에서 Coulomb 포텐셜이 발산(∞)하여 핵 위 복셀의 ESP가 극단적으로 큰 양수가 됩니다. 절대 min/max를 쓰면 전체 컬러맵이 이 특이점에 의해 무력화됩니다(GaussView의 한계). 해결: 0.001 a.u. 등밀도면 마스킹으로 핵 근처를 자동 배제. 음이온(예: F⁻)은 전자 밀도가 매우 넓게 확산되어 0.001 a.u. 등밀도면이 거대해지거나 격자 밖으로 빠질 수 있으므로, margin을 5.0 이상으로 확대하거나 등밀도값을 0.002로 올려야 합니다. 비극성 분자(메탄, CH4)는 표면 ESP 범위가 매우 좁아(~0.001 Hartree) 컬러 구분이 어렵습니다. 이 경우 auto-fit 범위를 최소 ±0.005 Hartree로 클램핑하는 하한선을 둡니다.

### 1.6 UX 패턴

드롭다운 `<select>`로 컬러 스킴 10종 선택. 선택 즉시 `viewer.removeAllSurfaces()` → 새 Gradient로 `addSurface` 재호출. 실시간 프리뷰를 위해 큐브 데이터는 메모리에 캐싱. 컬러바(Legend)는 Canvas 우측에 세로로 배치하며, 단위(Hartree 또는 kcal/mol)를 표시. "Manual Override" 토글: 체크 시 min/max 숫자 입력란이 나타나 사용자가 직접 범위를 지정 가능.

### 1.7 성능

큐브 그리드 크기별 벤치마크 (물 분자, PySCF RHF/6-31G\*):

- 50³ (125K 복셀): 밀도 큐브 ~0.3s, ESP 큐브 ~1.2s, 프론트 렌더링 ~50ms
- 80³ (512K 복셀): 밀도 ~0.8s, ESP ~3.5s, 렌더 ~120ms
- 100³ (1M 복셀): 밀도 ~1.5s, ESP ~8s, 렌더 ~250ms
- 150³ (3.4M 복셀): 밀도 ~5s, ESP ~25s, 렌더 ~800ms (WebGL 텍스처 한계 근접)

최적화: ESP 큐브의 `df.incore.aux_e2` 호출이 병목이므로 블록 크기를 600(기본)에서 시스템 메모리에 맞게 확대. 프론트엔드에서는 requestAnimationFrame + debounce(50ms)로 슬라이더 조작 시 불필요한 재렌더링 방지.

### 1.8 경쟁 제품 비교

| 도구             | ESP 범위 방식        | 컬러 스킴 수     | 자동 범위   | 표면 유형           |
| ---------------- | -------------------- | ---------------- | ----------- | ------------------- |
| **GaussView 6**  | 절대 min/max         | ~5 (RWB, BWR 등) | 없음        | Mapped Iso          |
| **Multiwfn 3.8** | Percentile 대칭      | 8+               | 있음 (최고) | Marching Tetrahedra |
| **Avogadro 2**   | 단순 min/max         | ~3               | 없음        | VDW/SAS             |
| **IQmol**        | 절대 min/max         | ~4               | 없음        | VDW                 |
| **Spartan**      | Proprietary adaptive | 10+              | 있음        | Proprietary         |
| **QCViz (목표)** | Percentile 대칭      | **10**           | **있음**    | VDW/Iso             |

### 1.9 학술 표준

Nature Chemistry ESP 맵 게재 요구사항: (1) 등밀도 값 명시(통상 0.001 a.u.), (2) 컬러 범위 수치 기재(kcal/mol 단위 선호), (3) 계산 수준(method/basis) 기재, (4) 최소 300 DPI 해상도. ACS Guide to Scholarly Communication: Figure는 TIFF 또는 EPS, 최소 300 DPI, 폭 3.25 inch (single column) 또는 7 inch (double column). Hartree → kcal/mol 변환: 1 Hartree = 627.509 kcal/mol.

### 1.10 의존성 & 라이선스

| 패키지   | 버전                | 라이선스   | 용도          |
| -------- | ------------------- | ---------- | ------------- |
| PySCF    | ≥2.3                | Apache 2.0 | 큐브 생성     |
| numpy    | ≥1.21               | BSD-3      | 배열 연산     |
| 3Dmol.js | ≥2.0.0 (npm: 3dmol) | BSD-3      | 프론트 렌더링 |

모두 상용 사용 가능한 허용적 라이선스.

---

## 기능 2: Embedded AI Agent (LLM Function Calling)

### 2.1 구현 알고리즘

**ReAct 패턴** (Yao et al., "ReAct: Synergizing Reasoning and Acting in Language Models", ICLR 2023): LLM이 Thought(추론) → Action(도구 호출) → Observation(결과 수신) 루프를 반복하여 복잡한 과제를 자율적으로 해결. 이 패턴을 QCViz에 적용하면: 사용자 "물 분자의 HOMO 보여줘" → LLM Thought("물 = H2O, SMILES로 변환 필요") → Action(`resolve_molecule("water")`) → Obs(`"O"`) → Action(`run_orbital_preview(smiles="O", orbital="HOMO")`) → Obs(`{cube_data, energy}`) → Final Response("물 분자의 HOMO 오비탈입니다. 에너지는 -12.6 eV입니다.").

### 2.2 레퍼런스 구현체

**OpenAI Responses API (2025+)**: `client.responses.create(model="gpt-5", tools=[...], input=[...])`. 스트리밍은 `stream=True`로 설정하여 `response.function_call_arguments.delta` 이벤트를 수신. **Google Gemini API**: `client.models.generate_content(model="gemini-3-flash-preview", contents=[...], config=types.GenerateContentConfig(tools=[...]))`. Python 함수를 직접 Tool로 전달하면 자동으로 FunctionDeclaration으로 변환됨. **LangChain**: `create_tool_calling_agent(llm, tools, prompt)` → AgentExecutor로 실행. 단, LangChain은 추상화 레이어가 두꺼워 디버깅이 어려울 수 있으므로, 직접 SDK 사용 권장.

### 2.3 API/SDK 시그니처

**OpenAI Responses API** (최신):

```python
from openai import OpenAI
client = OpenAI()

tools = [{
    "type": "function",
    "name": "run_orbital_preview",
    "description": "PySCF로 분자의 지정된 오비탈 큐브 데이터를 계산합니다.",
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {
            "smiles": {"type": "string", "description": "분자의 SMILES 문자열"},
            "orbital": {"type": "string", "enum": ["HOMO", "LUMO", "HOMO-1", "LUMO+1"]},
            "basis": {"type": "string", "description": "기저함수 (기본: 6-31G*)"}
        },
        "required": ["smiles", "orbital"],
        "additionalProperties": False
    }
}]

response = client.responses.create(
    model="gpt-5",
    tools=tools,
    input=[{"role": "user", "content": "물분자의 HOMO 보여줘"}],
    stream=True
)

for event in response:
    if event.type == "response.function_call_arguments.delta":
        # 스트리밍 인수 조각
        pass
    elif event.type == "response.output_item.done":
        # 완성된 function_call: event.item.name, event.item.arguments
        pass
```

**Google Gemini API**:

```python
from google import genai
from google.genai import types

client = genai.Client()  # GEMINI_API_KEY 환경변수에서 자동 로드

tools = types.Tool(function_declarations=[{
    "name": "run_orbital_preview",
    "description": "PySCF로 분자의 지정된 오비탈 큐브 데이터를 계산합니다.",
    "parameters": {
        "type": "object",
        "properties": {
            "smiles": {"type": "string"},
            "orbital": {"type": "string", "enum": ["HOMO", "LUMO"]}
        },
        "required": ["smiles", "orbital"]
    }
}])

config = types.GenerateContentConfig(tools=[tools])
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="물분자의 HOMO 보여줘",
    config=config
)
fc = response.candidates[0].content.parts[0].function_call
# fc.name = "run_orbital_preview", fc.args = {"smiles": "O", "orbital": "HOMO"}
```

### 2.4 데이터 포맷 & 파이프라인

WebSocket 메시지 프로토콜 설계:

```json
// 서버 → 클라이언트: LLM 사고 과정 스트리밍
{"type": "llm_thought", "content": "물 분자는 H2O이며..."}

// 서버 → 클라이언트: 도구 실행 시작
{"type": "tool_start", "tool_name": "run_orbital_preview", "args": {"smiles": "O"}}

// 서버 → 클라이언트: 도구 실행 진행 (프로그레스)
{"type": "tool_progress", "tool_name": "run_orbital_preview", "progress": 0.65}

// 서버 → 클라이언트: 도구 실행 완료
{"type": "tool_result", "tool_name": "run_orbital_preview", "result": {
    "cube_url": "/api/cube/abc123",
    "energy_eV": -12.6
}}

// 서버 → 클라이언트: LLM 최종 응답 스트리밍
{"type": "llm_response", "content": "물 분자의 HOMO 오비탈입니다.", "done": false}
{"type": "llm_response", "content": " 에너지는 -12.6 eV입니다.", "done": true}
```

### 2.5 엣지 케이스

LLM 할루시네이션: 존재하지 않는 Tool 이름을 호출하거나 잘못된 파라미터 전달. 대응: `strict: true`(OpenAI) 설정으로 스키마 준수 강제, 알 수 없는 함수명은 에러 메시지로 LLM에 재전달. API Rate Limit: Gemini Flash(무료 15 RPM, 유료 1500 RPM), OpenAI(티어별 상이). 대응: 요청 큐잉 + 지수 백오프. 비용 폭주 방지: `max_tokens` 제한(4096), 단일 요청당 최대 Tool 호출 5회로 제한. 한국어 입력에서 Tool 파라미터 인코딩: UTF-8 완벽 지원(두 SDK 모두), 다만 SMILES 내 한글이 섞이지 않도록 `_extract_structure_query` 전처리 유지.

### 2.6 UX 패턴

스트리밍 타이핑 효과: LLM 응답이 한 글자씩 채팅 버블에 추가됨(typewriter effect). "도구 실행 중..." 인라인 스피너: LLM이 Tool을 호출하면 채팅에 "[🔧 오비탈 계산 중... 65%]" 형태의 진행 표시줄 삽입. 사고 과정 아코디언: "💭 AI의 사고 과정 보기" 클릭 시 펼쳐짐. Quick Chip 제안: LLM 응답 하단에 "LUMO도 볼래요?", "ESP 맵 생성" 등 후속 액션 버튼.

### 2.7 성능

| 모델             | 첫 토큰 지연(TTFT) | 전체 응답 시간 | 비용(1K 토큰) |
| ---------------- | ------------------ | -------------- | ------------- |
| Gemini 2.5 Flash | ~300ms             | ~2s            | 무료/저가     |
| Gemini 2.5 Pro   | ~800ms             | ~5s            | ~$0.003       |
| GPT-4.1          | ~500ms             | ~3s            | ~$0.002       |
| GPT-5            | ~1.5s              | ~8s            | ~$0.01        |

동시 사용자 10명 기준 월 API 비용 추정: Gemini Flash 사용 시 ~$50, GPT-4.1 사용 시 ~$200. WebSocket backpressure: asyncio 큐 크기 제한(100)으로 느린 클라이언트 보호.

### 2.8 경쟁 비교

Cursor: 코드 에디터에 내장된 AI 에이전트, Function Calling + 파일시스템 도구로 코드를 자율 수정. Perplexity: 검색 에이전트, 웹 검색 도구를 자동 호출하여 답변 생성. GitHub Copilot Workspace: 이슈 → 코드 변경 자동 생성. QCViz의 차별점은 양자화학 계산 도구(PySCF)를 LLM의 Tool로 직접 연결한다는 점으로, 과학 도메인 에이전트의 선례가 됨.

### 2.9 학술 표준

해당 없음 (인프라 영역). 다만, LLM이 생성하는 Methods Section의 정확성이 학술 표준에 부합해야 하므로, 시스템 프롬프트에 "계산 방법론은 반드시 실제 사용된 method/basis를 기술하라"는 지침 포함.

### 2.10 의존성 & 라이선스

| 패키지          | 버전 | 라이선스   |
| --------------- | ---- | ---------- |
| `openai`        | ≥1.0 | MIT        |
| `google-genai`  | ≥0.3 | Apache 2.0 |
| `python-dotenv` | ≥1.0 | BSD-3      |

API Key 관리: `.env` 파일 + `python-dotenv`. 프로덕션에서는 HashiCorp Vault 또는 AWS Secrets Manager 권장.

---

## 기능 3: 오비탈 준위도 & 3D 전환 연동

### 3.1 구현 알고리즘

Aufbau 원리에 따른 MO 에너지 정렬. PySCF에서 `mf.mo_energy`는 각 MO의 에너지(Hartree)를 담은 1D ndarray이고, `mf.mo_occ`는 점유 수(RHF: 0 또는 2, UHF: Alpha/Beta 별도). HOMO 인덱스는 `np.where(mf.mo_occ > 0)[0][-1]`, LUMO 인덱스는 `np.where(mf.mo_occ == 0)[0][0]`. Hartree → eV 변환: 1 Hartree = 27.2114 eV.

### 3.2 레퍼런스 구현체

PySCF 직접 접근: `mf.mo_energy`, `mf.mo_occ`, `mf.mo_coeff`. IQmol(GitHub: `nutjunkie/IQmol`)의 MO 에너지 다이어그램, Avogadro 2의 Surfaces 다이얼로그(GitHub: `OpenChemistry/avogadrolibs`). IboView(http://www.iboview.org/)가 가장 세련된 에너지 준위도를 제공.

### 3.3 API/SDK 시그니처

```python
# PySCF MO 정보 추출
mf = mol.RHF().run()
energies = mf.mo_energy        # ndarray, shape (nmo,), in Hartree
occupations = mf.mo_occ        # ndarray, shape (nmo,), 0 or 2
coefficients = mf.mo_coeff     # ndarray, shape (nao, nmo)

# 특정 MO의 큐브 생성
from pyscf.tools import cubegen
cubegen.orbital(mol, f'mo_{i}.cube', mf.mo_coeff[:, i], nx=80, ny=80, nz=80)
```

3Dmol.js 오비탈 전환:

```javascript
// 이전 등치면 제거 + 새 등치면 추가
viewer.removeAllSurfaces();
viewer.removeAllShapes();

var voldata = new $3Dmol.VolumeData(cubeString, "cube");
viewer.addIsosurface(voldata, { isoval: 0.02, color: "blue", opacity: 0.7 });
viewer.addIsosurface(voldata, { isoval: -0.02, color: "red", opacity: 0.7 });
viewer.render();
```

### 3.4 데이터 포맷

```json
{
  "orbitals": [
    {
      "index": 0,
      "energy_eV": -559.2,
      "occ": 2.0,
      "label": "Core 1s",
      "type": "core"
    },
    {
      "index": 4,
      "energy_eV": -12.6,
      "occ": 2.0,
      "label": "HOMO",
      "type": "valence"
    },
    {
      "index": 5,
      "energy_eV": 4.3,
      "occ": 0.0,
      "label": "LUMO",
      "type": "virtual"
    },
    {
      "index": 6,
      "energy_eV": 6.1,
      "occ": 0.0,
      "label": "LUMO+1",
      "type": "virtual"
    }
  ],
  "homo_index": 4,
  "lumo_index": 5,
  "homo_lumo_gap_eV": 16.9
}
```

### 3.5 엣지 케이스

축퇴(Degenerate) 궤도: 동일 에너지의 MO 여러 개가 존재(예: 벤젠의 e1g 궤도 쌍). 에너지 차이 < 0.01 eV인 궤도들은 같은 높이에 병렬로 표시. Core 궤도 필터링: 원자번호 ≤ 2인 원자의 1s 궤도는 에너지가 매우 낮아 스케일을 왜곡하므로, 기본적으로 HOMO-5 ~ LUMO+5 범위만 표시하고 "전체 보기" 토글로 확장. UHF/UKS: Alpha/Beta 스핀을 색상으로 구분(Alpha: 위쪽 화살표 ↑, Beta: 아래쪽 화살표 ↓).

### 3.6 UX 패턴

세로축이 에너지(eV)인 사다리(Ladder) SVG 차트를 우측 패널에 배치. 각 수평선이 하나의 MO를 나타내며, 점유된 MO는 실선, 비점유는 점선. 클릭 시 해당 MO가 하이라이트(두꺼운 선 + 글로우)되고, 메인 Canvas의 3D 오비탈이 페이드인 애니메이션(opacity 0→0.7, 500ms)으로 전환. Shift+Click으로 다중 선택 시 두 오비탈이 서로 다른 색상으로 동시 렌더링. HOMO-LUMO 갭은 양방향 화살표 + 수치(eV)로 표시.

### 3.7 성능

큐브 프리로딩(Prefetch): 초기 계산 시 HOMO-2 ~ LUMO+2 범위의 큐브를 미리 생성하여 캐시. 온디맨드: 그 외 MO는 클릭 시 생성(~1s). 전환 애니메이션: requestAnimationFrame 기반 opacity 트윈, 60fps 안정적.

### 3.8 경쟁 비교

GaussView: MO Editor에서 에너지 수치 표시하나 차트는 아님. Avogadro: Surfaces Dialog에서 MO 선택 가능하나 준위도 없음. IQmol: 가장 나은 에너지 다이어그램 제공하나 웹 기반 아님. Spartan: 상용($800+), 세련된 MO 다이어그램. QCViz 목표: 웹 기반에서 IQmol 수준의 인터랙티브 준위도.

### 3.9 학술 표준

MO 에너지 단위: eV (가장 일반적). 일부 이론화학 논문에서는 Hartree 사용. MO 다이어그램 논문 표기: 수평선 + 화살표(점유), HOMO/LUMO 명확 표시.

### 3.10 의존성

D3.js(BSD-3, SVG 차트) 또는 Chart.js(MIT, Canvas 차트) + 3Dmol.js. D3.js가 SVG 기반이라 커스텀 인터랙션에 더 유연.

---

## 기능 4: IR/Raman 스펙트럼 + 진동 애니메이션

### 4.1 구현 알고리즘

Normal Mode Analysis: Hessian 행렬(에너지의 2차 미분, shape (3N, 3N))을 질량 가중(mass-weighted)으로 변환 후 대각화. 고유값 → 주파수(cm⁻¹), 고유벡터 → 진동 모드 벡터. 수식: `H_mw[i,j] = H[i,j] / sqrt(m_i * m_j)`, `ω = sqrt(λ)` (a.u.), `ν(cm⁻¹) = ω × au2hz / c × 1e-2`. 스케일링 팩터: HF/6-31G* → 0.8929, B3LYP/6-31G* → 0.9614 (NIST CCCBDB 표준). 음의 주파수(Imaginary Frequency): 고유값 λ < 0이면 전이 상태(TS)를 의미. PySCF의 `harmonic_analysis`는 `imaginary_freq=True`로 복소수를 반환하거나, `False`로 음의 실수를 반환.

### 4.2 레퍼런스 구현체

**PySCF hessian** (v2.3+):

```python
from pyscf import gto, scf, hessian
from pyscf.hessian import thermo

mol = gto.M(atom='O 0 0 0; H 0 .757 .587; H 0 -.757 .587', basis='6-31g*')
mf = scf.RHF(mol).run()
hess = mf.Hessian().kernel()                    # shape: (natm, natm, 3, 3)
freq_info = thermo.harmonic_analysis(mol, hess)  # 주파수 + 노멀 모드 반환
thermo_info = thermo.thermo(mf, freq_info['freq_au'], 298.15, 101325)
```

`freq_info` 반환값:

- `freq_wavenumber`: ndarray, 주파수(cm⁻¹)
- `norm_mode`: ndarray, shape (n_modes, natm, 3) — 각 모드에서 각 원자의 변위 벡터
- `reduced_mass`: ndarray, 환원 질량(a.u.)
- `force_const_dyne`: ndarray, 힘 상수(dyne/cm)

### 4.3 API/SDK 시그니처

PySCF `harmonic_analysis` 정확한 시그니처:

```python
pyscf.hessian.thermo.harmonic_analysis(
    mol,                    # Mole 객체
    hess,                   # ndarray shape (natm, natm, 3, 3)
    exclude_trans=True,     # 병진 모드 제거
    exclude_rot=True,       # 회전 모드 제거
    imaginary_freq=True,    # True: 복소수, False: 음의 실수
    mass=None               # 커스텀 질량 (기본: 평균 동위원소 질량)
)
# 반환: dict with keys 'freq_au', 'freq_wavenumber', 'norm_mode', 'reduced_mass', etc.
```

3Dmol.js 진동 애니메이션: 3Dmol.js 자체에는 내장 `vibrate()` 함수가 없으므로, XYZ 멀티프레임 파일을 생성하여 `addModelsAsFrames` + `animate`로 구현합니다.

```javascript
// Normal Mode를 XYZ 프레임으로 변환 (백엔드에서 생성)
// 10프레임: equilibrium ± displacement * sin(2πt/10)
viewer.addModelsAsFrames(xyzMultiframeString, "xyz");
viewer.animate({ loop: "backAndForth", reps: 0, interval: 75 });
viewer.setStyle({}, { stick: {}, sphere: { scale: 0.3 } });
viewer.render();
```

### 4.4 데이터 포맷

```json
{
  "frequencies": [
    {
      "index": 0,
      "cm_inv": 1648.3,
      "intensity_km_mol": 53.2,
      "reduced_mass_amu": 1.08,
      "label": "H-O-H bend",
      "mode": [[0.0, 0.0, 0.0], [0.05, -0.07, 0.0], [-0.05, -0.07, 0.0]],
      "xyz_frames": "<multiframe XYZ string>"
    },
    {
      "index": 1,
      "cm_inv": 3657.1,
      "intensity_km_mol": 8.7,
      "label": "O-H symmetric stretch",
      "mode": [...]
    }
  ],
  "scale_factor": 0.9614,
  "method": "B3LYP/6-31G*"
}
```

### 4.5 엣지 케이스

선형 분자(CO₂, HCN): 3N-5개 진동 모드(비선형은 3N-6). PySCF의 `harmonic_analysis`가 `exclude_rot=True`일 때 자동 처리. 음의 주파수: 전이 상태임을 빨간색으로 표시하고 "⚠ 이 구조는 안정점이 아닙니다(전이 상태 가능)"라는 경고 메시지. 매우 낮은 주파수(<50 cm⁻¹): 대진폭 모드(torsion)는 조화 근사의 한계, 경고 표시. Hessian 수치 미분 소요 시간: 원자 N개에 대해 6N회 단일점 계산이 필요하므로, N > 20이면 수 분 소요. 프로그레스 바로 6N 중 몇 번째인지 표시.

### 4.6 UX 패턴

화면 하단에 Plotly.js 또는 Chart.js로 IR 스펙트럼 차트 배치. X축: 파수(cm⁻¹), 관례에 따라 고→저(왼→오). Y축: 강도(km/mol). 피크에 마우스 호버 시 "3657 cm⁻¹ | O-H stretch" 툴팁. 피크 클릭 → 3D 뷰어에서 해당 진동 모드 애니메이션 재생. 재생/정지 버튼, 진폭 조절 슬라이더, 속도 조절(0.5x~2x).

### 4.7 성능

Hessian 계산 시간 (RHF/6-31G\*): H₂O(3원자) ~2s, 에탄올(9원자) ~30s, 아스피린(21원자) ~5min. 프론트엔드 진동 프레임: 10프레임 XYZ, `animate` interval 75ms → ~13fps, 부드러운 진동.

### 4.8 경쟁 비교

GaussView: 최고의 진동 플레이어(마우스로 화살표 표시 + 애니메이션). Avogadro: 진동 확장 플러그인, 기본 기능. Molden: IR 뷰어 + 진동, 오래된 UI. Jmol: `vibrate` 명령어 내장, 파워풀하나 UI 구식. QCViz 목표: GaussView 수준의 진동 + 웹 기반 인터랙티브 차트.

### 4.9 학술 표준

NIST Chemistry WebBook 표준 주파수와 비교 가능하도록 스케일링 팩터 적용. IR 스펙트럼 X축: 전통적으로 4000→400 cm⁻¹ (고→저). ACS 저널 IR 그래프: Transmittance(%) 또는 Absorbance 단위, X축 반전 관례.

### 4.10 의존성

| 패키지               | 용도            | 라이선스   |
| -------------------- | --------------- | ---------- |
| PySCF hessian        | Hessian 계산    | Apache 2.0 |
| PySCF hessian.thermo | 열화학 분석     | Apache 2.0 |
| Plotly.js            | IR 차트         | MIT        |
| 3Dmol.js             | 진동 애니메이션 | BSD-3      |

---

## 기능 5: NCI Plot (비공유 결합 상호작용)

### 5.1 구현 알고리즘

Johnson et al., "Revealing Noncovalent Interactions", JACS 2010, 132, 6498-6506 (DOI: 10.1021/ja100936w). 핵심 공식:

$$s(\mathbf{r}) = \frac{1}{2(3\pi^2)^{1/3}} \frac{|\nabla\rho(\mathbf{r})|}{\rho(\mathbf{r})^{4/3}}$$

여기서 s는 Reduced Density Gradient (RDG), ρ는 전자 밀도. 비공유 결합 영역에서 RDG는 0에 가까운 트로프(trough)를 형성. 결합 유형 구분: 전자 밀도 Hessian의 두 번째 고유값 sign(λ₂)를 사용 — λ₂ < 0이면 인력(수소결합/vdW), λ₂ > 0이면 척력(입체 장애). 3D 등치면은 RDG = 0.5 (또는 사용자 지정 cutoff)에서 그리고, sign(λ₂)×ρ로 컬러링.

### 5.2 레퍼런스 구현체

**NCIplot** (Contreras-García et al., JCTC 2011, 7, 625; GitHub: `juliacontrerasgarcia/nciplot`): Fortran, standalone. **Multiwfn**: 메인 메뉴 → 옵션 20 (Visual study of weak interaction). **ChemTools** (Python, https://chemtools.org): `from chemtools import NCI; nci = NCI.from_file('wfn.fchk')`. **Critic2** (GitHub: `aoterodelaroza/critic2`): Fortran, NCI 분석 지원. Python 자체 구현 시 PySCF `dft.numint.eval_rho`로 밀도+기울기를 동시에 계산:

```python
from pyscf.dft import numint
ao = mol.eval_gto('GTOval_sph_deriv1', coords)  # shape: (4, ngrids, nao)
rho_and_grad = numint.eval_rho(mol, ao, dm, xctype='GGA')
# rho_and_grad shape: (4, ngrids) or (5, ngrids)
# row 0: ρ, row 1-3: ∂ρ/∂x, ∂ρ/∂y, ∂ρ/∂z
```

### 5.3 API/SDK 시그니처

```python
# PySCF로 밀도 + 기울기 계산
ao_deriv1 = mol.eval_gto('GTOval_sph_deriv1', coords)  # (4, ngrids, nao)
rho_data = numint.eval_rho(mol, ao_deriv1, dm, xctype='GGA')
# rho_data[0] = ρ, rho_data[1:4] = ∇ρ

rho = rho_data[0]
grad_rho = rho_data[1:4]  # (3, ngrids)
abs_grad = np.linalg.norm(grad_rho, axis=0)

# RDG 계산
C = 1.0 / (2.0 * (3.0 * np.pi**2)**(1.0/3.0))
rdg = C * abs_grad / (rho**(4.0/3.0) + 1e-30)  # 1e-30로 0 나누기 방지

# sign(λ₂) 계산을 위한 밀도 Hessian
ao_deriv2 = mol.eval_gto('GTOval_sph_deriv2', coords)  # (10, ngrids, nao)
rho_hess = numint.eval_rho(mol, ao_deriv2, dm, xctype='MGGA')
# Hessian eigenvalue λ₂ 추출은 3×3 행렬 대각화 필요 (격자점마다)
```

### 5.4 데이터 포맷

두 개의 큐브: RDG 큐브 + sign(λ₂)ρ 큐브. 또는 백엔드에서 합성하여 단일 컬러 인코딩 큐브로 전송. 프론트엔드에서 addIsosurface로 RDG 등치면을 그리고, sign(λ₂)ρ 큐브로 컬러링:

```javascript
var rdgVol = new $3Dmol.VolumeData(rdgCube, "cube");
var signLambdaRhoVol = new $3Dmol.VolumeData(signLambda2RhoCube, "cube");
viewer.addIsosurface(rdgVol, {
  isoval: 0.5,
  voldata: signLambdaRhoVol,
  volscheme: { gradient: "rwb", min: -0.04, max: 0.04 },
});
```

### 5.5 엣지 케이스

핵 근처 RDG 특이점: ρ → ∞이면 RDG → 0, 가짜 피크 생성. 해결: ρ > 0.05 a.u. 영역을 마스킹(표준 cutoff). 분자 내(intramolecular) vs 분자 간(intermolecular) 구분: promolecular density(원자 밀도 합)를 사용하면 분자 간만 선택적 표시 가능하나, 정확도 감소. Hessian eigenvalue 계산 비용: 격자점마다 3×3 대각화가 필요해 큰 그리드에서 느림. numpy vectorized 연산으로 최적화.

### 5.6 UX 패턴

색상: 파랑(sign(λ₂)ρ < 0, 수소결합) / 초록(~0, vdW) / 빨강(> 0, 입체 장애). 별도의 2D scatter plot: X축 = sign(λ₂)ρ, Y축 = RDG → 트로프가 보이는 곳에 비공유 결합 존재. RDG cutoff 슬라이더(0.1~1.0): 실시간으로 등치면 두께 조절.

### 5.7 성능

RDG 큐브 계산(80³ 그리드, 물 분자): ~5s. 50+ 원자 분자: ~60s. 최적화: promolecular density 근사 사용 시 SCF 불필요, ~2s.

### 5.8 경쟁 비교

NCIplot standalone: 가장 정확, CLI 전용. Multiwfn: GUI 포함, 완전한 NCI 분석. VMD + NCIplot 파이프라인: 복잡한 설정 필요. QCViz 목표: 웹에서 원클릭 NCI 분석.

### 5.9 학술 표준

Johnson et al. 2010 JACS 원논문 파라미터: RDG cutoff 0.5, density cutoff 0.05 a.u., sign(λ₂)ρ 범위 [-0.04, 0.04] a.u. 이 값들이 학술 커뮤니티의 사실상 표준.

### 5.10 의존성

PySCF dft.numint (Apache 2.0), numpy (BSD-3), 3Dmol.js (BSD-3). 추가 의존성 없음.

---

## 기능 6: IBO/NBO 국소화 궤도

### 6.1 구현 알고리즘

Knizia, "Intrinsic Atomic Orbitals: An Unbiased Bridge between Quantum Theory and Chemical Concepts", JCTC 2013, 9, 4834-4843 (DOI: 10.1021/ct400687b). 2단계 프로세스: (1) IAO(Intrinsic Atomic Orbital) 구축: 최소 기저(MINAO)로의 프로젝션을 통해 물리적 의미가 명확한 원자 궤도를 정의. (2) IBO 국소화: IAO 기반 Mulliken 집단(population)을 최대화하는 Pipek-Mezey 방식의 유니터리 변환. 비용 함수: `Σ_A Σ_i (Q^A_ii)^p` 최대화 (p=4 for IBO, p=2 for PM). Foster-Boys 국소화는 대안으로, 궤도 쌍극자 모멘트 `Σ_i |<i|r|i>|²`를 최대화.

### 6.2 레퍼런스 구현체

**PySCF lo.ibo** (Apache 2.0):

```python
from pyscf import lo
# IAO 생성
orbocc = mf.mo_coeff[:, mf.mo_occ > 0]
iaos = lo.iao.iao(mol, orbocc, minao='minao')

# IBO 국소화
ibo_orbs = lo.ibo.ibo(mol, orbocc, locmethod='IBO', iaos=iaos, exponent=4)
# 반환: ndarray shape (nao, nocc) — 국소화된 MO 계수

# Boys 국소화 (대안)
boys_orbs = lo.Boys(mol, orbocc).kernel()

# Pipek-Mezey 국소화 (대안)
pm_orbs = lo.PipekMezey(mol, orbocc).kernel()
```

**IboView** (http://www.iboview.org/): Gerald Knizia의 공식 IBO 시각화 도구, C++ 기반, 독립 실행형.

### 6.3 API/SDK 시그니처

```python
pyscf.lo.ibo.ibo(
    mol,                    # Mole 객체
    orbocc,                 # ndarray (nao, nocc) — 점유 MO 계수
    locmethod='IBO',        # 'IBO' 또는 'PM'
    iaos=None,              # 미리 계산된 IAO (없으면 자동 생성)
    s=None,                 # 겹침 행렬 (없으면 자동 계산)
    exponent=4,             # PM 국소화 지수 (IBO: 4, classic PM: 2)
    grad_tol=1e-8,          # 수렴 기울기 허용치
    max_iter=200,           # 최대 반복 수
    minao='minao',          # IAO 참조 기저
    verbose=3
)
# 반환: ndarray (nao, nocc) — 국소화된 MO 계수
```

국소화 MO → 큐브 변환:

```python
for i in range(ibo_orbs.shape[1]):
    cubegen.orbital(mol, f'ibo_{i}.cube', ibo_orbs[:, i], nx=80, ny=80, nz=80)
```

### 6.4 데이터 포맷

```json
{
  "ibo_orbitals": [
    {
      "index": 0,
      "label": "O1-H2 σ bond",
      "atom_contributions": { "O1": 0.62, "H2": 0.38 },
      "cube_url": "/api/cube/ibo_0",
      "energy_eV": null
    },
    {
      "index": 1,
      "label": "O1 lone pair",
      "atom_contributions": { "O1": 0.95 },
      "cube_url": "/api/cube/ibo_1"
    }
  ]
}
```

자동 라벨링: 각 IBO에 대해 IAO Mulliken population이 > 0.15인 원자들을 추출하여 "C1-O2 σ bond", "N3 lone pair" 형태로 자동 생성.

### 6.5 엣지 케이스

방향족 π 결합: 벤젠의 경우 IBO가 세 개의 2중심 결합 대신 세 개의 2중심 "바나나 결합"으로 국소화됨 — 화학적으로 타당하지만 직관과 다를 수 있으므로 사용자 안내 필요. 금속 착물: d 궤도가 포함된 경우 IBO 수렴이 느리거나 실패할 수 있음 → `max_iter=500`으로 증가하고, 실패 시 Boys 국소화로 폴백. Core 궤도 분리: IBO는 기본적으로 점유 궤도 전체를 국소화하므로, core 궤도(1s 등)는 원자에 국소화된 상태로 자동 생성됨.

### 6.6 UX 패턴

`[Canonical | Localized (IBO)]` 토글 스위치. IBO 선택 시 좌측 목록이 "HOMO-3, HOMO-2..." 대신 "C1-H5 σ bond, O2 lone pair..."로 변경. 각 항목 클릭 시 3D 뷰어에 해당 IBO 렌더링.

### 6.7 성능

IBO 국소화 반복 계산: H₂O ~0.5s, 에탄올 ~2s, 아스피린 ~10s. 큐브 생성 병렬화: `concurrent.futures.ThreadPoolExecutor`로 여러 IBO 큐브를 동시 생성.

### 6.8 경쟁 비교

NBO7: $800+, Gaussian 연동 전용, 가장 완전한 NBO 분석. IboView: 무료, IBO의 원저자 도구, 시각적으로 우수하나 독립 실행형. Multiwfn: Boys/PM/IBO 모두 지원, GUI 포함. QCViz 목표: 웹에서 IboView 수준의 IBO 시각화.

### 6.9 학술 표준

Knizia 2013 원논문 권장: exponent=4, minao='MINAO' 기저. NBO vs IBO 비교 문헌: Knizia & Klein, Angew. Chem. Int. Ed. 2015, 54, 5518.

### 6.10 의존성

PySCF lo 모듈 (Apache 2.0), PySCF tools.cubegen (Apache 2.0). 추가 의존성 없음.

---

## 기능 7: 원클릭 논문 리포트 (PDF Export)

### 7.1 구현 알고리즘

3D 뷰어 스크린샷 → HTML 템플릿 삽입 → PDF 변환. 3Dmol.js의 래스터화: `viewer.pngURI({width, height})` 메서드가 WebGL Canvas의 현재 상태를 PNG data URI로 반환. HTML → PDF 변환 엔진 선택지: WeasyPrint(Python 네이티브, CSS Paged Media 지원, JS 미실행), Playwright(Chromium headless, 완벽한 CSS/JS 렌더링, 무거움).

### 7.2 레퍼런스 구현체

**WeasyPrint** (BSD-3): `from weasyprint import HTML; HTML(string=html_str).write_pdf('report.pdf')`. **Playwright** (Apache 2.0): `from playwright.sync_api import sync_playwright; page.pdf(path='report.pdf', format='A4')`. 3Dmol.js 캡처: `viewer.pngURI({width: 4096, height: 4096, transparent: true})` → base64 PNG.

### 7.3 API/SDK 시그니처

```javascript
// 프론트엔드: 3D 뷰어 캡처
const pngDataUri = viewer.pngURI({
  width: 4096,
  height: 4096,
  transparent: true,
});
// pngDataUri = "data:image/png;base64,iVBOR..."

// WebSocket으로 서버에 전송
ws.send(
  JSON.stringify({
    type: "export_report",
    image_data: pngDataUri,
    format: "ACS",
    include_methods: true,
  }),
);
```

```python
# 백엔드: WeasyPrint로 PDF 생성
from weasyprint import HTML
from jinja2 import Template

template = Template(open('report_template.html').read())
html = template.render(
    image_base64=image_data,
    energy=result['total_energy'],
    method="RHF/6-31G*",
    molecule_name="Water",
    charges=result['mulliken_charges']
)
pdf_bytes = HTML(string=html).write_pdf()
```

### 7.4 데이터 포맷

Jinja2 HTML 템플릿에 삽입할 데이터 JSON:

```json
{
  "molecule_name": "Water (H2O)",
  "method": "B3LYP/6-31G*",
  "total_energy_hartree": -76.408357,
  "homo_energy_eV": -10.35,
  "lumo_energy_eV": 0.89,
  "dipole_moment_debye": 2.16,
  "mulliken_charges": [
    { "atom": "O1", "charge": -0.67 },
    { "atom": "H2", "charge": 0.33 }
  ],
  "image_base64": "data:image/png;base64,...",
  "style": "ACS"
}
```

### 7.5 엣지 케이스

WebGL 컨텍스트 없는 서버사이드에서는 3D 캡처 불가 → 클라이언트에서 캡처 후 서버로 전송하는 방식 필수. 한국어/유니코드 폰트: WeasyPrint에 Noto Sans KR 폰트를 CSS `@font-face`로 지정. 4K 이미지 크기: ~2-5MB, PDF에 삽입 시 최종 PDF 크기 5-10MB.

### 7.6 UX 패턴

[📄 Export Report] 버튼 클릭 → 모달 열림 → 템플릿 선택(ACS/RSC/Nature) + 로고 업로드(선택) + 저자명 입력 → [Generate] → 프리뷰 → [Download PDF].

### 7.7 성능

WeasyPrint PDF 생성: ~1-3s (단일 페이지). Playwright: ~3-5s (Chromium 초기화 포함). 이미지 후처리(Pillow 리사이즈): ~0.5s.

### 7.8 경쟁 비교

Spartan: 내장 리포트 기능이나 커스텀 불가. GaussView: "Save As" PNG만 가능, PDF 없음. ORCA: 텍스트 출력만 제공. QCViz 목표: 논문에 바로 삽입 가능한 퀄리티의 자동 리포트.

### 7.9 학술 표준

ACS Author Guidelines: Figure 해상도 최소 300 DPI, 폭 3.25 inch(single)/7 inch(double), TIFF/EPS 권장(PNG도 허용). RSC: 최소 600 DPI for line art. Nature: 폭 89mm(single) 또는 183mm(double), 최소 300 DPI.

### 7.10 의존성

| 패키지            | 라이선스   | 참고                |
| ----------------- | ---------- | ------------------- |
| WeasyPrint        | BSD-3      | 경량, JS 미지원     |
| Jinja2            | BSD-3      | 템플릿 엔진         |
| Pillow            | HPND       | 이미지 후처리       |
| (선택) Playwright | Apache 2.0 | 완벽 렌더링, 무거움 |

---

## 기능 8: Command Palette (Cmd+K)

### 8.1 구현 알고리즘

Fuzzy search: Bitap 알고리즘(Fuse.js 내장). 문자열 근사 매칭으로 "ㅎㅇㅌㄷ"가 "하이라이트 토글"을 매칭하지는 못하지만, "hmo"가 "Show HOMO"를 매칭. 한국어 초성 검색 지원을 위해서는 별도의 초성 추출 함수(`getChosung`)를 구현하여 검색 키에 추가. 명령어 랭킹: 최근 사용 빈도(recency × frequency) 기반 가중치.

### 8.2 레퍼런스 구현체

**cmdk** (React, MIT): `github.com/dip/cmdk`. React 전용이므로 Vanilla JS 프로젝트에는 부적합. **ninja-keys** (Web Component, MIT): `github.com/nicknisi/ninja-keys`. Web Component 기반으로 프레임워크 무관. **command-pal** (Vanilla JS, MIT): `github.com/nicholasgasior/command-pal`. QCViz는 Vanilla JS이므로 ninja-keys 또는 자체 구현 권장.

### 8.3 API/SDK 시그니처

Fuse.js (Apache 2.0):

```javascript
import Fuse from "fuse.js";

const commands = [
  {
    id: "show-homo",
    label: "HOMO 보기",
    category: "Orbital",
    action: () => showOrbital("HOMO"),
  },
  {
    id: "set-opacity-50",
    label: "투명도 50%",
    category: "View",
    action: () => setOpacity(0.5),
  },
  {
    id: "bg-black",
    label: "배경 검은색",
    category: "View",
    action: () => setBg("black"),
  },
  {
    id: "export-csv",
    label: "CSV 다운로드",
    category: "Export",
    action: () => exportCSV(),
  },
];

const fuse = new Fuse(commands, {
  keys: ["label", "category"],
  threshold: 0.4, // 0.0=완전일치, 1.0=모두 매칭
  distance: 100,
  includeScore: true,
});

// 사용
const results = fuse.search("투명");
// → [{item: {id: 'set-opacity-50', label: '투명도 50%', ...}, score: 0.12}]
```

### 8.4 데이터 포맷

```json
{
  "commands": [
    {
      "id": "show-homo",
      "label": "HOMO 보기",
      "label_en": "Show HOMO",
      "category": "Orbital",
      "shortcut": "H",
      "icon": "🔵"
    },
    {
      "id": "show-lumo",
      "label": "LUMO 보기",
      "label_en": "Show LUMO",
      "category": "Orbital",
      "shortcut": "L",
      "icon": "🔴"
    },
    {
      "id": "run-esp",
      "label": "ESP 맵 생성",
      "label_en": "Generate ESP Map",
      "category": "Calculate",
      "icon": "🌈"
    },
    {
      "id": "toggle-bg",
      "label": "배경 토글",
      "label_en": "Toggle Background",
      "category": "View",
      "icon": "🎨"
    }
  ]
}
```

### 8.5 엣지 케이스

한국어 초성 검색: Fuse.js 기본으로는 미지원. 커스텀 전처리로 각 command의 label에서 초성을 추출하여 별도 `chosung` 필드 추가 후 검색 키에 포함. 명령어 충돌: 동일 단축키 방지를 위해 충돌 감지 로직. 포커스 트랩: 모달 열린 동안 Tab 키가 모달 내에서만 순환.

### 8.6 UX 패턴

Cmd+K (Mac) / Ctrl+K (Win) → 화면 중앙에 반투명 오버레이 + 검색 입력란. 타이핑 즉시 아래에 필터링된 명령어 목록 표시. 카테고리별 그룹 헤더(Orbital, View, Calculate, Export). 키보드 ↑↓로 선택, Enter로 실행, Esc로 닫기. 최근 사용 명령어가 상단에 "최근" 섹션으로 표시.

### 8.7 성능

Fuse.js로 500개 명령어 검색 시 < 5ms (60fps 유지 충분). DOM 업데이트는 Virtual DOM이 아닌 innerHTML 직접 교체로도 16ms 이내.

### 8.8 경쟁 비교

VS Code: 가장 성숙한 Command Palette. Notion, Figma, Linear: SaaS 표준으로 자리잡음. 과학 소프트웨어에서 Command Palette를 제공하는 도구는 현재 없음 → QCViz의 독특한 차별점.

### 8.9 학술 표준

해당 없음.

### 8.10 의존성

| 패키지            | 라이선스   |
| ----------------- | ---------- |
| Fuse.js           | Apache 2.0 |
| (선택) ninja-keys | MIT        |

또는 Vanilla JS로 자체 구현(의존성 0).

---

## 기능 9: 멀티 뷰어 동기화 비교 모드

### 9.1 구현 알고리즘

3Dmol.js `linkViewer(otherViewer)` 메서드가 핵심. 이 메서드는 한 뷰어의 view matrix가 변경될 때마다 다른 뷰어에 동일한 view를 자동 적용. 내부적으로 `getView()` → `[pos.x, pos.y, pos.z, rotationGroup.position.z, q.x, q.y, q.z, q.w]` 배열을 반환하고, `setView(view)` 로 적용. 동일 컬러 스케일 강제: 두 분자의 ESP 범위 중 더 넓은 범위를 공유하여 정량적 비교 가능.

### 9.2 레퍼런스 구현체

3Dmol.js 공식 API: `viewer1.linkViewer(viewer2)` — viewer1을 돌리면 viewer2도 동기화. NGL Viewer(GitHub: `nglviewer/ngl`)의 synced stages, Mol\*의 split view도 참조 가능하나 3Dmol.js가 QCViz 기반이므로 직접 활용.

### 9.3 API/SDK 시그니처

```javascript
// 두 개의 뷰어 인스턴스 생성
const viewer1 = $3Dmol.createViewer("viewer-left", {
  backgroundColor: "white",
});
const viewer2 = $3Dmol.createViewer("viewer-right", {
  backgroundColor: "white",
});

// 양방향 동기화
viewer1.linkViewer(viewer2);
viewer2.linkViewer(viewer1);

// 카메라 상태 수동 동기화 (linkViewer 미사용 시)
viewer1.getView();
// → [x, y, z, zoom, qx, qy, qz, qw]
viewer2.setView(viewer1.getView());
```

### 9.4 데이터 포맷

```json
{
  "type": "compare_request",
  "molecules": [
    { "name": "에탄올", "smiles": "CCO", "visualization": "esp" },
    { "name": "아세트산", "smiles": "CC(=O)O", "visualization": "esp" }
  ],
  "sync_camera": true,
  "shared_color_range": true
}
```

### 9.5 엣지 케이스

크기가 매우 다른 두 분자(H₂ vs 단백질): 줌 레벨 동기화 시 작은 분자가 보이지 않을 수 있음. 해결: 각 뷰어를 독립적으로 `zoomTo()` 후 회전만 동기화하는 모드 제공. 하나만 계산 완료 시: 완료된 쪽만 표시, 다른 쪽에 로딩 스피너.

### 9.6 UX 패턴

"비교 모드" 버튼 클릭 → 화면 좌우 분할(CSS Grid `grid-template-columns: 1fr 1fr`). 수직/수평 분할 선택 드롭다운. 경계선 드래그로 비율 조절. 동기화 on/off 토글. 각 뷰어 상단에 분자명 라벨.

### 9.7 성능

두 개의 WebGL 컨텍스트: 대부분의 현대 GPU에서 문제 없음. 단, 각각 100³ 큐브 두 개를 동시에 렌더링하면 GPU 메모리 ~500MB 사용. requestAnimationFrame 동기화: linkViewer가 내부적으로 처리.

### 9.8 경쟁 비교

GaussView: 다중 창 지원, 독립적 회전. Avogadro: 탭 기반, 동시 비교 불가. IQmol: 단일 뷰어. UCSF Chimera: split view 지원, 단 웹 기반 아님. QCViz 목표: 웹에서 Chimera 수준의 비교 모드.

### 9.9 학술 표준

논문 side-by-side figure: 동일 앵글, 동일 컬러 범위, 동일 스케일이 필수. QCViz의 동기화 모드가 이를 자동으로 보장.

### 9.10 의존성

3Dmol.js (BSD-3)만 필요. CSS Grid/Flexbox는 브라우저 내장.

---

## 기능 10: 세션 공유 & 협업

### 10.1 구현 알고리즘

상태 직렬화(Serialization): 뷰어 카메라 상태(`getView()`) + 슬라이더 값(ISO/Opacity) + 활성 오비탈 인덱스 + 채팅 히스토리 + 큐브 데이터 참조(URL)를 하나의 JSON으로 패킹. UUID v4로 고유 세션 ID 생성. 상태 JSON을 SQLite(개발용) 또는 Redis(프로덕션)에 저장. 큐브 파일은 별도 파일 시스템(로컬 `/data/cubes/` 또는 S3)에 저장하고 JSON에는 URL만 포함.

### 10.2 레퍼런스 구현체

Figma의 URL 기반 상태 공유, Excalidraw(GitHub: `excalidraw/excalidraw`)의 공유 링크 구현, CodeSandbox의 URL 상태 인코딩.

### 10.3 API/SDK 시그니처

```python
# FastAPI 라우트
@router.post("/api/session/save")
async def save_session(state: SessionState) -> dict:
    session_id = str(uuid.uuid4())[:8]
    # state를 JSON으로 직렬화하여 SQLite에 저장
    db.execute("INSERT INTO sessions (id, state, created_at, expires_at) VALUES (?, ?, ?, ?)",
               (session_id, state.json(), datetime.now(), datetime.now() + timedelta(days=7)))
    return {"session_id": session_id, "url": f"/session/{session_id}"}

@router.get("/api/session/{session_id}")
async def load_session(session_id: str) -> SessionState:
    row = db.execute("SELECT state FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Session not found or expired")
    return json.loads(row[0])
```

```javascript
// 프론트엔드: 세션 저장
async function saveSession() {
  const state = {
    camera: viewer.getView(),
    sliders: { iso: isoSlider.value, opacity: opacitySlider.value },
    color_scheme: currentColorScheme,
    active_orbital: currentOrbitalIndex,
    chat_history: chatMessages,
    cube_refs: loadedCubeUrls,
  };
  const res = await fetch("/api/session/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(state),
  });
  const { url } = await res.json();
  navigator.clipboard.writeText(window.location.origin + url);
  alert("링크가 복사되었습니다!");
}
```

### 10.4 데이터 포맷

```json
{
  "session_id": "a1b2c3d4",
  "created_at": "2026-03-08T16:00:00Z",
  "expires_at": "2026-03-15T16:00:00Z",
  "state": {
    "camera": [0, 0, 0, -150, 0, 0, 0, 1],
    "sliders": { "iso": 0.02, "opacity": 0.8 },
    "color_scheme": "RWB",
    "active_orbital": 4,
    "molecule": { "smiles": "O", "name": "water" },
    "calculation": { "method": "RHF", "basis": "6-31G*" },
    "chat_history": [
      { "role": "user", "content": "물분자 HOMO 보여줘" },
      { "role": "assistant", "content": "물 분자의 HOMO 오비탈입니다..." }
    ],
    "cube_refs": ["/data/cubes/abc123_homo.cube"]
  }
}
```

### 10.5 엣지 케이스

큐브 파일 용량: 80³ 큐브 ~4MB 텍스트, gzip 시 ~500KB. 세션에 큐브가 5개면 ~2.5MB. 세션 만료 정책: 기본 7일, 연장 가능. 동시 편집 충돌: V1에서는 읽기 전용 공유만 지원(편집 불가), V2에서 실시간 협업(WebSocket 기반 CRDT) 고려.

### 10.6 UX 패턴

"🔗 링크 복사" 버튼 → 클립보드에 URL 복사. 공유 시 "읽기 전용" 모드로 열림(슬라이더 조작 가능하나 새 계산 불가). QR코드 생성(qrcode.js). 만료 시간 표시("이 세션은 7일 후 만료됩니다").

### 10.7 성능

세션 로딩 시간: 상태 JSON ~10KB (즉시) + 큐브 데이터 ~2MB (gzip, ~1s on 100Mbps). CDN(CloudFront/Cloudflare) 캐싱으로 큐브 로딩 가속.

### 10.8 경쟁 비교

과학 소프트웨어에서 URL 기반 세션 공유를 제공하는 도구는 현재 없음. Figma/Google Docs의 패러다임을 과학 도구에 최초로 도입하는 것이 QCViz의 킬러 피처.

### 10.9 학술 표준

해당 없음.

### 10.10 의존성

| 패키지          | 라이선스      |
| --------------- | ------------- |
| SQLite (stdlib) | Public Domain |
| (선택) Redis    | BSD-3         |
| uuid (stdlib)   | Python stdlib |
| gzip (stdlib)   | Python stdlib |

---

## 종합 의존성 매트릭스

| 패키지        | 버전   | 라이선스   | 사용 기능          | 상용 가능 |
| ------------- | ------ | ---------- | ------------------ | --------- |
| PySCF         | ≥2.3   | Apache 2.0 | 모든 계산          | ✅        |
| numpy         | ≥1.21  | BSD-3      | 배열 연산          | ✅        |
| 3Dmol.js      | ≥2.0   | BSD-3      | 모든 3D 렌더링     | ✅        |
| FastAPI       | ≥0.100 | MIT        | 웹 서버            | ✅        |
| openai        | ≥1.0   | MIT        | LLM Agent          | ✅        |
| google-genai  | ≥0.3   | Apache 2.0 | LLM Agent (Gemini) | ✅        |
| Fuse.js       | ≥7.0   | Apache 2.0 | Command Palette    | ✅        |
| Plotly.js     | ≥2.0   | MIT        | IR 차트            | ✅        |
| WeasyPrint    | ≥60    | BSD-3      | PDF 리포트         | ✅        |
| Jinja2        | ≥3.0   | BSD-3      | 리포트 템플릿      | ✅        |
| D3.js         | ≥7.0   | ISC        | 오비탈 준위도      | ✅        |
| python-dotenv | ≥1.0   | BSD-3      | API Key 관리       | ✅        |

**모든 의존성이 허용적 라이선스(Apache 2.0, MIT, BSD-3)로 상용화에 법적 장애 없음.**

---

## GPT에게 전달할 통합 전수조사 요약 프롬프트

이 전수조사 보고서 전체를 GPT/LLM에게 전달할 때는 다음 요약을 함께 첨부하면 즉시 맥락을 파악할 수 있습니다:

> **핵심 API 시그니처 요약:**
>
> - PySCF cubegen: `density(mol, outfile, dm, nx, ny, nz)`, `mep(mol, outfile, dm, nx, ny, nz)`, `orbital(mol, outfile, coeff, nx, ny, nz)` — 모두 `numpy.ndarray (nx, ny, nz)` 반환
> - PySCF hessian: `mf.Hessian().kernel()` → shape (natm, natm, 3, 3), `thermo.harmonic_analysis(mol, hess)` → dict with `freq_wavenumber`, `norm_mode` (n_modes, natm, 3)
> - PySCF IBO: `lo.ibo.ibo(mol, orbocc, locmethod='IBO')` → ndarray (nao, nocc)
> - 3Dmol.js 등치면: `viewer.addIsosurface(voldata, {isoval, color, opacity, voldata, volscheme})`
> - 3Dmol.js 동기화: `viewer1.linkViewer(viewer2)`
> - 3Dmol.js 캡처: `viewer.pngURI({width, height, transparent})`
> - 3Dmol.js 애니메이션: `viewer.addModelsAsFrames(xyz, "xyz")` + `viewer.animate({loop, reps, interval})`
> - OpenAI Tool: `{"type": "function", "name": "...", "parameters": {...}, "strict": true}`
> - Gemini Tool: `types.Tool(function_declarations=[{...}])`, `client.models.generate_content(model, contents, config)`
> - ESP Auto-Fit: 0.001 a.u. 등밀도면 마스킹 → 2nd/98th percentile → 대칭 범위
> - NCI Plot: RDG = |∇ρ| / (2(3π²)^(1/3) ρ^(4/3)), sign(λ₂)ρ로 컬러링

# QCViz-MCP Enterprise V2 — 50억 달러 마스터 플랜

> **프로젝트**: 양자화학 시각화 MCP 서버 (Quantum Chemistry Visualization MCP Server)
> **목표**: 일반 실험 연구자가 CLI/터미널 지식 없이, 브라우저 하나로 자연어 입력만으로 양자화학 계산·시각화·분석을 수행하는 완전한 엔터프라이즈급 SaaS
> **작성일**: 2026-03-09
> **아키텍처**: FastAPI + PySCF + 3Dmol.js + WebSocket + LLM (Gemini/OpenAI) Function Calling

---

## 목차

1. [현재 상태 진단 및 해결된 버그](#1-현재-상태-진단-및-해결된-버그)
2. [핵심 아키텍처 전환: Rule-based → Embedded AI Agent](#2-핵심-아키텍처-전환-rule-based--embedded-ai-agent)
3. [수정 대상 파일 목록](#3-수정-대상-파일-목록)
4. [ESP 컬러 스킴 10종 + Auto-Fit 알고리즘](#4-esp-컬러-스킴-10종--auto-fit-알고리즘)
5. [Multiwfn/GaussView 전수조사 기반 고급 기능](#5-multiwfngaussview-전수조사-기반-고급-기능)
6. [AI Copilot 기반 Generative 워크플로우](#6-ai-copilot-기반-generative-워크플로우)
7. [3D 뷰어 & UI 고도화 (V1 기능 복원 포함)](#7-3d-뷰어--ui-고도화-v1-기능-복원-포함)
8. [양자화학 파이프라인 Backend 고도화](#8-양자화학-파이프라인-backend-고도화)
9. [엔터프라이즈급 협업 및 생산성](#9-엔터프라이즈급-협업-및-생산성)
10. [극강의 UX/DX (최신 SaaS 수준)](#10-극강의-uxdx-최신-saas-수준)
11. [GPT/LLM에게 전달할 작업 지시서 템플릿](#11-gptllm에게-전달할-작업-지시서-템플릿)
12. [구현 우선순위 로드맵](#12-구현-우선순위-로드맵)

---

## 1. 현재 상태 진단 및 해결된 버그

### 버그 A: `JobManager.submit signature unsupported`

- **증상**: WebSocket 채팅 요청 시 `RuntimeError: JobManager.submit() got an unexpected keyword argument 'intent_name'` 발생
- **원인**: `chat.py`의 `_jm_submit` 헬퍼 함수가 시도하는 `jm.submit(...)` 호출 방식이 실제 `JobManager.submit`의 시그니처(`target`, `kwargs`, `label`, `name`, `func`)와 불일치
- **조치**: `chat.py`와 `compute.py` 양쪽의 `_jm_submit` 헬퍼 함수 내 시도 목록(attempts 배열)을 실제 `JobManager` 시그니처와 100% 호환되도록 전면 재정의

```python
# 수정된 attempts 배열 (chat.py & compute.py 동일)
attempts = [
    lambda: jm.submit(fn=fn, kwargs=kwargs, name=name, metadata=metadata),
    lambda: jm.submit(func=fn, kwargs=kwargs, name=name, metadata=metadata),
    lambda: jm.submit(target=fn, kwargs=kwargs, name=name, metadata=metadata),
    lambda: jm.submit(fn, kwargs=kwargs, name=name, metadata=metadata),
    lambda: jm.submit(target=fn, kwargs=kwargs, label=name),
    lambda: jm.submit(func=fn, kwargs=kwargs, name=name),
    lambda: jm.submit(fn, kwargs=kwargs, name=name),
    lambda: jm.submit(fn, kwargs=kwargs, label=name),
    lambda: jm.submit(fn, name=name, metadata=metadata, **kwargs),
    lambda: jm.submit(fn, **kwargs),
]
```

### 버그 B: PubChem 404 — 분자명 파싱 오류

- **증상**: "물분자 분석"을 입력하면 `ValueError: 분자 이름 '물분자 분석'을(를) SMILES로 변환하지 못했습니다: HTTP Error 404: PUGREST.NotFound`
- **원인**: `_extract_structure_query` 함수의 정규식 필터링 목록에 "분석", "분석해줘" 등의 한국어 동사/명사 패턴이 누락되어, "물분자 분석" 전체가 PubChem에 그대로 전송됨
- **조치**: `chat.py`와 `compute.py`의 `_extract_structure_query` 정규식 목록에 `r"분석해줘"`, `r"분석"` 패턴 추가

### 버그 C: 프로그레스 바 / 실시간 로그 미표시

- **증상**: 계산이 진행 중인데 프론트엔드에 아무런 피드백(Progress Bar, 로그)이 없음
- **원인**: `index.html`에 "Live Job Monitor" 패널이 추가되었으나, `chat.js`에서 해당 패널을 조작하는 `_renderJobProgress` 함수가 누락됨
- **조치**: `chat.js`에 Live Job Monitor 실시간 렌더링 함수(`_renderJobProgress`)를 삽입하고, WebSocket Job Update 이벤트와 즉각 연동

---

## 2. 핵심 아키텍처 전환: Rule-based → Embedded AI Agent

### 현재 (Rule-based)

```
사용자 입력 → 정규식(_infer_intent) → 키워드 매칭 → 하드코딩된 함수 실행
```

- 한계: "물분자 분석해줘" 같은 자연스러운 표현에 취약, 오류 복구 불가, 문맥 이해 없음

### 목표 (Embedded AI Agent)

```
사용자 입력 → LLM (Gemini/OpenAI API) → Function Calling으로 도구 선택
           → pyscf_runner.py 실행 → 결과를 LLM이 해석 → 자연어 응답 + 3D 시각화
```

- 장점: 자연어 이해, 문맥 기반 오류 자동 복구, 다단계 추론, 사용자 맞춤 설명

### 핵심 설계 원칙

1. **사용자는 Gemini CLI를 모른다**: 웹 브라우저(localhost:8000)만 열면 끝
2. **uvicorn이 올라가면 AI가 자동 로드**: 서버 시작과 동시에 LLM 클라이언트가 초기화
3. **Function Calling 에이전트 루프**: LLM이 백엔드 도구(`run_orbital_preview`, `run_esp_map` 등)를 자율적으로 호출
4. **스트리밍 응답**: LLM의 사고 과정, 도구 실행 상태, 최종 답변이 WebSocket으로 실시간 중계

---

## 3. 수정 대상 파일 목록

| #   | 파일 경로                                            | 현재 역할 (Rule-based)                                    | 업그레이드 목표 (LLM Function Calling)                                                                 | 수정 규모 |
| --- | ---------------------------------------------------- | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | --------- |
| 1   | `version02/src/qcviz_mcp/web/routes/chat.py`         | 정규식(`_infer_intent`)으로 의도 파악, 하드코딩 함수 실행 | **[핵심]** 정규식 삭제 → LLM SDK 연동, Tool Call 가로채기 → pyscf_runner 실행, 에이전트 루프 전면 개편 | 🔴 높음   |
| 2   | `version02/src/qcviz_mcp/config.py` (또는 `app.py`)  | 서버 포트 등 기본 환경설정                                | `GEMINI_API_KEY` / `OPENAI_API_KEY` 등 LLM 인증 키를 `.env`에서 안전하게 로드                          | 🟢 낮음   |
| 3   | `version02/src/qcviz_mcp/compute/pyscf_runner.py`    | 백그라운드 계산 후 dict 반환                              | 로직 자체 수정 불필요. 단, LLM이 도구(Tool)로 인식할 수 있도록 **Docstring + Pydantic 스키마** 보강    | 🟡 보통   |
| 4   | `version02/src/qcviz_mcp/web/static/chat.js`         | 하드코딩된 시스템 메시지 수신                             | LLM 자연어 **스트리밍** 렌더링, "계산 도구 실행 중..." 상태 처리, UI 로직 확장                         | 🟡 보통   |
| 5   | `version02/requirements.txt` (또는 `pyproject.toml`) | PySCF, FastAPI 등 기본 패키지                             | `google-genai`, `openai`, `langchain` 등 LLM 통신 라이브러리 추가                                      | 🟢 낮음   |

---

## 4. ESP 컬러 스킴 10종 + Auto-Fit 알고리즘

### 4.1 컬러 스킴 프리셋 (10종)

| #   | 이름                     | 용도/특징                      | 색상 구성                                         |
| --- | ------------------------ | ------------------------------ | ------------------------------------------------- |
| 1   | **RWB (Red-White-Blue)** | 기본 / 교과서 표준             | 빨강(+) → 흰색(0) → 파랑(-)                       |
| 2   | **BWR (Blue-White-Red)** | 물리화학 관습 (부호 반전)      | 파랑(-) → 흰색(0) → 빨강(+)                       |
| 3   | **Viridis**              | 색맹 친화적 / Nature 저널 권장 | 보라 → 청록 → 노랑                                |
| 4   | **Inferno**              | 고대비 / 어두운 배경용         | 검정 → 자주 → 주황 → 노랑                         |
| 5   | **Spectral**             | 무지개 전체 범위               | 빨강 → 주황 → 노랑 → 초록 → 파랑                  |
| 6   | **Nature Style**         | Nature Chemistry 논문 스타일   | 짙은 파랑 → 연한 시안 → 흰색 → 연분홍 → 짙은 빨강 |
| 7   | **ACS Style**            | JACS / ACS 계열 저널 스타일    | 남색 → 흰색 → 진홍                                |
| 8   | **RSC Style**            | RSC 계열 저널 스타일           | 에메랄드 → 흰색 → 마젠타                          |
| 9   | **Greyscale**            | 흑백 인쇄 / 접근성용           | 검정 → 회색 → 흰색                                |
| 10  | **High Contrast**        | 발표 자료 / 프로젝터용         | 진한 오렌지(+) → 검정(0) → 진한 시안(-)           |

### 4.2 ESP Auto-Fit 알고리즘 (Multiwfn 방식 기반)

**전수조사 결과 요약:**

- **GaussView**: 메쉬 표면의 절대 Min/Max를 그대로 컬러 범위로 사용. 핵(Nuclei) 근처 특이점 때문에 화면이 옅어지는 문제 있음. 0이 중성을 의미하지 않을 수 있어 학술적 오독 유발.
- **Multiwfn**: 0.001 a.u. 등밀도 표면(van der Waals surface) 상의 ESP를 스캔하여, 0을 중앙으로 대칭 매핑. 학술적으로 가장 신뢰할 수 있는 방식.
- **Avogadro**: 단순 Min/Max 기반으로 GaussView과 유사한 한계.

**QCViz 구현 알고리즘 (Robust Symmetric Scaling):**

```python
import numpy as np

def compute_esp_auto_range(density_cube: np.ndarray, potential_cube: np.ndarray) -> float:
    """
    Multiwfn 방식 기반의 ESP 자동 범위 설정.
    0.001 a.u. 등밀도 표면에서 ESP 값을 스캔하고,
    상/하위 극단값 2%를 버린 뒤 대칭 범위를 계산.
    """
    # Step 1: 표면 근처 복셀(Voxel) 격리 (0.001 a.u. ± 10%)
    surface_mask = (density_cube >= 0.0009) & (density_cube <= 0.0011)

    # Step 2: 표면에서의 ESP 값 추출
    surface_potentials = potential_cube[surface_mask]

    if len(surface_potentials) == 0:
        # Fallback: 전체 큐브의 절대 최대값 사용
        return float(np.max(np.abs(potential_cube)))

    # Step 3: Outlier Rejection (2nd / 98th percentile)
    p2 = np.percentile(surface_potentials, 2)
    p98 = np.percentile(surface_potentials, 98)

    # Step 4: 대칭 범위 결정 (0이 항상 중앙)
    v_max = max(abs(p2), abs(p98))

    return float(v_max)
```

**효과**: 어떤 분자든 컬러 스케일의 중앙이 항상 0(전기적 중성)을 의미하게 되어, 서로 다른 분자 간 정량적 시각 비교가 가능해짐.

---

## 5. Multiwfn/GaussView 전수조사 기반 고급 기능

상용/학술 표준 도구들의 핵심 알고리즘과 엣지 기능을 QCViz에 이식합니다.

### 5.1 정량적 표면 임계점 (Quantitative Surface Critical Points)

- **출처**: Multiwfn의 "surface analysis" 모듈
- **기능**: 분자 표면에서 국소 최대점($V_{s,max}$, 시그마홀/할로겐 결합 예측)과 최소점($V_{s,min}$, 친핵성 공격 사이트)의 3D 좌표와 수치(kcal/mol)를 자동 계산
- **UX**: 3D 뷰어에서 해당 위치에 "+32 kcal/mol" 같은 부유(Floating) 텍스트 라벨이 자동으로 표시됨

### 5.2 분자 극성 지수 대시보드 (MPI / Polarity Statistics)

- **출처**: Multiwfn의 ESP statistics 기능
- **기능**: 전체 표면적 중 양전하/음전하 비율, 분산도(Variance), 평균 양/음 전위를 계산
- **UX**: 우측 패널에 도넛 차트 + 숫자 카드로 한눈에 표시

### 5.3 내부 단면 썰어보기 (Clipping Plane)

- **출처**: GaussView, ChemCraft의 Slab/Clipping 기능
- **기능**: 3Dmol.js의 `viewer.setSlab()` API를 슬라이더에 연결하여, ESP/MO 표면을 사과 썰듯이 단면으로 잘라 내부 노드(Node) 구조를 관찰
- **UX**: 툴바에 슬라이더 추가, 드래그하면 실시간으로 단면이 이동

### 5.4 NCI Plot (Non-Covalent Interactions)

- **출처**: Multiwfn / NCIplot 프로그램
- **기능**: 감소된 밀도 기울기(RDG) 큐브를 계산하여 수소 결합(파랑), 반데르발스 인력(초록), 입체 장애(빨강)를 얇은 등치면으로 시각화
- **용도**: 신약 개발 시 단백질-리간드 결합 분석의 킬러 기능

### 5.5 AIM (Atoms in Molecules) 위상 분석

- **출처**: Bader 분석, Multiwfn의 topology analysis
- **기능**: 전자 밀도의 기울기 장(Gradient Field)을 분석하여 진짜 화학 결합 경로(Bond Path)와 결합 임계점(BCP)을 추출
- **UX**: 점선과 작은 구체로 수소 결합 등 비공유 결합의 존재 유무를 3D 공간에 표시

### 5.6 전자 밀도 차이 맵 (Δρ Difference Map)

- **출처**: GaussView, Multiwfn의 density difference 기능
- **기능**: 두 상태(바닥 상태 vs 들뜬 상태, 중성 vs 이온 등)의 밀도 큐브를 빼서 전자 이동(Charge Transfer)을 시각화
- **UX**: 빨강(전자 감소) ↔ 파랑(전자 증가) 등치면으로 어디서 어디로 전자가 흘렀는지 직관적으로 표현

---

## 6. AI Copilot 기반 Generative 워크플로우

### 6.1 대화형 에러 복구 (Conversational Auto-Healing)

- **상황**: PySCF 계산이 SCF 수렴에 실패 (연구자들이 가장 좌절하는 상황)
- **기능**: 단순 에러 출력이 아니라, LLM이 에러 로그를 분석한 뒤 "SCF 수렴에 실패했습니다. 전이 금속이 포함되어 있어 `def2-SVP` 기저 함수와 Level Shift를 적용하여 재시도할까요?"라고 제안하고 [예/아니오] Quick Chip 버튼 표시
- **구현**: LLM의 Function Calling 응답에 `retry_with_options` 도구를 추가

### 6.2 텍스트 기반 분자 편집 (Prompt-to-Edit)

- **상황**: 벤젠 구조를 띄워놓고 치환기를 바꾸고 싶을 때
- **기능**: "파라(para) 위치의 수소를 하이드록시기(-OH)로 바꿔줘"라고 타이핑하면, LLM이 RDKit 백엔드를 통해 SMILES를 조작하고 즉시 3D 뷰어에 반영
- **구현**: `edit_molecule` Tool 함수를 RDKit 연동으로 구현

### 6.3 자연어 쿼리 필터링 (Semantic Data Extraction)

- **기능**: 거대한 JSON 결과에서 "쌍극자 모멘트가 가장 큰 원자 쌍이 뭐야?"라고 물으면 LLM이 표(Table) 형태로 추출하여 응답
- **구현**: LLM이 계산 결과 JSON을 컨텍스트로 받고 자연어 쿼리에 답변

### 6.4 하이라이트 & 내러티브 뷰어 (Narrative Storytelling)

- **기능**: LLM이 계산 결과를 설명할 때, 텍스트 내 특정 단어(예: "산소 원자의 음전하")를 클릭하면 3D 뷰어의 카메라가 해당 원자로 자동 줌인 + 하이라이트
- **구현**: LLM 응답에 `<atom-link atom-id="O1">산소 원자</atom-link>` 같은 시맨틱 태그를 포함시키고, `chat.js`에서 클릭 이벤트 바인딩

---

## 7. 3D 뷰어 & UI 고도화 (V1 기능 복원 포함)

### 7.1 동적 오비탈 준위도 (Interactive Energy Level Diagram)

- 단순 Chip 버튼 나열 → 실제 에너지 준위 **사다리(Ladder) 차트**로 시각화
- 준위 선(Line)을 클릭하면 메인 Canvas의 3D 오비탈이 **페이드인/아웃** 애니메이션으로 전환
- "LUMO+1과 HOMO-1 겹쳐서 보여줘"라고 타이핑하면 두 오비탈이 다른 색상으로 동시 렌더링

### 7.2 ISO/Opacity 슬라이더 실시간 바인딩

- `requestAnimationFrame` + **Debounce** 기법 적용
- 슬라이더 조작 시 **120fps급** 초스무스 실시간 렌더링 갱신
- 툴바에 ISO값, Opacity값 숫자 표시 (현재값 확인 가능)

### 7.3 분자 + 오비탈 동시 렌더링 (Canvas 통합)

- 분자 구조(Ball-and-Stick)와 오비탈 등치면이 **같은 Canvas**에 겹쳐서 렌더링
- 투명도 조절로 분자 뼈대를 통해 오비탈의 양/음 위상을 관찰

### 7.4 Spin Density 맵

- UHF/UKS 계산 시 Alpha-Beta 전자의 Spin 밀도 큐브 렌더링
- V1의 고급 시각화 옵션 복원

### 7.5 원자 호버 툴팁 (Contextual Hover Insights)

- 3D 분자 위에 마우스를 올리면(Hover), 클릭하지 않아도 원자 이름, 부분 전하(Mulliken Charge), 좌표가 담긴 반투명 툴팁이 마우스를 따라다님
- 3Dmol.js의 `hover` 콜백 활용

---

## 8. 양자화학 파이프라인 Backend 고도화

### 8.1 IBO (Intrinsic Bond Orbitals) 국소화

- PySCF 내장 IBO/Foster-Boys 국소화 메서드 활용
- UI에 "Orbital Type" 토글 추가: `[ Canonical | Localized (IBO) ]`
- 국소화 궤도는 자동으로 특정 결합(예: "C1-H2 Sigma Bond")에 매핑

### 8.2 진동 주파수 애니메이션 (IR/Raman Vibration)

- Geometry Optimization 후 Hessian 계산으로 Normal Mode 추출
- 화면 하단에 IR 스펙트럼 그래프(Plotly/Chart.js)
- **피크 클릭 → 3D 분자가 해당 진동 모드로 애니메이션** (3Dmol.js `vibrate()`)

### 8.3 IRC (Intrinsic Reaction Coordinate) 타임라인 플레이어

- 전이 상태(TS) 경로 계산 후 유튜브 스타일 슬라이더 바 제공
- 재생(Play)하면 반응물 → 전이 상태 → 생성물로 원자들이 스무스하게 이동

### 8.4 거대 분자 대응 (Smart Resolution)

- 원자 수에 따라 동적으로 `cube_grid_size`를 자동 조절(Down-Sampling)
- 100+ 원자 시스템에서도 브라우저가 터지지 않도록 보호

### 8.5 멀티 뷰어 동기화 비교 모드 (Split-screen Compare)

- "에탄올과 아세트산의 ESP 맵 비교해줘" → 화면 좌우 분할
- 카메라 동기화(Sync): 한 쪽을 돌리면 다른 쪽도 동일 각도로 회전

---

## 9. 엔터프라이즈급 협업 및 생산성

### 9.1 원클릭 리포트 제너레이터 (Publication-Ready Export)

- [Export PDF] 버튼 → 현재 3D 뷰어 앵글 그대로 **4K 투명 배경 PNG** 캡처
- AI가 작성한 **Methods Section** (계산 방법론) + 에너지/전하 데이터 표
- 연구실/회사 로고가 박힌 브랜딩 PDF 리포트 즉시 다운로드
- ACS/RSC/Nature 스타일 논문 포맷 선택 가능

### 9.2 세션 URL 공유 (Shareable Workspace State)

- 계산 큐브, 슬라이더 값(ISO/Opacity), 채팅 내역을 Session ID로 DB/캐시에 저장
- `https://.../session/xyz123` 링크를 동료에게 공유하면, 동일한 화면 상태로 즉시 접속
- Slack/Teams 연동 가능

### 9.3 백그라운드 큐 / 알림 시스템 (Async Job & Webhooks)

- 100+ 원자 시스템의 장시간 계산 시, "계산 완료 시 이메일/Slack 알림 받기" 체크박스 제공
- 창을 닫아도 `JobManager`가 계산을 완료하면 알림 발송
- 웹훅(Webhook) URL 설정으로 외부 시스템과 연동

### 9.4 히스토리 타임라인 (Time-travel Undo/Redo)

- 좌측에 Git 커밋 히스토리처럼 작업 타임라인 표시
- 과거 시점을 클릭하면 해당 당시의 분자 구조와 결과 화면으로 즉시 롤백

---

## 10. 극강의 UX/DX (최신 SaaS 수준)

### 10.1 Command Palette (Cmd+K / Ctrl+K)

- 화면 어디서든 Cmd+K → 중앙 검색창
- "HOMO 보기", "투명도 50%", "배경 검은색", "CSV 다운로드" 등 단축 명령을 타이핑만으로 실행
- 마우스 의존도 대폭 감소

### 10.2 2D 분자 구조 드로잉 보드 (SMILES/XYZ 양방향 컨버터)

- JSME 또는 Ketcher 등 2D 분자 에디터를 화면에 내장
- 사용자가 2D로 분자를 그리면 → RDKit/OpenBabel로 3D 좌표 자동 변환 → 즉시 계산 시작

### 10.3 다국어 지원 (i18n)

- 한국어, 영어, 일본어, 중국어 전환 가능
- AI 응답도 선택한 언어로 자동 번역

### 10.4 접근성 (Accessibility)

- 색맹 친화적 컬러 스킴 기본 제공 (Viridis 등)
- 키보드 네비게이션 완전 지원
- 스크린 리더 호환 ARIA 레이블

---

## 11. GPT/LLM에게 전달할 작업 지시서 템플릿

아래 텍스트를 복사하여 GPT-5.4 등 강력한 LLM에게 전달하면, 정확한 맥락을 파악하고 엔터프라이즈급 코드를 생성할 수 있습니다.

---

> ### [시스템 컨텍스트 및 작업 지시서]
>
> **프로젝트명**: QCViz-MCP (양자화학 시각화 MCP 서버)
> **기술 스택**: Python FastAPI + PySCF + 3Dmol.js + WebSocket + HTML/CSS/JS
> **현재 상태**: 웹의 채팅창(`chat.py`)이 정규식(RegEx) 기반 Rule-based 챗봇으로 동작 중
>
> ### [목표]
>
> 일반 실험 연구자들이 CLI 없이, 웹 UI에 자연어만 입력하면 "내장된 AI(Embedded LLM)"가 파악하여 백엔드의 양자화학 계산 도구를 자율적으로 실행하고, 결과를 3D로 시각화해주는 완전한 SaaS 형태의 에이전트로 업그레이드.
>
> ### [요구 사항]
>
> 1. `chat.py`의 정규식 파싱 로직을 걷어내고, LLM (OpenAI 또는 Gemini API) 기반의 **Function Calling (Tool Use) 에이전트 루프**로 전면 재설계
> 2. LLM이 사용할 수 있도록 `pyscf_runner.py` 내의 함수들(`run_single_point`, `run_orbital_preview`, `run_esp_map` 등)을 **Tool Schema**로 랩핑
> 3. 계산이 오래 걸리므로 FastAPI의 **WebSocket**을 통해 LLM의 사고 과정(Thought), 도구 실행 상태(Tool execution), 자연어 응답 스트리밍을 프론트엔드(`chat.js`)로 우아하게 중계하는 로직 작성
> 4. ESP 컬러 스킴 10종(RWB, Viridis, Inferno, Spectral, Nature, ACS, RSC, Material Dark, Greyscale, High Contrast) 프리셋 내장
> 5. ESP Auto-Fit 알고리즘 (Multiwfn 방식: 0.001 a.u. 등밀도 표면 기반 Robust Symmetric Scaling) 백엔드 구현
> 6. 오비탈 준위도 클릭 → 3D 뷰어 오비탈 전환, ISO/Opacity 슬라이더 실시간 바인딩
> 7. 코드의 견고함(Error Handling)과 확장성을 유지하는 엔터프라이즈급 아키텍처
>
> ### [수정 대상 파일]
>
> - `version02/src/qcviz_mcp/web/routes/chat.py` (핵심, 전면 개편)
> - `version02/src/qcviz_mcp/config.py` (API Key 로드 추가)
> - `version02/src/qcviz_mcp/compute/pyscf_runner.py` (Docstring/Schema 보강)
> - `version02/src/qcviz_mcp/web/static/chat.js` (스트리밍 렌더링 확장)
> - `version02/requirements.txt` (LLM 라이브러리 추가)

---

## 12. 구현 우선순위 로드맵

### Phase 1: 즉시 임팩트 (1~3일)

| 우선순위 | 기능                          | 이유                                      |
| -------- | ----------------------------- | ----------------------------------------- |
| ⭐⭐⭐   | ESP Robust Auto-Fit 알고리즘  | 백엔드 5줄 추가로 시각화 퀄리티 수직 상승 |
| ⭐⭐⭐   | ESP 컬러 스킴 10종 프리셋     | 프론트 드롭다운 하나로 논문급 결과물      |
| ⭐⭐⭐   | ISO/Opacity 슬라이더 Debounce | 사용감 즉시 체감 향상                     |

### Phase 2: 핵심 전환 (1~2주)

| 우선순위 | 기능                                     | 이유                          |
| -------- | ---------------------------------------- | ----------------------------- |
| ⭐⭐⭐   | Embedded AI Agent (LLM Function Calling) | 프로젝트의 근본적 가치 전환   |
| ⭐⭐     | 오비탈 준위도 클릭 ↔ 3D 전환 연동        | "Wow" 팩터, 직관적 탐색       |
| ⭐⭐     | 대화형 에러 복구 (Self-Healing)          | 연구자 좌절 방지, 리텐션 핵심 |

### Phase 3: 경쟁 우위 (2~4주)

| 우선순위 | 기능                                    | 이유                                          |
| -------- | --------------------------------------- | --------------------------------------------- |
| ⭐⭐     | IR 스펙트럼 피크 클릭 → 진동 애니메이션 | 3Dmol.js 내장 기능으로 빠른 구현, 높은 임팩트 |
| ⭐⭐     | IBO 국소화 궤도                         | PySCF 내장 메서드 활용, 해석 직관성 극대화    |
| ⭐⭐     | 멀티 뷰어 동기화 비교 모드              | 논문 작성 킬러 기능                           |
| ⭐       | NCI Plot / AIM 위상 분석                | 신약 개발 B2B 시장 진입 키                    |

### Phase 4: 엔터프라이즈 완성 (1~2개월)

| 우선순위 | 기능                     | 이유                     |
| -------- | ------------------------ | ------------------------ |
| ⭐⭐     | 원클릭 논문 리포트 (PDF) | 유료 전환 핵심 기능      |
| ⭐       | Command Palette (Cmd+K)  | 파워 유저 리텐션         |
| ⭐       | 세션 URL 공유            | 팀 협업 → 바이럴 성장    |
| ⭐       | IRC 반응 경로 애니메이션 | 고급 연구 시장 차별화    |
| ⭐       | Δρ 전자 밀도 차이 맵     | 전하 이동 분석 전문 기능 |

---

## 부록: 현재 프로젝트 파일 구조

```
version02/src/qcviz_mcp/
├── compute/
│   ├── job_manager.py          # 백그라운드 작업 관리 (ThreadPoolExecutor)
│   └── pyscf_runner.py         # PySCF 양자화학 계산 엔진
├── tools/
│   └── core.py                 # MoleculeResolver (PubChem/SMILES), MCP 도구 정의
├── web/
│   ├── advisor_flow.py         # Advisor 워크플로우
│   ├── app.py                  # FastAPI 앱 초기화
│   ├── routes/
│   │   ├── chat.py             # 💡 WebSocket 채팅 라우트 (핵심 수정 대상)
│   │   └── compute.py          # REST 계산 API 라우트
│   └── static/
│       ├── index.html          # 메인 SPA 페이지
│       ├── chat.js             # 채팅 UI 로직
│       ├── viewer.js           # 3Dmol.js 3D 뷰어 제어
│       ├── results.js          # 결과 렌더링
│       └── style.css           # 전체 스타일시트 (63KB)
├── config.py                   # 환경설정
└── requirements.txt            # 의존성 패키지
```

---

> **이 문서는 QCViz-MCP 프로젝트의 전체 고도화 계획을 담은 마스터 플랜입니다.**

전체를 고도화하고 오류없이 구현하고 나의 목적이 달성되도록 50억달러 짜리 프로젝트를 완수하라
전체를 고도화하고 오류없이 구현하고 나의 목적이 달성되도록 50억달러 짜리 프로젝트를 완수하라
전체를 고도화하고 오류없이 구현하고 나의 목적이 달성되도록 50억달러 짜리 프로젝트를 완수하라
전체를 고도화하고 오류없이 구현하고 나의 목적이 달성되도록 50억달러 짜리 프로젝트를 완수하라
전체를 고도화하고 오류없이 구현하고 나의 목적이 달성되도록 50억달러 짜리 프로젝트를 완수하라
전체를 고도화하고 오류없이 구현하고 나의 목적이 달성되도록 50억달러 짜리 프로젝트를 완수하라
전체를 고도화하고 오류없이 구현하고 나의 목적이 달성되도록 50억달러 짜리 프로젝트를 완수하라
전체를 고도화하고 오류없이 구현하고 나의 목적이 달성되도록 50억달러 짜리 프로젝트를 완수하라
전체를 고도화하고 오류없이 구현하고 나의 목적이 달성되도록 50억달러 짜리 프로젝트를 완수하라
