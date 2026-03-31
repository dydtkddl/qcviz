# Research Prompt: Resolve QCViz Structure Recognition and Clarification Failures

## 역할

당신은 chemistry-aware NLP, molecule resolution pipelines, scientific UX, resolver-backed disambiguation, PubChem/MolChat integration, LLM orchestration 설계에 강한 시니어 엔지니어이자 연구형 소프트웨어 아키텍트다.

지금부터 첨부 문서:

- `docs/20260321_structure_clarification_issue_dossier.md`

를 반드시 먼저 읽고, 그 문서에서 정리한 현재 QCViz v3의 분자 인식 및 clarification 문제를 해결하기 위한 **최신 best practice와 구현 가능한 해결안**을 전수조사하라.

이 작업의 핵심은 단순 아이디어 브레인스토밍이 아니다.  
목표는 다음과 같다.

> 현재 프로젝트의 `text-based molecule recognition -> structure resolution -> clarification candidate generation` 파이프라인을  
> generic fallback 중심 구조에서  
> resolver-grounded, chemistry-aware, minimal-clarification 구조로 재설계하는 것.

---

## 절대 조건

### 1. 이미지 기반 fallback은 제외

이번 문제 해결에서는 다음을 고려하지 마라.

- image attachment fallback
- screenshot-based fallback
- OCR
- image-to-structure rescue
- user가 구조 그림을 올렸을 때의 예외 경로

이번 문제는 **text molecule input**에 대한 해결책만 다뤄야 한다.

### 2. 분자 truth source는 LLM이 아니다

LLM은 molecule candidate suggestion을 보조할 수는 있지만, 최종 truth source가 되면 안 된다.  
구조 확인과 후보 검증은 다음처럼 resolver/backend 중심이어야 한다.

- MolChat
- PubChem
- synonym/property lookup
- charge/formal-charge validation
- optional local chemistry rule engine

### 3. generic fallback 추천은 문제로 간주

다음 같은 구조는 “좋은 fallback”이 아니다.

- water
- methane
- ethanol
- methanol
- benzene

사용자가 `Biphenyl`을 입력했는데 이런 후보가 뜨는 건 해결해야 할 문제다.

### 4. raw user input preservation이 최우선

사용자가 명확한 molecule-like 문자열을 넣었으면, system은 우선 그 문자열을 가능한 한 그대로 candidate chain에 유지해야 한다.

---

## 현재 문제 상황

프로젝트는 다음 상황에 있다.

- 사용자가 explicit molecule name을 입력해도 때때로 structure를 바로 인식하지 못한다.
- clarification이 뜨면 후보 목록이 generic hardcoded molecules나 vague Gemini suggestions로 채워질 수 있다.
- `Biphenyl`, `benzoic acid`, `fluorobenzene` 같은 영문 multiword/aromatic 계열에서 UX 품질이 특히 중요하다.
- 현재 ambiguity detection은 token count, regex, molecule-like text 판정에 크게 의존한다.
- resolver-backed candidate probing이 clarification 이전 단계에서 충분히 활용되지 않는다.

자세한 코드/문제 분석은 첨부 문서를 참고하라.

---

## 당신이 해야 할 일

### 1. 최신 해결 방향 전수조사

아래 주제를 중심으로 최근 커뮤니티, 공식 문서, 실전 설계 패턴, 논문/기술블로그/라이브러리 관행을 조사하라.

- chemistry-aware entity recognition for molecule names
- text-to-molecule candidate generation best practices
- synonym-normalization and resolver-first architecture
- multiword molecule handling
- disambiguation UX for chemistry software
- LLM as orchestration layer vs LLM as candidate source
- PubChem/MolChat-like backend probing before clarification
- rule-based + resolver-based + LLM hybrid pipelines

### 2. 문제를 구조적으로 분해

반드시 아래 질문을 각각 독립 항목으로 답하라.

1. 왜 현재 구조가 explicit molecule names를 안정적으로 처리하지 못하는가?
2. 왜 generic fallback suggestions가 UX를 망치는가?
3. `discovery`와 `disambiguation`은 왜 분리해야 하는가?
4. `Biphenyl` 같은 입력은 어떤 단계에서 바로 통과되어야 하는가?
5. `benzoic acid` 같은 multiword molecule과 `EMIM TFSI` 같은 multi-entity query는 어떻게 다르게 처리해야 하는가?
6. resolver-first clarification은 구체적으로 어떤 data flow를 가져야 하는가?
7. LLM은 어떤 단계까지만 써야 하며, 어디서는 쓰면 안 되는가?

### 3. 구현 가능한 설계안 제시

QCViz 코드베이스에 이식 가능한 수준으로 제안하라.  
추상적인 “이렇게 하면 좋다”가 아니라 다음 형태로 정리해야 한다.

