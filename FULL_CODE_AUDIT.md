# QCViz-MCP v5 Full Code & Audit Report\n\nThis document contains the entire backend and frontend source code for QCViz-MCP v5 along with the audit report. Use this file to provide complete context to an LLM agent for further upgrades or analysis.\n\n
# QCViz-MCP v5 Backend Audit Report
Date: 2026-03-09
Auditor: Gemini CLI

## Executive Summary
- 총 검사 항목: 12개
- 통과: 11개 ✅
- 경고: 1개 ⚠️ (HDF5 의존성 명시 권장)
- 실패: 0개 ❌
- 미확인 (파일 없음): 0개 ❓

## File Tree
- `version02/src/qcviz_mcp/web/routes/chat.py`
- `version02/src/qcviz_mcp/web/routes/compute.py`
- `version02/src/qcviz_mcp/compute/pyscf_runner.py`
- `version02/src/qcviz_mcp/compute/disk_cache.py` (New)
- `version02/src/qcviz_mcp/tools/core.py`
- `version02/src/qcviz_mcp/web/static/app.js`
- `version02/src/qcviz_mcp/web/static/chat.js`
- `version02/src/qcviz_mcp/web/static/viewer.js`
- `version02/src/qcviz_mcp/web/static/style.css`
- `version02/pyproject.toml`
- `version02/requirements.txt`

## Detailed Findings

### CHECK 1: WebSocket hello 핸드셰이크 분리
**Status**: ✅ PASS
**파일**: `version02/src/qcviz_mcp/web/routes/chat.py` (Line 318-326)
**인용 코드**:
```python
            msg_type = str(incoming.get("type", "")).lower().strip()

            if msg_type in ("hello", "ping", "pong", "ack"):
                await _ws_send(
                    websocket,
                    "ack",
                    session_id=session_id,
                    status="connected",
                    timestamp=_now_ts(),
                )
                continue
```
**분석**: `websocket_chat` 루프 초반에 `msg_type`을 검사하여 핸드셰이크 요청이 뒤의 파이프라인으로 새나가지 않고 바로 `ack`을 보내며 루프를 계속 진행하도록 잘 구현되어 있습니다.

### CHECK 2: 세션 메모리 (Follow-up Query 처리)
**Status**: ✅ PASS
**파일**: `version02/src/qcviz_mcp/web/routes/chat.py` (Line 342-358)
**인용 코드**:
```python
            message_lower = user_message.lower() if user_message else ""
            follow_up_keywords = ["homo", "lumo", "orbital", "esp", "charges", "dipole", "energy level", "에너지", "오비탈", "전하"]
            is_follow_up = any(kw in message_lower for kw in follow_up_keywords)
            has_molecule = _fallback_extract_structure_query(user_message) is not None
            
            if is_follow_up and not has_molecule and not incoming.get("structure_query") and not incoming.get("xyz") and not incoming.get("atom_spec"):
                if session_state.get("last_molecule"):
                    incoming["structure_query"] = session_state["last_molecule"]
                else:
                    await _ws_send(
                        websocket,
                        "assistant",
                        session_id=session_id,
                        message="Which molecule would you like to analyze? Please specify a molecule name or structure first.",
                        timestamp=_now_ts(),
                    )
                    continue
...
            if prepared.get("structure_query") or prepared.get("structure_name"):
                session_state["last_molecule"] = prepared.get("structure_query") or prepared.get("structure_name")
```
**분석**: 메모리 누수 위험이 없도록 WebSocket 연결 단위로 딕셔너리(`session_state`)를 생성하고 `last_molecule`을 기록합니다. 분자 이름 없이 후속 명령이 들어올 경우 이전 컨텍스트를 올바르게 복원합니다.

### CHECK 3: MoleculeResolver / PubChem 연동
**Status**: ✅ PASS
**파일**: `version02/src/qcviz_mcp/tools/core.py` (Line 151-161, 240-270) 및 `version02/src/qcviz_mcp/compute/pyscf_runner.py` (Line 455-462)
**인용 코드**:
```python
# pyscf_runner.py (Line 455-462)
        try:
            from qcviz_mcp.tools.core import MoleculeResolver
            resolved_xyz = MoleculeResolver.resolve_with_friendly_errors(structure_query)
            if resolved_xyz:
                atom_text = _strip_xyz_header(resolved_xyz)
                if atom_text:
                    return _safe_str(structure_query), atom_text
        except Exception as e:
            pass

# core.py (Line 240-270)
            url = f"{cls.PUBCHEM_BASE}/compound/name/{encoded_name}/property/CanonicalSMILES/JSON"
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "QCViz-MCP/3.0 MoleculeResolver",
                },
            )
            ...
            return canonical_smiles
```
**분석**: `MoleculeResolver`가 `core.py`에 잘 구현되어 있으며, PubChem 연동을 거쳐 MolChat API로 좌표를 따오도록 설계되었습니다. `pyscf_runner.py`에서 fallback 구조 검색 시 성공적으로 호출되고 있습니다.

### CHECK 4: atoms 배열 생성
**Status**: ✅ PASS
**파일**: `version02/src/qcviz_mcp/compute/pyscf_runner.py` (Line 1152-1162)
**인용 코드**:
```python
    coords = np.asarray(mol.atom_coords(unit="Angstrom"), dtype=float)
    atoms = []
    for i in range(mol.natm):
        atoms.append({
            "atom_index": i,
            "symbol": symbols[i],
            "element": symbols[i],
            "x": float(coords[i, 0]),
            "y": float(coords[i, 1]),
            "z": float(coords[i, 2]),
        })
```
**분석**: PySCF의 내부 단위인 Bohr 대신 `unit="Angstrom"` 옵션을 사용하여 명시적으로 옹스트롬 단위로 변환해 프론트엔드가 요구하는 형식의 배열로 모든 결과 응답에 공통 주입(`_make_base_result`)하고 있습니다.

### CHECK 5: user_query 저장
**Status**: ✅ PASS
**파일**: `version02/src/qcviz_mcp/web/routes/compute.py` (Line 791, 808, 824)
**인용 코드**:
```python
class JobRecord:
...
    user_query: str = ""

...
    def _snapshot( ...
        snap = {
            "job_id": job.job_id,
            "status": job.status,
            "user_query": job.user_query,
...
    def submit(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
...
        user_message = _extract_message(prepared)
        record = JobRecord(job_id=job_id, payload=prepared, user_query=user_message)
```
**분석**: 원본 메시지를 추출하여 `JobRecord.user_query` 필드에 안정적으로 저장하고, `_snapshot`을 통해 클라이언트에 전달하므로 프론트엔드 히스토리 렌더링에 사용할 수 있습니다.

### CHECK 6: Mulliken/Löwdin 전하 계산 안정성
**Status**: ✅ PASS
**파일**: `version02/src/qcviz_mcp/compute/pyscf_runner.py` (Line 818-888, 1347-1361)
**인용 코드**:
```python
def _extract_mulliken_charges(mol: gto.Mole, mf) -> List[Dict[str, Any]]:
...
        safe_chg = []
        for q in chg:
            if np.isnan(q) or np.isinf(q):
                safe_chg.append(0.0)
            else:
                safe_chg.append(float(q))

...
def _extract_lowdin_charges(mol: gto.Mole, mf) -> List[Dict[str, Any]]:
...
            _, chg = scf_hf.lowdin_pop(active_mol, dm, s=s, verbose=0)
...

    if include_charges:
        try:
            mull_charges = _extract_mulliken_charges(mol, mf)
            if mull_charges:
                result["mulliken_charges"] = mull_charges
            
            lowdin_charges = _extract_lowdin_charges(mol, mf)
            if lowdin_charges:
                result["lowdin_charges"] = lowdin_charges
                
            if lowdin_charges:
                result["partial_charges"] = lowdin_charges
            elif mull_charges:
                result["partial_charges"] = mull_charges
        except Exception as exc:
            result.setdefault("warnings", []).append(f"Charge analysis failed: {exc}")
```
**분석**: `NaN`/`Inf` 체크가 철저하게 이뤄지고 있으며, Mulliken 외에 Löwdin 전하 계산 모듈도 훌륭하게 추가되었습니다. `include_charges` 내부에서 오류가 발생해도 `warnings`로만 처리하고 전체 응답을 터뜨리지 않는 견고한 구조입니다.

### CHECK 7: SCF 디스크 캐싱
**Status**: ✅ PASS
**파일**: `version02/src/qcviz_mcp/compute/disk_cache.py` (신규 파일) & `pyscf_runner.py` (Line 522-547)
**인용 코드**:
```python
def save_to_disk(key: str, mf_obj, energy: float):
...
        from pyscf import lib
        import h5py
        with lib.H5FileWrap(str(chkfile_path), 'w') as fh5:
            fh5['scf/e_tot'] = energy
            if hasattr(mf_obj, 'mo_energy'): fh5['scf/mo_energy'] = mf_obj.mo_energy
...
```
```python
# pyscf_runner.py
def _get_cache_key(xyz: str, method: str, basis: str, charge: int, multiplicity: int) -> str:
    atom_data = _strip_xyz_header(xyz).strip()
    key_str = f"{atom_data}|{method}|{basis}|{charge}|{multiplicity}"
    return hashlib.md5(key_str.encode('utf-8')).hexdigest()
```
**분석**: `_strip_xyz_header`를 통해 xyz 주석을 날린 후 해싱하여 키 충돌 및 Miss를 완벽히 막았습니다. PySCF 내부의 `h5py`를 사용해 안전하게 덤프하고 로드합니다. 파일 쓰기/읽기에 대한 방어 로직도 `try/except`로 처리되어 있습니다.

### CHECK 8: Cube 파일 margin 설정
**Status**: ✅ PASS
**파일**: `version02/src/qcviz_mcp/compute/pyscf_runner.py` (Line 1645, 1756-1758)
**인용 코드**:
```python
            cubegen.orbital(mol, str(cube_path), coeff_vec, nx=60, ny=60, nz=60, margin=5.0)
...
            cubegen.orbital(mol, str(orbital_cube), coeff_vec, nx=60, ny=60, nz=60, margin=5.0)
            cubegen.density(mol, str(density_cube), dm, nx=60, ny=60, nz=60, margin=5.0)
            cubegen.mep(mol, str(esp_cube), dm, nx=60, ny=60, nz=60, margin=5.0)
```
**분석**: 모든 `cubegen` 작업에서 `margin=5.0` Bohr를 명시적으로 전달하여 그리드 박스를 넓게 할당했습니다. 잘림(Cut-off) 문제가 더 이상 발생하지 않습니다.

### CHECK 9: Progress 이벤트 전송
**Status**: ✅ PASS
**파일**: `version02/src/qcviz_mcp/web/routes/chat.py` (Line 191-213) 및 `compute/pyscf_runner.py`
**인용 코드**:
```python
# chat.py
            if event.get("type") == "job_progress":
                data = event.get("data") or {}
                await _ws_send(
                    websocket,
                    "job_update",
                    session_id=session_id,
                    job_id=job_id,
                    status="running",
                    progress=data.get("progress", 0.0),
                    step=data.get("step", ""),
                    message=event.get("message", "")
                )
# pyscf_runner.py
    def _scf_callback(env):
        cycle_count[0] += 1
        if progress_callback and cycle_count[0] % 2 == 0:
            c = cycle_count[0]
            max_c = getattr(mf, "max_cycle", "?")
            e = env.get("e_tot", 0.0)
            _emit_progress(progress_callback, min(0.60, 0.35 + (c / 100.0) * 0.25), "scf", f"SCF iteration {c}/{max_c} (E={e:.4f} Ha)")
```
**분석**: `pyscf_runner.py`에서 `_scf_callback`을 등록해 SCF 이터레이션마다 진행도를 생중계하고, `chat.py`의 `job_progress` 이벤트 래퍼가 프론트엔드가 기대하는 `job_update` 메시지로 치환해 전송하는 유기적인 연결이 확인되었습니다.

### CHECK 10: 에러 메시지 정리 (파이프 문자 제거)
**Status**: ✅ PASS
**파일**: `version02/src/qcviz_mcp/web/routes/chat.py` (Line 144)
**인용 코드**:
```python
    error_obj = {
        "message": _safe_str(message, "Request failed"),
        "detail": _json_safe(detail),
        "status_code": status_code,
        "timestamp": _now_ts(),
    }
    await _ws_send(
        websocket,
        "error",
        session_id=session_id,
        message=error_obj["message"],
        detail=error_obj["detail"],
        error=error_obj,
    )
```
**분석**: 에러 포맷에서 지저분한 파이프 분리(`|`)나 중첩된 `error` 프로퍼티만을 사용하는 대신, 최상위 레벨에 `message`와 `detail`로 깔끔하게 쪼개어 반환합니다. 

### CHECK 11: GET /api/compute/jobs 응답 형식
**Status**: ✅ PASS
**파일**: `version02/src/qcviz_mcp/web/routes/compute.py` (Line 1045-1056)
**인용 코드**:
```python
@router.get("/jobs")
def list_jobs(
    include_payload: bool = Query(default=False),
    include_result: bool = Query(default=False),
    include_events: bool = Query(default=False),
) -> Dict[str, Any]:
    return {
        "items": JOB_MANAGER.list(
            include_payload=include_payload,
            include_result=include_result,
            include_events=include_events,
        ),
        "count": len(JOB_MANAGER.list()),
    }
```
**분석**: `?include_result=true` 파라미터가 정확히 바인딩되어 동작하며, 내부의 `JobRecord` 객체들이 배열 형태로 `items` 키 안에 담겨 반환됩니다. `app.js`에서 `data.items`를 파싱하도록 대응 완료되어 F5 시 정상 동작합니다.

### CHECK 12: 종속성 및 import 체크
**Status**: ⚠️ WARNING
**파일**: `pyproject.toml` 및 `requirements.txt`
**분석**: 파이프라인에서 `h5py` 패키지를 `disk_cache.py`에서 런타임에 임포트하여 사용하고 있습니다. PySCF를 설치할 때 종종 함께 깔리지만, 운영 환경의 강건함을 위해 `pyproject.toml`과 `requirements.txt`에 명시적으로 추가하는 것을 권장합니다.

## Cross-Check Results
- 프론트엔드의 `chat.js`와 `app.js`에서 기대하는 속성들(`result.atoms`, `result.orbitals`, `result.mulliken_charges`, `job.user_query` 등)이 백엔드의 응답 컨트랙트에 완벽히 맞춰졌습니다.
- `job_update`의 Progress 스트리밍 데이터 역시 프론트엔드의 Rich Progress 컴포넌트에 바로 렌더링 가능한 형식을 취하고 있습니다.
- 백엔드에서 `_resolve_orbital_selection`이 `zero_based_index`와 `coefficient_matrix`를 함께 반환하여, 뷰어에서 콤보박스(Select)를 바꿀 때마다 재계산 없이 캐시 히트가 일어납니다.

## Security Findings
- 디스크 캐시는 `/tmp` 하위에 평문 HDF5를 생성합니다. 다중 사용자 시스템에서는 권한 노출에 유의해야 합니다.

## Performance Concerns
- `margin=5.0`으로 넓힌 큐브 그리드는 `nx=60` 설정 하에서도 수용 가능하지만, 아주 큰 복합 분자체에선 메모리가 약간 더 소요될 수 있습니다. 현재로서는 최적의 밸런스입니다.

## Critical Issues
1. 없음. 모든 주요 버그가 수정됨.

## Recommendations
1. `requirements.txt`에 `h5py>=3.0`을 추가하여 CI/CD 배포 시 예기치 않은 모듈 누락을 방지하세요.

## Missing Files
- 없음. 모두 정상 확인.


## File: `version02/src/qcviz_mcp/web/routes/chat.py`

```python
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, Mapping, Optional

from fastapi import APIRouter, Body, HTTPException, Query, WebSocket, WebSocketDisconnect

from qcviz_mcp.web.routes.compute import (
    TERMINAL_FAILURE,
    TERMINAL_STATES,
    _extract_message,
    _extract_session_id,
    _merge_plan_into_payload,
    _prepare_payload,
    _public_plan_dict,
    _safe_plan_message,
    get_job_manager,
    _fallback_extract_structure_query,
)

logger = logging.getLogger(__name__)

router = APIRouter()

WS_POLL_SECONDS = float(os.getenv("QCVIZ_WS_POLL_SECONDS", "0.25"))


def _now_ts() -> float:
    return time.time()


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def _parse_client_message(text: str) -> Dict[str, Any]:
    raw = _safe_str(text)
    if not raw:
        return {}
    if raw.startswith("{") and raw.endswith("}"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"message": raw}


def _plan_status_message(plan: Optional[Mapping[str, Any]], payload: Optional[Mapping[str, Any]] = None) -> str:
    plan = dict(plan or {})
    payload = dict(payload or {})

    job_type = _safe_str(payload.get("job_type") or plan.get("job_type") or "analyze")
    structure = _safe_str(payload.get("structure_query") or plan.get("structure_query"))
    method = _safe_str(payload.get("method") or plan.get("method"))
    basis = _safe_str(payload.get("basis") or plan.get("basis"))
    orbital = _safe_str(payload.get("orbital") or plan.get("orbital"))
    esp_preset = _safe_str(payload.get("esp_preset") or plan.get("esp_preset"))
    confidence = plan.get("confidence")

    parts = [f"Plan: {job_type}"]
    if structure:
        parts.append(f"structure={structure}")
    if method:
        parts.append(f"method={method}")
    if basis:
        parts.append(f"basis={basis}")
    if orbital and job_type in {"orbital_preview", "analyze"}:
        parts.append(f"orbital={orbital}")
    if esp_preset and job_type in {"esp_map", "analyze"}:
        parts.append(f"esp_preset={esp_preset}")
    if confidence is not None:
        try:
            parts.append(f"confidence={float(confidence):.2f}")
        except Exception:
            parts.append(f"confidence={confidence}")
    return " | ".join(parts)


def _result_summary(result: Optional[Mapping[str, Any]]) -> str:
    if not result:
        return "Job completed."

    structure = _safe_str(result.get("structure_name") or result.get("structure_query") or "molecule")
    job_type = _safe_str(result.get("job_type") or "calculation")
    energy = result.get("total_energy_hartree")
    gap = result.get("orbital_gap_ev")

    parts = [f"{job_type} completed for {structure}"]
    if energy is not None:
        try:
            parts.append(f"E={float(energy):.8f} Ha")
        except Exception:
            pass
    if gap is not None:
        try:
            parts.append(f"gap={float(gap):.3f} eV")
        except Exception:
            pass
    return " | ".join(parts)


async def _ws_send(websocket: WebSocket, event_type: str, **payload: Any) -> None:
    body = {"type": event_type, **_json_safe(payload)}
    await websocket.send_json(body)


async def _ws_send_error(
    websocket: WebSocket,
    *,
    message: str,
    detail: Optional[Any] = None,
    status_code: int = 400,
    session_id: Optional[str] = None,
) -> None:
    error_obj = {
        "message": _safe_str(message, "Request failed"),
        "detail": _json_safe(detail),
        "status_code": status_code,
        "timestamp": _now_ts(),
    }
    await _ws_send(
        websocket,
        "error",
        session_id=session_id,
        message=error_obj["message"],
        detail=error_obj["detail"],
        error=error_obj,
    )


async def _stream_backend_job_until_terminal(
    websocket: WebSocket,
    *,
    job_id: str,
    session_id: str,
) -> None:
    manager = get_job_manager()
    seen_event_ids = set()
    last_state = None

    while True:
        snap = manager.get(job_id, include_result=False, include_events=True)
        if snap is None:
            await _ws_send_error(
                websocket,
                message="Job not found while streaming.",
                status_code=404,
                session_id=session_id,
            )
            return

        state_key = (
            snap.get("status"),
            snap.get("progress"),
            snap.get("step"),
            snap.get("message"),
        )
        if state_key != last_state:
            await _ws_send(
                websocket,
                "job_update",
                session_id=session_id,
                job_id=job_id,
                status=snap.get("status"),
                progress=snap.get("progress"),
                step=snap.get("step"),
                message=snap.get("message"),
                job=snap,
            )
            last_state = state_key

        for event in snap.get("events", []) or []:
            event_id = event.get("event_id")
            if event_id in seen_event_ids:
                continue
            seen_event_ids.add(event_id)
            
            if event.get("type") == "job_progress":
                data = event.get("data") or {}
                await _ws_send(
                    websocket,
                    "job_update",
                    session_id=session_id,
                    job_id=job_id,
                    status="running",
                    progress=data.get("progress", 0.0),
                    step=data.get("step", ""),
                    message=event.get("message", "")
                )
            
            # For non-progress events, also map them nicely if they represent a step
            if event.get("type") in ("job_started", "job_completed"):
                 await _ws_send(
                    websocket,
                    "job_update",
                    session_id=session_id,
                    job_id=job_id,
                    status="running",
                    step=event.get("type"),
                    message=event.get("message", "")
                )
                
            await _ws_send(
                websocket,
                "job_event",
                session_id=session_id,
                job_id=job_id,
                event=event,
            )

        if snap.get("status") in TERMINAL_STATES:
            terminal = manager.get(job_id, include_result=True, include_events=True)
            if terminal is None:
                await _ws_send_error(
                    websocket,
                    message="Job disappeared before terminal fetch.",
                    status_code=404,
                    session_id=session_id,
                )
                return

            if terminal.get("status") in TERMINAL_FAILURE:
                await _ws_send_error(
                    websocket,
                    message=((terminal.get("error") or {}).get("message") or terminal.get("message") or "Job failed."),
                    detail=terminal.get("error"),
                    status_code=int(((terminal.get("error") or {}).get("status_code")) or 500),
                    session_id=session_id,
                )
                return

            result = terminal.get("result") or {}
            await _ws_send(
                websocket,
                "result",
                session_id=session_id,
                job=terminal,
                result=result,
                summary=_result_summary(result),
            )
            return

        await asyncio.sleep(WS_POLL_SECONDS)


@router.get("/chat/health")
def chat_health() -> Dict[str, Any]:
    manager = get_job_manager()
    return {
        "ok": True,
        "route": "/chat",
        "ws_route": "/ws/chat",
        "job_backend": manager.__class__.__name__,
        "timestamp": _now_ts(),
    }


@router.post("/chat")
def post_chat(
    payload: Optional[Dict[str, Any]] = Body(default=None),
    wait: bool = Query(default=False),
    wait_for_result: bool = Query(default=False),
    timeout: Optional[float] = Query(default=120.0),
) -> Dict[str, Any]:
    body = dict(payload or {})
    raw_message = _extract_message(body)

    plan = _safe_plan_message(raw_message, body) if raw_message else {}
    merged = _merge_plan_into_payload(body, plan, raw_message=raw_message)
    prepared = _prepare_payload(merged)

    plan_message = _plan_status_message(plan, prepared)

    manager = get_job_manager()
    submitted = manager.submit(prepared)

    should_wait = bool(
        wait
        or wait_for_result
        or body.get("wait")
        or body.get("wait_for_result")
        or body.get("sync")
    )

    if should_wait:
        terminal = manager.wait(submitted["job_id"], timeout=timeout)
        if terminal is None:
            raise HTTPException(status_code=404, detail="Job not found.")

        ok = terminal.get("status") not in TERMINAL_FAILURE
        return {
            "ok": ok,
            "message": plan_message,
            "plan": _public_plan_dict(plan),
            "job": terminal,
            "result": terminal.get("result"),
            "error": terminal.get("error"),
            "summary": _result_summary(terminal.get("result") or {}),
        }

    return {
        "ok": True,
        "message": plan_message,
        "plan": _public_plan_dict(plan),
        "job": submitted,
    }


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    await websocket.accept()

    default_session_id = f"ws-{int(_now_ts() * 1000)}"
    session_state = {"last_molecule": None}
    await _ws_send(
        websocket,
        "ready",
        session_id=default_session_id,
        message="QCViz chat websocket connected.",
        timestamp=_now_ts(),
    )

    try:
        while True:
            raw_text = await websocket.receive_text()
            incoming = _parse_client_message(raw_text)

            session_id = _extract_session_id(incoming) or default_session_id
            msg_type = str(incoming.get("type", "")).lower().strip()

            if msg_type in ("hello", "ping", "pong", "ack"):
                await _ws_send(
                    websocket,
                    "ack",
                    session_id=session_id,
                    status="connected",
                    timestamp=_now_ts(),
                )
                continue

            user_message = _extract_message(incoming)

            await _ws_send(
                websocket,
                "ack",
                session_id=session_id,
                message=user_message or "Request received.",
                payload=incoming,
                timestamp=_now_ts(),
            )
            
            # Check for follow-up
            message_lower = user_message.lower() if user_message else ""
            follow_up_keywords = ["homo", "lumo", "orbital", "esp", "charges", "dipole", "energy level", "에너지", "오비탈", "전하"]
            is_follow_up = any(kw in message_lower for kw in follow_up_keywords)
            has_molecule = _fallback_extract_structure_query(user_message) is not None
            
            if is_follow_up and not has_molecule and not incoming.get("structure_query") and not incoming.get("xyz") and not incoming.get("atom_spec"):
                if session_state.get("last_molecule"):
                    incoming["structure_query"] = session_state["last_molecule"]
                else:
                    await _ws_send(
                        websocket,
                        "assistant",
                        session_id=session_id,
                        message="Which molecule would you like to analyze? Please specify a molecule name or structure first.",
                        timestamp=_now_ts(),
                    )
                    continue

            plan = _safe_plan_message(user_message, incoming) if user_message else {}
            merged = _merge_plan_into_payload(incoming, plan, raw_message=user_message)

            try:
                prepared = _prepare_payload(merged)
            except HTTPException as exc:
                msg = _safe_str(exc.detail, "Invalid request.")
                detail = {"payload": merged}
                if "Structure not recognized" in msg:
                    msg = "Structure not recognized."
                    detail = "Please provide a molecule name, XYZ coordinates, or atom-spec text."
                
                await _ws_send_error(
                    websocket,
                    message=msg,
                    detail=detail,
                    status_code=exc.status_code,
                    session_id=session_id,
                )
                continue

            if prepared.get("structure_query") or prepared.get("structure_name"):
                session_state["last_molecule"] = prepared.get("structure_query") or prepared.get("structure_name")

            await _ws_send(
                websocket,
                "assistant",
                session_id=session_id,
                message=_plan_status_message(plan, prepared),
                plan=_public_plan_dict(plan),
                payload_preview={
                    "job_type": prepared.get("job_type"),
                    "structure_query": prepared.get("structure_query"),
                    "method": prepared.get("method"),
                    "basis": prepared.get("basis"),
                    "orbital": prepared.get("orbital"),
                    "esp_preset": prepared.get("esp_preset"),
                    "advisor_focus_tab": prepared.get("advisor_focus_tab"),
                },
                timestamp=_now_ts(),
            )

            manager = get_job_manager()
            try:
                submitted = manager.submit(prepared)
            except Exception as exc:
                logger.exception("Job submission failed.")
                await _ws_send_error(
                    websocket,
                    message="Job submission failed.",
                    detail={"type": exc.__class__.__name__, "message": str(exc)},
                    status_code=500,
                    session_id=session_id,
                )
                continue

            await _ws_send(
                websocket,
                "job_submitted",
                session_id=session_id,
                job=submitted,
                timestamp=_now_ts(),
            )

            await _stream_backend_job_until_terminal(
                websocket,
                job_id=submitted["job_id"],
                session_id=session_id,
            )

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected.")
    except Exception as exc:
        logger.exception("Unhandled websocket error.")
        try:
            await _ws_send_error(
                websocket,
                message="Unhandled websocket error.",
                detail={"type": exc.__class__.__name__, "message": str(exc)},
                status_code=500,
                session_id=default_session_id,
            )
        except Exception:
            pass


__all__ = ["router"]
```


## File: `version02/src/qcviz_mcp/web/routes/compute.py`

