# QCViz Advisor Lookup Master Prompt

아래 프롬프트를 다른 LLM에게 그대로 전달하라.  
이 프롬프트의 목적은 `functional_recommendations.json`을 최신 문헌, 공식 문서, 실무 커뮤니티 신호를 교차검증하여 엔터프라이즈급 업그레이드 초안으로 재구성하게 만드는 것이다.  
중요: 이 프롬프트는 “범용 조사 요청”이 아니라, **QCViz-MCP 런타임 제약과 JSON 스키마를 미리 주입한 컨텍스트 내장형 작업지시문**이다.

---

```markdown
# [QCViz-MCP TASK] functional_recommendations.json 엔터프라이즈급 전수조사 및 고도화 제안 생성

## 역할
당신은 다음 세 역할을 동시에 수행하는 시니어 전문가다.

1. 계산화학 방법론 리서치 리드
2. 프로덕션 룩업 데이터 설계자
3. 보수적 릴리즈 엔지니어

당신의 목표는 “좋은 설명”이 아니라, **제품에 바로 투입 가능한 룩업 업그레이드 초안**을 만드는 것이다.
단순 요약, 인상비평, 논문 나열은 금지한다.
반드시 실제 런타임 호환성과 JSON 소비 구조를 고려해 판단하라.

## 프로젝트 컨텍스트

- 프로젝트명: `QCViz-MCP`
- 작업 기준 루트(absolute): `D:\20260305_양자화학시각화MCP서버구축\version03`
- 작업 기준 루트(relative): repo root = `version03`
- source of truth:
  - `src/qcviz_mcp/advisor/reference_data/functional_recommendations.json`

중요:

- 이 프로젝트 주변에는 다른 `src/qcviz_mcp` 트리가 존재할 수 있다.
- 반드시 **`version03` 루트만 기준으로 조사**하라.
- 로컬 Python/import/pytest를 사용할 경우:
  - `cwd`를 `version03`로 고정
  - `PYTHONPATH=src`로 고정
- 다른 sibling 경로를 근거로 섞어 쓰지 마라.

## 이 JSON이 실제로 사용되는 런타임 소비자

다음 파일들을 반드시 먼저 읽고, JSON이 실제로 어떻게 쓰이는지 확인하라.

- `src/qcviz_mcp/advisor/reference_data/__init__.py`
- `src/qcviz_mcp/advisor/preset_recommender.py`
- `src/qcviz_mcp/advisor/confidence_scorer.py`
- `src/qcviz_mcp/web/advisor_flow.py`
- `src/qcviz_mcp/tools/advisor_tools.py`
- `src/qcviz_mcp/compute/pyscf_runner.py`
- `src/qcviz_mcp/advisor/reference_data/dft_accuracy_table.json`

또한 가능하면 다음 테스트를 읽어 현재 기대 동작을 파악하라.

- `tests/test_advisor_new.py`
- `tests/test_advisor_preset.py`
- `tests/test_advisor_scorer.py`
- `tests/test_advisor_script.py`
- `tests/test_advisor_drafter.py`
- `tests/test_advisor_flow.py`

핵심 인식:

- 이 JSON은 참고용 문서가 아니다.
- advisor preset 추천, confidence scoring, web advisor flow, tool 호출에 실제로 사용된다.
- 따라서 default 변경은 곧 실제 계산 기본값과 신뢰도 로직 변경을 의미한다.

## 핵심 목표

최신 peer-reviewed 저널, 공식 소프트웨어 문서, 그리고 실무 커뮤니티 신호를 교차검증하여
`functional_recommendations.json`의 **엔터프라이즈급 업그레이드 제안안**을 작성하라.

다만 다음 원칙을 지켜라.

- 기본 추천(default)은 보수적으로 유지하라.
- 현재 PySCF/QCViz 런타임에서 바로 못 쓰는 functional은 default로 승격하지 마라.
- 그런 후보는 `alternatives` 또는 `future_candidate` 성격으로만 기록하라.
- “문헌상 더 좋다”와 “현재 스택에서 실사용 가능하다”를 반드시 분리해서 판단하라.

## 절대 제약

### 1. Top-level key 고정

최종 제안 JSON의 top-level key는 아래 9개만 유지하라.

- `_metadata`
- `organic_small`
- `organic_large`
- `3d_tm`
- `heavy_tm`
- `lanthanide`
- `radical`
- `charged_organic`
- `main_group_metal`

새로운 top-level system type를 추가하지 마라.

### 2. 각 system 아래 purpose key 고정

각 system 아래에는 반드시 다음 key가 있어야 한다.

- `default`
- `geometry_opt`
- `single_point`
- `bonding_analysis`
- `reaction_energy`
- `spectroscopy`
- `esp_mapping`
- top-level `alternatives`

즉, top-level system만 유지하면 되는 것이 아니다.
각 system 아래의 purpose coverage까지 완전해야 한다.

### 3. 각 purpose entry의 필수 필드 고정

각 purpose entry에는 최소한 아래 필드가 반드시 있어야 한다.

- `functional`
- `basis`
- `dispersion`
- `rationale`
- `references`
- `confidence`
- `alternatives`

추가 필드는 허용한다.
하지만 다음 조건을 반드시 만족해야 한다.

- 기존 필드 rename 금지
- 기존 필드 삭제 금지
- 기존 소비 코드가 무시 가능해야 함
- backward-compatible한 추가 필드만 허용

### 4. 런타임 안전성 제약

현재 제품은 advisor lookup을 실제 preset/default 계산 설정에 사용한다.
따라서 다음 규칙을 반드시 지켜라.

- PySCF/QCViz 런타임에서 바로 못 쓰는 functional은 default로 승격 금지
- 새 default functional 제안 시 반드시 아래를 검토하라:
  - `preset_recommender.py`의 정규화/매핑 경로
  - `confidence_scorer.py`의 normalized functional 비교 경로
  - `web/advisor_flow.py`의 runner method 변환 경로
  - `compute/pyscf_runner.py`의 method alias / xc 지원 경로
  - `dft_accuracy_table.json`의 benchmark 키 존재 여부

### 5. fabricated citation 금지

- fabricated DOI 금지
- fabricated URL 금지
- DOI/URL 없는 주장 금지
- 단일 논문 1편 과적합 금지

## 반드시 재검토해야 할 functional class

최소한 아래 계열에 대해 문헌성과 런타임 실사용 가능성을 함께 검토하라.

- `B3LYP-D3(BJ)`
- `PBE0-D3(BJ)`
- `TPSSh-D3(BJ)`
- `UM06-2X-D3(0)`
- `wB97X-D`
- `r2SCAN-3c`
- `PWPB95-D3(BJ)`

판단 원칙:

- `r2SCAN-3c`는 composite method라는 점을 고려하라.
- double-hybrid 계열은 문헌상 우수해도 현재 실행 경로가 없는지 따로 판단하라.
- VV10/NLC 의존 계열은 “정확도 우수”와 “현재 스택 통합 여부”를 분리해서 다뤄라.

## 조사 방법론

반드시 실제 웹 조사를 수행하라.
추정만 하지 마라.

조사 실행 시 반드시 아래를 따른다.

- 조사 실행일을 `YYYY-MM-DD` 형식의 절대 날짜로 기재
- 조사 대상 기간도 절대 날짜 또는 연도 범위로 명시
- `latest`, `recent`, `today` 같은 상대 표현만 쓰지 말 것

### 근거 우선순위

1. 1차 근거
   - peer-reviewed benchmark papers
   - peer-reviewed reviews
   - perspective / best-practice articles
   - method validation papers

2. 2차 근거
   - 공식 소프트웨어 문서
   - 공식 개발자 문서
   - libxc / PySCF 공식 자료

3. 3차 근거
   - GitHub issue/discussion
   - Matter Modeling Stack Exchange
   - 연구 커뮤니티 / 포럼

커뮤니티 자료는 다음 용도로만 사용하라.

- adoption signal
- convergence/failure mode
- implementation caveat
- practical workaround

커뮤니티 자료만으로 기본 추천(default)을 바꾸지 마라.

## 조사 범위

반드시 아래를 전수 검토하라.

- 유기 소분자 DFT best practice
- 유기 대분자/대형 시스템의 cost-accuracy tradeoff
- 3d transition metal의 spin-state, geometry, energetics 민감도
- 4d/5d heavy TM의 relativistic/ECP 실무 권고
- lanthanide / 4f 계열의 multireference caution
- radical / open-shell 시스템의 spin contamination과 functional 선택
- charged organic 시스템의 diffuse basis, self-interaction, long-range 문제
- composite methods (`r2SCAN-3c` 등)의 실무 위치
- hybrid / GGA / meta-GGA / double-hybrid 간 현실적 tradeoff
- 목적별 권고:
  - geometry optimization
  - single-point energy
  - bonding analysis
  - reaction energy
  - spectroscopy
  - ESP mapping

## 판단 프레임

각 추천은 최소한 아래 프레임으로 판단하라.

- benchmark quality
- breadth of validation
- runtime support
- computational cost
- robustness / convergence behavior
- known failure modes
- open-shell risk
- relativistic risk
- multireference risk
- community adoption signal
- backward compatibility with current runtime

## 권장 추가 필드

기존 소비 코드를 깨지 않는 선에서 아래 추가 필드를 활용해도 된다.

- `applicability`
- `avoid_when`
- `cost_tier`
- `evidence_strength`
- `community_consensus`
- `implementation_notes`
- `basis_upgrade_path`
- `validation_notes`
- `last_reviewed`
- `source_bucket`
- `future_candidate`
- `pyscf_supported`

하지만 이 필드들이 기존 필수 필드를 대체해서는 안 된다.

## 필수 조사 절차

아래 순서로 작업하라.

### Phase 1. 코드베이스 grounding

먼저 반드시 로컬 파일을 읽고 현재 구조를 파악하라.

1. `functional_recommendations.json` 현재 구조 확인
2. runtime 소비자 코드 확인
3. `dft_accuracy_table.json`의 현재 functional 키 확인
4. 테스트가 무엇을 기대하는지 확인
5. 현재 JSON이 실제로 누락한 purpose key가 있는지 확인

이 단계 없이 곧바로 제안 JSON을 만들지 마라.

### Phase 2. 웹 기반 문헌 조사

최신 문헌, 공식 문서, 커뮤니티를 조사하라.
단, 근거 가중치는 문헌 > 공식문서 > 커뮤니티 순이다.

### Phase 3. 합성(synthesis)

조사 결과를 바탕으로 다음을 판단하라.

- baseline 유지 항목
- 강화해야 할 rationale
- confidence 조정 여부
- 추가 가능한 alternatives
- future candidate로만 남겨야 할 항목
- 런타임 blocker 여부

### Phase 4. 최종 제안안 구성

아래 산출물을 최종 응답으로 제출하라.

## 최종 출력 형식

최종 답변은 반드시 아래 7개 섹션을 이 순서대로 포함하라.

1. `Executive Summary`
2. `Research Log`
3. `Source Inventory Table`
4. `Proposed Upgraded JSON`
5. `Delta Report`
6. `Compatibility / Gap Report`
7. `Validation Checklist`

### 1. Executive Summary

반드시 포함:

- 무엇을 바꿨는지
- 어떤 기본 추천은 유지했고 어떤 것은 보류했는지
- 가장 중요한 리스크 3개

### 2. Research Log

반드시 포함:

- 조사 실행일
- 조사한 기간 범위
- 사용한 검색 전략
- source inclusion/exclusion 기준

### 3. Source Inventory Table

각 source에 대해 표로 정리:

- type
- title
- year
- DOI or URL
- accessed date
- trust level
- how it influenced the lookup

### 4. Proposed Upgraded JSON

반드시 parse 가능한 완전한 JSON 전문을 fenced `json` 블록으로 제시하라.

이 JSON은 다음을 만족해야 한다.

- 9개 top-level key 유지
- 각 system 아래 7개 purpose key + top-level `alternatives` 유지
- 각 purpose entry에 필수 필드 유지
- backward-compatible 추가 필드만 사용

### 5. Delta Report

현재 source-of-truth 대비 다음을 정리하라.

- changed defaults
- unchanged defaults
- changed basis recommendations
- added purpose coverage
- added alternatives
- added warnings/notes
- confidence 변화 이유

### 6. Compatibility / Gap Report

반드시 아래를 포함하라.

- 현재 코드와 완전 호환 여부
- default functional blocker 여부
- `dft_accuracy_table.json` 보강 필요 여부
- `preset_recommender.py` / `xc_map` 영향 여부
- `confidence_scorer.py` 영향 여부
- `advisor_flow.py` / runner path 영향 여부
- 코드 변경 없이 바로 넣어도 되는지
- future candidate로만 남겨야 할 항목

### 7. Validation Checklist

최소 아래 항목을 체크리스트 형태로 제출하라.

- 9개 top-level key 유지 여부
- 각 system의 7개 purpose key 유지 여부
- 필수 필드 유지 여부
- uncited claim 존재 여부
- fabricated DOI/URL 여부
- PySCF unsupported default 여부
- community-only recommendation 여부
- parse 가능한 JSON 여부

## 실패 조건

다음 중 하나라도 해당하면 실패로 간주한다.

- JSON schema를 깨뜨림
- 현재 코드가 읽지 못하는 구조를 제안함
- top-level key를 임의 추가/삭제함
- purpose key를 누락함
- default functional을 unsupported 상태로 올림
- 최신성 주장을 하면서 절대 날짜/출처가 없음
- DOI/URL 없는 핵심 주장
- fabricated citation
- community evidence만으로 권고를 바꿈
- runtime 영향도 분석을 누락함

## 작업 시 유의사항

- baseline을 모른 채 임의로 새 JSON을 창작하지 마라.
- 반드시 실제 source-of-truth 파일을 먼저 읽어라.
- 실행 가능성과 이론적 우수성을 분리해라.
- default는 보수적으로, alternatives는 풍부하게, future candidate는 명확하게 구분하라.
- 불확실하면 과감히 default 교체를 보류하라.
- 문헌이 엇갈리면 confidence를 낮추고 caution을 추가하라.

## 최종 지시

지금부터 작업을 시작하라.

반드시:

- 로컬 코드 조사 → 웹 조사 → 합성 → JSON 제안 → 호환성 점검 순으로 진행하라.
- 제품에 바로 넣을 수 있는 수준의 보수적 제안안을 작성하라.
- 결과는 위 7개 섹션 형식으로만 제출하라.
```

---

## 사용 메모

- 이 문서는 “다른 LLM에게 그대로 붙여 넣는 마스터 프롬프트”다.
- 상대 LLM이 로컬 파일 접근이 불가능하면, source-of-truth JSON과 소비자 코드 파일들을 함께 제공하는 것이 가장 좋다.
- 상대 LLM이 browsing을 지원하지 않으면, 이 프롬프트의 핵심 품질 기준 중 하나를 충족하지 못하므로 결과 신뢰도를 낮게 봐야 한다.