- 기능명
- 현재 문제
- 권장 설계
- 입력
- 출력
- 필요한 데이터 구조
- 실패 시 fallback
- 장점
- 리스크
- 구현 난이도
- 우선순위

---

## 반드시 포함해야 할 출력 형식

### A. Executive Summary

짧은 요약 1개.

- 지금 문제의 본질
- 가장 중요한 구조 변경 3개
- 왜 이미지 fallback이 아니라 text resolver pipeline을 고쳐야 하는지

### B. Lookup Table

반드시 Markdown 표로 정리하라.

최소 열:

- Problem Area
- Current Behavior
- Why It Fails
- Recommended Fix
- Data Source
- LLM Role
- Resolver Role
- Priority
- Implementation Risk

### C. Target Architecture

`raw input -> candidate extraction -> resolver probing -> scoring -> clarification -> execution`

형태의 파이프라인을 서술하고, 각 단계 입력/출력을 적어라.

### D. Clarification Redesign Table

clarification을 반드시 두 종류로 나눠서 설명하라.

1. `discovery clarification`
2. `disambiguation clarification`

각각에 대해:

- when to trigger
- candidate source
- UI shape
- what not to do

### E. Candidate Ranking Strategy

resolver-backed molecule 후보를 어떻게 정렬할지 제안하라.

반드시 아래 항목 포함:

- exact raw match
- normalized exact match
- alias hit
- synonym hit
- charge consistency
- known multiword molecule support
- resolver success
- LLM confidence는 어디에 넣고 어디에 넣지 말아야 하는지

### F. QCViz-Specific Implementation Plan

다음 파일에 구체적으로 어디를 어떻게 바꿀지 정리하라.

- `src/qcviz_mcp/llm/normalizer.py`
- `src/qcviz_mcp/web/routes/chat.py`
- `src/qcviz_mcp/llm/agent.py`
- `src/qcviz_mcp/services/structure_resolver.py`
- `src/qcviz_mcp/services/molchat_client.py`
- `src/qcviz_mcp/services/pubchem_client.py`

각 파일별로:

- keep
- change
- remove
- add

를 명시하라.

### G. Anti-Patterns

절대 하지 말아야 할 설계를 최소 10개 적어라.

반드시 포함할 것:

- explicit molecule names를 generic suggestions로 덮어쓰기
- resolver probing 없이 LLM suggestion 먼저 띄우기
- raw input을 너무 이른 단계에서 버리기
- whitespace token 수만 보고 multi-molecule로 분류하기
- image fallback으로 이번 문제를 해결하려 하기

### H. Test Matrix

반드시 테스트 케이스 표를 만들어라.

최소 케이스:

- `Biphenyl`
- `Biphenyl HOMO`
- `benzoic acid optimize`
- `fluorobenzene esp`
- `ethyl methyl carbonate`
- `EMIM TFSI`
- `TFSI- energy`
- `대표적인 방향족 분자`
- `5원자 분자`
- `benzene and toluene`

각 케이스마다:

- expected parse
- expected candidate source
- clarification needed or not
- expected final behavior

### I. Final Recommendation

맨 마지막에 반드시 아래를 명확히 정리하라.

1. 이번 문제를 푸는 가장 좋은 아키텍처 1개
2. 현실적으로 가장 빨리 적용 가능한 아키텍처 1개
3. QCViz에 가장 적합한 절충안 1개

---

## 조사 원칙

- 최신 자료를 우선하라.
- chemistry software, molecular informatics, scientific search UX 관점을 같이 보라.
- 추상적인 AI product advice보다 실제 scientific software 설계 패턴을 우선하라.
- 가능하면 source attribution을 포함하라.
- resolver-backed architecture를 선호하라.

---

## 금지사항

다음을 하지 마라.

- 이미지 첨부 fallback 제안
- “LLM이 알아서 molecule을 맞히면 된다” 식 제안
- generic molecule fallback을 정당화
- vague한 UX 원론만 말하고 구현 방안을 안 내는 것
- QCViz 파일 단위 이식 계획 없이 끝내는 것

---

## 최종 목표

당신의 답변은 단순 리서치 메모가 아니라,  
QCViz에서 실제로 바로 구현할 수 있는 수준의 설계서여야 한다.

최종 목표 문장:

> 사용자가 explicit molecule name을 입력했을 때는 가능한 한 clarification 없이 바로 resolver로 보내고,  
> clarification이 꼭 필요한 경우에도 generic 추천이 아니라 resolver-grounded 후보를 제시하며,  
> LLM은 molecule truth source가 아니라 orchestration layer로만 동작하도록 QCViz structure handling pipeline을 재설계하라.

