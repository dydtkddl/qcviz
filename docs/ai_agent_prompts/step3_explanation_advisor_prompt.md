# Step 3 Prompt: Result Explanation, Advisor, Observability, Live Validation

```text
당신은 이 프로젝트의 Step 3 담당 엔지니어다.
이번 Step의 목표는 계산 완료 이후의 경험을 AI-native하게 만드는 것이다.
즉 결과를 사람이 이해할 수 있게 설명하고, advisor를 자연스럽게 workflow에 녹이고, 실제 운영 수준의 검증까지 마무리해야 한다.

프로젝트 루트:
- /mnt/d/20260305_양자화학시각화MCP서버구축/version03

전제:
- Step 1에서 planner/normalization/schema가 정리되어 있다.
- Step 2에서 clarification UX와 세션 merge가 동작한다.
- 이번 Step에서는 결과 해설, next actions, advisor integration, observability, live smoke를 완성한다.

집중 대상 파일:
- src/qcviz_mcp/web/advisor_flow.py
- src/qcviz_mcp/llm/bridge.py
- src/qcviz_mcp/compute/pyscf_runner.py
- src/qcviz_mcp/web/static/results.js
- 필요 시 explanation helper/schema 파일

Step 3 최종 목표:
- 계산 결과를 사람이 이해 가능한 summary와 해설로 제공
- next actions를 제안
- advisor 기능을 자연어 workflow 안으로 통합
- observability와 live validation까지 마무리

반드시 구현할 것:
1. ResultExplanation 생성기
- 최소 필드:
  - summary
  - key_findings[]
  - interpretation[]
  - cautions[]
  - next_actions[]
- explanation은 계산값을 fabricated하지 말고 실제 결과를 바탕으로 생성
- 불확실하면 보수적으로 표현

2. job type별 explanation 정책
- orbital_preview
- esp_map
- partial_charges
- geometry_analysis
- geometry_optimization
- analyze
- 각 타입별로 무엇을 강조할지 정리된 template를 만들고, 필요 시 Gemini narrative를 결합

3. results UI 통합
- results.js 에 explanation panel 추가
- summary, key findings, cautions, next actions가 명확히 보이게 렌더링
- advisor 결과와 충돌하지 않게 구조를 잡을 것
- SCF/optimization 같은 반복 계산이 진행되거나 완료된 경우 수렴 그래프를 보여줄 것
- 최소 요구:
  - 진행 중 chat/progress 영역에서 SCF convergence mini-chart
  - 결과 패널에서 최종 SCF history / convergence summary / cycle count 표시
- HOMO/LUMO, total energy, orbital gap, ESP range 등 주요 수치 표기는 단위 변환이 가능해야 한다
- 최소 요구:
  - energy-like quantities: Hartree / eV / kcal/mol 등 상황에 맞는 단위 전환
  - orbital energies: Hartree / eV 전환
  - UI에서 단위 토글이 가능하고 선택 상태가 일관되게 유지될 것
  - payload에는 가능한 한 원시 단위값과 변환 단위값을 함께 보존할 것

4. advisor 자연통합
- advisor_flow.py / llm/bridge.py를 정리해 사용자 목표와 결과에 맞게 advisor를 호출
- 다음 기능을 자연스럽게 묶을 것:
  - preset recommendation
  - methods section draft
  - script generation
  - literature summary
  - confidence summary
- 결과 탭 focus도 적절히 자동 조정

5. 실패 복구 UX
- structure resolve 실패
- 계산 실패
- advisor 실패
- 이런 경우 각각 사용자 친화적인 recovery option을 제공
- 예:
  - 대체 분자 후보
  - 입력 수정 제안
  - 다시 시도
  - simpler calculation 추천

6. observability
- planner latency
- Gemini success ratio
- fallback ratio
- MolChat resolution success ratio
- 주요 failure reason
- tracing/logging은 운영에서 원인 파악이 가능하도록 남겨라

7. live smoke and regression
- 실제 Gemini 호출
- 실제 MolChat 호출
- 실제 브라우저 E2E
- 기존 compute contract regression 검증

필수 테스트:
- explanation schema validation
- explanation content sanity tests
- advisor happy path integration
- advisor failure fallback
- SCF convergence data propagation tests
- unit conversion and display tests
- live smoke marker tests
- browser E2E with actual server
- regression tests for result payload compatibility

대표 기대 결과:
- 사용자가 계산이 끝난 뒤 숫자만 보는 것이 아니라
  - 이 결과가 무엇을 뜻하는지
  - 어떤 해석이 가능한지
  - 주의할 점이 무엇인지
  - 다음에 어떤 계산을 해보면 좋은지
  를 바로 이해할 수 있어야 한다.

금지사항:
- LLM이 실제 계산 근거 없이 과장된 해석을 만들어내는 것
- advisor 결과를 별개 섬처럼 분리해두는 것
- observability 없이 live 기능을 붙이는 것
- regression 검증 없이 payload를 바꾸는 것

종료 기준:
- 결과 summary/explanation/next actions가 실제 UI에 보임
- advisor가 자연어 workflow에 자연스럽게 연결됨
- pytest, playwright, live smoke까지 통과

작업 완료 후 보고 형식:
1. explanation architecture
2. advisor integration strategy
3. observability additions
4. live smoke result
5. 수정 파일 목록
6. 테스트 결과
7. 남은 scientific/UX 리스크
```