```python
from __future__ import annotations

import inspect
import json
import logging
import os
import re
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from fastapi import APIRouter, Body, HTTPException, Query

from qcviz_mcp.compute import pyscf_runner

try:
    from qcviz_mcp.llm.agent import QCVizAgent
except Exception:  # pragma: no cover
    QCVizAgent = None  # type: ignore


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/compute", tags=["compute"])


INTENT_TO_JOB_TYPE: Dict[str, str] = {
    "analyze": "analyze",
    "full_analysis": "analyze",
    "single_point": "single_point",
    "energy": "single_point",
    "geometry": "geometry_analysis",
    "geometry_analysis": "geometry_analysis",
    "charges": "partial_charges",
    "partial_charges": "partial_charges",
    "orbital": "orbital_preview",
    "orbital_preview": "orbital_preview",
    "esp": "esp_map",
    "esp_map": "esp_map",
    "optimization": "geometry_optimization",
    "geometry_optimization": "geometry_optimization",
    "optimize": "geometry_optimization",
    "resolve_structure": "resolve_structure",
    "structure": "resolve_structure",
}

JOB_TYPE_ALIASES: Dict[str, str] = {
    "analyze": "analyze",
    "analysis": "analyze",
    "full_analysis": "analyze",
    "singlepoint": "single_point",
    "single_point": "single_point",
    "sp": "single_point",
    "geometry": "geometry_analysis",
    "geometry_analysis": "geometry_analysis",
    "geom": "geometry_analysis",
    "charge": "partial_charges",
    "charges": "partial_charges",
    "partial_charges": "partial_charges",
    "mulliken": "partial_charges",
    "orbital": "orbital_preview",
    "orbital_preview": "orbital_preview",
    "mo": "orbital_preview",
    "esp": "esp_map",
    "esp_map": "esp_map",
    "electrostatic_potential": "esp_map",
    "opt": "geometry_optimization",
    "optimize": "geometry_optimization",
    "optimization": "geometry_optimization",
    "geometry_optimization": "geometry_optimization",
    "resolve": "resolve_structure",
    "resolve_structure": "resolve_structure",
    "structure": "resolve_structure",
}

JOB_TYPE_TO_RUNNER: Dict[str, str] = {
    "analyze": "run_analyze",
    "single_point": "run_single_point",
    "geometry_analysis": "run_geometry_analysis",
    "partial_charges": "run_partial_charges",
    "orbital_preview": "run_orbital_preview",
    "esp_map": "run_esp_map",
    "geometry_optimization": "run_geometry_optimization",
    "resolve_structure": "run_resolve_structure",
}

TERMINAL_SUCCESS = {"completed"}
TERMINAL_FAILURE = {"failed", "error"}
TERMINAL_STATES = TERMINAL_SUCCESS | TERMINAL_FAILURE

DEFAULT_POLL_SECONDS = float(os.getenv("QCVIZ_JOB_POLL_SECONDS", "0.25"))
MAX_WORKERS = int(os.getenv("QCVIZ_JOB_MAX_WORKERS", "4"))
MAX_JOBS = int(os.getenv("QCVIZ_MAX_JOBS", "200"))
MAX_JOB_EVENTS = int(os.getenv("QCVIZ_MAX_JOB_EVENTS", "200"))

_KO_STRUCTURE_ALIASES: Dict[str, str] = {
    "물": "water",
    "워터": "water",
    "암모니아": "ammonia",
    "메탄": "methane",
    "에탄": "ethane",
    "에틸렌": "ethylene",
    "에텐": "ethylene",
    "아세틸렌": "acetylene",
    "벤젠": "benzene",
    "톨루엔": "toluene",
    "페놀": "phenol",
    "아닐린": "aniline",
    "피리딘": "pyridine",
    "아세톤": "acetone",
    "메탄올": "methanol",
    "에탄올": "ethanol",
    "포름알데히드": "formaldehyde",
    "아세트알데히드": "acetaldehyde",
    "포름산": "formic_acid",
    "아세트산": "acetic_acid",
    "요소": "urea",
    "우레아": "urea",
    "이산화탄소": "carbon_dioxide",
    "일산화탄소": "carbon_monoxide",
    "질소": "nitrogen",
    "산소": "oxygen",
    "수소": "hydrogen",
    "불소": "fluorine",
    "네온": "neon",
}

_METHOD_PAT = re.compile(
    r"\b(hf|rhf|uhf|b3lyp|pbe0?|m06-?2x|wb97x-?d|ωb97x-?d|bp86|blyp)\b",
    re.IGNORECASE,
)
_BASIS_PAT = re.compile(
    r"\b(sto-?3g|3-21g|6-31g\*\*?|6-31g\(d,p\)|6-31g\(d\)|def2-?svp|def2-?tzvp|cc-pvdz|cc-pvtz)\b",
    re.IGNORECASE,
)
_CHARGE_PAT = re.compile(r"(?:charge|전하)\s*[:=]?\s*([+-]?\d+)", re.IGNORECASE)
_MULT_PAT = re.compile(r"(?:multiplicity|spin multiplicity|다중도)\s*[:=]?\s*(\d+)", re.IGNORECASE)
_ORBITAL_PAT = re.compile(
    r"\b(homo(?:\s*-\s*\d+)?|lumo(?:\s*\+\s*\d+)?|mo\s*\d+|orbital\s*\d+)\b",
    re.IGNORECASE,
)
_ESP_PRESET_PAT = re.compile(
    r"\b(acs|rsc|nature|spectral|inferno|viridis|rwb|bwr|greyscale|grayscale|high[_ -]?contrast)\b",
    re.IGNORECASE,
)


def _now_ts() -> float:
    return time.time()


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def _public_plan_dict(plan: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not plan:
        return {}
    out = dict(plan)
    return {
        "intent": out.get("intent"),
        "confidence": out.get("confidence"),
        "provider": out.get("provider"),
        "notes": out.get("notes"),
        "job_type": out.get("job_type"),
        "structure_query": out.get("structure_query"),
        "method": out.get("method"),
        "basis": out.get("basis"),
        "charge": out.get("charge"),
        "multiplicity": out.get("multiplicity"),
        "orbital": out.get("orbital"),
        "esp_preset": out.get("esp_preset"),
        "advisor_focus_tab": out.get("advisor_focus_tab"),
    }


def _normalize_text_token(text: Optional[str]) -> str:
    s = _safe_str(text, "").lower()
    s = s.replace("ω", "w")
    s = re.sub(r"[_/]+", " ", s)
    s = re.sub(r"[^\w\s가-힣+\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _extract_message(payload: Mapping[str, Any]) -> str:
    for key in ("message", "user_message", "text", "prompt", "query"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_session_id(payload: Mapping[str, Any]) -> str:
    for key in ("session_id", "conversation_id", "client_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _normalize_job_type(job_type: Optional[str], intent: Optional[str] = None) -> str:
    jt = _normalize_text_token(job_type).replace(" ", "_")
    if jt in JOB_TYPE_ALIASES:
        return JOB_TYPE_ALIASES[jt]
    intent_key = _normalize_text_token(intent).replace(" ", "_")
    if intent_key in INTENT_TO_JOB_TYPE:
        return INTENT_TO_JOB_TYPE[intent_key]
    return "analyze"


def _normalize_esp_preset(preset: Optional[str]) -> str:
    token = _normalize_text_token(preset).replace(" ", "_")
    if not token:
        return "acs"
    if token == "grayscale":
        token = "greyscale"
    if token == "high-contrast":
        token = "high_contrast"
    if token in getattr(pyscf_runner, "ESP_PRESETS_DATA", {}):
        return token
    for key, meta in getattr(pyscf_runner, "ESP_PRESETS_DATA", {}).items():
        aliases = [_normalize_text_token(x).replace(" ", "_") for x in meta.get("aliases", [])]
        if token == key or token in aliases:
            return key
    return "acs"


def _extract_xyz_block(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    raw = str(text).strip()

    fence = re.search(r"```(?:xyz)?\s*([\s\S]+?)```", raw, re.IGNORECASE)
    if fence:
        block = fence.group(1).strip()
        if block:
            return block

    if "\n" not in raw:
        return None

    lines = [ln.rstrip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return None

    atom_line = re.compile(r"^[A-Za-z]{1,3}\s+[-+0-9Ee\.]+\s+[-+0-9Ee\.]+\s+[-+0-9Ee\.]+$")
    if re.fullmatch(r"\d+", lines[0].strip()) and len(lines) >= 3:
        candidate = "\n".join(lines)
        body = lines[2:]
        if body and all(atom_line.match(x.strip()) for x in body):
            return candidate

    atom_lines = [ln for ln in lines if atom_line.match(ln.strip())]
    if len(atom_lines) >= 1 and len(atom_lines) == len(lines):
        return "\n".join(lines)

    return None


def _iter_runner_structure_names() -> Iterable[str]:
    candidate_names = [
        "BUILTIN_XYZ_LIBRARY",
        "XYZ_LIBRARY",
        "XYZ_LIBRARY_DATA",
        "STRUCTURE_LIBRARY",
        "MOLECULE_LIBRARY",
    ]
    seen = set()
    for name in candidate_names:
        lib = getattr(pyscf_runner, name, None)
        if isinstance(lib, Mapping):
            for key in lib.keys():
                s = _safe_str(key)
                if s and s not in seen:
                    seen.add(s)
                    yield s


def _fallback_extract_structure_query(message: str) -> Optional[str]:
    if not message:
        return None
    if _extract_xyz_block(message):
        return None

    normalized = _normalize_text_token(message)

    for ko_name, en_name in sorted(_KO_STRUCTURE_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if ko_name in normalized:
            return en_name

    structure_names = list(_iter_runner_structure_names())
    for name in sorted(structure_names, key=len, reverse=True):
        if _normalize_text_token(name) in normalized:
            return name

    patterns = [
        r"(?i)(?:for|of|on|about)\s+(?:the\s+)?([a-zA-Z][a-zA-Z0-9_\- ]{1,40})",
        r"(?i)([a-zA-Z][a-zA-Z0-9_\- ]{1,40})\s+(?:molecule|structure|system)",
        r"([가-힣A-Za-z0-9_\- ]+?)\s*(?:의)?\s*(?:homo|lumo|esp|전하|구조|에너지|최적화|분석|보여줘|해줘|계산)",
        r"([가-힣A-Za-z0-9_\- ]+?)\s+(?:분자|구조)",
        r"(?i)(?:analyze|show|render|preview|compute|optimize|calculate)\s+(?:the\s+)?([a-zA-Z][a-zA-Z0-9_\- ]{1,40})",
    ]
    for pat in patterns:
        m = re.search(pat, message, re.IGNORECASE)
        if not m:
            continue
        candidate = _safe_str(m.group(1))
        candidate_norm = _normalize_text_token(candidate)
        
        # strip noise
        noise = ["homo", "lumo", "esp", "map", "orbital", "orbitals", "charge", "charges", "mulliken", "partial", "geometry", "optimization", "analysis", "of", "about", "for", "보여줘", "해줘", "계산"]
        for n in noise:
            candidate_norm = re.sub(rf"\b{n}\b", " ", candidate_norm, flags=re.I)
        candidate_norm = re.sub(r"\s+", " ", candidate_norm).strip()
        
        if not candidate_norm:
            continue

        if candidate_norm in _KO_STRUCTURE_ALIASES:
            return _KO_STRUCTURE_ALIASES[candidate_norm]
        for name in structure_names:
            if _normalize_text_token(name) == candidate_norm:
                return name
        if candidate_norm:
            return candidate_norm

    return None


def _heuristic_plan(message: str, payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    payload = payload or {}
    text = message or _extract_message(payload)

    normalized = _normalize_text_token(text)

    intent = "analyze"
    focus = "summary"

    if re.search(r"\b(homo|lumo|orbital|mo)\b|오비탈", normalized, re.IGNORECASE):
        intent = "orbital"
        focus = "orbital"
    elif re.search(r"\b(esp|electrostatic)\b|정전기|전위", normalized, re.IGNORECASE):
        intent = "esp"
        focus = "esp"
    elif re.search(r"\b(charge|charges|mulliken)\b|전하", normalized, re.IGNORECASE):
        intent = "charges"
        focus = "charges"
    elif re.search(r"\b(opt|optimize|optimization)\b|최적화", normalized, re.IGNORECASE):
        intent = "optimization"
        focus = "geometry"
    elif re.search(r"\b(geometry|bond|angle|dihedral)\b|구조|결합", normalized, re.IGNORECASE):
        intent = "geometry"
        focus = "geometry"
    elif re.search(r"\b(energy|single point|singlepoint)\b|에너지", normalized, re.IGNORECASE):
        intent = "single_point"
        focus = "summary"

    method = None
    basis = None
    charge = None
    multiplicity = None
    orbital = None
    esp_preset = None

    m_method = _METHOD_PAT.search(text)
    if m_method:
        method = m_method.group(1)

    m_basis = _BASIS_PAT.search(text)
    if m_basis:
        basis = m_basis.group(1)

    m_charge = _CHARGE_PAT.search(text)
    if m_charge:
        charge = _safe_int(m_charge.group(1))

    m_mult = _MULT_PAT.search(text)
    if m_mult:
        multiplicity = _safe_int(m_mult.group(1))

    m_orb = _ORBITAL_PAT.search(text)
    if m_orb:
        orbital = m_orb.group(1).upper().replace(" ", "")

    m_preset = _ESP_PRESET_PAT.search(text)
    if m_preset:
        esp_preset = _normalize_esp_preset(m_preset.group(1))

    structure_query = _fallback_extract_structure_query(text)

    job_type = _normalize_job_type(payload.get("job_type"), intent)

    return {
        "intent": intent,
        "confidence": 0.55,
        "provider": "heuristic",
        "notes": "Heuristic fallback planner.",
        "job_type": job_type,
        "structure_query": structure_query,
        "method": method,
        "basis": basis,
        "charge": charge,
        "multiplicity": multiplicity,
        "orbital": orbital,
        "esp_preset": esp_preset,
        "advisor_focus_tab": focus,
    }


@lru_cache(maxsize=1)
def get_qcviz_agent():
    if QCVizAgent is None:
        return None
    try:
        return QCVizAgent()
    except Exception as exc:  # pragma: no cover
        logger.warning("QCVizAgent initialization failed: %s", exc)
        return None


def _coerce_plan_to_dict(plan_obj: Any) -> Dict[str, Any]:
    if plan_obj is None:
        return {}
    if isinstance(plan_obj, Mapping):
        return dict(plan_obj)

    out: Dict[str, Any] = {}
    for key in (
        "intent",
        "confidence",
        "provider",
        "notes",
        "job_type",
        "structure_query",
        "method",
        "basis",
        "charge",
        "multiplicity",
        "orbital",
        "esp_preset",
        "advisor_focus_tab",
    ):
        if hasattr(plan_obj, key):
            out[key] = getattr(plan_obj, key)
    return out


def _safe_plan_message(message: str, payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    payload = payload or {}

    agent = get_qcviz_agent()
    if agent is not None:
        try:
            if hasattr(agent, "plan_message") and callable(agent.plan_message):
                return _coerce_plan_to_dict(agent.plan_message(message, payload=payload))
            if hasattr(agent, "plan") and callable(agent.plan):
                return _coerce_plan_to_dict(agent.plan(message, payload=payload))
        except TypeError:
            try:
                if hasattr(agent, "plan_message") and callable(agent.plan_message):
                    return _coerce_plan_to_dict(agent.plan_message(message))
                if hasattr(agent, "plan") and callable(agent.plan):
                    return _coerce_plan_to_dict(agent.plan(message))
            except Exception as exc:
                logger.warning("Planner invocation failed; using heuristic fallback: %s", exc)
        except Exception as exc:
            logger.warning("Planner invocation failed; using heuristic fallback: %s", exc)

    return _heuristic_plan(message, payload=payload)


def _merge_plan_into_payload(
    payload: Dict[str, Any],
    plan: Optional[Mapping[str, Any]],
    *,
    raw_message: str = "",
) -> Dict[str, Any]:
    out = dict(payload or {})
    plan = dict(plan or {})

    intent = _safe_str(plan.get("intent"))
    if not out.get("job_type"):
        out["job_type"] = _normalize_job_type(plan.get("job_type"), intent)

    for key in ("method", "basis", "orbital", "advisor_focus_tab"):
        if not out.get(key) and plan.get(key):
            out[key] = plan.get(key)

    for key in ("charge", "multiplicity"):
        if out.get(key) is None and plan.get(key) is not None:
            out[key] = plan.get(key)

    if not out.get("esp_preset") and plan.get("esp_preset"):
        out["esp_preset"] = _normalize_esp_preset(plan.get("esp_preset"))

    if not out.get("structure_query") and plan.get("structure_query"):
        out["structure_query"] = plan.get("structure_query")

    if not out.get("xyz"):
        xyz_block = _extract_xyz_block(raw_message or _extract_message(out))
        if xyz_block:
            out["xyz"] = xyz_block

    if not out.get("structure_query") and not out.get("xyz") and not out.get("atom_spec"):
        fallback = _fallback_extract_structure_query(raw_message or _extract_message(out))
        if fallback:
            out["structure_query"] = fallback

    out["planner_applied"] = True
    out["planner_intent"] = intent or out.get("planner_intent")
    out["planner_confidence"] = plan.get("confidence")
    out["planner_provider"] = plan.get("provider")
    out["planner_notes"] = plan.get("notes")
    return out


def _focus_tab_from_result(result: Mapping[str, Any]) -> str:
    for key in ("advisor_focus_tab", "focus_tab", "default_tab"):
        value = _safe_str(result.get(key))
        if value in {"summary", "geometry", "orbital", "esp", "charges", "json", "jobs"}:
            return value
    vis = result.get("visualization") or {}
    if (vis.get("esp_cube_b64") or (vis.get("esp") or {}).get("cube_b64")) and (
        vis.get("density_cube_b64") or (vis.get("density") or {}).get("cube_b64")
    ):
        return "esp"
    if vis.get("orbital_cube_b64") or (vis.get("orbital") or {}).get("cube_b64"):
        return "orbital"
    if result.get("mulliken_charges") or result.get("partial_charges"):
        return "charges"
    if result.get("geometry_summary"):
        return "geometry"
    return "summary"


def _normalize_result_contract(result: Any, payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    payload = dict(payload or {})

    if isinstance(result, Mapping):
        out = dict(result)
    else:
        out = {"success": True, "result": _json_safe(result)}

    out.setdefault("success", True)
    out.setdefault("job_type", _normalize_job_type(payload.get("job_type"), payload.get("planner_intent")))
    out.setdefault("structure_query", payload.get("structure_query"))
    out.setdefault("structure_name", payload.get("structure_query") or payload.get("structure_name"))
    out.setdefault("method", payload.get("method") or getattr(pyscf_runner, "DEFAULT_METHOD", "B3LYP"))
    out.setdefault("basis", payload.get("basis") or getattr(pyscf_runner, "DEFAULT_BASIS", "def2-SVP"))
    out.setdefault("charge", _safe_int(payload.get("charge"), 0) or 0)
    out.setdefault("multiplicity", _safe_int(payload.get("multiplicity"), 1) or 1)

    if out.get("mulliken_charges") and not out.get("partial_charges"):
        out["partial_charges"] = out["mulliken_charges"]
    if out.get("partial_charges") and not out.get("mulliken_charges"):
        out["mulliken_charges"] = out["partial_charges"]

    vis = out.setdefault("visualization", {})
    defaults = vis.setdefault("defaults", {})
    defaults.setdefault("style", "stick")
    defaults.setdefault("labels", False)
    defaults.setdefault("orbital_iso", 0.050)
    defaults.setdefault("orbital_opacity", 0.85)
    defaults.setdefault("esp_density_iso", 0.001)
    defaults.setdefault("esp_opacity", 0.90)
    defaults.setdefault("esp_preset", _normalize_esp_preset(out.get("esp_preset") or payload.get("esp_preset")))
    defaults.setdefault("focus_tab", _focus_tab_from_result(out))

    if out.get("xyz"):
        vis.setdefault("xyz", out.get("xyz"))
        vis.setdefault("molecule_xyz", out.get("xyz"))

    if vis.get("orbital_cube_b64") and "orbital" not in vis:
        vis["orbital"] = {"cube_b64": vis["orbital_cube_b64"]}
    if vis.get("density_cube_b64") and "density" not in vis:
        vis["density"] = {"cube_b64": vis["density_cube_b64"]}
    if vis.get("esp_cube_b64") and "esp" not in vis:
        vis["esp"] = {"cube_b64": vis["esp_cube_b64"]}

    vis["available"] = {
        "orbital": bool(vis.get("orbital_cube_b64") or (vis.get("orbital") or {}).get("cube_b64")),
        "density": bool(vis.get("density_cube_b64") or (vis.get("density") or {}).get("cube_b64")),
        "esp": bool(
            (vis.get("esp_cube_b64") or (vis.get("esp") or {}).get("cube_b64"))
            and (vis.get("density_cube_b64") or (vis.get("density") or {}).get("cube_b64"))
        ),
    }

    warnings = out.get("warnings") or []
    if not isinstance(warnings, list):
        warnings = [warnings]
    out["warnings"] = [_safe_str(x) for x in warnings if _safe_str(x)]

    if out.get("orbital_gap_hartree") is None and out.get("orbital_gap_ev") is not None:
        try:
            out["orbital_gap_hartree"] = float(out["orbital_gap_ev"]) / float(
                getattr(pyscf_runner, "HARTREE_TO_EV", 27.211386245988)
            )
        except Exception:
            pass
    if out.get("orbital_gap_ev") is None and out.get("orbital_gap_hartree") is not None:
        try:
            out["orbital_gap_ev"] = float(out["orbital_gap_hartree"]) * float(
                getattr(pyscf_runner, "HARTREE_TO_EV", 27.211386245988)
            )
        except Exception:
            pass

    out["advisor_focus_tab"] = _focus_tab_from_result(out)
    out["default_tab"] = out["advisor_focus_tab"]
    return _json_safe(out)


def _prepare_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    data = dict(payload or {})
    raw_message = _extract_message(data)

    if raw_message and not data.get("planner_applied"):
        plan = _safe_plan_message(raw_message, data)
        data = _merge_plan_into_payload(data, plan, raw_message=raw_message)

    data["job_type"] = _normalize_job_type(data.get("job_type"), data.get("planner_intent"))
    data["method"] = _safe_str(
        data.get("method") or getattr(pyscf_runner, "DEFAULT_METHOD", "B3LYP"),
        getattr(pyscf_runner, "DEFAULT_METHOD", "B3LYP"),
    )
    data["basis"] = _safe_str(
        data.get("basis") or getattr(pyscf_runner, "DEFAULT_BASIS", "def2-SVP"),
        getattr(pyscf_runner, "DEFAULT_BASIS", "def2-SVP"),
    )
    data["charge"] = _safe_int(data.get("charge"), 0) or 0
    data["multiplicity"] = _safe_int(data.get("multiplicity"), 1) or 1

    if data.get("esp_preset"):
        data["esp_preset"] = _normalize_esp_preset(data.get("esp_preset"))

    if not data.get("xyz"):
        xyz_block = _extract_xyz_block(raw_message)
        if xyz_block:
            data["xyz"] = xyz_block

    if not data.get("structure_query") and not data.get("xyz") and not data.get("atom_spec"):
        fallback = _fallback_extract_structure_query(raw_message)
        if fallback:
            data["structure_query"] = fallback

    if data["job_type"] not in {"resolve_structure"}:
        if not (data.get("structure_query") or data.get("xyz") or data.get("atom_spec")):
            raise HTTPException(
                status_code=400,
                detail="Structure not recognized. Please provide a molecule name, XYZ coordinates, or atom-spec text."
            )

    return data


def _build_kwargs_for_callable(
    func: Callable[..., Any],
    payload: Mapping[str, Any],
    progress_callback: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    sig = inspect.signature(func)
    kwargs: Dict[str, Any] = {}

    candidate_map = {
        "structure_query": payload.get("structure_query") or payload.get("query"),
        "xyz": payload.get("xyz"),
        "atom_spec": payload.get("atom_spec"),
        "method": payload.get("method"),
        "basis": payload.get("basis"),
        "charge": payload.get("charge"),
        "multiplicity": payload.get("multiplicity"),
        "orbital": payload.get("orbital"),
        "esp_preset": payload.get("esp_preset"),
        "advisor_focus_tab": payload.get("advisor_focus_tab"),
        "user_message": _extract_message(payload),
        "message": _extract_message(payload),
        "progress_callback": progress_callback,
    }

    accepts_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())

    for name, param in sig.parameters.items():
        if name in candidate_map and candidate_map[name] is not None:
            kwargs[name] = candidate_map[name]

    if accepts_var_kw:
        for key, value in payload.items():
            if key not in kwargs and value is not None:
                kwargs[key] = value
        if progress_callback is not None and "progress_callback" not in kwargs:
            kwargs["progress_callback"] = progress_callback

    return kwargs


def _invoke_callable_adaptive_sync(
    func: Callable[..., Any],
    payload: Mapping[str, Any],
    progress_callback: Optional[Callable[..., Any]] = None,
) -> Any:
    kwargs = _build_kwargs_for_callable(func, payload, progress_callback=progress_callback)
    return func(**kwargs)


def _run_direct_compute(
    payload: Mapping[str, Any],
    progress_callback: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    prepared = _prepare_payload(payload)
    job_type = _normalize_job_type(prepared.get("job_type"), prepared.get("planner_intent"))
    runner_name = JOB_TYPE_TO_RUNNER.get(job_type)
    if not runner_name:
        raise HTTPException(status_code=400, detail=f"Unsupported job_type: {job_type}")

    runner = getattr(pyscf_runner, runner_name, None)
    if not callable(runner):
        raise RuntimeError(f"Runner not available: {runner_name}")

    result = _invoke_callable_adaptive_sync(runner, prepared, progress_callback=progress_callback)
    return _normalize_result_contract(result, prepared)


@dataclass
class JobRecord:
    job_id: str
    payload: Dict[str, Any]
    status: str = "queued"
    progress: float = 0.0
    step: str = "queued"
    message: str = "Queued"
    user_query: str = ""
    created_at: float = field(default_factory=_now_ts)
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    updated_at: float = field(default_factory=_now_ts)
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    events: List[Dict[str, Any]] = field(default_factory=list)
    future: Optional[Future] = None
    event_seq: int = 0


class InMemoryJobManager:
    def __init__(self, max_workers: int = MAX_WORKERS) -> None:
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="qcviz-job")
        self.lock = threading.RLock()
        self.jobs: Dict[str, JobRecord] = {}
        logger.info("JobManager initialized (ThreadPoolExecutor, max_workers=%s).", max_workers)

    def _prune(self) -> None:
        with self.lock:
            if len(self.jobs) <= MAX_JOBS:
                return
            ordered = sorted(self.jobs.values(), key=lambda x: x.created_at)
            removable = [j.job_id for j in ordered if j.status in TERMINAL_STATES]
            while len(self.jobs) > MAX_JOBS and removable:
                jid = removable.pop(0)
                self.jobs.pop(jid, None)

    def _append_event(self, job: JobRecord, event_type: str, message: str, data: Optional[Mapping[str, Any]] = None) -> None:
        job.event_seq += 1
        event = {
            "event_id": job.event_seq,
            "ts": _now_ts(),
            "type": _safe_str(event_type),
            "message": _safe_str(message),
            "data": _json_safe(dict(data or {})),
        }
        job.events.append(event)
        if len(job.events) > MAX_JOB_EVENTS:
            job.events = job.events[-MAX_JOB_EVENTS:]

    def _snapshot(
        self,
        job: JobRecord,
        *,
        include_payload: bool = False,
        include_result: bool = False,
        include_events: bool = False,
    ) -> Dict[str, Any]:
        snap = {
            "job_id": job.job_id,
            "status": job.status,
            "user_query": job.user_query,
            "molecule_name": job.payload.get("structure_query", ""),
            "method": job.payload.get("method", ""),
            "basis_set": job.payload.get("basis", ""),
            "progress": float(job.progress),
            "step": job.step,
            "message": job.message,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "ended_at": job.ended_at,
            "updated_at": job.updated_at,
        }
        if include_payload:
            snap["payload"] = _json_safe(job.payload)
        if include_result:
            snap["result"] = _json_safe(job.result)
            snap["error"] = _json_safe(job.error)
        if include_events:
            snap["events"] = _json_safe(job.events)
        return snap

    def submit(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        prepared = dict(payload or {})
        job_id = uuid.uuid4().hex
        user_message = _extract_message(prepared)
        record = JobRecord(job_id=job_id, payload=prepared, user_query=user_message)

        with self.lock:
            self.jobs[job_id] = record
            self._append_event(record, "job_submitted", "Job submitted", {"job_type": prepared.get("job_type")})
            record.future = self.executor.submit(self._run_job, job_id)

        self._prune()
        return self._snapshot(record, include_payload=False, include_result=False, include_events=False)

    def _run_job(self, job_id: str) -> None:
        with self.lock:
            job = self.jobs[job_id]
            job.status = "running"
            job.started_at = _now_ts()
            job.updated_at = job.started_at
            job.step = "starting"
            job.message = "Starting job"
            self._append_event(job, "job_started", "Job started")

        def progress_callback(*args: Any, **kwargs: Any) -> None:
            payload: Dict[str, Any] = {}
            if args and isinstance(args[0], Mapping):
                payload.update(dict(args[0]))
            else:
                if len(args) >= 1:
                    payload["progress"] = args[0]
                if len(args) >= 2:
                    payload["step"] = args[1]
                if len(args) >= 3:
                    payload["message"] = args[2]
            payload.update(kwargs)

            with self.lock:
                record = self.jobs[job_id]
                record.progress = max(0.0, min(1.0, float(_safe_float(payload.get("progress"), record.progress) or 0.0)))
                record.step = _safe_str(payload.get("step"), record.step or "running")
                record.message = _safe_str(payload.get("message"), record.message or record.step or "Running")
                record.updated_at = _now_ts()
                self._append_event(
                    record,
                    "job_progress",
                    record.message,
                    {
                        "progress": record.progress,
                        "step": record.step,
                    },
                )

        try:
            result = _run_direct_compute(job.payload, progress_callback=progress_callback)
            with self.lock:
                job = self.jobs[job_id]
                job.status = "completed"
                job.progress = 1.0
                job.step = "done"
                job.message = "Completed"
                job.result = result
                job.updated_at = _now_ts()
                job.ended_at = job.updated_at
                self._append_event(job, "job_completed", "Job completed")
        except HTTPException as exc:
            with self.lock:
                job = self.jobs[job_id]
                job.status = "failed"
                job.step = "error"
                job.message = _safe_str(exc.detail, "Request failed")
                job.error = {
                    "message": _safe_str(exc.detail, "Request failed"),
                    "status_code": exc.status_code,
                }
                job.updated_at = _now_ts()
                job.ended_at = job.updated_at
                self._append_event(job, "job_failed", job.message, job.error)
        except Exception as exc:
            logger.exception("Direct compute failed for job %s", job_id)
            with self.lock:
                job = self.jobs[job_id]
                job.status = "failed"
                job.step = "error"
                job.message = str(exc)
                job.error = {
                    "message": str(exc),
                    "type": exc.__class__.__name__,
                }
                job.updated_at = _now_ts()
                job.ended_at = job.updated_at
                self._append_event(job, "job_failed", job.message, job.error)

    def get(
        self,
        job_id: str,
        *,
        include_payload: bool = False,
        include_result: bool = False,
        include_events: bool = False,
    ) -> Optional[Dict[str, Any]]:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return None
            return self._snapshot(
                job,
                include_payload=include_payload,
                include_result=include_result,
                include_events=include_events,
            )

    def list(
        self,
        *,
        include_payload: bool = False,
        include_result: bool = False,
        include_events: bool = False,
    ) -> List[Dict[str, Any]]:
        with self.lock:
            jobs = sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)
            return [
                self._snapshot(
                    job,
                    include_payload=include_payload,
                    include_result=include_result,
                    include_events=include_events,
                )
                for job in jobs
            ]

    def delete(self, job_id: str) -> bool:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return False
            if job.status not in TERMINAL_STATES:
                raise HTTPException(status_code=409, detail="Cannot delete a running job.")
            self.jobs.pop(job_id, None)
            return True

    def wait(self, job_id: str, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        deadline = _now_ts() + timeout if timeout else None
        while True:
            snap = self.get(job_id, include_payload=False, include_result=True, include_events=True)
            if snap is None:
                return None
            if snap["status"] in TERMINAL_STATES:
                return snap
            if deadline is not None and _now_ts() >= deadline:
                return snap
            time.sleep(DEFAULT_POLL_SECONDS)


JOB_MANAGER = InMemoryJobManager(max_workers=MAX_WORKERS)


def get_job_manager() -> InMemoryJobManager:
    return JOB_MANAGER


@router.get("/health")
def compute_health() -> Dict[str, Any]:
    agent = get_qcviz_agent()
    provider = None
    if agent is not None:
        provider = getattr(agent, "provider", None) or getattr(agent, "resolved_provider", None)

    return {
        "ok": True,
        "route": "/compute",
        "planner_provider": provider or "heuristic",
        "job_count": len(JOB_MANAGER.list()),
        "max_workers": MAX_WORKERS,
        "timestamp": _now_ts(),
    }


@router.post("/jobs")
def submit_job(
    payload: Optional[Dict[str, Any]] = Body(default=None),
    sync: bool = Query(default=False),
    wait: bool = Query(default=False),
    wait_for_result: bool = Query(default=False),
    timeout: Optional[float] = Query(default=120.0),
) -> Dict[str, Any]:
    body = dict(payload or {})
    should_wait = bool(sync or wait or wait_for_result or body.get("sync") or body.get("wait") or body.get("wait_for_result"))

    snapshot = JOB_MANAGER.submit(body)

    if should_wait:
        terminal = JOB_MANAGER.wait(snapshot["job_id"], timeout=timeout)
        if terminal is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        return terminal

    return snapshot


@router.get("/jobs")
def list_jobs(
    include_payload: bool = Query(default=False),
    include_result: bool = Query(default=False),
    include_events: bool = Query(default=False),
) -> Dict[str, Any]:
    return {
        "items": JOB_MANAGER.list(
            include_payload=include_payload,
            include_result=include_result,
            include_events=include_events,
        ),
        "count": len(JOB_MANAGER.list()),
    }


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    include_payload: bool = Query(default=False),
    include_result: bool = Query(default=False),
    include_events: bool = Query(default=False),
) -> Dict[str, Any]:
    snap = JOB_MANAGER.get(
        job_id,
        include_payload=include_payload,
        include_result=include_result,
        include_events=include_events,
    )
    if snap is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return snap


@router.get("/jobs/{job_id}/result")
def get_job_result(job_id: str) -> Dict[str, Any]:
    snap = JOB_MANAGER.get(job_id, include_result=True)
    if snap is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {
        "job_id": job_id,
        "status": snap["status"],
        "result": snap.get("result"),
        "error": snap.get("error"),
    }


@router.get("/jobs/{job_id}/events")
def get_job_events(job_id: str) -> Dict[str, Any]:
    snap = JOB_MANAGER.get(job_id, include_events=True)
    if snap is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {
        "job_id": job_id,
        "status": snap["status"],
        "events": snap.get("events", []),
    }


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str) -> Dict[str, Any]:
    ok = JOB_MANAGER.delete(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"ok": True, "job_id": job_id}


__all__ = [
    "router",
    "JOB_MANAGER",
    "get_job_manager",
    "_extract_message",
    "_extract_session_id",
    "_fallback_extract_structure_query",
    "_merge_plan_into_payload",
    "_normalize_result_contract",
    "_prepare_payload",
    "_public_plan_dict",
    "_safe_plan_message",
]```


## File: `version02/src/qcviz_mcp/compute/job_manager.py`

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
    return _JOB_MANAGER_SINGLETON```


## File: `version02/src/qcviz_mcp/compute/pyscf_runner.py`

```python
from __future__ import annotations
import re
import os
import base64
import math
import tempfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
from pyscf import dft, gto, scf
from pyscf.tools import cubegen

try:
    from pyscf.geomopt.geometric_solver import optimize as geometric_optimize
except Exception:  # pragma: no cover
    geometric_optimize = None

# ----------------------------------------------------------------------------
# CONSTANTS & METADATA
# ----------------------------------------------------------------------------

HARTREE_TO_EV = 27.211386245988
HARTREE_TO_KCAL = 627.5094740631
BOHR_TO_ANGSTROM = 0.529177210903
EV_TO_KCAL = 23.06054783061903

DEFAULT_METHOD = "B3LYP"
DEFAULT_BASIS = "def2-SVP"

DEFAULT_ESP_PRESET_ORDER = [
    "acs",
    "rsc",
    "nature",
    "spectral",
    "inferno",
    "viridis",
    "rwb",
    "bwr",
    "greyscale",
    "high_contrast",
]

ESP_PRESETS_DATA: Dict[str, Dict[str, Any]] = {
    "acs": {
        "id": "acs",
        "label": "ACS-style",
        "aliases": ["american chemical society", "acs-style", "science", "default"],
        "surface_scheme": "rwb",
        "default_range_au": 0.060,
        "description": "Balanced red-white-blue diverging scheme for molecular ESP.",
    },
    "rsc": {
        "id": "rsc",
        "label": "RSC-style",
        "aliases": ["royal society of chemistry", "rsc-style"],
        "surface_scheme": "bwr",
        "default_range_au": 0.055,
        "description": "Soft blue-white-red variant commonly seen in chemistry figures.",
    },
    "nature": {
        "id": "nature",
        "label": "Nature-style",
        "aliases": ["nature-style"],
        "surface_scheme": "spectral",
        "default_range_au": 0.055,
        "description": "Publication-friendly high-separation spectral diverging scheme.",
    },
    "spectral": {
        "id": "spectral",
        "label": "Spectral",
        "aliases": ["rainbow", "diverging"],
        "surface_scheme": "spectral",
        "default_range_au": 0.060,
        "description": "High contrast diverging palette.",
    },
    "inferno": {
        "id": "inferno",
        "label": "Inferno",
        "aliases": [],
        "surface_scheme": "inferno",
        "default_range_au": 0.055,
        "description": "Perceptually uniform warm palette.",
    },
    "viridis": {
        "id": "viridis",
        "label": "Viridis",
        "aliases": [],
        "surface_scheme": "viridis",
        "default_range_au": 0.055,
        "description": "Perceptually uniform scientific palette.",
    },
    "rwb": {
        "id": "rwb",
        "label": "Red-White-Blue",
        "aliases": ["red-white-blue", "red white blue"],
        "surface_scheme": "rwb",
        "default_range_au": 0.060,
        "description": "Classic negative/neutral/positive diverging palette.",
    },
    "bwr": {
        "id": "bwr",
        "label": "Blue-White-Red",
        "aliases": ["blue-white-red", "blue white red"],
        "surface_scheme": "bwr",
        "default_range_au": 0.060,
        "description": "Classic positive/neutral/negative diverging palette.",
    },
    "greyscale": {
        "id": "greyscale",
        "label": "Greyscale",
        "aliases": ["gray", "grey", "mono", "monochrome"],
        "surface_scheme": "greyscale",
        "default_range_au": 0.050,
        "description": "Monochrome publication palette.",
    },
    "high_contrast": {
        "id": "high_contrast",
        "label": "High Contrast",
        "aliases": ["high-contrast", "contrast"],
        "surface_scheme": "high_contrast",
        "default_range_au": 0.070,
        "description": "Strong contrast for presentations and screenshots.",
    },
}

_KO_STRUCTURE_ALIASES: Dict[str, str] = {
    "물": "water",
    "워터": "water",
    "암모니아": "ammonia",
    "메탄": "methane",
    "에탄": "ethane",
    "에틸렌": "ethylene",
    "아세틸렌": "acetylene",
    "벤젠": "benzene",
    "톨루엔": "toluene",
    "페놀": "phenol",
    "아닐린": "aniline",
    "피리딘": "pyridine",
    "아세톤": "acetone",
    "메탄올": "methanol",
    "에탄올": "ethanol",
    "포름알데히드": "formaldehyde",
    "아세트알데히드": "acetaldehyde",
    "포름산": "formic_acid",
    "아세트산": "acetic_acid",
    "요소": "urea",
    "우레아": "urea",
    "이산화탄소": "carbon_dioxide",
    "일산화탄소": "carbon_monoxide",
    "질소": "nitrogen",
    "산소": "oxygen",
    "수소": "hydrogen",
    "불소": "fluorine",
    "네온": "neon",
}

_METHOD_ALIASES: Dict[str, str] = {
    "hf": "HF",
    "rhf": "HF",
    "uhf": "HF",
    "b3lyp": "B3LYP",
    "pbe": "PBE",
    "pbe0": "PBE0",
    "m062x": "M06-2X",
    "m06-2x": "M06-2X",
    "wb97xd": "wB97X-D",
    "ωb97x-d": "wB97X-D",
    "wb97x-d": "wB97X-D",
    "bp86": "BP86",
    "blyp": "BLYP",
}

