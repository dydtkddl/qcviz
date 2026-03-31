# QCViz + MolChat Core Bundle Manifest

이 문서는 `QCVIZ_MOLCHAT_CORE_BUNDLE_2026-03-30.zip`에 포함된 주요 경로와 목적을 정리한 매니페스트다.

## 목적

- 외부 LLM 또는 외부 엔지니어가 현재 `QCViz version03`와 `MolChat v3`의 핵심 종속 로직을 한 번에 검토할 수 있도록 한다.
- semantic grounding, chat vs compute routing, clarification lifecycle, MolChat interpret/search/resolve, frontend state integrity, compute submission 흐름을 빠짐없이 포함한다.

## 포함 범위

### QCViz

- `pyproject.toml`
- `README.md`
- `src/qcviz_mcp/`
  - LLM planning / normalization
  - MolChat / PubChem / structure resolution services
  - compute runner
  - web app / routes / state / runtime / auth / result explanation
  - static frontend assets including chat UI logic
- `tests/`
  - REST / WebSocket / Playwright / runtime / unit tests

### MolChat

- `backend/app/`
  - FastAPI app
  - routers
  - schemas
  - molecule engine orchestrator / query resolver
  - dependent backend logic under `app/`
- `tests/`
  - molecule interpret 관련 테스트
- `backend/requirements.txt` 또는 동등한 환경 파일이 존재하면 함께 포함

## 제외 범위

- 가상환경, 캐시, 빌드 산출물
- 대용량 데이터 디렉터리
- 사용자별 비밀키가 들어 있는 `.env`
- 무관한 상위 저장소 파일

## 포함 이유

- 외부 LLM이 단순히 일부 함수만 보는 수준이 아니라, 실제 사용자 경험과 상태 전이를 재구성할 수 있게 하기 위함
- MolChat를 단순 resolver backend가 아니라 semantic grounding partner로 평가할 수 있게 하기 위함
- 테스트 코드까지 함께 제공하여 기대 동작, 회귀 포인트, 현재 설계 의도를 읽을 수 있게 하기 위함

## 생성물

- ZIP: `QCVIZ_MOLCHAT_CORE_BUNDLE_2026-03-30.zip`
- Base64 fallback: `QCVIZ_MOLCHAT_CORE_BUNDLE_2026-03-30.zip.base64.txt`
- 생성 스크립트: `build_qcviz_molchat_core_bundle_2026-03-30.ps1`

