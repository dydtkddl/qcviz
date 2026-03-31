# Release Notes
## QCViz-MCP v3
### Chat Grounding & Conversation Reliability Update

이번 업데이트는 사용자 입력 해석의 정확도, 분자 후보 선택의 신뢰성, 그리고 대화 흐름의 안정성을 높이는 데 초점을 맞췄습니다. 특히 서술형 분자 질의, 약어 기반 요청, 후속 질문 처리, 그리고 MolChat 연동 경계에서 발생하던 혼선을 줄여, 사용자가 더 자연스럽게 계산을 이어갈 수 있도록 개선했습니다.

## 주요 개선 사항

### 1. Semantic grounding 정확도 향상

- `TNT에 들어가는 주물질` 같은 설명형 질의가 더 이상 raw 문장 자체나 무관한 기본 예시 후보로 처리되지 않습니다.
- MolChat의 `/molecules/interpret` 경로를 중심으로 의미를 해석하고, 가능한 경우 실제 분자 후보 기반 dropdown을 구성합니다.
- semantic grounding 경로에서는 `water`, `benzene`, `ethanol` 같은 generic fallback 후보가 더 이상 끼어들지 않도록 정리했습니다.

### 2. 질문형 입력과 계산 요청의 분리 강화

- `MEA 알아?`, `HOMO가 뭐야?` 같은 입력은 이제 설명형 대화 질문으로 우선 처리됩니다.
- 반대로 `MEA HOMO 보여줘`처럼 계산 의도는 있지만 분자 의미가 불명확한 경우에는, 바로 계산하지 않고 먼저 의미 확인 단계로 진입합니다.
- 이로써 질문형 입력이 무리하게 계산 경로로 들어가던 문제가 줄어들었습니다.

### 3. 직접적인 분자 계산 요청은 그대로 빠르게 유지

- `benzene HOMO 보여줘`, `methylamine ESP 보여줘` 같은 명시적 분자명 + 계산 요청은 기존처럼 바로 계산됩니다.
- 안전장치를 강화하면서도, 정상적인 빠른 계산 흐름은 유지했습니다.

### 4. 후속 질문과 구조 재사용 안정화

- 사용자가 이미 하나의 분자를 확정한 뒤 `ESP도 보여줘`, `최적화도 해줘` 같은 후속 질문을 하면, 같은 구조를 더 안정적으로 이어받습니다.
- canonical molecule을 선택한 뒤 다시 다른 clarification으로 튀거나, 선택된 구조가 재해석되는 문제가 줄어들었습니다.

### 5. 멀티분자 요청 처리 개선

- 여러 분자를 한 번에 포함한 문단형 요청은, 선택 대상이 충분히 명확한 경우 불필요한 semantic clarification 없이 배치 계산 경로로 진행됩니다.
- explicit multi-molecule selection이 semantic descriptor보다 우선하도록 라우팅 순서를 조정했습니다.

### 6. MolChat 연동 fallback 안정화

- MolChat `interpret` endpoint가 unavailable이거나 적절한 후보를 주지 못하는 경우에도, QCViz가 더 안전하게 fallback을 처리하도록 개선했습니다.
- semantic grounding 실패 시 무관한 기본 후보를 보여주는 대신, 보수적인 clarification 또는 `custom` 경로로 유도합니다.

### 7. 대화 상태와 결과 매칭 안정성 개선

- clarification 카드가 불필요하게 누적되거나, 이전 턴 결과가 현재 질문에 섞여 보이는 현상을 줄였습니다.
- turn 단위 상태 관리와 result binding 경계를 정리해, 실제 사용자 기준으로 대화가 덜 불안정하게 느껴지도록 개선했습니다.

## 사용자 체감 변화

이번 업데이트 이후 사용자는 다음과 같은 차이를 느끼게 됩니다.

- 설명형 분자 질의에서 엉뚱한 후보가 덜 뜹니다.
- 질문형 입력이 무리하게 계산으로 들어가지 않습니다.
- 구조를 한 번 정하면, 후속 질문이 더 자연스럽게 이어집니다.
- 여러 턴을 주고받아도 결과와 맥락이 덜 섞이고 덜 헷갈립니다.
- 전체적으로 QCViz가 아무 말이나 계산으로 밀어 넣는 시스템이 아니라, 의미를 먼저 확인하고 계산을 안전하게 연결하는 시스템처럼 동작합니다.

## 내부적으로 보장된 동작 원칙

- semantic descriptor 경로에서는 raw descriptive phrase를 후보 옵션으로 재승격하지 않음
- semantic descriptor 경로에서는 generic fallback 후보를 허용하지 않음
- unknown acronym 기반 compute request는 semantic grounding을 먼저 요구함
- explicit molecule, explicit batch selection, structure-locked follow-up은 기존 계산 경로를 유지함

## 검증 포인트

이번 변경은 다음 경계를 중심으로 회귀 검증되었습니다.

- unknown acronym compute request -> semantic grounding
- concept question -> chat-only
- semantic descriptor selected canonical candidate -> compute without second clarification
- analysis-only follow-up -> previous structure reuse
- explicit multi-molecule paragraph -> compute-ready
- semantic descriptor path -> no generic fallback, no raw phrase option