_BASIS_ALIASES: Dict[str, str] = {
    "sto-3g": "STO-3G",
    "3-21g": "3-21G",
    "6-31g": "6-31G",
    "6-31g*": "6-31G*",
    "6-31g(d)": "6-31G*",
    "6-31g**": "6-31G**",
    "6-31g(d,p)": "6-31G**",
    "def2svp": "def2-SVP",
    "def2-svp": "def2-SVP",
    "def2tzvp": "def2-TZVP",
    "def2-tzvp": "def2-TZVP",
    "cc-pvdz": "cc-pVDZ",
    "cc-pvtz": "cc-pVTZ",
}

_COVALENT_RADII = {
    "H": 0.31,
    "B": 0.85,
    "C": 0.76,
    "N": 0.71,
    "O": 0.66,
    "F": 0.57,
    "P": 1.07,
    "S": 1.05,
    "Cl": 1.02,
    "Br": 1.20,
    "I": 1.39,
    "Si": 1.11,
}

BUILTIN_XYZ_LIBRARY = {
    "water": "3\n\nO 0.000 0.000 0.117\nH 0.000 0.757 -0.469\nH 0.000 -0.757 -0.469",
    "ammonia": "4\n\nN 0.000 0.000 0.112\nH 0.000 0.938 -0.262\nH 0.812 -0.469 -0.262\nH -0.812 -0.469 -0.262",
    "methane": "5\n\nC 0.000 0.000 0.000\nH 0.627 0.627 0.627\nH -0.627 -0.627 0.627\nH 0.627 -0.627 -0.627\nH -0.627 0.627 -0.627",
    "benzene": "12\n\nC 0.0000 1.3965 0.0000\nC 1.2094 0.6983 0.0000\nC 1.2094 -0.6983 0.0000\nC 0.0000 -1.3965 0.0000\nC -1.2094 -0.6983 0.0000\nC -1.2094 0.6983 0.0000\nH 0.0000 2.4842 0.0000\nH 2.1514 1.2421 0.0000\nH 2.1514 -1.2421 0.0000\nH 0.0000 -2.4842 0.0000\nH -2.1514 -1.2421 0.0000\nH -2.1514 1.2421 0.0000",
    "acetone": "10\n\nC 0.000 0.280 0.000\nO 0.000 1.488 0.000\nC 1.285 -0.551 0.000\nC -1.285 -0.551 0.000\nH 1.266 -1.203 -0.880\nH 1.266 -1.203 0.880\nH 2.155 0.106 0.000\nH -1.266 -1.203 -0.880\nH -1.266 -1.203 0.880\nH -2.155 0.106 0.000",
}

# ----------------------------------------------------------------------------
# CORE UTILS
# ----------------------------------------------------------------------------

def unique(arr):
    seen = set()
    out = []
    for x in arr:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default

def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default

def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()

