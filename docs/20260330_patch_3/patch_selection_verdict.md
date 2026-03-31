# Patch Selection Verdict

Date: 2026-03-30

## Verdict Summary

최종 선정안은 **`patch_2.md`를 기본 채택본**, **`patch_1.md`를 보조 참고본**으로 두는 것이다.

채택 이유는 다음과 같다.

1. `patch_2.md`가 현재 `version03` 코드와 더 잘 맞는 runtime 안전성 기준을 제시한다.
2. `wB97X-D`, `r2SCAN-3c`, `PWPB95-D3(BJ)`를 production-safe default와 future candidate로 더 명확히 분리한다.
3. `Compatibility / Gap Report`와 `Validation Checklist`가 더 배포 판단용 문서에 가깝다.

단, 두 문서 모두 현재 저장소 상태와 시점 차이가 있다.

- 현재 source-of-truth JSON은 이미 `v1.2.0`이며, 8개 system type에 대해 7개 purpose key가 모두 채워져 있다.
- 따라서 두 문서가 공통으로 언급하는 “purpose key 대량 누락”은 **현재 repo의 현상 진단이 아니라 baseline 시점 설명**으로만 사용해야 한다.

현재 코드 기준 핵심 판정:

- `wB97X-D`: 로컬 코드에는 정규화/runner 경로가 존재하지만, upstream PySCF issue `#2069` caveat를 감안하면 default 승격 금지라는 `patch_2`의 보수적 방향이 더 안전하다.
- `wB97X-V`: 로컬 코드에 부분 plumbing이 존재한다. 그래도 현재 lookup default가 아니므로 future candidate 취급이 맞다.
- `r2SCAN-3c`: plain `r2SCAN` alias와 달리 composite `3c`는 현재 스택에서 production-safe keyword가 아니다. `patch_2`의 설명이 더 정확하다.
- `PWPB95-D3(BJ)`: 현재 accuracy table row도 없고 explicit runner mapping도 없다. future candidate만 허용해야 한다.

## Side-by-Side Comparison Matrix

| 비교 항목 | `patch_1.md` | `patch_2.md` | 현재 `version03` 코드 기준 판정 |
| --- | --- | --- | --- |
| purpose coverage completeness | 누락 purpose 문제를 잘 지적함 | 누락 수량과 영향도를 더 명확히 적음 | 두 문서 모두 baseline 설명으로는 유효하지만, 현재 repo 상태에는 이미 반영 완료됨 |
| default 보수성 | 전반적으로 보수적 | 더 강하게 보수적 | `patch_2` 우세 |
| `wB97X-D` 판단 | 사용 가능 대안처럼 읽힐 여지가 있음 | PySCF issue `#2069`를 전면에 두고 caveat를 강조 | `patch_2` 우세 |
| `wB97X-V` 판단 | 중심 항목이 아님 | future candidate로 올리되 `xc_map` 영향 언급 | `patch_2` 우세 |
| `r2SCAN-3c` 판단 | 비-native라는 설명은 있음 | composite limitation을 더 명확히 구분 | `patch_2` 우세 |
| `PWPB95-D3(BJ)` 판단 | 3d TM future candidate로 다룸 | future candidate 성격은 유지하되 checklist/compat와 연결 | 동률, 단 배포용 문맥은 `patch_2` 우세 |
| PySCF support claim accuracy | 일부 항목에서 더 공격적 | 더 보수적이고 배포 친화적 | `patch_2` 우세 |
| validation checklist 품질 | 있음 | 더 구체적이고 제품 배포 판단용 | `patch_2` 우세 |
| current code alignment | 문헌 중심 서술이 강함 | runtime impact 서술이 더 강함 | `patch_2` 우세 |

### Current code evidence used for the verdict

- `src/qcviz_mcp/advisor/preset_recommender.py`
  - `wB97X-D`, `wB97X-V`, `r2SCAN`, `M06-2X` 정규화 경로 존재
  - `PWPB95`는 explicit map 없음
- `src/qcviz_mcp/web/advisor_flow.py`
  - `wb97x-d`, `wb97x-v`, `r2scan`, `m062x` runner method 변환 존재
  - `pwpb95` 변환 없음
- `src/qcviz_mcp/compute/pyscf_runner.py`
  - `wb97x-d`, `wb97x-v`, `r2scan`, `pw6b95`, `m062x` alias 존재
  - `pwpb95` alias 없음
- `src/qcviz_mcp/advisor/reference_data/dft_accuracy_table.json`
  - `WB97X`, `R2SCAN`, `M062X`는 존재
  - `R2SCAN-3C`, `PWPB95`는 없음
- `src/qcviz_mcp/advisor/reference_data/functional_recommendations.json`
  - 현재 metadata version은 `1.2.0`
  - 8개 system type 모두 purpose coverage complete

## Adopt / Reject / Cherry-pick Table

| 분류 | 항목 | 출처 | 최종 판정 | 이유 |
| --- | --- | --- | --- | --- |
| Adopt | `patch_2`를 주 문서로 사용 | `patch_2.md` | 채택 | runtime safety, blocker analysis, validation checklist가 더 강함 |
| Adopt | `wB97X-D`는 default 승격 금지 | `patch_2.md` | 채택 | 로컬 plumbing은 존재하지만 upstream integration caveat가 남아 있음 |
| Adopt | `r2SCAN-3c`는 plain keyword가 아닌 composite limitation으로 처리 | `patch_2.md` | 채택 | 현재 accuracy table / runner / product path와 맞음 |
| Adopt | `PWPB95-D3(BJ)`는 future candidate only | `patch_1.md`, `patch_2.md` | 채택 | accuracy table row와 explicit runtime mapping이 없음 |
| Cherry-pick | purpose coverage 누락이 fallback/strict lookup 문제를 만든다는 설명 | `patch_1.md` | 조건부 흡수 | baseline 설명으로는 유효하나, 현재 repo 상태 설명으로는 쓰지 않음 |
| Cherry-pick | BH9 / Tikhonov / Ln 관련 문헌 보강 | `patch_1.md` | 조건부 흡수 | DOI와 현재 서술 맥락을 다시 확인한 경우만 흡수 |
| Cherry-pick | 3d TM spin-state용 `PWPB95-D3(BJ)` 보수적 서술 | `patch_1.md` | 흡수 | future candidate 문구로는 안전함 |
| Reject | `wB97X-D`를 사실상 사용 가능한 안전 대안처럼 읽히는 서술 | `patch_1.md` | 기각 | 현재 QCViz 배포 기준으로는 너무 공격적임 |
| Reject | 현재 저장소에 purpose key가 여전히 누락돼 있다는 현재형 진술 | `patch_1.md`, `patch_2.md` | 기각 | 현재 repo의 source-of-truth는 이미 `v1.2.0`으로 보강 완료 |
| Reject | `PWPB95-D3(BJ)`를 runtime-near하게 읽힐 수 있는 표현 | `patch_1.md` | 기각 | explicit runner path와 accuracy support가 없음 |

## Residual Risks

1. `patch_2`도 현재 repo 상태를 그대로 반영한 문서는 아니다. 특히 purpose coverage 누락 관련 서술은 현재 상태와 어긋난다.
2. 로컬 코드에는 `wB97X-D` / `wB97X-V` plumbing이 존재하지만, 이것이 곧 production-safe default promotion을 뜻하지는 않는다.
3. `PWPB95-D3(BJ)`는 문헌상 강점이 있어도 현재 `version03` 런타임 기준으로는 future candidate 이상으로 올리면 안 된다.
4. `r2SCAN` alias 존재와 `r2SCAN-3c` composite 지원은 전혀 다른 문제다. 이 둘을 섞어서 읽지 않도록 문구를 분리해야 한다.
5. 앞으로 이 선정 결과를 실제 문서나 프롬프트에 반영할 때는, “현재 repo 상태”와 “baseline 시점 분석”을 반드시 구분해서 써야 한다.

## Final Selection Rule

후속 작업자가 이 두 문서를 사용할 때의 고정 규칙:

- 기준 문서는 `patch_2.md`
- 보조 문서는 `patch_1.md`
- `patch_1.md`에서 문장을 가져올 경우:
  - DOI 재확인
  - 현재 `version03` 코드 영향 재확인
  - runtime-safe wording으로 재작성
- 아래 항목은 무조건 future candidate 또는 caution으로만 유지:
  - `wB97X-D`
  - `wB97X-V`
  - `r2SCAN-3c`
  - `PWPB95-D3(BJ)`