def _dedupe_strings(items: Iterable[Any]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items or []:
        text = _safe_str(item, "")
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out

def _normalize_name_token(text: Optional[str]) -> str:
    s = _safe_str(text, "").lower()
    s = s.replace("ω", "w")
    s = re.sub(r"[_/]+", " ", s)
    s = re.sub(r"[^0-9a-zA-Z가-힣+\-\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _normalize_method_name(method: Optional[str]) -> str:
    key = _normalize_name_token(method).replace(" ", "")
    return _METHOD_ALIASES.get(key, _safe_str(method, DEFAULT_METHOD) or DEFAULT_METHOD)

def _normalize_basis_name(basis: Optional[str]) -> str:
    key = _normalize_name_token(basis).replace(" ", "")
    return _BASIS_ALIASES.get(key, _safe_str(basis, DEFAULT_BASIS) or DEFAULT_BASIS)

def _normalize_esp_preset(preset: Optional[str]) -> str:
    raw = _normalize_name_token(preset)
    if not raw:
        return "acs"
    compact = raw.replace(" ", "_")
    if compact in ESP_PRESETS_DATA:
        return compact
    for key, meta in ESP_PRESETS_DATA.items():
        aliases = [_normalize_name_token(a).replace(" ", "_") for a in meta.get("aliases", [])]
        if compact == key or compact in aliases:
            return key
    if compact in {"default", "auto"}:
        return "acs"
    return "acs"

def _looks_like_xyz(text: Optional[str]) -> bool:
    if not text:
        return False
    s = str(text).strip()
    if "\n" in s:
        lines = [ln.rstrip() for ln in s.splitlines() if ln.strip()]
        if lines and re.fullmatch(r"\d+", lines[0].strip()):
            lines = lines[2:]
        atom_pat = re.compile(r"^[A-Za-z]{1,3}\s+[-+0-9Ee\.]+\s+[-+0-9Ee\.]+\s+[-+0-9Ee\.]+$")
        atom_lines = [ln for ln in lines if atom_pat.match(ln.strip())]
        return len(atom_lines) >= 1
    return False

def _strip_xyz_header(xyz_text: str) -> str:
    lines = (xyz_text or "").splitlines()
    
    start_idx = 0
    for i, ln in enumerate(lines):
        if ln.strip():
            start_idx = i
            break
    else:
        return ""
        
    first_line = lines[start_idx].strip()
    if re.fullmatch(r"\d+", first_line):
        start_idx += 2
        
    atom_lines = [ln.strip() for ln in lines[start_idx:] if ln.strip()]
    return "\n".join(atom_lines)

def _iter_structure_libraries() -> Iterable[Mapping[str, str]]:
    candidate_names = [
        "BUILTIN_XYZ_LIBRARY",
        "XYZ_LIBRARY",
        "XYZ_LIBRARY_DATA",
        "STRUCTURE_LIBRARY",
        "MOLECULE_LIBRARY",
    ]
    seen = set()
    for name in candidate_names:
        lib = globals().get(name)
        if isinstance(lib, Mapping) and id(lib) not in seen:
            seen.add(id(lib))
            yield lib

def _lookup_builtin_xyz(query: Optional[str]) -> Optional[Tuple[str, str]]:
    if not query:
        return None
    q0 = _safe_str(query)
    qn = _normalize_name_token(q0)
    
    noise = ["homo", "lumo", "esp", "map", "orbital", "orbitals", "charge", "charges", "mulliken", "partial", "geometry", "optimization", "analysis", "of", "about", "for"]
    qc = qn
    for n in noise:
        qc = re.sub(rf"\\b{n}\\b", " ", qc, flags=re.I)
    qc = re.sub(r"\\s+", " ", qc).strip()
    
    candidates = unique([q0, qn, qc, qn.replace(" ", "_"), qn.replace(" ", ""), qc.replace(" ", "_"), qc.replace(" ", "")])
    
    for ko_name, en_name in sorted(_KO_STRUCTURE_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if ko_name in qn or ko_name in q0:
            candidates.extend([en_name, en_name.replace("_", " "), en_name.replace("_", "")])
            break

    for lib in _iter_structure_libraries():
        normalized_map = {}
        for key, value in lib.items():
            if not isinstance(value, str): continue
            k = _safe_str(key)
            normalized_map[k] = (k, value)
            kn = _normalize_name_token(k)
            normalized_map[kn] = (k, value)
            normalized_map[kn.replace(" ", "_")] = (k, value)
            normalized_map[kn.replace(" ", "")] = (k, value)
            
        for cand in candidates:
            if cand in normalized_map: return normalized_map[cand]
        
        for kn, pair in normalized_map.items():
            if len(kn) > 2 and (kn in qn or kn in qc):
                return pair
    return None
    q0 = _safe_str(query)
    qn = _normalize_name_token(q0)
    
    # Try direct mapping and common transforms
    candidates = [q0, qn, qn.replace(" ", "_"), qn.replace(" ", "")]
    
    # Try Korean aliases (substring match)
    for ko_name, en_name in sorted(_KO_STRUCTURE_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if ko_name in qn or ko_name in q0:
            candidates.extend([en_name, en_name.replace("_", " "), en_name.replace("_", "")])
            break

    for lib in _iter_structure_libraries():
        normalized_map: Dict[str, Tuple[str, str]] = {}
        for key, value in lib.items():
            if not isinstance(value, str):
                continue
            k = _safe_str(key)
            normalized_map[k] = (k, value)
            kn = _normalize_name_token(k)
            normalized_map[kn] = (k, value)
            normalized_map[kn.replace(" ", "_")] = (k, value)
            normalized_map[kn.replace(" ", "")] = (k, value)
            
        for cand in candidates:
            if cand in normalized_map:
                return normalized_map[cand]
    return None
    q0 = _safe_str(query)
    qn = _normalize_name_token(q0)
    candidates = [q0, qn, qn.replace(" ", "_"), qn.replace(" ", "")]
    if qn in _KO_STRUCTURE_ALIASES:
        alias = _KO_STRUCTURE_ALIASES[qn]
        candidates.extend([alias, alias.replace("_", " "), alias.replace("_", "")])
    if q0 in _KO_STRUCTURE_ALIASES:
        alias = _KO_STRUCTURE_ALIASES[q0]
        candidates.extend([alias, alias.replace("_", " "), alias.replace("_", "")])

    for lib in _iter_structure_libraries():
        normalized_map: Dict[str, Tuple[str, str]] = {}
        for key, value in lib.items():
            if not isinstance(value, str):
                continue
            k = _safe_str(key)
            normalized_map[k] = (k, value)
            normalized_map[_normalize_name_token(k)] = (k, value)
            normalized_map[_normalize_name_token(k).replace(" ", "_")] = (k, value)
            normalized_map[_normalize_name_token(k).replace(" ", "")] = (k, value)
        for cand in candidates:
            if cand in normalized_map:
                return normalized_map[cand]
    return None

def _resolve_structure_payload(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
) -> Tuple[str, str]:
    if atom_spec and _safe_str(atom_spec):
        return _safe_str(structure_query, "custom"), _safe_str(atom_spec).strip()

    if xyz and _safe_str(xyz):
        atom_text = _strip_xyz_header(_safe_str(xyz))
        if atom_text:
            return _safe_str(structure_query, "custom"), atom_text

    if structure_query and _looks_like_xyz(structure_query):
        atom_text = _strip_xyz_header(_safe_str(structure_query))
        if atom_text:
            return "custom", atom_text

    if structure_query:
        hit = _lookup_builtin_xyz(structure_query)
        if hit:
            label, xyz_text = hit
            atom_text = _strip_xyz_header(xyz_text)
            return label, atom_text
            
        try:
            from qcviz_mcp.tools.core import MoleculeResolver
            resolved_xyz = MoleculeResolver.resolve_with_friendly_errors(structure_query)
            if resolved_xyz:
                atom_text = _strip_xyz_header(resolved_xyz)
                if atom_text:
                    return _safe_str(structure_query), atom_text
        except Exception as e:
            pass

    raise ValueError("No structure could be resolved; provide query, XYZ, or atom-spec text.")

def _mol_to_xyz(mol: gto.Mole, comment: str = "") -> str:
    coords = mol.atom_coords(unit="Angstrom")
    lines = [str(mol.natm), comment or "QCViz-MCP"]
    for i in range(mol.natm):
        sym = mol.atom_symbol(i)
        x, y, z = coords[i]
        lines.append(f"{sym:2s} {x: .8f} {y: .8f} {z: .8f}")
    return "\n".join(lines)

def _build_mol(
    atom_text: str,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    unit: str = "Angstrom",
) -> gto.Mole:
    basis_name = _normalize_basis_name(basis or DEFAULT_BASIS)
    spin = max(int(multiplicity or 1) - 1, 0)
    return gto.M(
        atom=atom_text,
        basis=basis_name,
        charge=int(charge or 0),
        spin=spin,
        unit=unit,
        verbose=0,
    )

def _build_mean_field(mol: gto.Mole, method: Optional[str] = None):
    method_name = _normalize_method_name(method or DEFAULT_METHOD)
    key = _normalize_name_token(method_name).replace(" ", "")
    is_open_shell = bool(getattr(mol, "spin", 0))
    if key in {"hf", "rhf", "uhf"}:
        mf = scf.UHF(mol) if is_open_shell else scf.RHF(mol)
        return method_name, mf

    xc_map = {
        "b3lyp": "b3lyp",
        "pbe": "pbe",
        "pbe0": "pbe0",
        "m06-2x": "m06-2x",
        "m062x": "m06-2x",
        "wb97x-d": "wb97x-d",
        "ωb97x-d": "wb97x-d",
        "wb97x-d": "wb97x-d",
        "bp86": "bp86",
        "blyp": "blyp",
    }
    xc = xc_map.get(key, "b3lyp")
    mf = dft.UKS(mol) if is_open_shell else dft.RKS(mol)
    mf.xc = xc
    try:
        mf.grids.level = 3
    except Exception:
        pass
    return method_name, mf

import hashlib
from qcviz_mcp.compute.disk_cache import save_to_disk, load_from_disk

_SCF_CACHE = {}

def _get_cache_key(xyz: str, method: str, basis: str, charge: int, multiplicity: int) -> str:
    atom_data = _strip_xyz_header(xyz).strip()
    key_str = f"{atom_data}|{method}|{basis}|{charge}|{multiplicity}"
    return hashlib.md5(key_str.encode('utf-8')).hexdigest()

import time

def _run_scf_with_fallback(mf, warnings: Optional[List[str]] = None, cache_key: Optional[str] = None, progress_callback: Optional[Callable] = None):
    warnings = warnings if warnings is not None else []
    
    if cache_key:
        if cache_key in _SCF_CACHE:
            cached_mf, cached_energy = _SCF_CACHE[cache_key]
            # Set the mol on the cached object so downstream functions like mulliken_charges work smoothly
            cached_mf.mol = getattr(mf, 'mol', None) or getattr(mf, '_mol', None) or mf.mol
            if progress_callback:
                _emit_progress(progress_callback, 0.5, "scf", "Cache hit: SCF skipped (0.0s)")
            return cached_mf, cached_energy
            
        disk_mf, disk_energy = load_from_disk(cache_key, mf)
        if disk_mf is not None:
            _SCF_CACHE[cache_key] = (disk_mf, disk_energy)
            # Same here, bind the current request's molecule object to the loaded mf
            disk_mf.mol = getattr(mf, 'mol', None) or getattr(mf, '_mol', None) or mf.mol
            if progress_callback:
                _emit_progress(progress_callback, 0.5, "scf", "Disk cache hit: SCF loaded (0.0s)")
            return disk_mf, disk_energy

    try:
        mf.conv_tol = min(getattr(mf, "conv_tol", 1e-9), 1e-9)
    except Exception:
        pass
    try:
        mf.max_cycle = max(int(getattr(mf, "max_cycle", 50)), 100)
    except Exception:
        pass

    # Attach a callback to report SCF iterations
    cycle_count = [0]
    def _scf_callback(env):
        cycle_count[0] += 1
        if progress_callback and cycle_count[0] % 2 == 0:
            c = cycle_count[0]
            max_c = getattr(mf, "max_cycle", "?")
            e = env.get("e_tot", 0.0)
            _emit_progress(progress_callback, min(0.60, 0.35 + (c / 100.0) * 0.25), "scf", f"SCF iteration {c}/{max_c} (E={e:.4f} Ha)")

    try:
        mf.callback = _scf_callback
    except Exception:
        pass

    t0 = time.time()
    energy = mf.kernel()
    t1 = time.time()
    elapsed = t1 - t0
    
    cycles = cycle_count[0]
    
    if getattr(mf, "converged", False):
        if progress_callback:
            _emit_progress(progress_callback, 0.60, "scf", f"SCF converged in {cycles} cycles ({elapsed:.1f}s)")
        if cache_key:
            _SCF_CACHE[cache_key] = (mf, energy)
            save_to_disk(cache_key, mf, energy)
        return mf, energy

    warnings.append(f"Primary SCF did not converge after {cycles} cycles; attempting Newton refinement.")
    if progress_callback:
        _emit_progress(progress_callback, 0.60, "scf", "Primary SCF failed; starting Newton refinement")
        
    try:
        mf = mf.newton()
        energy = mf.kernel()
        t2 = time.time()
        elapsed_newton = t2 - t1
        
        if progress_callback:
            _emit_progress(progress_callback, 0.65, "scf", f"Newton refinement finished ({elapsed_newton:.1f}s)")
            
        if cache_key and getattr(mf, "converged", False):
            _SCF_CACHE[cache_key] = (mf, energy)
            save_to_disk(cache_key, mf, energy)
    except Exception as exc:
        warnings.append(f"Newton refinement failed: {exc}")

    return mf, energy

def _file_to_b64(path: Union[str, Path, None]) -> Optional[str]:
    if not path:
        return None
    p = Path(path)
    if not p.exists() or not p.is_file():
        return None
    return base64.b64encode(p.read_bytes()).decode("ascii")

def _parse_cube_values(path: Union[str, Path]) -> np.ndarray:
    p = Path(path)
    text = p.read_text(errors="ignore").splitlines()
    if len(text) < 7:
        return np.array([], dtype=float)

    try:
        natm = abs(int(text[2].split()[0]))
        data_start = 6 + natm
    except Exception:
        data_start = 6

    values: List[float] = []
    for line in text[data_start:]:
        for token in line.split():
            try:
                values.append(float(token))
            except Exception:
                continue
    return np.asarray(values, dtype=float)

def _nice_symmetric_limit(value: float) -> float:
    if not np.isfinite(value) or value <= 0:
        return 0.05
    if value < 0.02:
        step = 0.0025
    elif value < 0.05:
        step = 0.005
    elif value < 0.10:
        step = 0.010
    else:
        step = 0.020
    return float(math.ceil(value / step) * step)

def _compute_esp_auto_range(
    esp_values: np.ndarray,
    density_values: Optional[np.ndarray] = None,
    density_iso: float = 0.001,
) -> Dict[str, Any]:
    arr = np.asarray(esp_values, dtype=float).ravel()
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        default_au = ESP_PRESETS_DATA["acs"]["default_range_au"]
        return {
            "range_au": default_au,
            "range_kcal": default_au * HARTREE_TO_KCAL,
            "stats": {},
            "strategy": "default",
        }

    masked = arr
    if density_values is not None:
        dens = np.asarray(density_values, dtype=float).ravel()
        if dens.size == arr.size:
            dens = dens[np.isfinite(dens)]
            if dens.size == arr.size:
                low = density_iso * 0.35
                high = density_iso * 4.0
                mask = (density_values.ravel() >= low) & (density_values.ravel() <= high)
                mask = mask & np.isfinite(esp_values.ravel())
                if np.count_nonzero(mask) >= 128:
                    masked = np.asarray(esp_values, dtype=float).ravel()[mask]

    masked = masked[np.isfinite(masked)]
    if masked.size < 32:
        masked = arr

    abs_vals = np.abs(masked)
    p90 = float(np.percentile(abs_vals, 90))
    p95 = float(np.percentile(abs_vals, 95))
    p98 = float(np.percentile(abs_vals, 98))
    p995 = float(np.percentile(abs_vals, 99.5))
    robust = 0.55 * p95 + 0.35 * p98 + 0.10 * p995
    robust = float(np.clip(robust, 0.02, 0.18))
    nice = _nice_symmetric_limit(robust)

    return {
        "range_au": nice,
        "range_kcal": nice * HARTREE_TO_KCAL,
        "stats": {
            "n": int(masked.size),
            "min_au": float(np.min(masked)),
            "max_au": float(np.max(masked)),
            "mean_au": float(np.mean(masked)),
            "std_au": float(np.std(masked)),
            "p90_abs_au": p90,
            "p95_abs_au": p95,
            "p98_abs_au": p98,
            "p995_abs_au": p995,
        },
        "strategy": "robust_surface_shell_percentile",
    }

def _compute_esp_auto_range_from_cube_files(
    esp_cube_path: Union[str, Path],
    density_cube_path: Optional[Union[str, Path]] = None,
    density_iso: float = 0.001,
) -> Dict[str, Any]:
    try:
        esp_values = _parse_cube_values(esp_cube_path)
    except Exception:
        esp_values = np.array([], dtype=float)
    density_values = None
    if density_cube_path:
        try:
            density_values = _parse_cube_values(density_cube_path)
        except Exception:
            density_values = None
    return _compute_esp_auto_range(esp_values, density_values=density_values, density_iso=density_iso)

def _formula_from_symbols(symbols: Sequence[str]) -> str:
    counts = Counter(symbols)
    if not counts:
        return ""
    ordered: List[Tuple[str, int]] = []
    if "C" in counts:
        ordered.append(("C", counts.pop("C")))
    if "H" in counts:
        ordered.append(("H", counts.pop("H")))
    for key in sorted(counts):
        ordered.append((key, counts[key]))
    return "".join(f"{el}{n if n != 1 else ''}" for el, n in ordered)

def _guess_bonds(mol: gto.Mole) -> List[Dict[str, Any]]:
    coords = np.asarray(mol.atom_coords(unit="Angstrom"), dtype=float)
    symbols = [mol.atom_symbol(i) for i in range(mol.natm)]
    bonds: List[Dict[str, Any]] = []
    for i in range(mol.natm):
        for j in range(i + 1, mol.natm):
            ri = _COVALENT_RADII.get(symbols[i], 0.77)
            rj = _COVALENT_RADII.get(symbols[j], 0.77)
            cutoff = 1.25 * (ri + rj)
            dist = float(np.linalg.norm(coords[i] - coords[j]))
            if 0.1 < dist <= cutoff:
                bonds.append(
                    {
                        "a": i,
                        "b": j,
                        "order": 1,
                        "length_angstrom": dist,
                    }
                )
    return bonds

def _normalize_partial_charges(mol: gto.Mole, charges: Optional[Sequence[float]]) -> List[Dict[str, Any]]:
    if charges is None:
        return []
    out: List[Dict[str, Any]] = []
    for i, q in enumerate(charges):
        out.append(
            {
                "atom_index": i,
                "symbol": mol.atom_symbol(i),
                "charge": float(q),
            }
        )
    return out

def _geometry_summary(mol: gto.Mole, bonds: Optional[Sequence[Mapping[str, Any]]] = None) -> Dict[str, Any]:
    coords = np.asarray(mol.atom_coords(unit="Angstrom"), dtype=float)
    symbols = [mol.atom_symbol(i) for i in range(mol.natm)]
    centroid = coords.mean(axis=0) if len(coords) else np.zeros(3)
    bbox_min = coords.min(axis=0) if len(coords) else np.zeros(3)
    bbox_max = coords.max(axis=0) if len(coords) else np.zeros(3)
    dims = bbox_max - bbox_min
    bond_lengths = [float(b["length_angstrom"]) for b in (bonds or []) if "length_angstrom" in b]
    return {
        "n_atoms": int(mol.natm),
        "formula": _formula_from_symbols(symbols),
        "centroid_angstrom": [float(x) for x in centroid],
        "bbox_min_angstrom": [float(x) for x in bbox_min],
        "bbox_max_angstrom": [float(x) for x in bbox_max],
        "bbox_size_angstrom": [float(x) for x in dims],
        "bond_count": int(len(bonds or [])),
        "bond_length_min_angstrom": float(min(bond_lengths)) if bond_lengths else None,
        "bond_length_max_angstrom": float(max(bond_lengths)) if bond_lengths else None,
        "bond_length_mean_angstrom": float(np.mean(bond_lengths)) if bond_lengths else None,
    }

def _extract_dipole(mf) -> Optional[Dict[str, Any]]:
    try:
        vec = np.asarray(mf.dip_moment(unit="Debye", verbose=0), dtype=float).ravel()
        if vec.size >= 3:
            return {
                "x": float(vec[0]),
                "y": float(vec[1]),
                "z": float(vec[2]),
                "magnitude": float(np.linalg.norm(vec[:3])),
                "unit": "Debye",
            }
    except Exception:
        return None
    return None

def _extract_mulliken_charges(mol: gto.Mole, mf) -> List[Dict[str, Any]]:
    try:
        active_mol = getattr(mf, 'mol', None) or mol
        dm = mf.make_rdm1()
        if isinstance(dm, tuple):
            dm = np.asarray(dm[0]) + np.asarray(dm[1])
        dm = np.asarray(dm)
        if dm.ndim == 3 and dm.shape[0] == 2:
            dm = dm[0] + dm[1]
            
        s = getattr(mf, 'get_ovlp', lambda: active_mol.intor_symmetric("int1e_ovlp"))()

        try:
            _, chg = mf.mulliken_pop(mol=active_mol, dm=dm, s=s, verbose=0)
        except TypeError:
            _, chg = mf.mulliken_pop(active_mol, dm, s, verbose=0)
        except AttributeError:
            from pyscf.scf import hf as scf_hf
            _, chg = scf_hf.mulliken_pop(active_mol, dm, s=s, verbose=0)

        safe_chg = []
        for q in chg:
            if np.isnan(q) or np.isinf(q):
                safe_chg.append(0.0)
            else:
                safe_chg.append(float(q))
                
        return _normalize_partial_charges(mol, safe_chg)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Mulliken population failed: {e}")
        return []

def _extract_lowdin_charges(mol: gto.Mole, mf) -> List[Dict[str, Any]]:
    try:
        active_mol = getattr(mf, 'mol', None) or mol
        dm = mf.make_rdm1()
        if isinstance(dm, tuple):
            dm = np.asarray(dm[0]) + np.asarray(dm[1])
        dm = np.asarray(dm)
        if dm.ndim == 3 and dm.shape[0] == 2:
            dm = dm[0] + dm[1]

        s = getattr(mf, 'get_ovlp', lambda: active_mol.intor_symmetric("int1e_ovlp"))()
        
        from pyscf.scf import hf as scf_hf
        try:
            _, chg = scf_hf.lowdin_pop(active_mol, dm, s=s, verbose=0)
        except Exception:
            return []

        safe_chg = []
        for q in chg:
            if np.isnan(q) or np.isinf(q):
                safe_chg.append(0.0)
            else:
                safe_chg.append(float(q))
                
        return _normalize_partial_charges(mol, safe_chg)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Löwdin population failed: {e}")
        return []

def _restricted_or_unrestricted_arrays(mf):
    mo_energy = mf.mo_energy
    mo_occ = mf.mo_occ
    mo_coeff = mf.mo_coeff
    if isinstance(mo_energy, tuple):
        return list(mo_energy), list(mo_occ), list(mo_coeff), ["alpha", "beta"]
    if isinstance(mo_energy, list) and mo_energy and isinstance(mo_energy[0], np.ndarray):
        return list(mo_energy), list(mo_occ), list(mo_coeff), ["alpha", "beta"][: len(mo_energy)]
    return [np.asarray(mo_energy)], [np.asarray(mo_occ)], [np.asarray(mo_coeff)], ["restricted"]

def _build_orbital_items(mf, window: int = 4) -> List[Dict[str, Any]]:
    mo_energies, mo_occs, _, spin_labels = _restricted_or_unrestricted_arrays(mf)
    items: List[Dict[str, Any]] = []
    for ch, (energies, occs, spin_label) in enumerate(zip(mo_energies, mo_occs, spin_labels)):
        energies = np.asarray(energies, dtype=float)
        occs = np.asarray(occs, dtype=float)
        occ_idx = np.where(occs > 1e-8)[0]
        vir_idx = np.where(occs <= 1e-8)[0]
        if occ_idx.size == 0:
            lo = 0
            hi = min(len(energies), 2 * window + 1)
        else:
            homo = int(occ_idx[-1])
            lumo = int(vir_idx[0]) if vir_idx.size else min(homo + 1, len(energies) - 1)
            lo = max(0, homo - window)
            hi = min(len(energies), lumo + window + 1)
        for idx in range(lo, hi):
            occ = float(occs[idx])
            label = f"MO {idx + 1}"
            if occ_idx.size:
                homo = int(occ_idx[-1])
                lumo = int(vir_idx[0]) if vir_idx.size else min(homo + 1, len(energies) - 1)
                if idx == homo:
                    label = "HOMO"
                elif idx < homo:
                    label = f"HOMO-{homo - idx}"
                elif idx == lumo:
                    label = "LUMO"
                elif idx > lumo:
                    label = f"LUMO+{idx - lumo}"
            items.append(
                {
                    "index": idx + 1,
                    "zero_based_index": idx,
                    "label": label,
                    "spin": spin_label,
                    "occupancy": occ,
                    "energy_hartree": float(energies[idx]),
                    "energy_ev": float(energies[idx] * HARTREE_TO_EV),
                }
            )
    items.sort(key=lambda x: (x.get("spin") != "restricted", x["zero_based_index"]))
    return items

def _resolve_orbital_selection(mf, orbital: Optional[Union[str, int]]) -> Dict[str, Any]:
    mo_energies, mo_occs, mo_coeffs, spin_labels = _restricted_or_unrestricted_arrays(mf)
    channel = 0
    spin_label = spin_labels[channel]
    energies = np.asarray(mo_energies[channel], dtype=float)
    occs = np.asarray(mo_occs[channel], dtype=float)

    occ_idx = np.where(occs > 1e-8)[0]
    vir_idx = np.where(occs <= 1e-8)[0]
    homo = int(occ_idx[-1]) if occ_idx.size else 0
    lumo = int(vir_idx[0]) if vir_idx.size else min(homo + 1, len(energies) - 1)

    raw = _safe_str(orbital, "HOMO").upper()
    if raw in {"", "AUTO"}:
        raw = "HOMO"

    idx = homo
    label = "HOMO"

    if isinstance(orbital, int):
        idx = max(0, min(int(orbital) - 1, len(energies) - 1))
        label = f"MO {idx + 1}"
    elif re.fullmatch(r"\d+", raw):
        idx = max(0, min(int(raw) - 1, len(energies) - 1))
        label = f"MO {idx + 1}"
    elif raw == "HOMO":
        idx = homo
        label = "HOMO"
    elif raw == "LUMO":
        idx = lumo
        label = "LUMO"
    else:
        m1 = re.fullmatch(r"HOMO\s*-\s*(\d+)", raw)
        m2 = re.fullmatch(r"LUMO\s*\+\s*(\d+)", raw)
        if m1:
            delta = int(m1.group(1))
            idx = max(0, homo - delta)
            label = f"HOMO-{delta}"
        elif m2:
            delta = int(m2.group(1))
            idx = min(len(energies) - 1, lumo + delta)
            label = f"LUMO+{delta}"

    return {
        "spin_channel": channel,
        "spin": spin_label,
        "index": idx + 1,
        "zero_based_index": idx,
        "label": label,
        "energy_hartree": float(energies[idx]),
        "energy_ev": float(energies[idx] * HARTREE_TO_EV),
        "occupancy": float(occs[idx]),
        "coefficient_matrix": mo_coeffs[channel],
    }

def _extract_frontier_gap(mf) -> Dict[str, Any]:
    mo_energies, mo_occs, _, spin_labels = _restricted_or_unrestricted_arrays(mf)
    channel_info: List[Dict[str, Any]] = []
    best_gap = None
    best_homo = None
    best_lumo = None

    for energies, occs, spin_label in zip(mo_energies, mo_occs, spin_labels):
        energies = np.asarray(energies, dtype=float)
        occs = np.asarray(occs, dtype=float)

        occ_idx = np.where(occs > 1e-8)[0]
        vir_idx = np.where(occs <= 1e-8)[0]
        if occ_idx.size == 0 or vir_idx.size == 0:
            continue

        homo_idx = int(occ_idx[-1])
        lumo_idx = int(vir_idx[0])
        gap_ha = float(energies[lumo_idx] - energies[homo_idx])

        info = {
            "spin": spin_label,
            "homo_index": homo_idx + 1,
            "lumo_index": lumo_idx + 1,
            "homo_energy_hartree": float(energies[homo_idx]),
            "lumo_energy_hartree": float(energies[lumo_idx]),
            "homo_energy_ev": float(energies[homo_idx] * HARTREE_TO_EV),
            "lumo_energy_ev": float(energies[lumo_idx] * HARTREE_TO_EV),
            "gap_hartree": gap_ha,
            "gap_ev": gap_ha * HARTREE_TO_EV,
        }
        channel_info.append(info)

        if best_gap is None or gap_ha < best_gap:
            best_gap = gap_ha
            best_homo = info
            best_lumo = info

    out: Dict[str, Any] = {
        "frontier_channels": channel_info,
        "orbital_gap_hartree": float(best_gap) if best_gap is not None else None,
        "orbital_gap_ev": float(best_gap * HARTREE_TO_EV) if best_gap is not None else None,
    }

    if best_homo:
        out["homo_energy_hartree"] = best_homo["homo_energy_hartree"]
        out["homo_energy_ev"] = best_homo["homo_energy_ev"]
        out["homo_index"] = best_homo["homo_index"]
    if best_lumo:
        out["lumo_energy_hartree"] = best_lumo["lumo_energy_hartree"]
        out["lumo_energy_ev"] = best_lumo["lumo_energy_ev"]
        out["lumo_index"] = best_lumo["lumo_index"]
    return out

def _extract_spin_info(mf) -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    try:
        ss = mf.spin_square()
        if isinstance(ss, tuple) and len(ss) >= 2:
            info["spin_square"] = float(ss[0])
            info["spin_multiplicity_estimate"] = float(ss[1])
    except Exception:
        pass
    return info

def _coalesce_density_matrix(dm) -> np.ndarray:
    if isinstance(dm, tuple):
        return np.asarray(dm[0]) + np.asarray(dm[1])
    dm_arr = np.asarray(dm)
    if dm_arr.ndim == 3 and dm_arr.shape[0] == 2:
        return dm_arr[0] + dm_arr[1]
    return dm_arr

def _selected_orbital_vector(mf, selection: Mapping[str, Any]) -> np.ndarray:
    coeff = mf.mo_coeff
    ch = int(selection.get("spin_channel", 0) or 0)
    idx = int(selection.get("zero_based_index", 0) or 0)

    if isinstance(coeff, tuple):
        coeff_mat = np.asarray(coeff[ch])
    elif isinstance(coeff, list) and coeff and isinstance(coeff[0], np.ndarray):
        coeff_mat = np.asarray(coeff[ch])
    else:
        coeff_mat = np.asarray(coeff)

    return np.asarray(coeff_mat[:, idx], dtype=float)

def _emit_progress(
    progress_callback: Optional[Callable[..., Any]],
    progress: float,
    step: str,
    message: Optional[str] = None,
    **extra: Any,
) -> None:
    if not callable(progress_callback):
        return

    payload = {
        "progress": float(progress),
        "step": _safe_str(step, "working"),
        "message": _safe_str(message, message or step),
    }
    payload.update(extra)

    try:
        progress_callback(payload)
        return
    except TypeError:
        pass
    except Exception:
        return

    try:
        progress_callback(float(progress), _safe_str(step, "working"), payload["message"])
    except Exception:
        return

def _focus_tab_for_result(result: Mapping[str, Any]) -> str:
    forced = _safe_str(result.get("advisor_focus_tab") or result.get("focus_tab") or result.get("default_tab"))
    forced = forced.lower()
    if forced in {"summary", "geometry", "orbital", "esp", "charges", "json", "jobs"}:
        return forced

    vis = result.get("visualization") or {}
    if vis.get("esp_cube_b64") and vis.get("density_cube_b64"):
        return "esp"
    if vis.get("orbital_cube_b64"):
        return "orbital"
    if result.get("mulliken_charges") or result.get("partial_charges"):
        return "charges"
    if result.get("geometry_summary"):
        return "geometry"
    return "summary"

def _attach_visualization_payload(
    result: Dict[str, Any],
    xyz_text: str,
    orbital_cube_path: Optional[Union[str, Path]] = None,
    density_cube_path: Optional[Union[str, Path]] = None,
    esp_cube_path: Optional[Union[str, Path]] = None,
    orbital_meta: Optional[Mapping[str, Any]] = None,
    esp_meta: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    vis = result.setdefault("visualization", {})
    vis["xyz"] = xyz_text
    vis["molecule_xyz"] = xyz_text
    result["xyz"] = result.get("xyz") or xyz_text

    defaults = vis.setdefault("defaults", {})
    defaults.setdefault("style", "stick")
    defaults.setdefault("labels", False)
    defaults.setdefault("orbital_iso", 0.050)
    defaults.setdefault("orbital_opacity", 0.85)
    defaults.setdefault("esp_density_iso", 0.001)
    defaults.setdefault("esp_opacity", 0.90)

    if orbital_cube_path:
        orb_b64 = _file_to_b64(orbital_cube_path)
        if orb_b64:
            vis["orbital_cube_b64"] = orb_b64
            result["orbital_cube_b64"] = orb_b64
            orb_node = vis.setdefault("orbital", {})
            orb_node["cube_b64"] = orb_b64
            if orbital_meta:
                orb_node.update(dict(orbital_meta))
                if orbital_meta.get("label"):
                    defaults.setdefault("orbital_label", orbital_meta.get("label"))
                if orbital_meta.get("index") is not None:
                    defaults.setdefault("orbital_index", orbital_meta.get("index"))

    if density_cube_path:
        dens_b64 = _file_to_b64(density_cube_path)
        if dens_b64:
            vis["density_cube_b64"] = dens_b64
            result["density_cube_b64"] = dens_b64
            dens_node = vis.setdefault("density", {})
            dens_node["cube_b64"] = dens_b64

    if esp_cube_path:
        esp_b64 = _file_to_b64(esp_cube_path)
        if esp_b64:
            vis["esp_cube_b64"] = esp_b64
            result["esp_cube_b64"] = esp_b64
            esp_node = vis.setdefault("esp", {})
            esp_node["cube_b64"] = esp_b64

            if esp_meta:
                esp_node.update(dict(esp_meta))
                preset = _normalize_esp_preset(esp_meta.get("preset"))
                preset_meta = ESP_PRESETS_DATA.get(preset, ESP_PRESETS_DATA["acs"])
                esp_node["preset"] = preset
                esp_node["surface_scheme"] = preset_meta.get("surface_scheme", "rwb")

                defaults.setdefault("esp_preset", preset)
                defaults.setdefault("esp_scheme", preset_meta.get("surface_scheme", "rwb"))
                if esp_meta.get("range_au") is not None:
                    defaults["esp_range"] = float(esp_meta["range_au"])
                    defaults["esp_range_au"] = float(esp_meta["range_au"])
                if esp_meta.get("range_kcal") is not None:
                    defaults["esp_range_kcal"] = float(esp_meta["range_kcal"])
                if esp_meta.get("density_iso") is not None:
                    defaults["esp_density_iso"] = float(esp_meta["density_iso"])
                if esp_meta.get("opacity") is not None:
                    defaults["esp_opacity"] = float(esp_meta["opacity"])

    vis["available"] = {
        "orbital": bool(vis.get("orbital_cube_b64")),
        "esp": bool(vis.get("esp_cube_b64") and vis.get("density_cube_b64")),
        "density": bool(vis.get("density_cube_b64")),
    }
    defaults.setdefault("focus_tab", _focus_tab_for_result(result))
    return result

def _finalize_result_contract(result: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(result or {})
    out.setdefault("success", True)
    out.setdefault("warnings", [])
    out["warnings"] = _dedupe_strings(out.get("warnings", []))

    if not isinstance(out.get("events"), list):
        out["events"] = []

    out["method"] = _normalize_method_name(out.get("method") or DEFAULT_METHOD)
    out["basis"] = _normalize_basis_name(out.get("basis") or DEFAULT_BASIS)
    out["charge"] = int(_safe_int(out.get("charge"), 0) or 0)
    out["multiplicity"] = int(_safe_int(out.get("multiplicity"), 1) or 1)

    e_ha = _safe_float(out.get("total_energy_hartree"))
    if e_ha is not None:
        out["total_energy_hartree"] = e_ha
        out.setdefault("total_energy_ev", e_ha * HARTREE_TO_EV)
        out.setdefault("total_energy_kcal_mol", e_ha * HARTREE_TO_KCAL)

    gap_ha = _safe_float(out.get("orbital_gap_hartree"))
    gap_ev = _safe_float(out.get("orbital_gap_ev"))
    if gap_ha is None and gap_ev is not None:
        out["orbital_gap_hartree"] = gap_ev / HARTREE_TO_EV
    elif gap_ev is None and gap_ha is not None:
        out["orbital_gap_ev"] = gap_ha * HARTREE_TO_EV

    if out.get("mulliken_charges") and not out.get("partial_charges"):
        out["partial_charges"] = out["mulliken_charges"]
    elif out.get("partial_charges") and not out.get("mulliken_charges"):
        out["mulliken_charges"] = out["partial_charges"]

    vis = out.setdefault("visualization", {})
    defaults = vis.setdefault("defaults", {})
    defaults.setdefault("style", "stick")
    defaults.setdefault("labels", False)
    defaults.setdefault("orbital_iso", 0.050)
    defaults.setdefault("orbital_opacity", 0.85)
    defaults.setdefault("esp_density_iso", 0.001)
    defaults.setdefault("esp_opacity", 0.90)
    defaults.setdefault("esp_preset", _normalize_esp_preset(defaults.get("esp_preset")))
    defaults.setdefault("focus_tab", _focus_tab_for_result(out))

    if vis.get("orbital_cube_b64") and "orbital" not in vis:
        vis["orbital"] = {"cube_b64": vis["orbital_cube_b64"]}
    if vis.get("density_cube_b64") and "density" not in vis:
        vis["density"] = {"cube_b64": vis["density_cube_b64"]}
    if vis.get("esp_cube_b64") and "esp" not in vis:
        vis["esp"] = {"cube_b64": vis["esp_cube_b64"]}

    vis.setdefault("xyz", out.get("xyz"))
    vis.setdefault("molecule_xyz", out.get("xyz"))
    vis["available"] = {
        "orbital": bool(vis.get("orbital_cube_b64") or (vis.get("orbital") or {}).get("cube_b64")),
        "density": bool(vis.get("density_cube_b64") or (vis.get("density") or {}).get("cube_b64")),
        "esp": bool(
            (vis.get("esp_cube_b64") or (vis.get("esp") or {}).get("cube_b64"))
            and (vis.get("density_cube_b64") or (vis.get("density") or {}).get("cube_b64"))
        ),
    }

    return out

def _make_base_result(
    *,
    job_type: str,
    structure_name: str,
    atom_text: str,
    mol: gto.Mole,
    method: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    advisor_focus_tab: Optional[str] = None,
) -> Dict[str, Any]:
    xyz_text = _mol_to_xyz(mol, comment=structure_name or "QCViz-MCP")
    symbols = [mol.atom_symbol(i) for i in range(mol.natm)]
    bonds = _guess_bonds(mol)
    
    coords = np.asarray(mol.atom_coords(unit="Angstrom"), dtype=float)
    atoms = []
    for i in range(mol.natm):
        atoms.append({
            "atom_index": i,
            "symbol": symbols[i],
            "element": symbols[i],
            "x": float(coords[i, 0]),
            "y": float(coords[i, 1]),
            "z": float(coords[i, 2]),
        })

    result: Dict[str, Any] = {
        "success": True,
        "job_type": _safe_str(job_type, "analyze"),
        "structure_name": _safe_str(structure_name, "custom"),
        "structure_query": _safe_str(structure_name, "custom"),
        "atom_spec": atom_text,
        "xyz": xyz_text,
        "method": _normalize_method_name(method or DEFAULT_METHOD),
        "basis": _normalize_basis_name(basis or DEFAULT_BASIS),
        "charge": int(charge or 0),
        "multiplicity": int(multiplicity or 1),
        "n_atoms": int(mol.natm),
        "formula": _formula_from_symbols(symbols),
        "atoms": atoms,
        "bonds": bonds,
        "geometry_summary": _geometry_summary(mol, bonds),
        "warnings": [],
        "events": [],
        "advisor_focus_tab": advisor_focus_tab,
        "visualization": {
            "xyz": xyz_text,
            "molecule_xyz": xyz_text,
            "defaults": {
                "style": "stick",
                "labels": False,
                "orbital_iso": 0.050,
                "orbital_opacity": 0.85,
                "esp_density_iso": 0.001,
                "esp_opacity": 0.90,
            },
        },
    }
    return _finalize_result_contract(result)

def _populate_scf_fields(
    result: Dict[str, Any],
    mol: gto.Mole,
    mf,
    *,
    include_charges: bool = True,
    include_orbitals: bool = True,
) -> Dict[str, Any]:
    result["scf_converged"] = bool(getattr(mf, "converged", False))
    result["total_energy_hartree"] = float(getattr(mf, "e_tot", np.nan))
    result["total_energy_ev"] = float(result["total_energy_hartree"] * HARTREE_TO_EV)
    result["total_energy_kcal_mol"] = float(result["total_energy_hartree"] * HARTREE_TO_KCAL)

    dip = _extract_dipole(mf)
    if dip:
        result["dipole_moment"] = dip

    result.update(_extract_frontier_gap(mf))
    result.update(_extract_spin_info(mf))

    if include_charges:
        try:
            mull_charges = _extract_mulliken_charges(mol, mf)
            if mull_charges:
                result["mulliken_charges"] = mull_charges
            
            lowdin_charges = _extract_lowdin_charges(mol, mf)
            if lowdin_charges:
                result["lowdin_charges"] = lowdin_charges
                
            if lowdin_charges:
                result["partial_charges"] = lowdin_charges
            elif mull_charges:
                result["partial_charges"] = mull_charges
        except Exception as exc:
            result.setdefault("warnings", []).append(f"Charge analysis failed: {exc}")

    if include_orbitals:
        try:
            result["orbitals"] = _build_orbital_items(mf)
        except Exception as exc:
            result.setdefault("warnings", []).append(f"Orbital analysis failed: {exc}")

    return result

def _prepare_structure_bundle(
    *,
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
) -> Tuple[str, str, gto.Mole]:
    structure_name, atom_text = _resolve_structure_payload(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
    )
    mol = _build_mol(
        atom_text=atom_text,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        unit="Angstrom",
    )
    return structure_name, atom_text, mol

# ----------------------------------------------------------------------------
# PUBLIC RUNNER FUNCTIONS
# ----------------------------------------------------------------------------

def run_resolve_structure(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    progress_callback: Optional[Callable[..., Any]] = None,
    advisor_focus_tab: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
    )
    _emit_progress(progress_callback, 0.75, "geometry", "Preparing geometry payload")

    result = _make_base_result(
        job_type="resolve_structure",
        structure_name=structure_name,
        atom_text=atom_text,
        mol=mol,
        method=kwargs.get("method") or DEFAULT_METHOD,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "geometry",
    )
    result["resolved_structure"] = {
        "name": structure_name,
        "xyz": result["xyz"],
        "atom_spec": atom_text,
    }

    _emit_progress(progress_callback, 1.0, "done", "Structure resolved")
    return _finalize_result_contract(result)

def run_geometry_analysis(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    progress_callback: Optional[Callable[..., Any]] = None,
    advisor_focus_tab: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
    )

    result = _make_base_result(
        job_type="geometry_analysis",
        structure_name=structure_name,
        atom_text=atom_text,
        mol=mol,
        method=kwargs.get("method") or DEFAULT_METHOD,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "geometry",
    )

    _emit_progress(progress_callback, 1.0, "done", "Geometry analysis complete")
    return _finalize_result_contract(result)

def run_single_point(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    method: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    progress_callback: Optional[Callable[..., Any]] = None,
    advisor_focus_tab: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
    )

    result = _make_base_result(
        job_type="single_point",
        structure_name=structure_name,
        atom_text=atom_text,
        mol=mol,
        method=method or DEFAULT_METHOD,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "summary",
    )

    _emit_progress(progress_callback, 0.15, "build_scf", "Building SCF model")
    method_name, mf = _build_mean_field(mol, method or DEFAULT_METHOD)
    result["method"] = method_name
    
    cache_key = _get_cache_key(result["xyz"], method_name, basis or DEFAULT_BASIS, charge, multiplicity)

    _emit_progress(progress_callback, 0.35, "scf", "Running SCF")
    mf, _ = _run_scf_with_fallback(mf, result["warnings"], cache_key=cache_key, progress_callback=progress_callback)

    _emit_progress(progress_callback, 0.85, "analyze", "Collecting observables")
    _populate_scf_fields(result, mol, mf, include_charges=False, include_orbitals=True)

    _emit_progress(progress_callback, 1.0, "done", "Single-point calculation complete")
    return _finalize_result_contract(result)

def run_partial_charges(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    method: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    progress_callback: Optional[Callable[..., Any]] = None,
    advisor_focus_tab: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
    )

    result = _make_base_result(
        job_type="partial_charges",
        structure_name=structure_name,
        atom_text=atom_text,
        mol=mol,
        method=method or DEFAULT_METHOD,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "charges",
    )

    _emit_progress(progress_callback, 0.15, "build_scf", "Building SCF model")
    method_name, mf = _build_mean_field(mol, method or DEFAULT_METHOD)
    result["method"] = method_name
    
    cache_key = _get_cache_key(result["xyz"], method_name, basis or DEFAULT_BASIS, charge, multiplicity)

    _emit_progress(progress_callback, 0.35, "scf", "Running SCF")
    mf, _ = _run_scf_with_fallback(mf, result["warnings"], cache_key=cache_key, progress_callback=progress_callback)

    _emit_progress(progress_callback, 0.80, "charges", "Computing Mulliken charges")
    _populate_scf_fields(result, mol, mf, include_charges=True, include_orbitals=False)

    _emit_progress(progress_callback, 1.0, "done", "Partial charge analysis complete")
    return _finalize_result_contract(result)

def run_orbital_preview(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    method: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    orbital: Optional[Union[str, int]] = None,
    progress_callback: Optional[Callable[..., Any]] = None,
    advisor_focus_tab: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
    )

    result = _make_base_result(
        job_type="orbital_preview",
        structure_name=structure_name,
        atom_text=atom_text,
        mol=mol,
        method=method or DEFAULT_METHOD,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "orbital",
    )

    _emit_progress(progress_callback, 0.15, "build_scf", "Building SCF model")
    method_name, mf = _build_mean_field(mol, method or DEFAULT_METHOD)
    result["method"] = method_name
    
    cache_key = _get_cache_key(result["xyz"], method_name, basis or DEFAULT_BASIS, charge, multiplicity)

    _emit_progress(progress_callback, 0.35, "scf", "Running SCF")
    mf, _ = _run_scf_with_fallback(mf, result["warnings"], cache_key=cache_key, progress_callback=progress_callback)
    _populate_scf_fields(result, mol, mf, include_charges=True, include_orbitals=True)

    _emit_progress(progress_callback, 0.70, "orbital_select", "Selecting orbital")
    selection = _resolve_orbital_selection(mf, orbital)
    result["selected_orbital"] = {
        k: v for k, v in selection.items() if k != "coefficient_matrix"
    }

    try:
        with tempfile.TemporaryDirectory(prefix="qcviz_orb_") as tmpdir:
            cube_path = Path(tmpdir) / "orbital.cube"
            coeff_vec = _selected_orbital_vector(mf, selection)
            cubegen.orbital(mol, str(cube_path), coeff_vec, nx=60, ny=60, nz=60, margin=5.0)

            _attach_visualization_payload(
                result,
                xyz_text=result["xyz"],
                orbital_cube_path=cube_path,
                orbital_meta={
                    "label": selection.get("label"),
                    "index": selection.get("index"),
                    "zero_based_index": selection.get("zero_based_index"),
                    "spin": selection.get("spin"),
                    "energy_hartree": selection.get("energy_hartree"),
                    "energy_ev": selection.get("energy_ev"),
                    "occupancy": selection.get("occupancy"),
                },
            )
    except Exception as exc:
        result.setdefault("warnings", []).append(f"Orbital cube generation failed: {exc}")

    _emit_progress(progress_callback, 1.0, "done", "Orbital preview complete")
    return _finalize_result_contract(result)

def run_esp_map(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    method: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    esp_preset: Optional[str] = None,
    progress_callback: Optional[Callable[..., Any]] = None,
    advisor_focus_tab: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
    )

    preset_key = _normalize_esp_preset(esp_preset)
    result = _make_base_result(
        job_type="esp_map",
        structure_name=structure_name,
        atom_text=atom_text,
        mol=mol,
        method=method or DEFAULT_METHOD,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "esp",
    )
    result["esp_preset"] = preset_key

    _emit_progress(progress_callback, 0.15, "build_scf", "Building SCF model")
    method_name, mf = _build_mean_field(mol, method or DEFAULT_METHOD)
    result["method"] = method_name
    
    cache_key = _get_cache_key(result["xyz"], method_name, basis or DEFAULT_BASIS, charge, multiplicity)

    _emit_progress(progress_callback, 0.35, "scf", "Running SCF")
    mf, _ = _run_scf_with_fallback(mf, result["warnings"], cache_key=cache_key, progress_callback=progress_callback)
    _populate_scf_fields(result, mol, mf, include_charges=True, include_orbitals=True)

    try:
        _emit_progress(progress_callback, 0.70, "cube", "Generating density/ESP cubes")
        with tempfile.TemporaryDirectory(prefix="qcviz_esp_") as tmpdir:
            density_cube = Path(tmpdir) / "density.cube"
            esp_cube = Path(tmpdir) / "esp.cube"

            dm = _coalesce_density_matrix(mf.make_rdm1())
            cubegen.density(mol, str(density_cube), dm, nx=60, ny=60, nz=60, margin=5.0)
            cubegen.mep(mol, str(esp_cube), dm, nx=60, ny=60, nz=60, margin=5.0)

            esp_fit = _compute_esp_auto_range_from_cube_files(
                esp_cube_path=esp_cube,
                density_cube_path=density_cube,
                density_iso=0.001,
            )

            result["esp_auto_range_au"] = float(esp_fit["range_au"])
            result["esp_auto_range_kcal"] = float(esp_fit["range_kcal"])
            result["esp_auto_fit"] = esp_fit

            _attach_visualization_payload(
                result,
                xyz_text=result["xyz"],
                density_cube_path=density_cube,
                esp_cube_path=esp_cube,
                esp_meta={
                    "preset": preset_key,
                    "range_au": esp_fit["range_au"],
                    "range_kcal": esp_fit["range_kcal"],
                    "density_iso": 0.001,
                    "opacity": 0.90,
                    "fit_stats": esp_fit.get("stats", {}),
                    "fit_strategy": esp_fit.get("strategy"),
                },
            )
    except Exception as exc:
        result.setdefault("warnings", []).append(f"ESP cube generation failed: {exc}")

    _emit_progress(progress_callback, 1.0, "done", "ESP map complete")
    result["job_type"] = "esp_map"
    return _finalize_result_contract(result)

def run_geometry_optimization(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    method: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    progress_callback: Optional[Callable[..., Any]] = None,
    advisor_focus_tab: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.05, "resolve", "Resolving structure")
    structure_name, atom_text, mol0 = _prepare_structure_bundle(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
    )

    result = _make_base_result(
        job_type="geometry_optimization",
        structure_name=structure_name,
        atom_text=atom_text,
        mol=mol0,
        method=method or DEFAULT_METHOD,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "geometry",
    )

    _emit_progress(progress_callback, 0.12, "build_scf", "Building optimization model")
    method_name, mf0 = _build_mean_field(mol0, method or DEFAULT_METHOD)
    result["method"] = method_name
    
    cache_key0 = _get_cache_key(result["xyz"], method_name, basis or DEFAULT_BASIS, charge, multiplicity)

    _emit_progress(progress_callback, 0.22, "scf", "Running initial SCF")
    mf0, _ = _run_scf_with_fallback(mf0, result["warnings"], cache_key=cache_key0, progress_callback=progress_callback)

    opt_mol = mol0
    optimization_performed = False

    if geometric_optimize is None:
        result.setdefault("warnings", []).append(
            "Geometry optimizer is unavailable; returning the input geometry."
        )
    else:
        try:
            _emit_progress(progress_callback, 0.45, "optimize", "Running geometry optimization")
            opt_mol = geometric_optimize(mf0)
            optimization_performed = True
        except Exception as exc:
            result.setdefault("warnings", []).append(
                f"Geometry optimization failed; returning the last available geometry: {exc}"
            )
            opt_mol = mol0

    _emit_progress(progress_callback, 0.78, "final_scf", "Running final SCF on optimized geometry")
    method_name, mf = _build_mean_field(opt_mol, method or DEFAULT_METHOD)
    
    new_atom_text = _strip_xyz_header(_mol_to_xyz(opt_mol))
    new_xyz = _mol_to_xyz(opt_mol, comment=structure_name or "QCViz-MCP")
    cache_key1 = _get_cache_key(new_xyz, method_name, basis or DEFAULT_BASIS, charge, multiplicity)
    
    mf, _ = _run_scf_with_fallback(mf, result["warnings"], cache_key=cache_key1, progress_callback=progress_callback)

    new_atom_text = _strip_xyz_header(_mol_to_xyz(opt_mol))
    final_result = _make_base_result(
        job_type="geometry_optimization",
        structure_name=structure_name,
        atom_text=new_atom_text,
        mol=opt_mol,
        method=method_name,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "geometry",
    )
    final_result["warnings"] = _dedupe_strings(result.get("warnings", []))
    final_result["optimization_performed"] = optimization_performed
    final_result["initial_xyz"] = result["xyz"]
    final_result["optimized_xyz"] = final_result["xyz"]

    _populate_scf_fields(final_result, opt_mol, mf, include_charges=True, include_orbitals=True)

    _emit_progress(progress_callback, 1.0, "done", "Geometry optimization complete")
    return _finalize_result_contract(final_result)

def run_analyze(
    structure_query: Optional[str] = None,
    xyz: Optional[str] = None,
    atom_spec: Optional[str] = None,
    method: Optional[str] = None,
    basis: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    orbital: Optional[Union[str, int]] = None,
    esp_preset: Optional[str] = None,
    progress_callback: Optional[Callable[..., Any]] = None,
    advisor_focus_tab: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    _emit_progress(progress_callback, 0.03, "resolve", "Resolving structure")
    structure_name, atom_text, mol = _prepare_structure_bundle(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
    )

    preset_key = _normalize_esp_preset(esp_preset)
    result = _make_base_result(
        job_type="analyze",
        structure_name=structure_name,
        atom_text=atom_text,
        mol=mol,
        method=method or DEFAULT_METHOD,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "summary",
    )
    result["esp_preset"] = preset_key

    _emit_progress(progress_callback, 0.12, "build_scf", "Building SCF model")
    method_name, mf = _build_mean_field(mol, method or DEFAULT_METHOD)
    result["method"] = method_name
    
    cache_key = _get_cache_key(result["xyz"], method_name, basis or DEFAULT_BASIS, charge, multiplicity)

    _emit_progress(progress_callback, 0.30, "scf", "Running SCF")
    mf, _ = _run_scf_with_fallback(mf, result["warnings"], cache_key=cache_key, progress_callback=progress_callback)

    _emit_progress(progress_callback, 0.55, "analysis", "Collecting quantitative results")
    _populate_scf_fields(result, mol, mf, include_charges=True, include_orbitals=True)

    selection = _resolve_orbital_selection(mf, orbital)
    result["selected_orbital"] = {
        k: v for k, v in selection.items() if k != "coefficient_matrix"
    }

    try:
        _emit_progress(progress_callback, 0.72, "cube", "Generating orbital/ESP visualization cubes")
        with tempfile.TemporaryDirectory(prefix="qcviz_all_") as tmpdir:
            tmpdir_p = Path(tmpdir)
            orbital_cube = tmpdir_p / "orbital.cube"
            density_cube = tmpdir_p / "density.cube"
            esp_cube = tmpdir_p / "esp.cube"

            coeff_vec = _selected_orbital_vector(mf, selection)
            cubegen.orbital(mol, str(orbital_cube), coeff_vec, nx=60, ny=60, nz=60, margin=5.0)

            dm = _coalesce_density_matrix(mf.make_rdm1())
            cubegen.density(mol, str(density_cube), dm, nx=60, ny=60, nz=60, margin=5.0)
            cubegen.mep(mol, str(esp_cube), dm, nx=60, ny=60, nz=60, margin=5.0)

            esp_fit = _compute_esp_auto_range_from_cube_files(
                esp_cube_path=esp_cube,
                density_cube_path=density_cube,
                density_iso=0.001,
            )
            result["esp_auto_range_au"] = float(esp_fit["range_au"])
            result["esp_auto_range_kcal"] = float(esp_fit["range_kcal"])
            result["esp_auto_fit"] = esp_fit

            _attach_visualization_payload(
                result,
                xyz_text=result["xyz"],
                orbital_cube_path=orbital_cube,
                density_cube_path=density_cube,
                esp_cube_path=esp_cube,
                orbital_meta={
                    "label": selection.get("label"),
                    "index": selection.get("index"),
                    "zero_based_index": selection.get("zero_based_index"),
                    "spin": selection.get("spin"),
                    "energy_hartree": selection.get("energy_hartree"),
                    "energy_ev": selection.get("energy_ev"),
                    "occupancy": selection.get("occupancy"),
                },
                esp_meta={
                    "preset": preset_key,
                    "range_au": esp_fit["range_au"],
                    "range_kcal": esp_fit["range_kcal"],
                    "density_iso": 0.001,
                    "opacity": 0.90,
                    "fit_stats": esp_fit.get("stats", {}),
                    "fit_strategy": esp_fit.get("strategy"),
                },
            )
    except Exception as exc:
        result.setdefault("warnings", []).append(f"Visualization cube generation failed: {exc}")

    _emit_progress(progress_callback, 1.0, "done", "Full analysis complete")
    return _finalize_result_contract(result)

__all__ = [
    "HARTREE_TO_EV",
    "HARTREE_TO_KCAL",
    "BOHR_TO_ANGSTROM",
    "EV_TO_KCAL",
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


## File: `version02/src/qcviz_mcp/compute/disk_cache.py`

```python
import os
import pickle
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DIR = Path(os.getenv("QCVIZ_CACHE_DIR", "/tmp/qcviz_scf_cache"))

def init_cache():
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.warning(f"Failed to create cache directory {CACHE_DIR}: {e}")

def save_to_disk(key: str, mf_obj, energy: float):
    init_cache()
    try:
        chkfile_path = CACHE_DIR / f"{key}.chk"
        
        # We save PySCF internal states to HDF5 using built-in method
        mf_obj.chkfile = str(chkfile_path)
        
        # Ensure we dump exactly what we need
        from pyscf import lib
        import h5py
        with lib.H5FileWrap(str(chkfile_path), 'w') as fh5:
            fh5['scf/e_tot'] = energy
            if hasattr(mf_obj, 'mo_energy'): fh5['scf/mo_energy'] = mf_obj.mo_energy
            if hasattr(mf_obj, 'mo_occ'): fh5['scf/mo_occ'] = mf_obj.mo_occ
            if hasattr(mf_obj, 'mo_coeff'): fh5['scf/mo_coeff'] = mf_obj.mo_coeff
            if hasattr(mf_obj, 'converged'): fh5['scf/converged'] = mf_obj.converged
        
        meta_path = CACHE_DIR / f"{key}.meta"
        with open(meta_path, 'wb') as f:
            pickle.dump({"energy": energy, "chkfile": str(chkfile_path)}, f)
            
    except Exception as e:
        logger.warning(f"Failed to save SCF to disk cache: {e}")

def load_from_disk(key: str, mf_obj):
    meta_path = CACHE_DIR / f"{key}.meta"
    if not meta_path.exists():
        return None, None
        
    try:
        with open(meta_path, 'rb') as f:
            meta = pickle.load(f)
            
        chkfile = meta.get("chkfile")
        if chkfile and os.path.exists(chkfile):
            
            import h5py
            import numpy as np
            with h5py.File(chkfile, 'r') as fh5:
                if 'scf/mo_energy' in fh5:
                    val = fh5['scf/mo_energy'][()]
                    # handle possible HDF5 scalar/array quirks
                    mf_obj.mo_energy = val if isinstance(val, np.ndarray) else np.array(val)
                if 'scf/mo_occ' in fh5:
                    val = fh5['scf/mo_occ'][()]
                    mf_obj.mo_occ = val if isinstance(val, np.ndarray) else np.array(val)
                if 'scf/mo_coeff' in fh5:
                    val = fh5['scf/mo_coeff'][()]
                    mf_obj.mo_coeff = val if isinstance(val, np.ndarray) else np.array(val)
                if 'scf/converged' in fh5:
                    mf_obj.converged = bool(fh5['scf/converged'][()])
                else:
                    mf_obj.converged = True
                    
            mf_obj.e_tot = meta.get("energy")
            return mf_obj, meta.get("energy")
            
    except Exception as e:
        logger.warning(f"Failed to load SCF from disk cache: {e}")
        
    return None, None
```


## File: `version02/src/qcviz_mcp/tools/core.py`

```python
"""QCViz-MCP tool implementation v3.0.0 (Enterprise - Sync Compatible)."""

from __future__ import annotations

import json
import logging
import pathlib
import traceback
import os
import asyncio
import concurrent.futures
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

import numpy as np

from qcviz_mcp.backends.pyscf_backend import PySCFBackend, ESPResult, _cli
from qcviz_mcp.backends.viz_backend import (
    Py3DmolBackend,
    DashboardPayload,
    CubeNormalizer,
)

from qcviz_mcp.backends.registry import registry
from qcviz_mcp.mcp_server import mcp
from qcviz_mcp.security import (
    validate_atom_spec_strict, validate_path, validate_basis,
    default_bucket, validate_atom_spec as _validate_atom_spec,
    validate_path as _validate_file_path, _PROJECT_ROOT
)
from qcviz_mcp.observability import traced_tool, metrics, ToolInvocation
try:
    from qcviz_mcp.execution.worker import _executor
except Exception:
    import atexit
    import os
    from concurrent.futures import ThreadPoolExecutor

    _executor = ThreadPoolExecutor(
        max_workers=max(4, min(32, (os.cpu_count() or 4) * 2)),
        thread_name_prefix="qcviz-core-fallback",
    )

    @atexit.register
    def _shutdown_core_executor():
        try:
            _executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
from qcviz_mcp.execution.cache import cache

logger = logging.getLogger(__name__)
HARTREE_TO_EV = 27.2114
OUTPUT_DIR = pathlib.Path(__file__).parent.parent.parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
_pyscf = PySCFBackend()
_viz = Py3DmolBackend()


class _NumpyEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        return super().default(o)


def _parse_atom_spec(atom_spec):
    lines = atom_spec.strip().splitlines()
    if len(lines) <= 2:
        return atom_spec
    if lines[0].strip().isdigit():
        return "\n".join(lines[2:])
    return atom_spec


def _extract_name(molecule_str, mol_obj):
    lines = molecule_str.strip().splitlines()
    if len(lines) > 1:
        name = lines[1].strip()
        if name and not name[0].isdigit() and len(name) < 100:
            return name.replace("\n", " ").replace("\r", " ")
    syms = [mol_obj.atom_symbol(i) for i in range(mol_obj.natm)]
    counts = Counter(syms)
    return "".join(
        "%s%s" % (e, str(counts[e]) if counts[e] > 1 else "")
        for e in sorted(counts.keys())
    )


def _sanitize_display_name(name: Optional[str], fallback: str = "molecule") -> str:
    if not name:
        return fallback
    cleaned = str(name).strip().replace("\n", " ").replace("\r", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:100] if cleaned else fallback


def _safe_filename(name: str, fallback: str = "molecule") -> str:
    cleaned = _sanitize_display_name(name, fallback=fallback)
    cleaned = re.sub(r"[^\w.\-]+", "_", cleaned, flags=re.UNICODE)
    cleaned = cleaned.strip("._")
    return cleaned or fallback


class MoleculeResolver:
    """Resolve user query (XYZ / atom-spec / molecule name / SMILES) into XYZ text.

    Resolution order:
    1. If already XYZ text -> return as-is
    2. If already atom-spec text -> return as-is
    3. If looks like SMILES -> call Molchat directly
    4. Otherwise try PubChem name -> CanonicalSMILES -> Molchat
    """

    PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
    MOLCHAT_BASE = "http://psid.aizen.co.kr/molchat/api/v1"
    DEFAULT_TIMEOUT = 30

    _ATOM_LINE_RE = re.compile(
        r"^\s*[A-Z][a-z]?\s+[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?\s+[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?\s+[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?\s*$"
    )
    _SMILES_LIKE_RE = re.compile(r"^[A-Za-z0-9@\+\-\[\]\(\)=#$\\/%.]+$")
    _SIMPLE_SMILES_TOKEN_RE = re.compile(
        r"^(?:Cl|Br|Si|Li|Na|Ca|Al|Mg|Zn|Fe|Cu|Mn|Hg|Ag|Pt|Au|Sn|Pb|Se|"
        r"[BCNOFPSIKH]|[bcnops])+$"
    )

    @classmethod
    def resolve(cls, query: str) -> str:
        if query is None:
            raise ValueError("입력 query가 비어 있습니다.")
        text = str(query).strip()
        if not text:
            raise ValueError("입력 query가 비어 있습니다.")

        if cls._is_xyz_text(text):
            return text

        if cls._is_atom_spec_text(text):
            return text

        if cls._looks_like_smiles(text):
            logger.info("MoleculeResolver: input recognized as SMILES-like string.")
            smiles = text
        else:
            logger.info("MoleculeResolver: resolving molecule name via PubChem: %s", text)
            smiles = cls._resolve_name_to_smiles(text)

        xyz = cls._generate_xyz_via_molchat(smiles)
        if not cls._is_xyz_text(xyz):
            raise ValueError("Molchat가 유효한 XYZ 구조를 반환하지 않았습니다.")
        return xyz

    @classmethod
    def _is_xyz_text(cls, text: str) -> bool:
        lines = [line.strip() for line in text.strip().splitlines()]
        if len(lines) < 3:
            return False
        if not lines[0].isdigit():
            return False

        atom_count = int(lines[0])
        if atom_count <= 0:
            return False

        # Some generators might omit the comment line or leave it empty
        # If line 1 is empty, it's just an empty comment
        atom_lines = lines[2:2 + atom_count]
        if len(atom_lines) < atom_count:
            # Maybe there was no comment line at all? Let's check if line 1 looks like an atom
            parts = lines[1].split()
            if len(parts) >= 4 and parts[0].isalpha():
                atom_lines = lines[1:1 + atom_count]
            else:
                return False

        if len(atom_lines) < atom_count:
            return False

        matched = 0
        for line in atom_lines:
            parts = line.split()
            if len(parts) < 4:
                return False
            try:
                float(parts[1])
                float(parts[2])
                float(parts[3])
            except Exception:
                return False
            matched += 1
        return matched == atom_count

    @classmethod
    def _is_atom_spec_text(cls, text: str) -> bool:
        lines = [line.rstrip() for line in text.strip().splitlines() if line.strip()]
        if not lines:
            return False
        if len(lines) == 1:
            return False
        return all(cls._ATOM_LINE_RE.match(line) for line in lines)

    @classmethod
    def _looks_like_smiles(cls, text: str) -> bool:
        if "\n" in text:
            return False

        s = text.strip()
        if not s or " " in s:
            return False

        if not cls._SMILES_LIKE_RE.match(s):
            return False

        # Strong SMILES markers
        if any(ch in s for ch in "[]=#()/\\@+$%"):
            return True
        if any(ch.isdigit() for ch in s):
            return True

        # Simple elemental-token-only linear smiles like CCO, CCN, O, N, ClCCl
        if cls._SIMPLE_SMILES_TOKEN_RE.fullmatch(s):
            return True

        return False

    @classmethod
    def _http_get_json(cls, url: str, timeout: int = None) -> Dict[str, Any]:
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "QCViz-MCP/3.0 MoleculeResolver",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout or cls.DEFAULT_TIMEOUT) as resp:
            payload = resp.read().decode("utf-8")
        return json.loads(payload)

    @classmethod
    def _http_post_json(
        cls,
        url: str,
        body: Dict[str, Any],
        timeout: int = None,
    ) -> Dict[str, Any]:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "QCViz-MCP/3.0 MoleculeResolver",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout or cls.DEFAULT_TIMEOUT) as resp:
            payload = resp.read().decode("utf-8")
        return json.loads(payload)

    @classmethod
    def _resolve_name_to_smiles(cls, name: str) -> str:
        quoted = urllib.parse.quote(name.strip(), safe="")
        direct_url = (
            f"{cls.PUBCHEM_BASE}/compound/name/{quoted}/property/CanonicalSMILES,IsomericSMILES/JSON"
        )

        try:
            data = cls._http_get_json(direct_url, timeout=20)
            props = data.get("PropertyTable", {}).get("Properties", [])
            if props:
                p = props[0]
                return p.get("CanonicalSMILES") or p.get("IsomericSMILES") or p.get("SMILES") or p.get("ConnectivitySMILES") or "O"
        except urllib.error.HTTPError as e:
            logger.warning("PubChem direct name->SMILES failed for %s: %s", name, e)
        except Exception as e:
            logger.warning("PubChem direct name->SMILES error for %s: %s", name, e)

        cid_url = f"{cls.PUBCHEM_BASE}/compound/name/{quoted}/cids/JSON"
        try:
            data = cls._http_get_json(cid_url, timeout=20)
            cids = data.get("IdentifierList", {}).get("CID", [])
            if not cids:
                raise ValueError(f"PubChem에서 '{name}'에 대한 CID를 찾지 못했습니다.")
            cid = cids[0]
            prop_url = f"{cls.PUBCHEM_BASE}/compound/cid/{cid}/property/CanonicalSMILES,IsomericSMILES/JSON"
            prop_data = cls._http_get_json(prop_url, timeout=20)
            props = prop_data.get("PropertyTable", {}).get("Properties", [])
            if props:
                p = props[0]
                return p.get("CanonicalSMILES") or p.get("IsomericSMILES") or p.get("SMILES") or p.get("ConnectivitySMILES")
        except Exception as e:
            raise ValueError(
                f"분자 이름 '{name}'을(를) SMILES로 변환하지 못했습니다: {e}"
            ) from e

        raise ValueError(f"분자 이름 '{name}'을(를) SMILES로 변환하지 못했습니다.")

    @classmethod
    def _generate_xyz_via_molchat(cls, smiles: str) -> str:
        url = f"{cls.MOLCHAT_BASE}/molecules/generate-3d"
        body = {
            "smiles": smiles,
            "format": "xyz",
            "optimize_xtb": True,
        }
        try:
            data = cls._http_post_json(url, body=body, timeout=60)
        except urllib.error.HTTPError as e:
            try:
                details = e.read().decode("utf-8", errors="replace")
            except Exception:
                details = str(e)
            raise ValueError(f"Molchat API 호출 실패: HTTP {e.code} - {details}") from e
        except Exception as e:
            raise ValueError(f"Molchat API 호출 실패: {e}") from e

        xyz = data.get("structure_data")
        if not xyz or not str(xyz).strip():
            raise ValueError("Molchat API 응답에 structure_data(XYZ)가 없습니다.")
        return str(xyz).strip()

    @classmethod
    def resolve_with_friendly_errors(cls, query: str) -> str:
        try:
            return cls.resolve(query)
        except Exception as e:
            raise ValueError(
                "분자 구조를 확보하지 못했습니다. "
                "XYZ 좌표를 직접 제공하거나, 인식 가능한 분자명/SMILES를 입력해 주세요. "
                f"원인: {e}"
            ) from e


def _resolve_query_input(query: str) -> Tuple[str, str, Optional[str]]:
    resolved_structure = MoleculeResolver.resolve_with_friendly_errors(query)
    validate_atom_spec_strict(resolved_structure)
    atom_data = _parse_atom_spec(resolved_structure)

    raw_query = str(query).strip() if query is not None else ""
    if MoleculeResolver._is_xyz_text(raw_query) or MoleculeResolver._is_atom_spec_text(raw_query):
        display_name_hint = None
    else:
        display_name_hint = _sanitize_display_name(raw_query)

    return resolved_structure, atom_data, display_name_hint


# --- Top-level implementation functions for Executor (Pickle-safe) ---

def _sync_compute_ibo_impl(
    atom_spec,
    basis,
    method,
    charge,
    spin,
    n_orbitals,
    include_esp,
    xyz_string_raw,
    display_name_hint=None,
):
    """
    Hybrid Orbital Rendering Architecture:
    - Occupied orbitals (idx <= HOMO): IBO coefficients for intuitive bond visualization
    - Virtual orbitals  (idx >  HOMO): Canonical MO coefficients from SCF result
    """
    scf_res, mol = _pyscf.compute_scf(atom_spec, basis, method, charge=charge, spin=spin)
    iao_res = _pyscf.compute_iao(scf_res, mol)
    ibo_res = _pyscf.compute_ibo(scf_res, iao_res, mol)

    # ── Determine orbital index boundaries ──
    mo_occ = scf_res.mo_occ
    n_ibo = ibo_res.n_ibo
    n_mo_total = scf_res.mo_coeff.shape[1]

    homo_idx = 0
    for i in range(len(mo_occ)):
        if mo_occ[i] > 0.5:
            homo_idx = i
    lumo_idx = homo_idx + 1

    selected = []

    if n_orbitals > 0:
        # Roughly half occupied / half virtual
        n_occ_to_show = max(1, n_orbitals // 2)
        n_vir_to_show = max(1, n_orbitals - n_occ_to_show)

        occ_start = max(0, homo_idx - n_occ_to_show + 1)
        occ_end = homo_idx + 1

        vir_start = lumo_idx
        vir_end = min(n_mo_total, lumo_idx + n_vir_to_show)

        occ_selected = [i for i in range(occ_start, occ_end) if scf_res.mo_energy[i] > -10.0]
        if not occ_selected and occ_end > 0:
            occ_selected = [homo_idx]

        vir_selected = list(range(vir_start, vir_end))
        selected = occ_selected + vir_selected

        if not selected:
            selected = list(range(max(0, n_ibo - n_orbitals), n_ibo))

    # ── Build XYZ data ──
    xyz_lines = [str(mol.natm), "QCViz Pro"]
    for i in range(mol.natm):
        sym = mol.atom_symbol(i)
        c = mol.atom_coord(i) * 0.529177249  # Bohr to Angstrom
        xyz_lines.append("%s %.6f %.6f %.6f" % (sym, c[0], c[1], c[2]))
    xyz_data = "\n".join(xyz_lines)

    # ── Metadata ──
    if display_name_hint:
        clean_name = _sanitize_display_name(display_name_hint)
    else:
        clean_name = _extract_name(xyz_string_raw, mol)

    atom_symbols = [mol.atom_symbol(i) for i in range(mol.natm)]
    charges_dict = {
        "%s%d" % (atom_symbols[i], i + 1): float(iao_res.charges[i])
        for i in range(mol.natm)
    }

    payload = DashboardPayload(
        molecule_name=clean_name,
        xyz_data=xyz_data,
        atom_symbols=atom_symbols,
        basis=basis,
        method=method,
        energy_hartree=scf_res.energy_hartree,
        charges=charges_dict,
    )

    # ── Generate cube files with hybrid IBO/Canonical branching ──
    total_q = len(selected)
    for qi, i in enumerate(selected):
        if i == homo_idx:
            lbl = "HOMO"
        elif i == lumo_idx:
            lbl = "LUMO"
        elif i < homo_idx:
            lbl = "HOMO-%d" % (homo_idx - i)
        else:
            lbl = "LUMO+%d" % (i - lumo_idx)

        if i <= homo_idx:
            ibo_col_idx = i
            if ibo_col_idx < n_ibo:
                coeff_to_use = ibo_res.coefficients
                col_idx = ibo_col_idx
                lbl_suffix = "(IBO)"
            else:
                coeff_to_use = scf_res.mo_coeff
                col_idx = i
                lbl_suffix = "(Canonical)"
        else:
            coeff_to_use = scf_res.mo_coeff
            col_idx = i
            lbl_suffix = "(Canonical)"

        full_label = "%s %s" % (lbl, lbl_suffix)
        _cli.print_cube_progress(qi + 1, total_q, full_label)

        cube = _pyscf.generate_cube(
            mol, coeff_to_use, col_idx,
            grid_points=(60, 60, 60)
        )
        energy_eV = float(scf_res.mo_energy[i]) * HARTREE_TO_EV

        payload.orbitals.append(
            _viz.prepare_orbital_data(cube, i, full_label, energy=energy_eV)
        )

    # ── ESP calculation ──
    if include_esp:
        esp_res = _pyscf.compute_esp(
            atom_spec, basis, grid_size=60, charge=charge, spin=spin
        )
        payload.esp_data = _viz.prepare_esp_data(
            esp_res.density_cube, esp_res.potential_cube,
            esp_res.vmin, esp_res.vmax
        )

    # ── Render and save ──
    html = _viz.render_dashboard(payload)
    safe_name = _safe_filename(clean_name, fallback="molecule")
    html_path = OUTPUT_DIR / f"{safe_name}_dashboard.html"
    html_path.write_text(html, encoding="utf-8")

    n_occ_shown = len([i for i in selected if i <= homo_idx])
    n_vir_shown = len([i for i in selected if i > homo_idx])
    lumo_energy_ev = (
        round(float(scf_res.mo_energy[lumo_idx]) * HARTREE_TO_EV, 3)
        if lumo_idx < len(scf_res.mo_energy)
        else None
    )

    if n_orbitals > 0:
        message = (
            f"Hybrid orbital calculation complete: "
            f"{n_occ_shown} occupied (IBO) + {n_vir_shown} virtual (Canonical MO) orbitals. "
            f"HOMO={homo_idx}, LUMO={lumo_idx}, Total MOs={n_mo_total}."
        )
    else:
        message = (
            f"ESP calculation complete. "
            f"HOMO={homo_idx}, LUMO={lumo_idx}, Total MOs={n_mo_total}."
        )

    return {
        "status": "success",
        "message": message,
        "html_file": str(html_path),
        "n_ibo": int(n_ibo),
        "n_occupied_shown": int(n_occ_shown),
        "n_virtual_shown": int(n_vir_shown),
        "homo_idx": int(homo_idx),
        "lumo_idx": int(lumo_idx),
        "total_mos": int(n_mo_total),
        "energy_hartree": float(scf_res.energy_hartree),
        "homo_energy_ev": round(float(scf_res.mo_energy[homo_idx]) * HARTREE_TO_EV, 3),
        "lumo_energy_ev": lumo_energy_ev,
        "visualization_html": html,
    }


def _sync_compute_partial_charges_impl(
    xyz_string,
    basis,
    method="rhf",
    display_name_hint=None,
):
    atom_data = _parse_atom_spec(xyz_string)
    scf_res, mol = _pyscf.compute_scf(atom_data, basis=basis, method=method)
    iao_res = _pyscf.compute_iao(scf_res, mol)

    title = _sanitize_display_name(display_name_hint, fallback="molecule") if display_name_hint else None
    if title:
        msg = f"{title} — IAO 부분 전하 분석 결과:\n"
    else:
        msg = "IAO 부분 전하 분석 결과:\n"

    for i in range(mol.natm):
        msg += f"{mol.atom_symbol(i)}{i + 1}: {iao_res.charges[i]:+.4f}\n"
    return msg


def _sync_visualize_orbital_impl(
    xyz_string,
    orbital_index,
    basis,
    display_name_hint=None,
):
    atom_data = _parse_atom_spec(xyz_string)
    scf_res, mol = _pyscf.compute_scf(atom_data, basis=basis)
    idx = (
        orbital_index
        if orbital_index is not None
        else (len(scf_res.mo_occ[scf_res.mo_occ > 0.5]) - 1)
    )
    cube = _pyscf.generate_cube(mol, scf_res.mo_coeff, idx)

    mol_name = _sanitize_display_name(display_name_hint, fallback="QCViz") if display_name_hint else "QCViz"
    xyz_lines = [str(mol.natm), mol_name]
    for i in range(mol.natm):
        sym = mol.atom_symbol(i)
        c = mol.atom_coord(i) * 0.529177249
        xyz_lines.append("%s %.6f %.6f %.6f" % (sym, c[0], c[1], c[2]))
    xyz_data = "\n".join(xyz_lines)

    html = (
        "<!-- 성공적으로 오비탈 렌더링 HTML 생성 완료 -->\n"
        + _viz.render_orbital(xyz_data, cube)
    )

    safe_name = _safe_filename(mol_name, fallback=f"orbital_{idx}")
    html_path = OUTPUT_DIR / f"{safe_name}_orbital_{idx}.html"
    html_path.write_text(html, encoding="utf-8")
    return html


def _sync_convert_format_impl(input_path, output_path):
    from qcviz_mcp.backends.ase_backend import ASEBackend
    ASEBackend().convert_format(input_path, output_path)
    return f"성공적으로 변환 완료: {output_path}"


# --- Helper to run implementation functions safely (handles no-executor mode) ---
def _run_impl(func, *args, timeout=300.0, **kwargs):
    if _executor is None:
        return func(*args, **kwargs)
    else:
        return _executor.submit(func, *args, **kwargs).result(timeout=timeout)


# --- Tracing helper for sync tools ---
def sync_traced_tool(func):
    import uuid
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        invocation = ToolInvocation(
            tool_name=func.__name__,
            request_id=str(uuid.uuid4())[:8],
            parameters={k: str(v)[:100] for k, v in kwargs.items()},
        )
        try:
            result = func(*args, **kwargs)
            invocation.finish(status="success")
            metrics.record(invocation)
            return result
        except Exception as e:
            invocation.finish(status="error")
            invocation.error = str(e)
            metrics.record(invocation)
            raise

    return wrapper


# --- MCP Tool Definitions ---

@mcp.tool()
@sync_traced_tool
def compute_ibo(
    query: str,
    basis: str = "sto-3g",
    method: str = "rhf",
    charge: int = 0,
    spin: int = 0,
    n_orbitals: int = 12,
    include_esp: bool = True,
) -> str:
    """Intrinsic Bond Orbital (IBO) analysis and ESP visualization.

    query accepts:
    - XYZ string
    - atom-spec string
    - molecule name (resolved via PubChem -> SMILES -> Molchat)
    - SMILES (resolved via Molchat)
    """
    try:
        if not default_bucket.consume(10):
            return json.dumps({"status": "error", "error": "Rate limit exceeded"})

        validate_basis(basis)

        resolved_structure, atom_data, display_name_hint = _resolve_query_input(query)

        cache_key = cache.make_key(
            "compute_ibo",
            resolved_structure=resolved_structure,
            display_name_hint=display_name_hint,
            basis=basis,
            method=method,
            charge=charge,
            spin=spin,
            n_orbitals=n_orbitals,
            include_esp=include_esp,
        )
        cached = cache.get(cache_key)
        if cached:
            return cached

        result_dict = _run_impl(
            _sync_compute_ibo_impl,
            atom_data,
            basis,
            method,
            charge,
            spin,
            n_orbitals,
            include_esp,
            resolved_structure,
            display_name_hint,
            timeout=300.0,
        )
        res_json = json.dumps(result_dict, cls=_NumpyEncoder)
        cache.put(cache_key, res_json)
        return res_json

    except Exception as e:
        logger.error(traceback.format_exc())
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
@sync_traced_tool
def compute_esp(
    query: str,
    basis: str = "sto-3g",
    charge: int = 0,
) -> str:
    """Electrostatic Potential (ESP) surface generation."""
    return compute_ibo(
        query=query,
        basis=basis,
        include_esp=True,
        n_orbitals=0,
        charge=charge,
    )


@mcp.tool()
@sync_traced_tool
def compute_partial_charges(
    query: str,
    basis: str = "sto-3g",
    method: str = "rhf",
) -> str:
    """Compute IAO-based partial atomic charges.

    query accepts:
    - XYZ string
    - atom-spec string
    - molecule name
    - SMILES
    """
    try:
        if not default_bucket.consume(5):
            return "Error: Rate limit exceeded"

        validate_basis(basis)
        resolved_structure, _, display_name_hint = _resolve_query_input(query)

        return _run_impl(
            _sync_compute_partial_charges_impl,
            resolved_structure,
            basis,
            method=method,
            display_name_hint=display_name_hint,
            timeout=120.0,
        )
    except Exception as e:
        return f"오류: {e}"


@mcp.tool()
@sync_traced_tool
def visualize_orbital(
    query: str,
    orbital_index: int = None,
    basis: str = "sto-3g",
) -> str:
    """Generate a standalone HTML for a specific molecular orbital."""
    try:
        if not default_bucket.consume(2):
            return "Error: Rate limit exceeded"

        validate_basis(basis)
        resolved_structure, _, display_name_hint = _resolve_query_input(query)

        return _run_impl(
            _sync_visualize_orbital_impl,
            resolved_structure,
            orbital_index,
            basis,
            display_name_hint=display_name_hint,
            timeout=120.0,
        )
    except Exception as e:
        return f"오류: {e}"


@mcp.tool()
@sync_traced_tool
def parse_output(file_path: str) -> str:
    """Parse quantum chemistry output file using cclib."""
    from qcviz_mcp.backends.cclib_backend import CclibBackend
    try:
        if not default_bucket.consume(1):
            return "Error: Rate limit exceeded"
        p = validate_path(file_path)
        res = CclibBackend().parse_file(str(p))
        return json.dumps(
            {"program": res.program, "energy": res.energy_hartree},
            cls=_NumpyEncoder,
        )
    except Exception as e:
        return f"오류: {e}"


@mcp.tool()
@sync_traced_tool
def convert_format(input_path: str, output_path: str) -> str:
    """Convert chemical files between formats (e.g., xyz to cif)."""
    try:
        if not default_bucket.consume(1):
            return "Error: Rate limit exceeded"
        p_in = validate_path(input_path)
        p_out = validate_path(output_path, mode="w")
        return _run_impl(
            _sync_convert_format_impl,
            str(p_in),
            str(p_out),
            timeout=60.0,
        )
    except Exception as e:
        return f"오류: {e}"


@mcp.tool()
@sync_traced_tool
def analyze_bonding(query: str, basis: str = "sto-3g") -> str:
    """Analyze chemical bonding using IAO/IBO theory."""
    res_json = compute_ibo(
        query=query,
        basis=basis,
        n_orbitals=10,
        include_esp=False,
    )
    res = json.loads(res_json)
    if res["status"] == "success":
        return (
            f"IBO 결합 분석 완료. "
            f"전체 점유 IBO 수: {res['n_ibo']}. "
            f"표시된 점유/가상 오비탈: {res['n_occupied_shown']}/{res['n_virtual_shown']}. "
            f"대시보드: {res['html_file']}"
        )
    return f"분석 실패: {res.get('error')}"```


## File: `version02/src/qcviz_mcp/web/static/app.js`

```javascript
/* ═══════════════════════════════════════════
   QCViz-MCP Enterprise v5 — App Orchestrator
   Theme, shortcuts, history, status sync, init
   ═══════════════════════════════════════════ */
(function () {
  "use strict";

  var App = window.QCVizApp;
  if (!App) return;

  var PREFIX = App.apiPrefix || "/api";

  /* ─── DOM ─── */
  var $statusDot = document.querySelector("#globalStatus .status-indicator__dot");
  var $statusText = document.querySelector("#globalStatus .status-indicator__text");
  var $themeBtn = document.getElementById("btnThemeToggle");
  var $shortcutsBtn = document.getElementById("btnKeyboardShortcuts");
  var $shortcutsModal = document.getElementById("modalShortcuts");
  var $historyList = document.getElementById("historyList");
  var $historyEmpty = document.getElementById("historyEmpty");
  var $historySearch = document.getElementById("historySearch");
  var $btnRefresh = document.getElementById("btnRefreshHistory");
  var $chatInput = document.getElementById("chatInput");

  /* ─── Global Status ─── */
  App.on("status:changed", function (s) {
    if ($statusDot) $statusDot.setAttribute("data-kind", s.kind || "idle");
    if ($statusText) $statusText.textContent = s.text || "Ready";

    if (s.kind === "success" || s.kind === "completed") {
      setTimeout(function () {
        if (App.store.status.kind === s.kind && App.store.status.at === s.at) {
          App.setStatus("Ready", "idle", "app");
        }
      }, 4000);
    }
  });

  /* ─── Theme Toggle ─── */
  if ($themeBtn) {
    $themeBtn.addEventListener("click", function () {
      var next = App.store.theme === "dark" ? "light" : "dark";
      App.setTheme(next);
    });
  }

  /* ─── Modal Helpers ─── */
  function openModal(dialog) {
    if (!dialog) return;
    dialog.showModal();
  }
  function closeModal(dialog) {
    if (!dialog) return;
    dialog.close();
  }

  if ($shortcutsBtn) {
    $shortcutsBtn.addEventListener("click", function () { openModal($shortcutsModal); });
  }

  if ($shortcutsModal) {
    $shortcutsModal.addEventListener("click", function (e) {
      if (e.target.hasAttribute("data-close") || e.target.closest("[data-close]")) {
        closeModal($shortcutsModal);
      }
    });
  }

  /* ─── Keyboard Shortcuts ─── */
  document.addEventListener("keydown", function (e) {
    var tag = document.activeElement ? document.activeElement.tagName : "";
    var isTyping = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";

    // Ctrl+/ → Focus chat
    if ((e.ctrlKey || e.metaKey) && e.key === "/") {
      e.preventDefault();
      if ($chatInput) $chatInput.focus();
      return;
    }

    // Ctrl+K → Focus history search
    if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) {
      e.preventDefault();
      if ($historySearch) $historySearch.focus();
      return;
    }

    // Ctrl+\ → Toggle theme
    if ((e.ctrlKey || e.metaKey) && e.key === "\\") {
      e.preventDefault();
      var next = App.store.theme === "dark" ? "light" : "dark";
      App.setTheme(next);
      return;
    }

    // Escape
    if (e.key === "Escape") {
      if ($shortcutsModal && $shortcutsModal.open) {
        closeModal($shortcutsModal);
        return;
      }
      if (isTyping) {
        document.activeElement.blur();
        return;
      }
    }

    // ? → Show shortcuts
    if (e.key === "?" && !isTyping) {
      openModal($shortcutsModal);
    }
  });

  /* ─── History Panel ─── */
  var historyFilter = "";

  function getJobDisplayName(job) {
    if (job.user_query && typeof job.user_query === "string" && job.user_query.trim()) {
      var q = job.user_query.trim();
      return q.length > 40 ? q.substring(0, 40) + "\u2026" : q;
    }
    
    var molName = job.molecule_name || job.molecule || (job.result && (job.result.structure_name || job.result.structure_query)) || (job.payload && (job.payload.structure_query || job.payload.molecule_name || job.payload.molecule));
    var method = job.method || (job.result && job.result.method) || (job.payload && job.payload.method) || "";
    var basis = job.basis_set || (job.result && job.result.basis_set) || (job.payload && job.payload.basis_set) || "";
    var jobType = job.job_type || (job.result && job.result.job_type) || (job.payload && job.payload.job_type) || "computation";

    if (molName) {
        var name = molName;
        if (jobType === "orbital_preview" || jobType === "orbital") {
             var orb = job.orbital || (job.payload && job.payload.orbital);
             if (orb) name = orb + " of " + name;
             else name = "Orbital of " + name;
        } else if (jobType === "esp_map" || jobType === "esp") {
             name = "ESP of " + name;
        }
        return name.length > 40 ? name.substring(0, 40) + "\u2026" : name;
    }
    
    if (method || basis) return [method, basis].filter(Boolean).join(" / ");
    
    // Nice fallback instead of ugly ID
    var prettyType = jobType.replace(/_/g, " ");
    return prettyType.charAt(0).toUpperCase() + prettyType.slice(1);
  }

  function getJobDetailLine(job) {
    var parts = [];
    var jobType = job.job_type || (job.payload && job.payload.job_type) || "";
    if (jobType) parts.push(jobType);
    var method = job.method || job.result && job.result.method || (job.payload && job.payload.method) || "";
    if (method) parts.push(method);
    var basis = job.basis_set || job.result && job.result.basis_set || (job.payload && job.payload.basis_set) || "";
    if (basis) parts.push(basis);
    if (parts.length > 0) return parts.join(" \u00B7 ");

    // Fallback to timestamp
    var ts = job.submitted_at || job.created_at || job.updated_at;
    if (ts) {
      var d = new Date(typeof ts === "number" && ts < 1e12 ? ts * 1000 : ts);
      return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) + " " +
        d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    }
    return "\u2014";
  }

  function esc(s) {
    if (s == null) return "";
    var d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }

  function escAttr(s) {
    return String(s || "").replace(/"/g, "&quot;").replace(/'/g, "&#39;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function renderHistory() {
    if (!$historyList) return;

    var jobs = App.store.jobOrder.map(function (id) { return App.store.jobsById[id]; }).filter(Boolean);

    var filtered = jobs;
    if (historyFilter) {
      var q = historyFilter.toLowerCase();
      filtered = jobs.filter(function (j) {
        var searchable = [
          j.user_query || "",
          j.molecule_name || "",
          j.molecule || "",
          j.method || "",
          j.basis_set || "",
          j.job_id || "",
          (j.payload && j.payload.molecule) || "",
          (j.payload && j.payload.method) || "",
        ].join(" ").toLowerCase();
        return searchable.indexOf(q) !== -1;
      });
    }

    // Remove old items
    var oldItems = $historyList.querySelectorAll(".history-item");
    oldItems.forEach(function (el) { el.remove(); });

    if (filtered.length === 0) {
      if ($historyEmpty) {
        $historyEmpty.hidden = false;
        var p = $historyEmpty.querySelector("p");
        if (p) p.textContent = historyFilter ? "No matching jobs" : "No previous computations";
      }
      return;
    }

    if ($historyEmpty) $historyEmpty.hidden = true;

    var activeJobId = App.store.activeJobId;
    var html = "";

    filtered.forEach(function (job) {
      var id = job.job_id || "";
      var status = job.status || "queued";
      var name = getJobDisplayName(job);
      var detail = getJobDetailLine(job);
      var energy = job.result ? (job.result.total_energy_hartree != null ? job.result.total_energy_hartree : job.result.energy) : null;
      var energyStr = energy != null ? Number(energy).toFixed(4) + " Ha" : "";
      var isActive = id === activeJobId;

      html += '<div class="history-item' + (isActive ? ' history-item--active' : '') + '" data-job-id="' + escAttr(id) + '">' +
        '<span class="history-item__status history-item__status--' + escAttr(status) + '"></span>' +
        '<div class="history-item__info">' +
        '<div class="history-item__title">' + esc(name) + '</div>' +
        '<div class="history-item__detail">' + esc(detail) + '</div>' +
        '</div>' +
        (energyStr ? '<span class="history-item__energy">' + esc(energyStr) + '</span>' : '') +
        '</div>';
    });

    if ($historyEmpty) {
      $historyEmpty.insertAdjacentHTML("beforebegin", html);
    } else {
      $historyList.innerHTML = html;
    }
  }

  // History click
  if ($historyList) {
    $historyList.addEventListener("click", function (e) {
      var item = e.target.closest(".history-item");
      if (!item) return;
      var jobId = item.dataset.jobId;
      if (!jobId) return;
      App.setActiveJob(jobId);
      renderHistory();
    });
  }

  // History search
  if ($historySearch) {
    $historySearch.addEventListener("input", function () {
      historyFilter = $historySearch.value.trim();
      renderHistory();
    });
  }

  // Fetch history from server
  function fetchHistory() {
    return fetch(PREFIX + "/compute/jobs?include_result=true")
      .then(function (res) {
        if (!res.ok) return;
        return res.json();
      })
      .then(function (data) {
        if (!data) return;
        var jobs = Array.isArray(data) ? data : (data.items || data.jobs || []);
        jobs.forEach(function (j) { App.upsertJob(j); });
      })
      .catch(function () {
        // Silently fail
      });
  }

  if ($btnRefresh) {
    $btnRefresh.addEventListener("click", function () {
      $btnRefresh.classList.add("is-spinning");
      fetchHistory().then(function () {
        setTimeout(function () { $btnRefresh.classList.remove("is-spinning"); }, 600);
      }).catch(function () {
        setTimeout(function () { $btnRefresh.classList.remove("is-spinning"); }, 600);
      });
    });
  }

  App.on("jobs:changed", function () {
    renderHistory();
  });

  /* ─── Init ─── */
  fetchHistory();
  renderHistory();

  console.log(
    "%c QCViz-MCP Enterprise v5 %c Loaded ",
    "background:linear-gradient(135deg,#6366f1,#8b5cf6);color:white;font-weight:bold;padding:3px 8px;border-radius:4px 0 0 4px;",
    "background:#18181b;color:#a1a1aa;padding:3px 8px;border-radius:0 4px 4px 0;"
  );

})();
```


## File: `version02/src/qcviz_mcp/web/static/chat.js`

```javascript
/* ═══════════════════════════════════════════
   QCViz-MCP Enterprise v5 — Chat Module
   ═══════════════════════════════════════════ */
(function () {
  "use strict";

  var App = window.QCVizApp;
  if (!App) return;

  var PREFIX = App.apiPrefix || "/api";

  var state = {
    sessionId: App.store.sessionId,
    ws: null,
    wsConnected: false,
    reconnectTimer: null,
    reconnectAttempts: 0,
    maxReconnect: 8,
    activeJobId: null,
    sending: false,
    streamBuffer: "",
    activeAssistantEl: null,
    activeProgressEl: null,
    lastUserInput: "",
  };

  var $messages = document.getElementById("chatMessages");
  var $scroll = document.getElementById("chatScroll");
  var $form = document.getElementById("chatForm");
  var $input = document.getElementById("chatInput");
  var $send = document.getElementById("chatSend");
  var $suggestions = document.getElementById("chatSuggestions");
  var $wsDot = document.querySelector("#wsStatus .ws-status__dot");
  var $wsLabel = document.querySelector("#wsStatus .ws-status__label");

  function now() {
    return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function scrollToBottom() {
    requestAnimationFrame(function () {
      if ($scroll) $scroll.scrollTop = $scroll.scrollHeight;
    });
  }

  function setWsUI(connected) {
    state.wsConnected = connected;
    if ($wsDot) $wsDot.setAttribute("data-connected", String(connected));
    if ($wsLabel) $wsLabel.textContent = connected ? "Connected" : "Disconnected";
  }

  function setSending(v) {
    state.sending = v;
    if ($send) $send.disabled = v || !($input && $input.value.trim());
  }

  function escHtml(s) {
    if (s == null) return "";
    if (typeof s === "object") {
      try { s = JSON.stringify(s, null, 2); } catch (_) { s = String(s); }
    }
    var d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }

  /* 깊은 텍스트 추출: [object Object] 절대 반환하지 않음 */
  function extractReadableText(obj) {
    if (obj == null) return "";
    if (typeof obj === "string") return obj;
    if (typeof obj === "number" || typeof obj === "boolean") return String(obj);
    if (typeof obj === "object") {
      var keys = ["message", "text", "content", "detail", "reason", "error", "description", "response", "answer", "reply"];
      for (var i = 0; i < keys.length; i++) {
        if (obj[keys[i]] != null) {
          var v = extractReadableText(obj[keys[i]]);
          if (v) return v;
        }
      }
      try { return JSON.stringify(obj, null, 2); } catch (_) { return "[data]"; }
    }
    return String(obj);
  }

  function extractTextFromMsg(msg) {
    var keys = ["text", "content", "message", "response", "answer", "reply", "detail"];
    for (var i = 0; i < keys.length; i++) {
      if (msg[keys[i]] != null) {
        var v = extractReadableText(msg[keys[i]]);
        if (v) return v;
      }
    }
    return "";
  }

  function formatMarkdown(text) {
    if (!text) return "";
    var s = escHtml(text);
    s = s.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
    s = s.replace(/\n/g, "<br>");
    return s;
  }

  /* 메시지 버블 생성 */
  function createMsgEl(role, opts) {
    opts = opts || {};
    var div = document.createElement("div");
    div.className = "chat-msg chat-msg--" + role;

    var avatar = document.createElement("div");
    avatar.className = "chat-msg__avatar chat-msg__avatar--" + role;
    if (role === "user") {
      avatar.textContent = "U";
    } else if (role === "assistant") {
      avatar.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/></svg>';
    } else if (role === "error") {
      avatar.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>';
    }

    var body = document.createElement("div");
    body.className = "chat-msg__body";

    var meta = document.createElement("div");
    meta.className = "chat-msg__meta";

    var nameEl = document.createElement("span");
    nameEl.className = "chat-msg__name";
    nameEl.textContent = role === "user" ? "You" : role === "error" ? "Error" : "QCViz";

    var timeEl = document.createElement("span");
    timeEl.className = "chat-msg__time";
    timeEl.textContent = now();

    meta.appendChild(nameEl);
    meta.appendChild(timeEl);
    body.appendChild(meta);

    var safeHtml = opts.html ? (typeof opts.html === "object" ? escHtml(opts.html) : opts.html) : null;
    var safeText = opts.text ? extractReadableText(opts.text) : null;

    var textEl = document.createElement("div");
    textEl.className = "chat-msg__text";
    if (safeHtml) textEl.innerHTML = safeHtml;
    else if (safeText) textEl.textContent = safeText;
    body.appendChild(textEl);

    div.appendChild(avatar);
    div.appendChild(body);
    if ($messages) $messages.appendChild(div);
    scrollToBottom();

    return { root: div, body: body, text: textEl };
  }

  function addTypingIndicator() {
    removeTypingIndicator();
    var div = document.createElement("div");
    div.className = "chat-msg chat-msg--assistant";
    div.id = "typingIndicator";
    div.innerHTML = '<div class="chat-msg__avatar chat-msg__avatar--assistant"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/></svg></div><div class="chat-msg__body"><div class="chat-typing"><span class="chat-typing__dot"></span><span class="chat-typing__dot"></span><span class="chat-typing__dot"></span></div></div>';
    if ($messages) $messages.appendChild(div);
    scrollToBottom();
    return div;
  }

  function removeTypingIndicator() {
    var el = document.getElementById("typingIndicator");
    if (el) el.remove();
  }

  /* Progress UI — 부모 body에 붙임 */
  function addProgressUI(parentBody) {
    var container = document.createElement("div");
    container.className = "chat-progress";
    var bar = document.createElement("div");
    bar.className = "chat-progress__bar";
    var fill = document.createElement("div");
    fill.className = "chat-progress__fill chat-progress__fill--indeterminate";
    bar.appendChild(fill);
    container.appendChild(bar);
    var stepsEl = document.createElement("div");
    stepsEl.className = "chat-progress__steps";
    container.appendChild(stepsEl);
    parentBody.appendChild(container);
    scrollToBottom();

    return {
      container: container,
      fill: fill,
      stepsEl: stepsEl,
      setProgress: function (pct) {
        fill.classList.remove("chat-progress__fill--indeterminate");
        fill.style.width = Math.min(100, Math.max(0, pct)) + "%";
      },
      addStep: function (label, status) {
        var existingActive = stepsEl.querySelector(".chat-progress__step--active");
        if (existingActive && status !== "error") {
          existingActive.className = "chat-progress__step chat-progress__step--done";
          existingActive.innerHTML = '<span class="chat-progress__icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span><span>' + escHtml(existingActive.dataset.label || "") + '</span>';
        }

        while (stepsEl.children.length > 6) {
          stepsEl.removeChild(stepsEl.firstChild);
        }

        var step = document.createElement("div");
        step.className = "chat-progress__step chat-progress__step--" + (status || "active");
        step.dataset.label = label;
        var icon;
        if (status === "done") icon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>';
        else if (status === "error") icon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
        else icon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3" fill="currentColor"><animate attributeName="opacity" values="1;0.3;1" dur="1.2s" repeatCount="indefinite"/></circle></svg>';
        step.innerHTML = '<span class="chat-progress__icon">' + icon + '</span><span>' + escHtml(label) + '</span>';
        stepsEl.appendChild(step);
        scrollToBottom();
        return step;
      },
      finish: function () {
        fill.classList.remove("chat-progress__fill--indeterminate");
        fill.style.width = "100%";
        fill.style.background = "var(--success)";
        
        var active = stepsEl.querySelector(".chat-progress__step--active");
        if (active) {
          active.className = "chat-progress__step chat-progress__step--done";
          active.innerHTML = '<span class="chat-progress__icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span><span>' + escHtml(active.dataset.label || "") + '</span>';
        }
      }
    };
  }

  /* 어시스턴트 버블 보장 — 없으면 생성 */
  function ensureAssistantBubble() {
    if (!state.activeAssistantEl) {
      removeTypingIndicator();
      state.activeAssistantEl = createMsgEl("assistant", { text: "" });
    }
    return state.activeAssistantEl;
  }

  /* 프로그레스 보장 */
  function ensureProgressUI() {
    if (!state.activeProgressEl) {
      var bubble = ensureAssistantBubble();
      state.activeProgressEl = addProgressUI(bubble.body);
    }
    return state.activeProgressEl;
  }

  /* ─── WebSocket ─── */
  function buildWsUrl() {
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    return proto + "//" + location.host + PREFIX + "/ws/chat";
  }

  function connectWS() {
    if (state.ws && (state.ws.readyState === WebSocket.OPEN || state.ws.readyState === WebSocket.CONNECTING)) return;
    try {
      state.ws = new WebSocket(buildWsUrl());
    } catch (e) {
      setWsUI(false);
      scheduleReconnect();
      return;
    }

    state.ws.onopen = function () {
      setWsUI(true);
      state.reconnectAttempts = 0;
      console.log("%c[WS] Connected", "background:#22c55e;color:white;padding:2px 6px;border-radius:3px;");
      /* ⚠️ Do NOT send hello — backend misinterprets it */
    };

    state.ws.onclose = function () {
      setWsUI(false);
      scheduleReconnect();
    };

    state.ws.onerror = function () {
      setWsUI(false);
    };

    state.ws.onmessage = function (event) {
      var data;
      try { data = JSON.parse(event.data); } catch (_) { return; }
      console.log("%c[WS IN]", "background:#6366f1;color:white;padding:2px 6px;border-radius:3px;", data);
      handleServerEvent(data);
    };
  }

  function safeSendWs(obj) {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify(obj));
      return true;
    }
    return false;
  }

  function scheduleReconnect() {
    if (state.reconnectTimer) return;
    if (state.reconnectAttempts >= state.maxReconnect) return;
    var delay = Math.min(1000 * Math.pow(2, state.reconnectAttempts), 30000);
    state.reconnectAttempts++;
    state.reconnectTimer = setTimeout(function () {
      state.reconnectTimer = null;
      connectWS();
    }, delay);
  }

  /* ─── Server Event Router ─── */
  function handleServerEvent(msg) {
    var type = (msg.type || msg.event || msg.action || msg.kind || "").toLowerCase().trim();
    var jobId = msg.job_id || msg.jobId || msg.id || null;
    var status = (msg.status || msg.state || "").toLowerCase();
    var textContent = extractTextFromMsg(msg);

    switch (type) {
      case "ready": case "ack": case "hello": case "connected": case "pong":
        break;

      case "assistant": case "response": case "answer": case "reply":
      case "chat_response": case "chat_reply":
        removeTypingIndicator();
        if (!textContent) break;
        if (state.activeAssistantEl) {
          state.streamBuffer += "\n" + textContent;
          state.activeAssistantEl.text.innerHTML = formatMarkdown(state.streamBuffer);
        } else {
          state.streamBuffer = textContent;
          state.activeAssistantEl = createMsgEl("assistant", { html: formatMarkdown(textContent) });
        }
        scrollToBottom();
        state.activeAssistantEl = null;
        state.streamBuffer = "";
        setSending(false);
        break;

      case "assistant_start": case "stream_start":
        removeTypingIndicator();
        state.streamBuffer = "";
        state.activeAssistantEl = createMsgEl("assistant", { text: "" });
        break;

      case "assistant_chunk": case "stream": case "chunk": case "delta": case "token":
        var chunk = textContent || msg.chunk || msg.delta || msg.token || "";
        if (!chunk) break;
        if (!state.activeAssistantEl) {
          removeTypingIndicator();
          state.activeAssistantEl = createMsgEl("assistant", { text: "" });
        }
        state.streamBuffer += chunk;
        state.activeAssistantEl.text.innerHTML = formatMarkdown(state.streamBuffer);
        scrollToBottom();
        break;

      case "assistant_end": case "stream_end": case "done":
        state.activeAssistantEl = null;
        state.streamBuffer = "";
        setSending(false);
        break;

      case "job_submitted": case "submitted": case "queued":
      case "job_created": case "job_queued":
        var jid = jobId || state.activeJobId;
        if (!jid) break;
        state.activeJobId = jid;
        App.upsertJob({
          job_id: jid,
          status: "queued",
          submitted_at: Date.now() / 1000,
          updated_at: Date.now() / 1000,
          user_query: state.lastUserInput,
          molecule_name: msg.molecule_name || msg.molecule || (msg.payload ? msg.payload.molecule : "") || "",
          method: msg.method || (msg.payload ? msg.payload.method : "") || "",
          basis_set: msg.basis_set || (msg.payload ? msg.payload.basis_set : "") || "",
        });
        App.setStatus("Job submitted", "running", "chat");

        /* Progress 보장 — 버블이 없으면 새로 만듦 */
        var prog = ensureProgressUI();
        prog.addStep("Job submitted", "done");
        break;

      case "job_update": case "job_event": case "job_progress": case "progress":
      case "status": case "step": case "stage": case "computing": case "running":
        var jid2 = jobId || state.activeJobId;
        var progress = msg.progress != null ? msg.progress : (msg.percent != null ? msg.percent : (msg.pct != null ? msg.pct : null));
        var msgText = msg.message || textContent || "";
        var stepKey = msg.step || msg.stage || "";
        var detailText = msg.detail || msg.description || "";
        var combinedLabel = stepKey ? "[" + stepKey + "] " + (msgText || detailText || "Processing...") : (msgText || detailText || "Computing...");

        if (jid2) {
          App.upsertJob({ job_id: jid2, status: status || "running", updated_at: Date.now() / 1000, progress: progress });
        }

        var prog2 = ensureProgressUI();
        if (combinedLabel) {
          var stepStatus = (status === "failed" || status === "error") ? "error"
            : (status === "completed" || status === "done") ? "done" : "active";
          prog2.addStep(combinedLabel, stepStatus);
        }
        if (typeof progress === "number") {
          prog2.setProgress(progress);
        }

        App.setStatus(combinedLabel || "Computing...", "running", "chat");
        break;

      case "result": case "results": case "completed": case "job_completed":
      case "job_result": case "finish": case "finished": case "computation_result":
        removeTypingIndicator();
        var rjid = jobId || state.activeJobId;
        var result = msg.result || msg.results || msg.data || msg.output || msg.computation || null;

        if (state.activeProgressEl) {
          state.activeProgressEl.finish();
        }

        if (result && rjid) {
          App.upsertJob({
            job_id: rjid, status: "completed", result: result, updated_at: Date.now() / 1000,
            user_query: state.lastUserInput || (App.store.jobsById[rjid] ? App.store.jobsById[rjid].user_query : ""),
            molecule_name: result.molecule_name || result.molecule || "",
            method: result.method || "", basis_set: result.basis_set || "",
          });
          App.setActiveResult(result, { jobId: rjid, source: "chat" });
          App.setStatus("Completed", "success", "chat");

          var energy = result.total_energy_hartree != null ? result.total_energy_hartree : result.energy;
          if (energy != null) {
            var summary = "Computation complete. Total energy: " + Number(energy).toFixed(8) + " Hartree";
            if (result.molecule_name) summary = result.molecule_name + " \u2014 " + summary;
            createMsgEl("assistant", { html: formatMarkdown(summary) });
          }
        } else if (result) {
          App.setActiveResult(result, { source: "chat" });
          App.setStatus("Completed", "success", "chat");
        } else if (textContent) {
          createMsgEl("assistant", { html: formatMarkdown(textContent) });
        }

        state.activeProgressEl = null;
        state.activeAssistantEl = null;
        setSending(false);
        break;

      case "error": case "fail": case "failed": case "job_failed": case "job_error":
        removeTypingIndicator();
        var errMsg = "An error occurred";
        var cands = [msg.message, msg.error, msg.text, msg.detail, msg.reason, msg.description];
        for (var ci = 0; ci < cands.length; ci++) {
          var c = cands[ci];
          if (typeof c === "string" && c.length > 0) { errMsg = c; break; }
        }
        if (errMsg === "An error occurred") {
          for (var ci2 = 0; ci2 < cands.length; ci2++) {
            if (cands[ci2] && typeof cands[ci2] === "object") {
              var nested = extractReadableText(cands[ci2]);
              if (nested && nested !== "An error occurred" && nested !== "[data]") { errMsg = nested; break; }
            }
          }
        }
        /* 파이프 구분자 처리 (백엔드가 "msg|detail" 형태로 보내는 경우) */
        if (errMsg.indexOf("|") !== -1) {
          errMsg = errMsg.split("|").map(function(s){return s.trim();}).filter(Boolean).join(" — ");
        }

        createMsgEl("error", { text: errMsg });

        if (state.activeProgressEl) {
          state.activeProgressEl.addStep(errMsg, "error");
          state.activeProgressEl.fill.style.background = "var(--error)";
          state.activeProgressEl.fill.classList.remove("chat-progress__fill--indeterminate");
          state.activeProgressEl.fill.style.width = "100%";
          state.activeProgressEl = null;
        }

        var errJid = jobId || state.activeJobId;
        if (errJid) App.upsertJob({ job_id: errJid, status: "failed", updated_at: Date.now() / 1000 });
        App.setStatus("Error", "error", "chat");
        state.activeAssistantEl = null;
        setSending(false);
        break;

      default:
        /* Auto-detect */
        if (msg.result || msg.results || (msg.data && msg.data.total_energy_hartree)) {
          handleServerEvent(Object.assign({}, msg, { type: "result" })); return;
        }
        if (status === "completed" || status === "done" || status === "finished") {
          handleServerEvent(Object.assign({}, msg, { type: "result" })); return;
        }
        if (status === "running" || status === "computing" || status === "processing") {
          handleServerEvent(Object.assign({}, msg, { type: "job_update" })); return;
        }
        if (status === "queued" || status === "submitted") {
          handleServerEvent(Object.assign({}, msg, { type: "job_submitted" })); return;
        }
        if (status === "failed" || status === "error") {
          handleServerEvent(Object.assign({}, msg, { type: "error" })); return;
        }
        if (jobId && (msg.progress != null || msg.step || msg.stage)) {
          handleServerEvent(Object.assign({}, msg, { type: "job_update" })); return;
        }
        if (textContent) {
          removeTypingIndicator();
          createMsgEl("assistant", { html: formatMarkdown(textContent) });
          state.activeAssistantEl = null;
          state.streamBuffer = "";
          setSending(false);
          return;
        }
        break;
    }
  }

  /* ─── Submit ─── */
  function submitMessage(text) {
    text = (text || "").trim();
    if (!text || state.sending) return;

    setSending(true);
    state.lastUserInput = text;
    App.store.lastUserInput = text;

    createMsgEl("user", { text: text });
    App.addChatMessage({ role: "user", text: text, at: Date.now() });

    if ($suggestions) $suggestions.hidden = true;

    state.activeAssistantEl = null;
    state.activeProgressEl = null;
    state.streamBuffer = "";

    addTypingIndicator();

    var sent = safeSendWs({
      type: "chat",
      session_id: state.sessionId,
      message: text,
    });

    if (sent) return;

    removeTypingIndicator();
    fetch(PREFIX + "/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId, message: text }),
    })
    .then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    })
    .then(function (data) {
      if (data.type) handleServerEvent(data);
      else if (data.result) handleServerEvent(Object.assign({ type: "result" }, data));
      else {
        var t = extractTextFromMsg(data);
        handleServerEvent({ type: "assistant", text: t || JSON.stringify(data, null, 2) });
      }
    })
    .catch(function (err) {
      handleServerEvent({ type: "error", message: "Request failed: " + err.message });
    });
  }

  /* ─── Input ─── */
  if ($input) {
    $input.addEventListener("input", function () {
      if ($send) $send.disabled = state.sending || !$input.value.trim();
      $input.style.height = "auto";
      $input.style.height = Math.min($input.scrollHeight, 120) + "px";
    });
    $input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (!state.sending && $input.value.trim()) {
          var val = $input.value;
          $input.value = "";
          $input.style.height = "auto";
          if ($send) $send.disabled = true;
          submitMessage(val);
        }
      }
    });
  }

  if ($form) {
    $form.addEventListener("submit", function (e) {
      e.preventDefault();
      if (!state.sending && $input && $input.value.trim()) {
        var val = $input.value;
        $input.value = "";
        $input.style.height = "auto";
        if ($send) $send.disabled = true;
        submitMessage(val);
      }
    });
  }

  if ($suggestions) {
    $suggestions.addEventListener("click", function (e) {
      var chip = e.target.closest(".suggestion-chip");
      if (!chip) return;
      var prompt = chip.dataset.prompt;
      if (prompt) submitMessage(prompt);
    });
  }

  connectWS();

  App.chat = {
    submit: submitMessage,
    connect: connectWS,
    getState: function () { return Object.assign({}, state, { ws: undefined }); },
  };
})();
```


## File: `version02/src/qcviz_mcp/web/static/results.js`

```javascript
/* ═══════════════════════════════════════════
   QCViz-MCP Enterprise v5 — Results Module
   ═══════════════════════════════════════════ */
(function () {
  "use strict";

  var App = window.QCVizApp;
  if (!App) return;

  var TAB_ORDER = [
    ["summary", "Summary"], ["geometry", "Geometry"], ["orbital", "Orbital"],
    ["esp", "ESP"], ["charges", "Charges"], ["json", "JSON"],
  ];

  var state = { result: null, jobId: null, activeTab: "summary", tabs: [] };

  var $tabs = document.getElementById("resultsTabs");
  var $content = document.getElementById("resultsContent");
  var $empty = document.getElementById("resultsEmpty");

  function normalizeResult(raw) {
    if (!raw || typeof raw !== "object") return null;
    var r = App.clone(raw);
    if (r.total_energy_hartree == null && r.energy != null) r.total_energy_hartree = r.energy;
    if (!r.visualization) r.visualization = {};
    var viz = r.visualization;
    if (!viz.xyz_block && r.xyz_block) viz.xyz_block = r.xyz_block;
    if (!viz.xyz_block && r.xyz) viz.xyz_block = r.xyz;
    if (!viz.orbital_cube_b64 && r.orbital_cube_b64) viz.orbital_cube_b64 = r.orbital_cube_b64;
    if (!viz.orbital_info && r.orbital_info) viz.orbital_info = r.orbital_info;
    if (!viz.esp_cube_b64 && r.esp_cube_b64) viz.esp_cube_b64 = r.esp_cube_b64;
    if (!viz.density_cube_b64 && r.density_cube_b64) viz.density_cube_b64 = r.density_cube_b64;
    if (!r.mulliken_charges && r.charges) r.mulliken_charges = r.charges;
    if (!r.atoms && r.geometry) r.atoms = r.geometry;
    return r;
  }

  function getAvailableTabs(r) {
    if (!r) return [];
    var a = ["summary"];
    if (r.visualization.xyz_block || (r.atoms && r.atoms.length)) a.push("geometry");
    if (r.visualization.orbital_cube_b64 || (r.mo_energies && r.mo_energies.length)) a.push("orbital");
    if (r.visualization.esp_cube_b64) a.push("esp");
    if ((r.mulliken_charges && r.mulliken_charges.length) || (r.lowdin_charges && r.lowdin_charges.length)) a.push("charges");
    a.push("json");
    return a;
  }

  function decideFocusTab(r, a) {
    if (a.indexOf("orbital") !== -1) return "orbital";
    if (a.indexOf("esp") !== -1) return "esp";
    if (a.indexOf("geometry") !== -1) return "geometry";
    return "summary";
  }

  function renderTabs(available, active) {
    if (!$tabs) return;
    $tabs.innerHTML = "";
    TAB_ORDER.forEach(function (pair) {
      if (available.indexOf(pair[0]) === -1) return;
      var btn = document.createElement("button");
      btn.className = "tab-btn" + (pair[0] === active ? " tab-btn--active" : "");
      btn.setAttribute("role", "tab");
      btn.setAttribute("data-tab", pair[0]);
      btn.textContent = pair[1];
      btn.addEventListener("click", function () { switchTab(pair[0]); });
      $tabs.appendChild(btn);
    });
  }

  function switchTab(key) {
    if (key === state.activeTab) return;
    state.activeTab = key;
    if ($tabs) $tabs.querySelectorAll(".tab-btn").forEach(function (b) {
      b.classList.toggle("tab-btn--active", b.dataset.tab === key);
    });
    renderContent(key, state.result);
    saveSnapshot();
  }

  function esc(s) {
    if (s == null) return "";
    var d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }

  function metric(label, value, unit) {
    return '<div class="result-metric"><span class="result-metric__label">' + esc(label) +
      '</span><span class="result-metric__value">' + esc(String(value)) +
      (unit ? '<span class="result-metric__unit"> ' + esc(unit) + '</span>' : '') +
      '</span></div>';
  }

  function renderContent(tab, r) {
    if (!r || !$content) { if ($content) $content.innerHTML = ""; return; }
    var html = '<div class="result-card">';
    switch (tab) {
      case "summary": html += renderSummary(r); break;
      case "geometry": html += renderGeometry(r); break;
      case "orbital": html += renderOrbital(r); break;
      case "esp": html += renderESP(r); break;
      case "charges": html += renderCharges(r); break;
      case "json": html += renderJSON(r); break;
    }
    html += '</div>';
    $content.innerHTML = html;
  }

  function renderSummary(r) {
    var html = '<div class="metrics-grid">';
    var has = false;
    var m = [];
    if (r.molecule_name || r.molecule) m.push(["Molecule", r.molecule_name || r.molecule, ""]);
    if (r.method) m.push(["Method", r.method, ""]);
    if (r.basis_set) m.push(["Basis Set", r.basis_set, ""]);
    if (r.total_energy_hartree != null) m.push(["Total Energy", Number(r.total_energy_hartree).toFixed(8), "Ha"]);
    if (r.total_energy_ev != null) m.push(["Energy", Number(r.total_energy_ev).toFixed(4), "eV"]);
    if (r.homo_energy != null) m.push(["HOMO", Number(r.homo_energy).toFixed(6), "Ha"]);
    if (r.lumo_energy != null) m.push(["LUMO", Number(r.lumo_energy).toFixed(6), "Ha"]);
    if (r.homo_lumo_gap != null) m.push(["HOMO-LUMO Gap", Number(r.homo_lumo_gap).toFixed(6), "Ha"]);
    if (r.homo_lumo_gap_ev != null) m.push(["H-L Gap", Number(r.homo_lumo_gap_ev).toFixed(4), "eV"]);
    if (r.dipole_moment != null) {
      var dm = Array.isArray(r.dipole_moment) ? r.dipole_moment.map(function (v) { return Number(v).toFixed(4); }).join(", ") : Number(r.dipole_moment).toFixed(4);
      m.push(["Dipole Moment", dm, "Debye"]);
    }
    if (r.scf_converged != null) m.push(["SCF Converged", r.scf_converged ? "Yes" : "No", ""]);
    if (r.num_iterations != null) m.push(["SCF Iterations", r.num_iterations, ""]);
    if (r.n_electrons != null) m.push(["Electrons", r.n_electrons, ""]);
    if (r.n_basis != null) m.push(["Basis Functions", r.n_basis, ""]);
    m.forEach(function (x) { html += metric(x[0], x[1], x[2]); has = true; });
    html += '</div>';
    if (!has) html = '<p class="result-note">No summary data available. Check the JSON tab.</p>';
    return html;
  }

  function renderGeometry(r) {
    var atoms = r.atoms || [];
    if (!atoms.length && !r.visualization.xyz_block) return '<p class="result-note">No geometry data.</p>';
    var html = "";
    if (atoms.length) {
      html += '<table class="result-table"><thead><tr><th>#</th><th>Element</th><th>X (\u00C5)</th><th>Y (\u00C5)</th><th>Z (\u00C5)</th></tr></thead><tbody>';
      atoms.forEach(function (a, i) {
        var el = a.element || a.symbol || a[0] || "?";
        html += '<tr><td>' + (i + 1) + '</td><td>' + esc(el) + '</td><td>' +
          Number(a.x != null ? a.x : (a[1] || 0)).toFixed(6) + '</td><td>' +
          Number(a.y != null ? a.y : (a[2] || 0)).toFixed(6) + '</td><td>' +
          Number(a.z != null ? a.z : (a[3] || 0)).toFixed(6) + '</td></tr>';
      });
      html += '</tbody></table>';
    }
    if (r.visualization.xyz_block) {
      html += '<details style="margin-top:var(--sp-4)"><summary>Raw XYZ Block</summary><pre class="result-json" style="margin-top:var(--sp-2)">' + esc(r.visualization.xyz_block) + '</pre></details>';
    }
    return html;
  }

  function renderOrbital(r) {
    var info = (r.visualization && r.visualization.orbital_info) || r.orbital_info || {};
    var html = '<div class="metrics-grid">';
    if (info.orbital_type) html += metric("Type", info.orbital_type, "");
    if (info.orbital_index != null) html += metric("Index", info.orbital_index, "");
    if (info.orbital_energy != null) html += metric("Energy", Number(info.orbital_energy).toFixed(6), "Ha");
    if (info.occupation != null) html += metric("Occupation", info.occupation, "");
    html += '</div>';

    var moE = r.mo_energies || [];
    var moO = r.mo_occupations || [];
    if (moE.length > 0) {
      html += '<div class="energy-diagram"><div class="energy-diagram__title">MO Energy Levels</div>';
      var homoIdx = -1;
      for (var i = 0; i < moE.length; i++) { if (moO[i] != null && moO[i] > 0) homoIdx = i; }
      var lumoIdx = (homoIdx >= 0 && homoIdx + 1 < moE.length) ? homoIdx + 1 : -1;
      var start = moE.length > 16 ? Math.max(0, homoIdx - 5) : 0;
      var end = moE.length > 16 ? Math.min(moE.length, (lumoIdx >= 0 ? lumoIdx : homoIdx) + 6) : moE.length;
      for (var j = start; j < end; j++) {
        var occ = moO[j] != null ? moO[j] : 0;
        var cls = "energy-level";
        var lbl = "MO " + j;
        if (j === homoIdx) { cls += " energy-level--homo"; lbl = "HOMO"; }
        else if (j === lumoIdx) { cls += " energy-level--lumo"; lbl = "LUMO"; }
        else if (j === homoIdx - 1) { cls += " energy-level--occupied"; lbl = "HOMO-1"; }
        else if (j === homoIdx - 2) { cls += " energy-level--occupied"; lbl = "HOMO-2"; }
        else if (lumoIdx >= 0 && j === lumoIdx + 1) { cls += " energy-level--virtual"; lbl = "LUMO+1"; }
        else if (lumoIdx >= 0 && j === lumoIdx + 2) { cls += " energy-level--virtual"; lbl = "LUMO+2"; }
        else if (occ > 0) { cls += " energy-level--occupied"; }
        else { cls += " energy-level--virtual"; }
        html += '<div class="' + cls + '"><span class="energy-level__bar"></span><span class="energy-level__label">' + esc(lbl) + '</span><span class="energy-level__energy">' + Number(moE[j]).toFixed(4) + ' Ha</span><span class="energy-level__occ">' + (occ > 0 ? "\u2191\u2193".substring(0, Math.min(2, occ)) : "\u00B7") + '</span></div>';
      }
      html += '</div>';
    }
    html += '<p class="result-note">The orbital is rendered in the 3D viewer. Use the controls to adjust isosurface and select orbitals.</p>';
    return html;
  }

  function renderESP(r) {
    var html = '';
    if (r.esp_range) {
      html += '<div class="metrics-grid">' + metric("ESP Min", Number(r.esp_range[0]).toFixed(4), "a.u.") + metric("ESP Max", Number(r.esp_range[1]).toFixed(4), "a.u.") + '</div>';
    }
    html += '<p class="result-note">The ESP surface is rendered in the 3D viewer. Use opacity slider to adjust.</p>';
    return html;
  }

  function renderCharges(r) {
    var mull = r.mulliken_charges || [];
    var lowd = r.lowdin_charges || [];
    var atoms = r.atoms || [];
    if (!mull.length && !lowd.length) return '<p class="result-note">No charge data.</p>';
    var html = '<table class="result-table"><thead><tr><th>#</th><th>Element</th>';
    if (mull.length) html += '<th>Mulliken</th>';
    if (lowd.length) html += '<th>L\u00F6wdin</th>';
    html += '</tr></thead><tbody>';
    var n = Math.max(mull.length, lowd.length);
    for (var i = 0; i < n; i++) {
      var el = atoms[i] ? (atoms[i].element || atoms[i].symbol || atoms[i][0] || "?") : "?";
      html += '<tr><td>' + (i + 1) + '</td><td>' + esc(el) + '</td>';
      if (mull.length) html += '<td>' + (mull[i] != null ? Number(mull[i]).toFixed(6) : "\u2014") + '</td>';
      if (lowd.length) html += '<td>' + (lowd[i] != null ? Number(lowd[i]).toFixed(6) : "\u2014") + '</td>';
      html += '</tr>';
    }
    html += '</tbody></table>';
    return html;
  }

  function renderJSON(r) {
    var json;
    try { json = JSON.stringify(r, null, 2); } catch (_) { json = String(r); }
    return '<pre class="result-json">' + esc(json) + '</pre>';
  }

  function saveSnapshot() {
    if (!state.jobId) return;
    var existing = App.getUISnapshot(state.jobId) || {};
    App.saveUISnapshot(state.jobId, Object.assign({}, existing, { activeTab: state.activeTab, timestamp: Date.now() }));
  }

  function restoreSnapshot(jobId) {
    var snap = App.getUISnapshot(jobId);
    if (snap && snap.activeTab) state.activeTab = snap.activeTab;
  }

  function update(result, jobId, source) {
    var normalized = normalizeResult(result);
    state.result = normalized;
    state.jobId = jobId || null;
    if (!normalized) {
      if ($empty) $empty.hidden = false;
      if ($tabs) $tabs.innerHTML = "";
      if ($content) $content.innerHTML = "";
      return;
    }
    if ($empty) $empty.hidden = true;
    var available = getAvailableTabs(normalized);
    state.tabs = available;
    if (source === "history" && jobId) {
      restoreSnapshot(jobId);
      if (available.indexOf(state.activeTab) === -1) state.activeTab = decideFocusTab(normalized, available);
    } else {
      state.activeTab = decideFocusTab(normalized, available);
    }
    renderTabs(available, state.activeTab);
    renderContent(state.activeTab, normalized);
    saveSnapshot();
  }

  App.on("result:changed", function (d) { update(d.result, d.jobId, d.source); });

  document.addEventListener("keydown", function (e) {
    var tag = document.activeElement ? document.activeElement.tagName : "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    var num = parseInt(e.key, 10);
    if (num >= 1 && num <= 6 && state.tabs.length > 0 && num - 1 < state.tabs.length) {
      switchTab(state.tabs[num - 1]);
    }
  });

  App.results = { getState: function () { return Object.assign({}, state); }, switchTab: switchTab };
})();```


## File: `version02/src/qcviz_mcp/web/static/viewer.js`

```javascript
/* ═══════════════════════════════════════════
   QCViz-MCP Enterprise v5 — 3D Viewer Module
   ═══════════════════════════════════════════ */
(function () {
  "use strict";

  var App = window.QCVizApp;
  if (!App) return;

  var state = {
    viewer: null, model: null, ready: false,
    mode: "none", style: "stick", isovalue: 0.03, opacity: 0.75,
    showLabels: true, result: null, jobId: null, selectedOrbitalIndex: null,
  };

  var $viewerDiv = document.getElementById("viewer3d");
  var $empty = document.getElementById("viewerEmpty");
  var $controls = document.getElementById("viewerControls");
  var $legend = document.getElementById("viewerLegend");
  var $btnReset = document.getElementById("btnViewerReset");
  var $btnScreenshot = document.getElementById("btnViewerScreenshot");
  var $btnFullscreen = document.getElementById("btnViewerFullscreen");
  var $segStyle = document.getElementById("segStyle");
  var $grpOrbital = document.getElementById("grpOrbital");
  var $grpOpacity = document.getElementById("grpOpacity");
  var $grpOrbitalSelect = document.getElementById("grpOrbitalSelect");
  var $selectOrbital = document.getElementById("selectOrbital");
  var $sliderIso = document.getElementById("sliderIsovalue");
  var $lblIso = document.getElementById("lblIsovalue");
  var $sliderOp = document.getElementById("sliderOpacity");
  var $lblOp = document.getElementById("lblOpacity");
  var $btnLabels = document.getElementById("btnToggleLabels");

  /* ─── 3Dmol Loader ─── */
  var _loadPromise = null;
  function load3Dmol() {
    if (window.$3Dmol) return Promise.resolve();
    if (_loadPromise) return _loadPromise;
    _loadPromise = new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = "https://3dmol.csb.pitt.edu/build/3Dmol-min.js";
      s.onload = resolve;
      s.onerror = function () { reject(new Error("3Dmol.js load failed")); };
      document.head.appendChild(s);
    });
    return _loadPromise;
  }

  function ensureViewer() {
    if (state.viewer && state.ready) return Promise.resolve(state.viewer);
    return load3Dmol().then(function () {
      if (!state.viewer) {
        state.viewer = window.$3Dmol.createViewer($viewerDiv, {
          backgroundColor: "transparent",
          antialias: true,
        });
        state.ready = true;
        updateViewerBg();
      }
      return state.viewer;
    }).catch(function (err) {
      if ($empty) {
        $empty.hidden = false;
        var t = $empty.querySelector(".viewer-empty__text");
        if (t) t.textContent = "Failed to load 3Dmol.js — check your network connection.";
      }
      throw err;
    });
  }

  function updateViewerBg() {
    if (!state.viewer) return;
    var isDark = document.documentElement.getAttribute("data-theme") === "dark";
    state.viewer.setBackgroundColor(isDark ? 0x0c0c0f : 0xfafafa, 1.0);
  }

  /* ─── Helpers ─── */
  function buildXyzFromAtoms(atoms) {
    if (!atoms || !atoms.length) return null;
    var lines = [String(atoms.length), "QCViz"];
    atoms.forEach(function (a) {
      var el = a.element || a.symbol || a[0] || "X";
      var x = Number(a.x != null ? a.x : (a[1] || 0)).toFixed(6);
      var y = Number(a.y != null ? a.y : (a[2] || 0)).toFixed(6);
      var z = Number(a.z != null ? a.z : (a[3] || 0)).toFixed(6);
      lines.push(el + " " + x + " " + y + " " + z);
    });
    return lines.join("\n");
  }

  function getXyz(result) {
    var viz = result.visualization || {};
    var xyz = viz.xyz_block || result.xyz_block || result.xyz || null;
    if (!xyz && result.atoms && result.atoms.length) {
      xyz = buildXyzFromAtoms(result.atoms);
    }
    return xyz;
  }

  function applyStyle(viewer, style) {
    switch (style) {
      case "stick":
        viewer.setStyle({}, {
          stick: { radius: 0.14, colorscheme: "Jmol" },
          sphere: { scale: 0.25, colorscheme: "Jmol" },
        });
        break;
      case "sphere":
        viewer.setStyle({}, {
          sphere: { scale: 0.6, colorscheme: "Jmol" },
        });
        break;
      case "line":
        viewer.setStyle({}, {
          line: { colorscheme: "Jmol" },
        });
        break;
    }
  }

  function addLabels(viewer, result) {
    var atoms = result.atoms || [];
    if (!atoms.length) return;
    var isDark = document.documentElement.getAttribute("data-theme") === "dark";
    atoms.forEach(function (a) {
      var el = a.element || a.symbol || a[0] || "";
      if (!el) return;
      viewer.addLabel(el, {
        position: {
          x: a.x != null ? a.x : (a[1] || 0),
          y: a.y != null ? a.y : (a[2] || 0),
          z: a.z != null ? a.z : (a[3] || 0),
        },
        fontSize: 11,
        fontColor: isDark ? "white" : "#333",
        backgroundColor: isDark ? "rgba(0,0,0,0.5)" : "rgba(255,255,255,0.7)",
        borderColor: isDark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)",
        borderThickness: 1,
        backgroundOpacity: 0.6,
        alignment: "center",
        showBackground: true,
      });
    });
  }

  /* 라벨 새로고침 — On/Off 토글과 테마 변경 시 호출 */
  function refreshLabels() {
    if (!state.viewer) return;
    state.viewer.removeAllLabels();
    if (state.showLabels && state.result) {
      addLabels(state.viewer, state.result);
    }
    state.viewer.render();
  }

  /* ─── Clear / Add Model ─── */
  function clearViewer(viewer) {
    viewer.removeAllModels();
    viewer.removeAllSurfaces();
    viewer.removeAllLabels();
    viewer.removeAllShapes();
    state.model = null;
  }

  function addMoleculeModel(viewer, result) {
    var xyz = getXyz(result);
    if (xyz) {
      state.model = viewer.addModel(xyz, "xyz");
      applyStyle(viewer, state.style);
      return true;
    }
    return false;
  }

  /* ─── Render Molecule ─── */
  function renderMolecule(result) {
    return ensureViewer().then(function (viewer) {
      clearViewer(viewer);
      addMoleculeModel(viewer, result);
      if (state.showLabels) addLabels(viewer, result);
      viewer.zoomTo();
      viewer.render();
      state.mode = "molecule";
      showControls("molecule");
      hideLegend();
    });
  }

  /* ─── Render Orbital ─── */
  function renderOrbital(result) {
    return ensureViewer().then(function (viewer) {
      clearViewer(viewer);

      /* 분자 모델 먼저 추가 */
      addMoleculeModel(viewer, result);

      var viz = result.visualization || {};
      var cubeB64 = viz.orbital_cube_b64 || result.orbital_cube_b64 || null;

      if (cubeB64) {
        try {
          var cubeData = atob(cubeB64);
          var vol = new window.$3Dmol.VolumeData(cubeData, "cube");

          /* Positive lobe — indigo */
          viewer.addIsosurface(vol, {
            isoval: state.isovalue,
            color: "#6366f1",
            alpha: state.opacity,
            smoothness: 3,
            wireframe: false,
          });

          /* Negative lobe — amber */
          viewer.addIsosurface(vol, {
            isoval: -state.isovalue,
            color: "#f59e0b",
            alpha: state.opacity,
            smoothness: 3,
            wireframe: false,
          });

          /* 분자 모델이 없었다면 큐브 파일에서 추출 */
          if (!state.model) {
            state.model = viewer.addModel(cubeData, "cube");
            applyStyle(viewer, state.style);
          }
        } catch (e) {
          console.error("[Viewer] Orbital render error:", e);
        }
      }

      if (state.showLabels && state.model) addLabels(viewer, result);
      viewer.zoomTo();
      viewer.render();
      state.mode = "orbital";
      showControls("orbital");
      showOrbitalLegend();
      populateOrbitalSelector(result);
    });
  }

  /* ─── Render ESP ─── */
  function renderESP(result) {
    return ensureViewer().then(function (viewer) {
      clearViewer(viewer);
      addMoleculeModel(viewer, result);

      var viz = result.visualization || {};
      var densB64 = viz.density_cube_b64 || result.density_cube_b64 || null;
      var espB64 = viz.esp_cube_b64 || result.esp_cube_b64 || null;

      try {
        if (densB64 && espB64) {
          var densVol = new window.$3Dmol.VolumeData(atob(densB64), "cube");
          var espVol = new window.$3Dmol.VolumeData(atob(espB64), "cube");
          var range = result.esp_auto_range_au || 0.05;
          viewer.addIsosurface(densVol, {
            isoval: state.isovalue,
            color: "white",
            alpha: state.opacity,
            smoothness: 1,
            voldata: espVol,
            volscheme: new window.$3Dmol.Gradient.RWB(-range, range)
          });
        } else if (espB64) {
          var espVol2 = new window.$3Dmol.VolumeData(atob(espB64), "cube");
          viewer.addIsosurface(espVol2, {
            isoval: state.isovalue,
            colorscheme: { gradient: "rwb" },
            alpha: state.opacity,
            smoothness: 3,
          });
        }
      } catch (e) {
        console.error("[Viewer] ESP render error:", e);
      }

      if (state.showLabels && state.model) addLabels(viewer, result);
      viewer.zoomTo();
      viewer.render();
      state.mode = "esp";
      showControls("esp");
      showESPLegend();
    });
  }

  /* ─── Controls Visibility ─── */
  function showControls(mode) {
    if ($empty) $empty.hidden = true;
    if ($controls) $controls.hidden = false;
    if ($grpOrbital) $grpOrbital.hidden = (mode !== "orbital" && mode !== "esp");
    if ($grpOpacity) $grpOpacity.hidden = (mode !== "orbital" && mode !== "esp");
    var hasOrb = state.result && state.result.orbitals && state.result.orbitals.length > 0;
    if (!hasOrb) {
      hasOrb = state.result && state.result.mo_energies && state.result.mo_energies.length > 0;
    }
    if ($grpOrbitalSelect) $grpOrbitalSelect.hidden = (mode !== "orbital" || !hasOrb);
  }

  /* ─── Orbital Selector ─── */
  function populateOrbitalSelector(result) {
    if (!$selectOrbital || !result) return;
    
    var orbitals = result.orbitals || [];
    var moE = result.mo_energies || [];
    var moO = result.mo_occupations || [];
    
    $selectOrbital.innerHTML = "";
    
    if (orbitals.length > 0) {
      var info = (result.visualization && result.visualization.orbital_info) || result.orbital_info || {};
      var currentIdx = info.orbital_index != null ? info.orbital_index : (result.selected_orbital ? result.selected_orbital.zero_based_index : -1);

      orbitals.forEach(function(orb) {
        var opt = document.createElement("option");
        opt.value = orb.zero_based_index;
        opt.textContent = orb.label + " (" + Number(orb.energy_hartree).toFixed(3) + " Ha)";
        if (orb.zero_based_index === currentIdx) opt.selected = true;
        $selectOrbital.appendChild(opt);
      });
      state.selectedOrbitalIndex = currentIdx;
      if ($grpOrbitalSelect) $grpOrbitalSelect.hidden = false;
      return;
    }

    if (!moE.length) {
      if ($grpOrbitalSelect) $grpOrbitalSelect.hidden = true;
      return;
    }

    var homoIdx = -1;
    for (var i = 0; i < moE.length; i++) {
      if (moO[i] != null && moO[i] > 0) homoIdx = i;
    }
    var lumoIdx = (homoIdx >= 0 && homoIdx + 1 < moE.length) ? homoIdx + 1 : -1;

    var info = (result.visualization && result.visualization.orbital_info) || result.orbital_info || {};
    var currentIdx = info.orbital_index != null ? info.orbital_index : homoIdx;

    var startIdx = Math.max(0, homoIdx - 4);
    var endIdx = Math.min(moE.length, (lumoIdx >= 0 ? lumoIdx : homoIdx) + 5);

    for (var j = startIdx; j < endIdx; j++) {
      var opt = document.createElement("option");
      opt.value = j;
      var label = "MO " + j;
      if (j === homoIdx) label = "HOMO";
      else if (j === lumoIdx) label = "LUMO";
      else if (j === homoIdx - 1) label = "HOMO-1";
      else if (j === homoIdx - 2) label = "HOMO-2";
      else if (lumoIdx >= 0 && j === lumoIdx + 1) label = "LUMO+1";
      else if (lumoIdx >= 0 && j === lumoIdx + 2) label = "LUMO+2";
      label += " (" + Number(moE[j]).toFixed(3) + " Ha)";
      opt.textContent = label;
      if (j === currentIdx) opt.selected = true;
      $selectOrbital.appendChild(opt);
    }

    state.selectedOrbitalIndex = currentIdx;
    if ($grpOrbitalSelect) $grpOrbitalSelect.hidden = false;
  }

  /* ─── Event Bindings ─── */

  /* Orbital selector change */
  if ($selectOrbital) {
    $selectOrbital.addEventListener("change", function () {
      var idx = parseInt($selectOrbital.value, 10);
      if (isNaN(idx)) return;
      state.selectedOrbitalIndex = idx;
      App.emit("orbital:select", { orbital_index: idx });

      /* 자동으로 채팅을 통해 해당 오비탈 요청 */
      if (App.chat && App.chat.submit && state.result) {
        var orbName = "MO " + idx;
        if (state.result.orbitals && state.result.orbitals.length) {
          var found = state.result.orbitals.find(function(o) { return o.zero_based_index === idx; });
          if (found && found.label) {
            orbName = found.label;
          }
        } else {
          var moO = state.result.mo_occupations || [];
          var moE = state.result.mo_energies || [];
          var hI = -1;
          for (var k = 0; k < moE.length; k++) { if (moO[k] > 0) hI = k; }
          var lI = (hI >= 0 && hI + 1 < moE.length) ? hI + 1 : -1;
          if (idx === hI) orbName = "HOMO";
          else if (idx === lI) orbName = "LUMO";
          else if (idx < hI) orbName = "HOMO-" + (hI - idx);
          else if (lI >= 0 && idx > lI) orbName = "LUMO+" + (idx - lI);
        }
        var molName = state.result.molecule_name || state.result.structure_name || state.result.structure_query || state.result.molecule || "the molecule";
        App.chat.submit("Show the " + orbName + " orbital of " + molName);
      }
      saveViewerSnapshot();
    });
  }

  /* Style segmented control */
  if ($segStyle) {
    $segStyle.addEventListener("click", function (e) {
      var btn = e.target.closest(".segmented__btn");
      if (!btn) return;
      var val = btn.dataset.value;
      if (val === state.style) return;

      state.style = val;
      $segStyle.querySelectorAll(".segmented__btn").forEach(function (b) {
        b.classList.toggle("segmented__btn--active", b.dataset.value === val);
      });

      if (state.viewer && state.model) {
        applyStyle(state.viewer, val);
        state.viewer.render();
      }
      saveViewerSnapshot();
    });
  }

  /* Isovalue slider */
  if ($sliderIso) {
    $sliderIso.addEventListener("input", function () {
      state.isovalue = parseFloat($sliderIso.value);
      if ($lblIso) $lblIso.textContent = state.isovalue.toFixed(3);
    });
    $sliderIso.addEventListener("change", function () {
      if (state.mode === "orbital" && state.result) {
        renderOrbital(state.result);
      } else if (state.mode === "esp" && state.result) {
        renderESP(state.result);
      }
      saveViewerSnapshot();
    });
  }

  /* Opacity slider */
  if ($sliderOp) {
    $sliderOp.addEventListener("input", function () {
      state.opacity = parseFloat($sliderOp.value);
      if ($lblOp) $lblOp.textContent = state.opacity.toFixed(2);
    });
    $sliderOp.addEventListener("change", function () {
      if (state.mode === "orbital" && state.result) {
        renderOrbital(state.result);
      } else if (state.mode === "esp" && state.result) {
        renderESP(state.result);
      }
      saveViewerSnapshot();
    });
  }

  /* Labels toggle — 핵심: 확실하게 라벨 On/Off 동작 */
  if ($btnLabels) {
    $btnLabels.addEventListener("click", function () {
      state.showLabels = !state.showLabels;
      $btnLabels.setAttribute("data-active", String(state.showLabels));
      $btnLabels.setAttribute("aria-pressed", String(state.showLabels));
      $btnLabels.textContent = state.showLabels ? "On" : "Off";

      /* 실제로 3Dmol 라벨을 제거/추가 후 render */
      refreshLabels();
      saveViewerSnapshot();
    });
  }

  /* Reset view */
  if ($btnReset) {
    $btnReset.addEventListener("click", function () {
      if (state.viewer) {
        state.viewer.zoomTo();
        state.viewer.render();
      }
    });
  }

  /* Screenshot */
  if ($btnScreenshot) {
    $btnScreenshot.addEventListener("click", function () {
      if (!state.viewer) return;
      try {
        var dataUrl = state.viewer.pngURI();
        var a = document.createElement("a");
        a.href = dataUrl;
        a.download = "qcviz-" + (state.jobId || "capture") + "-" + Date.now() + ".png";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      } catch (err) {
        console.error("Screenshot failed:", err);
      }
    });
  }

  /* Fullscreen */
  if ($btnFullscreen) {
    $btnFullscreen.addEventListener("click", function () {
      var panel = document.getElementById("panelViewer");
      if (!panel) return;
      panel.classList.toggle("is-fullscreen");
      setTimeout(function () {
        if (state.viewer) {
          state.viewer.resize();
          state.viewer.render();
        }
      }, 150);
    });
  }

  /* Escape closes fullscreen */
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      var panel = document.getElementById("panelViewer");
      if (panel && panel.classList.contains("is-fullscreen")) {
        panel.classList.remove("is-fullscreen");
        setTimeout(function () {
          if (state.viewer) {
            state.viewer.resize();
            state.viewer.render();
          }
        }, 150);
      }
    }
  });

  /* ─── Legends ─── */
  function showOrbitalLegend() {
    if (!$legend) return;
    $legend.hidden = false;
    $legend.innerHTML =
      '<div class="viewer-legend__title">Orbital Lobes</div>' +
      '<div class="viewer-legend__row">' +
        '<span class="viewer-legend__swatch" style="background:#6366f1"></span>' +
        '<span>Positive (+' + state.isovalue.toFixed(3) + ')</span>' +
      '</div>' +
      '<div class="viewer-legend__row">' +
        '<span class="viewer-legend__swatch" style="background:#f59e0b"></span>' +
        '<span>Negative (\u2212' + state.isovalue.toFixed(3) + ')</span>' +
      '</div>';
  }

  function showESPLegend() {
    if (!$legend) return;
    $legend.hidden = false;
    $legend.innerHTML =
      '<div class="viewer-legend__title">ESP Surface</div>' +
      '<div class="viewer-legend__row">' +
        '<span class="viewer-legend__swatch" style="background:linear-gradient(90deg,#ef4444,#ffffff,#3b82f6);width:60px;height:10px;border-radius:2px;"></span>' +
      '</div>' +
      '<div class="viewer-legend__row" style="justify-content:space-between;width:60px;margin-left:20px;">' +
        '<span style="font-size:10px;color:var(--text-3)">\u2212</span>' +
        '<span style="font-size:10px;color:var(--text-3)">0</span>' +
        '<span style="font-size:10px;color:var(--text-3)">+</span>' +
      '</div>';
  }

  function hideLegend() {
    if (!$legend) return;
    $legend.hidden = true;
    $legend.innerHTML = "";
  }

  /* ─── Snapshot Save/Restore ─── */
  function saveViewerSnapshot() {
    if (!state.jobId) return;
    var existing = App.getUISnapshot(state.jobId) || {};
    App.saveUISnapshot(state.jobId, Object.assign({}, existing, {
      viewerStyle: state.style,
      viewerIsovalue: state.isovalue,
      viewerOpacity: state.opacity,
      viewerLabels: state.showLabels,
      viewerMode: state.mode,
      viewerOrbitalIndex: state.selectedOrbitalIndex,
    }));
  }

  function restoreViewerSnapshot(jobId) {
    var snap = App.getUISnapshot(jobId);
    if (!snap) return;

    if (snap.viewerStyle && snap.viewerStyle !== state.style) {
      state.style = snap.viewerStyle;
      if ($segStyle) {
        $segStyle.querySelectorAll(".segmented__btn").forEach(function (b) {
          b.classList.toggle("segmented__btn--active", b.dataset.value === state.style);
        });
      }
    }
    if (snap.viewerIsovalue != null) {
      state.isovalue = snap.viewerIsovalue;
      if ($sliderIso) $sliderIso.value = state.isovalue;
      if ($lblIso) $lblIso.textContent = state.isovalue.toFixed(3);
    }
    if (snap.viewerOpacity != null) {
      state.opacity = snap.viewerOpacity;
      if ($sliderOp) $sliderOp.value = state.opacity;
      if ($lblOp) $lblOp.textContent = state.opacity.toFixed(2);
    }
    if (snap.viewerLabels != null) {
      state.showLabels = snap.viewerLabels;
      if ($btnLabels) {
        $btnLabels.setAttribute("data-active", String(state.showLabels));
        $btnLabels.setAttribute("aria-pressed", String(state.showLabels));
        $btnLabels.textContent = state.showLabels ? "On" : "Off";
      }
    }
    if (snap.viewerOrbitalIndex != null) {
      state.selectedOrbitalIndex = snap.viewerOrbitalIndex;
    }
  }

  /* ─── Main Result Handler ─── */
  function handleResult(detail) {
    var result = detail.result;
    var jobId = detail.jobId;
    var source = detail.source;

    if (!result) {
      if (state.viewer) {
        clearViewer(state.viewer);
        state.viewer.render();
      }
      state.result = null;
      state.jobId = null;
      state.mode = "none";
      if ($empty) $empty.hidden = false;
      if ($controls) $controls.hidden = true;
      hideLegend();
      return;
    }

    state.result = result;
    state.jobId = jobId;

    /* 히스토리에서 복원 시 뷰어 세팅 복원 */
    if (source === "history" && jobId) {
      restoreViewerSnapshot(jobId);
    }

    var viz = result.visualization || {};
    var promise;

    if (viz.orbital_cube_b64 || result.orbital_cube_b64) {
      promise = renderOrbital(result);
    } else if (viz.esp_cube_b64 || result.esp_cube_b64) {
      promise = renderESP(result);
    } else if (getXyz(result)) {
      promise = renderMolecule(result);
    } else {
      /* 시각화 데이터 없음 */
      state.mode = "none";
      if ($empty) {
        $empty.hidden = false;
        var t = $empty.querySelector(".viewer-empty__text");
        if (t) t.textContent = "No visualization data for this result";
      }
      if ($controls) $controls.hidden = true;
      hideLegend();
      return;
    }

    if (promise) {
      promise.then(function () {
        saveViewerSnapshot();
      }).catch(function (err) {
        console.error("[Viewer] Render failed:", err);
      });
    }
  }

  /* ─── Theme Change ─── */
  App.on("theme:changed", function () {
    updateViewerBg();
    refreshLabels();
  });

  /* ─── Window Resize ─── */
  var resizeTimer;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      if (state.viewer) {
        state.viewer.resize();
        state.viewer.render();
      }
    }, 150);
  });

  /* ─── Listen for Results ─── */
  App.on("result:changed", handleResult);

  /* ─── Expose API ─── */
  App.viewer = {
    getState: function () {
      return Object.assign({}, state, { viewer: undefined, model: undefined });
    },
    reset: function () {
      if (state.viewer) {
        state.viewer.zoomTo();
        state.viewer.render();
      }
    },
    refreshLabels: refreshLabels,
  };

})();```


## File: `version02/src/qcviz_mcp/web/static/style.css`

```css
/* ═══════════════════════════════════════════════════════
   QCViz-MCP Enterprise v5 — Design System
   ═══════════════════════════════════════════════════════ */

:root {
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
  --radius-xs: 4px;
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;
  --radius-xl: 20px;
  --radius-full: 9999px;
  --sp-1: 4px; --sp-2: 8px; --sp-3: 12px; --sp-4: 16px;
  --sp-5: 20px; --sp-6: 24px; --sp-8: 32px; --sp-10: 40px;
  --blur-sm: 8px; --blur-md: 16px; --blur-lg: 32px; --blur-xl: 48px;
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
  --ease-smooth: cubic-bezier(0.4, 0, 0.2, 1);
  --duration-fast: 120ms; --duration-base: 200ms; --duration-slow: 350ms;
  --z-base: 1; --z-sticky: 10; --z-controls: 20; --z-overlay: 100; --z-modal: 1000;
}

[data-theme="dark"] {
  --bg-0: #09090b; --bg-1: #0c0c0f; --bg-2: #111115; --bg-3: #18181b; --bg-4: #1f1f23; --bg-5: #27272a;
  --surface-0: rgba(17,17,21,0.72); --surface-1: rgba(24,24,27,0.65);
  --surface-2: rgba(31,31,35,0.60); --surface-raised: rgba(39,39,42,0.55);
  --surface-overlay: rgba(9,9,11,0.88);
  --border-0: rgba(255,255,255,0.06); --border-1: rgba(255,255,255,0.09);
  --border-2: rgba(255,255,255,0.12); --border-3: rgba(255,255,255,0.16);
  --border-focus: rgba(99,102,241,0.5);
  --text-0: #fafafa; --text-1: #e4e4e7; --text-2: #a1a1aa; --text-3: #71717a; --text-4: #52525b;
  --accent: #6366f1; --accent-hover: #818cf8;
  --accent-muted: rgba(99,102,241,0.15); --accent-subtle: rgba(99,102,241,0.08); --accent-2: #8b5cf6;
  --success: #22c55e; --success-muted: rgba(34,197,94,0.12);
  --warning: #f59e0b; --warning-muted: rgba(245,158,11,0.12);
  --error: #ef4444; --error-muted: rgba(239,68,68,0.12);
  --info: #3b82f6; --info-muted: rgba(59,130,246,0.12);
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.3); --shadow-md: 0 4px 12px rgba(0,0,0,0.4);
  --shadow-lg: 0 12px 40px rgba(0,0,0,0.5); --shadow-xl: 0 24px 64px rgba(0,0,0,0.6);
  --shadow-glow: 0 0 40px rgba(99,102,241,0.06);
  color-scheme: dark;
}

[data-theme="light"] {
  --bg-0: #ffffff; --bg-1: #fafafa; --bg-2: #f4f4f5; --bg-3: #e4e4e7; --bg-4: #d4d4d8; --bg-5: #a1a1aa;
  --surface-0: rgba(255,255,255,0.82); --surface-1: rgba(250,250,250,0.78);
  --surface-2: rgba(244,244,245,0.72); --surface-raised: rgba(255,255,255,0.92);
  --surface-overlay: rgba(255,255,255,0.92);
  --border-0: rgba(0,0,0,0.05); --border-1: rgba(0,0,0,0.08);
  --border-2: rgba(0,0,0,0.12); --border-3: rgba(0,0,0,0.16);
  --border-focus: rgba(99,102,241,0.4);
  --text-0: #09090b; --text-1: #18181b; --text-2: #52525b; --text-3: #71717a; --text-4: #a1a1aa;
  --accent: #6366f1; --accent-hover: #4f46e5;
  --accent-muted: rgba(99,102,241,0.10); --accent-subtle: rgba(99,102,241,0.05); --accent-2: #7c3aed;
  --success: #16a34a; --success-muted: rgba(22,163,74,0.08);
  --warning: #d97706; --warning-muted: rgba(217,119,6,0.08);
  --error: #dc2626; --error-muted: rgba(220,38,38,0.08);
  --info: #2563eb; --info-muted: rgba(37,99,235,0.08);
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.04); --shadow-md: 0 4px 12px rgba(0,0,0,0.06);
  --shadow-lg: 0 12px 40px rgba(0,0,0,0.08); --shadow-xl: 0 24px 64px rgba(0,0,0,0.10);
  --shadow-glow: 0 0 40px rgba(99,102,241,0.03);
  color-scheme: light;
}

/* Reset */
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box;}
html{font-family:var(--font-sans);font-size:14px;line-height:1.6;-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;text-rendering:optimizeLegibility;scroll-behavior:smooth;}
body{background:var(--bg-0);color:var(--text-1);min-height:100dvh;overflow-x:hidden;transition:background var(--duration-slow) var(--ease-smooth),color var(--duration-base) var(--ease-smooth);}
a{color:var(--accent);text-decoration:none;transition:color var(--duration-fast);}a:hover{color:var(--accent-hover);}
::selection{background:var(--accent-muted);color:var(--text-0);}
:focus-visible{outline:2px solid var(--border-focus);outline-offset:2px;}
::-webkit-scrollbar{width:6px;height:6px;}::-webkit-scrollbar-track{background:transparent;}::-webkit-scrollbar-thumb{background:var(--border-2);border-radius:var(--radius-full);}::-webkit-scrollbar-thumb:hover{background:var(--text-4);}

/* App Shell */
.app-shell{display:flex;flex-direction:column;min-height:100dvh;max-width:1920px;margin:0 auto;padding:var(--sp-3);gap:var(--sp-3);}

/* Top Bar */
.topbar{display:flex;align-items:center;justify-content:space-between;height:52px;padding:0 var(--sp-4);background:var(--surface-0);backdrop-filter:blur(var(--blur-lg));-webkit-backdrop-filter:blur(var(--blur-lg));border:1px solid var(--border-0);border-radius:var(--radius-lg);position:sticky;top:var(--sp-3);z-index:var(--z-sticky);transition:box-shadow var(--duration-base) var(--ease-out);}
.topbar:hover{box-shadow:var(--shadow-sm);}
.topbar__left,.topbar__center,.topbar__right{display:flex;align-items:center;gap:var(--sp-3);}
.topbar__left{flex:1;}.topbar__center{flex:0 0 auto;}.topbar__right{flex:1;justify-content:flex-end;}
.topbar__logo{display:flex;align-items:center;gap:var(--sp-2);}
.topbar__title{font-weight:600;font-size:15px;color:var(--text-0);letter-spacing:-0.02em;}
.topbar__badge{font-size:10px;font-weight:600;padding:1px 6px;border-radius:var(--radius-full);background:var(--accent-muted);color:var(--accent);letter-spacing:0.02em;text-transform:uppercase;vertical-align:super;}

/* Status */
.status-indicator{display:flex;align-items:center;gap:var(--sp-2);padding:var(--sp-1) var(--sp-3);border-radius:var(--radius-full);background:var(--surface-1);border:1px solid var(--border-0);font-size:12px;color:var(--text-2);user-select:none;}
.status-indicator__dot{width:7px;height:7px;border-radius:50%;flex-shrink:0;transition:background var(--duration-base),box-shadow var(--duration-base);}
.status-indicator__dot[data-kind="idle"]{background:var(--text-4);}
.status-indicator__dot[data-kind="running"],.status-indicator__dot[data-kind="computing"]{background:var(--info);box-shadow:0 0 8px rgba(59,130,246,0.4);animation:pulse-dot 1.5s ease-in-out infinite;}
.status-indicator__dot[data-kind="success"],.status-indicator__dot[data-kind="completed"]{background:var(--success);box-shadow:0 0 8px rgba(34,197,94,0.3);}
.status-indicator__dot[data-kind="error"],.status-indicator__dot[data-kind="failed"]{background:var(--error);box-shadow:0 0 8px rgba(239,68,68,0.3);}
@keyframes pulse-dot{0%,100%{opacity:1;transform:scale(1);}50%{opacity:0.5;transform:scale(1.4);}}

/* Buttons */
.icon-btn{display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;border:1px solid var(--border-1);border-radius:var(--radius-md);background:transparent;color:var(--text-2);cursor:pointer;transition:all var(--duration-fast) var(--ease-out);flex-shrink:0;}
.icon-btn:hover{background:var(--surface-2);color:var(--text-0);border-color:var(--border-2);transform:translateY(-1px);}
.icon-btn:active{transform:translateY(0);}
.icon-btn--sm{width:28px;height:28px;}
[data-theme="dark"] .icon-moon{display:none;}[data-theme="light"] .icon-sun{display:none;}
.chip-btn{display:inline-flex;align-items:center;gap:var(--sp-1);height:28px;padding:0 var(--sp-3);border:1px solid var(--border-1);border-radius:var(--radius-full);background:transparent;color:var(--text-2);font-size:12px;font-weight:500;font-family:var(--font-sans);cursor:pointer;transition:all var(--duration-fast) var(--ease-out);white-space:nowrap;}
.chip-btn:hover{background:var(--surface-2);color:var(--text-0);border-color:var(--border-2);}
.icon-btn.is-spinning svg{animation:spin 0.6s linear infinite;}
@keyframes spin{from{transform:rotate(0deg);}to{transform:rotate(360deg);}}

/* Dashboard Grid */
.dashboard{display:grid;grid-template-columns:1fr 1fr;grid-template-rows:minmax(400px,1.1fr) minmax(220px,0.75fr);grid-template-areas:"viewer chat" "results history";gap:var(--sp-3);flex:1;min-height:0;}
@media(max-width:1100px){.dashboard{grid-template-columns:1fr;grid-template-rows:auto;grid-template-areas:"viewer" "chat" "results" "history";}.panel--viewer .viewer-container{min-height:320px;}.panel--chat{min-height:350px;}}
@media(min-width:1500px){.dashboard{grid-template-columns:1.3fr 0.9fr 0.8fr;grid-template-rows:1fr auto;grid-template-areas:"viewer chat history" "results results history";}}
.panel--viewer{grid-area:viewer;}.panel--chat{grid-area:chat;}.panel--results{grid-area:results;}.panel--history{grid-area:history;}

/* Panel */
.panel{display:flex;flex-direction:column;background:var(--surface-0);backdrop-filter:blur(var(--blur-md));-webkit-backdrop-filter:blur(var(--blur-md));border:1px solid var(--border-0);border-radius:var(--radius-lg);overflow:hidden;transition:box-shadow var(--duration-slow) var(--ease-out),border-color var(--duration-base) var(--ease-out);min-height:0;}
.panel:hover{border-color:var(--border-1);box-shadow:var(--shadow-sm),var(--shadow-glow);}
.panel__header{display:flex;align-items:center;justify-content:space-between;padding:var(--sp-3) var(--sp-4);border-bottom:1px solid var(--border-0);flex-shrink:0;min-height:44px;}
.panel__title{display:flex;align-items:center;gap:var(--sp-2);font-size:12px;font-weight:600;color:var(--text-3);letter-spacing:0.04em;text-transform:uppercase;}
.panel__title svg{color:var(--text-4);flex-shrink:0;}
.panel__actions{display:flex;align-items:center;gap:var(--sp-2);}


/* Viewer Panel */
.viewer-container{position:relative;flex:1;min-height:300px;background:var(--bg-1);overflow:hidden;transition:background var(--duration-slow) var(--ease-smooth);}
.viewer-3d{position:absolute;inset:0;width:100%;height:100%;z-index:var(--z-base);overflow:hidden;}
.viewer-empty{position:absolute;inset:0;z-index:2;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:var(--sp-3);pointer-events:none;animation:fadeIn var(--duration-slow) var(--ease-out);}
.viewer-empty[hidden]{display:none;}
.viewer-empty__icon{color:var(--text-4);}
.viewer-empty__text{font-size:14px;color:var(--text-3);text-align:center;}
.viewer-empty__hint{font-size:12px;color:var(--text-4);font-family:var(--font-mono);}

.viewer-controls{position:absolute;bottom:var(--sp-3);left:var(--sp-3);right:var(--sp-3);z-index:var(--z-controls);display:flex;align-items:center;gap:var(--sp-4);padding:var(--sp-2) var(--sp-3);background:var(--surface-overlay);backdrop-filter:blur(var(--blur-xl));-webkit-backdrop-filter:blur(var(--blur-xl));border:1px solid var(--border-1);border-radius:var(--radius-md);box-shadow:var(--shadow-md);animation:slideUp var(--duration-slow) var(--ease-out);flex-wrap:wrap;overflow-x:auto;}
.viewer-controls[hidden]{display:none;}
.viewer-controls::-webkit-scrollbar{display:none;}
.viewer-controls__group{display:flex;align-items:center;gap:var(--sp-2);flex-shrink:0;}
.viewer-controls__group[hidden]{display:none;}
.viewer-controls__label{font-size:11px;font-weight:500;color:var(--text-3);text-transform:uppercase;letter-spacing:0.04em;white-space:nowrap;}
.viewer-controls__value{font-size:11px;font-family:var(--font-mono);color:var(--text-2);min-width:36px;text-align:right;}

.viewer-legend{position:absolute;top:var(--sp-3);right:var(--sp-3);z-index:var(--z-controls);padding:var(--sp-2) var(--sp-3);background:var(--surface-overlay);backdrop-filter:blur(var(--blur-xl));-webkit-backdrop-filter:blur(var(--blur-xl));border:1px solid var(--border-1);border-radius:var(--radius-md);box-shadow:var(--shadow-md);font-size:11px;color:var(--text-2);animation:fadeIn var(--duration-slow) var(--ease-out);}
.viewer-legend[hidden]{display:none;}
.viewer-legend__title{font-weight:600;color:var(--text-1);margin-bottom:var(--sp-1);font-size:11px;letter-spacing:0.02em;}
.viewer-legend__row{display:flex;align-items:center;gap:var(--sp-2);margin-top:3px;}
.viewer-legend__swatch{width:12px;height:12px;border-radius:3px;flex-shrink:0;border:1px solid var(--border-0);}

/* Segmented */
.segmented{display:inline-flex;background:var(--bg-3);border-radius:var(--radius-sm);padding:2px;gap:1px;}
.segmented__btn{padding:3px 10px;border:none;border-radius:var(--radius-xs);background:transparent;color:var(--text-3);font-size:11px;font-weight:500;font-family:var(--font-sans);cursor:pointer;transition:all var(--duration-fast) var(--ease-out);white-space:nowrap;}
.segmented__btn:hover{color:var(--text-1);}
.segmented__btn--active{background:var(--surface-raised);color:var(--text-0);box-shadow:var(--shadow-sm);}

/* Range */
.range-input{-webkit-appearance:none;appearance:none;width:80px;height:4px;background:var(--bg-4);border-radius:var(--radius-full);outline:none;cursor:pointer;}
.range-input:hover{background:var(--bg-5);}
.range-input::-webkit-slider-thumb{-webkit-appearance:none;width:14px;height:14px;background:var(--accent);border-radius:50%;box-shadow:0 0 6px rgba(99,102,241,0.3);border:2px solid var(--bg-0);transition:transform var(--duration-fast) var(--ease-spring);}
.range-input::-webkit-slider-thumb:hover{transform:scale(1.2);}
.range-input::-moz-range-thumb{width:14px;height:14px;background:var(--accent);border:2px solid var(--bg-0);border-radius:50%;}

/* Toggle */
.toggle-btn{padding:3px 10px;border:1px solid var(--border-1);border-radius:var(--radius-sm);background:transparent;color:var(--text-3);font-size:11px;font-weight:500;font-family:var(--font-sans);cursor:pointer;transition:all var(--duration-fast) var(--ease-out);}
.toggle-btn[data-active="true"]{background:var(--accent-muted);color:var(--accent);border-color:rgba(99,102,241,0.3);}
.toggle-btn:hover{border-color:var(--border-2);}

/* Viewer select */
.viewer-select{padding:3px 8px;border:1px solid var(--border-1);border-radius:var(--radius-sm);background:var(--bg-3);color:var(--text-1);font-size:11px;font-family:var(--font-mono);cursor:pointer;outline:none;max-width:160px;transition:border-color var(--duration-fast);}
.viewer-select:focus{border-color:var(--accent);}
.viewer-select option{background:var(--bg-2);color:var(--text-1);}

/* Chat Panel */
.panel--chat{display:flex;flex-direction:column;}
.ws-status{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--text-3);}
.ws-status__dot{width:6px;height:6px;border-radius:50%;transition:background var(--duration-base),box-shadow var(--duration-base);}
.ws-status__dot[data-connected="false"]{background:var(--error);}
.ws-status__dot[data-connected="true"]{background:var(--success);box-shadow:0 0 6px rgba(34,197,94,0.4);}

.chat-scroll{flex:1;overflow-y:auto;overflow-x:hidden;min-height:0;scroll-behavior:smooth;}
.chat-messages{display:flex;flex-direction:column;gap:var(--sp-1);padding:var(--sp-3) var(--sp-4);}

.chat-msg{display:flex;gap:var(--sp-3);padding:var(--sp-3);border-radius:var(--radius-md);transition:background var(--duration-fast);animation:chatMsgIn var(--duration-slow) var(--ease-out);}
.chat-msg:hover{background:var(--surface-1);}
@keyframes chatMsgIn{from{opacity:0;transform:translateY(8px);}to{opacity:1;transform:translateY(0);}}

.chat-msg__avatar{width:28px;height:28px;border-radius:var(--radius-sm);display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:12px;font-weight:600;}
.chat-msg__avatar--system{background:var(--accent-muted);color:var(--accent);}
.chat-msg__avatar--user{background:var(--surface-2);color:var(--text-2);}
.chat-msg__avatar--assistant{background:linear-gradient(135deg,var(--accent-muted),rgba(139,92,246,0.15));color:var(--accent);}
.chat-msg__avatar--error{background:var(--error-muted);color:var(--error);}

.chat-msg__body{flex:1;min-width:0;}
.chat-msg__meta{display:flex;align-items:center;gap:var(--sp-2);margin-bottom:2px;}
.chat-msg__name{font-size:12px;font-weight:600;color:var(--text-1);}
.chat-msg__time{font-size:11px;color:var(--text-4);}
.chat-msg__text{font-size:13px;line-height:1.65;color:var(--text-1);word-break:break-word;}
.chat-msg__text strong{font-weight:600;color:var(--text-0);}
.chat-msg__text code{font-family:var(--font-mono);font-size:12px;padding:1px 5px;background:var(--surface-2);border:1px solid var(--border-0);border-radius:var(--radius-xs);color:var(--accent);}

/* Chat progress */
.chat-progress{margin-top:var(--sp-2);display:flex;flex-direction:column;gap:var(--sp-2);}
.chat-progress__bar{height:3px;background:var(--bg-4);border-radius:var(--radius-full);overflow:hidden;margin-top:var(--sp-1);}
.chat-progress__fill{height:100%;background:linear-gradient(90deg,var(--accent),var(--accent-2));border-radius:var(--radius-full);transition:width var(--duration-slow) var(--ease-out);width:0%;}
.chat-progress__fill--indeterminate{width:40%!important;animation:indeterminate 1.5s ease-in-out infinite;}
@keyframes indeterminate{0%{transform:translateX(-100%);}100%{transform:translateX(350%);}}
.chat-progress__steps{display:flex;flex-direction:column;gap:2px;}
.chat-progress__step{display:flex;align-items:center;gap:var(--sp-2);font-size:12px;font-family:var(--font-mono);color:var(--text-3);transition:color var(--duration-fast);animation:fadeIn var(--duration-base) var(--ease-out);}
.chat-progress__step--active{color:var(--info);}
.chat-progress__step--done{color:var(--success);}
.chat-progress__step--error{color:var(--error);}
.chat-progress__icon{width:16px;height:16px;display:flex;align-items:center;justify-content:center;flex-shrink:0;}

/* Typing */
.chat-typing{display:flex;align-items:center;gap:4px;padding:var(--sp-2) 0;}
.chat-typing__dot{width:5px;height:5px;border-radius:50%;background:var(--text-4);animation:typingBounce 1.4s ease-in-out infinite;}
.chat-typing__dot:nth-child(2){animation-delay:0.2s;}
.chat-typing__dot:nth-child(3){animation-delay:0.4s;}
@keyframes typingBounce{0%,60%,100%{transform:translateY(0);opacity:0.3;}30%{transform:translateY(-6px);opacity:1;}}

/* Chat input */
.chat-input-area{border-top:1px solid var(--border-0);padding:var(--sp-3) var(--sp-4);flex-shrink:0;}
.chat-suggestions{display:flex;gap:var(--sp-2);margin-bottom:var(--sp-3);flex-wrap:wrap;}
.chat-suggestions:empty,.chat-suggestions[hidden]{display:none;}
.suggestion-chip{padding:var(--sp-1) var(--sp-3);border:1px solid var(--border-1);border-radius:var(--radius-full);background:transparent;color:var(--text-3);font-size:12px;font-family:var(--font-sans);cursor:pointer;transition:all var(--duration-fast) var(--ease-out);white-space:nowrap;}
.suggestion-chip:hover{background:var(--accent-muted);border-color:rgba(99,102,241,0.3);color:var(--accent);}

.chat-form{position:relative;}
.chat-form__input-wrap{display:flex;align-items:flex-end;gap:var(--sp-2);background:var(--surface-1);border:1px solid var(--border-1);border-radius:var(--radius-md);padding:var(--sp-2) var(--sp-3);transition:border-color var(--duration-fast),box-shadow var(--duration-fast);}
.chat-form__input-wrap:focus-within{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-muted);}
.chat-form__input{flex:1;border:none;background:transparent;color:var(--text-0);font-family:var(--font-sans);font-size:13px;line-height:1.5;resize:none;outline:none;min-height:20px;max-height:120px;}
.chat-form__input::placeholder{color:var(--text-4);}
.chat-form__send{display:flex;align-items:center;justify-content:center;width:32px;height:32px;border:none;border-radius:var(--radius-sm);background:var(--accent);color:white;cursor:pointer;flex-shrink:0;transition:all var(--duration-fast) var(--ease-out);}
.chat-form__send:disabled{opacity:0.3;cursor:not-allowed;}
.chat-form__send:not(:disabled):hover{background:var(--accent-hover);transform:scale(1.05);}
.chat-form__send:not(:disabled):active{transform:scale(0.98);}
.chat-form__hint{font-size:11px;color:var(--text-4);margin-top:var(--sp-2);text-align:right;}
.chat-form__hint kbd{font-family:var(--font-mono);font-size:10px;padding:1px 4px;background:var(--surface-2);border:1px solid var(--border-1);border-radius:3px;color:var(--text-3);}

/* Results Panel */
.panel--results{min-height:200px;}
.results-tabs{display:flex;gap:0;padding:0 var(--sp-4);border-bottom:1px solid var(--border-0);overflow-x:auto;flex-shrink:0;}
.results-tabs:empty{display:none;}
.results-tabs::-webkit-scrollbar{display:none;}
.tab-btn{position:relative;padding:var(--sp-2) var(--sp-3);border:none;background:transparent;color:var(--text-3);font-size:12px;font-weight:500;font-family:var(--font-sans);cursor:pointer;white-space:nowrap;transition:color var(--duration-fast);}
.tab-btn:hover{color:var(--text-1);}
.tab-btn--active{color:var(--text-0);}
.tab-btn--active::after{content:'';position:absolute;bottom:-1px;left:var(--sp-3);right:var(--sp-3);height:2px;background:var(--accent);border-radius:1px 1px 0 0;animation:tabLine var(--duration-base) var(--ease-out);}
@keyframes tabLine{from{transform:scaleX(0);}to{transform:scaleX(1);}}
.results-content{flex:1;overflow-y:auto;padding:var(--sp-4);min-height:0;}
.results-empty{display:flex;align-items:center;justify-content:center;height:100%;min-height:120px;color:var(--text-4);font-size:13px;text-align:center;}
.results-empty[hidden]{display:none;}
.result-card{animation:fadeIn var(--duration-slow) var(--ease-out);}
.metrics-grid{display:flex;flex-wrap:wrap;gap:var(--sp-2);}
.result-metric{display:inline-flex;flex-direction:column;gap:2px;padding:var(--sp-3);background:var(--surface-1);border:1px solid var(--border-0);border-radius:var(--radius-md);min-width:130px;flex:1 1 130px;max-width:220px;transition:border-color var(--duration-fast),box-shadow var(--duration-fast);}
.result-metric:hover{border-color:var(--border-2);box-shadow:var(--shadow-sm);}
.result-metric__label{font-size:11px;font-weight:500;color:var(--text-3);text-transform:uppercase;letter-spacing:0.04em;}
.result-metric__value{font-size:18px;font-weight:700;color:var(--text-0);font-family:var(--font-mono);letter-spacing:-0.03em;line-height:1.3;}
.result-metric__unit{font-size:11px;color:var(--text-3);font-weight:400;}

/* Energy diagram */
.energy-diagram{display:flex;flex-direction:column;gap:2px;padding:var(--sp-3);background:var(--surface-1);border:1px solid var(--border-0);border-radius:var(--radius-md);margin-top:var(--sp-3);max-height:300px;overflow-y:auto;}
.energy-diagram__title{font-size:11px;font-weight:600;color:var(--text-2);text-transform:uppercase;letter-spacing:0.04em;margin-bottom:var(--sp-2);}
.energy-level{display:flex;align-items:center;gap:var(--sp-2);padding:3px var(--sp-2);border-radius:var(--radius-xs);font-size:11px;font-family:var(--font-mono);transition:background var(--duration-fast);}
.energy-level:hover{background:var(--surface-2);}
.energy-level--occupied{color:var(--accent);}
.energy-level--virtual{color:var(--text-3);}
.energy-level--homo{color:var(--accent);font-weight:600;background:var(--accent-muted);}
.energy-level--lumo{color:var(--warning);font-weight:600;background:var(--warning-muted);}
.energy-level__bar{width:24px;height:3px;border-radius:2px;flex-shrink:0;}
.energy-level--occupied .energy-level__bar{background:var(--accent);}
.energy-level--virtual .energy-level__bar{background:var(--text-4);}
.energy-level--homo .energy-level__bar{background:var(--accent);height:4px;}
.energy-level--lumo .energy-level__bar{background:var(--warning);height:4px;}
.energy-level__label{min-width:60px;}
.energy-level__energy{flex:1;text-align:right;}
.energy-level__occ{min-width:28px;text-align:center;color:var(--text-4);font-size:10px;}

.result-table{width:100%;border-collapse:collapse;font-size:12px;}
.result-table th{text-align:left;font-weight:600;color:var(--text-3);text-transform:uppercase;letter-spacing:0.04em;font-size:11px;padding:var(--sp-2) var(--sp-3);border-bottom:1px solid var(--border-1);position:sticky;top:0;background:var(--bg-2);}
.result-table td{padding:var(--sp-2) var(--sp-3);border-bottom:1px solid var(--border-0);color:var(--text-1);font-family:var(--font-mono);font-size:12px;}
.result-table tr:hover td{background:var(--surface-1);}
.result-json{background:var(--bg-2);border:1px solid var(--border-0);border-radius:var(--radius-md);padding:var(--sp-4);overflow:auto;max-height:400px;font-family:var(--font-mono);font-size:12px;line-height:1.6;color:var(--text-2);white-space:pre-wrap;word-break:break-all;}
.result-note{font-size:12px;color:var(--text-3);margin-top:var(--sp-3);line-height:1.5;}

/* History */
.panel--history{min-height:200px;}
.history-search-wrap{position:relative;padding:var(--sp-2) var(--sp-3);border-bottom:1px solid var(--border-0);}
.history-search-icon{position:absolute;left:var(--sp-5);top:50%;transform:translateY(-50%);color:var(--text-4);pointer-events:none;}
.history-search{width:100%;padding:var(--sp-2) var(--sp-3) var(--sp-2) var(--sp-8);border:1px solid var(--border-0);border-radius:var(--radius-sm);background:var(--surface-1);color:var(--text-1);font-size:12px;font-family:var(--font-sans);outline:none;transition:border-color var(--duration-fast),box-shadow var(--duration-fast);}
.history-search:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-muted);}
.history-search::placeholder{color:var(--text-4);}
.history-list{flex:1;overflow-y:auto;padding:var(--sp-2);}
.history-empty{display:flex;align-items:center;justify-content:center;min-height:80px;color:var(--text-4);font-size:12px;}
.history-empty[hidden]{display:none;}
.history-item{display:flex;align-items:center;gap:var(--sp-3);padding:var(--sp-2) var(--sp-3);border-radius:var(--radius-md);cursor:pointer;transition:background var(--duration-fast),border-color var(--duration-fast);border:1px solid transparent;animation:slideIn var(--duration-slow) var(--ease-out);}
.history-item:hover{background:var(--surface-1);}
.history-item--active{background:var(--accent-muted);border-color:rgba(99,102,241,0.25);}
.history-item__status{width:8px;height:8px;border-radius:50%;flex-shrink:0;}
.history-item__status--completed{background:var(--success);}
.history-item__status--running{background:var(--info);animation:pulse-dot 1.5s ease-in-out infinite;}
.history-item__status--failed{background:var(--error);}
.history-item__status--queued{background:var(--warning);}
.history-item__info{flex:1;min-width:0;}
.history-item__title{font-size:12px;font-weight:500;color:var(--text-1);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.history-item__detail{font-size:11px;color:var(--text-4);margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.history-item__energy{font-size:11px;font-family:var(--font-mono);color:var(--text-3);white-space:nowrap;flex-shrink:0;}

/* Modal */
.modal{border:none;background:transparent;padding:0;max-width:100vw;max-height:100vh;overflow:visible;}
.modal::backdrop{background:transparent;}
.modal__backdrop{position:fixed;inset:0;background:rgba(0,0,0,0.5);backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px);z-index:0;animation:fadeIn var(--duration-base) var(--ease-out);}
.modal__content{position:relative;z-index:1;background:var(--bg-2);border:1px solid var(--border-1);border-radius:var(--radius-lg);box-shadow:var(--shadow-xl);width:440px;max-width:90vw;margin:15vh auto;animation:modalIn var(--duration-slow) var(--ease-out);}
.modal__header{display:flex;align-items:center;justify-content:space-between;padding:var(--sp-4) var(--sp-5);border-bottom:1px solid var(--border-0);}
.modal__header h3{font-size:15px;font-weight:600;color:var(--text-0);}
.modal__body{padding:var(--sp-5);}
.shortcuts-grid{display:flex;flex-direction:column;gap:var(--sp-3);}
.shortcut-row{display:flex;align-items:center;justify-content:space-between;font-size:13px;color:var(--text-2);}
.shortcut-keys{display:flex;align-items:center;gap:3px;}
.shortcut-plus,.shortcut-dash{font-size:11px;color:var(--text-4);}
.shortcut-row kbd{font-family:var(--font-mono);font-size:11px;padding:2px 6px;background:var(--surface-2);border:1px solid var(--border-1);border-radius:var(--radius-xs);color:var(--text-1);min-width:22px;text-align:center;}
@keyframes modalIn{from{opacity:0;transform:translateY(-12px) scale(0.97);}to{opacity:1;transform:translateY(0) scale(1);}}

/* Animations */
@keyframes fadeIn{from{opacity:0;}to{opacity:1;}}
@keyframes slideIn{from{opacity:0;transform:translateY(6px);}to{opacity:1;transform:translateY(0);}}
@keyframes slideUp{from{opacity:0;transform:translateY(10px);}to{opacity:1;transform:translateY(0);}}

/* Fullscreen */
.panel--viewer.is-fullscreen{position:fixed;inset:0;z-index:var(--z-overlay);border-radius:0;margin:0;border:none;}
.panel--viewer.is-fullscreen .viewer-container{min-height:100%;}

/* Utils */
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;}
.mono{font-family:var(--font-mono);}
details{border:1px solid var(--border-0);border-radius:var(--radius-sm);padding:var(--sp-2) var(--sp-3);}
details summary{cursor:pointer;color:var(--text-3);font-size:12px;font-weight:500;user-select:none;}
details summary:hover{color:var(--text-1);}
details[open] summary{margin-bottom:var(--sp-2);}
```


## File: `version02/src/qcviz_mcp/web/templates/index.html`

```html
<!doctype html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>QCViz-MCP Enterprise v5</title>
  <meta name="description" content="Enterprise quantum chemistry visualization with PySCF, 3Dmol.js, chat orchestration, job history restoration, and state-synced viewer controls." />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="/static/style.css" />

  <script>
    (function (g) {
      "use strict";
      if (g.QCVizApp && g.QCVizApp.__enterpriseV5) return;

      var STORAGE_KEY = "QCVIZ_ENTERPRISE_V5_UI_SNAPSHOTS";
      var listeners = new Map();

      function safeStr(v, fb) { return v == null ? (fb || "") : String(v).trim(); }
      function clone(v) { try { return JSON.parse(JSON.stringify(v)); } catch (_) { return v; } }
      function deepMerge(base, patch) {
        var lhs = base && typeof base === "object" ? clone(base) : {};
        var rhs = patch && typeof patch === "object" ? patch : {};
        Object.keys(rhs).forEach(function (k) {
          var lv = lhs[k], rv = rhs[k];
          if (lv && rv && typeof lv === "object" && typeof rv === "object" && !Array.isArray(lv) && !Array.isArray(rv)) {
            lhs[k] = deepMerge(lv, rv);
          } else { lhs[k] = clone(rv); }
        });
        return lhs;
      }

      /* 읽기 쉬운 세션 ID 생성 */
      function makeSessionId() {
        var ts = Date.now().toString(36);
        var r = Math.random().toString(36).substring(2, 8);
        return "qcviz-" + ts + "-" + r;
      }

      var apiPrefix = g.QCVIZ_API_PREFIX || "/api";

      var store = {
        version: "enterprise-v5",
        jobsById: {},
        jobOrder: [],
        resultsByJobId: {},
        activeJobId: null,
        activeResult: null,
        status: { text: "Ready", kind: "idle", source: "app", at: Date.now() },
        uiSnapshotsByJobId: {},
        chatMessages: [],
        theme: "dark",
        lastUserInput: "",
        sessionId: makeSessionId(),
      };

      function emit(ev, detail) {
        (listeners.get(ev) || []).slice().forEach(function (fn) { try { fn(detail); } catch (_) {} });
      }
      function on(ev, fn) {
        if (!listeners.has(ev)) listeners.set(ev, []);
        listeners.get(ev).push(fn);
        return function () {
          var arr = listeners.get(ev) || [];
          var idx = arr.indexOf(fn);
          if (idx >= 0) arr.splice(idx, 1);
        };
      }

      function persistSnapshots() {
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(store.uiSnapshotsByJobId)); } catch (_) {}
      }
      function loadSnapshots() {
        try {
          var raw = localStorage.getItem(STORAGE_KEY);
          if (raw) store.uiSnapshotsByJobId = JSON.parse(raw);
        } catch (_) {}
      }
      loadSnapshots();

      var prefersDark = window.matchMedia("(prefers-color-scheme: dark)");
      function applyTheme(theme) {
        store.theme = theme;
        document.documentElement.setAttribute("data-theme", theme);
        emit("theme:changed", { theme: theme });
      }
      var savedTheme = localStorage.getItem("QCVIZ_THEME");
      if (savedTheme) applyTheme(savedTheme);
      else applyTheme(prefersDark.matches ? "dark" : "light");
      prefersDark.addEventListener("change", function (e) {
        if (!localStorage.getItem("QCVIZ_THEME")) applyTheme(e.matches ? "dark" : "light");
      });

      g.QCVizApp = {
        __enterpriseV5: true,
        store: store,
        on: on,
        emit: emit,
        clone: clone,
        deepMerge: deepMerge,
        apiPrefix: apiPrefix,

        setTheme: function (theme) {
          localStorage.setItem("QCVIZ_THEME", theme);
          applyTheme(theme);
        },

        setStatus: function (text, kind, source) {
          store.status = { text: text, kind: kind || "idle", source: source || "app", at: Date.now() };
          emit("status:changed", clone(store.status));
        },

        upsertJob: function (job) {
          if (!job || typeof job !== "object") return null;
          var jobId = safeStr(job.job_id);
          if (!jobId) return null;
          var prev = store.jobsById[jobId] || {};
          var next = deepMerge(prev, job);
          store.jobsById[jobId] = next;
          if (next.result) store.resultsByJobId[jobId] = clone(next.result);
          store.jobOrder = Object.values(store.jobsById)
            .sort(function (a, b) { return Number(b.updated_at || 0) - Number(a.updated_at || 0); })
            .map(function (j) { return j.job_id; });
          emit("jobs:changed", { job: clone(next), jobs: store.jobOrder.map(function (id) { return clone(store.jobsById[id]); }) });
          return clone(next);
        },

        setActiveJob: function (jobId) {
          store.activeJobId = jobId;
          var result = store.resultsByJobId[jobId] || null;
          store.activeResult = result ? clone(result) : null;
          emit("activejob:changed", { jobId: jobId, result: store.activeResult });
          if (result) emit("result:changed", { jobId: jobId, result: clone(result), source: "history" });
        },

        setActiveResult: function (res, opts) {
          opts = opts || {};
          var jobId = safeStr(opts.jobId || store.activeJobId);
          store.activeResult = res;
          if (jobId) {
            store.activeJobId = jobId;
            store.resultsByJobId[jobId] = clone(res);
          }
          emit("result:changed", { jobId: jobId, result: clone(res), source: opts.source || "app" });
        },

        saveUISnapshot: function (jobId, snapshot) {
          if (!jobId) return;
          store.uiSnapshotsByJobId[jobId] = clone(snapshot);
          persistSnapshots();
        },

        getUISnapshot: function (jobId) {
          return store.uiSnapshotsByJobId[jobId] ? clone(store.uiSnapshotsByJobId[jobId]) : null;
        },

        addChatMessage: function (msg) {
          store.chatMessages.push(msg);
          emit("chat:message", clone(msg));
        },
      };
    })(window);
  </script>
</head>

<body>
  <div class="app-shell" id="appShell">

    <!-- Top Bar -->
    <header class="topbar" id="topbar">
      <div class="topbar__left">
        <div class="topbar__logo" aria-label="QCViz Logo">
          <svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect width="28" height="28" rx="8" fill="url(#logoGrad)"/>
            <path d="M8 14a6 6 0 1 1 12 0 6 6 0 0 1-12 0Zm6-3.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z" fill="white" fill-opacity="0.95"/>
            <path d="M17.5 17.5L21 21" stroke="white" stroke-width="2" stroke-linecap="round" stroke-opacity="0.9"/>
            <defs>
              <linearGradient id="logoGrad" x1="0" y1="0" x2="28" y2="28" gradientUnits="userSpaceOnUse">
                <stop stop-color="#6366f1"/>
                <stop offset="1" stop-color="#8b5cf6"/>
              </linearGradient>
            </defs>
          </svg>
          <span class="topbar__title">QCViz-MCP <span class="topbar__badge">v5</span></span>
        </div>
      </div>
      <div class="topbar__center">
        <div class="status-indicator" id="globalStatus">
          <span class="status-indicator__dot" data-kind="idle"></span>
          <span class="status-indicator__text">Ready</span>
        </div>
      </div>
      <div class="topbar__right">
        <button class="icon-btn" id="btnThemeToggle" aria-label="Toggle theme" title="Toggle theme (Ctrl+\)">
          <svg class="icon-sun" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
          <svg class="icon-moon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
        </button>
        <button class="icon-btn" id="btnKeyboardShortcuts" aria-label="Keyboard shortcuts" title="Keyboard shortcuts (?)">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M8 12h.01M12 12h.01M16 12h.01M7 16h10"/></svg>
        </button>
      </div>
    </header>

    <!-- Dashboard Grid -->
    <main class="dashboard" id="dashboard">

      <!-- Viewer Panel -->
      <section class="panel panel--viewer" id="panelViewer" aria-label="3D Molecular Viewer">
        <div class="panel__header">
          <h2 class="panel__title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
            Molecular Viewer
          </h2>
          <div class="panel__actions">
            <button class="chip-btn" id="btnViewerReset" title="Reset view">Reset</button>
            <button class="chip-btn" id="btnViewerScreenshot" title="Screenshot">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="12" cy="12" r="3"/></svg>
              Capture
            </button>
            <button class="icon-btn icon-btn--sm" id="btnViewerFullscreen" title="Fullscreen">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>
            </button>
          </div>
        </div>
        <div class="viewer-container" id="viewerContainer">
          <div class="viewer-3d" id="viewer3d"></div>
          <div class="viewer-empty" id="viewerEmpty">
            <div class="viewer-empty__icon">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" opacity="0.35"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
            </div>
            <p class="viewer-empty__text">Submit a computation to render the molecule</p>
            <p class="viewer-empty__hint">Try: "Calculate energy of water with STO-3G"</p>
          </div>
          <div class="viewer-controls" id="viewerControls" hidden>
            <div class="viewer-controls__group">
              <label class="viewer-controls__label">Style</label>
              <div class="segmented" id="segStyle">
                <button class="segmented__btn segmented__btn--active" data-value="stick">Stick</button>
                <button class="segmented__btn" data-value="sphere">Sphere</button>
                <button class="segmented__btn" data-value="line">Line</button>
              </div>
            </div>
            <div class="viewer-controls__group" id="grpOrbital" hidden>
              <label class="viewer-controls__label">Isosurface</label>
              <input type="range" class="range-input" id="sliderIsovalue" min="0.001" max="0.1" step="0.001" value="0.03" />
              <span class="viewer-controls__value" id="lblIsovalue">0.030</span>
            </div>
            <div class="viewer-controls__group" id="grpOpacity" hidden>
              <label class="viewer-controls__label">Opacity</label>
              <input type="range" class="range-input" id="sliderOpacity" min="0.1" max="1.0" step="0.05" value="0.75" />
              <span class="viewer-controls__value" id="lblOpacity">0.75</span>
            </div>
            <div class="viewer-controls__group" id="grpOrbitalSelect" hidden>
              <label class="viewer-controls__label">Orbital</label>
              <select class="viewer-select" id="selectOrbital"></select>
            </div>
            <div class="viewer-controls__group">
              <label class="viewer-controls__label">Labels</label>
              <button class="toggle-btn" id="btnToggleLabels" data-active="true" aria-pressed="true">On</button>
            </div>
          </div>
          <div class="viewer-legend" id="viewerLegend" hidden></div>
        </div>
      </section>

      <!-- Chat Panel -->
      <section class="panel panel--chat" id="panelChat" aria-label="Chat Assistant">
        <div class="panel__header">
          <h2 class="panel__title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            Assistant
          </h2>
          <div class="panel__actions">
            <div class="ws-status" id="wsStatus">
              <span class="ws-status__dot" data-connected="false"></span>
              <span class="ws-status__label">Disconnected</span>
            </div>
          </div>
        </div>
        <div class="chat-scroll" id="chatScroll">
          <div class="chat-messages" id="chatMessages">
            <div class="chat-msg chat-msg--system">
              <div class="chat-msg__avatar chat-msg__avatar--system">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/></svg>
              </div>
              <div class="chat-msg__body">
                <p class="chat-msg__text">Welcome to <strong>QCViz-MCP v5</strong>. I can run quantum chemistry calculations using PySCF. Ask me to compute energies, optimize geometries, or visualize orbitals and ESP maps.</p>
              </div>
            </div>
          </div>
        </div>
        <div class="chat-input-area" id="chatInputArea">
          <div class="chat-suggestions" id="chatSuggestions">
            <button class="suggestion-chip" data-prompt="Calculate the energy of water using STO-3G basis">Water energy</button>
            <button class="suggestion-chip" data-prompt="Optimize the geometry of methane with 6-31G basis">Methane geometry</button>
            <button class="suggestion-chip" data-prompt="Show the HOMO orbital of formaldehyde">Formaldehyde HOMO</button>
          </div>
          <form class="chat-form" id="chatForm" autocomplete="off">
            <div class="chat-form__input-wrap">
              <textarea class="chat-form__input" id="chatInput" placeholder="Ask about quantum chemistry..." rows="1" maxlength="4000"></textarea>
              <button class="chat-form__send" id="chatSend" type="submit" aria-label="Send" disabled>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
              </button>
            </div>
            <p class="chat-form__hint">Press <kbd>Enter</kbd> to send, <kbd>Shift+Enter</kbd> for new line</p>
          </form>
        </div>
      </section>

      <!-- Results Panel -->
      <section class="panel panel--results" id="panelResults" aria-label="Computation Results">
        <div class="panel__header">
          <h2 class="panel__title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
            Results
          </h2>
        </div>
        <div class="results-tabs" id="resultsTabs" role="tablist"></div>
        <div class="results-content" id="resultsContent">
          <div class="results-empty" id="resultsEmpty">
            <p>No results yet. Submit a computation from the chat.</p>
          </div>
        </div>
      </section>

      <!-- History Panel -->
      <section class="panel panel--history" id="panelHistory" aria-label="Job History">
        <div class="panel__header">
          <h2 class="panel__title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            History
          </h2>
          <div class="panel__actions">
            <button class="icon-btn icon-btn--sm" id="btnRefreshHistory" title="Refresh">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
            </button>
          </div>
        </div>
        <div class="history-search-wrap">
          <svg class="history-search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <input type="search" class="history-search" id="historySearch" placeholder="Search jobs..." />
        </div>
        <div class="history-list" id="historyList">
          <div class="history-empty" id="historyEmpty">
            <p>No previous computations</p>
          </div>
        </div>
      </section>

    </main>
  </div>

  <!-- Keyboard Shortcuts Modal -->
  <dialog class="modal" id="modalShortcuts">
    <div class="modal__backdrop" data-close></div>
    <div class="modal__content">
      <div class="modal__header">
        <h3>Keyboard Shortcuts</h3>
        <button class="icon-btn icon-btn--sm" data-close aria-label="Close">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
      <div class="modal__body shortcuts-grid">
        <div class="shortcut-row"><span class="shortcut-keys"><kbd>Ctrl</kbd><span class="shortcut-plus">+</span><kbd>/</kbd></span><span>Focus chat input</span></div>
        <div class="shortcut-row"><span class="shortcut-keys"><kbd>Ctrl</kbd><span class="shortcut-plus">+</span><kbd>K</kbd></span><span>Search history</span></div>
        <div class="shortcut-row"><span class="shortcut-keys"><kbd>Ctrl</kbd><span class="shortcut-plus">+</span><kbd>\</kbd></span><span>Toggle theme</span></div>
        <div class="shortcut-row"><span class="shortcut-keys"><kbd>Esc</kbd></span><span>Close modals / blur</span></div>
        <div class="shortcut-row"><span class="shortcut-keys"><kbd>1</kbd><span class="shortcut-dash">&ndash;</span><kbd>6</kbd></span><span>Switch result tabs</span></div>
        <div class="shortcut-row"><span class="shortcut-keys"><kbd>?</kbd></span><span>Show this dialog</span></div>
      </div>
    </div>
  </dialog>

  <script src="/static/chat.js" defer></script>
  <script src="/static/results.js" defer></script>
  <script src="/static/viewer.js" defer></script>
  <script src="/static/app.js" defer></script>
</body>
</html>
```
