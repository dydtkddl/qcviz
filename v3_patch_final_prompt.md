# QCViz Version03 패치 작업지시서

## 너의 역할

너는 15년차 Principal Full-Stack Engineer & Staff SRE다.
아래 [패치 룩업테이블]에 명시된 모든 변경사항을 version03 코드베이스에 적용하라.
이 문서 하단에 [현재 코드 전문]이 첨부되어 있다. 그 코드를 읽고 수정하라.

## 출력 규칙

1. 신규 파일 → 전체 코드 출력
2. 수정 파일 → 전체 교체본 출력 (diff가 아님, 파일 전체를 출력)
3. 모든 수정에 `# FIX(이슈ID): 설명` 주석 필수
4. 삭제 대상 코드는 실제로 삭제. 주석으로 남기지 마라
5. 파이썬은 type hints 필수, async/await 적절히 사용
6. 에러 메시지는 한국어 + 영어 이중 언어
7. import 순서: stdlib → 서드파티 → 로컬
8. 구현 순서대로 파일을 하나씩 출력하라 (아래 순서 참조)
9. 기존 모듈의 외부 인터페이스(함수명, 클래스명, DOM ID)는 최대한 유지하여 하위 호환 보장

## 프로젝트 구조

```
src/qcviz_mcp/
├── __init__.py, app.py, config.py, errors.py, mcp_server.py
├── security.py, log_config.py, observability.py
├── llm/          ← Gemini 탑재 대상
├── compute/      ← PySCF (유지, 수정)
├── web/
│   ├── app.py, advisor_flow.py
│   ├── routes/   ← compute.py, chat.py
│   ├── static/   ← JS, CSS
│   └── templates/ ← HTML
├── services/     ← 신규 생성 (MolChat, PubChem, resolver 등)
├── tools/, backends/, analysis/, advisor/
```

## 핵심 변경 요약

version02는 regex 하드코딩으로 자연어를 파싱하고, 존재하지 않는 가짜 resolver를 호출하고 있었다.
version03에서는:

- **Gemini API function calling**으로 자연어 파싱을 대체
- **MolChat API** (`http://psid.aizen.co.kr/molchat`)에서 구조 데이터(CID, SMILES, 3D SDF)를 가져옴
- **PubChem PUG-REST**를 폴백으로 사용
- **이온쌍**(TFSI- EMIM+ 등)은 별칭 사전 + Gemini 분리 + 개별 resolve + SDF 합치기로 처리
- **PySCF 계산은 유지** (MolChat에 없는 qcviz만의 차별점)
- 프론트엔드 버그 수정 (재귀, XSS, 레이스 컨디션, 레이아웃)

## MolChat API (실제 테스트 완료, 2026-03-10 확인)

Base URL: `http://psid.aizen.co.kr/molchat`

### 동작 확인된 엔드포인트

| 엔드포인트                                                                     | 응답 예시                                                                               |
| ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------- |
| `GET /api/v1/health/live`                                                      | `{"status":"alive"}`                                                                    |
| `GET /api/v1/health/ready`                                                     | `{"status":"ready"}`                                                                    |
| `GET /api/v1/molecules/resolve?names=aspirin`                                  | `{"resolved":[{"name":"aspirin","cid":2244}],"total":1}`                                |
| `GET /api/v1/molecules/resolve?names=water,ethanol,benzene`                    | 3개 전부 CID 반환                                                                       |
| `GET /api/v1/molecules/resolve?names=EMIM`                                     | `{"resolved":[{"name":"EMIM","cid":174076}],"total":1}`                                 |
| `GET /api/v1/molecules/resolve?names=caffeine,glucose,methane,propane,acetone` | 5개 전부 CID 반환                                                                       |
| `GET /api/v1/molecules/card?q=aspirin`                                         | `{cid:2244, canonical_smiles:"CC(=O)OC1=CC=CC=C1C(=O)O", molecular_weight:180.16, ...}` |
| `GET /api/v1/molecules/card?q=water`                                           | `{cid:962, canonical_smiles:"O", molecular_weight:18.015, ...}`                         |
| `GET /api/v1/molecules/card?q=caffeine`                                        | `{cid:2519, canonical_smiles:"CN1C=NC2=C1C(=O)N(C(=O)N2C)C", ...}`                      |
| `GET /api/v1/molecules/generate-3d/sdf?smiles=O`                               | RDKit 3D SDF V2000 (3 atoms)                                                            |
| `GET /api/v1/molecules/generate-3d/sdf?smiles=CCO`                             | 에탄올 3D SDF (9 atoms)                                                                 |
| `GET /api/v1/molecules/generate-3d/sdf?smiles=CCO&optimize_xtb=true`           | xTB 최적화 SDF                                                                          |
| `GET /api/v1/molecules/generate-3d/sdf?smiles=c1ccccc1`                        | 벤젠 3D SDF (12 atoms)                                                                  |

### 안 되는 것

| 엔드포인트                        | 결과         | 대응                                                    |
| --------------------------------- | ------------ | ------------------------------------------------------- |
| `resolve?names=아스피린` (한국어) | `[]` 빈 배열 | → 로컬 ko_aliases.py에서 한국어→영어 변환 후 호출       |
| `card?q=EMIM`                     | 실패         | → resolve로 CID 획득 → PubChem에서 SMILES → generate-3d |
| `search?q=...`                    | 인증 필요    | → 사용하지 않음. resolve+card로 대체                    |

### MolChat card 응답 주요 필드

```json
{
  "cid": 2244,
  "name": "2-acetyloxybenzoic acid",
  "canonical_smiles": "CC(=O)OC1=CC=CC=C1C(=O)O",
  "molecular_formula": "C9H8O4",
  "molecular_weight": 180.16,
  "inchi": "InChI=1S/C9H8O4/...",
  "inchikey": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
  "drug_likeness": [...],
  "ghs_safety": {...},
  "similar_molecules": [...],
  "ai_summary": "..."
}
```

## PubChem PUG-REST (폴백용)

| 용도             | URL                                                                                          |
| ---------------- | -------------------------------------------------------------------------------------------- |
| 이름→CID         | `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{name}/cids/JSON`                   |
| CID→SMILES       | `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/property/CanonicalSMILES/JSON` |
| CID→3D SDF       | `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/SDF?record_type=3d`            |
| 이름→3D SDF 직접 | `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{name}/SDF?record_type=3d`          |
| 제한             | 5 req/s, 우리 코드에서 4 req/s로 제한                                                        |

---

## 파일별 작업 룩업테이블

### 신규 생성 (8개) — `src/qcviz_mcp/services/` 디렉토리 신규

| #   | 파일경로                                       | 역할                             | 핵심 구현 내용                                                                                                                                                                                                                                                                                                                                                                      |
| --- | ---------------------------------------------- | -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| N0  | `src/qcviz_mcp/services/__init__.py`           | 패키지 init                      | 빈 파일 또는 public import                                                                                                                                                                                                                                                                                                                                                          |
| N1  | `src/qcviz_mcp/services/ko_aliases.py`         | 한국어→영어 분자명 사전          | `KO_TO_EN: dict` 30개 매핑. `translate(text: str) -> str` 함수: 입력에서 한국어 분자명을 찾아 영어로 변환. 조사(은/는/이/가/을/를/의/에/에서/로/부터/에 대해) 제거. Gemini 실패 시 폴백용                                                                                                                                                                                           |
| N2  | `src/qcviz_mcp/services/sdf_converter.py`      | SDF→XYZ 변환기                   | `sdf_to_xyz(sdf_text: str) -> str`: V2000 MOL 블록 파싱, 원자 기호+3D 좌표 추출, XYZ 포맷 문자열 반환. `merge_sdfs(sdf_list: list[str], offset: float = 5.0) -> str`: 여러 SDF를 좌표 오프셋하여 합친 후 XYZ 반환. `sdf_to_atoms_list(sdf_text: str) -> list[tuple[str, float, float, float]]`: PySCF 입력용                                                                        |
| N3  | `src/qcviz_mcp/services/molchat_client.py`     | MolChat API 클라이언트           | `MolChatClient` 클래스. httpx AsyncClient. `resolve(names: list[str]) -> list[dict]`: `/api/v1/molecules/resolve`. `get_card(query: str) -> dict                                                                                                                                                                                                                                    | None`: `/api/v1/molecules/card`. `generate_3d_sdf(smiles: str, optimize_xtb: bool = False) -> str   | None`: `/api/v1/molecules/generate-3d/sdf`. 환경변수: `MOLCHAT_BASE_URL`, `MOLCHAT_TIMEOUT`. tenacity 재시도 3회, 지수 백오프 |
| N4  | `src/qcviz_mcp/services/pubchem_client.py`     | PubChem PUG-REST 직접 클라이언트 | `PubChemClient` 클래스. httpx AsyncClient. `name_to_cid(name: str) -> int                                                                                                                                                                                                                                                                                                           | None`. `cid_to_smiles(cid: int) -> str                                                              | None`. `cid_to_sdf_3d(cid: int) -> str                                                                                        | None`. `name_to_sdf_3d(name: str) -> str                                                                                                                                                                                                                | None`. 속도제한: `asyncio.sleep(0.25)` 호출 간. 타임아웃 10s |
| N5  | `src/qcviz_mcp/services/ion_pair_handler.py`   | 이온쌍 전용 처리기               | `ION_ALIASES: dict` 27개 (약어→풀네임). `is_ion_pair(structures: list) -> bool`. `resolve_ion_pair(structures: list[dict], molchat: MolChatClient, pubchem: PubChemClient) -> IonPairResult`: 각 이온 개별 resolve → 개별 SDF 생성 → `sdf_converter.merge_sdfs()` → 합산 charge 계산. `IonPairResult` dataclass: `xyz: str, total_charge: int, smiles_list: list[str], source: str` |
| N6  | `src/qcviz_mcp/services/structure_resolver.py` | 통합 구조 해석 파이프라인        | `StructureResolver` 클래스. `resolve(query: str) -> StructureResult`. 파이프라인: (1) ko_aliases로 한국어→영어 (2) MolChat resolve→card→SMILES→generate-3d→SDF (3) 실패시 PubChem 폴백 (4) SDF→XYZ 변환. `StructureResult` dataclass: `xyz: str, smiles: str, cid: int                                                                                                              | None, name: str, source: str, molecular_weight: float                                               | None`                                                                                                                         |
| N7  | `src/qcviz_mcp/services/gemini_agent.py`       | Gemini function calling 에이전트 | `GeminiAgent` 클래스. `google.genai` SDK. tool 스키마 3종 등록. `parse(message: str, history: list                                                                                                                                                                                                                                                                                  | None) -> GeminiResult`. 자동 function calling. `GeminiResult`dataclass:`intent: str, structure: str | None, structures: list[dict]                                                                                                  | None, method: str, basis_set: str, job_type: str, charge: int, multiplicity: int, raw_response: str, model_used: str`. 환경변수: `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_TIMEOUT`, `GEMINI_TEMPERATURE`. 실패 시 None 반환 (폴백은 agent.py에서 처리) |

### 수정 (11개)

| #   | 파일경로                                                                        | 변경 내용                                                                                                                                                                                                                                                                               | 삭제 대상                                                                                                                                       |
| --- | ------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| M1  | `src/qcviz_mcp/llm/agent.py`                                                    | `parse_user_intent()` 또는 동등 함수가 `gemini_agent.parse()` 먼저 호출 → 실패 시 `ko_aliases.translate()` + 기존 키워드 매칭 폴백. 기존 regex 기반 구조 추출 로직 삭제. Gemini 결과를 기존 plan dict 형식으로 변환하는 어댑터 추가                                                     | 하드코딩된 한국어 조사 리스트, regex 기반 `_extract_structure_query` 계열 함수들, 하드코딩된 한국어 별칭 dict. 존재하는 것만 삭제 (없으면 무시) |
| M2  | `src/qcviz_mcp/web/routes/compute.py`                                           | 구조 해석 부분을 `structure_resolver.resolve()` 호출로 교체. 이온쌍 감지 시 `ion_pair_handler` 위임. 가짜 resolver URL 삭제. LRU 캐시 적용 (OrderedDict, 256개). 에러 메시지 이중 언어화. 기존 `_prepare_payload`, `_resolve_structure_payload` 등을 새 resolver 기반으로 재작성        | `STRUCTURE_RESOLVER_URL` (가짜), 중복 파싱 함수, 기존 resolver 로직                                                                             |
| M3  | `src/qcviz_mcp/web/routes/chat.py`                                              | Gemini agent 연동. 채팅 메시지 → `gemini_agent.parse()` → 구조 감지 시 자동 계산 제안. WebSocket 핸들러가 있으면 keepalive(25s ping, 60s timeout) + cleanup 추가                                                                                                                        | —                                                                                                                                               |
| M4  | `src/qcviz_mcp/compute/pyscf_runner.py`                                         | XYZ 문자열을 직접 입력 받는 인터페이스 추가/확인. `+`/`-` 문자 포함 regex 안전화. atoms list `[(symbol, (x,y,z)), ...]` 형태 입력도 지원. progress callback 유지                                                                                                                        | regex에서 `re.error` 유발 가능 패턴                                                                                                             |
| M5  | `src/qcviz_mcp/compute/job_manager.py`                                          | 스레드 안전 확인: RLock 사용. atomic file write (tmp→rename). 상태 업데이트 시 shallow copy 반환                                                                                                                                                                                        | —                                                                                                                                               |
| M6  | `src/qcviz_mcp/config.py`                                                       | 새 환경변수 추가: `GEMINI_API_KEY`, `GEMINI_MODEL`(기본 gemini-2.5-flash), `GEMINI_TIMEOUT`(10), `GEMINI_TEMPERATURE`(0.1), `MOLCHAT_BASE_URL`(http://psid.aizen.co.kr/molchat), `MOLCHAT_TIMEOUT`(15), `PUBCHEM_FALLBACK`(true), `SCF_CACHE_MAX_SIZE`(256), `ION_OFFSET_ANGSTROM`(5.0) | —                                                                                                                                               |
| M7  | `src/qcviz_mcp/web/static/chat.js`                                              | 재귀 방지(depth guard max 3), 상태 머신(idle/sending/awaiting_ack), 재접속(지수 백오프 max 10회), XSS 방지(textContent), aria-live 추가, client ping 20s                                                                                                                                | —                                                                                                                                               |
| M8  | `src/qcviz_mcp/web/static/viewer.js`                                            | CDN 3개 순차 재시도 + 실패 시 유저 메시지, 100ms 디바운스, viewerReady 큐잉(로드 전 update 호출 시), `viz.xyz`/`viz.molecule_xyz`→`viz.xyz_block` 키 매핑                                                                                                                               | —                                                                                                                                               |
| M9  | `src/qcviz_mcp/web/static/results.js`                                           | created_at 기준 안정 정렬, MAX_RETAINED_RESULTS=100 eviction, clampIndex off-by-one 방지, backend 키 매핑(`total_energy`→`energy`, `viz.xyz`→`viz.xyz_block`), 메모리 누수 방지                                                                                                         | —                                                                                                                                               |
| M10 | `src/qcviz_mcp/web/static/app.js`                                               | 히스토리 newest-first 표시, rAF 배치 렌더링(dirty flag), localStorage 쓰기 2초 쓰로틀, 키보드 접근성(resize divider), 이벤트 플로우 루프 방지                                                                                                                                           | —                                                                                                                                               |
| M11 | `src/qcviz_mcp/web/static/style.css` + `src/qcviz_mcp/web/templates/index.html` | CSS: 3-column grid(1.4fr 1fr 0.9fr), fr/minmax(고정px 제거), 반응형(640px/1024px/1600px), 다크모드(prefers-color-scheme), focus outline, reduced-motion. HTML: 3-column DOM 순서, ARIA roles/landmarks, skip-to-content link, resize divider                                            |                                                                                                                                                 |

### requirements.txt 추가 패키지

```
google-genai>=1.0
httpx>=0.27
tenacity>=8.0
```

---

## 환경변수 (v3 추가분)

| 변수명                | 기본값                            | 용도                              |
| --------------------- | --------------------------------- | --------------------------------- |
| `GEMINI_API_KEY`      | (필수, 기본값 없음)               | Gemini API 인증                   |
| `GEMINI_MODEL`        | `gemini-2.5-flash`                | function calling 메인 모델        |
| `GEMINI_TIMEOUT`      | `10`                              | Gemini API 타임아웃(초)           |
| `GEMINI_TEMPERATURE`  | `0.1`                             | 낮을수록 결정적 응답              |
| `MOLCHAT_BASE_URL`    | `http://psid.aizen.co.kr/molchat` | MolChat API 주소                  |
| `MOLCHAT_TIMEOUT`     | `15`                              | MolChat 타임아웃(초)              |
| `PUBCHEM_FALLBACK`    | `true`                            | PubChem 폴백 활성화 여부          |
| `SCF_CACHE_MAX_SIZE`  | `256`                             | PySCF LRU 캐시 상한               |
| `ION_OFFSET_ANGSTROM` | `5.0`                             | 이온쌍 SDF 합칠 때 좌표 오프셋(Å) |

---

## Gemini Function Calling Tool 스키마 (gemini_agent.py에 포함)

```json
[
  {
    "name": "run_calculation",
    "description": "양자화학 계산을 실행한다. 단일 분자 또는 이온쌍을 받아 PySCF로 계산한다.",
    "parameters": {
      "type": "object",
      "properties": {
        "structure": {
          "type": "string",
          "description": "단일 분자명/화학식. 예: water, H2O, aspirin, benzene"
        },
        "structures": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "name": {
                "type": "string",
                "description": "이온/분자의 PubChem 검색 가능한 영문 화학명"
              },
              "charge": {
                "type": "integer",
                "description": "이온 전하. 예: +1, -1"
              }
            },
            "required": ["name"]
          },
          "description": "이온쌍/다중 분자. 약어(TFSI, EMIM 등)가 아닌 풀네임으로 변환하여 반환할 것"
        },
        "method": {
          "type": "string",
          "enum": ["hf", "b3lyp", "mp2", "pbe", "pbe0", "ccsd"],
          "description": "계산 방법. 기본: hf"
        },
        "basis_set": {
          "type": "string",
          "description": "기저함수. 예: sto-3g, 6-31g*, cc-pvdz, 6-311g**, aug-cc-pvdz. 기본: sto-3g"
        },
        "job_type": {
          "type": "string",
          "enum": ["energy", "optimize", "frequency", "orbital", "esp"],
          "description": "계산 종류. 기본: energy"
        },
        "charge": {
          "type": "integer",
          "description": "분자 전체 전하. 기본: 0"
        },
        "multiplicity": {
          "type": "integer",
          "description": "스핀 다중도. 기본: 1"
        }
      }
    }
  },
  {
    "name": "search_molecule",
    "description": "분자를 이름, 화학식, CAS 번호로 검색한다.",
    "parameters": {
      "type": "object",
      "properties": {
        "query": { "type": "string", "description": "검색어" }
      },
      "required": ["query"]
    }
  },
  {
    "name": "get_molecule_info",
    "description": "특정 분자의 상세 정보(물성, 구조, 안전데이터)를 조회한다.",
    "parameters": {
      "type": "object",
      "properties": {
        "name": { "type": "string", "description": "분자명 (영문)" },
        "properties": {
          "type": "array",
          "items": { "type": "string" },
          "description": "요청 속성. 예: molecular_weight, smiles, safety, drug_likeness"
        }
      },
      "required": ["name"]
    }
  }
]
```

---

## 이온쌍 별칭 사전 (ion_pair_handler.py에 포함)

| 약어 | 풀네임                                          | 타입   | PubChem CID |
| ---- | ----------------------------------------------- | ------ | ----------- |
| EMIM | 1-ethyl-3-methylimidazolium                     | 양이온 | 174076      |
| BMIM | 1-butyl-3-methylimidazolium                     | 양이온 | 2734162     |
| HMIM | 1-hexyl-3-methylimidazolium                     | 양이온 | —           |
| OMIM | 1-octyl-3-methylimidazolium                     | 양이온 | —           |
| BPy  | 1-butylpyridinium                               | 양이온 | —           |
| DEME | N,N-diethyl-N-methyl-N-(2-methoxyethyl)ammonium | 양이온 | —           |
| P14  | N-butyl-N-methylpyrrolidinium                   | 양이온 | —           |
| TEA  | tetraethylammonium                              | 양이온 | 5413        |
| TBA  | tetrabutylammonium                              | 양이온 | 16211036    |
| Li   | lithium ion                                     | 양이온 | 3028194     |
| Na   | sodium ion                                      | 양이온 | 923         |
| K    | potassium ion                                   | 양이온 | 813         |
| TFSI | bis(trifluoromethylsulfonyl)imide               | 음이온 | 6093299     |
| BF4  | tetrafluoroborate                               | 음이온 | 26255       |
| PF6  | hexafluorophosphate                             | 음이온 | 26066       |
| OTf  | trifluoromethanesulfonate                       | 음이온 | 62406       |
| DCA  | dicyanamide                                     | 음이온 | 68144       |
| SCN  | thiocyanate                                     | 음이온 | 9322        |
| OAc  | acetate                                         | 음이온 | 175         |
| Cl   | chloride                                        | 음이온 | 312         |
| Br   | bromide                                         | 음이온 | 259         |
| I    | iodide                                          | 음이온 | 30165       |
| NO3  | nitrate                                         | 음이온 | 943         |
| HSO4 | hydrogen sulfate                                | 음이온 | 1117        |
| FSI  | bis(fluorosulfonyl)imide                        | 음이온 | —           |
| BOB  | bis(oxalato)borate                              | 음이온 | —           |
| FAP  | tris(pentafluoroethyl)trifluorophosphate        | 음이온 | —           |

## 한국어 별칭 사전 (ko_aliases.py에 포함)

| 한국어       | 영어              | CID   |
| ------------ | ----------------- | ----- |
| 물           | water             | 962   |
| 에탄올       | ethanol           | 702   |
| 메탄올       | methanol          | 887   |
| 메탄         | methane           | 297   |
| 에탄         | ethane            | 6324  |
| 벤젠         | benzene           | 241   |
| 톨루엔       | toluene           | 1140  |
| 아세톤       | acetone           | 180   |
| 암모니아     | ammonia           | 222   |
| 이산화탄소   | carbon dioxide    | 280   |
| 일산화탄소   | carbon monoxide   | 281   |
| 포름알데히드 | formaldehyde      | 712   |
| 아세트산     | acetic acid       | 176   |
| 글리신       | glycine           | 750   |
| 요소         | urea              | 1176  |
| 피리딘       | pyridine          | 1049  |
| 페놀         | phenol            | 996   |
| 아스피린     | aspirin           | 2244  |
| 카페인       | caffeine          | 2519  |
| 포도당       | glucose           | 5793  |
| 과산화수소   | hydrogen peroxide | 784   |
| 황산         | sulfuric acid     | 1118  |
| 염산         | hydrochloric acid | 313   |
| 수산화나트륨 | sodium hydroxide  | 14798 |
| 아세틸렌     | acetylene         | 6326  |
| 프로판       | propane           | 6334  |
| 부탄         | butane            | 7843  |
| 나프탈렌     | naphthalene       | 931   |
| 글루탐산     | glutamic acid     | 33032 |
| 세로토닌     | serotonin         | 5202  |

---

## v3 데이터 흐름 (이걸 구현하라)

```
유저 입력 (한국어/영어/이온쌍 모두 가능)
│
├─ 1. WebSocket 또는 HTTP 수신 (chat.py / compute.py)
│
├─ 2. Gemini function calling (services/gemini_agent.py)
│     ├─ 성공 → GeminiResult (structure/structures, method, basis_set, job_type 등)
│     └─ 실패 → ko_aliases.translate() + agent.py 키워드 폴백
│
├─ 3. 이온쌍 감지? (structures 배열이 있으면)
│     ├─ Yes → ion_pair_handler.resolve_ion_pair()
│     │        ├─ ION_ALIASES 사전으로 약어→풀네임
│     │        ├─ 각 이온을 structure_resolver로 개별 resolve
│     │        ├─ sdf_converter.merge_sdfs() (5Å 오프셋)
│     │        └─ IonPairResult (xyz, total_charge, smiles_list)
│     └─ No → structure_resolver.resolve() 단일 분자
│
├─ 4. structure_resolver.resolve()
│     ├─ 4a. ko_aliases.translate() (한국어→영어)
│     ├─ 4b. molchat_client.resolve() → CID
│     ├─ 4c. molchat_client.get_card() → SMILES
│     ├─ 4d. molchat_client.generate_3d_sdf() → 3D SDF
│     ├─ 4e. sdf_converter.sdf_to_xyz() → XYZ
│     └─ 4f. 실패 시 → pubchem_client 폴백 (name_to_sdf_3d 또는 cid_to_sdf_3d)
│
├─ 5. PySCF 계산 (compute/pyscf_runner.py) ← 기존 유지
│     ├─ XYZ 문자열 또는 atoms list 입력
│     ├─ SCF 캐시 확인 (LRU 256)
│     ├─ ThreadPoolExecutor에서 실행
│     └─ progress callback → WebSocket/SSE 스트리밍
│
└─ 6. 결과 → 프론트엔드
      ├─ results.js: 결과 저장 + 키 매핑
      ├─ viewer.js: 3D 렌더링 (XYZ → 3Dmol.js)
      └─ app.js: 히스토리 추가
```

---

## 구현 순서 (이 순서대로 파일을 출력하라)

```
 1. src/qcviz_mcp/services/__init__.py        (신규)
 2. src/qcviz_mcp/services/ko_aliases.py       (신규)
 3. src/qcviz_mcp/services/sdf_converter.py    (신규)
 4. src/qcviz_mcp/services/molchat_client.py   (신규)
 5. src/qcviz_mcp/services/pubchem_client.py   (신규)
 6. src/qcviz_mcp/services/ion_pair_handler.py (신규)
 7. src/qcviz_mcp/services/structure_resolver.py (신규)
 8. src/qcviz_mcp/services/gemini_agent.py     (신규)
 9. src/qcviz_mcp/config.py                    (수정)
10. src/qcviz_mcp/llm/agent.py                 (수정)
11. src/qcviz_mcp/web/routes/compute.py        (수정)
12. src/qcviz_mcp/web/routes/chat.py           (수정)
13. src/qcviz_mcp/compute/pyscf_runner.py      (수정)
14. src/qcviz_mcp/compute/job_manager.py       (수정)
15. src/qcviz_mcp/web/static/chat.js           (수정)
16. src/qcviz_mcp/web/static/viewer.js         (수정)
17. src/qcviz_mcp/web/static/results.js        (수정)
18. src/qcviz_mcp/web/static/app.js            (수정)
19. src/qcviz_mcp/web/static/style.css         (수정)
20. src/qcviz_mcp/web/templates/index.html     (수정)
21. requirements.txt                            (수정)
```

각 파일을 `## 파일: {경로}` 헤더와 함께 전체 코드를 코드블록으로 출력하라.

---

## 현재 코드 전문 (패치 전 상태)

아래부터 version03의 핵심 파일 전문입니다. 이 코드를 읽고 위 지시에 따라 수정/생성하라.

# QCViz Version03 - 패치 대상 핵심 파일 전문 (패치 전 상태)

> version02에서 복사한 version03의 현재 코드입니다.
> 이 코드를 읽고 v3_patch_prompt.md의 지시에 따라 수정하세요.

---

## 파일: `pyproject.toml` (52줄, 1056bytes)

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "qcviz-mcp"
version = "0.2.0"
description = "Quantum Chemistry Visualization MCP server with FastAPI, PySCF, 3Dmol.js, WebSocket, and LLM planning"
readme = "README.md"
requires-python = ">=3.10"
authors = [
  { name = "QCViz Team" }
]
dependencies = [
  "fastapi>=0.110,<1.0",
  "uvicorn[standard]>=0.29,<1.0",
  "jinja2>=3.1,<4.0",
  "pydantic>=2.6,<3.0",
  "numpy>=1.26",
  "scipy>=1.11",
  "pyscf>=2.4,<3.0",
  "python-dotenv>=1.0,<2.0",
  "httpx>=0.27,<1.0",
  "orjson>=3.10,<4.0",
]

[project.optional-dependencies]
llm-openai = [
  "openai>=1.30,<2.0",
]
llm-gemini = [
  "google-genai>=0.7,<2.0",
]
dev = [
  "pytest>=8.0,<9.0",
  "pytest-asyncio>=0.23,<1.0",
  "pytest-cov>=5.0,<6.0",
]

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.coverage.run]
source = ["src/qcviz_mcp"]
branch = true
```

---

## 파일: `requirements.txt` (14줄, 227bytes)

```
fastapi>=0.110,<1.0
uvicorn[standard]>=0.29,<1.0
jinja2>=3.1,<4.0
pydantic>=2.6,<3.0

numpy>=1.26
scipy>=1.11
pyscf>=2.4,<3.0

openai>=1.30,<2.0
google-genai>=0.7,<2.0

python-dotenv>=1.0,<2.0
httpx>=0.27,<1.0
orjson>=3.10,<4.0
```

---

## 파일: `pytest.ini` (15줄, 429bytes)

```ini
[pytest]
pythonpath = src
testpaths = tests
asyncio_mode = auto
addopts = -ra --tb=short --strict-markers
markers =
    api: HTTP API tests
    ws: WebSocket contract tests
    contract: payload/result contract tests
    slow: slow tests
    real_pyscf: real PySCF integration tests
filterwarnings =
    ignore::DeprecationWarning:pkg_resources.*
    ignore::DeprecationWarning:starlette.*
    ignore::DeprecationWarning:httpx.*

```

---

## 파일: `start_server.sh` (23줄, 973bytes)

```bash
#!/bin/bash

# ==============================================================================
# QCViz-MCP Enterprise Server Startup Script
# ==============================================================================

# 1. 설정된 포트 번호 받기 (기본값: 8000)
PORT=${1:-8000}

# 2. 실행 안내 메시지
echo "🚀 QCViz-MCP Enterprise Web Server를 시작합니다!"
echo "   포트 번호: $PORT"
echo "--------------------------------------------------------------------------------"

# 3. 소스 코드 경로(PYTHONPATH) 설정
# 현재 디렉토리가 'version02'인지 확인하고, 'src'를 파이썬 모듈 경로로 등록합니다.
export PYTHONPATH=src

# 4. 서버 시작 (uvicorn 실행)
# 호스트는 0.0.0.0 (외부 접속 허용)으로 열어두고, 지정된 포트로 실행합니다.
uvicorn qcviz_mcp.web.app:app --host 0.0.0.0 --port "$PORT" --reload

# ==============================================================================

```

---

## 파일: `src/qcviz_mcp/__init__.py` (8줄, 251bytes)

```python
"""QCViz-MCP: 양자화학 시각화 및 전자 구조 분석을 위한 MCP 서버.

이 패키지는 빠른 MCP 연동을 위한 백엔드 구조와 도구들을 제공합니다.
"""

from __future__ import annotations

__version__ = "0.1.0"

```

---

## 파일: `src/qcviz_mcp/config.py` (56줄, 1830bytes)

```python
from dataclasses import dataclass, field
from pathlib import Path
import os

@dataclass(frozen=True)
class ServerConfig:
    """서버 설정. 환경 변수 또는 기본값에서 로드. 불변."""

    # 서버
    host: str = "127.0.0.1"
    port: int = 8765
    transport: str = "sse"  # "sse" | "stdio"

    # 계산
    max_atoms: int = 50
    max_workers: int = 2
    computation_timeout_seconds: float = 300.0
    default_basis: str = "sto-3g"
    default_cube_resolution: int = 80

    # 캐시
    cache_max_size: int = 50
    cache_ttl_seconds: float = 3600.0

    # 보안
    rate_limit_capacity: int = 100
    rate_limit_refill_rate: float = 1.0
    allowed_output_root: Path = field(default_factory=lambda: Path.cwd() / "output")

    # 관측가능성
    log_level: str = "INFO"
    log_json: bool = False

    # 렌더러
    preferred_renderer: str = "auto"  # "auto" | "pyvista" | "playwright" | "py3dmol"

    @classmethod
    def from_env(cls) -> "ServerConfig":
        """환경 변수에서 설정 로드. QCVIZ_ 접두사."""
        kwargs = {}
        for f in cls.__dataclass_fields__:
            env_key = f"QCVIZ_{f.upper()}"
            env_val = os.environ.get(env_key)
            if env_val is not None:
                field_type = cls.__dataclass_fields__[f].type
                if field_type in ("int", int):
                    kwargs[f] = int(env_val)
                elif field_type in ("float", float):
                    kwargs[f] = float(env_val)
                elif field_type in ("bool", bool):
                    kwargs[f] = env_val.lower() in ("true", "1", "yes")
                elif "Path" in str(field_type):
                    kwargs[f] = Path(env_val)
                else:
                    kwargs[f] = env_val
        return cls(**kwargs)

```

---

## 파일: `src/qcviz_mcp/errors.py` (53줄, 2090bytes)

```python
from enum import Enum

class ErrorCategory(str, Enum):
    VALIDATION = "validation"       # 입력 검증 실패
    CONVERGENCE = "convergence"     # SCF 수렴 실패
    RESOURCE = "resource"           # 메모리/타임아웃
    BACKEND = "backend"             # 백엔드 라이브러리 오류
    INTERNAL = "internal"           # 예상치 못한 오류

class QCVizError(Exception):
    """모든 QCViz 에러의 기본 클래스."""

    def __init__(self, message: str, category: ErrorCategory,
                 suggestion: str | None = None, details: dict | None = None):
        super().__init__(message)
        self.category = category
        self.suggestion = suggestion
        self.details = details or {}

    def to_mcp_response(self) -> dict:
        """MCP 프로토콜 호환 에러 응답 생성."""
        resp = {
            "error": {
                "category": self.category.value,
                "message": str(self),
            }
        }
        if self.suggestion:
            resp["error"]["suggestion"] = self.suggestion
        return resp


class ValidationError(QCVizError):
    def __init__(self, message: str, **kwargs):
        super().__init__(message, ErrorCategory.VALIDATION, **kwargs)

class ConvergenceError(QCVizError):
    def __init__(self, message: str, strategies_tried: list[str] | None = None, **kwargs):
        suggestion = (
            "Try: (1) a smaller basis set, (2) adaptive=True for 5-level escalation, "
            "(3) providing an initial guess, or (4) checking molecular geometry."
        )
        super().__init__(message, ErrorCategory.CONVERGENCE, suggestion=suggestion, **kwargs)
        self.strategies_tried = strategies_tried or []

class ResourceError(QCVizError):
    def __init__(self, message: str, **kwargs):
        super().__init__(message, ErrorCategory.RESOURCE, **kwargs)

class BackendError(QCVizError):
    def __init__(self, message: str, backend_name: str = "", **kwargs):
        super().__init__(message, ErrorCategory.BACKEND, **kwargs)
        self.backend_name = backend_name

```

---

## 파일: `src/qcviz_mcp/app.py` (2줄, 78bytes)

```python
from qcviz_mcp.web.app import app, create_app

__all__ = ["app", "create_app"]
```

---

## 파일: `src/qcviz_mcp/mcp_server.py` (24줄, 656bytes)

```python
"""FastMCP 서버 엔트리포인트 (스텁).
Phase 2와 Phase 3 사이에서 유닛 테스트와 통합 테스트를 원활하게 진행하기 위해 뼈대만 작성합니다.
"""

from __future__ import annotations

import logging

from fastmcp import FastMCP

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastMCP 서버 초기화
mcp = FastMCP("QCViz-MCP")

# Tools 등록
import qcviz_mcp.tools.core  # noqa: F401
import qcviz_mcp.tools.advisor_tools  # noqa: F401  — v5.0 advisor

if __name__ == "__main__":
    logger.info("QCViz-MCP 서버 시작 중...")
    mcp.run()

```

---

## 파일: `src/qcviz_mcp/security.py` (113줄, 3982bytes)

```python
"""QCViz-MCP 보안 유틸리티 모듈."""

import os
import re
import time
from pathlib import Path
from dataclasses import dataclass

# 프로젝트 루트 설정
_PROJECT_ROOT = os.path.realpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)

def validate_path(path: str, mode: str = "r") -> Path:
    """경로 탐색 공격 방지를 위한 경로 검증."""
    if ":" in path:
        raise ValueError(f"보안: 잘못된 경로 형식입니다: {path}")
    real_path = os.path.realpath(path)
    if not real_path.startswith(_PROJECT_ROOT):
        # 만약 output 폴더면 허용
        if "output" in real_path:
            return Path(real_path)
        raise ValueError(f"보안: 허용되지 않은 경로입니다: {path}")
    return Path(real_path)

def validate_atom_spec(atom_spec: str, max_atoms: int = 200) -> str:
    """원자 지정 문자열 검증."""
    # 간단한 원자 수 체크
    lines = atom_spec.strip().splitlines()
    if not lines:
        return atom_spec

    # XYZ 포맷 체크
    try:
        n = int(lines[0].strip())
        is_xyz = True
    except (ValueError, IndexError):
        is_xyz = False

    if is_xyz:
        if n > max_atoms:
            raise ValueError(f"원자 수 초과 (최대 {max_atoms})")
    else:
        # PySCF 포맷 체크 (세미콜론 구분)
        n = len([l for l in atom_spec.split(";") if l.strip()])
        if n > max_atoms:
            raise ValueError(f"원자 수 초과 (최대 {max_atoms})")
    return atom_spec

# 기존 검증에 추가
FORBIDDEN_BASIS_PATTERNS = re.compile(r"[;&|`$(){}]")  # shell injection 차단

def validate_basis(basis: str) -> str:
    """기저 함수 이름 검증. Shell injection 등 방지."""
    if len(basis) > 50:
        raise ValueError(f"Basis name too long: {len(basis)} chars (max 50)")
    if FORBIDDEN_BASIS_PATTERNS.search(basis):
        raise ValueError(f"Invalid characters in basis name: {basis!r}")
    return basis

def validate_atom_spec_strict(atom_spec: str, max_atoms: int = 50,
                                max_length: int = 10_000) -> str:
    """원자 지정 문자열 엄격 검증."""
    if len(atom_spec) > max_length:
        raise ValueError(f"atom_spec too long: {len(atom_spec)} chars (max {max_length})")
    # 줄 수 = 원자 수 근사
    lines = [l.strip() for l in atom_spec.strip().splitlines() if l.strip()]
    if len(lines) > max_atoms:
        raise ValueError(f"원자 수 초과: {len(lines)} (max {max_atoms})")
    return atom_spec

def validate_output_dir(path: Path, allowed_root: Path) -> Path:
    """출력 디렉토리가 허용 범위 내인지 확인. Symlink 해소 후 검증."""
    resolved = path.resolve()
    allowed = allowed_root.resolve()
    if not str(resolved).startswith(str(allowed)):
        raise ValueError(f"Path traversal detected: {path} resolves to {resolved}")
    return resolved


@dataclass
class TokenBucket:
    capacity: int          # 최대 토큰 수
    refill_rate: float     # 초당 토큰 리필 속도
    tokens: float = 0.0
    last_refill: float = 0.0

    def __post_init__(self):
        self.tokens = float(self.capacity)
        self.last_refill = time.monotonic()

    def consume(self, n: int = 1) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False

# 도구별 비용 가중치 (SCF 계산은 비쌈)
TOOL_COSTS = {
    "compute_ibo": 10,        # 무거운 계산
    "analyze_bonding": 8,
    "compute_partial_charges": 5,
    "visualize_orbital": 2,   # 렌더링만
    "parse_output": 1,        # 파일 읽기만
    "convert_format": 1,
}

# 기본 버킷: 분당 60 토큰, 최대 100 토큰
default_bucket = TokenBucket(capacity=100, refill_rate=1.0)

```

---

## 파일: `src/qcviz_mcp/log_config.py` (29줄, 1001bytes)

```python
import logging
import json
import sys

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        if hasattr(record, "invocation"):
            log_entry["invocation"] = record.invocation
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)

def configure_logging(level: str = "INFO", json_output: bool = False):
    handler = logging.StreamHandler(sys.stderr)
    if json_output:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
    root = logging.getLogger("qcviz_mcp")
    root.setLevel(getattr(logging, level.upper()))
    root.addHandler(handler)

```

---

## 파일: `src/qcviz_mcp/observability.py` (112줄, 3584bytes)

```python
import logging
import time
import json
import functools
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from typing import Any

logger = logging.getLogger("qcviz_mcp")

@dataclass
class ToolInvocation:
    tool_name: str
    request_id: str
    start_time: float = field(default_factory=time.monotonic)
    end_time: float | None = None
    status: str = "running"
    parameters: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def duration_ms(self) -> float:
        if self.end_time is None:
            return (time.monotonic() - self.start_time) * 1000
        return (self.end_time - self.start_time) * 1000

    def finish(self, status: str = "success", **extra_metrics):
        self.end_time = time.monotonic()
        self.status = status
        self.metrics.update(extra_metrics)

    def to_log_dict(self) -> dict:
        d = asdict(self)
        d["duration_ms"] = self.duration_ms
        return d


class MetricsCollector:
    """In-process metrics aggregation.
    Enterprise deployment would export to Prometheus/OTLP."""

    def __init__(self):
        self._invocations: list[ToolInvocation] = []
        self._counters: dict[str, int] = {}

    def record(self, invocation: ToolInvocation):
        self._invocations.append(invocation)
        self._counters[f"{invocation.tool_name}.{invocation.status}"] = (
            self._counters.get(f"{invocation.tool_name}.{invocation.status}", 0) + 1
        )

    def get_summary(self) -> dict:
        return {
            "total_invocations": len(self._invocations),
            "counters": dict(self._counters),
            "avg_duration_ms": {
                name: sum(
                    inv.duration_ms for inv in self._invocations
                    if inv.tool_name == name
                ) / max(1, sum(1 for inv in self._invocations if inv.tool_name == name))
                for name in {inv.tool_name for inv in self._invocations}
            }
        }

# Singleton
metrics = MetricsCollector()


def traced_tool(func):
    """Decorator for MCP tool functions with automatic tracing."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        import uuid
        invocation = ToolInvocation(
            tool_name=func.__name__,
            request_id=str(uuid.uuid4())[:8],
            parameters={k: _safe_repr(v) for k, v in kwargs.items()},
        )
        logger.info(
            "tool.start",
            extra={"invocation": invocation.to_log_dict()}
        )
        try:
            result = await func(*args, **kwargs)
            invocation.finish(
                status="success",
                result_size=len(str(result)) if result else 0,
            )
            logger.info(
                "tool.success",
                extra={"invocation": invocation.to_log_dict()}
            )
            metrics.record(invocation)
            return result
        except Exception as e:
            invocation.finish(status="error")
            invocation.error = f"{type(e).__name__}: {e}"
            logger.error(
                "tool.error",
                extra={"invocation": invocation.to_log_dict()},
                exc_info=True,
            )
            metrics.record(invocation)
            raise
    return wrapper


def _safe_repr(v: Any, max_len: int = 200) -> str:
    """Truncate large values for logging."""
    s = repr(v)
    return s[:max_len] + "..." if len(s) > max_len else s

```

---

## 파일: `src/qcviz_mcp/llm/__init__.py` (2줄, 79bytes)

```python
from .agent import AgentPlan, QCVizAgent

__all__ = ["AgentPlan", "QCVizAgent"]
```

---

## 파일: `src/qcviz_mcp/llm/agent.py` (608줄, 21429bytes)

```python
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


PLAN_TOOL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": [
                "analyze",
                "single_point",
                "geometry_analysis",
                "partial_charges",
                "orbital_preview",
                "esp_map",
                "geometry_optimization",
                "resolve_structure",
            ],
        },
        "structure_query": {"type": "string"},
        "method": {"type": "string"},
        "basis": {"type": "string"},
        "charge": {"type": "integer"},
        "multiplicity": {"type": "integer"},
        "orbital": {"type": "string"},
        "esp_preset": {
            "type": "string",
            "enum": [
                "rwb",
                "bwr",
                "viridis",
                "inferno",
                "spectral",
                "nature",
                "acs",
                "rsc",
                "greyscale",
                "high_contrast",
                "grey",
                "hicon",
            ],
        },
        "focus_tab": {
            "type": "string",
            "enum": ["summary", "geometry", "orbital", "esp", "charges", "json", "jobs"],
        },
        "confidence": {"type": "number"},
        "notes": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["intent"],
    "additionalProperties": True,
}


INTENT_DEFAULTS: Dict[str, Dict[str, str]] = {
    "analyze": {"tool_name": "run_analyze", "focus_tab": "summary"},
    "single_point": {"tool_name": "run_single_point", "focus_tab": "summary"},
    "geometry_analysis": {"tool_name": "run_geometry_analysis", "focus_tab": "geometry"},
    "partial_charges": {"tool_name": "run_partial_charges", "focus_tab": "charges"},
    "orbital_preview": {"tool_name": "run_orbital_preview", "focus_tab": "orbital"},
    "esp_map": {"tool_name": "run_esp_map", "focus_tab": "esp"},
    "geometry_optimization": {"tool_name": "run_geometry_optimization", "focus_tab": "geometry"},
    "resolve_structure": {"tool_name": "run_resolve_structure", "focus_tab": "summary"},
}


SYSTEM_PROMPT = """
You are QCViz Planner, a planning agent for a quantum chemistry web app.

Your job:
- Read the user's natural-language request.
- Infer the best computation intent.
- Extract structure_query, method, basis, charge, multiplicity, orbital, and esp_preset when explicit.
- Choose the best focus_tab for the frontend.
- Return ONLY arguments for the planning function / JSON object.

Intent rules:
- Use "esp_map" for electrostatic potential / ESP / electrostatic surface requests.
- Use "orbital_preview" for HOMO/LUMO/orbital/isovalue/orbital rendering requests.
- Use "partial_charges" for Mulliken/partial charge requests.
- Use "geometry_optimization" for optimize/optimization/relax geometry requests.
- Use "geometry_analysis" for bond length / angle / geometry analysis requests.
- Use "single_point" for single-point energy requests.
- Use "analyze" for general all-in-one analysis requests.

Extraction rules:
- structure_query should be the molecule/material/system name or pasted geometry string.
- focus_tab should be:
  - orbital for orbital_preview
  - esp for esp_map
  - charges for partial_charges
  - geometry for geometry_analysis or geometry_optimization
  - summary otherwise
- confidence should be 0.0 to 1.0
- notes can explain ambiguous choices briefly.

If the structure is unclear, still return the best intent and leave structure_query empty.
""".strip()


@dataclass
class AgentPlan:
    intent: str = "analyze"
    structure_query: Optional[str] = None
    method: Optional[str] = None
    basis: Optional[str] = None
    charge: Optional[int] = None
    multiplicity: Optional[int] = None
    orbital: Optional[str] = None
    esp_preset: Optional[str] = None
    focus_tab: str = "summary"
    confidence: float = 0.0
    tool_name: str = "run_analyze"
    notes: List[str] = field(default_factory=list)
    provider: str = "heuristic"
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_public_dict(self) -> Dict[str, Any]:
        data = self.to_dict()
        data.pop("raw", None)
        return data


class QCVizAgent:
    def __init__(
        self,
        *,
        provider: Optional[str] = None,
        openai_model: Optional[str] = None,
        gemini_model: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        gemini_api_key: Optional[str] = None,
    ) -> None:
        self.provider = (provider or os.getenv("QCVIZ_LLM_PROVIDER", "auto")).strip().lower()
        self.openai_model = openai_model or os.getenv("QCVIZ_OPENAI_MODEL", "gpt-4.1-mini")
        self.gemini_model = gemini_model or os.getenv("QCVIZ_GEMINI_MODEL", "gemini-2.0-flash")
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY")

    @classmethod
    def from_env(cls) -> "QCVizAgent":
        return cls()

    def plan(self, message: str, context: Optional[Dict[str, Any]] = None) -> AgentPlan:
        text = (message or "").strip()
        if not text:
            return self._coerce_plan({"intent": "analyze", "confidence": 0.0}, provider="heuristic")

        chosen = self._choose_provider()
        if chosen == "openai":
            try:
                return self._plan_with_openai(text, context=context or {})
            except Exception:
                pass

        if chosen == "gemini":
            try:
                return self._plan_with_gemini(text, context=context or {})
            except Exception:
                pass

        if chosen == "auto":
            if self.openai_api_key:
                try:
                    return self._plan_with_openai(text, context=context or {})
                except Exception:
                    pass
            if self.gemini_api_key:
                try:
                    return self._plan_with_gemini(text, context=context or {})
                except Exception:
                    pass

        return self._heuristic_plan(text, context=context or {})

    def _choose_provider(self) -> str:
        if self.provider in {"openai", "gemini", "none"}:
            return self.provider
        return "auto"

    def _plan_with_openai(self, message: str, context: Dict[str, Any]) -> AgentPlan:
        from openai import OpenAI

        if not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        client = OpenAI(api_key=self.openai_api_key)
        user_prompt = self._compose_user_prompt(message, context=context)

        resp = client.chat.completions.create(
            model=self.openai_model,
            temperature=0,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "plan_quantum_request",
                        "description": "Plan a user request into a QCViz compute intent.",
                        "parameters": PLAN_TOOL_SCHEMA,
                    },
                }
            ],
            tool_choice={"type": "function", "function": {"name": "plan_quantum_request"}},
        )

        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        data: Dict[str, Any]

        if tool_calls:
            args = tool_calls[0].function.arguments or "{}"
            data = json.loads(args)
        else:
            content = self._message_content_to_text(getattr(msg, "content", ""))
            data = self._extract_json_dict(content)

        return self._coerce_plan(data, provider="openai")

    def _plan_with_gemini(self, message: str, context: Dict[str, Any]) -> AgentPlan:
        user_prompt = self._compose_user_prompt(message, context=context)

        # new google-genai
        try:
            from google import genai  # type: ignore

            if not self.gemini_api_key:
                raise RuntimeError("GEMINI_API_KEY is not set")

            client = genai.Client(api_key=self.gemini_api_key)
            resp = client.models.generate_content(
                model=self.gemini_model,
                contents=[
                    {"role": "user", "parts": [{"text": SYSTEM_PROMPT}]},
                    {"role": "user", "parts": [{"text": user_prompt}]},
                ],
                config={
                    "response_mime_type": "application/json",
                },
            )
            text = getattr(resp, "text", None) or self._message_content_to_text(resp)
            data = self._extract_json_dict(text)
            return self._coerce_plan(data, provider="gemini")
        except ImportError:
            pass

        # older google-generativeai
        import google.generativeai as genai  # type: ignore

        if not self.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")

        genai.configure(api_key=self.gemini_api_key)
        model = genai.GenerativeModel(self.gemini_model)
        resp = model.generate_content(
            f"{SYSTEM_PROMPT}\n\n{user_prompt}",
            generation_config={"response_mime_type": "application/json", "temperature": 0},
        )
        text = getattr(resp, "text", None) or self._message_content_to_text(resp)
        data = self._extract_json_dict(text)
        return self._coerce_plan(data, provider="gemini")

    def _compose_user_prompt(self, message: str, context: Dict[str, Any]) -> str:
        context_json = json.dumps(context or {}, ensure_ascii=False)
        return f"Context:\n{context_json}\n\nUser message:\n{message}"

    def _heuristic_plan(self, message: str, context: Dict[str, Any]) -> AgentPlan:
        text = message.strip()
        lower = text.lower()

        intent = "analyze"
        confidence = 0.55
        notes: List[str] = []

        if any(k in lower for k in ["esp", "electrostatic potential", "electrostatic surface", "potential map"]):
            intent = "esp_map"
            confidence = 0.9
        elif any(k in lower for k in ["homo", "lumo", "orbital", "mo ", "molecular orbital", "isosurface"]):
            intent = "orbital_preview"
            confidence = 0.88
        elif any(k in lower for k in ["mulliken", "partial charge", "charges", "charge distribution"]):
            intent = "partial_charges"
            confidence = 0.88
        elif any(k in lower for k in ["optimize", "optimization", "relax geometry", "geometry optimization", "minimize"]):
            intent = "geometry_optimization"
            confidence = 0.86
        elif any(k in lower for k in ["bond length", "bond angle", "dihedral", "geometry", "angle"]):
            intent = "geometry_analysis"
            confidence = 0.8
        elif any(k in lower for k in ["single point", "single-point", "sp energy"]):
            intent = "single_point"
            confidence = 0.82

        structure_query = self._extract_structure_query(text)
        method = self._extract_method(text)
        basis = self._extract_basis(text)
        charge = self._extract_charge(text)
        multiplicity = self._extract_multiplicity(text)
        orbital = self._extract_orbital(text)
        esp_preset = self._extract_esp_preset(text)

        if structure_query:
            confidence = min(0.98, confidence + 0.05)
        else:
            notes.append("structure_query not confidently extracted")

        data = {
            "intent": intent,
            "structure_query": structure_query,
            "method": method,
            "basis": basis,
            "charge": charge,
            "multiplicity": multiplicity,
            "orbital": orbital,
            "esp_preset": esp_preset,
            "confidence": confidence,
            "notes": notes,
        }
        return self._coerce_plan(data, provider="heuristic")

    def _coerce_plan(self, data: Dict[str, Any], provider: str) -> AgentPlan:
        data = dict(data or {})
        intent = str(data.get("intent") or "analyze").strip()
        defaults = INTENT_DEFAULTS.get(intent, INTENT_DEFAULTS["analyze"])

        structure_query = self._none_if_blank(data.get("structure_query"))
        method = self._none_if_blank(data.get("method"))
        basis = self._none_if_blank(data.get("basis"))
        orbital = self._none_if_blank(data.get("orbital"))
        esp_preset = self._normalize_preset(self._none_if_blank(data.get("esp_preset")))
        focus_tab = str(data.get("focus_tab") or defaults["focus_tab"]).strip()
        tool_name = str(data.get("tool_name") or defaults["tool_name"]).strip()

        charge = self._safe_int(data.get("charge"))
        multiplicity = self._safe_int(data.get("multiplicity"))
        confidence = self._safe_float(data.get("confidence"), 0.0)
        confidence = max(0.0, min(1.0, confidence))

        notes = data.get("notes") or []
        if not isinstance(notes, list):
            notes = [str(notes)]

        return AgentPlan(
            intent=intent,
            structure_query=structure_query,
            method=method,
            basis=basis,
            charge=charge,
            multiplicity=multiplicity,
            orbital=orbital,
            esp_preset=esp_preset,
            focus_tab=focus_tab,
            confidence=confidence,
            tool_name=tool_name,
            notes=[str(x) for x in notes if str(x).strip()],
            provider=provider,
            raw=data,
        )

    def _extract_structure_query(self, text: str) -> Optional[str]:
        # pasted xyz block
        if len(re.findall(r"\n", text)) >= 2 and re.search(r"^[A-Z][a-z]?\s+-?\d", text, re.M):
            return text.strip()

        quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', text)
        if quoted:
            first = quoted[0][0] or quoted[0][1]
            if first.strip():
                return first.strip()

        patterns = [
            r"(?i)(?:for|of|on|about)\s+(?:the\s+)?([a-zA-Z][a-zA-Z0-9_\-\+\(\), ]{1,80})",
            r"(?i)([a-zA-Z][a-zA-Z0-9_\-\+\(\), ]{1,80})\s+(?:molecule|structure|system)",
            r"([가-힣A-Za-z0-9_\-\+\(\), ]+?)\s*(?:의|에\s*대한)?\s*(?:homo|lumo|esp|전하|구조|에너지|최적화|분석|보여줘|해줘|계산)",
            r"([가-힣A-Za-z0-9_\-\+\(\), ]+?)\s+(?:분자|구조|이온쌍|이온)",
            r"(?i)(?:analyze|compute|calculate|show|render|visualize|optimize)\s+(?:the\s+)?([A-Za-z0-9_\-\+\(\), ]{2,80})",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                candidate = m.group(1).strip(" .,:;")
                candidate = re.split(
                    r"\b(using|with|at|in|and show|and render|method|basis|charge|multiplicity|spin|preset)\b",
                    candidate,
                    maxsplit=1,
                    flags=re.I,
                )[0].strip(" .,:;")

                # Filter out korean noise words
                for noise in ["의", "에 대한", "에대한", "분자", "구조", "계산", "해줘", "보여줘"]:
                    if candidate.endswith(noise):
                        candidate = candidate[:-len(noise)].strip(" .,:;")

                if candidate and len(candidate) >= 2:
                    return candidate

        common = [
            "water",
            "methane",
            "ammonia",
            "benzene",
            "ethanol",
            "acetone",
            "formaldehyde",
            "carbon dioxide",
            "co2",
            "nh3",
            "h2o",
            "caffeine",
            "naphthalene",
            "pyridine",
            "phenol",
        ]
        lower = text.lower()
        for name in common:
            if name in lower:
                return name

        return None

    def _extract_method(self, text: str) -> Optional[str]:
        methods = [
            "HF",
            "B3LYP",
            "PBE",
            "PBE0",
            "M06-2X",
            "M062X",
            "wB97X-D",
            "WB97X-D",
            "CAM-B3LYP",
            "TPSSh",
            "BP86",
        ]
        for method in methods:
            if re.search(rf"\b{re.escape(method)}\b", text, re.I):
                return method
        return None

    def _extract_basis(self, text: str) -> Optional[str]:
        basis_list = [
            "sto-3g",
            "3-21g",
            "6-31g",
            "6-31g*",
            "6-31g**",
            "6-311g",
            "6-311g*",
            "6-311g**",
            "def2-svp",
            "def2-tzvp",
            "cc-pvdz",
            "cc-pvtz",
            "aug-cc-pvdz",
        ]
        for basis in basis_list:
            if re.search(rf"\b{re.escape(basis)}\b", text, re.I):
                return basis
        return None

    def _extract_charge(self, text: str) -> Optional[int]:
        patterns = [
            r"\bcharge\s*[:=]?\s*([+-]?\d+)\b",
            r"\bq\s*=\s*([+-]?\d+)\b",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                return self._safe_int(m.group(1))

        if re.search(r"\banion\b", text, re.I):
            return -1
        if re.search(r"\bcation\b", text, re.I):
            return 1
        return None

    def _extract_multiplicity(self, text: str) -> Optional[int]:
        patterns = [
            r"\bmultiplicity\s*[:=]?\s*(\d+)\b",
            r"\bspin multiplicity\s*[:=]?\s*(\d+)\b",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                return self._safe_int(m.group(1))

        if re.search(r"\bsinglet\b", text, re.I):
            return 1
        if re.search(r"\bdoublet\b", text, re.I):
            return 2
        if re.search(r"\btriplet\b", text, re.I):
            return 3
        return None

    def _extract_orbital(self, text: str) -> Optional[str]:
        patterns = [
            r"\b(HOMO(?:[+-]\d+)?)\b",
            r"\b(LUMO(?:[+-]\d+)?)\b",
            r"\b(MO\s*\d+)\b",
            r"\borbital\s+([A-Za-z0-9+\-]+)\b",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                return m.group(1).strip().upper().replace(" ", "")
        return None

    def _extract_esp_preset(self, text: str) -> Optional[str]:
        presets = [
            "rwb",
            "bwr",
            "viridis",
            "inferno",
            "spectral",
            "nature",
            "acs",
            "rsc",
            "greyscale",
            "grey",
            "high_contrast",
            "hicon",
        ]
        for preset in presets:
            if re.search(rf"\b{re.escape(preset)}\b", text, re.I):
                return self._normalize_preset(preset)
        return None

    def _normalize_preset(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        key = value.strip().lower()
        if key == "grey":
            return "greyscale"
        if key == "hicon":
            return "high_contrast"
        return key

    def _message_content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    if "text" in item:
                        parts.append(str(item["text"]))
                    elif item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
                else:
                    parts.append(str(item))
            return "\n".join(parts).strip()
        return str(content or "")

    def _extract_json_dict(self, text: str) -> Dict[str, Any]:
        raw = (text or "").strip()
        if not raw:
            return {}

        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            pass

        match = re.search(r"\{.*\}", raw, re.S)
        if match:
            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}
        return {}

    def _safe_int(self, value: Any) -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except Exception:
            return None

    def _safe_float(self, value: Any, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return default

    def _none_if_blank(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
```

---

## 파일: `src/qcviz_mcp/llm/bridge.py` (140줄, 4811bytes)

```python
"""LLM bridge for QCViz web UI."""

from __future__ import annotations

import importlib
import inspect
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict

from qcviz_mcp.llm.rule_provider import plan_from_message

logger = logging.getLogger(__name__)


@dataclass
class Intent:
    """Normalized intent."""

    intent: str
    query: str
    metadata: Dict[str, Any]


class LLMBridge:
    """Tiered LLM bridge.

    Bootstrap implementation:
    - rule_based
    - auto -> rule_based
    - advisor direct-call helper
    """

    def __init__(self, mode: str = "auto") -> None:
        self.mode = mode or "auto"

    def interpret_user_intent(self, message: str) -> Intent:
        """Interpret natural language into structured intent."""
        parsed = plan_from_message(message)
        return Intent(
            intent=parsed.intent,
            query=parsed.query,
            metadata=parsed.metadata,
        )

    def _load_advisor_module(self):
        """Load advisor tool module."""
        return importlib.import_module("qcviz_mcp.tools.advisor_tools")

    def call_advisor_tool(self, tool_name: str, params: Dict[str, Any]) -> Any:
        """Call an advisor MCP tool directly as a Python function.

        Args:
            tool_name: Advisor tool name.
            params: Candidate kwargs.

        Returns:
            Tool output, parsed as JSON when possible.
        """
        module = self._load_advisor_module()

        if not hasattr(module, tool_name):
            raise AttributeError("advisor tool not found: %s" % tool_name)

        func = getattr(module, tool_name)
        sig = inspect.signature(func)
        accepts_kwargs = any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in sig.parameters.values()
        )

        kwargs = {}
        for key, value in dict(params or {}).items():
            if accepts_kwargs or key in sig.parameters:
                kwargs[key] = value

        raw = func(**kwargs)

        if isinstance(raw, str):
            text = raw.strip()
            if text.startswith("{") or text.startswith("["):
                try:
                    return json.loads(text)
                except Exception:
                    return raw

        return raw

    def generate_response(self, intent: Intent, results: Dict[str, Any]) -> str:
        """Generate a user-facing response."""
        if results.get("status") == "error":
            return "요청을 처리하지 못했습니다. %s" % results.get("error", "알 수 없는 오류")

        advisor = results.get("advisor") or {}
        confidence = advisor.get("confidence") or {}
        confidence_data = confidence.get("data") if isinstance(confidence, dict) else None

        literature = advisor.get("literature") or {}
        literature_data = literature.get("data") if isinstance(literature, dict) else None

        if intent.intent == "geometry_opt":
            base = "구조 최적화 계산이 완료되었습니다. 오른쪽 뷰어에서 최적화된 3D 구조를 확인하세요."
        elif intent.intent == "validate":
            base = "기하구조 분석이 완료되었습니다. 결합 길이와 각도 표를 확인하세요."
        elif intent.intent == "partial_charges":
            base = "부분 전하 계산이 완료되었습니다. Charges 탭에서 원자별 전하를 확인하세요."
        elif intent.intent == "orbital":
            base = "오비탈 프리뷰 계산이 완료되었습니다. Orbitals 탭에서 HOMO/LUMO 근처 궤도를 확인하세요."
        elif intent.intent == "single_point":
            base = "단일점 에너지 계산이 완료되었습니다."
        else:
            base = "요청한 구조 또는 계산 작업이 완료되었습니다."

        parts = [base]

        if results.get("method") and results.get("basis"):
            parts.append(
                "advisor 추천 또는 기본 설정으로 %s/%s 조건을 사용했습니다."
                % (results.get("method"), results.get("basis"))
            )

        if isinstance(confidence_data, dict):
            score = (
                confidence_data.get("score")
                or confidence_data.get("confidence")
                or confidence_data.get("final_score")
            )
            if score is not None:
                parts.append("신뢰도 점수는 %s 입니다." % score)

        if isinstance(literature_data, dict):
            status = (
                literature_data.get("status")
                or literature_data.get("summary")
                or literature_data.get("message")
            )
            if status:
                parts.append("문헌 검증 요약: %s" % status)

        return " ".join(parts)
```

---

## 파일: `src/qcviz_mcp/llm/prompts.py` (28줄, 2116bytes)

```python
"""
System prompts for the QCViz-MCP LLM Agent.
"""

SYSTEM_PROMPT = """You are an elite Quantum Chemistry AI Assistant embedded in the QCViz-MCP Enterprise Web UI.
Your primary role is to interpret natural language requests from researchers and map them to the correct backend computational tools (PySCF).

You have access to a suite of tools for quantum chemical analysis.
For any request, you must analyze the user's intent, decide which tool is most appropriate, and extract the necessary arguments.

CRITICAL RULES:
1. Identify the molecule: If the user provides a common name (e.g., "benzene", "water"), pass it to the `query` argument. If they provide raw XYZ, pass it to the `xyz` argument.
2. If the user asks for "orbitals", "HOMO", "LUMO", or "Frontier MO", you MUST use the `run_orbital_preview` tool.
3. If the user asks for "ESP", "electrostatic potential", "map", or "전기정전위", you MUST use the `run_esp_map` tool.
4. If the user asks for "charges", "Mulliken", or "부분 전하", you MUST use the `run_partial_charges` tool.
5. If the user asks for "optimization", "opt", or "최적화", you MUST use the `run_geometry_optimization` tool.
6. If the user just asks for energy, or doesn't specify, use `run_single_point`.
7. NEVER write code. ALWAYS output a structured JSON response indicating which tool to call.
8. If the user asks a general chemistry question without needing a calculation, set `is_help_only` to true and provide an informative `assistant_message`.

Available Tools:
- run_single_point(query: str, method: str="B3LYP", basis: str="def2-SVP", charge: int=0, spin: int=0)
- run_orbital_preview(query: str, method: str="B3LYP", basis: str="def2-SVP", charge: int=0, spin: int=0)
- run_esp_map(query: str, method: str="B3LYP", basis: str="def2-SVP", charge: int=0, spin: int=0)
- run_partial_charges(query: str, method: str="B3LYP", basis: str="def2-SVP", charge: int=0, spin: int=0)
- run_geometry_optimization(query: str, method: str="B3LYP", basis: str="def2-SVP", charge: int=0, spin: int=0)

Output Format: You must strictly adhere to the PlannerResponse JSON schema.
"""
```

---

## 파일: `src/qcviz_mcp/llm/providers.py` (113줄, 4046bytes)

```python
"""
LLM Provider implementations (Gemini, OpenAI).
"""

import json
import os
import logging
from typing import Optional
from pydantic import ValidationError

from .schemas import PlannerRequest, PlannerResponse, ToolCall
from .prompts import SYSTEM_PROMPT

logger = logging.getLogger("qcviz_mcp.llm.providers")

try:
    from google import genai
    from google.genai import types
    _HAS_GEMINI = True
except ImportError:
    _HAS_GEMINI = False


class LLMProvider:
    def plan(self, request: PlannerRequest) -> PlannerResponse:
        raise NotImplementedError()


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: Optional[str] = None):
        if not _HAS_GEMINI:
            raise ImportError("google-genai is not installed. Run: pip install google-genai")

        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set.")

        self.client = genai.Client(api_key=self.api_key)
        self.model_name = "gemini-2.5-flash"

    def plan(self, request: PlannerRequest) -> PlannerResponse:
        user_prompt = request.user_prompt

        prompt_text = f"""
        User Request: {user_prompt}

        Available Tools: {request.available_tools}

        Return a JSON object that perfectly matches the PlannerResponse schema.
        """

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt_text,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=PlannerResponse.model_json_schema(),
                    temperature=0.1,
                ),
            )

            raw_text = response.text
            data = json.loads(raw_text)
            return PlannerResponse(**data)

        except Exception as e:
            logger.error(f"Gemini API Error: {e}")
            # Fallback to rule-based logic or default response
            return PlannerResponse(
                thought_process=f"Failed to call LLM: {str(e)}",
                assistant_message="AI 에이전트 호출에 실패하여 기본 룰(Rule-based) 모드로 동작합니다.",
                tool_calls=[],
                is_help_only=True
            )


class DummyProvider(LLMProvider):
    """Fallback provider when no API key is available. Simulates basic rule-based routing."""

    def plan(self, request: PlannerRequest) -> PlannerResponse:
        text = request.user_prompt.lower()
        tool = "run_single_point"
        focus = "summary"

        if any(x in text for x in ["orbital", "homo", "lumo", "오비탈"]):
            tool = "run_orbital_preview"
            focus = "orbitals"
        elif any(x in text for x in ["esp", "potential", "map", "전기정전위"]):
            tool = "run_esp_map"
            focus = "esp"
        elif any(x in text for x in ["charge", "mulliken", "부분 전하"]):
            tool = "run_partial_charges"
            focus = "charges"
        elif any(x in text for x in ["opt", "최적화"]):
            tool = "run_geometry_optimization"
            focus = "geometry"

        return PlannerResponse(
            thought_process="Rule-based fallback routing.",
            assistant_message="API 키가 설정되지 않아 로컬 규칙 기반 엔진이 요청을 처리합니다.",
            tool_calls=[ToolCall(tool_name=tool, parameters={"query": request.user_prompt})],
            is_help_only=False,
            suggested_focus_tab=focus
        )


def get_provider() -> LLMProvider:
    if os.environ.get("GEMINI_API_KEY") and _HAS_GEMINI:
        return GeminiProvider()

    logger.warning("No LLM API key found or SDK missing. Using DummyProvider (Rule-based fallback).")
    return DummyProvider()
```

---

## 파일: `src/qcviz_mcp/llm/rule_provider.py` (35줄, 1248bytes)

```python
"""Rule-based LLM provider fallback."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict

@dataclass
class ParsedPlan:
    intent: str
    query: str
    metadata: Dict[str, Any] = field(default_factory=dict)

def plan_from_message(message: str) -> ParsedPlan:
    """Parse message via simple rules."""
    msg_lower = message.lower()
    intent_type = "resolve_structure"

    if "최적화" in msg_lower or "optimize" in msg_lower:
        intent_type = "geometry_opt"
    elif "에너지" in msg_lower or "단일점" in msg_lower or "single point" in msg_lower:
        intent_type = "single_point"
    elif "결합" in msg_lower or "구조 분석" in msg_lower or "validate" in msg_lower:
        intent_type = "validate"
    elif "전하" in msg_lower or "charge" in msg_lower:
        intent_type = "partial_charges"
    elif "오비탈" in msg_lower or "orbital" in msg_lower or "homo" in msg_lower or "lumo" in msg_lower:
        intent_type = "orbital"

    query = message
    for kw in ["계산해줘", "분석해줘", "보여줘", "그려줘", "알려줘"]:
        query = query.replace(kw, "")

    query = query.strip()

    return ParsedPlan(intent=intent_type, query=query)

```

---

## 파일: `src/qcviz_mcp/llm/schemas.py` (25줄, 1222bytes)

```python
"""
Pydantic schemas for LLM Planner Layer.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    tool_name: str = Field(description="Name of the Python tool to execute (e.g., 'run_single_point')")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Arguments to pass to the tool")


class PlannerRequest(BaseModel):
    user_prompt: str = Field(description="Natural language request from the user")
    chat_history: List[Dict[str, str]] = Field(default_factory=list, description="Previous messages")
    available_tools: List[str] = Field(default_factory=list, description="Names of tools the LLM can use")


class PlannerResponse(BaseModel):
    thought_process: str = Field(description="LLM's internal reasoning before deciding on the tool")
    assistant_message: str = Field(description="Message to display to the user")
    tool_calls: List[ToolCall] = Field(default_factory=list, description="Tools to execute")
    is_help_only: bool = Field(default=False, description="True if no tool execution is needed")
    suggested_focus_tab: str = Field(default="summary", description="UI tab to focus on (e.g., 'orbitals', 'esp')")

```

---

## 파일: `src/qcviz_mcp/compute/pyscf_runner.py` (2003줄, 73439bytes)

```python
from __future__ import annotations
import logging
import re
import os
import base64
import math
import tempfile
import threading
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

logger = logging.getLogger(__name__)

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
    "H": 0.31, "He": 0.28,
    "Li": 1.28, "Be": 0.96, "B": 0.85, "C": 0.76, "N": 0.71, "O": 0.66, "F": 0.57, "Ne": 0.58,
    "Na": 1.66, "Mg": 1.41, "Al": 1.21, "Si": 1.11, "P": 1.07, "S": 1.05, "Cl": 1.02, "Ar": 1.06,
    "K": 2.03, "Ca": 1.76, "Sc": 1.70, "Ti": 1.60, "V": 1.53, "Cr": 1.39, "Mn": 1.39,
    "Fe": 1.32, "Co": 1.26, "Ni": 1.24, "Cu": 1.32, "Zn": 1.22,
    "Ga": 1.22, "Ge": 1.20, "As": 1.19, "Se": 1.20, "Br": 1.20, "Kr": 1.16,
    "Rb": 2.20, "Sr": 1.95, "Mo": 1.54, "Ru": 1.46, "Rh": 1.42, "Pd": 1.39,
    "Ag": 1.45, "Cd": 1.44, "In": 1.42, "Sn": 1.39, "Sb": 1.39, "Te": 1.38, "I": 1.39, "Xe": 1.40,
    "Pt": 1.36, "Au": 1.36, "Hg": 1.32, "Pb": 1.46, "Bi": 1.48,
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
        v = float(value)
        if not math.isfinite(v):
            return default
        return v
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
        qc = re.sub(rf"\b{n}\b", " ", qc, flags=re.I)
    qc = re.sub(r"\s+", " ", qc).strip()

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

        # Don't silently swallow the error
        resolve_error = None
        try:
            from qcviz_mcp.tools.core import MoleculeResolver
            resolved_xyz = MoleculeResolver.resolve_with_friendly_errors(structure_query)
            if resolved_xyz:
                atom_text = _strip_xyz_header(resolved_xyz)
                if atom_text:
                    return _safe_str(structure_query), atom_text
        except Exception as e:
            resolve_error = e

        if resolve_error:
            raise ValueError(
                f"Could not resolve structure '{structure_query}': {resolve_error}"
            ) from resolve_error

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
    xc = xc_map.get(key)
    if xc is None:
        xc = key  # attempt direct PySCF xc string
        logger.warning(
            "Method '%s' is not in the predefined list; attempting to use '%s' directly with PySCF.",
            method_name, key,
        )
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
_SCF_CACHE_LOCK = threading.Lock()

def _get_cache_key(xyz: str, method: str, basis: str, charge: int, multiplicity: int) -> str:
    atom_data = _strip_xyz_header(xyz).strip()
    key_str = f"{atom_data}|{method}|{basis}|{charge}|{multiplicity}"
    return hashlib.md5(key_str.encode('utf-8')).hexdigest()

import time

def _run_scf_with_fallback(mf, warnings: Optional[List[str]] = None, cache_key: Optional[str] = None, progress_callback: Optional[Callable] = None):
    warnings = warnings if warnings is not None else []

    current_mol = getattr(mf, 'mol', None)

    if cache_key:
        with _SCF_CACHE_LOCK:
            if cache_key in _SCF_CACHE:
                cached_mf, cached_energy = _SCF_CACHE[cache_key]
                if current_mol is not None:
                    cached_mf.mol = current_mol
                if progress_callback:
                    _emit_progress(progress_callback, 0.5, "scf", "Cache hit: SCF skipped (0.0s)")
                return cached_mf, cached_energy

        disk_mf, disk_energy = load_from_disk(cache_key, mf)
        if disk_mf is not None:
            with _SCF_CACHE_LOCK:
                _SCF_CACHE[cache_key] = (disk_mf, disk_energy)
            if current_mol is not None:
                disk_mf.mol = current_mol
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
        try:
            cycle_count[0] += 1
            if progress_callback and cycle_count[0] % 2 == 0:
                c = cycle_count[0]
                max_c = getattr(mf, "max_cycle", "?")
                e = env.get("e_tot", 0.0)
                _emit_progress(progress_callback, min(0.60, 0.35 + (c / 100.0) * 0.25), "scf", f"SCF iteration {c}/{max_c} (E={e:.4f} Ha)")
        except Exception:
            pass  # never let callback errors abort SCF

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
            with _SCF_CACHE_LOCK:
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
            with _SCF_CACHE_LOCK:
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
        dens_raw = np.asarray(density_values, dtype=float).ravel()
        esp_raw = np.asarray(esp_values, dtype=float).ravel()
        if dens_raw.size == esp_raw.size:
            # finite mask on BOTH arrays simultaneously
            finite_mask = np.isfinite(dens_raw) & np.isfinite(esp_raw)
            if np.count_nonzero(finite_mask) >= 128:
                low = density_iso * 0.35
                high = density_iso * 4.0
                shell_mask = finite_mask & (dens_raw >= low) & (dens_raw <= high)
                if np.count_nonzero(shell_mask) >= 128:
                    masked = esp_raw[shell_mask]

    masked = masked[np.isfinite(masked)] if not np.all(np.isfinite(masked)) else masked
    if masked.size < 32:
        masked = arr

    abs_vals = np.abs(masked)
    p90 = float(np.percentile(abs_vals, 90))
    p95 = float(np.percentile(abs_vals, 95))
    p98 = float(np.percentile(abs_vals, 98))
    p995 = float(np.percentile(abs_vals, 99.5))
    robust = 0.55 * p95 + 0.35 * p98 + 0.10 * p995
    dynamic_upper = max(0.18, min(float(p995) * 1.2, 0.50))
    robust = float(np.clip(robust, 0.02, dynamic_upper))
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

    # Case 1: tuple (e.g., from some UHF implementations)
    if isinstance(mo_energy, tuple):
        labels = ["alpha", "beta"][:len(mo_energy)]
        return list(mo_energy), list(mo_occ), list(mo_coeff), labels

    # Case 2: list of arrays
    if isinstance(mo_energy, list) and mo_energy and isinstance(mo_energy[0], np.ndarray):
        labels = ["alpha", "beta"][:len(mo_energy)]
        return list(mo_energy), list(mo_occ), list(mo_coeff), labels

    # Case 3: numpy arrays — check dimensionality
    mo_energy = np.asarray(mo_energy)
    mo_occ = np.asarray(mo_occ)

    if mo_energy.ndim == 2 and mo_energy.shape[0] == 2:
        # Unrestricted: shape (2, nmo)
        mo_coeff_arr = np.asarray(mo_coeff)
        if mo_coeff_arr.ndim == 3 and mo_coeff_arr.shape[0] == 2:
            coeff_list = [mo_coeff_arr[0], mo_coeff_arr[1]]
        elif isinstance(mo_coeff, (tuple, list)) and len(mo_coeff) == 2:
            coeff_list = [np.asarray(mo_coeff[0]), np.asarray(mo_coeff[1])]
        else:
            # Fallback: use same coeff for both channels (shouldn't happen)
            coeff_list = [mo_coeff_arr, mo_coeff_arr]
        return [mo_energy[0], mo_energy[1]], [mo_occ[0], mo_occ[1]], coeff_list, ["alpha", "beta"]

    # Case 4: restricted (1D arrays)
    mo_coeff = np.asarray(mo_coeff)
    return [mo_energy], [mo_occ], [mo_coeff], ["restricted"]

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
    _emit_progress(progress_callback, 0.03, "resolve", "Resolving structure")
    structure_name, atom_text, mol0 = _prepare_structure_bundle(
        structure_query=structure_query,
        xyz=xyz,
        atom_spec=atom_spec,
        basis=basis,
        charge=charge,
        multiplicity=multiplicity,
    )

    # Initialize initial result for tracking warnings and initial state
    initial_result = _make_base_result(
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

    _emit_progress(progress_callback, 0.12, "build_scf", "Building initial SCF model")
    method_name, mf0 = _build_mean_field(mol0, method or DEFAULT_METHOD)

    trajectory = []

    def _geomopt_callback(envs):
        try:
            mol_current = envs.get("mol", None)
            e_current = envs.get("e_tot", None)
            grad_norm = None
            g = envs.get("gradients", envs.get("gradient", None))
            if g is not None:
                import numpy as np
                grad_norm = float(np.linalg.norm(g))

            step_num = len(trajectory) + 1
            xyz_string = _mol_to_xyz(mol_current, comment=f"Step {step_num}") if mol_current else None

            step_data = {
                "step": step_num,
                "energy_hartree": float(e_current) if e_current is not None else None,
                "grad_norm": grad_norm,
                "xyz": xyz_string,
            }
            trajectory.append(step_data)

            if progress_callback:
                frac = min(0.3 + (step_num / 50) * 0.55, 0.85)
                msg = f"Opt step {step_num}: E={e_current:.8f} Ha"
                if grad_norm:
                    msg += f", |grad|={grad_norm:.6f}"
                _emit_progress(progress_callback, frac, "optimize", msg)
        except Exception:
            pass

    _emit_progress(progress_callback, 0.30, "optimize", "Starting geometry optimization")

    opt_mol = mol0
    optimization_performed = False

    try:
        try:
            from pyscf.geomopt.geometric_solver import optimize as geometric_optimize
            _emit_progress(progress_callback, 0.35, "optimize", "Running geometry optimization (geometric)")
            opt_mol = geometric_optimize(mf0, callback=_geomopt_callback, maxsteps=kwargs.get("max_steps", 100))
            optimization_performed = True
        except (ImportError, Exception) as e:
            if isinstance(e, ImportError):
                logger.info("geometric solver not found, trying berny")
            else:
                logger.warning(f"geometric solver failed: {e}, trying berny")

            from pyscf.geomopt.berny_solver import optimize as berny_optimize
            _emit_progress(progress_callback, 0.35, "optimize", "Running geometry optimization (berny)")
            opt_mol = berny_optimize(mf0, callback=_geomopt_callback, maxsteps=kwargs.get("max_steps", 100))
            optimization_performed = True
    except Exception as exc:
        logger.warning(f"Geometry optimization failed: {exc}")
        initial_result.setdefault("warnings", []).append(f"Geometry optimization failed: {exc}")
        optimization_performed = False
        # Use initial molecule if optimization failed completely
        opt_mol = mol0

    _emit_progress(progress_callback, 0.88, "final_scf", "Running final SCF on optimized geometry")
    method_name, mf = _build_mean_field(opt_mol, method or DEFAULT_METHOD)

    # Run final SCF on optimized geometry
    new_xyz = _mol_to_xyz(opt_mol, comment=structure_name or "QCViz-MCP")
    cache_key = _get_cache_key(new_xyz, method_name, basis or DEFAULT_BASIS, charge, multiplicity)
    mf, _ = _run_scf_with_fallback(mf, initial_result["warnings"], cache_key=cache_key, progress_callback=progress_callback)

    final_result = _make_base_result(
        job_type="geometry_optimization",
        structure_name=structure_name,
        atom_text=_strip_xyz_header(_mol_to_xyz(opt_mol)),
        mol=opt_mol,
        method=method_name,
        basis=basis or DEFAULT_BASIS,
        charge=charge,
        multiplicity=multiplicity,
        advisor_focus_tab=advisor_focus_tab or "geometry",
    )
    final_result["warnings"] = _dedupe_strings(initial_result.get("warnings", []))
    final_result["optimization_performed"] = optimization_performed
    final_result["optimization_steps"] = len(trajectory)
    final_result["trajectory"] = trajectory

    if trajectory:
        frames = [step.get("xyz").strip() for step in trajectory if step.get("xyz")]
        if frames:
            final_result["trajectory_xyz"] = "\n".join(frames) + "\n"

    final_result["initial_xyz"] = initial_result["xyz"]
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

---

## 파일: `src/qcviz_mcp/compute/job_manager.py` (630줄, 20410bytes)

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

---

## 파일: `src/qcviz_mcp/compute/disk_cache.py` (112줄, 3994bytes)

```python
import os
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DIR = Path(os.getenv("QCVIZ_CACHE_DIR", "/tmp/qcviz_scf_cache"))

def init_cache():
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # 다중 사용자 환경에서 다른 사용자가 접근 못하게
        try:
            os.chmod(str(CACHE_DIR), 0o700)
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"Failed to create cache directory {CACHE_DIR}: {e}")

def save_to_disk(key: str, mf_obj, energy: float):
    init_cache()
    try:
        chkfile_path = CACHE_DIR / f"{key}.chk"

        from pyscf import lib
        import h5py
        with lib.H5FileWrap(str(chkfile_path), 'w') as fh5:
            fh5['scf/e_tot'] = energy
            if hasattr(mf_obj, 'mo_energy'): fh5['scf/mo_energy'] = mf_obj.mo_energy
            if hasattr(mf_obj, 'mo_occ'): fh5['scf/mo_occ'] = mf_obj.mo_occ
            if hasattr(mf_obj, 'mo_coeff'): fh5['scf/mo_coeff'] = mf_obj.mo_coeff
            if hasattr(mf_obj, 'converged'): fh5['scf/converged'] = mf_obj.converged

        # JSON instead of pickle for safety
        meta_path = CACHE_DIR / f"{key}.meta.json"
        with open(meta_path, 'w') as f:
            json.dump({"energy": energy, "chkfile": str(chkfile_path)}, f)

    except Exception as e:
        logger.warning(f"Failed to save SCF to disk cache: {e}")

def load_from_disk(key: str, mf_obj):
    # Check both old pickle format and new JSON format
    meta_path_json = CACHE_DIR / f"{key}.meta.json"
    meta_path_pkl = CACHE_DIR / f"{key}.meta"

    meta = None

    if meta_path_json.exists():
        try:
            with open(meta_path_json, 'r') as f:
                meta = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read JSON meta cache: {e}")
            return None, None
    elif meta_path_pkl.exists():
        # Legacy pickle format — read but don't trust blindly
        # Only accept if structure matches expected format
        try:
            import pickle
            with open(meta_path_pkl, 'rb') as f:
                raw = pickle.load(f)
            if isinstance(raw, dict) and "energy" in raw and "chkfile" in raw:
                meta = raw
                # Migrate to JSON
                try:
                    with open(meta_path_json, 'w') as f:
                        json.dump({"energy": raw["energy"], "chkfile": raw["chkfile"]}, f)
                    meta_path_pkl.unlink(missing_ok=True)
                except Exception:
                    pass
            else:
                return None, None
        except Exception as e:
            logger.warning(f"Failed to read legacy pickle meta cache: {e}")
            return None, None
    else:
        return None, None

    if meta is None:
        return None, None

    try:
        chkfile = meta.get("chkfile")
        if not chkfile or not os.path.exists(chkfile):
            return None, None

        import h5py
        import numpy as np
        with h5py.File(chkfile, 'r') as fh5:
            if 'scf/mo_energy' in fh5:
                val = fh5['scf/mo_energy'][()]
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

---

## 파일: `src/qcviz_mcp/compute/safety_guard.py` (220줄, 6214bytes)

```python
"""Safety guard for local quantum chemistry jobs."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional


MAX_ATOMS_DEFAULT = 200
TIMEOUT_MINUTES_DEFAULT = 30
MEMORY_FRACTION_LIMIT_DEFAULT = 0.80


@dataclass
class SafetyDecision:
    """Safety evaluation result."""

    allowed: bool
    atom_count: Optional[int]
    estimated_memory_mb: Optional[float]
    total_memory_mb: Optional[float]
    max_workers: int
    warnings: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert decision to dict."""
        return {
            "allowed": self.allowed,
            "atom_count": self.atom_count,
            "estimated_memory_mb": self.estimated_memory_mb,
            "total_memory_mb": self.total_memory_mb,
            "max_workers": self.max_workers,
            "warnings": list(self.warnings),
            "reasons": list(self.reasons),
        }


def _is_xyz_text(text: str) -> bool:
    lines = [line.strip() for line in (text or "").strip().splitlines() if line.strip()]
    if len(lines) < 3:
        return False
    if not lines[0].isdigit():
        return False
    atom_count = int(lines[0])
    return len(lines) >= atom_count + 2


def _is_atom_spec_line(line: str) -> bool:
    return bool(
        re.match(
            r"^\s*[A-Z][a-z]?\s+[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?\s+[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?\s+[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?\s*$",
            line or "",
        )
    )


def estimate_atom_count(query: str) -> Optional[int]:
    """Estimate atom count from XYZ or atom-spec text.

    Args:
        query: User input.

    Returns:
        Atom count if determinable, else None.
    """
    text = (query or "").strip()
    if not text:
        return None

    if _is_xyz_text(text):
        first = text.splitlines()[0].strip()
        return int(first)

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines and all(_is_atom_spec_line(line) for line in lines):
        return len(lines)

    return None


def _basis_factor(basis: str) -> float:
    """Very rough memory multiplier by basis family."""
    name = (basis or "").lower()

    if "sto-3g" in name:
        return 1.0
    if "3-21g" in name:
        return 1.4
    if "6-31g" in name:
        return 1.8
    if "svp" in name:
        return 2.4
    if "tzvp" in name:
        return 4.0
    if "qzvp" in name:
        return 7.0
    if "cc-pvdz" in name:
        return 2.8
    if "cc-pvtz" in name:
        return 5.0
    if "def2-svp" in name:
        return 2.5
    if "def2-tzvp" in name:
        return 4.2
    if "def2-qzvp" in name:
        return 7.2

    return 3.0


def estimate_memory_mb(atom_count: Optional[int], basis: str) -> Optional[float]:
    """Estimate memory usage in MB.

    This is intentionally conservative and heuristic.

    Args:
        atom_count: Number of atoms if known.
        basis: Basis set name.

    Returns:
        Estimated memory in MB, or None.
    """
    if atom_count is None:
        return None

    factor = _basis_factor(basis)
    estimate = 256.0 + (float(atom_count) ** 2) * factor * 0.35
    return round(estimate, 1)


def get_total_memory_mb() -> Optional[float]:
    """Get total physical memory in MB if detectable."""
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        phys_pages = os.sysconf("SC_PHYS_PAGES")
        total = float(page_size) * float(phys_pages) / (1024.0 * 1024.0)
        return round(total, 1)
    except Exception:
        return None


def recommended_max_workers(cpu_fraction: float = 0.5) -> int:
    """Recommend max worker count for local machine."""
    cpu_count = os.cpu_count() or 1
    workers = int(max(1, round(float(cpu_count) * float(cpu_fraction))))
    return max(1, workers)


def evaluate_request(
    query: str,
    basis: str = "def2-SVP",
    requested_timeout_minutes: int = TIMEOUT_MINUTES_DEFAULT,
    max_atoms: int = MAX_ATOMS_DEFAULT,
    memory_fraction_limit: float = MEMORY_FRACTION_LIMIT_DEFAULT,
) -> SafetyDecision:
    """Evaluate whether a local job should be allowed.

    Args:
        query: User molecular input.
        basis: Basis set name.
        requested_timeout_minutes: Requested timeout.
        max_atoms: Hard atom-count limit.
        memory_fraction_limit: Fraction of RAM allowed for estimated job size.

    Returns:
        SafetyDecision object.
    """
    warnings = []
    reasons = []

    atom_count = estimate_atom_count(query)
    estimated_mb = estimate_memory_mb(atom_count, basis)
    total_mb = get_total_memory_mb()
    max_workers = recommended_max_workers()

    allowed = True

    if atom_count is not None and atom_count > max_atoms:
        allowed = False
        reasons.append(
            "원자 수 %d개가 허용 한도 %d개를 초과합니다." % (atom_count, max_atoms)
        )

    if (
        estimated_mb is not None
        and total_mb is not None
        and estimated_mb > total_mb * float(memory_fraction_limit)
    ):
        allowed = False
        reasons.append(
            "예상 메모리 사용량 %.1f MB가 총 메모리 %.1f MB의 %.0f%%를 초과합니다."
            % (estimated_mb, total_mb, float(memory_fraction_limit) * 100.0)
        )

    if atom_count is None:
        warnings.append("입력만으로 원자 수를 추정하지 못했습니다. 계산 전 추가 검증이 필요합니다.")

    if requested_timeout_minutes > TIMEOUT_MINUTES_DEFAULT:
        warnings.append(
            "요청된 타임아웃 %d분은 기본 권장값 %d분보다 큽니다."
            % (requested_timeout_minutes, TIMEOUT_MINUTES_DEFAULT)
        )

    return SafetyDecision(
        allowed=allowed,
        atom_count=atom_count,
        estimated_memory_mb=estimated_mb,
        total_memory_mb=total_mb,
        max_workers=max_workers,
        warnings=warnings,
        reasons=reasons,
    )


def raise_if_unsafe(decision: SafetyDecision) -> None:
    """Raise ValueError if a request is unsafe."""
    if not decision.allowed:
        raise ValueError("; ".join(decision.reasons))
```

---

## 파일: `src/qcviz_mcp/web/app.py` (204줄, 6581bytes)

```python
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from qcviz_mcp.web.routes.chat import router as chat_router
from qcviz_mcp.web.routes.compute import router as compute_router

logger = logging.getLogger(__name__)


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

DEFAULT_TITLE = os.getenv("QCVIZ_APP_TITLE", "QCViz-MCP")
DEFAULT_VERSION = os.getenv("QCVIZ_APP_VERSION", "v2")
DEFAULT_CORS = os.getenv("QCVIZ_CORS_ALLOW_ORIGINS", "*")


def _now_ts() -> float:
    return time.time()


def _split_csv_env(value: str) -> List[str]:
    parts = [x.strip() for x in (value or "").split(",")]
    return [x for x in parts if x] or ["*"]


def _build_templates() -> Any:
    try:
        from fastapi.templating import Jinja2Templates
        if TEMPLATES_DIR.exists() and TEMPLATES_DIR.is_dir():
            return Jinja2Templates(directory=str(TEMPLATES_DIR))
    except Exception:
        pass
    return None


def _fallback_index_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>QCViz-MCP</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: system-ui, sans-serif; margin: 2rem; background: #0b1020; color: #e6edf3; }
    a { color: #7cc7ff; }
    code { background: rgba(255,255,255,.08); padding: .15rem .35rem; border-radius: 6px; }
    .card { max-width: 960px; padding: 1.25rem 1.5rem; border-radius: 14px; background: #11182d; }
    ul { line-height: 1.7; }
  </style>
</head>
<body>
  <div class="card">
    <h1>QCViz-MCP</h1>
    <p>The template <code>web/templates/index.html</code> was not found.</p>
    <p>Core endpoints are still live:</p>
    <ul>
      <li><a href="/health">/health</a></li>
      <li><a href="/api/health">/api/health</a></li>
      <li><a href="/chat/health">/chat/health</a></li>
      <li><a href="/api/chat/health">/api/chat/health</a></li>
      <li><a href="/compute/health">/compute/health</a></li>
      <li><a href="/api/compute/health">/api/compute/health</a></li>
      <li><code>WS /ws/chat</code></li>
      <li><code>WS /api/ws/chat</code></li>
    </ul>
  </div>
</body>
</html>
"""


def _route_table() -> Dict[str, Any]:
    return {
        "http": {
            "index": "/",
            "health": "/health",
            "chat_health": "/chat/health",
            "compute_health": "/compute/health",
            "chat_rest": "/chat",
            "compute_jobs": "/compute/jobs",
        },
        "api_alias": {
            "health": "/api/health",
            "chat_health": "/api/chat/health",
            "compute_health": "/api/compute/health",
            "chat_rest": "/api/chat",
            "compute_jobs": "/api/compute/jobs",
        },
        "websocket": {
            "chat": "/ws/chat",
            "chat_api_alias": "/api/ws/chat",
        },
        "static": {
            "root": "/static",
            "api_alias": "/api/static",
        },
    }


def create_app() -> FastAPI:
    app = FastAPI(
        title=DEFAULT_TITLE,
        version=DEFAULT_VERSION,
    )

    cors_origins = _split_csv_env(DEFAULT_CORS)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    templates = _build_templates()
    app.state.templates = templates

    if STATIC_DIR.exists() and STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
        # /api/static/* alias도 같이 제공
        app.mount("/api/static", StaticFiles(directory=str(STATIC_DIR)), name="api-static")
    else:
        logger.warning("Static directory not found: %s", STATIC_DIR)

    # 기본 라우터
    app.include_router(chat_router)
    app.include_router(compute_router)

    # /api alias 라우터
    api_router = APIRouter(prefix="/api")
    api_router.include_router(chat_router)
    api_router.include_router(compute_router)
    app.include_router(api_router)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index(request: Request):
        if templates is not None and (TEMPLATES_DIR / "index.html").exists():
            return templates.TemplateResponse("index.html", {"request": request})
        elif (TEMPLATES_DIR / "index.html").exists():
            from fastapi.responses import FileResponse
            return FileResponse(str(TEMPLATES_DIR / "index.html"))
        elif (STATIC_DIR / "index.html").exists():
            from fastapi.responses import FileResponse
            return FileResponse(str(STATIC_DIR / "index.html"))
        return HTMLResponse(_fallback_index_html())

    @app.get("/index.html", response_class=HTMLResponse, include_in_schema=False)
    async def index_html(request: Request):
        return await index(request)

    @app.get("/api", include_in_schema=False)
    @app.get("/api/", include_in_schema=False)
    async def api_root():
        return JSONResponse(
            {
                "ok": True,
                "name": DEFAULT_TITLE,
                "version": DEFAULT_VERSION,
                "timestamp": _now_ts(),
                "routes": _route_table(),
            }
        )

    @app.get("/health")
    @app.get("/api/health", include_in_schema=False)
    async def health() -> Dict[str, Any]:
        return {
            "ok": True,
            "name": DEFAULT_TITLE,
            "version": DEFAULT_VERSION,
            "timestamp": _now_ts(),
            "static_dir": str(STATIC_DIR),
            "templates_dir": str(TEMPLATES_DIR),
            "has_static": STATIC_DIR.exists(),
            "has_templates": TEMPLATES_DIR.exists(),
            "routes": _route_table(),
        }

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon_redirect():
        # favicon 없어서 404 나는 경우 잡기
        if STATIC_DIR.exists() and (STATIC_DIR / "favicon.ico").exists():
            return RedirectResponse(url="/static/favicon.ico")
        from fastapi.responses import Response
        return Response(status_code=204)

    return app


app = create_app()

__all__ = ["app", "create_app"]
```

---

## 파일: `src/qcviz_mcp/web/routes/compute.py` (1203줄, 42469bytes)

````python
from __future__ import annotations

import inspect
import json
import logging
import math
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
        v = float(value)
        if not math.isfinite(v):
            return default
        return v
    except Exception:
        return default


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    try:
        import numpy as np
        if isinstance(value, (np.integer,)):
            return int(value)
        if isinstance(value, (np.floating,)):
            v = float(value)
            return None if not math.isfinite(v) else v
        if isinstance(value, (np.bool_,)):
            return bool(value)
        if isinstance(value, np.ndarray):
            return _json_safe(value.tolist())
    except ImportError:
        pass
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
        r"(?i)(?:for|of|on|about)\s+(?:the\s+)?([a-zA-Z][a-zA-Z0-9_\-\+\(\), ]{1,40})",
        r"(?i)([a-zA-Z][a-zA-Z0-9_\-\+\(\), ]{1,40})\s+(?:molecule|structure|system)",
        r"([가-힣A-Za-z0-9_\-\+\(\), ]+?)\s*(?:의|에\s*대한)?\s*(?:homo|lumo|esp|전하|구조|에너지|최적화|분석|보여줘|해줘|계산)",
        r"([가-힣A-Za-z0-9_\-\+\(\), ]+?)\s+(?:분자|구조|이온쌍|이온)",
        r"(?i)(?:analyze|show|render|preview|compute|optimize|calculate)\s+(?:the\s+)?([a-zA-Z][a-zA-Z0-9_\-\+\(\), ]{1,40})",
    ]
    for pat in patterns:
        m = re.search(pat, message, re.IGNORECASE)
        if not m:
            continue
        candidate = _safe_str(m.group(1)).strip()

        noise = ["homo", "lumo", "esp", "map", "orbital", "orbitals", "charge", "charges", "mulliken", "partial", "geometry", "optimization", "analysis", "of", "about", "for", "보여줘", "해줘", "계산"]
        for n in noise:
            candidate = re.sub(rf"\b{n}\b", " ", candidate, flags=re.I)

        # strip korean postpositions
        for n in ["에 대한", "에대한", "이온쌍", "의", "분자", "구조", "계산", "해줘", "보여줘"]:
            if candidate.endswith(n):
                candidate = candidate[:-len(n)].strip()

        candidate = re.sub(r"\s+", " ", candidate).strip()

        if not candidate:
            continue

        candidate_norm = _normalize_text_token(candidate)
        if candidate_norm in _KO_STRUCTURE_ALIASES:
            return _KO_STRUCTURE_ALIASES[candidate_norm]
        for name in structure_names:
            if _normalize_text_token(name) == candidate_norm:
                return name
        return candidate

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


import json
import os

class InMemoryJobManager:
    def __init__(self, max_workers: int = MAX_WORKERS) -> None:
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="qcviz-job")
        self.lock = threading.RLock()
        self.jobs: Dict[str, JobRecord] = {}
        self.cache_file = os.path.join(os.getenv("QCVIZ_CACHE_DIR", "/tmp/qcviz_scf_cache"), "job_history.json")
        logger.info("JobManager initialized (ThreadPoolExecutor, max_workers=%s).", max_workers)
        self._load_from_disk()

    def _save_to_disk(self):
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                dump_data = {}
                for k, v in self.jobs.items():
                    dump_data[k] = {
                        "job_id": v.job_id,
                        "status": v.status,
                        "user_query": v.user_query,
                        "payload": v.payload,
                        "progress": v.progress,
                        "step": v.step,
                        "message": v.message,
                        "created_at": v.created_at,
                        "started_at": v.started_at,
                        "ended_at": v.ended_at,
                        "error": v.error,
                        "result": v.result,
                        "events": v.events,
                    }
                json.dump(dump_data, f)
        except Exception as e:
            logger.warning(f"Failed to save job history: {e}")

    def _load_from_disk(self):
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for k, v in data.items():
                    rec = JobRecord(job_id=v["job_id"], user_query=v["user_query"], payload=v["payload"])
                    rec.status = v["status"]
                    rec.progress = v["progress"]
                    rec.step = v["step"]
                    rec.message = v["message"]
                    rec.created_at = v["created_at"]
                    rec.started_at = v["started_at"]
                    rec.ended_at = v["ended_at"]
                    rec.error = v.get("error")
                    rec.result = v.get("result")
                    rec.events = v.get("events", [])
                    self.jobs[k] = rec
        except Exception as e:
            logger.warning(f"Failed to load job history: {e}")

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
            "job_type": job.payload.get("job_type", ""),
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
            payload_copy = dict(job.payload)

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
            result = _run_direct_compute(payload_copy, progress_callback=progress_callback)
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
            self._save_to_disk()
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
            self._save_to_disk()
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
            self._save_to_disk()

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
    items = JOB_MANAGER.list(
        include_payload=include_payload,
        include_result=include_result,
        include_events=include_events,
    )
    return {
        "items": items,
        "count": len(items),
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
]
````

---

## 파일: `src/qcviz_mcp/web/routes/chat.py` (478줄, 15800bytes)

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

            event_type = event.get("type", "")

            if event_type == "job_progress":
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
                # Do NOT send job_event separately — already sent as job_update
                continue

            if event_type in ("job_started", "job_completed"):
                await _ws_send(
                    websocket,
                    "job_update",
                    session_id=session_id,
                    job_id=job_id,
                    status="running" if event_type == "job_started" else "completed",
                    step=event_type,
                    message=event.get("message", "")
                )
                continue

            # Other event types: send as job_event
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

---

## 파일: `src/qcviz_mcp/web/advisor_flow.py` (861줄, 27913bytes)

````python
"""Advisor-tools integration layer for QCViz web chat flow.

Exact-signature adapter for qcviz_mcp.tools.advisor_tools.

This module is intentionally tuned to the real tool signatures:

- recommend_preset(atom_spec, purpose, charge, spin)
- draft_methods_section(system_name, atom_spec, functional, basis, charge, spin,
                        dispersion, software_version, optimizer, analysis_type,
                        citation_style, energy_hartree, converged, n_cycles)
- generate_script(system_name, atom_spec, functional, basis, charge, spin,
                  dispersion, optimizer, analysis_type, include_analysis)
- validate_against_literature(system_formula, functional, basis,
                              bond_lengths, bond_angles)
- score_confidence(functional, basis, converged, n_scf_cycles, max_cycles,
                   system_type, spin, s2_expected, s2_actual, validation_status)
"""

from __future__ import annotations

import importlib
import json
import logging
import re
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence

from qcviz_mcp import __version__ as QCVIZ_VERSION
try:
    from qcviz_mcp.tools.core import MoleculeResolver
except Exception:
    MoleculeResolver = None

def _get_resolver():
    if MoleculeResolver:
        return MoleculeResolver
    class _Fallback:
        @classmethod
        def resolve_with_friendly_errors(cls, q): return q
        @staticmethod
        def _is_xyz_text(t): return False
        @staticmethod
        def _is_atom_spec_text(t): return False
    return _Fallback

logger = logging.getLogger(__name__)

_MODULE_CACHE = None

_TM_3D = {
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
}
_TM_HEAVY = {
    "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd",
    "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
}
_LANTHANIDES = {
    "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb",
    "Dy", "Ho", "Er", "Tm", "Yb", "Lu",
}
_MAIN_GROUP_METALS = {
    "Li", "Be", "Na", "Mg", "Al", "K", "Ca", "Ga", "In",
    "Sn", "Tl", "Pb", "Bi", "Rb", "Sr", "Cs", "Ba",
}


# -----------------------------------------------------------------------------
# Generic helpers
# -----------------------------------------------------------------------------


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _parse_jsonish(value: Any) -> Any:
    """Parse JSON-like tool output when possible."""
    if isinstance(value, (dict, list)):
        return value

    if value is None:
        return None

    if not isinstance(value, str):
        return value

    text = value.strip()
    if not text:
        return value

    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    if text.startswith("{") or text.startswith("["):
        try:
            return json.loads(text)
        except Exception:
            return value

    return value


def _load_advisor_module():
    """Load advisor tool module once."""
    global _MODULE_CACHE
    if _MODULE_CACHE is not None:
        return _MODULE_CACHE

    _MODULE_CACHE = importlib.import_module("qcviz_mcp.tools.advisor_tools")
    return _MODULE_CACHE


def _resolve_tool_callable(obj: Any) -> Any:
    """Resolve callable from MCP-decorated object if needed."""
    if callable(obj):
        return obj

    for attr in ("fn", "func", "__wrapped__"):
        candidate = getattr(obj, attr, None)
        if callable(candidate):
            return candidate

    return obj


def _get_tool(tool_name: str):
    module = _load_advisor_module()
    if not hasattr(module, tool_name):
        raise AttributeError(f"advisor tool not found: {tool_name}")

    obj = getattr(module, tool_name)
    func = _resolve_tool_callable(obj)
    if not callable(func):
        raise TypeError(f"advisor tool is not callable: {tool_name}")

    return func


def _wrap_tool_result(tool_name: str, raw: Any) -> Dict[str, Any]:
    """Normalize raw tool output into a common result envelope."""
    parsed = _parse_jsonish(raw)

    if isinstance(parsed, dict) and parsed.get("status") == "error":
        return {
            "status": "error",
            "tool": tool_name,
            "error": parsed.get("error") or "advisor tool error",
            "data": parsed,
            "raw": raw,
        }

    return {
        "status": "success",
        "tool": tool_name,
        "data": parsed,
        "raw": raw,
    }


def _call_tool(tool_name: str, **kwargs) -> Dict[str, Any]:
    """Call one advisor tool exactly once."""
    try:
        func = _get_tool(tool_name)
        raw = func(**kwargs)
        return _wrap_tool_result(tool_name, raw)
    except Exception as exc:
        logger.exception("advisor tool %s failed", tool_name)
        return {
            "status": "error",
            "tool": tool_name,
            "error": str(exc),
            "data": None,
            "raw": None,
        }


def _call_tool_candidates(tool_name: str, candidates: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Try multiple exact-signature candidate payloads until one succeeds."""
    attempts: List[Dict[str, Any]] = []

    for idx, kwargs in enumerate(candidates):
        result = _call_tool(tool_name, **kwargs)
        attempts.append({
            "index": idx,
            "status": result.get("status"),
            "error": result.get("error"),
            "keys": sorted(kwargs.keys()),
        })
        if result.get("status") == "success":
            result["attempts"] = attempts
            result["selected_candidate_index"] = idx
            return result

    return {
        "status": "error",
        "tool": tool_name,
        "error": "all exact-signature candidates failed",
        "data": None,
        "raw": None,
        "attempts": attempts,
    }


# -----------------------------------------------------------------------------
# Structure / chemistry helpers
# -----------------------------------------------------------------------------


def _is_xyz_text(text: Optional[str]) -> bool:
    if not text:
        return False
    lines = [line.strip() for line in str(text).strip().splitlines()]
    if len(lines) < 3:
        return False
    if not lines[0].isdigit():
        return False
    atom_count = int(lines[0])
    return len([line for line in lines if line]) >= atom_count + 1


def _xyz_to_atom_spec(xyz_text: str) -> str:
    """Convert XYZ to compact atom-spec (headerless atom lines)."""
    lines = [line.rstrip() for line in str(xyz_text).strip().splitlines() if line.strip()]
    if len(lines) >= 3 and lines[0].strip().isdigit():
        return "\n".join(lines[2:]).strip()
    return str(xyz_text).strip()


def _extract_symbols_from_xyz(xyz_text: Optional[str]) -> List[str]:
    if not xyz_text:
        return []

    lines = [line.strip() for line in str(xyz_text).strip().splitlines()]
    if len(lines) < 3 or not lines[0].isdigit():
        return []

    atom_count = int(lines[0])
    if len([line for line in lines if line]) < atom_count + 1:
        return []

    symbols: List[str] = []
    for line in lines[2:2 + atom_count]:
        parts = line.split()
        if parts:
            symbols.append(parts[0])
    return symbols


def _formula_from_xyz(xyz_text: Optional[str]) -> Optional[str]:
    symbols = _extract_symbols_from_xyz(xyz_text)
    if not symbols:
        return None

    counts = Counter(symbols)
    parts: List[str] = []

    for elem in ("C", "H"):
        if elem in counts:
            n_val = counts.pop(elem)
            parts.append(elem if n_val == 1 else f"{elem}{n_val}")

    for elem in sorted(counts.keys()):
        n_val = counts[elem]
        parts.append(elem if n_val == 1 else f"{elem}{n_val}")

    return "".join(parts) if parts else None


def _display_name_from_query(query: str) -> str:
    text = (query or "").strip()
    if not text:
        return "molecule"

    resolver = _get_resolver()
    if hasattr(resolver, "_is_xyz_text") and resolver._is_xyz_text(text):
        return "molecule"
    if hasattr(resolver, "_is_atom_spec_text") and resolver._is_atom_spec_text(text):
        return "molecule"

    return text[:100]


def _intent_to_purpose(intent_name: str) -> str:
    """Map chat intent to recommend_preset purpose values."""
    name = (intent_name or "").strip().lower()

    if name == "geometry_opt":
        return "geometry_opt"
    if name == "single_point":
        return "single_point"
    if name == "esp":
        return "esp_mapping"
    if name in {"orbital", "partial_charges", "analyze"}:
        return "bonding_analysis"
    if name in {"validate", "draft_methods", "generate_script", "resolve"}:
        return "single_point"
    return "single_point"


def _intent_to_analysis_type(intent_name: str) -> str:
    """Map chat intent to methods/script analysis labels."""
    name = (intent_name or "").strip().lower()

    if name == "geometry_opt":
        return "geometry_optimization"
    if name == "partial_charges":
        return "population_analysis"
    if name == "orbital":
        return "orbital_analysis"
    if name == "esp":
        return "esp"
    if name == "validate":
        return "geometry_validation"
    if name == "draft_methods":
        return "methods_drafting"
    if name == "generate_script":
        return "script_generation"
    if name == "resolve":
        return "structure_resolution"
    return "single_point"


def _guess_dispersion(functional: Optional[str], preset_dispersion: Optional[str]) -> str:
    if preset_dispersion:
        return str(preset_dispersion)

    name = (functional or "").lower()
    if "d3" in name and "bj" in name:
        return "D3(BJ)"
    if "d3" in name:
        return "D3"
    if "d4" in name:
        return "D4"
    if "vv10" in name:
        return "VV10"
    return ""


def _normalize_bond_key(label: str) -> str:
    elems = re.findall(r"[A-Z][a-z]?", label or "")
    if len(elems) < 2:
        return label or "bond"
    elems = sorted(elems[:2])
    return f"{elems[0]}-{elems[1]}"


def _normalize_angle_key(label: str) -> str:
    elems = re.findall(r"[A-Z][a-z]?", label or "")
    if len(elems) < 3:
        return label or "angle"
    elems = elems[:3]
    return f"{elems[0]}-{elems[1]}-{elems[2]}"


def _summarize_bond_lengths(result: Dict[str, Any]) -> Dict[str, float]:
    bonds = result.get("bonds") or []
    if not isinstance(bonds, list):
        return {}

    out: Dict[str, float] = {}
    for bond in bonds:
        if not isinstance(bond, dict):
            continue

        label = str(
            bond.get("label")
            or bond.get("pair")
            or bond.get("atoms")
            or ""
        )
        key = _normalize_bond_key(label)
        dist = _safe_float(
            bond.get("distance_angstrom")
            or bond.get("length_angstrom")
            or bond.get("distance")
            or bond.get("length")
        )
        if dist is None:
            continue

        if key not in out or dist < out[key]:
            out[key] = dist

    return out


def _summarize_bond_angles(result: Dict[str, Any]) -> Dict[str, float]:
    angles = result.get("angles") or []
    if not isinstance(angles, list):
        return {}

    bucket: Dict[str, List[float]] = defaultdict(list)

    for angle in angles:
        if not isinstance(angle, dict):
            continue

        label = str(angle.get("label") or angle.get("atoms") or "")
        key = _normalize_angle_key(label)
        val = _safe_float(angle.get("angle_deg") or angle.get("angle"))
        if val is not None:
            bucket[key].append(val)

    out: Dict[str, float] = {}
    for key, values in bucket.items():
        if values:
            out[key] = sum(values) / float(len(values))
    return out


def _extract_energy_hartree(result: Dict[str, Any]) -> float:
    if "energy_hartree" in result:
        return float(result.get("energy_hartree") or 0.0)

    scf = result.get("scf") or {}
    for key in ("energy_hartree", "energy", "e_tot"):
        if key in scf:
            return float(scf.get(key) or 0.0)

    return 0.0


def _extract_converged(result: Dict[str, Any]) -> bool:
    if isinstance(result.get("converged"), bool):
        return result["converged"]

    scf = result.get("scf") or {}
    if isinstance(scf.get("converged"), bool):
        return scf["converged"]

    return True


def _extract_n_cycles(result: Dict[str, Any]) -> int:
    if "scf_cycles" in result:
        return _safe_int(result.get("scf_cycles"), 0)

    scf = result.get("scf") or {}
    for key in ("n_cycles", "cycles", "scf_cycles", "iterations"):
        if key in scf:
            return _safe_int(scf.get(key), 0)

    return 0


def _extract_max_cycles(result: Dict[str, Any]) -> int:
    if "max_cycles" in result:
        return _safe_int(result.get("max_cycles"), 200)

    scf = result.get("scf") or {}
    return _safe_int(scf.get("max_cycles"), 200)


def _extract_s2_actual(result: Dict[str, Any]) -> float:
    if "actual_s2" in result:
        return float(result.get("actual_s2") or 0.0)

    scf = result.get("scf") or {}
    for key in ("actual_s2", "s2", "<S^2>", "spin_square"):
        if key in scf:
            return float(scf.get(key) or 0.0)

    return 0.0


def _s2_expected_from_spin(spin: int) -> float:
    s_val = float(spin) / 2.0
    return s_val * (s_val + 1.0)


def _infer_system_type(result: Dict[str, Any], xyz_text: Optional[str]) -> str:
    symbols = _extract_symbols_from_xyz(xyz_text)
    charge = _safe_int(result.get("charge"), 0)
    spin = _safe_int(result.get("spin"), 0)
    atom_count = _safe_int(result.get("atom_count"), len(symbols))

    if any(sym in _LANTHANIDES for sym in symbols):
        return "lanthanide"
    if any(sym in _TM_3D for sym in symbols):
        return "3d_tm"
    if any(sym in _TM_HEAVY for sym in symbols):
        return "heavy_tm"
    if any(sym in _MAIN_GROUP_METALS for sym in symbols):
        return "main_group_metal"
    if spin > 0:
        return "radical"
    if charge != 0:
        return "charged_organic"
    if atom_count > 24:
        return "organic_large"
    return "organic_small"


def _normalize_validation_status(literature_result: Optional[Dict[str, Any]]) -> Optional[str]:
    """Convert validator overall_status to PASS/WARN/FAIL-ish status."""
    if not literature_result or literature_result.get("status") != "success":
        return None

    data = literature_result.get("data")
    if not isinstance(data, dict):
        return None

    raw = str(data.get("overall_status") or "").strip().upper()
    if not raw:
        return None

    if raw in {"PASS", "OK", "GOOD", "CONSISTENT"}:
        return "PASS"
    if raw in {"WARN", "WARNING", "PARTIAL", "MIXED"}:
        return "WARN"
    if raw in {"FAIL", "BAD", "ERROR"}:
        return "FAIL"

    return raw


# -----------------------------------------------------------------------------
# Tool output normalization
# -----------------------------------------------------------------------------


def _extract_preset_data(preset_result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not preset_result or preset_result.get("status") != "success":
        return {}

    data = preset_result.get("data")
    if not isinstance(data, dict):
        return {}

    return {
        "functional": data.get("functional"),
        "basis": data.get("basis"),
        "dispersion": data.get("dispersion"),
        "spin_treatment": data.get("spin_treatment"),
        "relativistic": data.get("relativistic"),
        "convergence": data.get("convergence"),
        "alternatives": data.get("alternatives"),
        "warnings": data.get("warnings"),
        "references": data.get("references"),
        "rationale": data.get("rationale"),
        "confidence": data.get("confidence"),
        "pyscf_settings": data.get("pyscf_settings"),
        "raw": data,
    }


# -----------------------------------------------------------------------------
# Record building
# -----------------------------------------------------------------------------


def _build_record(
    query: str,
    intent_name: str,
    result: Dict[str, Any],
    preset_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    xyz_text = result.get("xyz") or (preset_bundle or {}).get("resolved_xyz")
    compact_atom_spec = _xyz_to_atom_spec(xyz_text) if xyz_text else ""
    formula = result.get("formula") or _formula_from_xyz(xyz_text)
    preset_data = _extract_preset_data((preset_bundle or {}).get("preset"))

    functional = result.get("method") or preset_data.get("functional") or "B3LYP"
    basis = result.get("basis") or preset_data.get("basis") or "def2-SVP"
    dispersion = (
        result.get("dispersion")
        or preset_data.get("dispersion")
        or _guess_dispersion(functional, preset_data.get("dispersion"))
    )

    return {
        "query": query,
        "intent": intent_name,
        "purpose": _intent_to_purpose(intent_name),
        "analysis_type": _intent_to_analysis_type(intent_name),
        "system_name": result.get("display_name") or formula or _display_name_from_query(query),
        "formula": formula,
        "xyz_text": xyz_text,
        "atom_spec_compact": compact_atom_spec,
        "functional": functional,
        "basis": basis,
        "dispersion": dispersion,
        "charge": _safe_int(result.get("charge"), 0),
        "spin": _safe_int(result.get("spin"), 0),
        "software": "PySCF",
        "software_version": str(result.get("software_version") or f"QCViz-MCP {QCVIZ_VERSION}"),
        "optimizer": str(result.get("optimizer") or ("geomeTRIC" if intent_name == "geometry_opt" else "")),
        "energy_hartree": _extract_energy_hartree(result),
        "converged": _extract_converged(result),
        "n_cycles": _extract_n_cycles(result),
        "max_cycles": _extract_max_cycles(result),
        "s2_expected": _s2_expected_from_spin(_safe_int(result.get("spin"), 0)),
        "s2_actual": _extract_s2_actual(result),
        "system_type": _infer_system_type(result, xyz_text),
        "job_type": result.get("job_type"),
        "atom_count": _safe_int(result.get("atom_count"), 0),
    }


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def prepare_advisor_plan(
    query: str,
    intent_name: str,
    charge: int = 0,
    spin: int = 0,
) -> Dict[str, Any]:
    """Resolve geometry and run exact-signature recommend_preset."""
    out: Dict[str, Any] = {
        "status": "success",
        "purpose": _intent_to_purpose(intent_name),
        "resolved_xyz": None,
        "resolved_atom_spec": None,
        "preset": None,
        "applied_functional": None,
        "applied_basis": None,
        "warnings": [],
    }

    try:
        resolver = _get_resolver()
        xyz = resolver.resolve_with_friendly_errors(query)
        out["resolved_xyz"] = xyz
        out["resolved_atom_spec"] = _xyz_to_atom_spec(xyz)
    except Exception as exc:
        out["status"] = "error"
        out["warnings"].append(f"구조 사전 해석 실패: {exc}")
        return out

    # There is ambiguity in the codebase: the parameter is named atom_spec,
    # but docstrings mention XYZ format. We therefore try both compact atom-spec
    # and full XYZ, using the exact same signature each time.
    preset_candidates = [
        {
            "atom_spec": out["resolved_atom_spec"],
            "purpose": out["purpose"],
            "charge": int(charge),
            "spin": int(spin),
        },
        {
            "atom_spec": out["resolved_xyz"],
            "purpose": out["purpose"],
            "charge": int(charge),
            "spin": int(spin),
        },
    ]

    preset = _call_tool_candidates("recommend_preset", preset_candidates)
    out["preset"] = preset

    norm = _extract_preset_data(preset)
    out["applied_functional"] = norm.get("functional")
    out["applied_basis"] = norm.get("basis")

    if preset.get("status") != "success":
        out["warnings"].append(
            f"advisor preset 실패: {preset.get('error', 'unknown error')}"
        )
    if not out["applied_functional"]:
        out["warnings"].append("advisor preset에서 functional을 추출하지 못했습니다.")
    if not out["applied_basis"]:
        out["warnings"].append("advisor preset에서 basis를 추출하지 못했습니다.")

    return out


def apply_preset_to_runner_kwargs(
    runner_kwargs: Dict[str, Any],
    advisor_plan: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Apply advisor preset into compute runner kwargs."""
    merged = dict(runner_kwargs or {})
    if not advisor_plan:
        return merged

    functional = advisor_plan.get("applied_functional")
    basis = advisor_plan.get("applied_basis")

    if functional and not merged.get("_method_user_supplied", False):
        merged["method"] = functional
    if basis and not merged.get("_basis_user_supplied", False):
        merged["basis"] = basis

    return merged


def enrich_result_with_advisor(
    query: str,
    intent_name: str,
    result: Dict[str, Any],
    preset_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run exact-signature postcompute advisor enrichment."""
    advisor: Dict[str, Any] = {
        "status": "success",
        "preset": None,
        "methods": None,
        "script": None,
        "literature": None,
        "confidence": None,
        "record": None,
    }

    if preset_bundle:
        advisor["preset"] = preset_bundle.get("preset")
    else:
        advisor["preset"] = prepare_advisor_plan(
            query=query,
            intent_name=intent_name,
            charge=_safe_int(result.get("charge"), 0),
            spin=_safe_int(result.get("spin"), 0),
        ).get("preset")

    record = _build_record(
        query=query,
        intent_name=intent_name,
        result=result,
        preset_bundle=preset_bundle,
    )
    advisor["record"] = record

    # -----------------------------------------------------------------
    # draft_methods_section
    # Exact signature:
    #   system_name, atom_spec, functional, basis, charge, spin,
    #   dispersion, software_version, optimizer, analysis_type,
    #   citation_style, energy_hartree, converged, n_cycles
    # -----------------------------------------------------------------
    methods_candidates = []
    for atom_spec_candidate in filter(None, [record["xyz_text"], record["atom_spec_compact"]]):
        methods_candidates.append({
            "system_name": record["system_name"],
            "atom_spec": atom_spec_candidate,
            "functional": record["functional"],
            "basis": record["basis"],
            "charge": int(record["charge"]),
            "spin": int(record["spin"]),
            "dispersion": record["dispersion"],
            "software_version": record["software_version"],
            "optimizer": record["optimizer"],
            "analysis_type": record["analysis_type"],
            "citation_style": "acs",
            "energy_hartree": float(record["energy_hartree"]),
            "converged": bool(record["converged"]),
            "n_cycles": int(record["n_cycles"]),
        })
    advisor["methods"] = _call_tool_candidates("draft_methods_section", methods_candidates)

    # -----------------------------------------------------------------
    # generate_script
    # Exact signature:
    #   system_name, atom_spec, functional, basis, charge, spin,
    #   dispersion, optimizer, analysis_type, include_analysis
    # -----------------------------------------------------------------
    script_candidates = []
    for atom_spec_candidate in filter(None, [record["xyz_text"], record["atom_spec_compact"]]):
        script_candidates.append({
            "system_name": record["system_name"],
            "atom_spec": atom_spec_candidate,
            "functional": record["functional"],
            "basis": record["basis"],
            "charge": int(record["charge"]),
            "spin": int(record["spin"]),
            "dispersion": record["dispersion"],
            "optimizer": record["optimizer"],
            "analysis_type": record["analysis_type"],
            "include_analysis": True,
        })
    advisor["script"] = _call_tool_candidates("generate_script", script_candidates)

    # -----------------------------------------------------------------
    # validate_against_literature
    # Exact signature:
    #   system_formula, functional, basis, bond_lengths, bond_angles
    # -----------------------------------------------------------------
    bond_lengths = _summarize_bond_lengths(result)
    bond_angles = _summarize_bond_angles(result)

    if record["formula"] and (bond_lengths or bond_angles):
        advisor["literature"] = _call_tool(
            "validate_against_literature",
            system_formula=record["formula"],
            functional=record["functional"],
            basis=record["basis"],
            bond_lengths=bond_lengths or None,
            bond_angles=bond_angles or None,
        )
    else:
        advisor["literature"] = {
            "status": "skipped",
            "tool": "validate_against_literature",
            "error": "formula 또는 geometry 요약 정보가 부족하여 문헌 검증을 생략했습니다.",
            "data": None,
            "raw": None,
        }

    # -----------------------------------------------------------------
    # score_confidence
    # Exact signature:
    #   functional, basis, converged, n_scf_cycles, max_cycles,
    #   system_type, spin, s2_expected, s2_actual, validation_status
    # -----------------------------------------------------------------
    validation_status = _normalize_validation_status(advisor["literature"])
    advisor["confidence"] = _call_tool(
        "score_confidence",
        functional=record["functional"],
        basis=record["basis"],
        converged=bool(record["converged"]),
        n_scf_cycles=int(record["n_cycles"]),
        max_cycles=int(record["max_cycles"]),
        system_type=record["system_type"],
        spin=int(record["spin"]),
        s2_expected=float(record["s2_expected"]),
        s2_actual=float(record["s2_actual"]),
        validation_status=validation_status,
    )

    advisor["meta"] = {
        "query": query,
        "intent_name": intent_name,
        "system_name": record["system_name"],
        "formula": record["formula"],
        "purpose": record["purpose"],
        "analysis_type": record["analysis_type"],
        "functional": record["functional"],
        "basis": record["basis"],
        "dispersion": record["dispersion"],
        "charge": record["charge"],
        "spin": record["spin"],
        "software_version": record["software_version"],
        "optimizer": record["optimizer"],
        "energy_hartree": record["energy_hartree"],
        "converged": record["converged"],
        "n_cycles": record["n_cycles"],
        "max_cycles": record["max_cycles"],
        "system_type": record["system_type"],
        "s2_expected": record["s2_expected"],
        "s2_actual": record["s2_actual"],
        "bond_length_keys": sorted(list(bond_lengths.keys())),
        "bond_angle_keys": sorted(list(bond_angles.keys())),
        "validation_status_normalized": validation_status,
    }

    return advisor
````

---

## 파일: `src/qcviz_mcp/web/static/chat.js` (658줄, 24948bytes)

```javascript
function stringifyError(val) {
  if (val == null) return "";
  if (typeof val === "string") return val;
  if (val instanceof Error) return val.message || String(val);
  if (typeof val === "object") {
    if (typeof val.message === "string") return val.message;
    if (typeof val.error === "string") return val.error;
    if (typeof val.detail === "string") return val.detail;
    if (typeof val.error === "object") return stringifyError(val.error);
    if (typeof val.detail === "object") return stringifyError(val.detail);
    try {
      return JSON.stringify(val, null, 2);
    } catch (_) {
      return String(val);
    }
  }
  return String(val);
}

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
    return new Date().toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function scrollToBottom() {
    requestAnimationFrame(function () {
      if ($scroll) $scroll.scrollTop = $scroll.scrollHeight;
    });
  }

  function setWsUI(connected) {
    state.wsConnected = connected;
    if ($wsDot) $wsDot.setAttribute("data-connected", String(connected));
    if ($wsLabel)
      $wsLabel.textContent = connected ? "Connected" : "Disconnected";
  }

  function setSending(v) {
    state.sending = v;
    if ($send) $send.disabled = v || !($input && $input.value.trim());
  }

  function escHtml(s) {
    if (s == null) return "";
    if (typeof s === "object") {
      try {
        s = JSON.stringify(s, null, 2);
      } catch (_) {
        s = String(s);
      }
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
      var keys = [
        "message",
        "text",
        "content",
        "detail",
        "reason",
        "error",
        "description",
        "response",
        "answer",
        "reply",
      ];
      for (var i = 0; i < keys.length; i++) {
        if (obj[keys[i]] != null) {
          var v = extractReadableText(obj[keys[i]]);
          if (v) return v;
        }
      }
      try {
        return JSON.stringify(obj, null, 2);
      } catch (_) {
        return "[data]";
      }
    }
    return String(obj);
  }

  function extractTextFromMsg(msg) {
    var keys = [
      "text",
      "content",
      "message",
      "response",
      "answer",
      "reply",
      "detail",
    ];
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
      avatar.innerHTML =
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/></svg>';
    } else if (role === "error") {
      avatar.innerHTML =
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>';
    }

    var body = document.createElement("div");
    body.className = "chat-msg__body";

    var meta = document.createElement("div");
    meta.className = "chat-msg__meta";

    var nameEl = document.createElement("span");
    nameEl.className = "chat-msg__name";
    nameEl.textContent =
      role === "user" ? "You" : role === "error" ? "Error" : "QCViz";

    var timeEl = document.createElement("span");
    timeEl.className = "chat-msg__time";
    timeEl.textContent = now();

    meta.appendChild(nameEl);
    meta.appendChild(timeEl);
    body.appendChild(meta);

    var safeHtml = opts.html
      ? typeof opts.html === "object"
        ? escHtml(opts.html)
        : opts.html
      : null;
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
    div.innerHTML =
      '<div class="chat-msg__avatar chat-msg__avatar--assistant"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/></svg></div><div class="chat-msg__body"><div class="chat-typing"><span class="chat-typing__dot"></span><span class="chat-typing__dot"></span><span class="chat-typing__dot"></span></div></div>';
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
        var existingActive = stepsEl.querySelector(
          ".chat-progress__step--active",
        );
        if (existingActive && status !== "error") {
          existingActive.className =
            "chat-progress__step chat-progress__step--done";
          existingActive.innerHTML =
            '<span class="chat-progress__icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span><span>' +
            escHtml(existingActive.dataset.label || "") +
            "</span>";
        }

        while (stepsEl.children.length > 6) {
          stepsEl.removeChild(stepsEl.firstChild);
        }

        var step = document.createElement("div");
        step.className =
          "chat-progress__step chat-progress__step--" + (status || "active");
        step.dataset.label = label;
        var icon;
        if (status === "done")
          icon =
            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>';
        else if (status === "error")
          icon =
            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
        else
          icon =
            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3" fill="currentColor"><animate attributeName="opacity" values="1;0.3;1" dur="1.2s" repeatCount="indefinite"/></circle></svg>';
        step.innerHTML =
          '<span class="chat-progress__icon">' +
          icon +
          "</span><span>" +
          escHtml(label) +
          "</span>";
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
          active.innerHTML =
            '<span class="chat-progress__icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></span><span>' +
            escHtml(active.dataset.label || "") +
            "</span>";
        }
      },
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
    // Clear old handlers to prevent ghost callbacks
    if (state.ws) {
      if (
        state.ws.readyState === WebSocket.OPEN ||
        state.ws.readyState === WebSocket.CONNECTING
      )
        return;
      state.ws.onopen = null;
      state.ws.onclose = null;
      state.ws.onerror = null;
      state.ws.onmessage = null;
      state.ws = null;
    }

    try {
      state.ws = new WebSocket(buildWsUrl());
    } catch (e) {
      setWsUI(false);
      scheduleReconnect();
      return;
    }

    state.ws.onopen = function () {
      // Verify this is still the active WS
      if (this !== state.ws) return;
      setWsUI(true);
      state.reconnectAttempts = 0;
      console.log(
        "%c[WS] Connected",
        "background:#22c55e;color:white;padding:2px 6px;border-radius:3px;",
      );
    };

    state.ws.onclose = function () {
      if (this !== state.ws) return;
      setWsUI(false);
      scheduleReconnect();
    };

    state.ws.onerror = function () {
      if (this !== state.ws) return;
      setWsUI(false);
    };

    state.ws.onmessage = function (event) {
      if (this !== state.ws) return;
      var data;
      try {
        data = JSON.parse(event.data);
      } catch (_) {
        return;
      }
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
    var type = (msg.type || msg.event || msg.action || msg.kind || "")
      .toLowerCase()
      .trim();
    var jobId = msg.job_id || msg.jobId || msg.id || null;
    var status = (msg.status || msg.state || "").toLowerCase();
    var textContent = extractTextFromMsg(msg);

    switch (type) {
      case "ready":
      case "ack":
      case "hello":
      case "connected":
      case "pong":
        break;

      case "assistant":
      case "response":
      case "answer":
      case "reply":
      case "chat_response":
      case "chat_reply":
        removeTypingIndicator();
        if (!textContent) break;
        if (state.activeAssistantEl) {
          state.streamBuffer += "\n" + textContent;
          state.activeAssistantEl.text.innerHTML = formatMarkdown(
            state.streamBuffer,
          );
        } else {
          state.streamBuffer = textContent;
          state.activeAssistantEl = createMsgEl("assistant", {
            html: formatMarkdown(textContent),
          });
        }
        scrollToBottom();
        state.activeAssistantEl = null;
        state.streamBuffer = "";
        setSending(false);
        break;

      case "assistant_start":
      case "stream_start":
        removeTypingIndicator();
        state.streamBuffer = "";
        state.activeAssistantEl = createMsgEl("assistant", { text: "" });
        break;

      case "assistant_chunk":
      case "stream":
      case "chunk":
      case "delta":
      case "token":
        var chunk = textContent || msg.chunk || msg.delta || msg.token || "";
        if (!chunk) break;
        if (!state.activeAssistantEl) {
          removeTypingIndicator();
          state.activeAssistantEl = createMsgEl("assistant", { text: "" });
        }
        state.streamBuffer += chunk;
        state.activeAssistantEl.text.innerHTML = formatMarkdown(
          state.streamBuffer,
        );
        scrollToBottom();
        break;

      case "assistant_end":
      case "stream_end":
      case "done":
        state.activeAssistantEl = null;
        state.streamBuffer = "";
        setSending(false);
        break;

      case "job_submitted":
      case "submitted":
      case "queued":
      case "job_created":
      case "job_queued":
        var jid = jobId || state.activeJobId;
        var jobSnap = msg.job || {};
        if (!jid && jobSnap.job_id) jid = jobSnap.job_id;
        if (!jid) break;
        state.activeJobId = jid;
        App.upsertJob({
          job_id: jid,
          status: "queued",
          submitted_at: Date.now() / 1000,
          updated_at: Date.now() / 1000,
          user_query: state.lastUserInput,
          molecule_name:
            jobSnap.molecule_name ||
            msg.molecule_name ||
            msg.molecule ||
            (msg.payload ? msg.payload.molecule : "") ||
            "",
          method:
            jobSnap.method ||
            msg.method ||
            (msg.payload ? msg.payload.method : "") ||
            "",
          basis_set:
            jobSnap.basis_set ||
            jobSnap.basis ||
            msg.basis_set ||
            msg.basis ||
            (msg.payload ? msg.payload.basis_set || msg.payload.basis : "") ||
            "",
        });
        App.setStatus("Job submitted", "running", "chat");
        var prog = ensureProgressUI();
        prog.addStep("Job submitted", "done");
        break;

      case "job_update":
      case "job_event":
      case "job_progress":
      case "progress":
      case "status":
      case "step":
      case "stage":
      case "computing":
      case "running":
        var jid2 = jobId || state.activeJobId;
        var progress =
          msg.progress != null
            ? msg.progress
            : msg.percent != null
              ? msg.percent
              : msg.pct != null
                ? msg.pct
                : null;
        var msgText = msg.message || textContent || "";
        var stepKey = msg.step || msg.stage || "";
        var detailText = msg.detail || msg.description || "";
        var combinedLabel = stepKey
          ? "[" + stepKey + "] " + (msgText || detailText || "Processing...")
          : msgText || detailText || "Computing...";

        if (jid2) {
          App.upsertJob({
            job_id: jid2,
            status: status || "running",
            updated_at: Date.now() / 1000,
            progress: progress,
          });
        }

        var prog2 = ensureProgressUI();
        if (combinedLabel) {
          var stepStatus =
            status === "failed" || status === "error"
              ? "error"
              : status === "completed" || status === "done"
                ? "done"
                : "active";
          prog2.addStep(combinedLabel, stepStatus);
        }
        if (typeof progress === "number") {
          // Backend sends progress as 0~1; UI expects 0~100
          var pct =
            progress <= 1.0 && progress >= 0 ? progress * 100 : progress;
          prog2.setProgress(pct);
        }

        App.setStatus(combinedLabel || "Computing...", "running", "chat");
        break;

      case "result":
        removeTypingIndicator();
        var rjid = jobId || state.activeJobId;
        var result =
          msg.result ||
          msg.results ||
          msg.data ||
          msg.output ||
          msg.computation ||
          null;
        if (result && rjid) {
          App.upsertJob({
            job_id: rjid,
            status: "completed",
            result: result,
            updated_at: Date.now() / 1000,
            user_query:
              state.lastUserInput ||
              (App.store.jobsById[rjid]
                ? App.store.jobsById[rjid].user_query
                : ""),
            molecule_name:
              result.structure_name ||
              result.molecule_name ||
              result.molecule ||
              "",
            method: result.method || "",
            basis_set: result.basis || result.basis_set || "",
          });
          App.setActiveResult(result, { jobId: rjid, source: "chat" });
          App.setStatus("Completed", "success", "chat");

          var energy =
            result.total_energy_hartree != null
              ? result.total_energy_hartree
              : result.energy;
          if (energy != null) {
            var summary =
              "Computation complete. Total energy: " +
              Number(energy).toFixed(8) +
              " Hartree";
            if (result.molecule_name)
              summary = result.molecule_name + " \u2014 " + summary;
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

      case "error":
      case "fail":
      case "failed":
      case "job_failed":
      case "job_error":
        removeTypingIndicator();
        var errMsg = "An error occurred";
        var cands = [
          msg.message,
          msg.error,
          msg.text,
          msg.detail,
          msg.reason,
          msg.description,
        ];
        for (var ci = 0; ci < cands.length; ci++) {
          var c = cands[ci];
          if (typeof c === "string" && c.length > 0) {
            errMsg = c;
            break;
          }
        }
        if (errMsg === "An error occurred") {
          for (var ci2 = 0; ci2 < cands.length; ci2++) {
            if (cands[ci2] && typeof cands[ci2] === "object") {
              var nested = extractReadableText(cands[ci2]);
              if (
                nested &&
                nested !== "An error occurred" &&
                nested !== "[data]"
              ) {
                errMsg = nested;
                break;
              }
            }
          }
        }
        /* 파이프 구분자 처리 (백엔드가 "msg|detail" 형태로 보내는 경우) */
        if (errMsg.indexOf("|") !== -1) {
          errMsg = errMsg
            .split("|")
            .map(function (s) {
              return s.trim();
            })
            .filter(Boolean)
            .join(" — ");
        }

        createMsgEl("error", { text: errMsg });

        if (state.activeProgressEl) {
          state.activeProgressEl.addStep(errMsg, "error");
          state.activeProgressEl.fill.style.background = "var(--error)";
          state.activeProgressEl.fill.classList.remove(
            "chat-progress__fill--indeterminate",
          );
          state.activeProgressEl.fill.style.width = "100%";
          state.activeProgressEl = null;
        }

        var errJid = jobId || state.activeJobId;
        if (errJid)
          App.upsertJob({
            job_id: errJid,
            status: "failed",
            updated_at: Date.now() / 1000,
          });
        App.setStatus("Error", "error", "chat");
        state.activeAssistantEl = null;
        setSending(false);
        break;

      default:
        /* Auto-detect */
        if (
          msg.result ||
          msg.results ||
          (msg.data && msg.data.total_energy_hartree)
        ) {
          handleServerEvent(Object.assign({}, msg, { type: "result" }));
          return;
        }
        if (
          status === "completed" ||
          status === "done" ||
          status === "finished"
        ) {
          handleServerEvent(Object.assign({}, msg, { type: "result" }));
          return;
        }
        if (
          status === "running" ||
          status === "computing" ||
          status === "processing"
        ) {
          handleServerEvent(Object.assign({}, msg, { type: "job_update" }));
          return;
        }
        if (status === "queued" || status === "submitted") {
          handleServerEvent(Object.assign({}, msg, { type: "job_submitted" }));
          return;
        }
        if (status === "failed" || status === "error") {
          handleServerEvent(Object.assign({}, msg, { type: "error" }));
          return;
        }
        if (jobId && (msg.progress != null || msg.step || msg.stage)) {
          handleServerEvent(Object.assign({}, msg, { type: "job_update" }));
          return;
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
        else if (data.result)
          handleServerEvent(Object.assign({ type: "result" }, data));
        else {
          var t = extractTextFromMsg(data);
          handleServerEvent({
            type: "assistant",
            text: t || JSON.stringify(data, null, 2),
          });
        }
      })
      .catch(function (err) {
        handleServerEvent({
          type: "error",
          message: "Request failed: " + err.message,
        });
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
    getState: function () {
      return Object.assign({}, state, { ws: undefined });
    },
  };
})();
```

---

## 파일: `src/qcviz_mcp/web/static/viewer.js` (837줄, 32030bytes)

```javascript
/* ═══════════════════════════════════════════
   QCViz-MCP Enterprise v5 — 3D Viewer Module
   (Complete Rewrite: Unified Rendering Pipeline)
   ════───────────────────────────────────── */
(function () {
  "use strict";

  var App = window.QCVizApp;
  if (!App) return;

  /* ─────────────────────────────────────────
     STATE
     ───────────────────────────────────────── */
  var state = {
    ready: false,
    viewer: null,
    model: null,
    mode: "none", // none | molecule | orbital | esp
    style: "stick",
    isovalue: 0.03,
    opacity: 0.75,
    espDensityIso: 0.001,
    colorScheme: "classic",
    showLabels: true,
    result: null,
    jobId: null,
    selectedOrbitalIndex: null,
    // Trajectory
    trajectoryFrames: [],
    trajectoryPlaying: false,
    trajectoryFrame: 0,
    trajectoryTimer: null,
  };

  /* ─────────────────────────────────────────
     DOM REFS — collected once in init()
     FIX #6: 이벤트 바인딩은 init()에서 한 번만
     ───────────────────────────────────────── */
  var dom = {};

  function collectDom() {
    dom.$viewerDiv = document.getElementById("viewer3d");
    dom.$empty = document.getElementById("viewerEmpty");
    dom.$controls = document.getElementById("viewerControls");
    dom.$legend = document.getElementById("viewerLegend");
    dom.$btnReset = document.getElementById("btnViewerReset");
    dom.$btnScreenshot = document.getElementById("btnViewerScreenshot");
    dom.$btnFullscreen = document.getElementById("btnViewerFullscreen");
    dom.$segStyle = document.getElementById("segStyle");
    dom.$grpOrbital = document.getElementById("grpOrbital");
    dom.$grpOpacity = document.getElementById("grpOpacity");
    dom.$grpOrbitalSelect = document.getElementById("grpOrbitalSelect");
    dom.$selectOrbital = document.getElementById("selectOrbital");
    dom.$sliderIso = document.getElementById("sliderIsovalue");
    dom.$lblIso = document.getElementById("lblIsovalue");
    dom.$sliderOp = document.getElementById("sliderOpacity");
    dom.$lblOp = document.getElementById("lblOpacity");
    dom.$btnLabels = document.getElementById("btnToggleLabels");
    dom.$btnModeOrbital = document.getElementById("btnModeOrbital");
    dom.$btnModeESP = document.getElementById("btnModeESP");
    dom.$vizModeToggle = document.getElementById("vizModeToggle");
    dom.$grpESP = document.getElementById("grpESP");
    dom.$selectColor = document.getElementById("selectColorScheme");
    dom.$sliderEspDensIso = document.getElementById("sliderEspDensIso");
    dom.$lblEspDensIso = document.getElementById("lblEspDensIso");
  }

  /* ─────────────────────────────────────────
     3Dmol LOADER
     ───────────────────────────────────────── */
  var _loadPromise = null;
  function load3Dmol() {
    if (window.$3Dmol) return Promise.resolve();
    if (_loadPromise) return _loadPromise;
    _loadPromise = new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = "https://3dmol.csb.pitt.edu/build/3Dmol-min.js";
      s.onload = resolve;
      s.onerror = function () {
        _loadPromise = null; // allow retry on next call
        reject(new Error("3Dmol.js load failed"));
      };
      document.head.appendChild(s);
    });
    return _loadPromise;
  }

  function ensureViewer() {
    if (state.viewer && state.ready) return Promise.resolve(state.viewer);
    return load3Dmol()
      .then(function () {
        if (!state.viewer && dom.$viewerDiv) {
          var isDark =
            document.documentElement.getAttribute("data-theme") === "dark";
          state.viewer = window.$3Dmol.createViewer(dom.$viewerDiv, {
            backgroundColor: isDark ? "black" : "white",
            antialias: true,
          });
          try {
            var canvas = dom.$viewerDiv.querySelector("canvas");
            if (canvas) canvas.style.backgroundColor = "transparent";
          } catch (_) {}
          state.ready = true;
          updateViewerBg();
        }
        return state.viewer;
      })
      .catch(function (err) {
        if (dom.$empty) {
          dom.$empty.hidden = false;
          var t = dom.$empty.querySelector(".viewer-empty__text");
          if (t)
            t.textContent =
              "Failed to load 3Dmol.js — check your network connection.";
        }
        throw err;
      });
  }

  function updateViewerBg() {
    if (!state.viewer) return;
    var isDark = document.documentElement.getAttribute("data-theme") === "dark";
    state.viewer.setBackgroundColor(isDark ? 0x0c0c0f : 0xfafafa, 1.0);
  }

  /* ─────────────────────────────────────────
     COLOR SCHEMES
     ───────────────────────────────────────── */
  var COLOR_SCHEMES = {
    classic: {
      label: "Classic (Blue/Red)",
      orbPositive: "#3b82f6",
      orbNegative: "#ef4444",
      espGradient: "rwb",
      reverse: false,
    },
    jmol: {
      label: "Jmol",
      orbPositive: "#1e40af",
      orbNegative: "#dc2626",
      espGradient: "rwb",
      reverse: false,
    },
    rwb: {
      label: "RWB (Red-White-Blue)",
      orbPositive: "#2563eb",
      orbNegative: "#dc2626",
      espGradient: "rwb",
      reverse: false,
    },
    bwr: {
      label: "BWR (Blue-White-Red)",
      orbPositive: "#dc2626",
      orbNegative: "#2563eb",
      espGradient: "rwb",
      reverse: true,
    },
    spectral: {
      label: "Spectral",
      orbPositive: "#2b83ba",
      orbNegative: "#d7191c",
      espGradient: "sinebow",
      reverse: false,
    },
    viridis: {
      label: "Viridis",
      orbPositive: "#21918c",
      orbNegative: "#fde725",
      espGradient: "roygb",
      reverse: false,
    },
    inferno: {
      label: "Inferno",
      orbPositive: "#fcffa4",
      orbNegative: "#420a68",
      espGradient: "roygb",
      reverse: false,
    },
    coolwarm: {
      label: "Cool-Warm",
      orbPositive: "#4575b4",
      orbNegative: "#d73027",
      espGradient: "rwb",
      reverse: false,
    },
    purplegreen: {
      label: "Purple-Green",
      orbPositive: "#1b7837",
      orbNegative: "#762a83",
      espGradient: "rwb",
      reverse: false,
    },
    greyscale: {
      label: "Greyscale",
      orbPositive: "#f0f0f0",
      orbNegative: "#404040",
      espGradient: "rwb",
      reverse: false,
    },
  };

  function getScheme() {
    return COLOR_SCHEMES[state.colorScheme] || COLOR_SCHEMES.classic;
  }

  function createGradient(type, min, max) {
    if (!window.$3Dmol) return null;
    var G = window.$3Dmol.Gradient;
    if (type === "sinebow" && G.Sinebow) return new G.Sinebow(min, max);
    if (type === "roygb" && G.ROYGB) return new G.ROYGB(min, max);
    return new G.RWB(min, max);
  }

  function updateSchemePreview() {
    var scheme = getScheme();
    var $preview = document.getElementById("schemePreview");
    if (!$preview) return;
    var $pos = $preview.querySelector(".swatch-pos");
    var $neg = $preview.querySelector(".swatch-neg");
    if ($pos) $pos.style.backgroundColor = scheme.orbPositive;
    if ($neg) $neg.style.backgroundColor = scheme.orbNegative;
  }

  /* ─────────────────────────────────────────
     HELPERS
     ───────────────────────────────────────── */
  function dismissLoader() {
    var $loader = document.getElementById("appLoader");
    if (!$loader) return;
    $loader.classList.add("fade-out");
    setTimeout(function () {
      if ($loader.parentNode) $loader.parentNode.removeChild($loader);
    }, 600);
  }

  function buildXyzFromAtoms(atoms) {
    if (!atoms || !atoms.length) return null;
    var lines = [String(atoms.length), "QCViz"];
    atoms.forEach(function (a) {
      var el = a.element || a.symbol || a[0] || "X";
      var x = Number(a.x != null ? a.x : a[1] || 0).toFixed(6);
      var y = Number(a.y != null ? a.y : a[2] || 0).toFixed(6);
      var z = Number(a.z != null ? a.z : a[3] || 0).toFixed(6);
      lines.push(el + " " + x + " " + y + " " + z);
    });
    return lines.join("\n");
  }

  function getXyz(result) {
    if (!result) return null;
    var viz = result.visualization || {};
    return (
      viz.xyz ||
      viz.molecule_xyz ||
      viz.xyz_block ||
      result.xyz_block ||
      result.xyz ||
      null ||
      (result.atoms && result.atoms.length
        ? buildXyzFromAtoms(result.atoms)
        : null)
    );
  }

  function findCubeB64(result, type) {
    var viz = result.visualization || {};
    var key = type + "_cube_b64";
    return viz[key] || result[key] || (viz[type] && viz[type].cube_b64) || null;
  }

  function safeAtob(b64) {
    if (!b64) return null;
    try {
      return atob(b64);
    } catch (e) {
      console.error("[Viewer] atob failed:", e);
      return null;
    }
  }

  function applyStyle(viewer, style) {
    var styles = {
      stick: {
        stick: { radius: 0.14, colorscheme: "Jmol" },
        sphere: { scale: 0.25, colorscheme: "Jmol" },
      },
      sphere: { sphere: { scale: 0.6, colorscheme: "Jmol" } },
      line: { line: { colorscheme: "Jmol" } },
    };
    viewer.setStyle({}, styles[style] || styles.stick);
  }

  /* ─────────────────────────────────────────
     LABELS
     ───────────────────────────────────────── */
  function addLabels(viewer, result) {
    var atoms = result.atoms || [];
    if (!atoms.length) return;

    var isDark = document.documentElement.getAttribute("data-theme") === "dark";
    var charges = result.mulliken_charges || result.lowdin_charges || [];

    var maxAbs = 0;
    for (var k = 0; k < charges.length; k++) {
      var cv = charges[k];
      var cval = cv != null && typeof cv === "object" ? cv.charge : cv;
      if (cval != null && isFinite(cval) && Math.abs(cval) > maxAbs)
        maxAbs = Math.abs(cval);
    }
    if (maxAbs < 0.001) maxAbs = 1;

    atoms.forEach(function (a, i) {
      var el = a.element || a.symbol || a[0] || "";
      if (!el) return;

      var rawCharge = charges[i];
      var chargeVal = null;
      if (rawCharge != null) {
        chargeVal =
          typeof rawCharge === "object" ? rawCharge.charge : rawCharge;
        if (chargeVal != null && !isFinite(chargeVal)) chargeVal = null;
      }

      var labelText = el;
      if (chargeVal != null) {
        labelText +=
          " (" + (chargeVal >= 0 ? "+" : "") + chargeVal.toFixed(3) + ")";
      }

      var bgColor, fontColor, borderColor;
      var labelBgOpacity = 0.85;
      if (chargeVal != null && Math.abs(chargeVal) > 0.005) {
        var alpha = 0.25 + Math.min(Math.abs(chargeVal) / maxAbs, 1.0) * 0.55;
        labelBgOpacity = alpha;
        if (chargeVal > 0) {
          bgColor = "#3b82f6";
          fontColor = isDark ? "#dbeafe" : "#1e3a5f";
          borderColor = "#93bbfd";
        } else {
          bgColor = "#ef4444";
          fontColor = isDark ? "#fee2e2" : "#7f1d1d";
          borderColor = "#f87171";
        }
      } else {
        fontColor = isDark ? "white" : "#333";
        bgColor = isDark ? "#000000" : "#ffffff";
        borderColor = isDark ? "#333333" : "#cccccc";
        labelBgOpacity = isDark ? 0.5 : 0.7;
      }

      viewer.addLabel(labelText, {
        position: {
          x: a.x != null ? a.x : a[1] || 0,
          y: a.y != null ? a.y : a[2] || 0,
          z: a.z != null ? a.z : a[3] || 0,
        },
        fontSize: 11,
        fontColor: fontColor,
        backgroundColor: bgColor,
        borderColor: borderColor,
        borderThickness: 1,
        backgroundOpacity: labelBgOpacity,
        alignment: "center",
        showBackground: true,
      });
    });
  }

  function refreshLabels() {
    if (!state.viewer) return;
    state.viewer.removeAllLabels();
    if (state.showLabels && state.result) addLabels(state.viewer, state.result);
    state.viewer.render();
  }

  /* ─────────────────────────────────────────
     CORE RENDER PRIMITIVES
     ───────────────────────────────────────── */
  function clearViewer(viewer) {
    if (!viewer) return;
    viewer.removeAllModels();
    viewer.removeAllSurfaces();
    viewer.removeAllLabels();
    if (typeof viewer.removeAllShapes === "function") viewer.removeAllShapes();
    state.model = null;
  }

  function addMoleculeModel(viewer, result) {
    var xyz = getXyz(result);
    if (!xyz) return false;
    state.model = viewer.addModel(xyz, "xyz");
    applyStyle(viewer, state.style);
    return true;
  }

  function addOrbitalSurfaces(viewer, cubeString) {
    if (!cubeString) return;
    try {
      var scheme = getScheme();
      var vol = new window.$3Dmol.VolumeData(cubeString, "cube");
      viewer.addIsosurface(vol, {
        isoval: state.isovalue,
        color: scheme.orbPositive,
        alpha: state.opacity,
        smoothness: 3,
        wireframe: false,
      });
      viewer.addIsosurface(vol, {
        isoval: -state.isovalue,
        color: scheme.orbNegative,
        alpha: state.opacity,
        smoothness: 3,
        wireframe: false,
      });
    } catch (e) {
      console.error("[Viewer] addOrbitalSurfaces error:", e);
    }
  }

  function addESPSurface(viewer, result) {
    var espB64 = findCubeB64(result, "esp");
    var densB64 = findCubeB64(result, "density");
    var espStr = safeAtob(espB64);
    if (!espStr) {
      console.warn("[Viewer] No ESP cube data found");
      return;
    }

    var scheme = getScheme();
    var range = result.esp_auto_range_au || 0.05;
    var minVal = scheme.reverse ? range : -range;
    var maxVal = scheme.reverse ? -range : range;
    var grad = createGradient(scheme.espGradient, minVal, maxVal);

    var espVol = new window.$3Dmol.VolumeData(espStr, "cube");

    if (densB64) {
      var densStr = safeAtob(densB64);
      if (densStr) {
        var densVol = new window.$3Dmol.VolumeData(densStr, "cube");
        viewer.addIsosurface(densVol, {
          isoval: state.espDensityIso,
          color: "white",
          alpha: state.opacity,
          smoothness: 1,
          voldata: espVol,
          volscheme: grad,
        });
        return;
      }
    }

    // Fallback: Map ESP on its own isosurface (less ideal)
    viewer.addIsosurface(espVol, {
      isoval: state.isovalue,
      alpha: state.opacity,
      smoothness: 3,
      volscheme: grad,
    });
  }

  /* ─────────────────────────────────────────
     HIGH-LEVEL RENDERERS
     ───────────────────────────────────────── */
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

  function renderOrbital(result) {
    return ensureViewer().then(function (viewer) {
      var oldXyz = state.result ? getXyz(state.result) : null;
      var newXyz = getXyz(result);
      var isNew = oldXyz !== newXyz;

      clearViewer(viewer);
      addMoleculeModel(viewer, result);

      var cubeB64 = findCubeB64(result, "orbital");
      var cubeStr = safeAtob(cubeB64);
      if (cubeStr) {
        addOrbitalSurfaces(viewer, cubeStr);
        if (!state.model) {
          state.model = viewer.addModel(cubeStr, "cube");
          applyStyle(viewer, state.style);
        }
      }

      if (state.showLabels && state.model) addLabels(viewer, result);
      if (isNew) viewer.zoomTo();
      viewer.render();
      state.mode = "orbital";
      showControls("orbital");
      showOrbitalLegend();
      populateOrbitalSelector(result);
    });
  }

  function renderESP(result) {
    return ensureViewer().then(function (viewer) {
      var oldXyz = state.result ? getXyz(state.result) : null;
      var newXyz = getXyz(result);
      var isNew = oldXyz !== newXyz;

      clearViewer(viewer);
      addMoleculeModel(viewer, result);

      try {
        addESPSurface(viewer, result);
      } catch (e) {
        console.error("[Viewer] ESP render error:", e);
      }

      if (state.showLabels && state.model) addLabels(viewer, result);
      if (isNew) viewer.zoomTo();
      viewer.render();
      state.mode = "esp";
      showControls("esp");
      showESPLegend();
    });
  }

  function reRenderCurrentSurface() {
    if (!state.viewer || !state.result) return;
    if (state.mode === "orbital") {
      renderOrbital(state.result);
    } else if (state.mode === "esp") {
      renderESP(state.result);
    }
  }

  function switchVizMode(newMode) {
    if (!state.result) return;
    if (state.mode === newMode) return;
    var prevMode = state.mode;
    state.mode = "switching";

    var p;
    if (newMode === "orbital") {
      if (findCubeB64(state.result, "orbital")) {
        p = renderOrbital(state.result);
      } else {
        p = renderMolecule(state.result);
      }
    } else if (newMode === "esp") {
      if (findCubeB64(state.result, "esp")) {
        p = renderESP(state.result);
      } else {
        p = renderMolecule(state.result);
      }
    }

    if (p) {
      p.then(function () {
        saveViewerSnapshot();
      }).catch(function (err) {
        console.error("[Viewer] Mode switch failed:", err);
        state.mode = prevMode;
        showControls(prevMode);
      });
    } else {
      state.mode = prevMode;
    }
  }

  function showControls(mode) {
    if (dom.$empty) dom.$empty.hidden = true;
    if (dom.$controls) dom.$controls.hidden = false;

    var result = state.result || {};
    var hasOrbital = !!(
      findCubeB64(result, "orbital") ||
      (result.orbitals && result.orbitals.length)
    );
    var hasESP = !!findCubeB64(result, "esp");

    if (dom.$grpOrbital) dom.$grpOrbital.hidden = !hasOrbital;
    if (dom.$grpESP) dom.$grpESP.hidden = !hasESP;
    if (dom.$grpOpacity) dom.$grpOpacity.hidden = !(hasOrbital || hasESP);
    if (dom.$vizModeToggle) dom.$vizModeToggle.hidden = !(hasOrbital && hasESP);
    if (dom.$grpOrbitalSelect)
      dom.$grpOrbitalSelect.hidden = mode !== "orbital" || !hasOrbital;

    if (dom.$sliderIso) {
      if (mode === "esp") {
        dom.$sliderIso.min = "0.0001";
        dom.$sliderIso.max = "0.02";
        dom.$sliderIso.step = "0.0001";
        if (state.isovalue > 0.02 || state.isovalue < 0.0001)
          state.isovalue = 0.002;
      } else {
        dom.$sliderIso.min = "0.001";
        dom.$sliderIso.max = "0.2";
        dom.$sliderIso.step = "0.001";
        if (state.isovalue < 0.001 || state.isovalue > 0.2)
          state.isovalue = 0.03;
      }
      dom.$sliderIso.value = state.isovalue;
      if (dom.$lblIso) dom.$lblIso.textContent = state.isovalue.toFixed(4);
    }

    if (dom.$btnModeOrbital)
      dom.$btnModeOrbital.classList.toggle("active", mode === "orbital");
    if (dom.$btnModeESP)
      dom.$btnModeESP.classList.toggle("active", mode === "esp");

    if (mode === "orbital") showOrbitalLegend();
    else if (mode === "esp") showESPLegend();
    else hideLegend();
  }

  function showOrbitalLegend() {
    if (!dom.$legend) return;
    var s = getScheme();
    dom.$legend.hidden = false;
    dom.$legend.innerHTML =
      '<div class="viewer-legend__title">Orbital Lobes</div>' +
      '<div class="viewer-legend__row"><span class="viewer-legend__swatch" style="background:' +
      s.orbPositive +
      '"></span><span>Positive (+' +
      state.isovalue.toFixed(3) +
      ")</span></div>" +
      '<div class="viewer-legend__row"><span class="viewer-legend__swatch" style="background:' +
      s.orbNegative +
      '"></span><span>Negative (\u2212' +
      state.isovalue.toFixed(3) +
      ")</span></div>";
  }

  function showESPLegend() {
    if (!dom.$legend) return;
    var css = getGradientCSS(getScheme());
    dom.$legend.hidden = false;
    dom.$legend.innerHTML =
      '<div class="viewer-legend__title">ESP Surface</div>' +
      '<div class="viewer-legend__row" style="justify-content:center;width:100%;margin-top:4px;">' +
      '<span class="viewer-legend__swatch" style="background:' +
      css +
      ';width:100px;height:12px;border-radius:3px;"></span></div>' +
      '<div class="viewer-legend__row" style="display:flex;justify-content:space-between;width:100px;margin:2px auto 0;">' +
      '<span style="font-size:11px;color:var(--text-3)">\u2212</span><span style="font-size:10px;color:var(--text-4)">0</span><span style="font-size:11px;color:var(--text-3)">+</span></div>';
  }

  function hideLegend() {
    if (dom.$legend) {
      dom.$legend.hidden = true;
      dom.$legend.innerHTML = "";
    }
  }

  function getGradientCSS(schemeObj) {
    var g = schemeObj.espGradient;
    var r = schemeObj.reverse;
    if (g === "sinebow")
      return "linear-gradient(90deg,#ff0000,#0000ff,#00ffff,#00ff00,#ffff00,#ff0000)";
    if (g === "roygb")
      return r
        ? "linear-gradient(90deg,#0000ff,#00ff00,#ffff00,#ff0000)"
        : "linear-gradient(90deg,#ff0000,#ffff00,#00ff00,#0000ff)";
    return r
      ? "linear-gradient(90deg,#3b82f6,#ffffff,#ef4444)"
      : "linear-gradient(90deg,#ef4444,#ffffff,#3b82f6)";
  }

  function populateOrbitalSelector(result) {
    if (!dom.$selectOrbital || !result) return;
    var orbitals = result.orbitals || [];
    var moE = result.mo_energies || [];
    var moO = result.mo_occupations || [];
    dom.$selectOrbital.innerHTML = "";

    if (orbitals.length > 0) {
      var info =
        (result.visualization && result.visualization.orbital_info) ||
        result.orbital_info ||
        {};
      var currentIdx =
        info.orbital_index != null
          ? info.orbital_index
          : result.selected_orbital
            ? result.selected_orbital.zero_based_index
            : -1;
      orbitals.forEach(function (orb) {
        var opt = document.createElement("option");
        opt.value = orb.zero_based_index;
        opt.textContent =
          orb.label + " (" + Number(orb.energy_hartree).toFixed(3) + " Ha)";
        if (orb.zero_based_index === currentIdx) opt.selected = true;
        dom.$selectOrbital.appendChild(opt);
      });
      state.selectedOrbitalIndex = currentIdx;
      if (dom.$grpOrbitalSelect) dom.$grpOrbitalSelect.hidden = false;
    } else if (moE.length > 0) {
      var homoIdx = -1;
      for (var i = 0; i < moE.length; i++) if (moO[i] > 0) homoIdx = i;
      var lumoIdx = homoIdx >= 0 && homoIdx + 1 < moE.length ? homoIdx + 1 : -1;
      var currentIdx2 = homoIdx;
      var start = Math.max(0, homoIdx - 4);
      var end = Math.min(moE.length, (lumoIdx >= 0 ? lumoIdx : homoIdx) + 5);
      for (var j = start; j < end; j++) {
        var opt = document.createElement("option");
        opt.value = j;
        var label = "MO " + j;
        if (j === homoIdx) label = "HOMO";
        else if (j === lumoIdx) label = "LUMO";
        opt.textContent = label + " (" + Number(moE[j]).toFixed(3) + " Ha)";
        if (j === currentIdx2) opt.selected = true;
        dom.$selectOrbital.appendChild(opt);
      }
      state.selectedOrbitalIndex = currentIdx2;
      if (dom.$grpOrbitalSelect) dom.$grpOrbitalSelect.hidden = false;
    } else {
      if (dom.$grpOrbitalSelect) dom.$grpOrbitalSelect.hidden = true;
    }
  }

  function saveViewerSnapshot() {
    if (!state.jobId) return;
    var existing = App.getUISnapshot(state.jobId) || {};
    App.saveUISnapshot(
      state.jobId,
      Object.assign({}, existing, {
        viewerStyle: state.style,
        viewerIsovalue: state.isovalue,
        viewerOpacity: state.opacity,
        viewerLabels: state.showLabels,
        viewerMode: state.mode,
        viewerOrbitalIndex: state.selectedOrbitalIndex,
        viewerColorScheme: state.colorScheme,
      }),
    );
  }

  function restoreViewerSnapshot(jobId) {
    var snap = App.getUISnapshot(jobId);
    if (!snap) return;
    if (snap.viewerStyle) state.style = snap.viewerStyle;
    if (snap.viewerIsovalue != null) state.isovalue = snap.viewerIsovalue;
    if (snap.viewerOpacity != null) state.opacity = snap.viewerOpacity;
    if (snap.viewerLabels != null) state.showLabels = snap.viewerLabels;
    if (snap.viewerOrbitalIndex != null)
      state.selectedOrbitalIndex = snap.viewerOrbitalIndex;
    if (snap.viewerColorScheme) state.colorScheme = snap.viewerColorScheme;
    syncUIToState();
  }

  function syncUIToState() {
    if (dom.$segStyle) {
      dom.$segStyle.querySelectorAll(".segmented__btn").forEach(function (b) {
        b.classList.toggle(
          "segmented__btn--active",
          b.dataset.value === state.style,
        );
      });
    }
    if (dom.$sliderIso) dom.$sliderIso.value = state.isovalue;
    if (dom.$lblIso) dom.$lblIso.textContent = state.isovalue.toFixed(4);
    if (dom.$sliderOp) dom.$sliderOp.value = state.opacity;
    if (dom.$lblOp) dom.$lblOp.textContent = state.opacity.toFixed(2);
    if (dom.$btnLabels) {
      dom.$btnLabels.setAttribute("data-active", String(state.showLabels));
      dom.$btnLabels.textContent = state.showLabels ? "On" : "Off";
    }
    if (dom.$selectColor) dom.$selectColor.value = state.colorScheme;
    updateSchemePreview();
  }

  function handleResult(detail) {
    var result = detail.result;
    var jobId = detail.jobId;
    if (!result) {
      if (state.viewer) {
        clearViewer(state.viewer);
        state.viewer.render();
      }
      state.result = null;
      state.jobId = null;
      state.mode = "none";
      if (dom.$empty) dom.$empty.hidden = false;
      if (dom.$controls) dom.$controls.hidden = true;
      hideLegend();
      return;
    }
    state.result = result;
    state.jobId = jobId;
    if (detail.source === "history" && jobId) restoreViewerSnapshot(jobId);
    var p;
    if (findCubeB64(result, "orbital")) p = renderOrbital(result);
    else if (findCubeB64(result, "esp")) p = renderESP(result);
    else if (getXyz(result)) p = renderMolecule(result);
    if (p) p.then(saveViewerSnapshot).catch(console.error);
  }

  function handleResultSwitched(data) {
    var r = data.result;
    if (!r) return;
    state.result = r;
    state.jobId = data.jobId || null;
    if (findCubeB64(r, "orbital")) renderOrbital(r);
    else if (findCubeB64(r, "esp")) renderESP(r);
    else if (getXyz(r)) renderMolecule(r);
  }

  function bindEvents() {
    if (dom.$segStyle)
      dom.$segStyle.addEventListener("click", function (e) {
        var b = e.target.closest(".segmented__btn");
        if (!b) return;
        state.style = b.dataset.value;
        dom.$segStyle.querySelectorAll(".segmented__btn").forEach(function (x) {
          x.classList.toggle(
            "segmented__btn--active",
            x.dataset.value === state.style,
          );
        });
        if (state.viewer && state.model) {
          applyStyle(state.viewer, state.style);
          state.viewer.render();
        }
        saveViewerSnapshot();
      });
    if (dom.$btnLabels)
      dom.$btnLabels.addEventListener("click", function () {
        state.showLabels = !state.showLabels;
        refreshLabels();
        syncUIToState();
        saveViewerSnapshot();
      });
    if (dom.$btnReset)
      dom.$btnReset.addEventListener("click", function () {
        if (state.viewer) {
          state.viewer.zoomTo();
          state.viewer.render();
        }
      });
    if (dom.$btnScreenshot)
      dom.$btnScreenshot.addEventListener("click", function () {
        if (!state.viewer) return;
        var a = document.createElement("a");
        a.href = state.viewer.pngURI();
        a.download = "qcviz-" + (state.jobId || "capture") + ".png";
        a.click();
      });
    if (dom.$btnFullscreen)
      dom.$btnFullscreen.addEventListener("click", function () {
        var p = document.getElementById("panelViewer");
        if (p) p.classList.toggle("is-fullscreen");
        setTimeout(function () {
          if (state.viewer) {
            state.viewer.resize();
            state.viewer.render();
          }
        }, 150);
      });
    if (dom.$sliderIso) {
      dom.$sliderIso.addEventListener("input", function () {
        state.isovalue = parseFloat(dom.$sliderIso.value);
        if (dom.$lblIso) dom.$lblIso.textContent = state.isovalue.toFixed(4);
      });
      dom.$sliderIso.addEventListener("change", function () {
        reRenderCurrentSurface();
        saveViewerSnapshot();
      });
    }
    if (dom.$sliderOp) {
      dom.$sliderOp.addEventListener("input", function () {
        state.opacity = parseFloat(dom.$sliderOp.value);
        if (dom.$lblOp) dom.$lblOp.textContent = state.opacity.toFixed(2);
      });
      dom.$sliderOp.addEventListener("change", function () {
        reRenderCurrentSurface();
        saveViewerSnapshot();
      });
    }
    if (dom.$selectOrbital)
      dom.$selectOrbital.addEventListener("change", function () {
        var idx = parseInt(dom.$selectOrbital.value, 10);
        if (isNaN(idx)) return;
        state.selectedOrbitalIndex = idx;
        // In a real implementation, we might need to fetch the orbital cube here if not cached.
        // For now, assume it's available or handled by the parent.
        saveViewerSnapshot();
      });
    if (dom.$btnModeOrbital)
      dom.$btnModeOrbital.addEventListener("click", function () {
        switchVizMode("orbital");
      });
    if (dom.$btnModeESP)
      dom.$btnModeESP.addEventListener("click", function () {
        switchVizMode("esp");
      });
    if (dom.$sliderEspDensIso) {
      dom.$sliderEspDensIso.addEventListener("input", function () {
        state.espDensityIso = parseFloat(dom.$sliderEspDensIso.value);
        if (dom.$lblEspDensIso)
          dom.$lblEspDensIso.textContent = state.espDensityIso.toFixed(4);
      });
      dom.$sliderEspDensIso.addEventListener("change", function () {
        reRenderCurrentSurface();
        saveViewerSnapshot();
      });
    }
    if (dom.$selectColor)
      dom.$selectColor.addEventListener("change", function () {
        state.colorScheme = dom.$selectColor.value;
        updateSchemePreview();
        reRenderCurrentSurface();
        saveViewerSnapshot();
      });

    App.on("result:changed", handleResult);
    App.on("result:switched", handleResultSwitched);
    App.on("result:cleared", function () {
      if (state.viewer) {
        clearViewer(state.viewer);
        state.viewer.render();
      }
      state.result = null;
      state.jobId = null;
      state.mode = "none";
      if (dom.$empty) dom.$empty.hidden = false;
      if (dom.$controls) dom.$controls.hidden = true;
      hideLegend();
    });
    App.on("theme:changed", function () {
      updateViewerBg();
      refreshLabels();
    });
    window.addEventListener("resize", function () {
      if (state.viewer) {
        state.viewer.resize();
        state.viewer.render();
      }
    });
  }

  function init() {
    collectDom();
    bindEvents();
    syncUIToState();
    var safety = setTimeout(dismissLoader, 5000);
    ensureViewer()
      .then(function () {
        clearTimeout(safety);
        var ajid = App.store && App.store.activeJobId;
        if (ajid && App.store.resultsByJobId[ajid]) {
          var r = App.store.resultsByJobId[ajid];
          // handleResult with source:history will call restoreViewerSnapshot
          handleResult({ result: r, jobId: ajid, source: "history" });
        }
        dismissLoader();
      })
      .catch(function (e) {
        clearTimeout(safety);
        console.error(e);
        dismissLoader();
      });
  }

  App.viewer = {
    reset: function () {
      if (state.viewer) state.viewer.zoomTo();
    },
  };
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();
```

---

## 파일: `src/qcviz_mcp/web/static/results.js` (899줄, 30789bytes)

```javascript
/* ═══════════════════════════════════════════
   QCViz-MCP Enterprise v5 — Results Module
   (Fixed: field name alignment with backend)
   ═══════════════════════════════════════════ */
(function () {
  "use strict";

  var App = window.QCVizApp;
  if (!App) return;

  var TAB_ORDER = [
    ["summary", "Summary"],
    ["geometry", "Geometry"],
    ["orbital", "Orbital"],
    ["esp", "ESP"],
    ["charges", "Charges"],
    ["json", "JSON"],
  ];

  var state = { result: null, jobId: null, activeTab: "summary", tabs: [] };

  var sessionResults = [];
  var activeSessionIdx = -1;

  function buildResultLabel(result, index) {
    var mol = result.molecule_name || result.structure_name || "Mol";
    var type = "";

    if (result.optimization_performed) {
      type = "Opt";
    } else if (result.orbital_cube_b64 || result.orbital_cube) {
      var orbs = result.orbitals || [];
      var selIdx = 0;
      for (var i = 0; i < orbs.length; i++) {
        if (orbs[i] && orbs[i].is_selected) {
          selIdx = i;
          break;
        }
      }
      var orbLabel = (orbs[selIdx] && orbs[selIdx].label) || "MO";
      type = orbLabel;
    } else if (result.esp_cube_b64 || result.esp_cube) {
      type = "ESP";
    } else {
      type = result.method || "SCF";
    }
    return "#" + index + " " + mol + " " + type;
  }

  function renderSessionTabs() {
    var $bar = document.getElementById("sessionTabBar");
    if (!$bar) return;
    $bar.innerHTML = "";
    $bar.hidden = sessionResults.length <= 1;

    for (var i = 0; i < sessionResults.length; i++) {
      (function (idx) {
        var entry = sessionResults[idx];
        var $tab = document.createElement("button");
        $tab.className =
          "session-tab" + (idx === activeSessionIdx ? " active" : "");
        $tab.textContent = entry.label;
        $tab.title = new Date(entry.timestamp).toLocaleTimeString();
        $tab.setAttribute("data-idx", idx);

        $tab.addEventListener("click", function () {
          switchToSessionResult(idx);
        });

        var $close = document.createElement("span");
        $close.className = "session-tab-close";
        $close.textContent = "×";
        $close.title = "이 결과 닫기";
        $close.addEventListener("click", function (e) {
          e.stopPropagation();
          removeSessionResult(idx);
        });

        $tab.appendChild($close);
        $bar.appendChild($tab);
      })(i);
    }
  }

  function switchToSessionResult(idx) {
    if (idx < 0 || idx >= sessionResults.length) return;
    if (idx === activeSessionIdx) return;
    activeSessionIdx = idx;
    var entry = sessionResults[idx];
    state.result = entry.result;
    state.jobId = entry.jobId;

    var available = getAvailableTabs(entry.result);
    state.tabs = available;
    if (available.indexOf(state.activeTab) === -1) {
      state.activeTab = decideFocusTab(entry.result, available);
    }

    renderSessionTabs();
    renderTabs(available, state.activeTab);
    renderContent(state.activeTab, entry.result);
    App.emit("result:switched", { result: entry.result, jobId: entry.jobId });
  }

  function removeSessionResult(idx) {
    if (idx < 0 || idx >= sessionResults.length) return;
    sessionResults.splice(idx, 1);
    if (sessionResults.length === 0) {
      activeSessionIdx = -1;
      state.result = null;
      state.jobId = null;
      renderSessionTabs();
      if ($empty) $empty.hidden = false;
      if ($tabs) $tabs.innerHTML = "";
      if ($content) $content.innerHTML = "";
      App.emit("result:cleared");
      return;
    }
    if (idx === activeSessionIdx) {
      activeSessionIdx = Math.min(idx, sessionResults.length - 1);
      var entry = sessionResults[activeSessionIdx];
      state.result = entry.result;
      state.jobId = entry.jobId;
      var available = getAvailableTabs(entry.result);
      state.tabs = available;
      if (available.indexOf(state.activeTab) === -1) {
        state.activeTab = decideFocusTab(entry.result, available);
      }
      renderTabs(available, state.activeTab);
      renderContent(state.activeTab, entry.result);
    } else if (idx < activeSessionIdx) {
      activeSessionIdx--;
    }
    renderSessionTabs();
  }

  var $tabs = document.getElementById("resultsTabs");
  var $content = document.getElementById("resultsContent");
  var $empty = document.getElementById("resultsEmpty");

  function normalizeResult(raw) {
    if (!raw || typeof raw !== "object") return null;
    var r = App.clone(raw);

    /* ── energy aliases ── */
    if (r.total_energy_hartree == null && r.energy != null)
      r.total_energy_hartree = r.energy;

    /* ── visualization normalization ── */
    if (!r.visualization) r.visualization = {};
    var viz = r.visualization;

    /* Backend sends viz.xyz and viz.molecule_xyz, NOT viz.xyz_block */
    if (!viz.xyz_block) {
      viz.xyz_block =
        viz.xyz || viz.molecule_xyz || r.xyz_block || r.xyz || null;
    }

    if (!viz.orbital_cube_b64 && r.orbital_cube_b64)
      viz.orbital_cube_b64 = r.orbital_cube_b64;
    if (!viz.orbital_info && r.orbital_info) viz.orbital_info = r.orbital_info;
    if (!viz.esp_cube_b64 && r.esp_cube_b64) viz.esp_cube_b64 = r.esp_cube_b64;
    if (!viz.density_cube_b64 && r.density_cube_b64)
      viz.density_cube_b64 = r.density_cube_b64;

    /* ── orbital sub-objects ── */
    if (!viz.orbital_cube_b64 && viz.orbital && viz.orbital.cube_b64) {
      viz.orbital_cube_b64 = viz.orbital.cube_b64;
    }
    if (!viz.esp_cube_b64 && viz.esp && viz.esp.cube_b64) {
      viz.esp_cube_b64 = viz.esp.cube_b64;
    }
    if (!viz.density_cube_b64 && viz.density && viz.density.cube_b64) {
      viz.density_cube_b64 = viz.density.cube_b64;
    }

    /* ── selected_orbital → orbital_info ── */
    if (!viz.orbital_info && r.selected_orbital) {
      viz.orbital_info = r.selected_orbital;
    }

    /* ── charges: backend returns [{atom_index, symbol, charge}, ...] ── */
    /* Normalize to parallel arrays for easy rendering */
    if (
      r.mulliken_charges &&
      r.mulliken_charges.length &&
      typeof r.mulliken_charges[0] === "object"
    ) {
      r._mulliken_raw = r.mulliken_charges;
      r.mulliken_charges = r.mulliken_charges.map(function (c) {
        return c.charge != null ? c.charge : c;
      });
    }
    if (
      r.lowdin_charges &&
      r.lowdin_charges.length &&
      typeof r.lowdin_charges[0] === "object"
    ) {
      r._lowdin_raw = r.lowdin_charges;
      r.lowdin_charges = r.lowdin_charges.map(function (c) {
        return c.charge != null ? c.charge : c;
      });
    }
    if (
      r.partial_charges &&
      r.partial_charges.length &&
      typeof r.partial_charges[0] === "object"
    ) {
      r.partial_charges = r.partial_charges.map(function (c) {
        return c.charge != null ? c.charge : c;
      });
    }

    /* ── fallback aliases for old-style keys ── */
    if (!r.mulliken_charges && r.charges) r.mulliken_charges = r.charges;
    if (!r.atoms && r.geometry) r.atoms = r.geometry;

    /* ── Build mo_energies / mo_occupations from orbitals array ── */
    if (
      (!r.mo_energies || !r.mo_energies.length) &&
      r.orbitals &&
      r.orbitals.length
    ) {
      var sorted = r.orbitals.slice().sort(function (a, b) {
        var ai =
          typeof a.zero_based_index === "number" ? a.zero_based_index : 0;
        var bi =
          typeof b.zero_based_index === "number" ? b.zero_based_index : 0;
        return ai - bi;
      });
      r.mo_energies = sorted.map(function (o) {
        return o.energy_hartree;
      });
      r.mo_occupations = sorted.map(function (o) {
        return o.occupancy;
      });
      r._orbital_index_offset = sorted[0] ? sorted[0].zero_based_index : 0;
      r._orbital_labels = sorted.map(function (o) {
        return o.label;
      });
    }

    return r;
  }

  function getAvailableTabs(r) {
    if (!r) return [];
    var a = ["summary"];
    var viz = r.visualization || {};

    if (viz.xyz_block || (r.atoms && r.atoms.length)) a.push("geometry");

    if (
      viz.orbital_cube_b64 ||
      (r.mo_energies && r.mo_energies.length) ||
      (r.orbitals && r.orbitals.length)
    )
      a.push("orbital");

    if (viz.esp_cube_b64) a.push("esp");

    // Sometimes backend returns single float or object instead of arrays,
    // or array of objects [{charge: 0.1}, ...]
    // Better to check if the property exists and has elements/keys.
    var hasMulliken = Array.isArray(r.mulliken_charges)
      ? r.mulliken_charges.length > 0
      : r.mulliken_charges &&
        typeof r.mulliken_charges === "object" &&
        Object.keys(r.mulliken_charges).length > 0;
    var hasLowdin = Array.isArray(r.lowdin_charges)
      ? r.lowdin_charges.length > 0
      : r.lowdin_charges &&
        typeof r.lowdin_charges === "object" &&
        Object.keys(r.lowdin_charges).length > 0;

    if (hasMulliken || hasLowdin) a.push("charges");

    a.push("json");
    return a;
  }

  function decideFocusTab(r, a) {
    /* Use backend's advisor_focus_tab if valid */
    var advised =
      r.advisor_focus_tab ||
      r.default_tab ||
      (r.visualization &&
        r.visualization.defaults &&
        r.visualization.defaults.focus_tab);
    if (advised && a.indexOf(advised) !== -1) return advised;
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
      btn.className =
        "tab-btn" + (pair[0] === active ? " tab-btn--active" : "");
      btn.setAttribute("role", "tab");
      btn.setAttribute("data-tab", pair[0]);
      btn.textContent = pair[1];
      btn.addEventListener("click", function () {
        switchTab(pair[0]);
      });
      $tabs.appendChild(btn);
    });
  }

  function switchTab(key) {
    if (key === state.activeTab) return;
    state.activeTab = key;
    if ($tabs)
      $tabs.querySelectorAll(".tab-btn").forEach(function (b) {
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
    return (
      '<div class="result-metric"><span class="result-metric__label">' +
      esc(label) +
      '</span><span class="result-metric__value">' +
      esc(String(value)) +
      (unit
        ? '<span class="result-metric__unit"> ' + esc(unit) + "</span>"
        : "") +
      "</span></div>"
    );
  }

  function renderContent(tab, r) {
    if (!r || !$content) {
      if ($content) $content.innerHTML = "";
      return;
    }
    var html = '<div class="result-card">';
    switch (tab) {
      case "summary":
        html += renderSummary(r);
        break;
      case "geometry":
        html += renderGeometry(r);
        break;
      case "orbital":
        html += renderOrbital(r);
        break;
      case "esp":
        html += renderESP(r);
        break;
      case "charges":
        html += renderCharges(r);
        break;
      case "json":
        html += renderJSON(r);
        break;
    }
    html += "</div>";
    $content.innerHTML = html;
  }

  function renderSummary(r) {
    var html = '<div class="metrics-grid">';
    var has = false;
    var m = [];

    if (r.structure_name || r.molecule_name || r.molecule)
      m.push([
        "Molecule",
        r.structure_name || r.molecule_name || r.molecule,
        "",
      ]);
    if (r.formula) m.push(["Formula", r.formula, ""]);
    if (r.method) m.push(["Method", r.method, ""]);
    /* Backend sends "basis", not "basis_set" */
    if (r.basis || r.basis_set)
      m.push(["Basis Set", r.basis || r.basis_set, ""]);
    if (r.n_atoms != null) m.push(["Atoms", r.n_atoms, ""]);
    if (r.scf_converged != null)
      m.push(["SCF Converged", r.scf_converged ? "Yes" : "No", ""]);

    if (r.total_energy_hartree != null)
      m.push(["Total Energy", Number(r.total_energy_hartree).toFixed(8), "Ha"]);
    if (r.total_energy_ev != null)
      m.push(["Energy", Number(r.total_energy_ev).toFixed(4), "eV"]);

    /* Backend sends homo_energy_hartree / homo_energy_ev, NOT homo_energy */
    if (r.homo_energy_hartree != null)
      m.push(["HOMO", Number(r.homo_energy_hartree).toFixed(6), "Ha"]);
    else if (r.homo_energy != null)
      m.push(["HOMO", Number(r.homo_energy).toFixed(6), "Ha"]);

    if (r.lumo_energy_hartree != null)
      m.push(["LUMO", Number(r.lumo_energy_hartree).toFixed(6), "Ha"]);
    else if (r.lumo_energy != null)
      m.push(["LUMO", Number(r.lumo_energy).toFixed(6), "Ha"]);

    /* Backend sends orbital_gap_hartree / orbital_gap_ev, NOT homo_lumo_gap */
    if (r.orbital_gap_hartree != null)
      m.push(["HOMO-LUMO Gap", Number(r.orbital_gap_hartree).toFixed(6), "Ha"]);
    else if (r.homo_lumo_gap != null)
      m.push(["HOMO-LUMO Gap", Number(r.homo_lumo_gap).toFixed(6), "Ha"]);

    if (r.orbital_gap_ev != null)
      m.push(["H-L Gap", Number(r.orbital_gap_ev).toFixed(4), "eV"]);
    else if (r.homo_lumo_gap_ev != null)
      m.push(["H-L Gap", Number(r.homo_lumo_gap_ev).toFixed(4), "eV"]);

    if (r.dipole_moment != null) {
      var dm;
      if (
        typeof r.dipole_moment === "object" &&
        r.dipole_moment.magnitude != null
      ) {
        dm = Number(r.dipole_moment.magnitude).toFixed(4);
      } else if (Array.isArray(r.dipole_moment)) {
        dm = r.dipole_moment
          .map(function (v) {
            return Number(v).toFixed(4);
          })
          .join(", ");
      } else {
        dm = Number(r.dipole_moment).toFixed(4);
      }
      m.push(["Dipole Moment", dm, "Debye"]);
    }

    m.forEach(function (x) {
      html += metric(x[0], x[1], x[2]);
      has = true;
    });
    html += "</div>";
    if (!has)
      html =
        '<p class="result-note">No summary data available. Check the JSON tab.</p>';
    return html;
  }

  function renderGeometry(r) {
    var atoms = r.atoms || [];
    if (!atoms.length && !r.visualization.xyz_block)
      return '<p class="result-note">No geometry data.</p>';
    var html = "";

    /* Geometry summary from backend */
    var gs = r.geometry_summary;
    if (gs) {
      html += '<div class="metrics-grid" style="margin-bottom:var(--sp-4)">';
      if (gs.formula) html += metric("Formula", gs.formula, "");
      if (gs.n_atoms != null) html += metric("Atoms", gs.n_atoms, "");
      if (gs.bond_count != null) html += metric("Bonds", gs.bond_count, "");
      if (gs.bond_length_mean_angstrom != null)
        html += metric(
          "Avg Bond",
          Number(gs.bond_length_mean_angstrom).toFixed(4),
          "\u00C5",
        );
      html += "</div>";
    }

    if (atoms.length) {
      html +=
        '<table class="result-table"><thead><tr><th>#</th><th>Element</th><th>X (\u00C5)</th><th>Y (\u00C5)</th><th>Z (\u00C5)</th></tr></thead><tbody>';
      atoms.forEach(function (a, i) {
        var el = a.element || a.symbol || a[0] || "?";
        html +=
          "<tr><td>" +
          (i + 1) +
          "</td><td>" +
          esc(el) +
          "</td><td>" +
          Number(a.x != null ? a.x : a[1] || 0).toFixed(6) +
          "</td><td>" +
          Number(a.y != null ? a.y : a[2] || 0).toFixed(6) +
          "</td><td>" +
          Number(a.z != null ? a.z : a[3] || 0).toFixed(6) +
          "</td></tr>";
      });
      html += "</tbody></table>";
    }
    if (r.visualization.xyz_block) {
      html +=
        '<details style="margin-top:var(--sp-4)"><summary>Raw XYZ Block</summary><pre class="result-json" style="margin-top:var(--sp-2)">' +
        esc(r.visualization.xyz_block) +
        "</pre></details>";
    }
    return html;
  }

  function renderOrbital(r) {
    var info =
      (r.visualization && r.visualization.orbital_info) ||
      r.selected_orbital ||
      r.orbital_info ||
      {};
    var html = '<div class="metrics-grid">';
    if (info.label) html += metric("Selected", info.label, "");
    if (info.energy_hartree != null)
      html += metric("Energy", Number(info.energy_hartree).toFixed(6), "Ha");
    if (info.energy_ev != null)
      html += metric("Energy", Number(info.energy_ev).toFixed(4), "eV");
    if (info.occupancy != null) html += metric("Occupancy", info.occupancy, "");
    if (info.spin) html += metric("Spin", info.spin, "");
    html += "</div>";

    /* Use orbitals array from backend if available */
    var orbitals = r.orbitals || [];
    var moE = r.mo_energies || [];
    var moO = r.mo_occupations || [];
    var offset = r._orbital_index_offset || 0;
    var labels = r._orbital_labels || [];

    if (orbitals.length > 0 || moE.length > 0) {
      html +=
        '<div class="energy-diagram"><div class="energy-diagram__title">MO Energy Levels</div>';

      if (orbitals.length > 0 && moE.length === 0) {
        /* Render directly from orbitals array */
        orbitals.forEach(function (orb) {
          var occ = orb.occupancy || 0;
          var cls = "energy-level";
          var lbl = orb.label || "MO " + orb.index;
          if (lbl === "HOMO") cls += " energy-level--homo";
          else if (lbl === "LUMO") cls += " energy-level--lumo";
          else if (occ > 0) cls += " energy-level--occupied";
          else cls += " energy-level--virtual";
          html +=
            '<div class="' +
            cls +
            '"><span class="energy-level__bar"></span><span class="energy-level__label">' +
            esc(lbl) +
            '</span><span class="energy-level__energy">' +
            Number(orb.energy_hartree).toFixed(4) +
            ' Ha</span><span class="energy-level__occ">' +
            (occ > 0
              ? "\u2191\u2193".substring(0, Math.min(2, Math.round(occ)))
              : "\u00B7") +
            "</span></div>";
        });
      } else {
        /* Legacy path: mo_energies + mo_occupations arrays */
        var homoIdx = -1;
        for (var i = 0; i < moE.length; i++) {
          if (moO[i] != null && moO[i] > 0) homoIdx = i;
        }
        var lumoIdx =
          homoIdx >= 0 && homoIdx + 1 < moE.length ? homoIdx + 1 : -1;
        var start = moE.length > 16 ? Math.max(0, homoIdx - 5) : 0;
        var end =
          moE.length > 16
            ? Math.min(moE.length, (lumoIdx >= 0 ? lumoIdx : homoIdx) + 6)
            : moE.length;
        for (var j = start; j < end; j++) {
          var realIdx = j + offset;
          var occ = moO[j] != null ? moO[j] : 0;
          var cls = "energy-level";
          var lbl = labels[j] || "MO " + realIdx;
          if (lbl === "HOMO") {
            cls += " energy-level--homo";
          } else if (lbl === "LUMO") {
            cls += " energy-level--lumo";
          } else if (lbl.indexOf("HOMO") === 0) {
            cls += " energy-level--occupied";
          } else if (lbl.indexOf("LUMO") === 0) {
            cls += " energy-level--virtual";
          } else if (occ > 0) {
            cls += " energy-level--occupied";
          } else {
            cls += " energy-level--virtual";
          }
          html +=
            '<div class="' +
            cls +
            '"><span class="energy-level__bar"></span><span class="energy-level__label">' +
            esc(lbl) +
            '</span><span class="energy-level__energy">' +
            Number(moE[j]).toFixed(4) +
            ' Ha</span><span class="energy-level__occ">' +
            (occ > 0
              ? "\u2191\u2193".substring(0, Math.min(2, Math.round(occ)))
              : "\u00B7") +
            "</span></div>";
        }
      }
      html += "</div>";
    }
    html +=
      '<p class="result-note">The orbital is rendered in the 3D viewer. Use the controls to adjust isosurface and select orbitals.</p>';
    return html;
  }

  function renderESP(r) {
    var html = '<div class="metrics-grid">';
    if (r.esp_auto_range_au != null) {
      html += metric(
        "ESP Range",
        "\u00B1" + Number(r.esp_auto_range_au).toFixed(4),
        "a.u.",
      );
    }
    if (r.esp_auto_range_kcal != null) {
      html += metric(
        "ESP Range",
        "\u00B1" + Number(r.esp_auto_range_kcal).toFixed(2),
        "kcal/mol",
      );
    }
    if (r.esp_preset) {
      html += metric("Color Scheme", r.esp_preset, "");
    }
    /* Legacy */
    if (r.esp_range && !r.esp_auto_range_au) {
      html +=
        metric("ESP Min", Number(r.esp_range[0]).toFixed(4), "a.u.") +
        metric("ESP Max", Number(r.esp_range[1]).toFixed(4), "a.u.");
    }
    html += "</div>";
    html +=
      '<p class="result-note">The ESP surface is rendered in the 3D viewer. Use the Isosurface slider to adjust the electron density level and the Opacity slider for transparency.</p>';
    return html;
  }

  function renderCharges(r) {
    var mullRaw = r.mulliken_charges || {};
    var lowdRaw = r.lowdin_charges || {};
    var mull = Array.isArray(mullRaw) ? mullRaw : Object.values(mullRaw);
    var lowd = Array.isArray(lowdRaw) ? lowdRaw : Object.values(lowdRaw);
    var atoms = r.atoms || [];
    if (!mull.length && !lowd.length)
      return '<p class="result-note">No charge data.</p>';

    var primary = mull.length ? mull : lowd;
    var secondary = mull.length && lowd.length ? lowd : null;
    var primaryLabel = mull.length ? "Mulliken" : "Löwdin";
    var secondaryLabel = secondary ? "Löwdin" : null;

    function chargeVal(arr, i) {
      var v = arr[i];
      if (v == null) return null;
      if (typeof v === "object")
        return v.charge != null ? Number(v.charge) : null;
      return Number(v);
    }

    var maxAbs = 0;
    var n = Math.max(primary.length, secondary ? secondary.length : 0);
    for (var i = 0; i < n; i++) {
      var pv = chargeVal(primary, i);
      if (pv != null && Math.abs(pv) > maxAbs) maxAbs = Math.abs(pv);
      if (secondary) {
        var sv = chargeVal(secondary, i);
        if (sv != null && Math.abs(sv) > maxAbs) maxAbs = Math.abs(sv);
      }
    }
    if (maxAbs < 0.0001) maxAbs = 0.5;
    var plotMax = maxAbs;

    var html = "";

    html += '<div class="butterfly-legend">';
    html +=
      '<span class="butterfly-legend__item">' +
      '<span class="butterfly-legend__swatch butterfly-legend__swatch--neg"></span>' +
      "Negative (−)</span>";
    html +=
      '<span class="butterfly-legend__item">' +
      '<span class="butterfly-legend__swatch butterfly-legend__swatch--pos"></span>' +
      "Positive (+)</span>";
    if (secondary) {
      html +=
        '<span class="butterfly-legend__item" style="margin-left:auto;">' +
        '<span style="font-size:11px;color:var(--text-3);">' +
        '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--accent);margin-right:4px;"></span>' +
        primaryLabel +
        ' &nbsp; <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--accent-2);margin-right:4px;"></span>' +
        secondaryLabel +
        "</span></span>";
    }
    html += "</div>";

    html += '<div class="butterfly-chart">';

    for (var i = 0; i < n; i++) {
      var el = atoms[i]
        ? atoms[i].element || atoms[i].symbol || atoms[i][0] || "?"
        : "?";

      var pv = chargeVal(primary, i);
      var sv = secondary ? chargeVal(secondary, i) : null;

      html += '<div class="butterfly-row">';

      html += '<div class="butterfly-bar-area butterfly-bar-area--neg">';
      if (pv != null && pv < 0) {
        var pctP = ((Math.abs(pv) / plotMax) * 100).toFixed(1);
        html +=
          '<div class="butterfly-bar butterfly-bar--neg-primary" ' +
          'style="width:' +
          pctP +
          '%" ' +
          'title="' +
          primaryLabel +
          ": " +
          pv.toFixed(6) +
          '">' +
          '<span class="butterfly-bar__val">' +
          pv.toFixed(4) +
          "</span>" +
          "</div>";
      }
      if (sv != null && sv < 0) {
        var pctS = ((Math.abs(sv) / plotMax) * 100).toFixed(1);
        html +=
          '<div class="butterfly-bar butterfly-bar--neg-secondary" ' +
          'style="width:' +
          pctS +
          '%" ' +
          'title="' +
          secondaryLabel +
          ": " +
          sv.toFixed(6) +
          '"></div>';
      }
      html += "</div>";

      html +=
        '<div class="butterfly-label">' +
        '<span class="butterfly-label__idx">' +
        (i + 1) +
        "</span>" +
        '<span class="butterfly-label__el">' +
        esc(el) +
        "</span>" +
        "</div>";

      html += '<div class="butterfly-bar-area butterfly-bar-area--pos">';
      if (pv != null && pv >= 0) {
        var pctP = ((Math.abs(pv) / plotMax) * 100).toFixed(1);
        html +=
          '<div class="butterfly-bar butterfly-bar--pos-primary" ' +
          'style="width:' +
          pctP +
          '%" ' +
          'title="' +
          primaryLabel +
          ": " +
          (pv >= 0 ? "+" : "") +
          pv.toFixed(6) +
          '">' +
          '<span class="butterfly-bar__val">+' +
          pv.toFixed(4) +
          "</span>" +
          "</div>";
      }
      if (sv != null && sv >= 0) {
        var pctS = ((Math.abs(sv) / plotMax) * 100).toFixed(1);
        html +=
          '<div class="butterfly-bar butterfly-bar--pos-secondary" ' +
          'style="width:' +
          pctS +
          '%" ' +
          'title="' +
          secondaryLabel +
          ": +" +
          sv.toFixed(6) +
          '"></div>';
      }
      html += "</div>";

      html += "</div>";
    }

    html += "</div>";

    html += '<details style="margin-top:var(--sp-4)">';
    html += "<summary>Detailed Charge Table</summary>";
    html +=
      '<table class="result-table" style="margin-top:var(--sp-2)"><thead><tr>' +
      "<th>#</th><th>Element</th>";
    if (mull.length) html += "<th>Mulliken</th>";
    if (lowd.length) html += "<th>Löwdin</th>";
    html += "</tr></thead><tbody>";
    for (var i = 0; i < n; i++) {
      var el = atoms[i]
        ? atoms[i].element || atoms[i].symbol || atoms[i][0] || "?"
        : "?";
      html += "<tr><td>" + (i + 1) + "</td><td>" + esc(el) + "</td>";
      if (mull.length) {
        var mv = chargeVal(mull, i);
        html += "<td>" + (mv != null ? mv.toFixed(6) : "—") + "</td>";
      }
      if (lowd.length) {
        var lv = chargeVal(lowd, i);
        html += "<td>" + (lv != null ? lv.toFixed(6) : "—") + "</td>";
      }
      html += "</tr>";
    }
    html += "</tbody></table></details>";

    return html;
  }

  function renderJSON(r) {
    var json;
    /* Remove huge base64 fields for readability */
    var cleaned = App.clone(r);
    var viz = cleaned.visualization || {};
    if (viz.orbital_cube_b64)
      viz.orbital_cube_b64 =
        "[base64 data omitted, " + viz.orbital_cube_b64.length + " chars]";
    if (viz.esp_cube_b64)
      viz.esp_cube_b64 =
        "[base64 data omitted, " + viz.esp_cube_b64.length + " chars]";
    if (viz.density_cube_b64)
      viz.density_cube_b64 =
        "[base64 data omitted, " + viz.density_cube_b64.length + " chars]";
    if (cleaned.orbital_cube_b64) cleaned.orbital_cube_b64 = "[omitted]";
    if (cleaned.esp_cube_b64) cleaned.esp_cube_b64 = "[omitted]";
    if (cleaned.density_cube_b64) cleaned.density_cube_b64 = "[omitted]";
    if (viz.orbital && viz.orbital.cube_b64) viz.orbital.cube_b64 = "[omitted]";
    if (viz.esp && viz.esp.cube_b64) viz.esp.cube_b64 = "[omitted]";
    if (viz.density && viz.density.cube_b64) viz.density.cube_b64 = "[omitted]";
    delete cleaned._mulliken_raw;
    delete cleaned._lowdin_raw;
    delete cleaned._orbital_index_offset;
    delete cleaned._orbital_labels;
    try {
      json = JSON.stringify(cleaned, null, 2);
    } catch (_) {
      json = String(r);
    }
    return '<pre class="result-json">' + esc(json) + "</pre>";
  }

  function saveSnapshot() {
    if (!state.jobId) return;
    var existing = App.getUISnapshot(state.jobId) || {};
    App.saveUISnapshot(
      state.jobId,
      Object.assign({}, existing, {
        activeTab: state.activeTab,
        timestamp: Date.now(),
      }),
    );
  }

  function restoreSnapshot(jobId) {
    var snap = App.getUISnapshot(jobId);
    if (snap && snap.activeTab) state.activeTab = snap.activeTab;
  }

  function update(result, jobId, source) {
    var normalized = normalizeResult(result);

    if (normalized) {
      var label = buildResultLabel(normalized, sessionResults.length + 1);
      var entry = {
        id: jobId || "local-" + Date.now(),
        label: label,
        result: normalized,
        jobId: jobId,
        timestamp: Date.now(),
      };

      // Check if it's an update to an existing job in the session
      var existingIdx = -1;
      if (jobId) {
        for (var i = 0; i < sessionResults.length; i++) {
          if (sessionResults[i].jobId === jobId) {
            existingIdx = i;
            break;
          }
        }
      }

      if (existingIdx >= 0) {
        sessionResults[existingIdx] = entry;
        if (activeSessionIdx === existingIdx) {
          state.result = normalized;
        }
      } else {
        sessionResults.push(entry);
        // Cap sessionResults to prevent unbounded memory growth
        while (sessionResults.length > 50) {
          sessionResults.shift();
        }
        activeSessionIdx = sessionResults.length - 1;
        state.result = normalized;
        state.jobId = jobId || null;
      }
    } else {
      state.result = null;
      state.jobId = null;
    }

    renderSessionTabs();
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
      if (available.indexOf(state.activeTab) === -1)
        state.activeTab = decideFocusTab(normalized, available);
    } else {
      state.activeTab = decideFocusTab(normalized, available);
    }
    renderTabs(available, state.activeTab);
    renderContent(state.activeTab, normalized);
    saveSnapshot();
  }

  App.on("result:changed", function (d) {
    update(d.result, d.jobId, d.source);
  });

  document.addEventListener("keydown", function (e) {
    var tag = document.activeElement ? document.activeElement.tagName : "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    var num = parseInt(e.key, 10);
    if (
      num >= 1 &&
      num <= 6 &&
      state.tabs.length > 0 &&
      num - 1 < state.tabs.length
    ) {
      switchTab(state.tabs[num - 1]);
    }
  });

  App.results = {
    getState: function () {
      return Object.assign({}, state);
    },
    switchTab: switchTab,
  };
})();
```

---

## 파일: `src/qcviz_mcp/web/static/app.js` (384줄, 13205bytes)

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
  var $statusDot = document.querySelector(
    "#globalStatus .status-indicator__dot",
  );
  var $statusText = document.querySelector(
    "#globalStatus .status-indicator__text",
  );
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
    // Auto-reset error status after 8 seconds to prevent permanently stuck indicators
    if (s.kind === "error") {
      setTimeout(function () {
        if (App.store.status.kind === "error" && App.store.status.at === s.at) {
          App.setStatus("Ready", "idle", "app");
        }
      }, 8000);
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
    $shortcutsBtn.addEventListener("click", function () {
      openModal($shortcutsModal);
    });
  }

  if ($shortcutsModal) {
    $shortcutsModal.addEventListener("click", function (e) {
      if (
        e.target.hasAttribute("data-close") ||
        e.target.closest("[data-close]")
      ) {
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
    if (
      job.user_query &&
      typeof job.user_query === "string" &&
      job.user_query.trim()
    ) {
      var q = job.user_query.trim();
      return q.length > 40 ? q.substring(0, 40) + "\u2026" : q;
    }

    var molName =
      job.molecule_name ||
      job.molecule ||
      (job.result &&
        (job.result.structure_name || job.result.structure_query)) ||
      (job.payload &&
        (job.payload.structure_query ||
          job.payload.molecule_name ||
          job.payload.molecule));
    var method =
      job.method ||
      (job.result && job.result.method) ||
      (job.payload && job.payload.method) ||
      "";
    var basis =
      job.basis_set ||
      (job.result && job.result.basis_set) ||
      (job.payload && job.payload.basis_set) ||
      "";
    var jobType =
      job.job_type ||
      (job.result && job.result.job_type) ||
      (job.payload && job.payload.job_type) ||
      "computation";

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
    var method =
      job.method ||
      (job.result && job.result.method) ||
      (job.payload && job.payload.method) ||
      "";
    if (method) parts.push(method);
    var basis =
      job.basis_set ||
      (job.result && job.result.basis_set) ||
      (job.payload && job.payload.basis_set) ||
      "";
    if (basis) parts.push(basis);
    if (parts.length > 0) return parts.join(" \u00B7 ");

    // Fallback to timestamp
    var ts = job.submitted_at || job.created_at || job.updated_at;
    if (ts) {
      var d = new Date(typeof ts === "number" && ts < 1e12 ? ts * 1000 : ts);
      return (
        d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) +
        " " +
        d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
      );
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
    return String(s || "")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function renderHistory() {
    if (!$historyList) return;

    var jobs = App.store.jobOrder
      .map(function (id) {
        return App.store.jobsById[id];
      })
      .filter(Boolean);

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
        ]
          .join(" ")
          .toLowerCase();
        return searchable.indexOf(q) !== -1;
      });
    }

    // Remove old items
    var oldItems = $historyList.querySelectorAll(".history-item");
    oldItems.forEach(function (el) {
      el.remove();
    });

    if (filtered.length === 0) {
      if ($historyEmpty) {
        $historyEmpty.hidden = false;
        var p = $historyEmpty.querySelector("p");
        if (p)
          p.textContent = historyFilter
            ? "No matching jobs"
            : "No previous computations";
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
      var energy = job.result
        ? job.result.total_energy_hartree != null
          ? job.result.total_energy_hartree
          : job.result.energy
        : null;
      var energyStr = energy != null ? Number(energy).toFixed(4) + " Ha" : "";
      var isActive = id === activeJobId;

      html +=
        '<div class="history-item' +
        (isActive ? " history-item--active" : "") +
        '" data-job-id="' +
        escAttr(id) +
        '">' +
        '<span class="history-item__status history-item__status--' +
        escAttr(status) +
        '"></span>' +
        '<div class="history-item__info">' +
        '<div class="history-item__title">' +
        esc(name) +
        "</div>" +
        '<div class="history-item__detail">' +
        esc(detail) +
        "</div>" +
        "</div>" +
        (energyStr
          ? '<span class="history-item__energy">' + esc(energyStr) + "</span>"
          : "") +
        "</div>";
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
        var jobs = Array.isArray(data) ? data : data.items || data.jobs || [];

        var sortedJobs = jobs.sort(function (a, b) {
          return (a.created_at || 0) - (b.created_at || 0);
        });
        sortedJobs.forEach(function (j) {
          App.upsertJob(j);
        });

        // Auto-activate last job if none active
        if (!App.store.activeJobId && App.store.jobOrder.length > 0) {
          App.setActiveJob(App.store.jobOrder[0]);
        }

        renderHistory();
        renderSessionTabs();
      })
      .catch(function (e) {
        console.error("fetchHistory error:", e);
      });
  }

  if ($btnRefresh) {
    $btnRefresh.addEventListener("click", function () {
      $btnRefresh.classList.add("is-spinning");
      fetchHistory()
        .then(function () {
          setTimeout(function () {
            $btnRefresh.classList.remove("is-spinning");
          }, 600);
        })
        .catch(function () {
          setTimeout(function () {
            $btnRefresh.classList.remove("is-spinning");
          }, 600);
        });
    });
  }

  /* ─── Session Tabs ─── */
  var $sessionTabsContainer = document.getElementById("sessionTabsContainer");
  var $sessionTabs = document.getElementById("sessionTabs");

  function renderSessionTabs() {
    if (!$sessionTabs || !$sessionTabsContainer) return;
    var maxTabs = 15;
    var order = App.store.jobOrder.slice(0, maxTabs);

    if (order.length === 0) {
      $sessionTabsContainer.hidden = true;
      return;
    }

    $sessionTabsContainer.hidden = false;
    var html = "";

    order.forEach(function (id) {
      var job = App.store.jobsById[id];
      if (!job) return;

      var isActive = id === App.store.activeJobId;
      var name = job.molecule_name || job.user_query || id;
      if (name.length > 20) name = name.substring(0, 20) + "...";

      var method = job.method || "";
      var badge = "";
      if (job.status === "running") badge = " ⏳";
      else if (job.status === "failed") badge = " ❌";

      var displayStr = name + (method ? " (" + method + ")" : "") + badge;

      html +=
        '<div class="session-tab' +
        (isActive ? " session-tab--active" : "") +
        '" data-job-id="' +
        escAttr(id) +
        '" title="' +
        escAttr(job.user_query || "") +
        '">' +
        esc(displayStr) +
        "</div>";
    });

    $sessionTabs.innerHTML = html;
  }

  if ($sessionTabs) {
    $sessionTabs.addEventListener("click", function (e) {
      var tab = e.target.closest(".session-tab");
      if (!tab) return;
      var jid = tab.getAttribute("data-job-id");
      if (jid && jid !== App.store.activeJobId) {
        App.setActiveJob(jid);
      }
    });
  }

  App.on("jobs:changed", function () {
    renderHistory();
    renderSessionTabs();
  });

  App.on("activejob:changed", function () {
    renderHistory();
    renderSessionTabs();
  });

  /* ─── Init ─── */
  fetchHistory();
  renderHistory();

  console.log(
    "%c QCViz-MCP Enterprise v5 %c Loaded ",
    "background:linear-gradient(135deg,#6366f1,#8b5cf6);color:white;font-weight:bold;padding:3px 8px;border-radius:4px 0 0 4px;",
    "background:#18181b;color:#a1a1aa;padding:3px 8px;border-radius:0 4px 4px 0;",
  );
})();
```

---

## 파일: `src/qcviz_mcp/web/static/style.css` (517줄, 39340bytes)

```css
html,
body {
  height: 100vh;
  overflow: hidden;
}
/* ═══════════════════════════════════════════════════════
   QCViz-MCP Enterprise v5 — Design System
   ═══════════════════════════════════════════════════════ */

:root {
  --font-sans:
    "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-mono: "JetBrains Mono", "Fira Code", "Cascadia Code", monospace;
  --radius-xs: 4px;
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;
  --radius-xl: 20px;
  --radius-full: 9999px;
  --sp-1: 4px;
  --sp-2: 8px;
  --sp-3: 12px;
  --sp-4: 16px;
  --sp-5: 20px;
  --sp-6: 24px;
  --sp-8: 32px;
  --sp-10: 40px;
  --blur-sm: 8px;
  --blur-md: 16px;
  --blur-lg: 32px;
  --blur-xl: 48px;
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
  --ease-smooth: cubic-bezier(0.4, 0, 0.2, 1);
  --duration-fast: 120ms;
  --duration-base: 200ms;
  --duration-slow: 350ms;
  --z-base: 1;
  --z-sticky: 10;
  --z-controls: 20;
  --z-overlay: 100;
  --z-modal: 1000;
}

[data-theme="dark"] {
  --bg-0: #09090b;
  --bg-1: #0c0c0f;
  --bg-2: #111115;
  --bg-3: #18181b;
  --bg-4: #1f1f23;
  --bg-5: #27272a;
  --surface-0: rgba(17, 17, 21, 0.72);
  --surface-1: rgba(24, 24, 27, 0.65);
  --surface-2: rgba(31, 31, 35, 0.6);
  --surface-raised: rgba(39, 39, 42, 0.55);
  --surface-overlay: rgba(9, 9, 11, 0.88);
  --border-0: rgba(255, 255, 255, 0.06);
  --border-1: rgba(255, 255, 255, 0.09);
  --border-2: rgba(255, 255, 255, 0.12);
  --border-3: rgba(255, 255, 255, 0.16);
  --border-focus: rgba(99, 102, 241, 0.5);
  --text-0: #fafafa;
  --text-1: #e4e4e7;
  --text-2: #a1a1aa;
  --text-3: #71717a;
  --text-4: #52525b;
  --accent: #6366f1;
  --accent-hover: #818cf8;
  --accent-muted: rgba(99, 102, 241, 0.15);
  --accent-subtle: rgba(99, 102, 241, 0.08);
  --accent-2: #8b5cf6;
  --success: #22c55e;
  --success-muted: rgba(34, 197, 94, 0.12);
  --warning: #f59e0b;
  --warning-muted: rgba(245, 158, 11, 0.12);
  --error: #ef4444;
  --error-muted: rgba(239, 68, 68, 0.12);
  --info: #3b82f6;
  --info-muted: rgba(59, 130, 246, 0.12);
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.3);
  --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.4);
  --shadow-lg: 0 12px 40px rgba(0, 0, 0, 0.5);
  --shadow-xl: 0 24px 64px rgba(0, 0, 0, 0.6);
  --shadow-glow: 0 0 40px rgba(99, 102, 241, 0.06);
  color-scheme: dark;
}

[data-theme="light"] {
  --bg-0: #ffffff;
  --bg-1: #fafafa;
  --bg-2: #f4f4f5;
  --bg-3: #e4e4e7;
  --bg-4: #d4d4d8;
  --bg-5: #a1a1aa;
  --surface-0: rgba(255, 255, 255, 0.82);
  --surface-1: rgba(250, 250, 250, 0.78);
  --surface-2: rgba(244, 244, 245, 0.72);
  --surface-raised: rgba(255, 255, 255, 0.92);
  --surface-overlay: rgba(255, 255, 255, 0.92);
  --border-0: rgba(0, 0, 0, 0.05);
  --border-1: rgba(0, 0, 0, 0.08);
  --border-2: rgba(0, 0, 0, 0.12);
  --border-3: rgba(0, 0, 0, 0.16);
  --border-focus: rgba(99, 102, 241, 0.4);
  --text-0: #09090b;
  --text-1: #18181b;
  --text-2: #52525b;
  --text-3: #71717a;
  --text-4: #a1a1aa;
  --accent: #6366f1;
  --accent-hover: #4f46e5;
  --accent-muted: rgba(99, 102, 241, 0.1);
  --accent-subtle: rgba(99, 102, 241, 0.05);
  --accent-2: #7c3aed;
  --success: #16a34a;
  --success-muted: rgba(22, 163, 74, 0.08);
  --warning: #d97706;
  --warning-muted: rgba(217, 119, 6, 0.08);
  --error: #dc2626;
  --error-muted: rgba(220, 38, 38, 0.08);
  --info: #2563eb;
  --info-muted: rgba(37, 99, 235, 0.08);
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.04);
  --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.06);
  --shadow-lg: 0 12px 40px rgba(0, 0, 0, 0.08);
  --shadow-xl: 0 24px 64px rgba(0, 0, 0, 0.1);
  --shadow-glow: 0 0 40px rgba(99, 102, 241, 0.03);
  color-scheme: light;
}

/* Reset */
*,
*::before,
*::after {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}
html {
  font-family: var(--font-sans);
  font-size: 14px;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  text-rendering: optimizeLegibility;
  scroll-behavior: smooth;
}
body {
  background: var(--bg-0);
  color: var(--text-1);
  min-height: 100dvh;
  overflow-x: hidden;
  transition:
    background var(--duration-slow) var(--ease-smooth),
    color var(--duration-base) var(--ease-smooth);
}
a {
  color: var(--accent);
  text-decoration: none;
  transition: color var(--duration-fast);
}
a:hover {
  color: var(--accent-hover);
}
::selection {
  background: var(--accent-muted);
  color: var(--text-0);
}
:focus-visible {
  outline: 2px solid var(--border-focus);
  outline-offset: 2px;
}
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: var(--border-2);
  border-radius: var(--radius-full);
}
::-webkit-scrollbar-thumb:hover {
  background: var(--text-4);
}

/* App Shell */
.app-shell {
  display: grid;
  gap: 18px;
  padding: 18px;
  height: 100vh;
  overflow: hidden;
  box-sizing: border-box;
}

/* Top Bar */
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 52px;
  padding: 0 var(--sp-4);
  background: var(--surface-0);
  backdrop-filter: blur(var(--blur-lg));
  -webkit-backdrop-filter: blur(var(--blur-lg));
  border: 1px solid var(--border-0);
  border-radius: var(--radius-lg);
  position: sticky;
  top: var(--sp-3);
  z-index: var(--z-sticky);
  transition: box-shadow var(--duration-base) var(--ease-out);
}
.topbar:hover {
  box-shadow: var(--shadow-sm);
}
.topbar__left,
.topbar__center,
.topbar__right {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}
.topbar__left {
  flex: 1;
}
.topbar__center {
  flex: 0 0 auto;
}
.topbar__right {
  flex: 1;
  justify-content: flex-end;
}
.topbar__logo {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
.topbar__title {
  font-weight: 600;
  font-size: 15px;
  color: var(--text-0);
  letter-spacing: -0.02em;
}
.topbar__badge {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: var(--radius-full);
  background: var(--accent-muted);
  color: var(--accent);
  letter-spacing: 0.02em;
  text-transform: uppercase;
  vertical-align: super;
}

/* Status */
.status-indicator {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-1) var(--sp-3);
  border-radius: var(--radius-full);
  background: var(--surface-1);
  border: 1px solid var(--border-0);
  font-size: 12px;
  color: var(--text-2);
  user-select: none;
}
.status-indicator__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  transition:
    background var(--duration-base),
    box-shadow var(--duration-base);
}
.status-indicator__dot[data-kind="idle"] {
  background: var(--text-4);
}
.status-indicator__dot[data-kind="running"],
.status-indicator__dot[data-kind="computing"] {
  background: var(--info);
  box-shadow: 0 0 8px rgba(59, 130, 246, 0.4);
  animation: pulse-dot 1.5s ease-in-out infinite;
}
.status-indicator__dot[data-kind="success"],
.status-indicator__dot[data-kind="completed"] {
  background: var(--success);
  box-shadow: 0 0 8px rgba(34, 197, 94, 0.3);
}
.status-indicator__dot[data-kind="error"],
.status-indicator__dot[data-kind="failed"] {
  background: var(--error);
  box-shadow: 0 0 8px rgba(239, 68, 68, 0.3);
}
@keyframes pulse-dot {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.5;
    transform: scale(1.4);
  }
}

/* Buttons */
.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid var(--border-1);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
  flex-shrink: 0;
}
.icon-btn:hover {
  background: var(--surface-2);
  color: var(--text-0);
  border-color: var(--border-2);
  transform: translateY(-1px);
}
.icon-btn:active {
  transform: translateY(0);
}
.icon-btn--sm {
  width: 28px;
  height: 28px;
}
[data-theme="dark"] .icon-moon {
  display: none;
}
[data-theme="light"] .icon-sun {
  display: none;
}
.chip-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  height: 28px;
  padding: 0 var(--sp-3);
  border: 1px solid var(--border-1);
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--text-2);
  font-size: 12px;
  font-weight: 500;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
  white-space: nowrap;
}
.chip-btn:hover {
  background: var(--surface-2);
  color: var(--text-0);
  border-color: var(--border-2);
}
.icon-btn.is-spinning svg {
  animation: spin 0.6s linear infinite;
}
@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

/* Dashboard Grid — 뷰어 최소 55% 면적 보장 */
.dashboard {
  display: grid;
  grid-template-columns: 1fr 1fr;
  grid-template-rows: minmax(450px, 1.8fr) minmax(180px, 0.6fr);
  grid-template-areas: "viewer chat" "results history";
  gap: var(--sp-3);
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.panel--results,
.panel--history {
  max-height: 45vh;
  overflow: hidden;
}

.panel--results .results-content,
.panel--history .history-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

/* Mobile: < 768px */
@media (max-width: 767px) {
  .dashboard {
    grid-template-columns: 1fr;
    grid-template-rows: minmax(380px, 1fr) auto auto auto;
    grid-template-areas: "viewer" "chat" "results" "history";
    overflow-y: auto;
  }
  .panel--results,
  .panel--history {
    max-height: none;
  }
}

/* Tablet: 768px – 1099px */
@media (min-width: 768px) and (max-width: 1099px) {
  .dashboard {
    grid-template-columns: 1fr 1fr;
    grid-template-rows: minmax(380px, 1.8fr) minmax(160px, 0.6fr);
    grid-template-areas: "viewer chat" "results history";
  }
  .panel--viewer .viewer-container {
    min-height: 380px;
  }
}

/* Desktop wide: ≥ 1500px */
@media (min-width: 1500px) {
  .dashboard {
    grid-template-columns: 1.3fr 0.9fr 0.8fr;
    grid-template-rows: 1.8fr 0.6fr;
    grid-template-areas: "viewer chat history" "results results history";
  }
}
.panel--viewer {
  grid-area: viewer;
}
.panel--chat {
  grid-area: chat;
}
.panel--results {
  grid-area: results;
}
.panel--history {
  grid-area: history;
}

/* Panel */
.panel {
  display: flex;
  flex-direction: column;
  background: var(--surface-0);
  backdrop-filter: blur(var(--blur-md));
  -webkit-backdrop-filter: blur(var(--blur-md));
  border: 1px solid var(--border-0);
  border-radius: var(--radius-lg);
  overflow: hidden;
  transition:
    box-shadow var(--duration-slow) var(--ease-out),
    border-color var(--duration-base) var(--ease-out);
  min-height: 0;
}
.panel:hover {
  border-color: var(--border-1);
  box-shadow: var(--shadow-sm), var(--shadow-glow);
}
.panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--sp-3) var(--sp-4);
  border-bottom: 1px solid var(--border-0);
  flex-shrink: 0;
  min-height: 44px;
}
.panel__title {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-3);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.panel__title svg {
  color: var(--text-4);
  flex-shrink: 0;
}
.panel__actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

/* Viewer Panel */
.viewer-container {
  position: relative;
  flex: 1;
  min-height: 300px;
  background: var(--bg-1);
  overflow: hidden;
  transition: background var(--duration-slow) var(--ease-smooth);
}
.viewer-3d {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  z-index: var(--z-base);
  overflow: hidden;
}
.viewer-empty {
  position: absolute;
  inset: 0;
  z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--sp-3);
  pointer-events: none;
  animation: fadeIn var(--duration-slow) var(--ease-out);
}
.viewer-empty[hidden] {
  display: none;
}
.viewer-empty__icon {
  color: var(--text-4);
}
.viewer-empty__text {
  font-size: 14px;
  color: var(--text-3);
  text-align: center;
}
.viewer-empty__hint {
  font-size: 12px;
  color: var(--text-4);
  font-family: var(--font-mono);
}

.viewer-controls {
  position: absolute;
  bottom: var(--sp-3);
  left: var(--sp-3);
  right: var(--sp-3);
  z-index: var(--z-controls);
  display: flex;
  align-items: center;
  gap: var(--sp-4);
  padding: var(--sp-2) var(--sp-3);
  background: var(--surface-overlay);
  backdrop-filter: blur(var(--blur-xl));
  -webkit-backdrop-filter: blur(var(--blur-xl));
  border: 1px solid var(--border-1);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  animation: slideUp var(--duration-slow) var(--ease-out);
  flex-wrap: wrap;
  overflow-x: auto;
}
.viewer-controls[hidden] {
  display: none;
}
.viewer-controls::-webkit-scrollbar {
  display: none;
}
.viewer-controls__group {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-shrink: 0;
}
.viewer-controls__group[hidden] {
  display: none;
}
.viewer-controls__label {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  white-space: nowrap;
}
.viewer-controls__value {
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--text-2);
  min-width: 36px;
  text-align: right;
}

.viewer-legend {
  position: absolute;
  top: var(--sp-3);
  right: var(--sp-3);
  z-index: var(--z-controls);
  padding: var(--sp-2) var(--sp-3);
  background: var(--surface-overlay);
  backdrop-filter: blur(var(--blur-xl));
  -webkit-backdrop-filter: blur(var(--blur-xl));
  border: 1px solid var(--border-1);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  font-size: 11px;
  color: var(--text-2);
  animation: fadeIn var(--duration-slow) var(--ease-out);
}
.viewer-legend[hidden] {
  display: none;
}
.viewer-legend__title {
  font-weight: 600;
  color: var(--text-1);
  margin-bottom: var(--sp-1);
  font-size: 11px;
  letter-spacing: 0.02em;
}
.viewer-legend__row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-top: 3px;
}
.viewer-legend__swatch {
  width: 12px;
  height: 12px;
  border-radius: 3px;
  flex-shrink: 0;
  border: 1px solid var(--border-0);
}

/* Segmented */
.segmented {
  display: inline-flex;
  background: var(--bg-3);
  border-radius: var(--radius-sm);
  padding: 2px;
  gap: 1px;
}
.segmented__btn {
  padding: 3px 10px;
  border: none;
  border-radius: var(--radius-xs);
  background: transparent;
  color: var(--text-3);
  font-size: 11px;
  font-weight: 500;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
  white-space: nowrap;
}
.segmented__btn:hover {
  color: var(--text-1);
}
.segmented__btn--active {
  background: var(--surface-raised);
  color: var(--text-0);
  box-shadow: var(--shadow-sm);
}

/* Range */
.range-input {
  -webkit-appearance: none;
  appearance: none;
  width: 80px;
  height: 4px;
  background: var(--bg-4);
  border-radius: var(--radius-full);
  outline: none;
  cursor: pointer;
}
.range-input:hover {
  background: var(--bg-5);
}
.range-input::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 14px;
  height: 14px;
  background: var(--accent);
  border-radius: 50%;
  box-shadow: 0 0 6px rgba(99, 102, 241, 0.3);
  border: 2px solid var(--bg-0);
  transition: transform var(--duration-fast) var(--ease-spring);
}
.range-input::-webkit-slider-thumb:hover {
  transform: scale(1.2);
}
.range-input::-moz-range-thumb {
  width: 14px;
  height: 14px;
  background: var(--accent);
  border: 2px solid var(--bg-0);
  border-radius: 50%;
}

/* Toggle */
.toggle-btn {
  padding: 3px 10px;
  border: 1px solid var(--border-1);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-3);
  font-size: 11px;
  font-weight: 500;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}
.toggle-btn[data-active="true"] {
  background: var(--accent-muted);
  color: var(--accent);
  border-color: rgba(99, 102, 241, 0.3);
}
.toggle-btn:hover {
  border-color: var(--border-2);
}

/* Viewer select */
.viewer-select {
  padding: 3px 8px;
  border: 1px solid var(--border-1);
  border-radius: var(--radius-sm);
  background: var(--bg-3);
  color: var(--text-1);
  font-size: 11px;
  font-family: var(--font-mono);
  cursor: pointer;
  outline: none;
  max-width: 160px;
  transition: border-color var(--duration-fast);
}
.viewer-select:focus {
  border-color: var(--accent);
}
.viewer-select option {
  background: var(--bg-2);
  color: var(--text-1);
}

/* Chat Panel */
.panel--chat {
  display: flex;
  flex-direction: column;
}
.ws-status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-3);
}
.ws-status__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  transition:
    background var(--duration-base),
    box-shadow var(--duration-base);
}
.ws-status__dot[data-connected="false"] {
  background: var(--error);
}
.ws-status__dot[data-connected="true"] {
  background: var(--success);
  box-shadow: 0 0 6px rgba(34, 197, 94, 0.4);
}

.chat-scroll {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  min-height: 0;
  scroll-behavior: smooth;
}
.chat-messages {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  padding: var(--sp-3) var(--sp-4);
}

.chat-msg {
  display: flex;
  gap: var(--sp-3);
  padding: var(--sp-3);
  border-radius: var(--radius-md);
  transition: background var(--duration-fast);
  animation: chatMsgIn var(--duration-slow) var(--ease-out);
}
.chat-msg:hover {
  background: var(--surface-1);
}
@keyframes chatMsgIn {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.chat-msg__avatar {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 600;
}
.chat-msg__avatar--system {
  background: var(--accent-muted);
  color: var(--accent);
}
.chat-msg__avatar--user {
  background: var(--surface-2);
  color: var(--text-2);
}
.chat-msg__avatar--assistant {
  background: linear-gradient(
    135deg,
    var(--accent-muted),
    rgba(139, 92, 246, 0.15)
  );
  color: var(--accent);
}
.chat-msg__avatar--error {
  background: var(--error-muted);
  color: var(--error);
}

.chat-msg__body {
  flex: 1;
  min-width: 0;
}
.chat-msg__meta {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-bottom: 2px;
}
.chat-msg__name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-1);
}
.chat-msg__time {
  font-size: 11px;
  color: var(--text-4);
}
.chat-msg__text {
  font-size: 13px;
  line-height: 1.65;
  color: var(--text-1);
  word-break: break-word;
}
.chat-msg__text strong {
  font-weight: 600;
  color: var(--text-0);
}
.chat-msg__text code {
  font-family: var(--font-mono);
  font-size: 12px;
  padding: 1px 5px;
  background: var(--surface-2);
  border: 1px solid var(--border-0);
  border-radius: var(--radius-xs);
  color: var(--accent);
}

/* Chat progress */
.chat-progress {
  margin-top: var(--sp-2);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.chat-progress__bar {
  height: 3px;
  background: var(--bg-4);
  border-radius: var(--radius-full);
  overflow: hidden;
  margin-top: var(--sp-1);
}
.chat-progress__fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent), var(--accent-2));
  border-radius: var(--radius-full);
  transition: width var(--duration-slow) var(--ease-out);
  width: 0%;
}
.chat-progress__fill--indeterminate {
  width: 40% !important;
  animation: indeterminate 1.5s ease-in-out infinite;
}
@keyframes indeterminate {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(350%);
  }
}
.chat-progress__steps {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.chat-progress__step {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: 12px;
  font-family: var(--font-mono);
  color: var(--text-3);
  transition: color var(--duration-fast);
  animation: fadeIn var(--duration-base) var(--ease-out);
}
.chat-progress__step--active {
  color: var(--info);
}
.chat-progress__step--done {
  color: var(--success);
}
.chat-progress__step--error {
  color: var(--error);
}
.chat-progress__icon {
  width: 16px;
  height: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

/* Typing */
.chat-typing {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: var(--sp-2) 0;
}
.chat-typing__dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--text-4);
  animation: typingBounce 1.4s ease-in-out infinite;
}
.chat-typing__dot:nth-child(2) {
  animation-delay: 0.2s;
}
.chat-typing__dot:nth-child(3) {
  animation-delay: 0.4s;
}
@keyframes typingBounce {
  0%,
  60%,
  100% {
    transform: translateY(0);
    opacity: 0.3;
  }
  30% {
    transform: translateY(-6px);
    opacity: 1;
  }
}

/* Chat input */
.chat-input-area {
  border-top: 1px solid var(--border-0);
  padding: var(--sp-3) var(--sp-4);
  flex-shrink: 0;
}
.chat-suggestions {
  display: flex;
  gap: var(--sp-2);
  margin-bottom: var(--sp-3);
  flex-wrap: wrap;
}
.chat-suggestions:empty,
.chat-suggestions[hidden] {
  display: none;
}
.suggestion-chip {
  padding: var(--sp-1) var(--sp-3);
  border: 1px solid var(--border-1);
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--text-3);
  font-size: 12px;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
  white-space: nowrap;
}
.suggestion-chip:hover {
  background: var(--accent-muted);
  border-color: rgba(99, 102, 241, 0.3);
  color: var(--accent);
}

.chat-form {
  position: relative;
}
.chat-form__input-wrap {
  display: flex;
  align-items: flex-end;
  gap: var(--sp-2);
  background: var(--surface-1);
  border: 1px solid var(--border-1);
  border-radius: var(--radius-md);
  padding: var(--sp-2) var(--sp-3);
  transition:
    border-color var(--duration-fast),
    box-shadow var(--duration-fast);
}
.chat-form__input-wrap:focus-within {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-muted);
}
.chat-form__input {
  flex: 1;
  border: none;
  background: transparent;
  color: var(--text-0);
  font-family: var(--font-sans);
  font-size: 13px;
  line-height: 1.5;
  resize: none;
  outline: none;
  min-height: 20px;
  max-height: 120px;
}
.chat-form__input::placeholder {
  color: var(--text-4);
}
.chat-form__send {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--accent);
  color: white;
  cursor: pointer;
  flex-shrink: 0;
  transition: all var(--duration-fast) var(--ease-out);
}
.chat-form__send:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}
.chat-form__send:not(:disabled):hover {
  background: var(--accent-hover);
  transform: scale(1.05);
}
.chat-form__send:not(:disabled):active {
  transform: scale(0.98);
}
.chat-form__hint {
  font-size: 11px;
  color: var(--text-4);
  margin-top: var(--sp-2);
  text-align: right;
}
.chat-form__hint kbd {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 1px 4px;
  background: var(--surface-2);
  border: 1px solid var(--border-1);
  border-radius: 3px;
  color: var(--text-3);
}

/* Results Panel */
.panel--results {
  min-height: 200px;
}
.results-tabs {
  display: flex;
  gap: 0;
  padding: 0 var(--sp-4);
  border-bottom: 1px solid var(--border-0);
  overflow-x: auto;
  flex-shrink: 0;
}
.results-tabs:empty {
  display: none;
}
.results-tabs::-webkit-scrollbar {
  display: none;
}
.tab-btn {
  position: relative;
  padding: var(--sp-2) var(--sp-3);
  border: none;
  background: transparent;
  color: var(--text-3);
  font-size: 12px;
  font-weight: 500;
  font-family: var(--font-sans);
  cursor: pointer;
  white-space: nowrap;
  transition: color var(--duration-fast);
}
.tab-btn:hover {
  color: var(--text-1);
}
.tab-btn--active {
  color: var(--text-0);
}
.tab-btn--active::after {
  content: "";
  position: absolute;
  bottom: -1px;
  left: var(--sp-3);
  right: var(--sp-3);
  height: 2px;
  background: var(--accent);
  border-radius: 1px 1px 0 0;
  animation: tabLine var(--duration-base) var(--ease-out);
}
@keyframes tabLine {
  from {
    transform: scaleX(0);
  }
  to {
    transform: scaleX(1);
  }
}
.results-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--sp-4);
  min-height: 0;
}
.results-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 120px;
  color: var(--text-4);
  font-size: 13px;
  text-align: center;
}
.results-empty[hidden] {
  display: none;
}
.result-card {
  animation: fadeIn var(--duration-slow) var(--ease-out);
}
.metrics-grid {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}
.result-metric {
  display: inline-flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--sp-3);
  background: var(--surface-1);
  border: 1px solid var(--border-0);
  border-radius: var(--radius-md);
  min-width: 130px;
  flex: 1 1 130px;
  max-width: 220px;
  transition:
    border-color var(--duration-fast),
    box-shadow var(--duration-fast);
}
.result-metric:hover {
  border-color: var(--border-2);
  box-shadow: var(--shadow-sm);
}
.result-metric__label {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.result-metric__value {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-0);
  font-family: var(--font-mono);
  letter-spacing: -0.03em;
  line-height: 1.3;
}
.result-metric__unit {
  font-size: 11px;
  color: var(--text-3);
  font-weight: 400;
}

/* Energy diagram */
.energy-diagram {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--sp-3);
  background: var(--surface-1);
  border: 1px solid var(--border-0);
  border-radius: var(--radius-md);
  margin-top: var(--sp-3);
  max-height: 300px;
  overflow-y: auto;
}
.energy-diagram__title {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-2);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: var(--sp-2);
}
.energy-level {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 3px var(--sp-2);
  border-radius: var(--radius-xs);
  font-size: 11px;
  font-family: var(--font-mono);
  transition: background var(--duration-fast);
}
.energy-level:hover {
  background: var(--surface-2);
}
.energy-level--occupied {
  color: var(--accent);
}
.energy-level--virtual {
  color: var(--text-3);
}
.energy-level--homo {
  color: var(--accent);
  font-weight: 600;
  background: var(--accent-muted);
}
.energy-level--lumo {
  color: var(--warning);
  font-weight: 600;
  background: var(--warning-muted);
}
.energy-level__bar {
  width: 24px;
  height: 3px;
  border-radius: 2px;
  flex-shrink: 0;
}
.energy-level--occupied .energy-level__bar {
  background: var(--accent);
}
.energy-level--virtual .energy-level__bar {
  background: var(--text-4);
}
.energy-level--homo .energy-level__bar {
  background: var(--accent);
  height: 4px;
}
.energy-level--lumo .energy-level__bar {
  background: var(--warning);
  height: 4px;
}
.energy-level__label {
  min-width: 60px;
}
.energy-level__energy {
  flex: 1;
  text-align: right;
}
.energy-level__occ {
  min-width: 28px;
  text-align: center;
  color: var(--text-4);
  font-size: 10px;
}

.result-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.result-table th {
  text-align: left;
  font-weight: 600;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-size: 11px;
  padding: var(--sp-2) var(--sp-3);
  border-bottom: 1px solid var(--border-1);
  position: sticky;
  top: 0;
  background: var(--bg-2);
}
.result-table td {
  padding: var(--sp-2) var(--sp-3);
  border-bottom: 1px solid var(--border-0);
  color: var(--text-1);
  font-family: var(--font-mono);
  font-size: 12px;
}
.result-table tr:hover td {
  background: var(--surface-1);
}
.result-json {
  background: var(--bg-2);
  border: 1px solid var(--border-0);
  border-radius: var(--radius-md);
  padding: var(--sp-4);
  overflow: auto;
  max-height: 400px;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-2);
  white-space: pre-wrap;
  word-break: break-all;
}
.result-note {
  font-size: 12px;
  color: var(--text-3);
  margin-top: var(--sp-3);
  line-height: 1.5;
}

/* History */
.panel--history {
  min-height: 200px;
}
.history-search-wrap {
  position: relative;
  padding: var(--sp-2) var(--sp-3);
  border-bottom: 1px solid var(--border-0);
}
.history-search-icon {
  position: absolute;
  left: var(--sp-5);
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-4);
  pointer-events: none;
}
.history-search {
  width: 100%;
  padding: var(--sp-2) var(--sp-3) var(--sp-2) var(--sp-8);
  border: 1px solid var(--border-0);
  border-radius: var(--radius-sm);
  background: var(--surface-1);
  color: var(--text-1);
  font-size: 12px;
  font-family: var(--font-sans);
  outline: none;
  transition:
    border-color var(--duration-fast),
    box-shadow var(--duration-fast);
}
.history-search:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-muted);
}
.history-search::placeholder {
  color: var(--text-4);
}
.history-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--sp-2);
}
.history-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 80px;
  color: var(--text-4);
  font-size: 12px;
}
.history-empty[hidden] {
  display: none;
}
.history-item {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-2) var(--sp-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition:
    background var(--duration-fast),
    border-color var(--duration-fast);
  border: 1px solid transparent;
  animation: slideIn var(--duration-slow) var(--ease-out);
}
.history-item:hover {
  background: var(--surface-1);
}
.history-item--active {
  background: var(--accent-muted);
  border-color: rgba(99, 102, 241, 0.25);
}
.history-item__status {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.history-item__status--completed {
  background: var(--success);
}
.history-item__status--running {
  background: var(--info);
  animation: pulse-dot 1.5s ease-in-out infinite;
}
.history-item__status--failed {
  background: var(--error);
}
.history-item__status--queued {
  background: var(--warning);
}
.history-item__info {
  flex: 1;
  min-width: 0;
}
.history-item__title {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.history-item__detail {
  font-size: 11px;
  color: var(--text-4);
  margin-top: 1px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.history-item__energy {
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--text-3);
  white-space: nowrap;
  flex-shrink: 0;
}

/* Modal */
.modal {
  border: none;
  background: transparent;
  padding: 0;
  max-width: 100vw;
  max-height: 100vh;
  overflow: visible;
}
.modal::backdrop {
  background: transparent;
}
.modal__backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  z-index: 0;
  animation: fadeIn var(--duration-base) var(--ease-out);
}
.modal__content {
  position: relative;
  z-index: 1;
  background: var(--bg-2);
  border: 1px solid var(--border-1);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-xl);
  width: 440px;
  max-width: 90vw;
  margin: 15vh auto;
  animation: modalIn var(--duration-slow) var(--ease-out);
}
.modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--sp-4) var(--sp-5);
  border-bottom: 1px solid var(--border-0);
}
.modal__header h3 {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-0);
}
.modal__body {
  padding: var(--sp-5);
}
.shortcuts-grid {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.shortcut-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: var(--text-2);
}
.shortcut-keys {
  display: flex;
  align-items: center;
  gap: 3px;
}
.shortcut-plus,
.shortcut-dash {
  font-size: 11px;
  color: var(--text-4);
}
.shortcut-row kbd {
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 2px 6px;
  background: var(--surface-2);
  border: 1px solid var(--border-1);
  border-radius: var(--radius-xs);
  color: var(--text-1);
  min-width: 22px;
  text-align: center;
}
@keyframes modalIn {
  from {
    opacity: 0;
    transform: translateY(-12px) scale(0.97);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

/* Animations */
@keyframes fadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}
@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* Fullscreen */
.panel--viewer.is-fullscreen {
  position: fixed;
  inset: 0;
  z-index: var(--z-overlay);
  border-radius: 0;
  margin: 0;
  border: none;
}
.panel--viewer.is-fullscreen .viewer-container {
  min-height: 100%;
}

/* Utils */
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
.mono {
  font-family: var(--font-mono);
}
details {
  border: 1px solid var(--border-0);
  border-radius: var(--radius-sm);
  padding: var(--sp-2) var(--sp-3);
}
details summary {
  cursor: pointer;
  color: var(--text-3);
  font-size: 12px;
  font-weight: 500;
  user-select: none;
}
details summary:hover {
  color: var(--text-1);
}
details[open] summary {
  margin-bottom: var(--sp-2);
}

/* ═══ 요구사항 2: Orbital/ESP 토글 버튼 ═══ */
.viz-mode-toggle {
  display: inline-flex;
  gap: 0;
  border: 1px solid var(--border-1);
  border-radius: 6px;
  overflow: hidden;
  margin: 0 8px;
}
.viz-mode-toggle .toggle-btn {
  padding: 4px 14px;
  font-size: 12px;
  font-weight: 600;
  border: none;
  background: var(--bg-2);
  color: var(--text-2);
  cursor: pointer;
  transition:
    background 0.15s,
    color 0.15s;
}
.viz-mode-toggle .toggle-btn:not(:last-child) {
  border-right: 1px solid var(--border-1);
}
.viz-mode-toggle .toggle-btn.active {
  background: var(--accent);
  color: #fff;
}
.viz-mode-toggle .toggle-btn:hover:not(.active) {
  background: var(--bg-3);
}

/* ═══ 요구사항 3: Trajectory Player ═══ */
.trajectory-player {
  padding: 6px 12px;
  border-top: 1px solid var(--border-1);
  background: var(--bg-2);
  flex: 0 0 auto;
  z-index: 10;
  position: relative;
}
.traj-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}
.traj-btn {
  width: 32px;
  height: 32px;
  border: 1px solid var(--border-1);
  border-radius: 6px;
  background: var(--bg-1);
  cursor: pointer;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s;
  color: var(--text-1);
}
.traj-btn:hover {
  background: var(--bg-3);
}
.traj-slider {
  flex: 1;
  min-width: 100px;
  cursor: pointer;
}
.traj-label {
  font-size: 11px;
  color: var(--text-3);
  white-space: nowrap;
  min-width: 220px;
  font-family: var(--font-mono);
}

/* ═══ 요구사항 4: Session Tab Bar ═══ */
.session-tab-bar {
  display: flex;
  flex-wrap: nowrap;
  gap: 0;
  padding: 4px 8px 0;
  border-bottom: 1px solid var(--border-1);
  background: var(--bg-2);
  overflow-x: auto;
  overflow-y: hidden;
  flex: 0 0 auto;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: thin;
}
.session-tab-bar .session-tab {
  position: relative;
  padding: 5px 26px 5px 10px;
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
  border: 1px solid var(--border-1);
  border-bottom: none;
  border-radius: 6px 6px 0 0;
  background: var(--bg-3);
  color: var(--text-2);
  cursor: pointer;
  transition:
    background 0.15s,
    color 0.15s;
  flex: 0 0 auto;
}
.session-tab-bar .session-tab.active {
  background: var(--bg-1);
  color: var(--text-1);
  border-bottom: 1px solid var(--bg-1);
  margin-bottom: -1px;
  font-weight: 600;
}
.session-tab-bar .session-tab:hover:not(.active) {
  background: var(--bg-4);
}
.session-tab-bar .session-tab-close {
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  width: 14px;
  height: 14px;
  line-height: 14px;
  text-align: center;
  font-size: 13px;
  color: var(--text-3);
  border-radius: 3px;
  cursor: pointer;
  transition:
    background 0.1s,
    color 0.1s;
}
.session-tab-bar .session-tab-close:hover {
  background: rgba(200, 50, 50, 0.15);
  color: #f43f5e;
}

/* ═══ 요구사항 1: Loading Overlay ═══ */
.app-loader {
  position: fixed;
  inset: 0;
  z-index: 99999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-1);
  transition:
    opacity 0.45s ease,
    visibility 0.45s ease;
}
.app-loader.fade-out {
  opacity: 0;
  visibility: hidden;
  pointer-events: none;
}
.loader-content {
  text-align: center;
}
.loader-spinner {
  width: 48px;
  height: 48px;
  margin: 0 auto 18px;
  border: 4px solid var(--border-1);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: qcviz-loader-spin 0.75s linear infinite;
}
@keyframes qcviz-loader-spin {
  to {
    transform: rotate(360deg);
  }
}
.loader-text {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-1);
  margin: 0 0 6px;
}
.loader-sub {
  font-size: 12px;
  color: var(--text-3);
  margin: 0;
}

/* ═══ 요구사항 3: Color Scheme 선택 UI ═══ */
.scheme-preview {
  display: inline-flex;
  gap: 3px;
  margin-left: 8px;
  vertical-align: middle;
}
.swatch {
  display: inline-block;
  width: 14px;
  height: 14px;
  border-radius: 3px;
  border: 1px solid var(--border-1);
}

/* ═══════════════════════════════════════════════════════════
   Butterfly Chart — Charges Visualization
   ═══════════════════════════════════════════════════════════ */

.butterfly-legend {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
  padding: var(--sp-2) 0;
  margin-bottom: var(--sp-3);
  font-size: 11px;
  color: var(--text-2);
}
.butterfly-legend__item {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
}
.butterfly-legend__swatch {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 3px;
  border: 1px solid var(--border-0);
}
.butterfly-legend__swatch--neg {
  background: var(--error);
}
.butterfly-legend__swatch--pos {
  background: var(--info);
}
.butterfly-chart {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.butterfly-row {
  display: grid;
  grid-template-columns: 1fr 56px 1fr;
  align-items: center;
  gap: 0;
  min-height: 26px;
  transition: background var(--duration-fast);
  border-radius: var(--radius-xs);
  padding: 1px 0;
}
.butterfly-row:hover {
  background: var(--surface-1);
}
.butterfly-label {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-0);
  text-align: center;
  padding: 0 4px;
  background: var(--surface-0);
  border-left: 1px solid var(--border-1);
  border-right: 1px solid var(--border-1);
  min-height: 26px;
  z-index: 1;
}
.butterfly-label__idx {
  font-size: 10px;
  font-weight: 400;
  color: var(--text-4);
  font-family: var(--font-mono);
}
.butterfly-label__el {
  font-family: var(--font-sans);
}
.butterfly-bar-area {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 1px;
  height: 100%;
  justify-content: center;
}
.butterfly-bar-area--neg {
  align-items: flex-end;
  padding-right: 0;
}
.butterfly-bar-area--pos {
  align-items: flex-start;
  padding-left: 0;
}
.butterfly-bar {
  height: 16px;
  border-radius: 2px;
  min-width: 2px;
  max-width: 100%;
  position: relative;
  transition:
    width var(--duration-base) var(--ease-out),
    opacity var(--duration-fast);
  cursor: default;
}
.butterfly-bar:hover {
  opacity: 0.85;
}
.butterfly-bar--neg-primary {
  background: linear-gradient(270deg, var(--error), rgba(239, 68, 68, 0.6));
  border-radius: 2px 0 0 2px;
}
.butterfly-bar--neg-secondary {
  background: rgba(239, 68, 68, 0.3);
  border: 1px solid rgba(239, 68, 68, 0.4);
  height: 8px;
  border-radius: 2px 0 0 2px;
}
.butterfly-bar--pos-primary {
  background: linear-gradient(90deg, var(--info), rgba(59, 130, 246, 0.6));
  border-radius: 0 2px 2px 0;
}
.butterfly-bar--pos-secondary {
  background: rgba(59, 130, 246, 0.3);
  border: 1px solid rgba(59, 130, 246, 0.4);
  height: 8px;
  border-radius: 0 2px 2px 0;
}
.butterfly-bar__val {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-0);
  white-space: nowrap;
  pointer-events: none;
  text-shadow: 0 0 3px var(--bg-0);
}
.butterfly-bar-area--neg .butterfly-bar__val {
  left: 4px;
}
.butterfly-bar-area--pos .butterfly-bar__val {
  right: 4px;
}
.butterfly-bar[style*="width:0"] .butterfly-bar__val,
.butterfly-bar[style*="width:1"] .butterfly-bar__val,
.butterfly-bar[style*="width:2"] .butterfly-bar__val,
.butterfly-bar[style*="width:3"] .butterfly-bar__val {
  color: var(--text-2);
}
@media (max-width: 600px) {
  .butterfly-row {
    grid-template-columns: 1fr 44px 1fr;
  }
  .butterfly-label {
    font-size: 11px;
  }
  .butterfly-bar__val {
    font-size: 9px;
  }
}

.butterfly-axis {
  display: grid;
  grid-template-columns: 1fr 1fr 56px 1fr 1fr;
  margin-bottom: 4px;
  padding: 0;
}
.axis-tick {
  font-size: 10px;
  color: var(--text-4);
  font-family: var(--font-mono);
  position: relative;
}
.axis-tick:nth-child(1) {
  text-align: left;
}
.axis-tick:nth-child(2) {
  text-align: right;
  margin-right: 4px;
}
.center-tick {
  text-align: center;
  color: var(--text-3);
  font-weight: bold;
  border-left: 1px dashed var(--border-1);
  border-right: 1px dashed var(--border-1);
  background: var(--surface-0);
  border-radius: 2px;
}
.axis-tick:nth-child(4) {
  text-align: left;
  margin-left: 4px;
}
.axis-tick:nth-child(5) {
  text-align: right;
}

.butterfly-chart {
  border-top: 1px dashed var(--border-1);
  padding-top: 4px;
}

/* Session Tabs */
.session-tabs-container {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-4);
  background: var(--surface-0);
  border-bottom: 1px solid var(--border-0);
  overflow-x: auto;
  white-space: nowrap;
}
.session-tabs-container .session-tab {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 4px 12px;
  background: var(--surface-1);
  border: 1px solid var(--border-1);
  border-radius: var(--radius-full);
  color: var(--text-2);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--duration-fast);
}
.session-tabs-container .session-tab:hover {
  background: var(--surface-2);
  color: var(--text-1);
}
.session-tabs-container .session-tab--active {
  background: var(--accent-muted);
  border-color: rgba(99, 102, 241, 0.4);
  color: var(--accent);
}
.session-tabs-container .session-tab__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  margin-left: 2px;
}
.session-tabs-container .session-tab__close:hover {
  background: rgba(239, 68, 68, 0.1);
  color: var(--error);
}
```

---

## 파일: `src/qcviz_mcp/web/templates/index.html` (879줄, 30285bytes)

```html
<!doctype html>
<html lang="en" data-theme="dark">
  <head>
    <meta charset="utf-8" />
    <meta
      name="viewport"
      content="width=device-width, initial-scale=1, viewport-fit=cover"
    />
    <title>QCViz-MCP Enterprise v5</title>
    <meta
      name="description"
      content="Enterprise quantum chemistry visualization with PySCF, 3Dmol.js, chat orchestration, job history restoration, and state-synced viewer controls."
    />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"
      rel="stylesheet"
    />
    <link rel="stylesheet" href="/static/style.css" />

    <script>
      (function (g) {
        "use strict";
        if (g.QCVizApp && g.QCVizApp.__enterpriseV5) return;

        var STORAGE_KEY = "QCVIZ_ENTERPRISE_V5_UI_SNAPSHOTS";
        var listeners = new Map();

        function safeStr(v, fb) {
          return v == null ? fb || "" : String(v).trim();
        }
        function clone(v) {
          try {
            return JSON.parse(JSON.stringify(v));
          } catch (_) {
            return v;
          }
        }
        function deepMerge(base, patch) {
          var lhs = base && typeof base === "object" ? clone(base) : {};
          var rhs = patch && typeof patch === "object" ? patch : {};
          Object.keys(rhs).forEach(function (k) {
            var lv = lhs[k],
              rv = rhs[k];
            if (
              lv &&
              rv &&
              typeof lv === "object" &&
              typeof rv === "object" &&
              !Array.isArray(lv) &&
              !Array.isArray(rv)
            ) {
              lhs[k] = deepMerge(lv, rv);
            } else {
              lhs[k] = clone(rv);
            }
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
          status: {
            text: "Ready",
            kind: "idle",
            source: "app",
            at: Date.now(),
          },
          uiSnapshotsByJobId: {},
          chatMessages: [],
          theme: "dark",
          lastUserInput: "",
          sessionId: makeSessionId(),
        };

        function emit(ev, detail) {
          (listeners.get(ev) || []).slice().forEach(function (fn) {
            try {
              fn(detail);
            } catch (_) {}
          });
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
          try {
            localStorage.setItem(
              STORAGE_KEY,
              JSON.stringify(store.uiSnapshotsByJobId),
            );
          } catch (_) {}
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
          if (!localStorage.getItem("QCVIZ_THEME"))
            applyTheme(e.matches ? "dark" : "light");
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
            store.status = {
              text: text,
              kind: kind || "idle",
              source: source || "app",
              at: Date.now(),
            };
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
              .sort(function (a, b) {
                return Number(b.updated_at || 0) - Number(a.updated_at || 0);
              })
              .map(function (j) {
                return j.job_id;
              });
            emit("jobs:changed", {
              job: clone(next),
              jobs: store.jobOrder.map(function (id) {
                return clone(store.jobsById[id]);
              }),
            });
            return clone(next);
          },

          setActiveJob: function (jobId) {
            store.activeJobId = jobId;
            var result = store.resultsByJobId[jobId] || null;
            store.activeResult = result ? clone(result) : null;
            emit("activejob:changed", {
              jobId: jobId,
              result: store.activeResult,
            });
            if (result)
              emit("result:changed", {
                jobId: jobId,
                result: clone(result),
                source: "history",
              });
          },

          setActiveResult: function (res, opts) {
            opts = opts || {};
            var jobId = safeStr(opts.jobId || store.activeJobId);
            store.activeResult = res;
            if (jobId) {
              store.activeJobId = jobId;
              store.resultsByJobId[jobId] = clone(res);
            }
            emit("result:changed", {
              jobId: jobId,
              result: clone(res),
              source: opts.source || "app",
            });
          },

          saveUISnapshot: function (jobId, snapshot) {
            if (!jobId) return;
            store.uiSnapshotsByJobId[jobId] = clone(snapshot);
            persistSnapshots();
          },

          getUISnapshot: function (jobId) {
            return store.uiSnapshotsByJobId[jobId]
              ? clone(store.uiSnapshotsByJobId[jobId])
              : null;
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
    <!-- ═══ 로딩 오버레이 ═══ -->
    <div id="appLoader" class="app-loader">
      <div class="loader-content">
        <div class="loader-spinner"></div>
        <p class="loader-text">Initializing QCViz-MCP...</p>
        <p class="loader-sub">Loading 3D visualization engine</p>
      </div>
    </div>
    <script>
      // Fallback to ensure loader doesn't hang forever
      window.addEventListener("load", function () {
        setTimeout(function () {
          var loader = document.getElementById("appLoader");
          if (loader) {
            loader.classList.add("fade-out");
            setTimeout(function () {
              if (loader.parentNode) loader.parentNode.removeChild(loader);
            }, 600);
          }
        }, 1500);
      });
    </script>

    <div class="app-shell" id="appShell">
      <!-- Top Bar -->
      <header class="topbar" id="topbar">
        <div class="topbar__left">
          <div class="topbar__logo" aria-label="QCViz Logo">
            <svg
              width="28"
              height="28"
              viewBox="0 0 28 28"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              <rect width="28" height="28" rx="8" fill="url(#logoGrad)" />
              <path
                d="M8 14a6 6 0 1 1 12 0 6 6 0 0 1-12 0Zm6-3.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z"
                fill="white"
                fill-opacity="0.95"
              />
              <path
                d="M17.5 17.5L21 21"
                stroke="white"
                stroke-width="2"
                stroke-linecap="round"
                stroke-opacity="0.9"
              />
              <defs>
                <linearGradient
                  id="logoGrad"
                  x1="0"
                  y1="0"
                  x2="28"
                  y2="28"
                  gradientUnits="userSpaceOnUse"
                >
                  <stop stop-color="#6366f1" />
                  <stop offset="1" stop-color="#8b5cf6" />
                </linearGradient>
              </defs>
            </svg>
            <span class="topbar__title"
              >QCViz-MCP <span class="topbar__badge">v5</span></span
            >
          </div>
        </div>
        <div class="topbar__center">
          <div class="status-indicator" id="globalStatus">
            <span class="status-indicator__dot" data-kind="idle"></span>
            <span class="status-indicator__text">Ready</span>
          </div>
        </div>
        <div class="topbar__right">
          <button
            class="icon-btn"
            id="btnThemeToggle"
            aria-label="Toggle theme"
            title="Toggle theme (Ctrl+\)"
          >
            <svg
              class="icon-sun"
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <circle cx="12" cy="12" r="5" />
              <path
                d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"
              />
            </svg>
            <svg
              class="icon-moon"
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
            </svg>
          </button>
          <button
            class="icon-btn"
            id="btnKeyboardShortcuts"
            aria-label="Keyboard shortcuts"
            title="Keyboard shortcuts (?)"
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <rect x="2" y="4" width="20" height="16" rx="2" />
              <path
                d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M8 12h.01M12 12h.01M16 12h.01M7 16h10"
              />
            </svg>
          </button>
        </div>
      </header>

      <!-- App-level Session Tabs -->
      <div id="sessionTabsContainer" class="session-tabs-container" hidden>
        <div id="sessionTabs" class="session-tabs"></div>
      </div>

      <!-- Dashboard Grid -->
      <main class="dashboard" id="dashboard">
        <!-- Viewer Panel -->
        <section
          class="panel panel--viewer"
          id="panelViewer"
          aria-label="3D Molecular Viewer"
        >
          <div class="panel__header">
            <h2 class="panel__title">
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M12 2L2 7l10 5 10-5-10-5z" />
                <path d="M2 17l10 5 10-5" />
                <path d="M2 12l10 5 10-5" />
              </svg>
              Molecular Viewer
            </h2>
            <div class="panel__actions">
              <button class="chip-btn" id="btnViewerReset" title="Reset view">
                Reset
              </button>
              <div id="vizModeToggle" class="viz-mode-toggle" hidden>
                <button
                  id="btnModeOrbital"
                  class="toggle-btn active"
                  title="Orbital 표면 보기"
                >
                  Orbital
                </button>
                <button id="btnModeESP" class="toggle-btn" title="ESP 맵 보기">
                  ESP
                </button>
              </div>
              <button
                class="chip-btn"
                id="btnViewerScreenshot"
                title="Screenshot"
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                >
                  <rect x="3" y="3" width="18" height="18" rx="2" />
                  <circle cx="12" cy="12" r="3" />
                </svg>
                Capture
              </button>
              <button
                class="icon-btn icon-btn--sm"
                id="btnViewerFullscreen"
                title="Fullscreen"
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                >
                  <path
                    d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"
                  />
                </svg>
              </button>
            </div>
          </div>
          <div class="viewer-container" id="viewerContainer">
            <div class="viewer-3d" id="viewer3d"></div>
            <div class="viewer-empty" id="viewerEmpty">
              <div class="viewer-empty__icon">
                <svg
                  width="48"
                  height="48"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.5"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  opacity="0.35"
                >
                  <path d="M12 2L2 7l10 5 10-5-10-5z" />
                  <path d="M2 17l10 5 10-5" />
                  <path d="M2 12l10 5 10-5" />
                </svg>
              </div>
              <p class="viewer-empty__text">
                Submit a computation to render the molecule
              </p>
              <p class="viewer-empty__hint">
                Try: "Calculate energy of water with STO-3G"
              </p>
            </div>
            <div class="viewer-controls" id="viewerControls" hidden>
              <div class="viewer-controls__group">
                <label class="viewer-controls__label">Style</label>
                <div class="segmented" id="segStyle">
                  <button
                    class="segmented__btn segmented__btn--active"
                    data-value="stick"
                  >
                    Stick
                  </button>
                  <button class="segmented__btn" data-value="sphere">
                    Sphere
                  </button>
                  <button class="segmented__btn" data-value="line">Line</button>
                </div>
              </div>
              <div class="viewer-controls__group" id="grpOrbital" hidden>
                <label class="viewer-controls__label">Isosurface</label>
                <input
                  type="range"
                  class="range-input"
                  id="sliderIsovalue"
                  min="0.001"
                  max="0.1"
                  step="0.001"
                  value="0.03"
                />
                <span class="viewer-controls__value" id="lblIsovalue"
                  >0.030</span
                >
              </div>
              <div class="viewer-controls__group" id="grpESP" hidden>
                <label class="viewer-controls__label">ESP Density Iso</label>
                <input
                  type="range"
                  class="range-input"
                  id="sliderEspDensIso"
                  min="0.0001"
                  max="0.02"
                  step="0.0001"
                  value="0.001"
                />
                <span class="viewer-controls__value" id="lblEspDensIso"
                  >0.0010</span
                >
              </div>
              <div class="viewer-controls__group" id="grpOpacity" hidden>
                <label class="viewer-controls__label">Opacity</label>
                <input
                  type="range"
                  class="range-input"
                  id="sliderOpacity"
                  min="0.1"
                  max="1.0"
                  step="0.05"
                  value="0.75"
                />
                <span class="viewer-controls__value" id="lblOpacity">0.75</span>
              </div>

              <div class="viewer-controls__group" id="grpColorScheme">
                <label class="viewer-controls__label">Color Scheme</label>
                <select id="selectColorScheme" class="viewer-select">
                  <option value="classic">Classic (Blue/Red)</option>
                  <option value="jmol">Jmol</option>
                  <option value="rwb">RWB (Red-White-Blue)</option>
                  <option value="bwr">BWR (Blue-White-Red)</option>
                  <option value="spectral">Spectral</option>
                  <option value="viridis">Viridis</option>
                  <option value="inferno">Inferno</option>
                  <option value="coolwarm">Cool-Warm</option>
                  <option value="purplegreen">Purple-Green</option>
                  <option value="greyscale">Greyscale</option>
                </select>
                <span id="schemePreview" class="scheme-preview">
                  <span class="swatch swatch-pos"></span>
                  <span class="swatch swatch-neg"></span>
                </span>
              </div>

              <div class="viewer-controls__group" id="grpOrbitalSelect" hidden>
                <label class="viewer-controls__label">Orbital</label>
                <select class="viewer-select" id="selectOrbital"></select>
              </div>
              <div class="viewer-controls__group">
                <label class="viewer-controls__label">Labels</label>
                <button
                  class="toggle-btn"
                  id="btnToggleLabels"
                  data-active="true"
                  aria-pressed="true"
                >
                  On
                </button>
              </div>
            </div>
            <div class="viewer-legend" id="viewerLegend" hidden></div>
          </div>
        </section>

        <!-- Chat Panel -->
        <section
          class="panel panel--chat"
          id="panelChat"
          aria-label="Chat Assistant"
        >
          <div class="panel__header">
            <h2 class="panel__title">
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path
                  d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"
                />
              </svg>
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
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                  >
                    <path d="M12 2L2 7l10 5 10-5-10-5z" />
                    <path d="M2 17l10 5 10-5" />
                  </svg>
                </div>
                <div class="chat-msg__body">
                  <p class="chat-msg__text">
                    Welcome to <strong>QCViz-MCP v5</strong>. I can run quantum
                    chemistry calculations using PySCF. Ask me to compute
                    energies, optimize geometries, or visualize orbitals and ESP
                    maps.
                  </p>
                </div>
              </div>
            </div>
          </div>
          <div class="chat-input-area" id="chatInputArea">
            <div class="chat-suggestions" id="chatSuggestions">
              <button
                class="suggestion-chip"
                data-prompt="Calculate the energy of water using STO-3G basis"
              >
                Water energy
              </button>
              <button
                class="suggestion-chip"
                data-prompt="Optimize the geometry of methane with 6-31G basis"
              >
                Methane geometry
              </button>
              <button
                class="suggestion-chip"
                data-prompt="Show the HOMO orbital of formaldehyde"
              >
                Formaldehyde HOMO
              </button>
            </div>
            <form class="chat-form" id="chatForm" autocomplete="off">
              <div class="chat-form__input-wrap">
                <textarea
                  class="chat-form__input"
                  id="chatInput"
                  placeholder="Ask about quantum chemistry..."
                  rows="1"
                  maxlength="4000"
                ></textarea>
                <button
                  class="chat-form__send"
                  id="chatSend"
                  type="submit"
                  aria-label="Send"
                  disabled
                >
                  <svg
                    width="18"
                    height="18"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  >
                    <line x1="22" y1="2" x2="11" y2="13" />
                    <polygon points="22 2 15 22 11 13 2 9 22 2" />
                  </svg>
                </button>
              </div>
              <p class="chat-form__hint">
                Press <kbd>Enter</kbd> to send, <kbd>Shift+Enter</kbd> for new
                line
              </p>
            </form>
          </div>
        </section>

        <!-- Results Panel -->
        <section
          class="panel panel--results"
          id="panelResults"
          aria-label="Computation Results"
        >
          <div class="panel__header">
            <h2 class="panel__title">
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path
                  d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"
                />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
              </svg>
              Results
            </h2>
          </div>
          <div id="sessionTabBar" class="session-tab-bar" hidden></div>
          <div class="results-tabs" id="resultsTabs" role="tablist"></div>
          <div class="results-content" id="resultsContent">
            <div class="results-empty" id="resultsEmpty">
              <p>No results yet. Submit a computation from the chat.</p>
            </div>
          </div>
        </section>

        <!-- History Panel -->
        <section
          class="panel panel--history"
          id="panelHistory"
          aria-label="Job History"
        >
          <div class="panel__header">
            <h2 class="panel__title">
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <circle cx="12" cy="12" r="10" />
                <polyline points="12 6 12 12 16 14" />
              </svg>
              History
            </h2>
            <div class="panel__actions">
              <button
                class="icon-btn icon-btn--sm"
                id="btnRefreshHistory"
                title="Refresh"
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                >
                  <polyline points="23 4 23 10 17 10" />
                  <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
                </svg>
              </button>
            </div>
          </div>
          <div class="history-search-wrap">
            <svg
              class="history-search-icon"
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
            >
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              type="search"
              class="history-search"
              id="historySearch"
              placeholder="Search jobs..."
            />
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
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        <div class="modal__body shortcuts-grid">
          <div class="shortcut-row">
            <span class="shortcut-keys"
              ><kbd>Ctrl</kbd><span class="shortcut-plus">+</span
              ><kbd>/</kbd></span
            ><span>Focus chat input</span>
          </div>
          <div class="shortcut-row">
            <span class="shortcut-keys"
              ><kbd>Ctrl</kbd><span class="shortcut-plus">+</span
              ><kbd>K</kbd></span
            ><span>Search history</span>
          </div>
          <div class="shortcut-row">
            <span class="shortcut-keys"
              ><kbd>Ctrl</kbd><span class="shortcut-plus">+</span
              ><kbd>\</kbd></span
            ><span>Toggle theme</span>
          </div>
          <div class="shortcut-row">
            <span class="shortcut-keys"><kbd>Esc</kbd></span
            ><span>Close modals / blur</span>
          </div>
          <div class="shortcut-row">
            <span class="shortcut-keys"
              ><kbd>1</kbd><span class="shortcut-dash">&ndash;</span
              ><kbd>6</kbd></span
            ><span>Switch result tabs</span>
          </div>
          <div class="shortcut-row">
            <span class="shortcut-keys"><kbd>?</kbd></span
            ><span>Show this dialog</span>
          </div>
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

---

## 파일: `src/qcviz_mcp/tools/__init__.py` (6줄, 164bytes)

```python
"""MCP 도구 모듈 패키지.

QCViz-MCP가 노출하는 6개의 핵심 MCP 도구(function)들을 구현합니다.
"""

from __future__ import annotations

```

---

## 파일: `src/qcviz_mcp/tools/core.py` (837줄, 26951bytes)

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
        import re
        clean_name = re.sub(r"(?i)\b(?:the|of|orbital|homo|lumo|mo|esp|map|charge|charges|mulliken|partial)\b", "", name).strip()
        quoted = urllib.parse.quote(clean_name, safe="")
        direct_url = (
            f"{cls.PUBCHEM_BASE}/compound/name/{quoted}/property/CanonicalSMILES,IsomericSMILES/JSON"
        )

        try:
            data = cls._http_get_json(direct_url, timeout=20)
            props = data.get("PropertyTable", {}).get("Properties", [])
            if props:
                p = props[0]
                smiles = (p.get("CanonicalSMILES") or p.get("IsomericSMILES")
                          or p.get("SMILES") or p.get("ConnectivitySMILES"))
                if smiles:
                    return smiles
                # If PubChem returned properties but no SMILES, fall through to CID lookup
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
    return f"분석 실패: {res.get('error')}"
```

---

## 파일: `src/qcviz_mcp/tools/advisor_tools.py` (333줄, 11406bytes)

```python
"""QCViz-MCP v5.0 — Advisor Module MCP Tool Registration.

Registers 5 advisor tools that provide AI-driven chemistry research guidance:
  1. recommend_preset - DFT calculation settings recommendation
  2. draft_methods_section - Publication-ready methods text generation
  3. generate_script - Standalone PySCF script export
  4. validate_against_literature - NIST reference data validation
  5. score_confidence - Composite confidence scoring
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from qcviz_mcp.mcp_server import mcp
from qcviz_mcp.advisor import (
    PresetRecommender,
    MethodsSectionDrafter,
    CalculationRecord,
    ReproducibilityScriptGenerator,
    LiteratureEnergyValidator,
    ValidationRequest,
    ConfidenceScorer,
)

logger = logging.getLogger(__name__)

# Singleton instances — created once at import time
_recommender = PresetRecommender()
_drafter = MethodsSectionDrafter()
_script_gen = ReproducibilityScriptGenerator()
_validator = LiteratureEnergyValidator()
_scorer = ConfidenceScorer()


@mcp.tool()
def recommend_preset(
    atom_spec: str,
    purpose: str = "geometry_opt",
    charge: int = 0,
    spin: int = 0,
) -> str:
    """Analyze molecular structure and recommend optimal DFT calculation
    settings (functional, basis set, dispersion correction) with
    literature-backed justification.

    Args:
        atom_spec: Molecular structure in XYZ format.
        purpose: Calculation purpose (geometry_opt, single_point,
                 bonding_analysis, reaction_energy, spectroscopy,
                 esp_mapping).
        charge: Molecular charge.
        spin: Spin multiplicity (2S, e.g. 0=singlet, 1=doublet).

    Returns:
        JSON string with recommendation details.
    """
    try:
        rec = _recommender.recommend(
            atom_spec=atom_spec,
            purpose=purpose,
            charge=charge,
            spin=spin,
        )
        return json.dumps({
            "functional": rec.functional,
            "basis": rec.basis,
            "dispersion": rec.dispersion,
            "spin_treatment": rec.spin_treatment,
            "relativistic": rec.relativistic,
            "convergence": rec.convergence,
            "alternatives": [
                {"functional": a[0], "basis": a[1], "rationale": a[2]}
                for a in rec.alternatives
            ],
            "warnings": rec.warnings,
            "references": rec.references,
            "rationale": rec.rationale,
            "confidence": rec.confidence,
            "pyscf_settings": rec.pyscf_settings,
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error("recommend_preset error: %s", e)
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
def draft_methods_section(
    system_name: str,
    atom_spec: str,
    functional: str,
    basis: str,
    charge: int = 0,
    spin: int = 0,
    dispersion: str = "",
    software_version: str = "",
    optimizer: str = "",
    analysis_type: str = "",
    citation_style: str = "acs",
    energy_hartree: float = 0.0,
    converged: bool = True,
    n_cycles: int = 0,
) -> str:
    """Generate publication-ready Computational Methods text with BibTeX
    citations from calculation metadata.

    Args:
        system_name: Name of the molecular system.
        atom_spec: Molecular structure in XYZ format.
        functional: DFT functional used (e.g. B3LYP-D3(BJ)).
        basis: Basis set used (e.g. def2-SVP).
        charge: Molecular charge.
        spin: Spin multiplicity.
        dispersion: Dispersion correction (e.g. D3BJ).
        software_version: PySCF version string.
        optimizer: Geometry optimizer (e.g. geomeTRIC).
        analysis_type: Analysis performed (ibo, iao, esp).
        citation_style: Citation style (acs, rsc, nature).
        energy_hartree: Total energy in Hartree.
        converged: Whether SCF converged.
        n_cycles: Number of SCF cycles.

    Returns:
        JSON with methods_text, bibtex_entries, reviewer_notes, disclaimer.
    """
    try:
        record = CalculationRecord(
            system_name=system_name,
            atom_spec=atom_spec,
            charge=charge,
            spin=spin,
            functional=functional,
            basis=basis,
            dispersion=dispersion,
            software="PySCF",
            software_version=software_version,
            optimizer=optimizer,
            analysis_type=analysis_type,
            energy_hartree=energy_hartree,
            converged=converged,
            n_cycles=n_cycles,
        )
        draft = _drafter.draft(
            [record],
            citation_style=citation_style,
            include_bibtex=True,
        )
        return json.dumps({
            "methods_text": draft.methods_text,
            "bibtex_entries": draft.bibtex_entries,
            "reviewer_notes": draft.reviewer_notes,
            "disclaimer": draft.disclaimer,
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error("draft_methods_section error: %s", e)
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
def generate_script(
    system_name: str,
    atom_spec: str,
    functional: str,
    basis: str,
    charge: int = 0,
    spin: int = 0,
    dispersion: str = "",
    optimizer: str = "",
    analysis_type: str = "",
    include_analysis: bool = True,
) -> str:
    """Generate standalone PySCF Python script that reproduces a
    calculation without QCViz-MCP.

    Args:
        system_name: Name of the molecular system.
        atom_spec: Molecular structure in XYZ format.
        functional: DFT functional.
        basis: Basis set.
        charge: Molecular charge.
        spin: Spin multiplicity.
        dispersion: Dispersion correction.
        optimizer: Geometry optimizer.
        analysis_type: Analysis type (ibo, esp, etc).
        include_analysis: Whether to include analysis code.

    Returns:
        Complete Python script as a string.
    """
    try:
        record = CalculationRecord(
            system_name=system_name,
            atom_spec=atom_spec,
            charge=charge,
            spin=spin,
            functional=functional,
            basis=basis,
            dispersion=dispersion,
            optimizer=optimizer,
            analysis_type=analysis_type,
        )
        return _script_gen.generate(record, include_analysis=include_analysis)
    except Exception as e:
        logger.error("generate_script error: %s", e)
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
def validate_against_literature(
    system_formula: str,
    functional: str,
    basis: str,
    bond_lengths: Optional[dict] = None,
    bond_angles: Optional[dict] = None,
) -> str:
    """Compare computed molecular properties against NIST CCCBDB
    reference data and flag deviations.

    Args:
        system_formula: Hill-system molecular formula (e.g. H2O, CH4).
        functional: DFT functional used.
        basis: Basis set used.
        bond_lengths: Dict of bond_type to length in Angstrom.
        bond_angles: Dict of angle_type to angle in degrees.

    Returns:
        JSON with validation results, status, and recommendations.
    """
    try:
        req = ValidationRequest(
            system_formula=system_formula,
            functional=functional,
            basis=basis,
            bond_lengths=bond_lengths or {},
            bond_angles=bond_angles or {},
        )
        result = _validator.validate(req)
        return json.dumps({
            "overall_status": result.overall_status,
            "confidence": result.confidence,
            "method_assessment": result.method_assessment,
            "bond_validations": [
                {
                    "bond": v.bond_type,
                    "computed": v.computed,
                    "reference": v.reference,
                    "deviation": v.deviation,
                    "status": v.status,
                    "comment": v.comment,
                }
                for v in result.bond_validations
            ],
            "angle_validations": [
                {
                    "angle": v.bond_type,
                    "computed": v.computed,
                    "reference": v.reference,
                    "deviation": v.deviation,
                    "status": v.status,
                }
                for v in result.angle_validations
            ],
            "recommendations": result.recommendations,
            "disclaimer": result.disclaimer,
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error("validate_against_literature error: %s", e)
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
def score_confidence(
    functional: str,
    basis: str,
    converged: bool = True,
    n_scf_cycles: int = 0,
    max_cycles: int = 200,
    system_type: str = "organic_small",
    spin: int = 0,
    s2_expected: float = 0.0,
    s2_actual: float = 0.0,
    validation_status: str = None,
) -> str:
    """Compute composite confidence score (0-1) for a quantum chemistry
    calculation based on convergence, method quality, and reference
    agreement.

    Args:
        functional: DFT functional used.
        basis: Basis set used.
        converged: Whether SCF converged.
        n_scf_cycles: Number of SCF cycles taken.
        max_cycles: Maximum allowed SCF cycles.
        system_type: System classification (organic_small, organic_large,
                     3d_tm, heavy_tm, lanthanide, radical,
                     charged_organic, main_group_metal).
        spin: Spin multiplicity.
        s2_expected: Expected <S^2> value.
        s2_actual: Actual <S^2> value.
        validation_status: Literature validation status (PASS/WARN/FAIL).

    Returns:
        JSON with overall_score, sub-scores, breakdown, and recommendations.
    """
    try:
        report = _scorer.score(
            converged=converged,
            n_scf_cycles=n_scf_cycles,
            max_cycles=max_cycles,
            functional=functional,
            basis=basis,
            system_type=system_type,
            spin=spin,
            s2_expected=s2_expected,
            s2_actual=s2_actual,
            validation_status=validation_status,
        )
        return json.dumps({
            "overall_score": report.overall_score,
            "convergence_score": report.convergence_score,
            "basis_score": report.basis_score,
            "method_score": report.method_score,
            "spin_score": report.spin_score,
            "reference_score": report.reference_score,
            "breakdown": report.breakdown_text,
            "recommendations": report.recommendations,
            "disclaimer": report.disclaimer,
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error("score_confidence error: %s", e)
        return json.dumps({"status": "error", "error": str(e)})

```

---

## 파일: `src/qcviz_mcp/tools/health.py` (48줄, 1321bytes)

```python
import sys
import importlib
from datetime import datetime, timezone
from qcviz_mcp.mcp_server import mcp
from qcviz_mcp.observability import metrics

@mcp.tool()
async def health_check() -> dict:
    """서버 상태 및 백엔드 가용성 진단."""

    backends = {}
    for name, module in [
        ("pyscf", "pyscf"),
        ("cclib", "cclib"),
        ("py3Dmol", "py3Dmol"),
        ("ase", "ase"),
        ("pyvista", "pyvista"),
        ("playwright", "playwright"),
    ]:
        try:
            mod = importlib.import_module(module)
            version = getattr(mod, "__version__", "unknown")
            backends[name] = {"available": True, "version": version}
        except ImportError:
            backends[name] = {"available": False}

    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version,
        "qcviz_version": "0.6.0-alpha",
        "backends": backends,
        "metrics_summary": metrics.get_summary(),
        "renderer": _detect_renderer(),
    }

def _detect_renderer() -> str:
    try:
        import pyvista
        return "pyvista"
    except ImportError:
        pass
    try:
        import playwright
        return "playwright"
    except ImportError:
        pass
    return "py3dmol"

```

---

## 파일: `src/qcviz_mcp/backends/__init__.py` (16줄, 456bytes)

```python
"""백엔드 모듈 패키지.

PySCF, cclib, py3Dmol, ASE 등 다양한 양자화학 및 구조 프레임워크와의 연동을 담당합니다.
"""

from __future__ import annotations

# 레지스트리 초기화를 위해 모든 백엔드 모듈 임포트
from qcviz_mcp.backends import ase_backend, cclib_backend, pyscf_backend, viz_backend

__all__ = [
    "pyscf_backend",
    "cclib_backend",
    "viz_backend",
    "ase_backend",
]

```

---

## 파일: `src/qcviz_mcp/backends/base.py` (174줄, 4947bytes)

```python
"""QCViz-MCP 백엔드 공통 인터페이스 및 데이터 클래스 정의.

추상 클래스(ABC)를 통해 다양한 양자화학 프로그램 및 시각화 도구를 지원합니다.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class SCFResult:
    """단일 SCF 계산 결과."""

    converged: bool
    energy_hartree: float
    mo_coeff: np.ndarray
    mo_occ: np.ndarray
    mo_energy: np.ndarray
    basis: str
    method: str


@dataclass(frozen=True)
class IAOResult:
    """Intrinsic Atomic Orbital 계산 결과."""

    coefficients: np.ndarray
    charges: np.ndarray


@dataclass(frozen=True)
class IBOResult:
    """Intrinsic Bond Orbital 계산 결과."""

    coefficients: np.ndarray
    occupations: np.ndarray
    n_ibo: int


@dataclass(frozen=True)
class ParsedResult:
    """양자화학 프로그램 출력 파싱 결과."""

    energy_hartree: float | None
    coordinates: np.ndarray | None  # shape: (n_atoms, 3)
    atomic_numbers: list[int] | None
    mo_energies: list[np.ndarray] | None  # alpha, beta
    mo_coefficients: list[np.ndarray] | None
    program: str


@dataclass(frozen=True)
class AtomsData:
    """원자 구조 정보 데이터."""

    symbols: list[str]
    positions: np.ndarray  # shape: (n_atoms, 3)
    cell: np.ndarray | None
    pbc: list[bool] | None


class BackendBase(abc.ABC):
    """모든 백엔드의 최상위 기본 클래스."""

    @classmethod
    @abc.abstractmethod
    def name(cls) -> str:
        """백엔드 식별 이름을 반환합니다."""
        pass

    @classmethod
    @abc.abstractmethod
    def is_available(cls) -> bool:
        """해당 백엔드 구동에 필요한 의존성이 설치되어 있는지 확인합니다."""
        pass


class OrbitalBackend(BackendBase):
    """양자화학 계산 및 궤도(오비탈) 분석 백엔드 인터페이스."""

    @abc.abstractmethod
    def compute_scf(self, atom_spec: str, basis: str, method: str) -> SCFResult:
        """SCF 계산을 수행합니다."""
        pass

    @abc.abstractmethod
    def compute_iao(self, scf_result: SCFResult, mol_obj: Any) -> IAOResult:
        """주어진 SCF 결과로부터 IAO를 계산합니다."""
        pass

    @abc.abstractmethod
    def compute_ibo(
        self,
        scf_result: SCFResult,
        iao_result: IAOResult,
        mol_obj: Any,
        localization_method: str = "PM",
    ) -> IBOResult:
        """주어진 IAO/SCF 결과로부터 IBO를 계산합니다."""
        pass

    @abc.abstractmethod
    def generate_cube(
        self,
        mol_obj: Any,
        orbital_coeff: np.ndarray,
        orbital_index: int,
        grid_points: tuple[int, int, int] = (80, 80, 80),
    ) -> np.ndarray:
        """특정 오비탈의 cube 데이터를 생성합니다."""
        pass


class ParserBackend(BackendBase):
    """양자화학 계산 출력 파일 파싱 백엔드 인터페이스."""

    @abc.abstractmethod
    def parse_file(self, path: str | Path) -> ParsedResult:
        """출력 파일을 파싱합니다."""
        pass

    @classmethod
    @abc.abstractmethod
    def supported_programs(cls) -> list[str]:
        """지원하는 양자화학 프로그램 목록을 반환합니다."""
        pass


class VisualizationBackend(BackendBase):
    """3D 분자 및 오비탈 시각화 백엔드 인터페이스."""

    @abc.abstractmethod
    def render_molecule(self, xyz_data: str, style: str = "stick") -> str:
        """분자 구조를 시각화하는 HTML 문자열을 반환합니다."""
        pass

    @abc.abstractmethod
    def render_orbital(
        self,
        xyz_data: str,
        cube_data: str,
        isovalue: float = 0.05,
        colors: tuple[str, str] = ("blue", "red"),
        style: str = "stick",
    ) -> str:
        """오비탈 등치면과 분자 구조를 시각화하는 HTML 문자열을 반환합니다."""
        pass


class StructureBackend(BackendBase):
    """분자 구조 조작 및 포맷 변환 백엔드 인터페이스."""

    @abc.abstractmethod
    def read_structure(self, path: str | Path, format: str | None = None) -> AtomsData:
        """구조 파일을 읽어 AtomsData 객체로 반환합니다."""
        pass

    @abc.abstractmethod
    def write_structure(
        self, atoms: AtomsData, path: str | Path, format: str | None = None
    ) -> Path:
        """AtomsData 객체를 지정된 포맷의 파일로 저장합니다."""
        pass

    @abc.abstractmethod
    def convert_format(self, input_path: str | Path, output_path: str | Path) -> Path:
        """구조 파일 포맷을 변경합니다."""
        pass

```

---

## 파일: `src/qcviz_mcp/backends/pyscf_backend.py` (517줄, 23682bytes)

```python
"""PySCF 기반 IAO/IBO 및 엔터프라이즈 기능(Rich CLI, Shell-Sampling) 백엔드 v3.0.1."""

from __future__ import annotations

import os
import re
import sys
import tempfile
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple
from collections import Counter

import numpy as np

try:
    import pyscf
    from pyscf import gto, lo, scf, lib
    from pyscf.tools import cubegen
    _HAS_PYSCF = True
except ImportError:
    _HAS_PYSCF = False

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import (
        Progress, BarColumn, TextColumn, TimeElapsedColumn, SpinnerColumn,
    )
    from rich.text import Text
    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False

from qcviz_mcp.backends.base import IAOResult, IBOResult, OrbitalBackend, SCFResult
from qcviz_mcp.backends.registry import registry
from qcviz_mcp.analysis.sanitize import sanitize_xyz as _sanitize_xyz, extract_atom_list, atoms_to_xyz_string

logger = logging.getLogger(__name__)

_SUPPORTED_METHODS = frozenset({"HF", "RHF", "UHF", "RKS", "UKS", "B3LYP", "PBE0"})
_HEAVY_TM_Z = set(range(39, 49)) | set(range(72, 81))  # 4d(Y-Cd) + 5d(Hf-Hg)

# ================================================================
# §0  Errors & Strategies (Restored for tests)
# ================================================================

class ConvergenceError(RuntimeError):
    """적응적 SCF 수렴 전략이 모두 실패했을 때 발생."""
    pass

class ConvergenceStrategy:
    """적응적 SCF 수렴 에스컬레이션 엔진 (5단계)."""
    LEVELS = (
        {"name": "diis_default", "max_cycle": 100, "level_shift": 0.0, "soscf": False, "damp": 0.0},
        {"name": "diis_levelshift", "max_cycle": 200, "level_shift": 0.5, "soscf": False, "damp": 0.0},
        {"name": "diis_damp", "max_cycle": 200, "level_shift": 0.3, "soscf": False, "damp": 0.5},
        {"name": "soscf", "max_cycle": 200, "level_shift": 0.0, "soscf": True, "damp": 0.0},
        {"name": "soscf_shift", "max_cycle": 300, "level_shift": 0.5, "soscf": True, "damp": 0.0},
    )

    @staticmethod
    def apply(mf, level_idx: int = 0):
        if level_idx < 0 or level_idx >= len(ConvergenceStrategy.LEVELS):
            raise ValueError(f"Invalid strategy level: {level_idx}")
        cfg = ConvergenceStrategy.LEVELS[level_idx]
        mf.max_cycle = cfg["max_cycle"]
        mf.level_shift = cfg["level_shift"]
        mf.damp = cfg["damp"]
        if cfg["soscf"]:
            mf = mf.newton()
        return mf

    @staticmethod
    def level_name(level_idx: int) -> str:
        return ConvergenceStrategy.LEVELS[level_idx]["name"]

def _has_heavy_tm(mol) -> bool:
    if not _HAS_PYSCF: return False
    for ia in range(mol.natm):
        if int(mol.atom_charge(ia)) in _HEAVY_TM_Z: return True
    return False

def parse_cube_string(cube_text: str) -> dict:
    lines = cube_text.strip().splitlines()
    parts = lines[2].split()
    natm = abs(int(parts[0]))
    origin = (float(parts[1]), float(parts[2]), float(parts[3]))
    axes = []; npts_list = []
    for i in range(3):
        p = lines[3 + i].split()
        n = int(p[0]); npts_list.append(n)
        vec = np.array([float(p[1]), float(p[2]), float(p[3])]) * n
        axes.append(vec)
    npts = tuple(npts_list); atoms = []
    for i in range(natm):
        p = lines[6 + i].split()
        atoms.append((int(float(p[0])), float(p[2]), float(p[3]), float(p[4])))
    data_start = 6 + natm
    values = []
    for line in lines[data_start:]: values.extend(float(v) for v in line.split())
    data = np.array(values).reshape(npts)
    return {"data": data, "origin": origin, "axes": axes, "npts": npts, "atoms": atoms}

def _parse_atom_spec(atom_spec: str) -> str:
    lines = atom_spec.strip().splitlines()
    try:
        n_atoms = int(lines[0].strip())
    except ValueError:
        return atom_spec
    atom_lines: list[str] = []
    for line in lines[2 : 2 + n_atoms]:
        parts = line.split()
        if len(parts) >= 4:
            atom_lines.append(f"{parts[0]}  {parts[1]}  {parts[2]}  {parts[3]}")
    return "; ".join(atom_lines)

def _safe_parse_atom_spec(atom_spec: str) -> str:
    """sanitize_xyz를 시도하고, 실패 시 기존 _parse_atom_spec으로 폴백."""
    try:
        return _sanitize_xyz(atom_spec)
    except (ValueError, Exception):
        return _parse_atom_spec(atom_spec)

# ================================================================
# §1  Rich CLI Reporter
# ================================================================
class _CLIReporter:
    def __init__(self):
        self.console = Console(stderr=True) if _HAS_RICH else None

    def print_calc_summary(self, method, basis, charge, spin, natoms, formula):
        if self.console and _HAS_RICH:
            t = Table(title="[bold cyan]QCViz Setup[/bold cyan]", header_style="bold white on dark_blue", border_style="blue")
            t.add_column("Parameter", style="bold"); t.add_column("Value", style="green")
            t.add_row("Method", method); t.add_row("Basis", basis); t.add_row("Charge", str(charge))
            t.add_row("Spin", str(spin)); t.add_row("Atoms", str(natoms)); t.add_row("Formula", formula)
            self.console.print(t)

    def run_scf_with_progress(self, mf, method, basis):
        if not self.console or not _HAS_RICH:
            mf.run(); return mf
        cd = {"n": 0, "last_e": None, "max": getattr(mf, "max_cycle", 50)}
        prog = Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"), BarColumn(bar_width=30, complete_style="green"),
                        TextColumn("[cyan]{task.fields[energy]}"), TextColumn("[yellow]{task.fields[delta]}"), TimeElapsedColumn(), console=self.console)
        tid = [None]
        def cb(envs):
            cd["n"] += 1; e = envs.get("e_tot"); d_str = ""
            if e is not None:
                if cd["last_e"] is not None: d_str = "dE=%.2e" % (e - cd["last_e"])
                cd["last_e"] = e
            e_str = "E=%.8f" % e if e is not None else "E=..."
            if tid[0] is not None: prog.update(tid[0], completed=min(cd["n"]/cd["max"]*100, 100), energy=e_str, delta=d_str, description="SCF Cycle %d" % cd["n"])
        mf.callback = cb
        with prog:
            tid[0] = prog.add_task("SCF ...", total=100, energy="E=...", delta="")
            mf.run()
        if mf.converged: self.console.print(Panel(Text("CONVERGED  E = %.10f Ha" % mf.e_tot, style="bold green"), title="SCF Result", border_style="green"))
        return mf

    def print_esp_summary(self, vmin_raw, vmax_raw, vmin_sym, vmax_sym, p_lo, p_hi):
        if self.console and _HAS_RICH:
            t = Table(title="[bold cyan]ESP Analysis[/bold cyan]", border_style="cyan")
            t.add_column("Metric"); t.add_column("Value", style="green")
            t.add_row("Raw Min/Max", "%.6f / %.6f" % (vmin_raw, vmax_raw))
            t.add_row("P5/P95", "%.6f / %.6f" % (p_lo, p_hi))
            t.add_row("Final Range", "[bold]%.6f .. %.6f[/bold]" % (vmin_sym, vmax_sym))
            self.console.print(t)

    def print_cube_progress(self, current, total, label):
        if self.console and _HAS_RICH: self.console.print("  [dim]Cube[/dim] [bold]%d[/bold]/%d  %s" % (current, total, label))

_cli = _CLIReporter()

@dataclass
class ESPResult:
    density_cube: str; potential_cube: str; vmin: float; vmax: float; vmin_raw: float; vmax_raw: float
    atom_symbols: list; energy_hartree: float; basis: str; grid_size: int = 60; margin: float = 10.0

# ================================================================
# §2  PySCF Backend
# ================================================================

class PySCFBackend(OrbitalBackend):
    @classmethod
    def name(cls): return "pyscf"
    @classmethod
    def is_available(cls): return _HAS_PYSCF

    def compute_scf(self, atom_spec, basis="cc-pvdz", method="RHF", charge=0, spin=0):
        if not _HAS_PYSCF: raise ImportError("PySCF가 설치되지 않았습니다.")
        method_upper = method.upper()
        if method_upper not in _SUPPORTED_METHODS: raise ValueError(f"지원하지 않는 메서드 유형: {method}")
        atom_spec = _safe_parse_atom_spec(atom_spec)
        mol = gto.M(atom=atom_spec, basis=basis, charge=charge, spin=spin, verbose=0)

        is_dft = any(xc in method_upper for xc in ("B3LYP", "PBE", "WB97", "M06", "RKS", "UKS", "TPSS"))
        if is_dft:
            mf = scf.UKS(mol) if (spin > 0 or method_upper == "UKS") else scf.RKS(mol)
            if method_upper not in ("RKS", "UKS"): mf.xc = method
        else:
            mf = scf.UHF(mol) if (spin > 0 or method_upper == "UHF") else scf.RHF(mol)

        syms = [mol.atom_symbol(i) for i in range(mol.natm)]; counts = Counter(syms)
        formula = "".join("%s%s" % (e, str(counts[e]) if counts[e] > 1 else "") for e in sorted(counts.keys()))
        _cli.print_calc_summary(method, basis, charge, spin, mol.natm, formula)
        mf = _cli.run_scf_with_progress(mf, method, basis)

        if not mf.converged: mf, mol = self.compute_scf_adaptive(mol, spin=spin)
        return (SCFResult(True, float(mf.e_tot), mf.mo_coeff, mf.mo_occ, mf.mo_energy, basis, method), mol)

    def compute_esp(self, atom_spec, basis="cc-pvdz", grid_size=60, method="rhf", charge=0, spin=0):
        atom_spec = _safe_parse_atom_spec(atom_spec)
        mol = gto.M(atom=atom_spec, basis=basis, charge=charge, spin=spin, unit="Angstrom", verbose=0)
        mol.build(); mf = scf.RKS(mol) if spin == 0 else scf.UKS(mol); mf.run(); dm = mf.make_rdm1()
        d_p = p_p = None
        try:
            with tempfile.NamedTemporaryFile(suffix="_den.cube", delete=False) as f1: d_p = f1.name
            with tempfile.NamedTemporaryFile(suffix="_pot.cube", delete=False) as f2: p_p = f2.name
            cubegen.density(mol, d_p, dm, nx=grid_size, ny=grid_size, nz=grid_size, margin=10.0)
            cubegen.mep(mol, p_p, dm, nx=grid_size, ny=grid_size, nz=grid_size, margin=10.0)
            with open(d_p) as f: d_c = f.read()
            with open(p_p) as f: p_c = f.read()
        finally:
            for p in (d_p, p_p):
                if p and os.path.exists(p): os.unlink(p)
        vr, vxr, p_lo, p_hi = self._extract_surface_potential_range(d_c, p_c)
        abs_max = max(abs(p_lo), abs(p_hi))
        if abs_max < 1e-5: abs_max = 0.05
        _cli.print_esp_summary(vr, vxr, -abs_max, abs_max, p_lo, p_hi)
        return ESPResult(d_c, p_c, -abs_max, abs_max, vr, vxr, [mol.atom_symbol(i) for i in range(mol.natm)], float(mf.e_tot), basis, grid_size, 10.0)

    def _extract_surface_potential_range(self, den_cube, pot_cube, isoval=0.002):
        def get_data(cube):
            ls = cube.splitlines()
            if len(ls) < 7: return np.array([])
            toks2 = ls[2].split(); na = abs(int(toks2[0])); ds = 6 + na + (1 if int(toks2[0]) < 0 else 0)
            raw = " ".join(ls[ds:]).replace("D", "E").replace("d", "e")
            return np.fromstring(raw, sep=" ")
        darr = get_data(den_cube); parr = get_data(pot_cube)
        if len(darr) == 0 or len(darr) != len(parr): return -0.1, 0.1, -0.1, 0.1
        mask = (darr >= isoval * 0.8) & (darr <= isoval * 1.2)
        if not np.any(mask): mask = darr >= isoval
        surf_p = parr[mask]
        surf_p = surf_p[np.isfinite(surf_p)]
        if len(surf_p) == 0: return -0.1, 0.1, -0.1, 0.1
        p_lo = float(np.percentile(surf_p, 5))
        p_hi = float(np.percentile(surf_p, 95))
        return float(np.min(surf_p)), float(np.max(surf_p)), p_lo, p_hi

    def generate_cube(self, mol, coeffs, orbital_index, grid_points=(60,60,60)):
        with tempfile.NamedTemporaryFile(suffix=".cube", delete=False) as tmp: t_p = tmp.name
        try:
            cubegen.orbital(mol, t_p, coeffs[:, orbital_index], nx=grid_points[0], ny=grid_points[1], nz=grid_points[2], margin=10.0)
            with open(t_p) as f: return f.read()
        finally:
            if os.path.exists(t_p): os.remove(t_p)

    def compute_iao(self, scf_res, mol, minao="minao"):
        orbocc = scf_res.mo_coeff[:, scf_res.mo_occ > 0]
        iao_coeff = lo.iao.iao(mol, orbocc, minao=minao)
        charges = self._compute_iao_charges(mol, scf_res, iao_coeff)
        return IAOResult(coefficients=iao_coeff, charges=charges)

    def _iao_population_custom(self, mol, dm, iao_coeff):
        ovlp = mol.intor_symmetric("int1e_ovlp")
        s_iao = iao_coeff.T @ ovlp @ iao_coeff
        p_matrix = (iao_coeff @ np.linalg.inv(s_iao) @ iao_coeff.T @ ovlp @ dm @ ovlp)
        a_pop = [np.trace(p_matrix[b0:b1, b0:b1]) for b0, b1 in [mol.aoslice_by_atom()[i][2:] for i in range(mol.natm)]]
        return np.array(a_pop)

    def _compute_iao_charges(self, mol: Any, scf_result: SCFResult, iao_coeff: np.ndarray) -> np.ndarray:
        ovlp = mol.intor_symmetric("int1e_ovlp")
        orbocc = scf_result.mo_coeff[:, scf_result.mo_occ > 0]
        s_iao = iao_coeff.T @ ovlp @ iao_coeff
        eigvals, eigvecs = np.linalg.eigh(s_iao)
        s_iao_inv_half = eigvecs @ np.diag(1.0 / np.sqrt(eigvals)) @ eigvecs.T
        iao_orth = iao_coeff @ s_iao_inv_half
        proj = iao_orth.T @ ovlp @ orbocc
        dm_iao = (1.0 if mol.spin > 0 else 2.0) * proj @ proj.T

        from pyscf.lo.iao import reference_mol
        effective_minao, _ = self._resolve_minao(mol, "minao")
        pmol = reference_mol(mol, minao=effective_minao)
        ref_labels = pmol.ao_labels(fmt=False)
        n_iao = iao_orth.shape[1]
        charges = np.zeros(mol.natm)
        for j in range(n_iao):
            atom_idx = ref_labels[j][0]
            charges[atom_idx] += dm_iao[j, j]
        for i in range(mol.natm):
            charges[i] = mol.atom_charge(i) - charges[i]
        return charges

    def compute_ibo(self, scf_res, iao_res, mol, localization_method: str = "IBO"):
        orbocc = scf_res.mo_coeff[:, scf_res.mo_occ > 0]
        if localization_method.upper() == "BOYS":
            loc_obj = lo.Boys(mol, orbocc)
            ibo_coeff = loc_obj.kernel()
        elif localization_method.upper() == "PM":
            loc_obj = lo.PM(mol, orbocc)
            ibo_coeff = loc_obj.kernel()
        else:
            ibo_coeff = lo.ibo.ibo(mol, orbocc, iaos=iao_res.coefficients)
        n_ibo = ibo_coeff.shape[1]
        return IBOResult(coefficients=ibo_coeff, occupations=np.full(n_ibo, 2.0), n_ibo=n_ibo)

    def _resolve_minao(self, mol, minao="minao"):
        warnings = []; effective = minao; ecp_detected = False
        if hasattr(mol, "has_ecp"):
            ecp_result = mol.has_ecp()
            ecp_detected = bool(ecp_result) if not isinstance(ecp_result, dict) else len(ecp_result) > 0
        if not ecp_detected and hasattr(mol, "_ecp") and mol._ecp: ecp_detected = True
        if ecp_detected and minao == "minao":
            effective = "sto-3g"
            warnings.append("ECP detected. Switched IAO reference basis to 'sto-3g'.")
        if _has_heavy_tm(mol) and minao == "minao":
            warnings.append("Heavy TM (4d/5d) detected. Consider using minao='sto-3g' if IAO fails.")
        return effective, warnings

    @staticmethod
    def _unpack_uhf(mo_coeff, mo_occ):
        if isinstance(mo_coeff, (tuple, list)): return mo_coeff[0], mo_coeff[1], mo_occ[0], mo_occ[1]
        elif isinstance(mo_coeff, np.ndarray) and mo_coeff.ndim == 3: return mo_coeff[0], mo_coeff[1], mo_occ[0], mo_occ[1]
        raise ValueError("Unexpected mo_coeff type")

    def export_molden(self, mol_obj: Any, mo_coeff: np.ndarray, output_path: str) -> str:
        from pyscf.tools import molden as molden_mod
        molden_mod.from_mo(mol_obj, output_path, mo_coeff)
        return str(Path(output_path).resolve())

    def compute_scf_flexible(self, atom_spec: str, basis: str = "sto-3g", charge: int = 0, spin: int = 0, adaptive: bool = False):
        if not _HAS_PYSCF: raise ImportError("PySCF가 설치되지 않았습니다.")
        atom_spec = _safe_parse_atom_spec(atom_spec)
        mol = gto.M(atom=atom_spec, basis=basis, charge=charge, spin=spin, verbose=0)
        if adaptive: return self.compute_scf_adaptive(mol, spin=spin)
        mf = scf.UHF(mol) if spin > 0 else scf.RHF(mol)
        mf.kernel()
        if not mf.converged: raise RuntimeError(f"SCF not converged for spin={spin}")
        return mf, mol

    def compute_scf_adaptive(self, mol, spin: int = 0, max_escalation: int = 4):
        max_level = min(max_escalation, len(ConvergenceStrategy.LEVELS) - 1)
        for level in range(max_level + 1):
            mf = scf.UHF(mol) if spin > 0 else scf.RHF(mol)
            mf = ConvergenceStrategy.apply(mf, level)
            try:
                mf = _cli.run_scf_with_progress(mf, f"Adaptive L{level}", mol.basis)
                if mf.converged:
                    logger.info("SCF converged at level %d: %s (E=%.8f)", level, ConvergenceStrategy.level_name(level), mf.e_tot)
                    return mf, mol
            except Exception as e:
                logger.warning("Level %d failed: %s", level, e)
                continue
        raise ConvergenceError(f"SCF failed after {max_level + 1} strategies.")

    def compute_scf_relativistic(self, atom_spec, basis="def2-svp", ecp=None, spin=0, charge=0, relativistic="sfx2c1e"):
        atom_spec = _safe_parse_atom_spec(atom_spec)
        mol = gto.M(atom=atom_spec, basis=basis, ecp=ecp, charge=charge, spin=spin, verbose=0)
        mf = scf.UHF(mol) if spin > 0 else scf.RHF(mol)
        if relativistic == "sfx2c1e": mf = mf.sfx2c1e()
        elif relativistic == "x2c": mf = mf.x2c()
        mf = _cli.run_scf_with_progress(mf, f"Relativistic ({relativistic})", basis)
        if not mf.converged: mf, mol = self.compute_scf_adaptive(mol, spin=spin)
        return mf, mol

    def compute_iao_uhf(self, mf, mol, minao: str = "minao"):
        effective, warnings = self._resolve_minao(mol, minao)
        mo_a, mo_b, occ_a, occ_b = self._unpack_uhf(mf.mo_coeff, mf.mo_occ)
        mo_occ_a = mo_a[:, occ_a > 0]; mo_occ_b = mo_b[:, occ_b > 0]
        iao_a = lo.iao.iao(mol, mo_occ_a, minao=effective)
        iao_b = lo.iao.iao(mol, mo_occ_b, minao=effective)
        return {"alpha": {"iao_coeff": iao_a, "n_iao": iao_a.shape[1]}, "beta": {"iao_coeff": iao_b, "n_iao": iao_b.shape[1]}, "is_uhf": True, "minao_used": effective, "warnings": warnings}

    def compute_ibo_uhf(self, mf, iao_result, mol):
        mo_a, mo_b, occ_a, occ_b = self._unpack_uhf(mf.mo_coeff, mf.mo_occ)
        mo_occ_a = mo_a[:, occ_a > 0]; mo_occ_b = mo_b[:, occ_b > 0]
        ibo_a = lo.ibo.ibo(mol, mo_occ_a, iaos=iao_result["alpha"]["iao_coeff"])
        ibo_b = lo.ibo.ibo(mol, mo_occ_b, iaos=iao_result["beta"]["iao_coeff"])
        return {"alpha": {"ibo_coeff": ibo_a, "n_ibo": ibo_a.shape[1]}, "beta": {"ibo_coeff": ibo_b, "n_ibo": ibo_b.shape[1]}, "is_uhf": True, "total_ibo": ibo_a.shape[1] + ibo_b.shape[1]}

    def compute_uhf_charges(self, mf, mol):
        dm = mf.make_rdm1()
        dm_total = dm[0] + dm[1] if (isinstance(dm, np.ndarray) and dm.ndim == 3) or isinstance(dm, (list, tuple)) else dm
        s = mol.intor("int1e_ovlp")
        pop, chg = mf.mulliken_pop(mol, dm_total, s, verbose=0)
        return [float(c) for c in chg]

    def compute_geomopt(
        self,
        atom_spec: str,
        basis: str = "def2-svp",
        method: str = "B3LYP",
        charge: int = 0,
        spin: int = 0,
        maxsteps: int = 100,
        use_d3: bool = True,
    ) -> dict:
        """PySCF geomeTRIC 기반 구조 최적화.

        Parameters
        ----------
        atom_spec : str
            원자 좌표 (XYZ 또는 PySCF 형식).
        basis : str
            기저 함수 (기본: def2-svp).
        method : str
            계산 방법 (기본: B3LYP).
        charge, spin : int
            분자 전하 및 스핀 다중도.
        maxsteps : int
            최대 최적화 단계 수.
        use_d3 : bool
            DFT-D3 분산 보정 사용 여부.

        Returns
-------
        dict
            optimized_xyz: 최적화된 XYZ 문자열,
            energy: 최종 에너지 (Hartree),
            converged: 수렴 여부,
            n_steps: 최적화 단계 수.
        """
        if not _HAS_PYSCF:
            raise ImportError("PySCF가 설치되지 않았습니다.")

        try:
            from pyscf.geomopt.geometric_solver import optimize as geom_optimize
        except ImportError:
            raise ImportError(
                "geomeTRIC이 설치되지 않았습니다. "
                "'pip install geometric'으로 설치하세요."
            )

        atom_spec = _safe_parse_atom_spec(atom_spec)
        mol = gto.M(atom=atom_spec, basis=basis, charge=charge, spin=spin,
                     unit="Angstrom", verbose=0)

        method_upper = method.upper()
        is_dft = any(xc in method_upper for xc in (
            "B3LYP", "PBE", "WB97", "M06", "RKS", "UKS", "TPSS", "PBE0",
        ))

        if is_dft:
            from pyscf import dft
            mf = dft.UKS(mol) if spin > 0 else dft.RKS(mol)
            if method_upper not in ("RKS", "UKS"):
                mf.xc = method
            else:
                mf.xc = "b3lyp"
        else:
            mf = scf.UHF(mol) if spin > 0 else scf.RHF(mol)

        # D3 분산 보정
        if use_d3 and is_dft:
            try:
                from pyscf import dftd3
                mf = dftd3.dftd3(mf)
                logger.info("DFT-D3 dispersion correction enabled")
            except ImportError:
                logger.warning("pyscf-dftd3 not installed, skipping D3 correction")

        mf = _cli.run_scf_with_progress(mf, method, basis)

        # geomeTRIC 최적화
        conv_params = {
            "convergence_energy": 1e-6,
            "convergence_grms": 3e-4,
            "convergence_gmax": 4.5e-4,
            "convergence_drms": 1.2e-3,
            "convergence_dmax": 1.8e-3,
        }

        step_count = [0]
        def _opt_callback(envs):
            step_count[0] += 1
            if _cli.console and _HAS_RICH:
                e = envs.get("energy", 0.0)
                gnorm = envs.get("gradnorm", 0.0)
                _cli.console.print(
                    "  [dim]Opt Step[/dim] [bold]%d[/bold]  "
                    "E=%.8f  |g|=%.6f" % (step_count[0], e, gnorm)
                )

        try:
            mol_eq = geom_optimize(
                mf, maxsteps=maxsteps, callback=_opt_callback, **conv_params
            )
            converged = True
        except Exception as e:
            logger.warning("Geometry optimization did not converge: %s", e)
            mol_eq = mf.mol  # 마지막 지오메트리 사용
            converged = False

        # 최적화된 좌표를 XYZ 문자열로 변환
        from qcviz_mcp.analysis.sanitize import atoms_to_xyz_string
        coords = mol_eq.atom_coords(unit="Angstrom")
        symbols = [mol_eq.atom_symbol(i) for i in range(mol_eq.natm)]
        opt_atoms = list(zip(symbols, coords[:, 0], coords[:, 1], coords[:, 2]))
        opt_xyz = atoms_to_xyz_string(
            opt_atoms,
            comment="Optimized: %s/%s E=%.8f Ha" % (method, basis, mf.e_tot)
        )

        return {
            "optimized_xyz": opt_xyz,
            "optimized_atom_spec": mol_eq.tostring(),
            "energy_hartree": float(mf.e_tot),
            "converged": converged,
            "n_steps": step_count[0],
            "method": method,
            "basis": basis,
        }

registry.register(PySCFBackend)

```

---

## 파일: `src/qcviz_mcp/backends/registry.py` (65줄, 2257bytes)

```python
"""QCViz-MCP 백엔드 레지스트리 시스템.

플러그인 형태의 백엔드를 등록하고 관리하며, 사용 가능한 백엔드를 동적으로 제공합니다.
"""

from __future__ import annotations

import logging
from typing import TypeVar

from qcviz_mcp.backends.base import (
    BackendBase,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BackendBase)


class BackendNotAvailableError(Exception):
    """요청한 백엔드를 사용할 수 없거나 필수 의존성이 설치되지 않았을 때 발생하는 예외."""

    pass


class BackendRegistry:
    """백엔드 클래스들을 등록하고 관리하는 레지스트리."""

    def __init__(self) -> None:
        self._backends: dict[str, type[BackendBase]] = {}
        self._instances: dict[str, BackendBase] = {}

    def register(self, backend_class: type[BackendBase]) -> None:
        """새로운 백엔드 클래스를 등록합니다."""
        name = backend_class.name()
        self._backends[name] = backend_class
        logger.debug("백엔드 %s 등록됨", name)

    def get(self, name: str) -> BackendBase:
        """이름으로 백엔드 인스턴스를 가져옵니다(싱글톤)."""
        if name not in self._backends:
            raise ValueError(f"알 수 없는 백엔드: {name}")

        backend_class = self._backends[name]
        if not backend_class.is_available():
            raise BackendNotAvailableError(
                f"백엔드 '{name}'를 사용할 수 없습니다. 의존성 패키지를 설치해주세요."
            )

        if name not in self._instances:
            self._instances[name] = backend_class()

        return self._instances[name]

    def get_by_type(self, backend_type: type[T]) -> list[T]:
        """특정 타입(인터페이스)을 구현한 사용 가능한 모든 백엔드 인스턴스 목록을 반환합니다."""
        instances = []
        for name, cls in self._backends.items():
            if issubclass(cls, backend_type) and cls.is_available():
                instances.append(self.get(name))
        return instances


# 전역 기본 레지스트리 인스턴스
registry = BackendRegistry()

```

---

## 파일: `src/qcviz_mcp/backends/viz_backend.py` (2343줄, 72371bytes)

```python
"""시각화 백엔드 — Enterprise v3.5 UI/UX Restoration & Upgrade.

v3.5 패치 내역:
1. [RESTORE] v2.3.0의 모든 UI 요소 100% 복구 + v4 기능 통합.
2. [UPGRADE] Enterprise-grade sidebar layout, floating toolbar.
3. [ADD] Isovalue/Opacity sliders, Representation toggle, Labels,
   Charges overlay, Screenshot, Keyboard shortcuts.
4. [STYLE] Clean commercial SaaS aesthetic — white background,
   refined typography, subtle shadows.
5. [FIX] Flexbox scroll (min-height:0), Orbital clipping (zoom & slab),
   White background, Resize handling.
"""

from __future__ import annotations

import base64
import html
import json
import logging
import re
import textwrap
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from qcviz_mcp.backends.base import VisualizationBackend
from qcviz_mcp.backends.registry import registry

logger = logging.getLogger("qcviz_mcp.viz_backend")


_ESP_PRESET_ORDER = (
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
)

def _json_for_script(obj) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")

def _build_esp_select_options(presets: dict) -> str:
    seen = set()
    items = []

    for key in _ESP_PRESET_ORDER:
        if key in presets:
            items.append((key, presets[key]))
            seen.add(key)

    for key, value in presets.items():
        if key not in seen:
            items.append((key, value))

    lines = []
    for key, spec in items:
        label = html.escape(str(spec.get("name") or key))
        value = html.escape(str(key))
        selected = ' selected' if key == "rwb" else ""
        lines.append(f'<option value="{value}"{selected}>{label}</option>')

    return "\n".join(lines)


ESP_PRESETS_DATA = {
    "rwb": {
        "name": "Standard RWB",
        "gradient_type": "rwb",
        "colors": [],
    },
    "nature": {
        "name": "Nature",
        "gradient_type": "linear",
        "colors": ["#e91e63", "#ffffff", "#00bcd4"],
    },
    "acs": {
        "name": "ACS Gold",
        "gradient_type": "linear",
        "colors": ["#e65100", "#fffde7", "#4a148c"],
    },
    "rsc": {
        "name": "RSC Pastel",
        "gradient_type": "linear",
        "colors": ["#ff8a80", "#f5f5f5", "#82b1ff"],
    },
    "viridis": {
        "name": "Viridis",
        "gradient_type": "linear",
        "colors": [
            "#440154", "#31688e", "#21918c",
            "#35b779", "#fde725",
        ],
    },
    "inferno": {
        "name": "Inferno",
        "gradient_type": "linear",
        "colors": [
            "#000004", "#420a68", "#932667",
            "#dd513a", "#fcffa4",
        ],
    },
    "spectral": {
        "name": "Spectral",
        "gradient_type": "linear",
        "colors": [
            "#d53e4f", "#fc8d59", "#fee08b",
            "#e6f598", "#99d594", "#3288bd",
        ],
    },
    "grey": {
        "name": "Greyscale",
        "gradient_type": "linear",
        "colors": ["#212121", "#9e9e9e", "#fafafa"],
    },
    "matdark": {
        "name": "Materials Dark",
        "gradient_type": "linear",
        "colors": ["#ff6f00", "#1a1a2e", "#00e5ff"],
    },
    "hicon": {
        "name": "High Contrast",
        "gradient_type": "linear",
        "colors": ["#ff1744", "#000000", "#2979ff"],
    },
}


ESP_PRESETS_DATA = {
    "rwb": {
        "name": "Standard RWB",
        "gradient_type": "rwb",
        "colors": [],
    },
    "nature": {
        "name": "Nature",
        "gradient_type": "linear",
        "colors": ["#e91e63", "#ffffff", "#00bcd4"],
    },
    "acs": {
        "name": "ACS Gold",
        "gradient_type": "linear",
        "colors": ["#e65100", "#fffde7", "#4a148c"],
    },
    "rsc": {
        "name": "RSC Pastel",
        "gradient_type": "linear",
        "colors": ["#ff8a80", "#f5f5f5", "#82b1ff"],
    },
    "viridis": {
        "name": "Viridis",
        "gradient_type": "linear",
        "colors": [
            "#440154", "#31688e", "#21918c",
            "#35b779", "#fde725",
        ],
    },
    "inferno": {
        "name": "Inferno",
        "gradient_type": "linear",
        "colors": [
            "#000004", "#420a68", "#932667",
            "#dd513a", "#fcffa4",
        ],
    },
    "spectral": {
        "name": "Spectral",
        "gradient_type": "linear",
        "colors": [
            "#d53e4f", "#fc8d59", "#fee08b",
            "#e6f598", "#99d594", "#3288bd",
        ],
    },
    "grey": {
        "name": "Greyscale",
        "gradient_type": "linear",
        "colors": ["#212121", "#9e9e9e", "#fafafa"],
    },
    "matdark": {
        "name": "Materials Dark",
        "gradient_type": "linear",
        "colors": ["#ff6f00", "#1a1a2e", "#00e5ff"],
    },
    "hicon": {
        "name": "High Contrast",
        "gradient_type": "linear",
        "colors": ["#ff1744", "#000000", "#2979ff"],
    },
}


def build_web_visualization_payload(payload: DashboardPayload) -> dict:
    orbitals = []
    selected_key = None

    for i, orb in enumerate(payload.orbitals or []):
        key = f"orb:{orb.index}"
        item = {
            "key": key,
            "mo_index": int(orb.index),
            "label": orb.label or f"MO {orb.index}",
            "energy_ev": float(orb.energy_ev or 0.0),
            "occupation": None,
            "spin": "restricted",
            "cube_b64": orb.cube_b64,
        }
        orbitals.append(item)

        label_upper = str(item["label"]).upper()
        if selected_key is None and label_upper == "HOMO":
            selected_key = key

    if selected_key is None and orbitals:
        selected_key = orbitals[0]["key"]

    esp_available = bool(
        payload.esp_data
        and payload.esp_data.density_cube_b64
        and payload.esp_data.potential_cube_b64
    )

    esp_range = [-0.05, 0.05]
    if payload.esp_data:
        esp_range = [
            float(payload.esp_data.vmin),
            float(payload.esp_data.vmax),
        ]

    return {
        "status": "ready" if orbitals or esp_available else "empty",
        "defaults": {
            "orbital_iso": 0.02,
            "orbital_opacity": 0.82,
            "esp_iso": 0.002,
            "esp_opacity": 0.80,
            "esp_range": esp_range,
            "esp_preset": "rwb",
        },
        "orbitals": {
            "available": bool(orbitals),
            "items": orbitals,
            "selected_key": selected_key,
        },
        "esp": {
            "available": esp_available,
            "density_cube_b64": payload.esp_data.density_cube_b64 if payload.esp_data else None,
            "potential_cube_b64": payload.esp_data.potential_cube_b64 if payload.esp_data else None,
            "presets": ESP_PRESETS_DATA,
        },
        "warnings": [],
        "meta": {
            "molecule_name": payload.molecule_name,
            "method": payload.method,
            "basis": payload.basis,
            "energy_hartree": payload.energy_hartree,
        },
    }


class CubeNormalizer:
    _FLOAT_RE = re.compile(
        r"[+-]?(?:\d+\.?\d*|\.\d+)[EeDd][+-]?\d+|[+-]?(?:\d+\.?\d*|\.\d+)"
    )

    @classmethod
    def normalize(cls, cube_text: str) -> str:
        if not cube_text or not cube_text.strip():
            return ""
        raw = cube_text.replace("\r\n", "\n").replace("\r", "\n")
        lines = raw.split("\n")
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if len(lines) < 7:
            return cube_text
        try:
            out = [lines[0], lines[1]]
            toks2 = lines[2].split()
            na = abs(int(toks2[0]))
            has_dset = int(toks2[0]) < 0
            line2 = "%5d %11s %11s %11s" % (na, toks2[1], toks2[2], toks2[3])
            if len(toks2) > 4:
                line2 += " %4s" % toks2[4]
            out.append(line2)
            for i in range(3):
                toks = lines[3 + i].split()
                out.append(
                    "%5d %11s %11s %11s"
                    % (abs(int(toks[0])), toks[1], toks[2], toks[3])
                )
            for ia in range(na):
                toks = lines[6 + ia].split()
                if len(toks) >= 5:
                    out.append(
                        "%5s %11s %11s %11s %11s"
                        % (toks[0], toks[1], toks[2], toks[3], toks[4])
                    )
                else:
                    out.append(lines[6 + ia])
            ds = 6 + na + (1 if has_dset else 0)
            db = " ".join(lines[ds:]).replace("D", "E").replace("d", "e")
            floats = cls._FLOAT_RE.findall(db)
            if not floats:
                return cube_text
            for i in range(0, len(floats), 6):
                chunk = floats[i : i + 6]
                out.append("  ".join("%13.5E" % float(v) for v in chunk))
            return "\n".join(out) + "\n"
        except Exception:
            return cube_text

    @classmethod
    def to_base64(cls, cube_text: str) -> str:
        return base64.b64encode(
            cls.normalize(cube_text).encode("utf-8")
        ).decode("ascii")


@dataclass
class OrbitalRenderData:
    index: int
    label: str
    cube_b64: str
    energy_ev: float = 0.0


@dataclass
class ESPRenderData:
    density_cube_b64: str
    potential_cube_b64: str
    vmin: float = -0.1
    vmax: float = 0.1


@dataclass
class DashboardPayload:
    molecule_name: str
    xyz_data: str
    atom_symbols: List[str]
    basis: str
    method: str
    energy_hartree: float
    orbitals: List[OrbitalRenderData] = field(default_factory=list)
    charges: Dict[str, float] = field(default_factory=dict)
    esp_data: Optional[ESPRenderData] = None


class DashboardTemplateEngine:
    @classmethod
    def render(cls, p: DashboardPayload) -> str:
        xyz_b64 = base64.b64encode(
            p.xyz_data.strip().encode("utf-8")
        ).decode("ascii")
        formula = cls._formula(p.atom_symbols)

        orb_data_list = [
            {
                "ix": o.index,
                "label": o.label,
                "b64": o.cube_b64,
                "ev": o.energy_ev,
            }
            for o in p.orbitals
        ]

        charge_vals = list(p.charges.values()) if p.charges else []
        atom_labels = [
            "%s%d" % (s, i + 1) for i, s in enumerate(p.atom_symbols)
        ]

        esp_presets_data = ESP_PRESETS_DATA

        charge_html = ""
        if p.charges:
            mx = max(abs(v) for v in p.charges.values()) or 1.0
            for i, (sym, val) in enumerate(p.charges.items()):
                wp = abs(val) / mx * 50
                color_class = "charge-pos" if val > 0 else "charge-neg"
                margin = "50%" if val >= 0 else f"{50 - wp:.1f}%"
                charge_html += (
                    f'<div class="charge-row" data-idx="{i}" onclick="QV.lockAtom({i})">'
                    f'<div class="charge-label">{sym}</div>'
                    f'<div class="charge-bar-container">'
                    f'<div class="charge-bar-track">'
                    f'<div class="charge-bar-fill {color_class}" style="width:{wp:.1f}%; left:{margin}"></div>'
                    f'<div class="charge-zero-line"></div>'
                    f'</div>'
                    f'</div>'
                    f'<div class="charge-val {color_class}">{val:+.4f}</div>'
                    f'</div>'
                )

        orb_list_html = "".join(
            [
                f'<li data-idx="{i}" onclick="QV.showOrb({i})">'
                f'<div class="orb-idx">{i+1}</div>'
                f'<div class="orb-name">{o.label}</div>'
                f'<div class="orb-energy">{o.energy_ev:.3f} eV</div>'
                f'</li>'
                for i, o in enumerate(p.orbitals)
            ]
        )

        eden, epot, emin, emax = ("", "", -0.1, 0.1)
        if p.esp_data:
            eden = p.esp_data.density_cube_b64
            epot = p.esp_data.potential_cube_b64
            emin = p.esp_data.vmin
            emax = p.esp_data.vmax

        wiki_map = {
            "H2O": "Water",
            "CO2": "Carbon_dioxide",
            "C10H8": "Naphthalene",
            "C6H6": "Benzene",
            "NH3": "Ammonia",
            "CH4": "Methane",
        }
        wiki_q = wiki_map.get(formula, p.molecule_name)

        html = _DASHBOARD_HTML
        html = html.replace("%%MOL_NAME%%", html.escape(p.molecule_name))
        html = html.replace("%%CSS%%", _DASHBOARD_CSS)

        # Prepare JS with presets
        dashboard_js = _DASHBOARD_JS.replace("%%ESP_PRESETS_JSON%%", _json_for_script(esp_presets_data))
        html = html.replace("%%JS%%", dashboard_js)

        html = html.replace("%%ESP_OPTIONS%%", _build_esp_select_options(esp_presets_data))
        html = html.replace("%%XYZ_B64%%", xyz_b64)
        html = html.replace("%%ORB_JSON%%", json.dumps(orb_data_list))
        html = html.replace(
            "%%CHARGES_VAL_JSON%%", json.dumps(charge_vals)
        )
        html = html.replace(
            "%%ATOM_LABELS_JSON%%", json.dumps(atom_labels)
        )
        html = html.replace("%%WIKI_QUERY%%", json.dumps(wiki_q))
        html = html.replace(
            "%%ESP_PRESETS_DATA%%", json.dumps(esp_presets_data)
        )
        html = html.replace("%%EDEN_B64%%", eden)
        html = html.replace("%%EPOT_B64%%", epot)
        html = html.replace("%%EMIN%%", str(emin))
        html = html.replace("%%EMAX%%", str(emax))
        html = html.replace("%%BASIS%%", p.basis)
        html = html.replace("%%METHOD%%", p.method)
        html = html.replace(
            "%%ENERGY%%", "%.6f" % p.energy_hartree
        )
        html = html.replace("%%FORMULA%%", formula)
        html = html.replace("%%ORB_LIST%%", orb_list_html)
        html = html.replace("%%CHARGE_BARS%%", charge_html)
        return html

    @staticmethod
    def _formula(symbols):
        c = Counter(symbols)
        res = []
        for e in ["C", "H"]:
            if e in c:
                n = c.pop(e)
                res.append(e + (str(n) if n > 1 else ""))
        for e in sorted(c.keys()):
            n = c[e]
            res.append(e + (str(n) if n > 1 else ""))
        return "".join(res)


def build_web_visualization_payload(payload: DashboardPayload) -> dict:
    orbitals = []
    selected_key = None

    for i, orb in enumerate(payload.orbitals or []):
        key = f"orb:{orb.index}"
        item = {
            "key": key,
            "mo_index": int(orb.index),
            "label": orb.label or f"MO {orb.index}",
            "energy_ev": float(orb.energy_ev or 0.0),
            "occupation": None,
            "spin": "restricted",
            "cube_b64": orb.cube_b64,
        }
        orbitals.append(item)

        label_upper = str(item["label"]).upper()
        if selected_key is None and label_upper == "HOMO":
            selected_key = key

    if selected_key is None and orbitals:
        selected_key = orbitals[0]["key"]

    esp_available = bool(
        payload.esp_data
        and payload.esp_data.density_cube_b64
        and payload.esp_data.potential_cube_b64
    )

    esp_range = [-0.05, 0.05]
    if payload.esp_data:
        esp_range = [
            float(payload.esp_data.vmin),
            float(payload.esp_data.vmax),
        ]

    return {
        "status": "ready" if orbitals or esp_available else "empty",
        "defaults": {
            "orbital_iso": 0.02,
            "orbital_opacity": 0.82,
            "esp_iso": 0.002,
            "esp_opacity": 0.80,
            "esp_range": esp_range,
            "esp_preset": "rwb",
        },
        "orbitals": {
            "available": bool(orbitals),
            "items": orbitals,
            "selected_key": selected_key,
        },
        "esp": {
            "available": esp_available,
            "density_cube_b64": payload.esp_data.density_cube_b64 if payload.esp_data else None,
            "potential_cube_b64": payload.esp_data.potential_cube_b64 if payload.esp_data else None,
            "presets": ESP_PRESETS_DATA,
        },
        "warnings": [],
        "meta": {
            "molecule_name": payload.molecule_name,
            "method": payload.method,
            "basis": payload.basis,
            "energy_hartree": payload.energy_hartree,
        },
    }


class Py3DmolBackend(VisualizationBackend):
    @classmethod
    def name(cls):
        return "py3dmol"

    @staticmethod
    def is_available():
        return True

    def prepare_web_visualization_payload(self, payload):
        return build_web_visualization_payload(payload)

    def render_dashboard(self, payload):
        return DashboardTemplateEngine.render(payload)

    def prepare_orbital_data(self, c, i, l, energy=0.0):
        return OrbitalRenderData(
            i, l, CubeNormalizer.to_base64(c), energy
        )

    def prepare_esp_data(self, d, p, vmin, vmax):
        return ESPRenderData(
            CubeNormalizer.to_base64(d),
            CubeNormalizer.to_base64(p),
            vmin,
            vmax,
        )

    def render_molecule(self, xyz, style="stick"):
        return _SIMPLE_MOL.replace(
            "%%XYZ_B64%%",
            base64.b64encode(xyz.encode()).decode(),
        )

    def render_orbital(self, xyz, cube, isovalue=0.02):
        return _SIMPLE_ORB.replace(
            "%%XYZ_B64%%",
            base64.b64encode(xyz.encode()).decode(),
        ).replace("%%CUBE_B64%%", CubeNormalizer.to_base64(cube))

    def render_orbital_from_cube(
        self, cube_text, geometry_xyz, isovalue=0.02
    ):
        return self.render_orbital(geometry_xyz, cube_text, isovalue)


registry.register(Py3DmolBackend)

_DASHBOARD_CSS = """\
<style>
/* ─────────────────────────────────────────────
   QCViz Enterprise Web — style.css
   Scientific SaaS + Minimal Enterprise Dashboard
   CSS-only redesign for existing HTML/JS
   ───────────────────────────────────────────── */

/* ── Design Tokens ─────────────────────────── */
:root {
  /* ── 배경 계층 (Surface Hierarchy) ── */
  --bg-app: #f1f5fb;
  --bg-app-gradient: radial-gradient(ellipse at top left, rgba(79, 70, 229, 0.07), transparent 40%),
                     radial-gradient(ellipse at bottom right, rgba(2, 132, 199, 0.05), transparent 35%),
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
  --shadow-lg: 0 18px 40px rgba(15, 23, 42, 0.08), 0 6px 16px rgba(15, 23, 42, 0.04);
  --shadow-brand: 0 4px 14px rgba(79, 70, 229, 0.25);

  /* ── 라운딩 ── */
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
  --radius-xl: 20px;
  --radius-full: 9999px;

  /* ── 트랜지션 ── */
  --ease-out: cubic-bezier(.2, .8, .2, 1);
  --duration-fast: 150ms;
  --duration-normal: 220ms;
  --duration-slow: 320ms;

  /* ── 타이포그래피 ── */
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
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
  height: 100%;
  overflow: hidden;
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
  height: 100%;
  min-height: 0; /* CRITICAL for nested flex scroll */
  display: flex;
  flex-direction: column;
}

/* ── QCViz-MCP Specific Layout Mappings ── */

.layout-container {
  display: flex;
  height: 100vh;
  width: 100vw;
  background: var(--bg-app-gradient);
  overflow: hidden;
}

.main-area {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  padding: 16px;
  gap: 16px;
}

.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
  background: var(--surface-0);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  backdrop-filter: blur(12px);
  flex: 0 0 auto;
}

.logo-area {
  display: flex;
  align-items: center;
  gap: 12px;
  font-weight: 700;
  font-size: var(--font-size-lg);
  color: var(--text-primary);
}

.logo-icon {
  width: 32px;
  height: 32px;
  background: linear-gradient(135deg, var(--brand), var(--accent));
  color: white;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
}

.content-row {
  display: flex;
  flex: 1 1 auto;
  gap: 16px;
  min-height: 0; /* allows flex scrolling child */
}

.sidebar {
  display: flex;
  flex-direction: column;
  width: 360px;
  flex: 0 0 360px;
  background: var(--surface-0);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  backdrop-filter: blur(12px);
  overflow: hidden;
}

.sidebar-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--divider);
  background: var(--surface-1);
}

.sidebar-header h3 {
  font-size: var(--font-size-md);
  font-weight: 700;
  margin: 0;
}

.sidebar-scroll {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.viewer-container {
  flex: 1 1 auto;
  position: relative;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.info-grid {
  display: grid;
  grid-template-columns: minmax(80px, max-content) 1fr;
  gap: 8px 12px;
  font-size: var(--font-size-sm);
}

.info-label {
  color: var(--text-muted);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-size: var(--font-size-xs);
}

.info-value {
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-weight: 500;
}

.wiki-box {
  margin-top: 12px;
  padding: 12px;
  background: var(--surface-2);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
  line-height: 1.5;
}

.slider-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
}

.slider-group label {
  display: flex;
  justify-content: space-between;
  font-size: var(--font-size-xs);
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.slider-group .val {
  color: var(--brand);
  font-family: var(--font-mono);
}

input[type=range] {
  -webkit-appearance: none;
  width: 100%;
  background: transparent;
  padding: 0;
  border: none;
  box-shadow: none;
}

input[type=range]::-webkit-slider-thumb {
  -webkit-appearance: none;
  height: 16px;
  width: 16px;
  border-radius: 50%;
  background: var(--brand);
  cursor: pointer;
  margin-top: -6px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.3);
}

input[type=range]::-webkit-slider-runnable-track {
  width: 100%;
  height: 4px;
  cursor: pointer;
  background: var(--border-strong);
  border-radius: 2px;
}

/* ESP Colorbar */
.esp-colorbar {
  height: 8px;
  border-radius: 4px;
  margin-top: 4px;
}

.esp-labels {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-muted);
  margin-top: 4px;
}

/* Lists */
.orb-list, .charge-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.orb-item, .charge-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}

.orb-item:hover, .charge-row:hover {
  border-color: var(--border-strong);
  background: var(--brand-subtle);
}

.orb-item.active, .charge-row.active {
  background: var(--brand-muted);
  border-color: var(--brand);
}

.orb-idx, .c-atom {
  font-family: var(--font-mono);
  font-weight: 600;
  font-size: var(--font-size-sm);
  color: var(--text-primary);
  width: 30px;
}

.orb-label {
  flex: 1;
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
}

.orb-ev, .c-val {
  font-family: var(--font-mono);
  font-size: var(--font-size-sm);
  color: var(--brand-strong);
  font-weight: 600;
}

.charge-row .c-val.pos { color: var(--danger); }
.charge-row .c-val.neg { color: var(--brand); }

#v3d {
  width: 100%;
  height: 100%;
}

.panel {
  background: var(--surface-0);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md);
  padding: 16px;
  display: flex;
  flex-direction: column;
}

.panel-title {
  display: flex;
  align-items: center;
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

.badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: var(--radius-full);
  font-size: var(--font-size-xs);
  font-weight: 700;
  letter-spacing: 0.02em;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text-secondary);
}

.toolbar {
  display: flex;
  gap: 8px;
}

button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--surface-1);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}

button:hover {
  border-color: var(--border-strong);
  color: var(--text-primary);
}

button.active {
  background: var(--brand-muted);
  border-color: var(--brand);
  color: var(--brand-strong);
  font-weight: 600;
}

/* ── Status display (bottom right) ── */
#status-display {
  position: absolute;
  bottom: 16px;
  right: 16px;
  background: rgba(15, 23, 42, 0.7);
  color: #fff;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-family: var(--font-mono);
  backdrop-filter: blur(4px);
  pointer-events: none;
  z-index: 10;
}

/* ── Loader ── */
#loader {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  z-index: 50;
  background: rgba(255, 255, 255, 0.9);
  padding: 16px 24px;
  border-radius: 8px;
  box-shadow: var(--shadow-md);
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 12px;
}
.spinner {
  width: 20px;
  height: 20px;
  border: 3px solid var(--border);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}
@keyframes spin { 100% { transform: rotate(360deg); } }
</style>
"""

_DASHBOARD_JS = """\
<script>
/* ============================================================
   QCViz-MCP Enterprise v3.5 — Dashboard JS (Bug-Fixed)
   ============================================================ */

var QV = window.QV || {};
(function() {
    "use strict";

    // ── State ──
    var v = null;           // 3Dmol viewer instance
    var molModel = null;    // current molecule model

    const QCVIZ_ESP_PRESETS = %%ESP_PRESETS_JSON%%;
    const QCVIZ_ESP_PRESET_ORDER = ["rwb", "viridis", "inferno", "spectral", "nature", "acs", "rsc", "matdark", "grey", "hicon"];

    let qcvizCachedEDenVol = null;
    let qcvizCachedEPotVol = null;
    let qcvizCachedEDenKey = null;
    let qcvizCachedEPotKey = null;
    const qcvizCachedOrbVols = new Map();

    let qcvizEspSurfaceId = null;
    let qcvizOrbSurfaceIds = [];

    function qcvizGetViewer() {
      if (typeof v !== "undefined" && v) return v;
      if (typeof viewer !== "undefined" && viewer) return viewer;
      return null;
    }

    function qcvizNormalizeB64(s) {
      s = String(s || "").trim().replace(/\\s+/g, "").replace(/-/g, "+").replace(/_/g, "/");
      const pad = s.length % 4;
      if (pad) s += "=".repeat(4 - pad);
      return s;
    }

    function qcvizDecodeB64Text(b64) {
      try {
        const normalized = qcvizNormalizeB64(b64);
        const raw = atob(normalized);
        if (typeof TextDecoder === "undefined") return raw;
        const bytes = new Uint8Array(raw.length);
        for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
        return new TextDecoder("utf-8", { fatal: false }).decode(bytes);
      } catch (err) {
        console.error("[QCViz] Base64 decode failed:", err);
        return null;
      }
    }

    function qcvizSetDashboardStatus(msg, isError) {
      const el = document.getElementById("status-text");
      if (el) {
        el.textContent = msg;
        el.style.color = isError ? "#b91c1c" : "";
      }
    }

    function qcvizSafeRender() {
      try {
        const vv = qcvizGetViewer();
        if (vv && typeof vv.render === "function") vv.render();
      } catch (err) {
        console.error("[QCViz] viewer.render() failed:", err);
      }
    }

    function qcvizSafeRemoveSurface(surfaceId) {
      if (surfaceId == null) return null;
      try {
        const vv = qcvizGetViewer();
        if (vv && typeof vv.removeShape === "function") {
          vv.removeShape(surfaceId);
        }
      } catch (err) {
        console.warn("[QCViz] removeShape failed:", err);
      }
      return null;
    }

    function qcvizSafeRemoveSurfaceList(ids) {
      if (!Array.isArray(ids)) return [];
      for (const id of ids) qcvizSafeRemoveSurface(id);
      return [];
    }

    function qcvizMakeVolumeDataFromB64(b64, format, label) {
      const text = qcvizDecodeB64Text(b64);
      if (!text) {
        throw new Error(label + " decode returned empty/null text");
      }
      try {
        return new $3Dmol.VolumeData(text, format);
      } catch (err) {
        console.error("[QCViz] VolumeData creation failed for " + label + ":", err);
        throw new Error(label + " VolumeData creation failed: " + (err && err.message ? err.message : err));
      }
    }

    function qcvizGetCachedCube(kind, b64) {
      if (kind === "eden") {
        if (!qcvizCachedEDenVol || qcvizCachedEDenKey !== b64) {
          qcvizCachedEDenVol = qcvizMakeVolumeDataFromB64(b64, "cube", "electron density cube");
          qcvizCachedEDenKey = b64;
        }
        return qcvizCachedEDenVol;
      }
      if (kind === "epot") {
        if (!qcvizCachedEPotVol || qcvizCachedEPotKey !== b64) {
          qcvizCachedEPotVol = qcvizMakeVolumeDataFromB64(b64, "cube", "electrostatic potential cube");
          qcvizCachedEPotKey = b64;
        }
        return qcvizCachedEPotVol;
      }
      throw new Error("Unknown cube cache type: " + kind);
    }

    function qcvizGetOrbitalVolume(idx) {
      const b64 = orbCubes[idx] ? orbCubes[idx].b64 : null;
      if (!b64) throw new Error("Missing orbital cube at index " + idx);
      const cached = qcvizCachedOrbVols.get(idx);
      if (cached && cached.b64 === b64) return cached.vol;
      const vol = qcvizMakeVolumeDataFromB64(b64, "cube", "orbital cube #" + idx);
      qcvizCachedOrbVols.set(idx, { b64, vol });
      return vol;
    }

    function qcvizSyncEspSelectOptions() {
      const sel = document.getElementById("sel-esp");
      if (!sel || !QCVIZ_ESP_PRESETS) return;
      const current = sel.value || "rwb";
      sel.innerHTML = "";
      const orderedKeys = [];
      const seen = new Set();
      for (const key of QCVIZ_ESP_PRESET_ORDER) {
        if (QCVIZ_ESP_PRESETS[key] && !seen.has(key)) { orderedKeys.push(key); seen.add(key); }
      }
      for (const key of Object.keys(QCVIZ_ESP_PRESETS)) {
        if (!seen.has(key)) { orderedKeys.push(key); seen.add(key); }
      }
      for (const key of orderedKeys) {
        const opt = document.createElement("option");
        opt.value = key;
        opt.textContent = QCVIZ_ESP_PRESETS[key].name || key;
        if (key === current) opt.selected = true;
        sel.appendChild(opt);
      }
    }

    function qcvizResolveEspVolscheme(presetName, vmin, vmax) {
      try {
        var p = QCVIZ_ESP_PRESETS[presetName];
        if (p && p.gradient_type === "linear" && p.colors) {
            return new $3Dmol.Gradient.CustomLinear(vmin, vmax, p.colors);
        }
      } catch (err) { console.warn("[QCViz] custom ESP scheme builder failed:", err); }
      return new $3Dmol.Gradient.RWB(vmin, vmax);
    }

    var currentOrb = -1;    // currently displayed orbital index
    var orbSurfaces = [];   // references to orbital isosurfaces
    var espSurface = null;  // reference to ESP surface
    var labelsVisible = false;

    // Cached VolumeData objects to avoid re-parsing on every slider change
    var cachedOrbVolData = null;   // VolumeData for current orbital cube
    var cachedOrbIdx     = -1;     // which orbital index the cache belongs to
    var cachedEDenVol    = null;   // VolumeData for electron density
    var cachedEPotVol    = null;   // VolumeData for electrostatic potential

    // ── Configuration (injected by Python backend) ──
    var xyzB64       = "%%XYZ_B64%%";
    var orbCubes     = %%ORB_JSON%%;
    var presetsData  = %%ESP_PRESETS_DATA%%;
    var wikiQ        = %%WIKI_QUERY%%;
    var chargeVals   = %%CHARGES_VAL_JSON%%;
    var atomLabels   = %%ATOM_LABELS_JSON%%;
    var eDenB64      = "%%EDEN_B64%%";
    var ePotB64      = "%%EPOT_B64%%";
    var eMinOrig     = parseFloat("%%EMIN%%") || -0.05;
    var eMaxOrig     = parseFloat("%%EMAX%%") || 0.05;

    // ★ FIX ESP #1: Validate BOTH density AND potential data exist
    var hasESP = (
        typeof eDenB64 === "string" && eDenB64.length > 10 &&
        typeof ePotB64 === "string" && ePotB64.length > 10
    );

    var S = {
        // Orbital-specific controls
        orbIso: 0.02,
        orbOpa: 0.8,
        // ESP-specific controls
        espIso: 0.002,
        espOpa: 0.8,
        // General state
        esp: false,
        espP: "rwb",
        wire: false,
        focus: false,
        locked: -1,
        labels: false,
        charges: false,
        spinning: false,
        espMin: eMinOrig,
        espMax: eMaxOrig
    };

    var lblHandles = { atoms: [], charges: [] };

    // ── Debounce guard for heavy renders ──
    var _refreshTimer = null;
    function debouncedRefresh(fn, delay) {
        if (_refreshTimer) clearTimeout(_refreshTimer);
        _refreshTimer = setTimeout(function() {
            _refreshTimer = null;
            fn();
        }, delay || 60);
    }

    function ensureESPVolumes() {
        if (!hasESP) return false;
        try {
            if (!espDenVolume) {
                var denStr = D(eDenB64);
                if (!denStr || denStr.length < 10) {
                    hasESP = false;
                    return false;
                }
                espDenVolume = new $3Dmol.VolumeData(denStr, "cube");
            }
            if (!espPotVolume) {
                var potStr = D(ePotB64);
                if (!potStr || potStr.length < 10) {
                    hasESP = false;
                    return false;
                }
                espPotVolume = new $3Dmol.VolumeData(potStr, "cube");
            }
            return true;
        } catch(e) {
            console.error("[QCViz] ESP volume data creation failed:", e);
            hasESP = false;
            return false;
        }
    }

    // ── UTILITIES ──
    function safe3D(fn) { try { fn(); } catch(e) { console.warn("[QCViz]", e); } }

    function D(b) {
        if (!b || typeof b !== "string" || b.length < 2) return "";
        try {
            var s = atob(b.replace(/\\s/g, ''));
            var n = s.length;
            var u = new Uint8Array(n);
            for (var i = 0; i < n; i++) u[i] = s.charCodeAt(i);
            return new TextDecoder("utf-8").decode(u);
        } catch(e) {
            console.error("[QCViz] Base64 decode failed:", e);
            return "";
        }
    }

    function makeGradient(pk, mn, mx) {
        var p = (presetsData && presetsData[pk]) ? presetsData[pk] : null;
        if (!p) {
            return new $3Dmol.Gradient.RWB(mn, mx);
        }
        if (p.gradient_type === "rwb") return new $3Dmol.Gradient.RWB(mn, mx);
        if (p.colors && p.colors.length > 0) {
            return new $3Dmol.Gradient.CustomLinear(mn, mx, p.colors);
        }
        return new $3Dmol.Gradient.RWB(mn, mx);
    }

    function updateStatus(msg) {
        var el = document.getElementById("status-text");
        if (el) el.textContent = msg;
    }

    function widenClipping(factor) {
        try {
            if (v && typeof v.getPerceivedDistance === "function") {
                var slab = v.getPerceivedDistance() * (factor || 3.0);
                v.setSlab(-slab, slab);
            }
        } catch(e) { }
    }

    // ── Isovalue mapping helpers ──
    // Orbital: quadratic map  slider [0..100] → iso [0.001 .. 0.100]
    function sliderToOrbIso(val) {
        return 0.001 + Math.pow(val / 100, 2) * 0.099;
    }
    function orbIsoToSlider(iso) {
        return Math.sqrt((iso - 0.001) / 0.099) * 100;
    }
    // ESP Density: quadratic map  slider [0..100] → iso [0.0001 .. 0.020]
    function sliderToEspIso(val) {
        return 0.0001 + Math.pow(val / 100, 2) * 0.0199;
    }
    function espIsoToSlider(iso) {
        return Math.sqrt((iso - 0.0001) / 0.0199) * 100;
    }

    // ── Viewer Initialization ──
    function initViewer() {
        var c = document.getElementById("v3d");
        if (!c) { console.error("[QCViz] #v3d element not found"); return; }

        if (c.offsetWidth < 10 || c.offsetHeight < 10) {
            console.log("[QCViz] viewer container not ready, retrying in 200ms...");
            setTimeout(initViewer, 200);
            return;
        }

        try {
            v = $3Dmol.createViewer(c, {
                backgroundColor: "white",
                antialias: true,
                disableFog: false
            });
        } catch(e) {
            console.error("[QCViz] Failed to create 3Dmol viewer:", e);
            return;
        }

        if (xyzB64) {
            var xyzStr = D(xyzB64);
            if (xyzStr) {
                molModel = v.addModel(xyzStr, "xyz");
            }
        }

        applyStyle("ballstick");

        v.zoomTo();
        v.zoom(0.85);
        widenClipping(2.5);
        v.render();

        window.addEventListener("resize", function() {
            if (v) {
                try { v.resize(); v.render(); } catch(e) {}
            }
        });

        console.log("[QCViz] Viewer initialized successfully.");
        updateStatus("Ready");

        if (orbCubes && orbCubes.length > 0) {
            showOrb(0);
            var orbIsoSlider = document.getElementById("orb-iso-slider");
            if (orbIsoSlider) {
                orbIsoSlider.value = orbIsoToSlider(S.orbIso);
            }
        }

        if (hasESP) {
            setTimeout(function() {
                ensureESPVolumes();
            }, 500);
        }

        var btnEsp = document.getElementById("btn-esp");
        if (btnEsp) {
            if (!hasESP) {
                btnEsp.disabled = true;
                btnEsp.style.opacity = "0.4";
                btnEsp.title = "ESP data not available";
            } else {
                btnEsp.disabled = false;
                btnEsp.style.opacity = "1";
                btnEsp.title = "Toggle ESP Surface (E)";
            }
        }

        if (wikiQ) {
            fetch("https://en.wikipedia.org/api/rest_v1/page/summary/" + encodeURIComponent(wikiQ))
                .then(function(r) { return r.json(); })
                .then(function(d) {
                    var el = document.getElementById("wC");
                    if (el) el.innerHTML = d.extract || "No abstract available.";
                })
                .catch(function(e) {
                    console.warn("[QCViz] Wiki fetch failed", e);
                    var el = document.getElementById("wC");
                    if (el) el.innerHTML = "Wikipedia fetch failed.";
                });
        } else {
            var el = document.getElementById("wC");
            if (el) el.innerHTML = "No Wikipedia data found.";
        }
    }

    // ── Molecule Display Styles ──
    function applyStyle(mode) {
        if (!v || !molModel) return;
        v.setStyle({}, {});

        switch(mode) {
            case "ballstick":
                v.setStyle({}, {
                    stick: { radius: 0.14, colorscheme: "Jmol" },
                    sphere: { scale: 0.28, colorscheme: "Jmol" }
                });
                break;
            case "stick":
                v.setStyle({}, {
                    stick: { radius: 0.15, colorscheme: "Jmol" }
                });
                break;
            case "sphere":
                v.setStyle({}, {
                    sphere: { scale: 0.6, colorscheme: "Jmol" }
                });
                break;
            case "wireframe":
                v.setStyle({}, {
                    line: { colorscheme: "Jmol" }
                });
                break;
            default:
                v.setStyle({}, {
                    stick: { radius: 0.14, colorscheme: "Jmol" },
                    sphere: { scale: 0.28, colorscheme: "Jmol" }
                });
        }

        if (S.locked >= 0) {
            v.setStyle({serial: S.locked}, {
                sphere: { scale: 0.5, color: "yellow", opacity: 0.6 },
                stick: { radius: 0.12, colorscheme: "Jmol" }
            });
        }
        v.render();
    }
    QV.applyStyle = applyStyle;

    // ── Orbital Rendering ──
    function clearOrbitals() {
        if (!v) return;
        for (var i = 0; i < orbSurfaces.length; i++) {
            try { v.removeShape(orbSurfaces[i]); } catch(e) {}
        }
        orbSurfaces = [];
    }

    function showOrb(idx) {
      currentOrb = idx;
      qcvizOrbSurfaceIds = qcvizSafeRemoveSurfaceList(qcvizOrbSurfaceIds);
      if (idx < 0) {
          qcvizSafeRender();
          return;
      }

      let vol;
      try {
        vol = qcvizGetOrbitalVolume(idx);
      } catch (err) {
        console.error("[QCViz] Orbital preparation failed:", err);
        return;
      }

      try {
        qcvizOrbSurfaceIds.push(
          v.addIsosurface(vol, {
            isoval: S.orbIso,
            color: "blue",
            opacity: S.orbOpa,
            smoothness: 1
          })
        );
        qcvizOrbSurfaceIds.push(
          v.addIsosurface(vol, {
            isoval: -S.orbIso,
            color: "red",
            opacity: S.orbOpa,
            smoothness: 1
          })
        );
        qcvizSafeRender();
        updateStatus("Orbital: " + (orbCubes[idx].label || idx));
      } catch (err) {
        console.error("[QCViz] showOrb failed:", err);
      }
    }
    QV.showOrb = showOrb;

    function refreshOrbSurfaces() {
      try {
        const sel = document.getElementById("sel-orb");
        const idx = sel ? Number(sel.value) : 0;

        if (!Number.isFinite(idx) || idx < 0) {
          qcvizSetDashboardStatus("Invalid orbital selection.", true);
          return;
        }

        showOrb(idx);
      } catch (err) {
        console.error("[QCViz] refreshOrbSurfaces failed:", err);
        qcvizSetDashboardStatus("Orbital refresh failed: " + (err && err.message ? err.message : err), true);
      }
    }

    function refreshESPSurface() {
        if (!v || !hasESP || !S.esp) return;
        clearESP();

        if (!espDenVolume) espDenVolume = new $3Dmol.VolumeData(D(eDenB64), "cube");
        if (!espPotVolume) espPotVolume = new $3Dmol.VolumeData(D(ePotB64), "cube");

        var grad = makeGradient(S.espP, S.espMin, S.espMax);
        var spec = {
            isoval: S.espIso,
            voldata: espPotVolume,
            volscheme: grad,
            opacity: S.espOpa,
            smoothness: 7,
            wireframe: S.wire
        };

        if (S.focus && S.locked >= 0) {
            var fa = v.selectedAtoms({serial: S.locked});
            if (fa && fa.length > 0) { spec.coords = fa; spec.seldist = 4.0; }
        }

        try {
            espSurface = v.addIsosurface(espDenVolume, spec);
        } catch(e) {
            console.error("QCViz: Error refreshing ESP surface:", e);
        }
        v.render();
    }

    function refreshOrbOnly() {
        if (currentOrb >= 0) {
            debouncedRefresh(refreshOrbSurfaces);
        }
    }

    function refreshESPOnly() {
        if (S.esp) {
            debouncedRefresh(refreshESPSurface);
        }
    }

    function refreshOrb() {
        if (currentOrb >= 0) {
            debouncedRefresh(refreshOrbSurfaces);
        } else if (S.esp) {
            debouncedRefresh(refreshESPSurface);
        }
    }
    QV.refreshOrb = refreshOrb;

    // ── ESP Rendering ──
    function clearESP() {
        if (!v || !espSurface) return;
        try { v.removeShape(espSurface); } catch(e) {}
        espSurface = null;
    }

    function renderESP() {
      qcvizEspSurfaceId = qcvizSafeRemoveSurface(qcvizEspSurfaceId);
      if (!S.esp) {
          var cb = document.getElementById("cb-grad");
          if(cb) cb.style.display = "none";
          qcvizSafeRender();
          updateStatus("Ready");
          return;
      }

      if (!hasESP) {
        qcvizSetDashboardStatus("ESP data unavailable.", false);
        qcvizSafeRender();
        return;
      }

      let denVol, potVol;
      try {
        denVol = qcvizGetCachedCube("eden", eDenB64);
        potVol = qcvizGetCachedCube("epot", ePotB64);
      } catch (err) {
        console.error("[QCViz] ESP volume preparation failed:", err);
        qcvizSetDashboardStatus("ESP decode failed", true);
        return;
      }

      try {
        const presetName = S.espP || "rwb";
        const iso = S.espIso || 0.002;
        const opacity = S.espOpa || 0.8;
        const vmin = S.espMin;
        const vmax = S.espMax;

        const volscheme = qcvizResolveEspVolscheme(presetName, vmin, vmax);

        qcvizEspSurfaceId = v.addIsosurface(denVol, {
          isoval: iso,
          opacity: opacity,
          smoothness: 1,
          voldata: potVol,
          volscheme: volscheme
        });

        var p = presetsData[presetName] || presetsData["rwb"];
        var cols = (p.gradient_type === "rwb") ? ["#3b82f6", "#ffffff", "#ef4444"] : p.colors;
        var cb = document.getElementById("cb-grad");
        if(cb) {
            cb.style.background = "linear-gradient(to right, " + cols.join(",") + ")";
            cb.style.display = "block";
        }

        qcvizSafeRender();
        updateStatus("ESP Surface");
      } catch (err) {
        console.error("[QCViz] renderESP failed:", err);
        qcvizSetDashboardStatus("ESP render failed", true);
      }
    }
    QV.renderESP = renderESP;

    // ── Labels ──
    function toggleLabels() {
        if (!v) return;
        S.labels = !S.labels;
        lblHandles.atoms.forEach(function(l) { safe3D(function(){ v.removeLabel(l); }); });
        lblHandles.atoms = [];

        if (S.labels && atomLabels && atomLabels.length > 0) {
            safe3D(function() {
                var allAtoms = v.selectedAtoms({});
                for (var i = 0; i < allAtoms.length && i < atomLabels.length; i++) {
                    if (atomLabels[i]) {
                        var l = v.addLabel(atomLabels[i], {
                            position: allAtoms[i],
                            fontSize: 11,
                            fontColor: "#1a1a2e",
                            backgroundColor: "rgba(255,255,255,0.85)",
                            borderColor: "#e2e6ec",
                            borderThickness: 1,
                            backgroundOpacity: 0.85,
                            showBackground: true,
                            alignment: "center"
                        });
                        lblHandles.atoms.push(l);
                    }
                }
            });
        }
        var btn = document.getElementById("btn-labels");
        if (btn) btn.classList.toggle("active", S.labels);
        v.render();
    }
    QV.toggleLabels = toggleLabels;

    function toggleCharges() {
        if (!v) return;
        S.charges = !S.charges;
        lblHandles.charges.forEach(function(l) { safe3D(function(){ v.removeLabel(l); }); });
        lblHandles.charges = [];

        if (S.charges && chargeVals && chargeVals.length > 0) {
            safe3D(function() {
                var allAtoms = v.selectedAtoms({});
                for (var i = 0; i < allAtoms.length && i < chargeVals.length; i++) {
                    if (chargeVals[i] !== undefined && chargeVals[i] !== null) {
                        var val = chargeVals[i];
                        var cStr = (val >= 0 ? "+" : "") + val.toFixed(3);
                        var cCol = val >= 0 ? "#dc2626" : "#2563eb";
                        var l = v.addLabel(cStr, {
                            position: allAtoms[i],
                            fontSize: 11,
                            fontColor: cCol,
                            backgroundColor: "rgba(255,255,255,0.9)",
                            backgroundOpacity: 0.9,
                            borderRadius: 4,
                            padding: 2,
                            yOffset: -1.5
                        });
                        lblHandles.charges.push(l);
                    }
                }
            });
        }
        var btn = document.getElementById("btn-charges");
        if (btn) btn.classList.toggle("active", S.charges);
        v.render();
    }
    QV.toggleCharges = toggleCharges;

    QV.lockAtom = function(i) {
        S.locked = (S.locked === i) ? -1 : i;
        var activeStyleBtn = document.querySelector(".toolbar button.active[data-style]");
        applyStyle(activeStyleBtn ? activeStyleBtn.getAttribute("data-style") : "ballstick");

        var rows = document.querySelectorAll(".charge-row");
        for (var j = 0; j < rows.length; j++) {
            if (parseInt(rows[j].getAttribute("data-idx")) === S.locked) {
                rows[j].classList.add("active");
            } else {
                rows[j].classList.remove("active");
            }
        }

        if (S.esp && S.focus) renderESP();
    };

    // ── Screenshot ──
    function captureScreenshot() {
        if (!v) return;
        try {
            var png = v.pngURI();
            var link = document.createElement("a");
            link.download = "qcviz_capture.png";
            link.href = png;
            link.click();
        } catch(e) {
            console.error("[QCViz] Screenshot failed:", e);
        }
    }
    QV.captureScreenshot = captureScreenshot;

    // ── Reset View ──
    function resetView() {
        if (!v) return;
        clearOrbitals();
        clearESP();
        currentOrb = -1;
        cachedOrbVolData = null;
        cachedOrbIdx = -1;
        S.esp = false;

        var espBtn = document.getElementById("btn-esp");
        if (espBtn) espBtn.classList.remove("active");

        S.labels = false;
        lblHandles.atoms.forEach(function(l) { safe3D(function(){ v.removeLabel(l); }); });
        lblHandles.atoms = [];
        var btnLbl = document.getElementById("btn-labels");
        if (btnLbl) btnLbl.classList.remove("active");

        S.charges = false;
        lblHandles.charges.forEach(function(l) { safe3D(function(){ v.removeLabel(l); }); });
        lblHandles.charges = [];
        var btnChg = document.getElementById("btn-charges");
        if (btnChg) btnChg.classList.remove("active");

        S.locked = -1;
        var rows = document.querySelectorAll(".charge-row");
        for (var j = 0; j < rows.length; j++) rows[j].classList.remove("active");

        // Reset sliders
        S.orbIso = 0.02;  S.orbOpa = 0.8;
        S.espIso = 0.002;  S.espOpa = 0.8;

        var orbIsoSl = document.getElementById("orb-iso-slider");
        var orbIsoVl = document.getElementById("orb-iso-val");
        if (orbIsoSl) orbIsoSl.value = orbIsoToSlider(S.orbIso);
        if (orbIsoVl) orbIsoVl.textContent = S.orbIso.toFixed(3);

        var orbOpaSl = document.getElementById("orb-opa-slider");
        var orbOpaVl = document.getElementById("orb-opa-val");
        if (orbOpaSl) orbOpaSl.value = S.orbOpa;
        if (orbOpaVl) orbOpaVl.textContent = S.orbOpa.toFixed(2);

        var espIsoSl = document.getElementById("esp-iso-slider");
        var espIsoVl = document.getElementById("esp-iso-val");
        if (espIsoSl) espIsoSl.value = espIsoToSlider(S.espIso);
        if (espIsoVl) espIsoVl.textContent = S.espIso.toFixed(4);

        var espOpaSl = document.getElementById("esp-opa-slider");
        var espOpaVl = document.getElementById("esp-opa-val");
        if (espOpaSl) espOpaSl.value = S.espOpa;
        if (espOpaVl) espOpaVl.textContent = S.espOpa.toFixed(2);

        applyStyle("ballstick");
        v.zoomTo();
        v.zoom(0.85);
        widenClipping(2.5);
        v.render();
        updateOrbListUI(-1);
        updateStatus("Ready");
    }
    QV.resetView = resetView;

    // ── Orbital List UI ──
    function updateOrbListUI(activeIdx) {
        var items = document.querySelectorAll(".orb-list li");
        for (var i = 0; i < items.length; i++) {
            if (parseInt(items[i].getAttribute("data-idx")) === activeIdx) {
                items[i].classList.add("active");
            } else {
                items[i].classList.remove("active");
            }
        }
    }

    // ── Boot Sequence ──
    function boot() {
        // Orbital Sliders
        var orbIsoSlider = document.getElementById("orb-iso-slider");
        var orbIsoVal    = document.getElementById("orb-iso-val");
        if (orbIsoSlider) {
            orbIsoSlider.addEventListener("input", function() {
                S.orbIso = sliderToOrbIso(parseFloat(this.value));
                if (orbIsoVal) orbIsoVal.textContent = S.orbIso.toFixed(3);
            });
            orbIsoSlider.addEventListener("change", function() {
                S.orbIso = sliderToOrbIso(parseFloat(this.value));
                if (orbIsoVal) orbIsoVal.textContent = S.orbIso.toFixed(3);
                refreshOrbOnly();
            });
        }

        var orbOpaSlider = document.getElementById("orb-opa-slider");
        var orbOpaVal    = document.getElementById("orb-opa-val");
        if (orbOpaSlider) {
            orbOpaSlider.addEventListener("input", function() {
                S.orbOpa = parseFloat(this.value);
                if (orbOpaVal) orbOpaVal.textContent = S.orbOpa.toFixed(2);
            });
            orbOpaSlider.addEventListener("change", function() {
                S.orbOpa = parseFloat(this.value);
                if (orbOpaVal) orbOpaVal.textContent = S.orbOpa.toFixed(2);
                refreshOrbOnly();
            });
        }

        // ESP Sliders
        var espIsoSlider = document.getElementById("esp-iso-slider");
        var espIsoVal    = document.getElementById("esp-iso-val");
        if (espIsoSlider) {
            espIsoSlider.addEventListener("input", function() {
                S.espIso = sliderToEspIso(parseFloat(this.value));
                if (espIsoVal) espIsoVal.textContent = S.espIso.toFixed(4);
            });
            espIsoSlider.addEventListener("change", function() {
                S.espIso = sliderToEspIso(parseFloat(this.value));
                if (espIsoVal) espIsoVal.textContent = S.espIso.toFixed(4);
                refreshESPOnly();
            });
        }

        var espOpaSlider = document.getElementById("esp-opa-slider");
        var espOpaVal    = document.getElementById("esp-opa-val");
        if (espOpaSlider) {
            espOpaSlider.addEventListener("input", function() {
                S.espOpa = parseFloat(this.value);
                if (espOpaVal) espOpaVal.textContent = S.espOpa.toFixed(2);
            });
            espOpaSlider.addEventListener("change", function() {
                S.espOpa = parseFloat(this.value);
                if (espOpaVal) espOpaVal.textContent = S.espOpa.toFixed(2);
                refreshESPOnly();
            });
        }

        // Style buttons
        document.querySelectorAll("[data-style]").forEach(function(btn) {
            btn.addEventListener("click", function() {
                document.querySelectorAll("[data-style]").forEach(function(b) { b.classList.remove("active"); });
                this.classList.add("active");
                applyStyle(this.getAttribute("data-style"));
            });
        });

        // Feature toggles
        var btnLabels = document.getElementById("btn-labels");
        if (btnLabels) btnLabels.addEventListener("click", toggleLabels);

        var btnCharges = document.getElementById("btn-charges");
        if (btnCharges) btnCharges.addEventListener("click", toggleCharges);

        var btnEsp = document.getElementById("btn-esp");
        if (btnEsp) {
            btnEsp.addEventListener("click", function() {
                if (!hasESP) {
                    updateStatus("ESP data not available");
                    return;
                }
                S.esp = !S.esp;
                this.classList.toggle("active", S.esp);
                renderESP();
            });
        }

        var selEsp = document.getElementById("sel-esp");
        if (selEsp) {
            selEsp.addEventListener("change", function(e) {
                S.espP = e.target.value;
                if (S.esp) renderESP();
            });
        }

        var btnWire = document.getElementById("btn-wire");
        if (btnWire) {
            btnWire.addEventListener("click", function() {
                S.wire = !S.wire;
                this.classList.toggle("active", S.wire);
                if (S.esp) renderESP();
            });
        }

        var btnFocus = document.getElementById("btn-focus");
        if (btnFocus) {
            btnFocus.addEventListener("click", function() {
                S.focus = !S.focus;
                this.classList.toggle("active", S.focus);
                if (S.esp) renderESP();
            });
        }

        var btnScreenshot = document.getElementById("btn-screenshot");
        if (btnScreenshot) btnScreenshot.addEventListener("click", QV.captureScreenshot);

        var btnReset = document.getElementById("btn-reset");
        if (btnReset) btnReset.addEventListener("click", QV.resetView);

        if (typeof requestAnimationFrame === "function") {
            requestAnimationFrame(function() {
                setTimeout(initViewer, 200);
            });
        } else {
            setTimeout(initViewer, 300);
        }

        document.addEventListener("keydown", function(e) {
            if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
            var key = e.key.toLowerCase();
            if (e.key === "Escape") { resetView(); }
            if (e.key >= "1" && e.key <= "9") {
                var idx = parseInt(e.key) - 1;
                if (idx < orbCubes.length) showOrb(idx);
            }
            if (key === "e" && btnEsp) btnEsp.click();
            if (key === "r") resetView();
            if (key === "l") toggleLabels();
            if (key === "c") toggleCharges();
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", boot);
    } else {
        boot();
    }

})();
</script>
"""

_DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
        <title>QCViz Pro | %%MOL_NAME%%</title>
    <!-- Fonts -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">

    <!-- Icons -->
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@latest/tabler-icons.min.css">
    <script src="https://3Dmol.org/build/3Dmol-min.js"></script>
    %%CSS%%
  </head>
  <body>
    <div class="layout-container">
      <div class="main-area">
        <!-- Top toolbar bar -->
        <div class="top-bar">
          <div class="logo-area">
            <div class="logo-icon">Q</div>
            QCViz-MCP <span class="badge">Enterprise v3.5</span>
          </div>
          <div class="toolbar">
            <button data-style="ballstick" class="active">
              Ball &amp; Stick
            </button>
            <button data-style="stick">Stick</button>
            <button data-style="sphere">Sphere</button>
            <button data-style="wireframe" id="btn-wire">Wire</button>
            <button data-style="focus" id="btn-focus">Focus</button>
            <button id="btn-labels">Labels</button>
            <button id="btn-charges">Charges</button>
            <button id="btn-esp">ESP</button>
            <button id="btn-screenshot">📷 Capture</button>
            <button id="btn-reset">Reset</button>
          </div>
        </div>

        <!-- Content: sidebar + viewer -->
        <div class="content-row">
          <div class="sidebar">
            <div class="sidebar-header">
              <h3>Orbital Explorer</h3>
            </div>
            <div class="sidebar-scroll">
              <!-- Molecule Info -->
              <div class="panel">
                <div class="panel-title">
                  <span class="icon">📋</span> Molecule Info
                </div>
                <div class="info-grid">
                  <span class="info-label">Formula</span
                  ><span class="info-value">%%FORMULA%%</span>
                  <span class="info-label">Method</span
                  ><span class="info-value">%%METHOD%%</span>
                  <span class="info-label">Basis</span
                  ><span class="info-value">%%BASIS%%</span>
                  <span class="info-label">Energy</span
                  ><span class="info-value">%%ENERGY%% Ha</span>
                </div>
                <div class="wiki-box" id="wC">Loading Wikipedia...</div>
              </div>

              <!-- ============================================================
                             🌈 ESP Map Panel — with DEDICATED ESP sliders
                             ============================================================ -->
              <div class="panel">
                <div class="panel-title">
                  <span class="icon">🌈</span> ESP Map
                </div>
                <div class="slider-group">
                  <select
                    id="sel-esp"
                    style="width: 100%; padding: 4px; margin-bottom: 8px; border-radius: 4px; border: 1px solid #e2e6ec; outline: none;"
                  >
                    %%ESP_OPTIONS%%
                  </select>
                </div>
                <!-- ESP Isovalue Slider -->
                <div class="slider-group">
                  <label
                    >ESP Density Isovalue
                    <span class="val" id="esp-iso-val">0.0020</span></label
                  >
                  <input
                    type="range"
                    id="esp-iso-slider"
                    min="0"
                    max="100"
                    value="10"
                  />
                </div>
                <!-- ESP Opacity Slider -->
                <div class="slider-group">
                  <label
                    >ESP Opacity
                    <span class="val" id="esp-opa-val">0.80</span></label
                  >
                  <input
                    type="range"
                    id="esp-opa-slider"
                    min="0.1"
                    max="1.0"
                    step="0.05"
                    value="0.80"
                  />
                </div>
                <div
                  class="esp-colorbar"
                  id="cb-grad"
                  style="display:none;"
                ></div>
                <div class="esp-labels">
                  <span id="cb-min">%%EMIN%%</span><span>0</span
                  ><span id="cb-max">%%EMAX%%</span>
                </div>
              </div>

              <!-- ============================================================
                             🔬 Orbitals Panel — with DEDICATED Orbital sliders
                             ============================================================ -->
              <div class="panel">
                <div class="panel-title">
                  <span class="icon">🔬</span> Orbitals
                </div>
                <!-- Orbital Isovalue Slider -->
                <div class="slider-group">
                  <label
                    >Orbital Isovalue
                    <span class="val" id="orb-iso-val">0.020</span></label
                  >
                  <input
                    type="range"
                    id="orb-iso-slider"
                    min="0"
                    max="100"
                    value="30"
                  />
                </div>
                <!-- Orbital Opacity Slider -->
                <div class="slider-group">
                  <label
                    >Orbital Opacity
                    <span class="val" id="orb-opa-val">0.80</span></label
                  >
                  <input
                    type="range"
                    id="orb-opa-slider"
                    min="0.1"
                    max="1.0"
                    step="0.05"
                    value="0.80"
                  />
                </div>
                <ul class="orb-list">
                  %%ORB_LIST%%
                </ul>
              </div>

              <!-- Charges panel -->
              <div class="panel" style="margin-bottom: 0;">
                <div class="panel-title">
                  <span class="icon">⚡</span> IAO Charges
                </div>
                <div style="font-size:10px;color:#9ca3af;margin-bottom:8px;">
                  Click row to lock focus on atom
                </div>
                <div class="charge-list">%%CHARGE_BARS%%</div>
              </div>
            </div>
          </div>

          <!-- 3D Viewer -->
          <div class="viewer-area">
            <div class="viewer-container">
              <div id="v3d"></div>
              <div class="viewer-overlay">
                <!-- Optional floating controls -->
              </div>
            </div>
            <div class="status-bar">
              <div class="status-item">
                <span class="status-dot"></span>
                <span id="status-text">Initializing...</span>
              </div>
              <div class="status-item">
                %%MOL_NAME%% | %%METHOD%%/%%BASIS%% | %%ENERGY%% Ha
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    %%JS%%
  </body>
</html>
"""

_SIMPLE_MOL = (
    '<!DOCTYPE html><html><head>'
    '<script src="https://3Dmol.org/build/3Dmol-min.js"></script>'
    '</head><body><div id="v" style="width:100vw;height:100vh"></div>'
    "<script>"
    'var v=$3Dmol.createViewer(document.getElementById("v"),'
    '{backgroundColor:"white"});'
    'v.addModel(atob("%%XYZ_B64%%"),"xyz");'
    "v.setStyle({},{stick:{}});v.zoomTo();v.render();"
    "</script></body></html>"
)

_SIMPLE_ORB = r"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>QCViz Orbital</title>
  <script src="https://3Dmol.org/build/3Dmol-min.js"></script>
</head>
<body style="margin:0;padding:0;background:#fff;">
  <div id="v" style="width:100vw;height:100vh"></div>
  <script>
    function qcvizNormalizeB64(s) {
      s = String(s || "").trim().replace(/\s+/g, "").replace(/-/g, "+").replace(/_/g, "/");
      const pad = s.length % 4;
      if (pad) s += "=".repeat(4 - pad);
      return s;
    }

    function qcvizDecodeB64Text(b64) {
      const normalized = qcvizNormalizeB64(b64);
      const raw = atob(normalized);
      if (typeof TextDecoder === "undefined") return raw;
      const bytes = new Uint8Array(raw.length);
      for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
      return new TextDecoder("utf-8", { fatal: false }).decode(bytes);
    }

    try {
      var v = $3Dmol.createViewer(document.getElementById("v"), { backgroundColor: "white" });
      v.addModel(qcvizDecodeB64Text("%%XYZ_B64%%"), "xyz");

      var cubeText = qcvizDecodeB64Text("%%CUBE_B64%%");
      var vol = new $3Dmol.VolumeData(cubeText, "cube");

      v.addIsosurface(vol, {
        isoval: 0.02,
        color: "blue",
        opacity: 0.85,
        smoothness: 1
      });

      v.addIsosurface(vol, {
        isoval: -0.02,
        color: "red",
        opacity: 0.85,
        smoothness: 1
      });

      v.zoomTo();
      v.render();
    } catch (err) {
      console.error("Orbital render failed:", err);
      document.body.innerHTML =
        '<div style="padding:16px;font:14px/1.5 monospace;color:#b91c1c;background:#fff1f2;">' +
        '<strong>Orbital render failed</strong><br>' +
        String(err && err.message ? err.message : err) +
        '</div>';
    }
  </script>
</body>
</html>
"""

```

---

## 파일: `src/qcviz_mcp/backends/ase_backend.py` (93줄, 3022bytes)

```python
"""ASE 기반 구조 조작 및 포맷 변환 백엔드 구현."""

from __future__ import annotations

import logging
from pathlib import Path

from qcviz_mcp.backends.base import AtomsData, StructureBackend
from qcviz_mcp.backends.registry import registry

try:
    import ase.io

    _HAS_ASE = True
except ImportError:
    _HAS_ASE = False

logger = logging.getLogger(__name__)


class ASEBackend(StructureBackend):
    """ASE 기반 분자 구조 조작 백엔드.

    Note: ASE는 LGPL 라이선스를 가지며, 여기서는 동적 import를 통해 사용합니다.
    """

    @classmethod
    def name(cls) -> str:
        return "ase"

    @classmethod
    def is_available(cls) -> bool:
        return _HAS_ASE

    def read_structure(self, path: str | Path, format: str | None = None) -> AtomsData:
        if not _HAS_ASE:
            raise ImportError("ASE가 설치되지 않았습니다.")

        path_str = str(path)
        logger.info("구조 읽기 시도: %s", path_str)
        try:
            atoms = ase.io.read(path_str, format=format)

            return AtomsData(
                symbols=atoms.get_chemical_symbols(),
                positions=atoms.get_positions(),
                cell=atoms.get_cell().array if atoms.cell else None,  # 타입 문제 회피
                pbc=atoms.get_pbc().tolist() if hasattr(atoms, "get_pbc") else None,
            )
        except Exception as e:
            logger.error("구조 읽기 실패: %s", str(e))
            raise ValueError(f"지원하지 않거나 잘못된 형식: {e}")

    def write_structure(
        self, atoms_data: AtomsData, path: str | Path, format: str | None = None
    ) -> Path:
        if not _HAS_ASE:
            raise ImportError("ASE가 설치되지 않았습니다.")

        from ase import Atoms

        path_obj = Path(path)
        try:
            atoms = Atoms(
                symbols=atoms_data.symbols,
                positions=atoms_data.positions,
                cell=atoms_data.cell,
                pbc=atoms_data.pbc,
            )
            ase.io.write(str(path_obj), atoms, format=format)
            return path_obj
        except Exception as e:
            logger.error("구조 쓰기 실패: %s", str(e))
            raise ValueError(f"파일 저장 실패: {e}")

    def convert_format(self, input_path: str | Path, output_path: str | Path) -> Path:
        if not _HAS_ASE:
            raise ImportError("ASE가 설치되지 않았습니다.")

        in_str = str(input_path)
        out_str = str(output_path)

        logger.info("포맷 변환: %s -> %s", in_str, out_str)
        try:
            atoms = ase.io.read(in_str)
            ase.io.write(out_str, atoms)
            return Path(out_str)
        except Exception as e:
            logger.error("포맷 변환 실패: %s", str(e))
            raise ValueError(f"포맷 변환 실패: {e}")


registry.register(ASEBackend)

```

---

## 파일: `src/qcviz_mcp/backends/cclib_backend.py` (121줄, 3731bytes)

```python
"""cclib 기반 양자화학 출력 파일 파싱 백엔드 구현."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from qcviz_mcp.backends.base import ParsedResult, ParserBackend
from qcviz_mcp.backends.registry import registry

try:
    import cclib

    _HAS_CCLIB = True
except ImportError:
    _HAS_CCLIB = False

logger = logging.getLogger(__name__)


class CclibBackend(ParserBackend):
    """cclib 기반 양자화학 출력 파일 파서.

    지원하는 프로그램: ORCA, Gaussian, GAMESS, NWChem, Psi4, Q-Chem 등 16개.
    """

    @classmethod
    def name(cls) -> str:
        return "cclib"

    @classmethod
    def is_available(cls) -> bool:
        return _HAS_CCLIB

    def parse_file(self, path: str | Path) -> ParsedResult:
        if not _HAS_CCLIB:
            raise ImportError("cclib가 설치되지 않았습니다.")

        path_str = str(path)
        logger.info("파일 파싱 시도: %s", path_str)

        try:
            # cclib의 ccopen을 통해 파일 파싱
            parser = cclib.io.ccopen(path_str)
            if parser is None:
                raise ValueError(f"cclib가 지원하지 않는 파일 형식입니다: {path_str}")

            data = parser.parse()
            logger.info(
                "파싱 성공: %s", getattr(data, "metadata", {}).get("package", "Unknown")
            )

            # 에너지 (scfenergies의 마지막 값, eV 단위이므로 Hartree로 변환 필요)
            # 1 eV = 0.0367493 Hartree
            energy_hartree = None
            if hasattr(data, "scfenergies") and len(data.scfenergies) > 0:
                energy_ev = data.scfenergies[-1]
                energy_hartree = float(energy_ev) * 0.036749322

            # 좌표 (atomcoords의 마지막 구조 사용)
            coordinates = None
            if hasattr(data, "atomcoords") and len(data.atomcoords) > 0:
                coordinates = np.array(data.atomcoords[-1])

            # 원자 번호
            atomic_numbers = None
            if hasattr(data, "atomnos"):
                atomic_numbers = list(data.atomnos)

            # MO 에너지
            mo_energies = None
            if hasattr(data, "moenergies"):
                mo_energies = [np.array(e) for e in data.moenergies]

            # MO 계수
            mo_coefficients = None
            if hasattr(data, "mocoeffs"):
                mo_coefficients = [np.array(c) for c in data.mocoeffs]

            program = getattr(data, "metadata", {}).get("package", "Unknown")

            return ParsedResult(
                energy_hartree=energy_hartree,
                coordinates=coordinates,
                atomic_numbers=atomic_numbers,
                mo_energies=mo_energies,
                mo_coefficients=mo_coefficients,
                program=program,
            )

        except Exception as e:
            logger.error("파일 파싱 중 에러 발생: %s", str(e))
            raise ValueError(f"파싱 실패: {e}")

    @classmethod
    def supported_programs(cls) -> list[str]:
        # cclib가 공식 지원하는 프로그램들 중 대표적인 것들.
        return [
            "ADF",
            "DALTON",
            "Firefly",
            "GAMESS",
            "GAMESS-UK",
            "Gaussian",
            "Jaguar",
            "Molcas",
            "Molpro",
            "MOPAC",
            "NBO",
            "NWChem",
            "ORCA",
            "Psi3",
            "Psi4",
            "Q-Chem",
            "Turbomole",
        ]


registry.register(CclibBackend)

```

---

## 파일: `src/qcviz_mcp/analysis/__init__.py` (14줄, 504bytes)

```python
"""QCViz-MCP Analysis Module — fragment detection, charge transfer, sanitization."""

from qcviz_mcp.analysis.sanitize import sanitize_xyz, extract_atom_list, atoms_to_xyz_string
from qcviz_mcp.analysis.fragment_detector import detect_fragments, fragment_summary
from qcviz_mcp.analysis.charge_transfer import compute_fragment_charges

__all__ = [
    "sanitize_xyz",
    "extract_atom_list",
    "atoms_to_xyz_string",
    "detect_fragments",
    "fragment_summary",
    "compute_fragment_charges",
]

```

---

## 파일: `src/qcviz_mcp/analysis/charge_transfer.py` (103줄, 3691bytes)

```python
"""IAO 기반 프래그먼트 간 전하 이전 분석.

개별 원자의 IAO 부분 전하를 프래그먼트별로 합산하여
프래그먼트 순전하(net charge)와 프래그먼트 간 전하 이전량(ΔQ)을 계산한다.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np


def compute_fragment_charges(
    iao_charges: np.ndarray,
    fragments: List[List[int]],
    atom_symbols: List[str],
) -> Dict:
    """IAO 부분 전하를 프래그먼트별로 합산.

    Parameters
    ----------
    iao_charges : np.ndarray
        원자별 IAO 부분 전하 (길이 = 원자 수).
    fragments : list of list of int
        프래그먼트별 원자 인덱스.
    atom_symbols : list of str
        원자 기호 리스트.

    Returns
    -------
    dict
        프래그먼트별 전하, 전하 이전 정보를 포함하는 분석 결과.
    """
    from collections import Counter

    frag_data = []
    for i, indices in enumerate(fragments):
        syms = [atom_symbols[idx] for idx in indices]
        counts = Counter(syms)
        formula = "".join(
            "%s%s" % (e, str(counts[e]) if counts[e] > 1 else "")
            for e in sorted(counts.keys())
        )
        frag_charge = float(np.sum(iao_charges[indices]))
        atom_charges = {idx: float(iao_charges[idx]) for idx in indices}
        frag_data.append({
            "fragment_id": i,
            "formula": formula,
            "net_charge": frag_charge,
            "atom_charges": atom_charges,
            "n_atoms": len(indices),
        })

    # 프래그먼트 간 전하 이전 분석
    transfers = []
    if len(frag_data) >= 2:
        for i in range(len(frag_data)):
            for j in range(i + 1, len(frag_data)):
                qi = frag_data[i]["net_charge"]
                qj = frag_data[j]["net_charge"]
                # 양전하 프래그먼트 → 음전하 프래그먼트로의 전하 이전량
                delta_q = abs(qi - qj) / 2.0
                donor = i if qi > qj else j
                acceptor = j if qi > qj else i
                transfers.append({
                    "donor_fragment": donor,
                    "acceptor_fragment": acceptor,
                    "donor_formula": frag_data[donor]["formula"],
                    "acceptor_formula": frag_data[acceptor]["formula"],
                    "delta_q": delta_q,
                    "donor_charge": frag_data[donor]["net_charge"],
                    "acceptor_charge": frag_data[acceptor]["net_charge"],
                })

    # 상호작용 강도 추정 (정전기 근사, 조 표면 간)
    binding_info = None
    if len(frag_data) >= 2 and len(transfers) > 0:
        t = transfers[0]  # 가장 큰 두 프래그먼트 간
        # 프래그먼트 중심 간 거리 추정은 호출자가 제공
        binding_info = {
            "dominant_transfer": t,
            "interpretation": _interpret_transfer(t["delta_q"]),
        }

    return {
        "fragments": frag_data,
        "transfers": transfers,
        "binding_info": binding_info,
        "total_charge_check": float(np.sum(iao_charges)),
    }


def _interpret_transfer(delta_q: float) -> str:
    """전하 이전량에 따른 결합 특성 해석."""
    if delta_q < 0.05:
        return "Minimal charge_transfer — predominantly dispersive/vdW interaction"
    elif delta_q < 0.15:
        return "Moderate charge transfer — mixed electrostatic/CT interaction"
    elif delta_q < 0.40:
        return "Significant charge transfer — strong donor-acceptor character"
    else:
        return "Large charge transfer — ionic or dative bonding character"

```

---

## 파일: `src/qcviz_mcp/analysis/fragment_detector.py` (113줄, 3889bytes)

```python
"""거리 기반 분자 프래그먼트 자동 감지.

공유결합 반지름 + 허용 오차(1.3배)로 원자 연결성 그래프를 구축하고,
연결 성분(connected components)을 프래그먼트로 식별한다.
"""

from __future__ import annotations

import math
from typing import List, Tuple, Dict

# 공유결합 반지름 (Angstrom), Cordero et al. 2008
_COVALENT_RADII = {
    "H": 0.31, "He": 0.28, "Li": 1.28, "Be": 0.96, "B": 0.84,
    "C": 0.76, "N": 0.71, "O": 0.66, "F": 0.57, "Ne": 0.58,
    "Na": 1.66, "Mg": 1.41, "Al": 1.21, "Si": 1.11, "P": 1.07,
    "S": 1.05, "Cl": 1.02, "Ar": 1.06, "K": 2.03, "Ca": 1.76,
    "Sc": 1.70, "Ti": 1.60, "V": 1.53, "Cr": 1.39, "Mn": 1.39,
    "Fe": 1.32, "Co": 1.26, "Ni": 1.24, "Cu": 1.32, "Zn": 1.22,
    "Ga": 1.22, "Ge": 1.20, "As": 1.19, "Se": 1.20, "Br": 1.20,
    "Kr": 1.16, "Rb": 2.20, "Sr": 1.95, "Y": 1.90, "Zr": 1.75,
    "Nb": 1.64, "Mo": 1.54, "Ru": 1.46, "Rh": 1.42, "Pd": 1.39,
    "Ag": 1.45, "Cd": 1.44, "In": 1.42, "Sn": 1.39, "Sb": 1.39,
    "Te": 1.38, "I": 1.39, "Xe": 1.40,
}

_DEFAULT_RADIUS = 1.50  # 알 수 없는 원소 기본값
_BOND_TOLERANCE = 1.3   # 결합 판정 허용 배수


def detect_fragments(
    atoms: List[Tuple[str, float, float, float]],
    tolerance: float = _BOND_TOLERANCE,
) -> List[List[int]]:
    """원자 리스트에서 프래그먼트(연결 성분)를 감지.

    Parameters
    ----------
    atoms : list of (symbol, x, y, z)
    tolerance : float
        공유결합 반지름 합에 곱하는 허용 배수.

    Returns
    -------
    list of list of int
        각 프래그먼트의 원자 인덱스 리스트. 크기 순 정렬 (큰 것 먼저).
    """
    n = len(atoms)
    if n == 0:
        return []

    # 인접 리스트 구축
    adj = [[] for _ in range(n)]
    for i in range(n):
        si, xi, yi, zi = atoms[i]
        ri = _COVALENT_RADII.get(si, _DEFAULT_RADIUS)
        for j in range(i + 1, n):
            sj, xj, yj, zj = atoms[j]
            rj = _COVALENT_RADII.get(sj, _DEFAULT_RADIUS)
            dist = math.sqrt((xi - xj)**2 + (yi - yj)**2 + (zi - zj)**2)
            if dist <= (ri + rj) * tolerance:
                adj[i].append(j)
                adj[j].append(i)

    # BFS로 연결 성분 탐색
    visited = [False] * n
    fragments = []
    for start in range(n):
        if visited[start]:
            continue
        component = []
        queue = [start]
        visited[start] = True
        while queue:
            node = queue.pop(0)
            component.append(node)
            for neighbor in adj[node]:
                if not visited[neighbor]:
                    visited[neighbor] = True
                    queue.append(neighbor)
        fragments.append(sorted(component))

    # 크기 순 정렬 (큰 프래그먼트 먼저)
    fragments.sort(key=lambda f: -len(f))
    return fragments


def fragment_summary(
    atoms: List[Tuple[str, float, float, float]],
    fragments: List[List[int]],
) -> List[Dict]:
    """각 프래그먼트의 요약 정보 생성."""
    from collections import Counter
    results = []
    for i, frag_indices in enumerate(fragments):
        syms = [atoms[idx][0] for idx in frag_indices]
        counts = Counter(syms)
        formula = "".join(
            "%s%s" % (e, str(counts[e]) if counts[e] > 1 else "")
            for e in sorted(counts.keys())
        )
        # 프래그먼트 중심
        cx = sum(atoms[idx][1] for idx in frag_indices) / len(frag_indices)
        cy = sum(atoms[idx][2] for idx in frag_indices) / len(frag_indices)
        cz = sum(atoms[idx][3] for idx in frag_indices) / len(frag_indices)
        results.append({
            "fragment_id": i,
            "atom_indices": frag_indices,
            "n_atoms": len(frag_indices),
            "formula": formula,
            "center": (cx, cy, cz),
        })
    return results

```

---

## 파일: `src/qcviz_mcp/analysis/sanitize.py` (160줄, 5372bytes)

```python
"""범용 원자 좌표 문자열 정규화 모듈.

모든 도구 경로(SCF, ESP, IBO, GeomOpt)에서 사용되는 단일 정규화 지점.
지원 형식: XYZ 파일(헤더 포함/미포함), PySCF 세미콜론 형식, 빈 줄/주석 포함.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

# 원소 기호 집합 (Z=1-118)
_ELEMENTS = frozenset({
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar",
    "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Ga", "Ge", "As", "Se", "Br", "Kr",
    "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd",
    "In", "Sn", "Sb", "Te", "I", "Xe",
    "Cs", "Ba", "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy",
    "Ho", "Er", "Tm", "Yb", "Lu",
    "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
    "Tl", "Pb", "Bi", "Po", "At", "Rn",
    "Fr", "Ra", "Ac", "Th", "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf",
    "Es", "Fm", "Md", "No", "Lr",
    "Rf", "Db", "Sg", "Bh", "Hs", "Mt", "Ds", "Rg", "Cn",
    "Nh", "Fl", "Mc", "Lv", "Ts", "Og",
})

_COMMENT_RE = re.compile(r"^\s*[#!%]")
_BLANK_RE = re.compile(r"^\s*$")


def _is_atom_line(line: str) -> bool:
    """원소기호 + 3개 float 좌표가 있는 줄인지 판별."""
    parts = line.split()
    if len(parts) < 4:
        return False
    # 첫 토큰이 원소 기호인지 (대소문자 무관)
    sym = parts[0].strip().capitalize()
    # 숫자로 시작하는 경우 원자번호일 수 있음 (e.g., "8 0.0 0.0 0.0")
    if sym.isdigit():
        return len(parts) >= 4
    if sym not in _ELEMENTS:
        return False
    # 나머지 3개가 float인지
    try:
        for i in range(1, 4):
            float(parts[i])
        return True
    except (ValueError, IndexError):
        return False


def sanitize_xyz(raw: str, max_atoms: int = 200) -> str:
    """원시 원자 좌표 문자열을 PySCF 세미콜론 형식으로 정규화.

    Parameters
    ----------
    raw : str
        XYZ 파일 전체, PySCF 형식, 또는 혼합 형식의 원자 좌표 문자열.
    max_atoms : int
        허용 최대 원자 수 (보안 제한).

    Returns
    -------
    str
        "C 0.0 0.0 0.0; H 1.0 0.0 0.0; ..." 형식의 정규화된 문자열.

    Raises
    ------
    ValueError
        원자 좌표를 하나도 추출할 수 없는 경우.
    """
    if not raw or not raw.strip():
        raise ValueError("Empty atom specification")

    raw = raw.strip()

    # 모든 구분자(세미콜론, 개행)를 개행으로 통일하여 줄 단위 처리
    normalized_raw = raw.replace(";", "\n")
    lines = normalized_raw.splitlines()
    atoms = []

    for line in lines:
        line = line.strip()
        if not line: continue
        # 빈 줄, 주석 줄 건너뛰기
        if _BLANK_RE.match(line) or _COMMENT_RE.match(line):
            continue
        # 순수 정수 한 개만 있는 줄 (XYZ 헤더의 원자 수)
        if line.isdigit():
            continue
        # 원자 줄 시도
        if _is_atom_line(line):
            atoms.append(_normalize_atom_token(line))
        # 그 외: XYZ 파일의 comment line (두 번째 줄) — 무시

    if not atoms:
        raise ValueError(
            "No valid atom coordinates found. Expected format: "
            "'Element X Y Z' (one per line) or 'Element X Y Z; Element X Y Z; ...'"
        )

    if len(atoms) > max_atoms:
        raise ValueError("Too many atoms: %d (max %d)" % (len(atoms), max_atoms))

    return "; ".join(atoms)


def _normalize_atom_token(line: str) -> str:
    """단일 원자 줄을 'Element X Y Z' 형식으로 정규화."""
    parts = line.split()
    sym = parts[0].strip()

    # 원자번호인 경우 원소 기호로 변환
    if sym.isdigit():
        sym = _z_to_symbol(int(sym))
    else:
        sym = sym.capitalize()
        # "C1", "H2" 같은 라벨에서 숫자 제거
        sym = re.sub(r"\d+$", "", sym)

    x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
    return "%s  %.10f  %.10f  %.10f" % (sym, x, y, z)


def _z_to_symbol(z: int) -> str:
    """원자번호를 원소 기호로 변환."""
    _Z_MAP = [
        "", "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
        "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar",
        "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
        "Ga", "Ge", "As", "Se", "Br", "Kr",
        "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd",
        "In", "Sn", "Sb", "Te", "I", "Xe",
    ]
    if 1 <= z < len(_Z_MAP):
        return _Z_MAP[z]
    return "X"


def extract_atom_list(sanitized: str) -> list:
    """정규화된 문자열에서 [(symbol, x, y, z), ...] 리스트 추출."""
    atoms = []
    for seg in sanitized.split(";"):
        seg = seg.strip()
        if not seg:
            continue
        parts = seg.split()
        atoms.append((parts[0], float(parts[1]), float(parts[2]), float(parts[3])))
    return atoms


def atoms_to_xyz_string(atoms: list, comment: str = "") -> str:
    """[(symbol, x, y, z), ...] 리스트를 XYZ 파일 문자열로 변환."""
    lines = [str(len(atoms)), comment]
    for sym, x, y, z in atoms:
        lines.append("%-2s  %14.8f  %14.8f  %14.8f" % (sym, x, y, z))
    return "\n".join(lines)

```

---

## 파일: `src/qcviz_mcp/advisor/__init__.py` (48줄, 1134bytes)

```python
"""
QCViz-MCP Advisor Package -- Experimentalist Autonomy Modules.

Provides intelligent assistance for experimental chemists performing
computational chemistry verification without specialist knowledge.

Version: 1.1.0
"""

__version__ = "1.1.0"

__all__ = [
    "PresetRecommender",
    "PresetRecommendation",
    "MethodsSectionDrafter",
    "MethodsDraft",
    "CalculationRecord",
    "ReproducibilityScriptGenerator",
    "LiteratureEnergyValidator",
    "ValidationRequest",
    "ValidationResult",
    "BondValidation",
    "ConfidenceScorer",
    "ConfidenceReport",
]

from qcviz_mcp.advisor.preset_recommender import (
    PresetRecommender,
    PresetRecommendation,
)
from qcviz_mcp.advisor.methods_drafter import (
    MethodsSectionDrafter,
    MethodsDraft,
    CalculationRecord,
)
from qcviz_mcp.advisor.script_generator import (
    ReproducibilityScriptGenerator,
)
from qcviz_mcp.advisor.literature_validator import (
    LiteratureEnergyValidator,
    ValidationRequest,
    ValidationResult,
    BondValidation,
)
from qcviz_mcp.advisor.confidence_scorer import (
    ConfidenceScorer,
    ConfidenceReport,
)

```

---

## 파일: `src/qcviz_mcp/advisor/confidence_scorer.py` (383줄, 11863bytes)

```python
"""
Calculation Confidence Scorer (F7).

Computes a composite confidence score for quantum chemistry
calculations based on convergence quality, method appropriateness,
basis set adequacy, and reference data agreement.

Version: 1.1.0
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from qcviz_mcp.advisor.reference_data import (
    load_dft_accuracy_table,
    load_functional_recommendations,
    normalize_func_key,
)

__all__ = ["ConfidenceScorer", "ConfidenceReport"]

logger = logging.getLogger(__name__)

_DISCLAIMER = (
    "This confidence score is a heuristic estimate based on "
    "convergence metrics, method benchmarks, and reference data "
    "agreement. It should not be interpreted as a statistical "
    "probability. Consult a computational chemist for definitive "
    "quality assessment."
)


@dataclass
class ConfidenceReport:
    """Detailed confidence score breakdown."""

    overall_score: float
    convergence_score: float
    basis_score: float
    method_score: float
    spin_score: float
    reference_score: float
    breakdown_text: str
    recommendations: list = field(default_factory=list)
    disclaimer: str = _DISCLAIMER


class ConfidenceScorer:
    """Computes composite confidence scores for QC calculations.

    Evaluates multiple quality dimensions and combines them into
    a single 0.0-1.0 confidence metric with detailed breakdown.
    """

    def __init__(self):
        """Initialize scorer with reference data."""
        self._accuracy = load_dft_accuracy_table()
        self._recommendations = load_functional_recommendations()

    def score(
        self,
        converged=True,
        n_scf_cycles=0,
        max_cycles=200,
        functional="B3LYP",
        basis="def2-SVP",
        system_type="organic_small",
        spin=0,
        s2_expected=0.0,
        s2_actual=0.0,
        validation_status=None,
    ):
        """Compute a composite confidence score.

        Args:
            converged (bool): Whether SCF converged.
            n_scf_cycles (int): Number of SCF cycles used.
            max_cycles (int): Maximum allowed SCF cycles.
            functional (str): DFT functional used.
            basis (str): Basis set used.
            system_type (str): System classification.
            spin (int): Spin state (2S).
            s2_expected (float): Expected <S^2> value.
            s2_actual (float): Actual <S^2> value from calculation.
            validation_status (str): 'PASS', 'WARN', 'FAIL', or None.

        Returns:
            ConfidenceReport: Detailed score breakdown.
        """
        # 1. Convergence quality (0-1)
        conv_score = self._score_convergence(
            converged, n_scf_cycles, max_cycles
        )

        # 2. Basis set adequacy (0-1)
        basis_score = self._score_basis(basis, system_type)

        # 3. Method appropriateness (0-1)
        method_score = self._score_method(functional, system_type)

        # 4. Spin contamination (0-1)
        spin_score = self._score_spin(
            spin, s2_expected, s2_actual
        )

        # 5. Reference agreement (0-1)
        ref_score = self._score_reference(validation_status)

        # Weights (verified: both sum to 1.0)
        if spin > 0:
            weights = {
                "convergence": 0.20,
                "basis": 0.15,
                "method": 0.25,
                "spin": 0.20,
                "reference": 0.20,
            }
        else:
            weights = {
                "convergence": 0.20,
                "basis": 0.20,
                "method": 0.25,
                "spin": 0.05,
                "reference": 0.30,
            }

        overall = (
            weights["convergence"] * conv_score
            + weights["basis"] * basis_score
            + weights["method"] * method_score
            + weights["spin"] * spin_score
            + weights["reference"] * ref_score
        )

        # Hard cap: unconverged calculations must never exceed 0.4
        if not converged:
            overall = min(overall, 0.4)

        breakdown = self._format_breakdown(
            conv_score, basis_score, method_score,
            spin_score, ref_score, weights,
        )

        recs = self._generate_recommendations(
            conv_score, basis_score, method_score,
            spin_score, ref_score, functional, basis,
        )

        return ConfidenceReport(
            overall_score=round(overall, 2),
            convergence_score=round(conv_score, 2),
            basis_score=round(basis_score, 2),
            method_score=round(method_score, 2),
            spin_score=round(spin_score, 2),
            reference_score=round(ref_score, 2),
            breakdown_text=breakdown,
            recommendations=recs,
            disclaimer=_DISCLAIMER,
        )

    def _score_convergence(self, converged, n_cycles, max_cycles):
        """Score SCF convergence quality.

        Args:
            converged (bool): Whether SCF converged.
            n_cycles (int): Cycles used.
            max_cycles (int): Max cycles.

        Returns:
            float: Score 0.0-1.0.
        """
        if not converged:
            return 0.1
        if n_cycles == 0:
            return 0.7  # Unknown cycle count
        ratio = n_cycles / float(max_cycles)
        if ratio < 0.1:
            return 1.0
        if ratio < 0.3:
            return 0.9
        if ratio < 0.5:
            return 0.7
        return 0.5

    def _score_basis(self, basis, system_type):
        """Score basis set adequacy for the system type.

        Args:
            basis (str): Basis set name.
            system_type (str): System classification.

        Returns:
            float: Score 0.0-1.0.
        """
        basis_lower = basis.lower()
        if "qzvp" in basis_lower:
            return 1.0
        if "tzvp" in basis_lower:
            return 0.9
        if "svp" in basis_lower:
            if system_type in ("organic_small", "radical"):
                return 0.7
            return 0.5  # SVP too small for complex systems
        # Unknown basis
        return 0.5

    def _score_method(self, functional, system_type):
        """Score method appropriateness for system type.

        Args:
            functional (str): DFT functional.
            system_type (str): System classification.

        Returns:
            float: Score 0.0-1.0.
        """
        func_key = normalize_func_key(functional)
        acc = self._accuracy.get(func_key, {})
        wtmad2 = acc.get("wtmad2_kcal", None)

        if wtmad2 is None:
            return 0.5  # Unknown functional

        # FIXED #18: WTMAD-2 thresholds aligned with official Bonn
        # GMTKN55 values (def2-QZVP + dispersion correction).
        # < 5.0 = excellent (wB97X-V 3.98, M06-2X 4.94)
        # 5-7   = good (PW6B95 5.50, B3LYP 6.42, PBE0 6.61)
        # 7-10  = adequate (TPSSh 7.54, R2SCAN ~7.9, TPSS 9.10)
        # > 10  = poor (PBE 10.32)
        if wtmad2 <= 5.0:
            base = 0.95
        elif wtmad2 <= 7.0:
            base = 0.80
        elif wtmad2 <= 10.0:
            base = 0.65
        else:
            base = 0.40

        # System-specific bonus for recommended functional
        # FIXED #7: Exact match only (no substring)
        rules = self._recommendations.get(system_type, {})
        default_func = rules.get("default", {}).get("functional", "")
        if default_func:
            default_func_key = normalize_func_key(default_func)
            if func_key == default_func_key:
                base = min(1.0, base + 0.05)

        return base

    def _score_spin(self, spin, s2_expected, s2_actual):
        """Score spin contamination quality.

        Args:
            spin (int): 2S spin value.
            s2_expected (float): Expected <S^2>.
            s2_actual (float): Actual <S^2>.

        Returns:
            float: Score 0.0-1.0.
        """
        if spin == 0:
            return 1.0  # Closed-shell, no issue
        if s2_actual == 0.0 and s2_expected == 0.0:
            return 0.7  # No data available
        if s2_expected == 0.0:
            return 0.7

        deviation = abs(s2_actual - s2_expected) / s2_expected
        if deviation < 0.05:
            return 1.0
        if deviation < 0.10:
            return 0.8
        if deviation < 0.20:
            return 0.5
        return 0.2

    def _score_reference(self, validation_status):
        """Score agreement with reference data.

        Args:
            validation_status (str or None): Validation status.

        Returns:
            float: Score 0.0-1.0.
        """
        if validation_status is None:
            return 0.5  # No validation performed
        if validation_status == "PASS":
            return 1.0
        if validation_status == "WARN":
            return 0.6
        if validation_status == "FAIL":
            return 0.2
        return 0.5

    def _format_breakdown(
        self, conv, basis, method, spin, ref, weights
    ):
        """Format a human-readable score breakdown.

        Args:
            conv (float): Convergence score.
            basis (float): Basis score.
            method (float): Method score.
            spin (float): Spin score.
            ref (float): Reference score.
            weights (dict): Weight dictionary.

        Returns:
            str: Formatted breakdown text.
        """
        lines = []
        lines.append("Confidence Score Breakdown:")
        lines.append(
            "  Convergence:  %.2f (weight: %.0f%%)"
            % (conv, weights["convergence"] * 100)
        )
        lines.append(
            "  Basis Set:    %.2f (weight: %.0f%%)"
            % (basis, weights["basis"] * 100)
        )
        lines.append(
            "  Method:       %.2f (weight: %.0f%%)"
            % (method, weights["method"] * 100)
        )
        lines.append(
            "  Spin:         %.2f (weight: %.0f%%)"
            % (spin, weights["spin"] * 100)
        )
        lines.append(
            "  Reference:    %.2f (weight: %.0f%%)"
            % (ref, weights["reference"] * 100)
        )
        return "\n".join(lines)

    def _generate_recommendations(
        self, conv, basis, method, spin, ref,
        functional, basis_set,
    ):
        """Generate improvement recommendations.

        Args:
            conv (float): Convergence score.
            basis (float): Basis score.
            method (float): Method score.
            spin (float): Spin score.
            ref (float): Reference score.
            functional (str): Functional name.
            basis_set (str): Basis set name.

        Returns:
            list: List of recommendation strings.
        """
        recs = []
        if conv < 0.5:
            recs.append(
                "SCF convergence is poor. Try increasing max_cycle, "
                "using level shifting, or applying DIIS damping."
            )
        if basis < 0.7:
            recs.append(
                "Consider using a larger basis set (def2-TZVP or "
                "def2-QZVP) for more reliable results."
            )
        if method < 0.6:
            recs.append(
                "The chosen functional (%s) may not be optimal for "
                "this system type. Consult the preset recommender "
                "for alternatives." % functional
            )
        if spin < 0.5:
            recs.append(
                "Significant spin contamination detected. Results "
                "for this open-shell system may be unreliable. "
                "Consider ROHF or a different functional."
            )
        if ref < 0.5:
            recs.append(
                "Computed properties deviate from reference data. "
                "Re-check geometry and method choice."
            )
        return recs

```

---

## 파일: `src/qcviz_mcp/advisor/literature_validator.py` (475줄, 15087bytes)

```python
"""
Literature Energy Validator (F4).

Compares computed molecular properties against curated reference
databases (NIST CCCBDB, GMTKN55, W4-11) to assess calculation
quality and flag potential issues.

Version: 1.1.0
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from qcviz_mcp.advisor.reference_data import (
    load_nist_bonds,
    load_dft_accuracy_table,
    normalize_func_key,
)

__all__ = [
    "LiteratureEnergyValidator",
    "ValidationRequest",
    "ValidationResult",
    "BondValidation",
]

logger = logging.getLogger(__name__)

_DISCLAIMER = (
    "IMPORTANT: This validation is based on comparison with a limited "
    "curated reference dataset. It provides a preliminary quality "
    "assessment only. Results should be reviewed by a qualified "
    "computational chemist before drawing scientific conclusions or "
    "preparing manuscripts for publication."
)

# Status thresholds
_BOND_PASS_THRESHOLD = 0.02   # Angstrom
_BOND_WARN_THRESHOLD = 0.05   # Angstrom
_ANGLE_PASS_THRESHOLD = 2.0   # degrees
_ANGLE_WARN_THRESHOLD = 5.0   # degrees

# Hill-system formula aliases for common molecules
_FORMULA_ALIASES = {
    "H2CO": "CH2O",
    "HCHO": "CH2O",
    "H2O2": "H2O2",
    "HOOH": "H2O2",
}


@dataclass
class BondValidation:
    """Validation result for a single bond length or angle."""

    bond_type: str
    computed: float
    reference: float
    reference_source: str
    deviation: float
    status: str
    expected_accuracy: str
    comment: str


@dataclass
class ValidationRequest:
    """Input for literature validation."""

    bond_lengths: dict = field(default_factory=dict)
    bond_angles: dict = field(default_factory=dict)
    energy_hartree: float = 0.0
    functional: str = ""
    basis: str = ""
    system_formula: str = ""


@dataclass
class ValidationResult:
    """Complete validation output."""

    bond_validations: list = field(default_factory=list)
    angle_validations: list = field(default_factory=list)
    method_assessment: str = ""
    overall_status: str = "UNKNOWN"
    confidence: float = 0.0
    recommendations: list = field(default_factory=list)
    disclaimer: str = _DISCLAIMER


class LiteratureEnergyValidator:
    """Validates computed results against literature reference data.

    Compares bond lengths, bond angles, and energies with curated
    reference values from NIST CCCBDB and benchmark databases.
    Provides status tags (PASS/WARN/FAIL) and actionable recommendations.
    """

    def __init__(self):
        """Initialize validator with reference databases."""
        self._nist = load_nist_bonds()
        self._accuracy = load_dft_accuracy_table()

    def validate(self, request):
        """Validate computed properties against reference data.

        Args:
            request (ValidationRequest): Properties to validate.

        Returns:
            ValidationResult: Detailed validation report.
        """
        bond_vals = []
        if request.bond_lengths:
            bond_vals = self._validate_bonds(
                request.bond_lengths,
                request.system_formula,
                request.functional,
                request.basis,
            )

        angle_vals = []
        if request.bond_angles:
            angle_vals = self._validate_angles(
                request.bond_angles,
                request.system_formula,
            )

        method_assess = self._assess_method(
            request.functional, request.basis
        )

        overall = self._compute_overall_status(
            bond_vals, angle_vals
        )
        confidence = self._compute_confidence(
            bond_vals, angle_vals, request.functional
        )
        recs = self._generate_recommendations(
            bond_vals, angle_vals, request.functional, request.basis
        )

        return ValidationResult(
            bond_validations=bond_vals,
            angle_validations=angle_vals,
            method_assessment=method_assess,
            overall_status=overall,
            confidence=round(confidence, 2),
            recommendations=recs,
            disclaimer=_DISCLAIMER,
        )

    def _resolve_formula(self, formula):
        """Resolve formula aliases to canonical Hill-system key.

        Args:
            formula (str): Molecular formula.

        Returns:
            str: Canonical formula key.
        """
        return _FORMULA_ALIASES.get(formula, formula)

    def _validate_bonds(
        self, bond_lengths, formula, functional, basis
    ):
        """Validate computed bond lengths against NIST data.

        Args:
            bond_lengths (dict): {'O-H': 0.969, ...}
            formula (str): Molecular formula.
            functional (str): DFT functional used.
            basis (str): Basis set used.

        Returns:
            list: List of BondValidation objects.
        """
        results = []
        canonical = self._resolve_formula(formula)
        mol_data = self._nist.get(canonical, {})
        # Also try original formula
        if not mol_data or canonical == formula:
            mol_data = self._nist.get(formula, mol_data)

        func_key = normalize_func_key(functional)
        accuracy_data = self._accuracy.get(func_key, {})
        expected_mae = accuracy_data.get(
            "bond_length_mae_angstrom", 0.01
        )

        for bond_type, computed_val in bond_lengths.items():
            # Normalize bond type: "O-H" and "H-O" should match
            normalized = self._normalize_bond_type(bond_type)
            ref_entry = mol_data.get(normalized, None)

            if ref_entry is None:
                # Try reverse
                reversed_bt = self._reverse_bond_type(normalized)
                ref_entry = mol_data.get(reversed_bt, None)

            if ref_entry is None:
                # No reference data available
                continue

            ref_val = ref_entry.get("value", 0.0)
            source = ref_entry.get("source", "NIST CCCBDB")
            deviation = abs(computed_val - ref_val)

            if deviation <= _BOND_PASS_THRESHOLD:
                status = "PASS"
                comment = (
                    "Within expected DFT accuracy "
                    "(typical MAE: %.3f Angstrom)." % expected_mae
                )
            elif deviation <= _BOND_WARN_THRESHOLD:
                status = "WARN"
                comment = (
                    "Deviation (%.3f Angstrom) is slightly above typical "
                    "DFT accuracy. Consider checking geometry convergence."
                    % deviation
                )
            else:
                status = "FAIL"
                comment = (
                    "Deviation (%.3f Angstrom) significantly exceeds "
                    "typical DFT accuracy (MAE %.3f Angstrom). "
                    "This may indicate a problem with the geometry "
                    "or method choice." % (deviation, expected_mae)
                )

            results.append(BondValidation(
                bond_type=bond_type,
                computed=round(computed_val, 4),
                reference=round(ref_val, 4),
                reference_source=source,
                deviation=round(deviation, 4),
                status=status,
                expected_accuracy=(
                    "%s/%s typical MAE: %.3f Angstrom"
                    % (functional, basis, expected_mae)
                ),
                comment=comment,
            ))

        return results

    def _validate_angles(self, bond_angles, formula):
        """Validate computed bond angles against reference data.

        Args:
            bond_angles (dict): {'H-O-H': 104.5, ...}
            formula (str): Molecular formula.

        Returns:
            list: List of BondValidation objects (reused for angles).
        """
        results = []
        canonical = self._resolve_formula(formula)
        mol_data = self._nist.get(canonical, {})
        if not mol_data or canonical == formula:
            mol_data = self._nist.get(formula, mol_data)

        for angle_type, computed_val in bond_angles.items():
            ref_entry = mol_data.get(angle_type, None)
            # FIXED #17: Try reversed angle key (e.g., F-C-H -> H-C-F)
            if ref_entry is None:
                reversed_at = self._reverse_bond_type(angle_type)
                ref_entry = mol_data.get(reversed_at, None)
            if ref_entry is None:
                continue

            ref_val = ref_entry.get("value", 0.0)
            source = ref_entry.get("source", "NIST CCCBDB")
            deviation = abs(computed_val - ref_val)

            if deviation <= _ANGLE_PASS_THRESHOLD:
                status = "PASS"
                comment = "Within expected accuracy."
            elif deviation <= _ANGLE_WARN_THRESHOLD:
                status = "WARN"
                comment = (
                    "Deviation of %.1f degrees is slightly above normal."
                    % deviation
                )
            else:
                status = "FAIL"
                comment = (
                    "Deviation of %.1f degrees is significant. "
                    "Check geometry convergence." % deviation
                )

            results.append(BondValidation(
                bond_type=angle_type,
                computed=round(computed_val, 2),
                reference=round(ref_val, 2),
                reference_source=source,
                deviation=round(deviation, 2),
                status=status,
                expected_accuracy="Typical DFT angle error: 1-2 degrees",
                comment=comment,
            ))

        return results

    def _assess_method(self, functional, basis):
        """Generate an overall method quality assessment.

        Args:
            functional (str): DFT functional.
            basis (str): Basis set.

        Returns:
            str: Assessment text.
        """
        func_key = normalize_func_key(functional)
        acc = self._accuracy.get(func_key, {})

        if not acc:
            return (
                "No benchmark data available for %s. "
                "Consider using a well-benchmarked functional."
                % functional
            )

        wtmad2 = acc.get("wtmad2_kcal", None)
        bond_mae = acc.get("bond_length_mae_angstrom", None)
        reaction_mae = acc.get("reaction_energy_mae_kcal", None)

        parts = []
        parts.append(
            "Method: %s/%s." % (functional, basis)
        )
        if wtmad2 is not None:
            parts.append(
                "GMTKN55 WTMAD-2: %.1f kcal/mol." % wtmad2
            )
        if bond_mae is not None:
            parts.append(
                "Typical bond length MAE: %.3f Angstrom." % bond_mae
            )
        if reaction_mae is not None:
            parts.append(
                "Typical reaction energy MAE: %.1f kcal/mol."
                % reaction_mae
            )

        return " ".join(parts)

    def _compute_overall_status(self, bond_vals, angle_vals):
        """Compute overall validation status.

        Args:
            bond_vals (list): Bond validations.
            angle_vals (list): Angle validations.

        Returns:
            str: 'PASS', 'WARN', or 'FAIL'.
        """
        all_vals = bond_vals + angle_vals
        if not all_vals:
            return "UNKNOWN"

        statuses = [v.status for v in all_vals]
        if "FAIL" in statuses:
            return "FAIL"
        if "WARN" in statuses:
            return "WARN"
        return "PASS"

    def _compute_confidence(self, bond_vals, angle_vals, functional):
        """Compute numerical confidence score.

        Args:
            bond_vals (list): Bond validations.
            angle_vals (list): Angle validations.
            functional (str): Functional used.

        Returns:
            float: Confidence score 0.0-1.0.
        """
        if not bond_vals and not angle_vals:
            return 0.5  # No data to validate against

        all_vals = bond_vals + angle_vals
        n_total = len(all_vals)
        n_pass = sum(1 for v in all_vals if v.status == "PASS")
        n_warn = sum(1 for v in all_vals if v.status == "WARN")

        base_score = (n_pass + 0.5 * n_warn) / n_total

        # Method quality bonus
        func_key = normalize_func_key(functional)
        acc = self._accuracy.get(func_key, {})
        wtmad2 = acc.get("wtmad2_kcal", 10.0)
        method_bonus = max(0, min(0.1, (10.0 - wtmad2) / 100.0))

        return min(1.0, base_score + method_bonus)

    def _generate_recommendations(
        self, bond_vals, angle_vals, functional, basis
    ):
        """Generate actionable recommendations.

        Args:
            bond_vals (list): Bond validations.
            angle_vals (list): Angle validations.
            functional (str): Functional used.
            basis (str): Basis set used.

        Returns:
            list: List of recommendation strings.
        """
        recs = []

        fail_bonds = [v for v in bond_vals if v.status == "FAIL"]
        if fail_bonds:
            recs.append(
                "Some bond lengths deviate significantly from "
                "experiment. Consider: (1) re-optimizing the geometry "
                "with tighter convergence, (2) using a larger basis "
                "set, or (3) trying an alternative functional."
            )

        if "svp" in basis.lower() and "tzvp" not in basis.lower():
            recs.append(
                "A double-zeta basis set is used. For more accurate "
                "energies, perform a single-point calculation with "
                "def2-TZVP at the optimized geometry."
            )

        has_disp = any(
            d in functional.lower()
            for d in ("d3", "d4", "vv10", "-d")
        )
        if not has_disp:
            recs.append(
                "No dispersion correction detected. Modern best "
                "practices recommend always including a dispersion "
                "correction (e.g., D3BJ). See Bursch et al. "
                "Angew. Chem. Int. Ed. 2022, 61, e202205735."
            )

        return recs

    def _normalize_bond_type(self, bond_type):
        """Normalize a bond type string (e.g., 'O-H' stays 'O-H').

        Args:
            bond_type (str): Bond type string.

        Returns:
            str: Normalized bond type.
        """
        return bond_type.strip()

    def _reverse_bond_type(self, bond_type):
        """Reverse a bond or angle type string.

        For bonds (2 atoms): 'O-H' -> 'H-O'.
        For angles (3 atoms): 'F-C-H' -> 'H-C-F'
        (central atom stays in place).

        Args:
            bond_type (str): Bond or angle type string.

        Returns:
            str: Reversed type string.
        """
        parts = bond_type.split("-")
        if len(parts) == 2:
            return "%s-%s" % (parts[1], parts[0])
        if len(parts) == 3:
            return "%s-%s-%s" % (parts[2], parts[1], parts[0])
        return bond_type

```

---

## 파일: `src/qcviz_mcp/advisor/methods_drafter.py` (661줄, 23032bytes)

```python
"""
Computational Methods Section Draft Generator (F2).

Generates publication-ready Computational Methods text from
calculation metadata, with proper citations in BibTeX format.

Version: 1.1.0
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

__all__ = [
    "MethodsSectionDrafter",
    "MethodsDraft",
    "CalculationRecord",
]

logger = logging.getLogger(__name__)

# Citation database -- DOIs and BibTeX for common methods/software
_CITATIONS = {
    "pyscf": {
        "key": "Sun2020PySCF",
        "doi": "10.1063/5.0006074",
        "short": "Sun et al., J. Chem. Phys. 2020, 153, 024109",
        "bibtex": (
            "@article{Sun2020PySCF,\n"
            "  author  = {Sun, Qiming and Zhang, Xing and Banerjee, Samragni "
            "and Bao, Peng and Barbry, Marc and Blunt, Nick S. and "
            "Bogdanov, Nikolay A. and Booth, George H. and Chen, Jia "
            "and Cui, Zhi-Hao and others},\n"
            "  title   = {Recent developments in the {PySCF} program package},\n"
            "  journal = {J. Chem. Phys.},\n"
            "  volume  = {153},\n"
            "  pages   = {024109},\n"
            "  year    = {2020},\n"
            "  doi     = {10.1063/5.0006074},\n"
            "}\n"
        ),
    },
    "b3lyp": {
        "key": "Becke1993",
        "doi": "10.1063/1.464913",
        "short": "Becke, J. Chem. Phys. 1993, 98, 5648",
        "bibtex": (
            "@article{Becke1993,\n"
            "  author  = {Becke, Axel D.},\n"
            "  title   = {Density-functional thermochemistry. {III}. "
            "The role of exact exchange},\n"
            "  journal = {J. Chem. Phys.},\n"
            "  volume  = {98},\n"
            "  pages   = {5648--5652},\n"
            "  year    = {1993},\n"
            "  doi     = {10.1063/1.464913},\n"
            "}\n"
        ),
    },
    "lyp": {
        "key": "Lee1988",
        "doi": "10.1103/PhysRevB.37.785",
        "short": "Lee, Yang, Parr, Phys. Rev. B 1988, 37, 785",
        "bibtex": (
            "@article{Lee1988,\n"
            "  author  = {Lee, Chengteh and Yang, Weitao and Parr, Robert G.},\n"
            "  title   = {Development of the {Colle}-{Salvetti} "
            "correlation-energy formula into a functional of the "
            "electron density},\n"
            "  journal = {Phys. Rev. B},\n"
            "  volume  = {37},\n"
            "  pages   = {785--789},\n"
            "  year    = {1988},\n"
            "  doi     = {10.1103/PhysRevB.37.785},\n"
            "}\n"
        ),
    },
    "def2": {
        "key": "Weigend2005",
        "doi": "10.1039/B508541A",
        "short": (
            "Weigend, Ahlrichs, Phys. Chem. Chem. Phys. 2005, 7, 3297"
        ),
        "bibtex": (
            "@article{Weigend2005,\n"
            "  author  = {Weigend, Florian and Ahlrichs, Reinhart},\n"
            "  title   = {Balanced basis sets of split valence, triple zeta "
            "valence and quadruple zeta valence quality for {H} to "
            "{Rn}: Design and assessment of accuracy},\n"
            "  journal = {Phys. Chem. Chem. Phys.},\n"
            "  volume  = {7},\n"
            "  pages   = {3297--3305},\n"
            "  year    = {2005},\n"
            "  doi     = {10.1039/B508541A},\n"
            "}\n"
        ),
    },
    "d3": {
        "key": "Grimme2010",
        "doi": "10.1063/1.3382344",
        "short": (
            "Grimme, Antony, Ehrlich, Krieg, "
            "J. Chem. Phys. 2010, 132, 154104"
        ),
        "bibtex": (
            "@article{Grimme2010,\n"
            "  author  = {Grimme, Stefan and Antony, Jens and Ehrlich, "
            "Stephan and Krieg, Helge},\n"
            "  title   = {A consistent and accurate ab initio parametrization "
            "of density functional dispersion correction ({DFT}-{D}) "
            "for the 94 elements {H}-{Pu}},\n"
            "  journal = {J. Chem. Phys.},\n"
            "  volume  = {132},\n"
            "  pages   = {154104},\n"
            "  year    = {2010},\n"
            "  doi     = {10.1063/1.3382344},\n"
            "}\n"
        ),
    },
    "d3bj": {
        "key": "Grimme2011",
        "doi": "10.1002/jcc.21759",
        "short": (
            "Grimme, Ehrlich, Goerigk, "
            "J. Comput. Chem. 2011, 32, 1456"
        ),
        "bibtex": (
            "@article{Grimme2011,\n"
            "  author  = {Grimme, Stefan and Ehrlich, Stephan and "
            "Goerigk, Lars},\n"
            "  title   = {Effect of the damping function in dispersion "
            "corrected density functional theory},\n"
            "  journal = {J. Comput. Chem.},\n"
            "  volume  = {32},\n"
            "  pages   = {1456--1465},\n"
            "  year    = {2011},\n"
            "  doi     = {10.1002/jcc.21759},\n"
            "}\n"
        ),
    },
    "geometric": {
        "key": "Wang2016",
        "doi": "10.1063/1.4952956",
        "short": (
            "Wang, Song, J. Chem. Phys. 2016, 144, 214108"
        ),
        "bibtex": (
            "@article{Wang2016,\n"
            "  author  = {Wang, Lee-Ping and Song, Chenchen},\n"
            "  title   = {Geometry optimization made simple with "
            "translation and rotation coordinates},\n"
            "  journal = {J. Chem. Phys.},\n"
            "  volume  = {144},\n"
            "  pages   = {214108},\n"
            "  year    = {2016},\n"
            "  doi     = {10.1063/1.4952956},\n"
            "}\n"
        ),
    },
    "iao": {
        "key": "Knizia2013IAO",
        "doi": "10.1021/ct400687b",
        "short": (
            "Knizia, J. Chem. Theory Comput. 2013, 9, 4834"
        ),
        "bibtex": (
            "@article{Knizia2013IAO,\n"
            "  author  = {Knizia, Gerald},\n"
            "  title   = {Intrinsic Atomic Orbitals: An Unbiased Bridge "
            "between Quantum Theory and Chemical Concepts},\n"
            "  journal = {J. Chem. Theory Comput.},\n"
            "  volume  = {9},\n"
            "  pages   = {4834--4843},\n"
            "  year    = {2013},\n"
            "  doi     = {10.1021/ct400687b},\n"
            "}\n"
        ),
    },
    "ibo": {
        "key": "Knizia2013IBO",
        "doi": "10.1021/ct400687b",
        "short": (
            "Knizia, J. Chem. Theory Comput. 2013, 9, 4834"
        ),
        "bibtex": "",  # Same paper as IAO
    },
    "pbe0": {
        "key": "Adamo1999",
        "doi": "10.1063/1.478522",
        "short": "Adamo, Barone, J. Chem. Phys. 1999, 110, 6158",
        "bibtex": (
            "@article{Adamo1999,\n"
            "  author  = {Adamo, Carlo and Barone, Vincenzo},\n"
            "  title   = {Toward reliable density functional methods "
            "without adjustable parameters: The {PBE0} model},\n"
            "  journal = {J. Chem. Phys.},\n"
            "  volume  = {110},\n"
            "  pages   = {6158--6170},\n"
            "  year    = {1999},\n"
            "  doi     = {10.1063/1.478522},\n"
            "}\n"
        ),
    },
    "tpssh": {
        "key": "Staroverov2003",
        "doi": "10.1063/1.1626543",
        "short": (
            "Staroverov et al., J. Chem. Phys. 2003, 119, 12129"
        ),
        "bibtex": (
            "@article{Staroverov2003,\n"
            "  author  = {Staroverov, Viktor N. and Scuseria, Gustavo E. "
            "and Tao, Jianmin and Perdew, John P.},\n"
            "  title   = {Comparative assessment of a new nonempirical "
            "density functional: Molecules and hydrogen-bonded complexes},\n"
            "  journal = {J. Chem. Phys.},\n"
            "  volume  = {119},\n"
            "  pages   = {12129--12137},\n"
            "  year    = {2003},\n"
            "  doi     = {10.1063/1.1626543},\n"
            "}\n"
        ),
    },
    "tpss": {
        "key": "Tao2003",
        "doi": "10.1103/PhysRevLett.91.146401",
        "short": (
            "Tao, Perdew, Staroverov, Scuseria, "
            "Phys. Rev. Lett. 2003, 91, 146401"
        ),
        "bibtex": (
            "@article{Tao2003,\n"
            "  author  = {Tao, Jianmin and Perdew, John P. and "
            "Staroverov, Viktor N. and Scuseria, Gustavo E.},\n"
            "  title   = {Climbing the Density Functional Ladder: "
            "Nonempirical Meta-Generalized Gradient Approximation "
            "Designed for Molecules and Solids},\n"
            "  journal = {Phys. Rev. Lett.},\n"
            "  volume  = {91},\n"
            "  pages   = {146401},\n"
            "  year    = {2003},\n"
            "  doi     = {10.1103/PhysRevLett.91.146401},\n"
            "}\n"
        ),
    },
    # NEW: Additional functional citations
    "r2scan": {
        "key": "Furness2020",
        "doi": "10.1021/acs.jpclett.0c02405",
        "short": (
            "Furness et al., J. Phys. Chem. Lett. 2020, 11, 8208"
        ),
        "bibtex": (
            "@article{Furness2020,\n"
            "  author  = {Furness, James W. and Kaplan, Aaron D. and "
            "Ning, Jianwei and Perdew, John P. and Sun, Jianwei},\n"
            "  title   = {Accurate and Numerically Efficient r$^2${SCAN} "
            "Meta-Generalized Gradient Approximation},\n"
            "  journal = {J. Phys. Chem. Lett.},\n"
            "  volume  = {11},\n"
            "  pages   = {8208--8215},\n"
            "  year    = {2020},\n"
            "  doi     = {10.1021/acs.jpclett.0c02405},\n"
            "}\n"
        ),
    },
    "pw6b95": {
        "key": "Zhao2005",
        "doi": "10.1021/jp045141s",
        "short": (
            "Zhao, Truhlar, J. Phys. Chem. A 2005, 109, 5656"
        ),
        "bibtex": (
            "@article{Zhao2005,\n"
            "  author  = {Zhao, Yan and Truhlar, Donald G.},\n"
            "  title   = {Design of Density Functionals That Are Broadly "
            "Accurate for Thermochemistry, Thermochemical Kinetics, "
            "and Nonbonded Interactions},\n"
            "  journal = {J. Phys. Chem. A},\n"
            "  volume  = {109},\n"
            "  pages   = {5656--5667},\n"
            "  year    = {2005},\n"
            "  doi     = {10.1021/jp045141s},\n"
            "}\n"
        ),
    },
    "m062x": {
        "key": "Zhao2008",
        "doi": "10.1007/s00214-007-0310-x",
        "short": (
            "Zhao, Truhlar, Theor. Chem. Acc. 2008, 120, 215"
        ),
        "bibtex": (
            "@article{Zhao2008,\n"
            "  author  = {Zhao, Yan and Truhlar, Donald G.},\n"
            "  title   = {The {M06} suite of density functionals for main "
            "group thermochemistry, thermochemical kinetics, noncovalent "
            "interactions, excited states, and transition elements},\n"
            "  journal = {Theor. Chem. Acc.},\n"
            "  volume  = {120},\n"
            "  pages   = {215--241},\n"
            "  year    = {2008},\n"
            "  doi     = {10.1007/s00214-007-0310-x},\n"
            "}\n"
        ),
    },
}

_DISCLAIMER = (
    "Note: This computational methods text was auto-generated by "
    "QCViz-MCP. While all citations and technical details are accurate, "
    "the text should be reviewed by a qualified computational chemist "
    "before submission. Computational results presented here constitute "
    "a preliminary screening and should not replace expert analysis "
    "for publication-critical conclusions."
)


@dataclass
class CalculationRecord:
    """Metadata for a single calculation step."""

    system_name: str
    atom_spec: str
    charge: int
    spin: int
    functional: str
    basis: str
    dispersion: str = ""
    energy_hartree: float = 0.0
    converged: bool = True
    n_cycles: int = 0
    software: str = "PySCF"
    software_version: str = ""
    optimizer: str = ""
    convergence_criteria: dict = field(default_factory=dict)
    analysis_type: str = ""
    solvation: str = ""


@dataclass
class MethodsDraft:
    """Generated computational methods section."""

    methods_text: str
    bibtex_entries: list = field(default_factory=list)
    software_citations: list = field(default_factory=list)
    reviewer_notes: list = field(default_factory=list)
    disclaimer: str = _DISCLAIMER


class MethodsSectionDrafter:
    """Generates publication-ready Computational Methods text.

    Takes calculation metadata and produces natural-language methods
    descriptions with proper citations, suitable for direct inclusion
    in a chemistry manuscript.
    """

    def __init__(self):
        """Initialize the drafter with citation database."""
        self._citations = _CITATIONS

    def draft(self, records, citation_style="acs", include_bibtex=True):
        """Generate a methods section draft from calculation records.

        Args:
            records (list): List of CalculationRecord objects describing
                each calculation step.
            citation_style (str): Citation format ('acs', 'rsc', 'nature').
            include_bibtex (bool): Whether to include BibTeX entries.

        Returns:
            MethodsDraft: Complete methods draft with citations.
        """
        if not records:
            raise ValueError("at least one CalculationRecord is required.")

        used_citations = set()
        paragraphs = []

        # Software paragraph
        sw = records[0].software
        sw_version = records[0].software_version or "latest"
        sw_text = (
            "All density functional theory (DFT) calculations were "
            "performed using %s (version %s)" % (sw, sw_version)
        )
        used_citations.add("pyscf")
        sw_text += " [%s]." % self._cite("pyscf", citation_style)
        paragraphs.append(sw_text)

        # Method paragraph(s) -- one per unique method combination
        seen_methods = set()
        method_paragraphs = []
        for rec in records:
            method_key = (rec.functional, rec.basis, rec.dispersion)
            if method_key in seen_methods:
                continue
            seen_methods.add(method_key)

            mp = self._draft_method_paragraph(
                rec, citation_style, used_citations
            )
            method_paragraphs.append(mp)

        paragraphs.extend(method_paragraphs)

        # Geometry optimization paragraph (if any)
        opt_records = [r for r in records if r.optimizer]
        if opt_records:
            opt_text = self._draft_optimization_paragraph(
                opt_records[0], citation_style, used_citations
            )
            paragraphs.append(opt_text)

        # Analysis paragraph (if any)
        analysis_records = [r for r in records if r.analysis_type]
        if analysis_records:
            ana_text = self._draft_analysis_paragraph(
                analysis_records, citation_style, used_citations
            )
            paragraphs.append(ana_text)

        # Solvation paragraph (if any)
        solv_records = [r for r in records if r.solvation]
        if solv_records:
            solv_text = (
                "Solvation effects were accounted for using the %s "
                "implicit solvation model." % solv_records[0].solvation
            )
            paragraphs.append(solv_text)

        # Compile
        full_text = " ".join(paragraphs)

        bibtex_entries = []
        software_cites = []
        if include_bibtex:
            for ckey in sorted(used_citations):
                cdata = self._citations.get(ckey, {})
                bib = cdata.get("bibtex", "")
                if bib:
                    bibtex_entries.append(bib)
                software_cites.append(cdata.get("short", ""))

        reviewer_notes = self._generate_reviewer_notes(records)

        return MethodsDraft(
            methods_text=full_text,
            bibtex_entries=bibtex_entries,
            software_citations=software_cites,
            reviewer_notes=reviewer_notes,
            disclaimer=_DISCLAIMER,
        )

    def _draft_method_paragraph(
        self, rec, citation_style, used_citations
    ):
        """Draft a paragraph describing the method/basis combination.

        Args:
            rec (CalculationRecord): Calculation record.
            citation_style (str): Citation format.
            used_citations (set): Mutable set of used citation keys.

        Returns:
            str: Method description paragraph.
        """
        parts = []

        # Functional citation matching
        # FIXED #4: Sort keys by length descending to avoid
        # substring false matches (e.g., "pbe" matching "pbe0")
        func_lower = rec.functional.lower().replace("-", "")
        func_cite_key = None
        sorted_keys = sorted(
            self._citations.keys(), key=len, reverse=True
        )
        for key in sorted_keys:
            if func_lower == key or func_lower.startswith(key):
                func_cite_key = key
                break

        func_text = "The %s functional" % rec.functional
        if func_cite_key:
            used_citations.add(func_cite_key)
            func_text += " [%s]" % self._cite(
                func_cite_key, citation_style
            )
        parts.append(func_text)

        # Basis set
        basis_text = "was employed with the %s basis set" % rec.basis
        if "def2" in rec.basis.lower():
            used_citations.add("def2")
            basis_text += " [%s]" % self._cite("def2", citation_style)
        parts.append(basis_text)

        # Dispersion
        if rec.dispersion:
            disp = rec.dispersion.upper()
            if "D3" in disp and "BJ" in disp:
                disp_text = (
                    "Grimme's D3 dispersion correction with "
                    "Becke-Johnson damping (D3BJ)"
                )
                used_citations.add("d3bj")
                disp_text += (
                    " [%s]" % self._cite("d3bj", citation_style)
                )
                disp_text += " was applied"
            elif "D3" in disp:
                disp_text = "Grimme's D3 dispersion correction"
                used_citations.add("d3")
                disp_text += (
                    " [%s]" % self._cite("d3", citation_style)
                )
                disp_text += " was applied"
            else:
                disp_text = (
                    "Dispersion correction (%s) was applied" % disp
                )
            parts.append(disp_text)

        return ". ".join(parts) + "."

    def _draft_optimization_paragraph(
        self, rec, citation_style, used_citations
    ):
        """Draft a paragraph describing geometry optimization.

        Args:
            rec (CalculationRecord): Record with optimizer info.
            citation_style (str): Citation format.
            used_citations (set): Mutable set of used citation keys.

        Returns:
            str: Optimization description paragraph.
        """
        opt = rec.optimizer
        text = "Geometry optimizations were carried out using the %s " % opt
        text += "optimizer"
        if "geometr" in opt.lower():
            used_citations.add("geometric")
            text += " [%s]" % self._cite("geometric", citation_style)

        criteria = rec.convergence_criteria
        if criteria:
            energy_tol = criteria.get("energy", 1e-6)
            grad_rms = criteria.get("gradient_rms", 3e-4)
            text += (
                " with convergence criteria of %.0e Eh for energy "
                "and %.0e Eh/Bohr for the RMS gradient"
                % (energy_tol, grad_rms)
            )

        text += "."
        return text

    def _draft_analysis_paragraph(
        self, records, citation_style, used_citations
    ):
        """Draft a paragraph describing analysis methods.

        Args:
            records (list): Records with analysis info.
            citation_style (str): Citation format.
            used_citations (set): Mutable set of used citation keys.

        Returns:
            str: Analysis description paragraph.
        """
        analyses = set(r.analysis_type for r in records)
        parts = []

        if "ibo" in analyses or "iao" in analyses:
            used_citations.add("iao")
            ibo_text = (
                "Intrinsic bond orbital (IBO) analysis based on "
                "intrinsic atomic orbitals (IAO) "
                "[%s] was employed to characterize chemical bonding"
                % self._cite("iao", citation_style)
            )
            parts.append(ibo_text)

        if "esp" in analyses:
            parts.append(
                "Electrostatic potential (ESP) maps were generated on "
                "the 0.002 e/Bohr^3 electron density isosurface"
            )

        if "charges" in analyses:
            parts.append(
                "Partial atomic charges were computed using the IAO "
                "population analysis scheme"
            )

        return ". ".join(parts) + "."

    def _cite(self, key, style="acs"):
        """Format a citation reference.

        Currently supports 'acs' (inline author-year) as default
        and 'nature' (reference key only). RSC style defaults to
        the ACS format. Full numbered-reference style for RSC/Nature
        would require a separate reference list builder.

        Args:
            key (str): Citation key.
            style (str): Citation style.

        Returns:
            str: Formatted citation string.
        """
        cdata = self._citations.get(key, {})
        if style == "nature":
            return cdata.get("key", key)
        # TODO: RSC numbered style requires tracking reference
        # list order. For now, use inline author-year for all.
        return cdata.get("short", key)

    def _generate_reviewer_notes(self, records):
        """Generate preemptive reviewer notes.

        Args:
            records (list): Calculation records.

        Returns:
            list: List of reviewer note strings.
        """
        notes = []

        # Check for dispersion
        has_disp = any(r.dispersion for r in records)
        if not has_disp:
            notes.append(
                "IMPORTANT: No dispersion correction was used. "
                "Reviewers commonly ask about this. Consider adding "
                "D3(BJ) correction."
            )

        # Check for basis set justification
        bases = set(r.basis for r in records)
        for b in bases:
            if "svp" in b.lower() and "tzvp" not in b.lower():
                notes.append(
                    "A double-zeta basis set (%s) was used. "
                    "Reviewers may request single-point energy "
                    "calculations with a triple-zeta basis." % b
                )

        # Check for convergence mention
        has_conv = any(r.convergence_criteria for r in records)
        if not has_conv:
            notes.append(
                "Convergence criteria are not explicitly specified. "
                "Reviewers often request this information."
            )

        return notes

```

---

## 파일: `src/qcviz_mcp/advisor/preset_recommender.py` (403줄, 13470bytes)

```python
"""
Computation Preset Recommender (F1).

Analyzes molecular structure and recommends optimal DFT calculation
settings with literature-backed justifications.

Based on:
  - Bursch et al. Angew. Chem. Int. Ed. 2022, 61, e202205735
  - Goerigk et al. Phys. Chem. Chem. Phys. 2017, 19, 32184
  - Mardirossian & Head-Gordon, Mol. Phys. 2017, 115, 2315

Version: 1.1.0
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

from qcviz_mcp.advisor.reference_data import load_functional_recommendations

__all__ = ["PresetRecommender", "PresetRecommendation"]

logger = logging.getLogger(__name__)

# Periodic table classification
_ORGANIC_ELEMENTS = frozenset([
    "H", "C", "N", "O", "F", "Cl", "Br", "S", "P", "Si", "B", "I",
])
_3D_TM = frozenset([
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
])
_4D_TM = frozenset([
    "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd",
])
# FIXED #1: La is 5d^1, stays in 5D_TM. Lanthanides (Ce-Lu) separated.
_5D_TM = frozenset([
    "La", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
])
_LANTHANIDE = frozenset([
    "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd",
    "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu",
])
_MAIN_GROUP_METALS = frozenset([
    "Li", "Na", "K", "Rb", "Cs",
    "Be", "Mg", "Ca", "Sr", "Ba",
    "Al", "Ga", "In", "Tl",
    "Ge", "Sn", "Pb",
    "As", "Sb", "Bi",
    "Se", "Te",
])
_NOBLE_GASES = frozenset(["He", "Ne", "Ar", "Kr", "Xe", "Rn"])

# All known elements for validation
_ALL_ELEMENTS = (
    _ORGANIC_ELEMENTS | _3D_TM | _4D_TM | _5D_TM
    | _LANTHANIDE | _MAIN_GROUP_METALS | _NOBLE_GASES
)

# Purpose enumeration
VALID_PURPOSES = frozenset([
    "geometry_opt",
    "single_point",
    "bonding_analysis",
    "reaction_energy",
    "spectroscopy",
    "esp_mapping",
])


@dataclass
class PresetRecommendation:
    """Result of a computation preset recommendation."""

    functional: str
    basis: str
    dispersion: Optional[str]
    spin_treatment: str
    relativistic: bool
    convergence: dict
    alternatives: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    references: list = field(default_factory=list)
    rationale: str = ""
    confidence: float = 0.0
    pyscf_settings: dict = field(default_factory=dict)


class PresetRecommender:
    """Recommends DFT computation presets based on molecular analysis.

    Analyzes a molecular structure to determine the optimal functional,
    basis set, dispersion correction, and other settings for a given
    computational purpose.

    Uses a rule-based decision tree backed by literature benchmarks
    (GMTKN55, Bursch et al. best-practice protocols).
    """

    def __init__(self):
        """Initialize the recommender with reference data."""
        self._recommendations = load_functional_recommendations()

    def recommend(
        self,
        atom_spec,
        purpose="geometry_opt",
        charge=0,
        spin=0,
    ):
        """Generate a computation preset recommendation.

        Args:
            atom_spec (str): Molecular structure in XYZ format
                (lines of 'Element x y z'). May include a 2-line
                header (atom count + comment).
            purpose (str): Calculation purpose. One of:
                geometry_opt, single_point, bonding_analysis,
                reaction_energy, spectroscopy, esp_mapping.
            charge (int): Molecular charge.
            spin (int): Spin multiplicity 2S (0=singlet, 1=doublet).

        Returns:
            PresetRecommendation: Complete recommendation with
                rationale and references.

        Raises:
            ValueError: If purpose is invalid or atom_spec is
                unparseable.
        """
        if purpose not in VALID_PURPOSES:
            raise ValueError(
                "Invalid purpose '%s'. Must be one of: %s"
                % (purpose, ", ".join(sorted(VALID_PURPOSES)))
            )

        elements = self._parse_elements(atom_spec)
        if not elements:
            raise ValueError(
                "Could not parse any atoms from atom_spec."
            )

        n_atoms = len(elements)
        unique_elements = set(elements)
        system_type = self._classify_system(
            unique_elements, n_atoms, charge, spin
        )

        rec = self._build_recommendation(
            system_type, purpose, unique_elements, n_atoms,
            charge, spin,
        )

        logger.info(
            "Recommendation for %s (%s, %d atoms): %s/%s",
            system_type, purpose, n_atoms,
            rec.functional, rec.basis,
        )

        return rec

    def _parse_elements(self, atom_spec):
        """Extract element symbols from XYZ-format atom specification.

        Handles standard XYZ format with optional 2-line header
        (atom count line + comment line).

        Args:
            atom_spec (str): XYZ format string.

        Returns:
            list: List of element symbol strings.
        """
        # FIXED #13: Robust header parsing
        elements = []
        lines = atom_spec.strip().split("\n")

        # Detect and skip XYZ header (line 1: integer atom count,
        # line 2: comment)
        start_idx = 0
        if lines and lines[0].strip().isdigit():
            start_idx = 1
            # Skip comment line too if present
            if len(lines) > 1:
                # Line 2 is always comment in standard XYZ
                start_idx = 2

        for line in lines[start_idx:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 4:
                sym = parts[0].strip()
                # Validate: first char must be alphabetic
                if not sym[0].isalpha():
                    continue
                # Capitalize properly: "FE" -> "Fe", "cl" -> "Cl"
                sym = sym[0].upper() + sym[1:].lower()
                # Validate against known elements
                if sym not in _ALL_ELEMENTS:
                    continue
                elements.append(sym)
        return elements

    def _classify_system(self, unique_elements, n_atoms, charge, spin):
        """Classify the molecular system type.

        Priority order: lanthanide > heavy_tm > 3d_tm > radical
        > charged_organic > main_group_metal > organic.
        Note: compound classifications (e.g., lanthanide + radical)
        return the highest-priority match. Radical-specific advice
        (UKS, spin contamination) is still appended as warnings
        in _build_recommendation regardless of system_type.

        Args:
            unique_elements (set): Set of unique element symbols.
            n_atoms (int): Total number of atoms.
            charge (int): Molecular charge.
            spin (int): Spin state (2S).

        Returns:
            str: System type classification. One of:
                organic_small, organic_large, 3d_tm, heavy_tm,
                lanthanide, radical, charged_organic,
                main_group_metal.
        """
        has_3d = bool(unique_elements & _3D_TM)
        has_4d = bool(unique_elements & _4D_TM)
        has_5d = bool(unique_elements & _5D_TM)
        has_lanthanide = bool(unique_elements & _LANTHANIDE)
        has_main_metal = bool(unique_elements & _MAIN_GROUP_METALS)
        is_organic = unique_elements.issubset(_ORGANIC_ELEMENTS)
        is_radical = spin > 0
        is_charged = charge != 0

        # FIXED #1: Lanthanide branch
        if has_lanthanide:
            return "lanthanide"
        if has_5d or has_4d:
            return "heavy_tm"
        if has_3d:
            return "3d_tm"
        if is_radical:
            return "radical"
        if is_charged and is_organic:
            return "charged_organic"
        if has_main_metal:
            return "main_group_metal"
        if is_organic and n_atoms <= 50:
            return "organic_small"
        if is_organic and n_atoms > 50:
            return "organic_large"
        return "organic_small"

    def _build_recommendation(
        self, system_type, purpose, unique_elements,
        n_atoms, charge, spin,
    ):
        """Build a complete recommendation from rules and reference data.

        Args:
            system_type (str): Classified system type.
            purpose (str): Calculation purpose.
            unique_elements (set): Unique element set.
            n_atoms (int): Number of atoms.
            charge (int): Charge.
            spin (int): Spin.

        Returns:
            PresetRecommendation: Complete recommendation.
        """
        # Look up recommendation rules
        rules = self._recommendations.get(system_type, {})
        purpose_rules = rules.get(purpose, rules.get("default", {}))

        functional = purpose_rules.get("functional", "B3LYP")
        basis = purpose_rules.get("basis", "def2-SVP")
        dispersion = purpose_rules.get("dispersion", "d3bj")
        refs = purpose_rules.get("references", [])
        rationale_text = purpose_rules.get("rationale", "")
        confidence = purpose_rules.get("confidence", 0.7)

        # Determine spin treatment
        if spin > 0:
            spin_treatment = "UKS"
        else:
            spin_treatment = "RKS"

        # Determine if relativistic treatment needed
        relativistic = bool(
            unique_elements & (_4D_TM | _5D_TM | _LANTHANIDE)
        )

        # Build convergence criteria
        if purpose == "geometry_opt":
            convergence = {
                "energy": 1e-8,
                "gradient_rms": 3e-4,
                "gradient_max": 4.5e-4,
                "displacement_rms": 1.2e-3,
                "displacement_max": 1.8e-3,
            }
        else:
            convergence = {
                "energy": 1e-9,
            }

        # Build warnings
        warnings = []
        if spin > 0:
            warnings.append(
                "Open-shell system detected. Check spin contamination "
                "(<S^2> value) in the output. Expected <S^2> = %.2f; "
                "deviations > 10%% suggest unreliable results."
                % (spin / 2.0 * (spin / 2.0 + 1))
            )
        if system_type == "3d_tm":
            warnings.append(
                "3d transition metal detected. B3LYP may overestimate "
                "spin-state energy splittings. Consider TPSSh as an "
                "alternative. Multiple spin states should be checked."
            )
        if system_type == "heavy_tm":
            warnings.append(
                "Heavy element detected. Scalar relativistic effects are "
                "included via effective core potentials in the def2 basis "
                "sets for elements beyond Kr."
            )
        if system_type == "lanthanide":
            warnings.append(
                "Lanthanide (4f) element detected. DFT results for "
                "lanthanides should be treated with caution. "
                "Multiconfigurational effects may be important. "
                "Scalar relativistic ECPs are included in def2 basis sets."
            )
        if n_atoms > 100:
            warnings.append(
                "Large system (%d atoms). Consider using a GGA functional "
                "(e.g., r2SCAN-3c) for geometry optimization to reduce "
                "computational cost." % n_atoms
            )
            if "hybrid" in functional.lower() or functional in (
                "B3LYP", "PBE0", "TPSSh"
            ):
                confidence *= 0.8  # Lower confidence for large + hybrid

        # Build alternatives
        alt_rules = rules.get("alternatives", [])
        alternatives = []
        for alt in alt_rules:
            alternatives.append((
                alt.get("functional", ""),
                alt.get("basis", ""),
                alt.get("rationale", ""),
            ))

        # Build PySCF settings
        pyscf_xc = functional.replace("-D3(BJ)", "").replace("-D3BJ", "")
        pyscf_xc = pyscf_xc.replace("-D3", "").replace("-D4", "")
        pyscf_xc = pyscf_xc.replace("U", "", 1) if pyscf_xc.startswith("U") else pyscf_xc
        # Common functional name mappings for PySCF
        xc_map = {
            "B3LYP": "b3lyp",
            "PBE0": "pbe0",
            "TPSSh": "tpssh",
            "PBE": "pbe",
            "TPSS": "tpss",
            "r2SCAN": "r2scan",
            "M06-2X": "m062x",
            "M062X": "m062x",
            "wB97X-D": "wb97x-d",
            "wB97X-D3": "wb97x-d3",
            "wB97X-V": "wb97x",
            "PW6B95": "pw6b95",
        }
        pyscf_xc_lower = xc_map.get(pyscf_xc, pyscf_xc.lower())

        pyscf_settings = {
            "xc": pyscf_xc_lower,
            "basis": basis.lower(),
            "charge": charge,
            "spin": spin,
            "max_cycle": 200,
            "conv_tol": convergence.get("energy", 1e-9),
        }

        rec = PresetRecommendation(
            functional=functional,
            basis=basis,
            dispersion=dispersion,
            spin_treatment=spin_treatment,
            relativistic=relativistic,
            convergence=convergence,
            alternatives=alternatives,
            warnings=warnings,
            references=refs,
            rationale=rationale_text,
            confidence=round(confidence, 2),
            pyscf_settings=pyscf_settings,
        )

        return rec

```

---

## 파일: `src/qcviz_mcp/advisor/script_generator.py` (344줄, 10611bytes)

```python
"""
Reproducibility Script Generator (F3).

Converts QCViz-MCP calculation metadata into standalone PySCF
scripts that reproduce the exact same results without requiring
the QCViz-MCP framework.

Version: 1.1.0
"""

import logging
from datetime import datetime

from qcviz_mcp.advisor.methods_drafter import CalculationRecord

__all__ = ["ReproducibilityScriptGenerator"]

logger = logging.getLogger(__name__)

_DISCLAIMER_COMMENT = (
    "# WARNING: This is a preliminary computational result generated\n"
    "# by QCViz-MCP. Results should be reviewed by a qualified\n"
    "# computational chemist before use in publications.\n"
)


def _strip_dispersion_from_functional(functional):
    """Remove dispersion correction suffixes from functional name.

    Args:
        functional (str): Functional name, possibly with D3/D4 suffix.

    Returns:
        str: Clean functional name suitable for PySCF xc parameter.
    """
    xc = functional.replace("-D3(BJ)", "")
    xc = xc.replace("-D3BJ", "").replace("-D3", "")
    xc = xc.replace("-D4", "")
    # Strip leading U for unrestricted (handled by UKS class)
    if xc.startswith("U"):
        xc = xc[1:]
    return xc


class ReproducibilityScriptGenerator:
    """Generates standalone PySCF scripts for reproducibility.

    Converts calculation metadata into self-contained Python scripts
    that can be run independently of QCViz-MCP to reproduce results.
    """

    def __init__(self):
        """Initialize the script generator."""
        pass

    def generate(self, record, include_analysis=True):
        """Generate a reproducibility script from a calculation record.

        Args:
            record (CalculationRecord): Calculation metadata.
            include_analysis (bool): Whether to include analysis code
                (IBO, charges, etc.).

        Returns:
            str: Complete Python script as a string.
        """
        sections = []

        # Header
        sections.append(self._header(record))

        # Imports
        sections.append(self._imports(record))

        # Molecule definition
        sections.append(self._molecule_def(record))

        # SCF calculation
        sections.append(self._scf_block(record))

        # Geometry optimization (if applicable)
        if record.optimizer:
            sections.append(self._geomopt_block(record))

        # Analysis (if applicable)
        if include_analysis and record.analysis_type:
            sections.append(self._analysis_block(record))

        # Results summary
        sections.append(self._results_block(record))

        return "\n".join(sections)

    def _header(self, record):
        """Generate script header with metadata.

        Args:
            record (CalculationRecord): Calculation metadata.

        Returns:
            str: Header string.
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        header = '"""\n'
        header += "Reproducibility script for QCViz-MCP calculation.\n"
        header += "System: %s\n" % record.system_name
        header += "Method: %s/%s" % (record.functional, record.basis)
        if record.dispersion:
            header += " + %s" % record.dispersion.upper()
        header += "\n"
        header += "Generated: %s\n" % now
        header += "\n"
        header += (
            "This script reproduces the calculation using only PySCF.\n"
            "No QCViz-MCP installation is required.\n"
        )
        header += '"""\n'
        header += _DISCLAIMER_COMMENT
        return header

    def _imports(self, record):
        """Generate import statements.

        Args:
            record (CalculationRecord): Calculation metadata.

        Returns:
            str: Import block string.
        """
        imports = ["from pyscf import gto, scf, dft"]

        if record.analysis_type in ("ibo", "iao"):
            imports.append("from pyscf import lo")

        if record.analysis_type == "esp":
            imports.append("from pyscf.tools import cubegen")
            imports.append("import numpy as np")

        if record.analysis_type == "charges":
            imports.append("from pyscf import lo")

        if record.optimizer:
            imports.append(
                "from pyscf.geomopt.geometric_solver import optimize"
            )

        return "\n".join(imports) + "\n"

    def _molecule_def(self, record):
        """Generate molecule definition block.

        Args:
            record (CalculationRecord): Calculation metadata.

        Returns:
            str: Molecule definition code string.
        """
        lines = []
        lines.append("# --- Molecule Definition ---")
        lines.append("mol = gto.M(")
        lines.append("    atom='''")

        # Format atom spec with proper indentation
        for line in record.atom_spec.strip().split("\n"):
            line = line.strip()
            if line and not line.isdigit():
                parts = line.split()
                if len(parts) >= 4:
                    lines.append("    %s" % line)

        lines.append("    ''',")
        lines.append("    basis='%s'," % record.basis.lower())
        lines.append("    charge=%d," % record.charge)
        lines.append("    spin=%d," % record.spin)
        lines.append(")")
        lines.append("")
        return "\n".join(lines)

    def _scf_block(self, record):
        """Generate SCF calculation block.

        Args:
            record (CalculationRecord): Calculation metadata.

        Returns:
            str: SCF code string.
        """
        lines = []
        lines.append("# --- SCF Calculation ---")

        # Determine RKS vs UKS
        if record.spin > 0:
            lines.append("mf = dft.UKS(mol)")
        else:
            lines.append("mf = dft.RKS(mol)")

        # Set functional (strip dispersion suffixes)
        xc = _strip_dispersion_from_functional(record.functional)
        lines.append("mf.xc = '%s'" % xc.lower())

        # Convergence
        lines.append("mf.conv_tol = 1e-9")
        lines.append("mf.max_cycle = 200")
        lines.append("")
        lines.append("# Run SCF")
        lines.append("mf.kernel()")
        lines.append("")
        lines.append("if not mf.converged:")
        lines.append("    print('WARNING: SCF did not converge!')")
        lines.append("")
        return "\n".join(lines)

    def _geomopt_block(self, record):
        """Generate geometry optimization block.

        Args:
            record (CalculationRecord): Calculation metadata.

        Returns:
            str: Geometry optimization code string.
        """
        # FIXED #2: Strip D3 suffix from functional in geomopt block
        xc = _strip_dispersion_from_functional(record.functional)

        lines = []
        lines.append("# --- Geometry Optimization ---")
        lines.append("# Note: optimize() returns a Mole object (PySCF >= 2.1)")
        lines.append(
            "mol_opt = optimize(mf, maxsteps=100)"
        )
        lines.append("")
        lines.append("# Update mol with optimized geometry")
        lines.append("mol = mol_opt")
        lines.append("")
        lines.append("# Re-run SCF at optimized geometry")
        if record.spin > 0:
            lines.append("mf = dft.UKS(mol)")
        else:
            lines.append("mf = dft.RKS(mol)")
        lines.append("mf.xc = '%s'" % xc.lower())
        lines.append("mf.conv_tol = 1e-9")
        lines.append("mf.kernel()")
        lines.append("")
        return "\n".join(lines)

    def _analysis_block(self, record):
        """Generate analysis code block.

        Args:
            record (CalculationRecord): Calculation metadata.

        Returns:
            str: Analysis code string.
        """
        lines = []
        analysis = record.analysis_type

        if analysis in ("ibo", "iao"):
            lines.append("# --- IBO Analysis ---")
            lines.append(
                "orbocc = mf.mo_coeff[:, mf.mo_occ > 0]"
            )
            lines.append(
                "iao_coeff = lo.iao.iao(mol, orbocc)"
            )
            lines.append(
                "ibo_coeff = lo.ibo.ibo(mol, orbocc, iaos=iao_coeff)"
            )
            lines.append("")
            lines.append(
                "print('Number of IBOs: %%d' %% ibo_coeff.shape[1])"
            )
            lines.append("")

        elif analysis == "charges":
            lines.append("# --- Charge Analysis (IAO) ---")
            lines.append(
                "orbocc = mf.mo_coeff[:, mf.mo_occ > 0]"
            )
            lines.append(
                "iao_coeff = lo.iao.iao(mol, orbocc)"
            )
            lines.append("# IAO partial charges via Mulliken on IAO basis")
            lines.append("import numpy as np")
            lines.append("S = mol.intor('int1e_ovlp')")
            lines.append(
                "dm = mf.make_rdm1()"
            )
            lines.append(
                "# Project density onto IAO basis"
            )
            lines.append(
                "iao_inv = np.linalg.pinv(iao_coeff)"
            )
            lines.append(
                "dm_iao = iao_inv @ dm @ iao_inv.T"
            )
            lines.append("")

        elif analysis == "esp":
            lines.append("# --- ESP Cube File Generation ---")
            lines.append("import numpy as np")
            lines.append(
                "cubegen.density(mol, 'density.cube', mf.make_rdm1())"
            )
            lines.append(
                "cubegen.mep(mol, 'esp.cube', mf.make_rdm1())"
            )
            lines.append("print('Generated: density.cube, esp.cube')")
            lines.append("")

        return "\n".join(lines)

    def _results_block(self, record):
        """Generate results summary block.

        Args:
            record (CalculationRecord): Calculation metadata.

        Returns:
            str: Results summary code string.
        """
        lines = []
        lines.append("# --- Results Summary ---")
        lines.append("print('=' * 60)")
        lines.append(
            "print('System: %s')" % record.system_name
        )
        lines.append(
            "print('Method: %s/%s')"
            % (record.functional, record.basis)
        )
        lines.append(
            "print('SCF Energy: %%.10f Hartree' %% mf.e_tot)"
        )
        lines.append(
            "print('SCF Energy: %%.6f eV' %% (mf.e_tot * 27.2114))"
        )
        lines.append(
            "print('Converged: %%s' %% mf.converged)"
        )
        lines.append("print('=' * 60)")
        lines.append("")
        return "\n".join(lines)

```

---

## 파일: `src/qcviz_mcp/advisor/reference_data/__init__.py` (149줄, 4050bytes)

```python
"""
Reference data loader for QCViz-MCP advisor modules.

Loads curated JSON reference databases for functional recommendations,
NIST bond lengths, GMTKN55 subsets, and DFT accuracy tables.

All data is sourced from peer-reviewed literature with DOI citations.
"""

import json
import logging
import os

__all__ = [
    "load_nist_bonds",
    "load_gmtkn55_subset",
    "load_dft_accuracy_table",
    "load_functional_recommendations",
    "normalize_func_key",
]

logger = logging.getLogger(__name__)

_DATA_DIR = os.path.dirname(os.path.abspath(__file__))

# In-memory cache to avoid repeated file reads
_CACHE = {}


def _load_json(filename):
    """Load a JSON file from the reference_data directory.

    Args:
        filename (str): JSON filename (not full path).

    Returns:
        dict: Parsed JSON content.

    Raises:
        FileNotFoundError: If the JSON file does not exist.
        json.JSONDecodeError: If the file contains invalid JSON.
    """
    if filename in _CACHE:
        return _CACHE[filename]

    filepath = os.path.join(_DATA_DIR, filename)
    if not os.path.isfile(filepath):
        logger.error("Reference data file not found: %s", filepath)
        raise FileNotFoundError(
            "Reference data file not found: %s. "
            "Ensure the qcviz_mcp package was installed correctly "
            "with reference data included." % filepath
        )
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        logger.error(
            "Invalid JSON in reference data file %s: %s",
            filepath, exc,
        )
        raise

    _CACHE[filename] = data
    return data


def normalize_func_key(functional):
    """Normalize functional name to match dft_accuracy_table.json keys.

    Strips dispersion correction suffixes, resolves Minnesota
    functional naming conventions, and uppercases the result.

    Examples:
        'B3LYP-D3(BJ)' -> 'B3LYP'
        'M06-2X-D3(0)' -> 'M062X'
        'wB97X-V'      -> 'WB97X'
        'PBE0-D3(BJ)'  -> 'PBE0'
        'TPSSh-D3(BJ)' -> 'TPSSH'
        'PW6B95-D3(BJ)'-> 'PW6B95'
        'r2SCAN'       -> 'R2SCAN'

    Args:
        functional (str): Raw functional name, possibly with
            dispersion suffixes.

    Returns:
        str: Normalized uppercase key for accuracy table lookup.
    """
    s = functional
    # Strip dispersion suffixes (longest first to avoid partial match)
    for suffix in [
        "-D3(BJ)", "-D3BJ", "-D3(0)", "-D4", "-D3", "-NL",
    ]:
        s = s.replace(suffix, "")
    # Strip -V for wB97X-V (VV10 NLC is set separately in PySCF)
    s_up = s.upper()
    if s_up.startswith("WB97X"):
        s = s.replace("-V", "").replace("-D", "")
    # Handle Minnesota functionals with internal hyphens
    _MINN_MAP = {
        "M06-2X": "M062X",
        "M06-L": "M06L",
        "M05-2X": "M052X",
        "M06-HF": "M06HF",
        "M08-HX": "M08HX",
        "M11-L": "M11L",
    }
    s_upper = s.upper()
    for pattern, replacement in _MINN_MAP.items():
        if s_upper == pattern.upper():
            return replacement
    return s_upper


def load_nist_bonds():
    """Load NIST CCCBDB experimental bond length data.

    Returns:
        dict: Molecule-keyed dictionary of bond length data.
    """
    return _load_json("nist_bonds.json")


def load_gmtkn55_subset():
    """Load GMTKN55 benchmark subset reference energies.

    Returns:
        dict: Reaction-keyed dictionary of reference energies.
    """
    return _load_json("gmtkn55_subset.json")


def load_dft_accuracy_table():
    """Load DFT method accuracy statistics from benchmarks.

    Returns:
        dict: Method-keyed dictionary of accuracy metrics.
    """
    return _load_json("dft_accuracy_table.json")


def load_functional_recommendations():
    """Load functional recommendation decision tree data.

    Returns:
        dict: System-type-keyed recommendation rules.
    """
    return _load_json("functional_recommendations.json")

```

---

## 파일: `src/qcviz_mcp/advisor/execution/cache.py` (56줄, 1661bytes)

```python
import hashlib
import json
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Any

@dataclass
class CacheEntry:
    key: str
    result: Any
    created_at: float
    ttl_seconds: float = 3600.0  # 기본 1시간

    @property
    def is_expired(self) -> bool:
        return (time.monotonic() - self.created_at) > self.ttl_seconds


class ComputationCache:
    """SCF/IBO 계산 결과의 in-memory LRU 캐시."""

    def __init__(self, max_size: int = 50, ttl_seconds: float = 3600.0):
        self._store: dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._ttl = ttl_seconds

    @staticmethod
    def make_key(tool_name: str, **params) -> str:
        """결정론적 캐시 키 생성."""
        canonical = json.dumps(
            {"tool": tool_name, **params},
            sort_keys=True,
            ensure_ascii=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.is_expired:
            del self._store[key]
            return None
        return entry.result

    def put(self, key: str, result: Any):
        if len(self._store) >= self._max_size:
            # LRU: 가장 오래된 것 제거
            oldest_key = min(self._store, key=lambda k: self._store[k].created_at)
            del self._store[oldest_key]
        self._store[key] = CacheEntry(
            key=key, result=result, created_at=time.monotonic(), ttl_seconds=self._ttl
        )

cache = ComputationCache()

```

---

## 파일: `src/qcviz_mcp/advisor/execution/worker.py` (40줄, 1345bytes)

```python
import asyncio
import concurrent.futures
import os
import functools
from typing import Callable, Any

# SCF 계산은 CPU-bound이므로 ProcessPoolExecutor 사용
# 0으로 설정하면 직접 실행 (테스트 및 단일 프로세스 환경용)
_MAX_WORKERS = int(os.environ.get("QCVIZ_MAX_WORKERS", "2"))

if _MAX_WORKERS > 0:
    _executor = concurrent.futures.ProcessPoolExecutor(
        max_workers=_MAX_WORKERS
    )
else:
    _executor = None

async def run_in_executor(func: Callable[..., Any], *args, **kwargs) -> Any:
    """CPU-bound 함수를 별도 프로세스에서 실행 (executor가 있을 경우)."""
    if _executor is None:
        return func(*args, **kwargs)

    loop = asyncio.get_running_loop()
    partial_func = functools.partial(func, *args, **kwargs)
    return await loop.run_in_executor(_executor, partial_func)


# 타임아웃 래퍼
async def run_with_timeout(func: Callable, timeout_seconds: float = 300.0,
                           *args, **kwargs) -> Any:
    """계산에 타임아웃을 적용. 기본 5분."""
    try:
        return await asyncio.wait_for(
            run_in_executor(func, *args, **kwargs),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        raise TimeoutError(
            f"Computation timed out after {timeout_seconds}s."
        )

```

---

## 파일: `src/qcviz_mcp/validation/__init__.py` (185줄, 5695bytes)

```python
"""IBO 품질 검증 모듈.

IBO 로컬라이제이션 결과의 정량적 품질 지표:
- Orbital spread (σ²)
- Molden roundtrip fidelity
- Charge method comparison
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def compute_orbital_spread(mol_obj: Any, orbital_coeff: np.ndarray) -> dict:
    """각 궤도의 공간적 퍼짐(spread, σ²)을 계산.

    σ² = <r²> - <r>² for each orbital.

    Args:
        mol_obj: PySCF Mole 객체.
        orbital_coeff: 궤도 계수 행렬 (n_ao, n_orb).

    Returns:
        dict: spreads (list[float]), mean_spread, max_spread.

    """
    # 다이폴 적분: <μ|r_α|ν>  (α = x, y, z)
    r_ints = mol_obj.intor("int1e_r", comp=3)  # shape: (3, nao, nao)

    # 쿼드러폴 (r²) 적분: <μ|r²|ν>
    # PySCF: int1e_r2 = x² + y² + z²
    r2_int = mol_obj.intor("int1e_r2")  # shape: (nao, nao)

    n_orb = orbital_coeff.shape[1]
    spreads = []

    for i in range(n_orb):
        c = orbital_coeff[:, i]
        # <r²> = c^T @ r2 @ c
        r2_expect = c @ r2_int @ c
        # <r>² = Σ_α (c^T @ r_α @ c)²
        r_expect_sq = sum((c @ r_ints[a] @ c) ** 2 for a in range(3))
        spread = float(r2_expect - r_expect_sq)
        spreads.append(max(spread, 0.0))  # 수치 오차로 음수 방지

    return {
        "spreads": spreads,
        "mean_spread": float(np.mean(spreads)),
        "max_spread": float(np.max(spreads)),
    }


def verify_molden_roundtrip(
    mol_obj: Any, original_coeff: np.ndarray, molden_path: str
) -> dict:
    """Molden export → re-import → 계수 비교.

    Returns:
        dict: frobenius_norm, max_abs_diff, passed (bool).

    """
    from pyscf.tools import molden

    mol2, mo_energy, mo_coeff, mo_occ, irrep_labels, spins = molden.load(molden_path)

    if mo_coeff is None:
        return {
            "frobenius_norm": float("inf"),
            "max_abs_diff": float("inf"),
            "passed": False,
        }
    if mo_coeff.ndim == 1:
        mo_coeff = mo_coeff.reshape(-1, 1)
    if mo_coeff is None:
        return {
            "frobenius_norm": float("inf"),
            "max_abs_diff": float("inf"),
            "passed": False,
        }
    if mo_coeff.ndim == 1:
        mo_coeff = mo_coeff.reshape(-1, 1)
    n_orb = min(original_coeff.shape[1], mo_coeff.shape[1])

    # 부호 자유도 보정: 각 열의 최대 절대값 원소의 부호를 맞춤
    orig = original_coeff[:, :n_orb].copy()
    loaded = mo_coeff[:, :n_orb].copy()

    for i in range(n_orb):
        if np.dot(orig[:, i], loaded[:, i]) < 0:
            loaded[:, i] *= -1

    diff = orig - loaded
    frob = float(np.linalg.norm(diff, "fro"))
    max_abs = float(np.max(np.abs(diff)))

    return {
        "frobenius_norm": frob,
        "max_abs_diff": max_abs,
        "passed": frob < 1e-6,
    }


def compare_charges(charges_a: np.ndarray, charges_b: np.ndarray) -> dict:
    """두 전하 세트 간 일관성 비교.

    Returns:
        dict: correlation, max_diff, sign_agreement (0-1).

    """
    if len(charges_a) != len(charges_b):
        return {"correlation": 0.0, "max_diff": float("inf"), "sign_agreement": 0.0}

    corr = float(np.corrcoef(charges_a, charges_b)[0, 1]) if len(charges_a) > 1 else 1.0
    max_diff = float(np.max(np.abs(charges_a - charges_b)))
    sign_match = np.sum(np.sign(charges_a) == np.sign(charges_b))
    sign_agree = float(sign_match / len(charges_a))

    return {
        "correlation": corr,
        "max_diff": max_diff,
        "sign_agreement": sign_agree,
    }


# ── Phase η-4: 기저 함수 독립성 검증 ──


def verify_basis_independence(molecule_name: str, results_by_basis: dict) -> dict:
    """여러 기저의 IBO 결과를 비교하여 기저 독립성 검증."""
    if len(results_by_basis) < 2:
        return {
            "ibo_count_invariant": True,
            "charge_conservation": True,
            "charge_deviation_ok": True,
            "max_charge_deviation": 0.0,
            "ibo_counts": {b: r["n_ibo"] for b, r in results_by_basis.items()},
            "all_passed": True,
        }

    ibo_counts = {b: r["n_ibo"] for b, r in results_by_basis.items()}
    ibo_invariant = len(set(ibo_counts.values())) == 1

    charge_conservation = True
    for b, r in results_by_basis.items():
        if "charges" in r and r["charges"] is not None:
            if abs(float(np.sum(r["charges"]))) >= 1e-4:
                charge_conservation = False

    charge_arrays = [
        r["charges"]
        for r in results_by_basis.values()
        if "charges" in r and r["charges"] is not None
    ]
    max_deviation = 0.0
    if len(charge_arrays) >= 2:
        for i in range(len(charge_arrays)):
            for j in range(i + 1, len(charge_arrays)):
                if len(charge_arrays[i]) == len(charge_arrays[j]):
                    dev = float(np.max(np.abs(charge_arrays[i] - charge_arrays[j])))
                    max_deviation = max(max_deviation, dev)

    charge_deviation_ok = max_deviation < 0.15
    all_passed = ibo_invariant and charge_conservation and charge_deviation_ok
    logger.info(
        "%s basis independence: %s (maxΔq=%.4f, IBO=%s)",
        molecule_name,
        "PASS" if all_passed else "FAIL",
        max_deviation,
        ibo_counts,
    )

    return {
        "ibo_count_invariant": ibo_invariant,
        "charge_conservation": charge_conservation,
        "charge_deviation_ok": charge_deviation_ok,
        "max_charge_deviation": max_deviation,
        "ibo_counts": ibo_counts,
        "all_passed": all_passed,
    }

```

---

## 파일: `src/qcviz_mcp/utils/__init__.py` (6줄, 165bytes)

```python
"""유틸리티 패키지.

일반적인 헬퍼 함수, 로깅 설정, 예외 처리 클래스 등을 포함합니다.
"""

from __future__ import annotations

```

---

## 파일: `src/qcviz_mcp/execution/__init__.py` (5줄, 114bytes)

```python
"""Execution compatibility package for legacy imports."""

from .worker import _executor

__all__ = ["_executor"]

```

---

## 파일: `src/qcviz_mcp/execution/cache.py` (13줄, 266bytes)

```python
"""Execution cache shim module."""

class _FallbackCache:
    def get(self, key):
        return None
    def set(self, key, value, ttl=None):
        pass
    def clear(self):
        pass
    def __call__(self, func):
        return func

cache = _FallbackCache()

```

---

## 파일: `src/qcviz_mcp/execution/worker.py` (29줄, 682bytes)

```python
"""Compatibility worker module.

Some older parts of QCViz import:
    from qcviz_mcp.execution.worker import _executor

This shim provides an in-process ThreadPoolExecutor so legacy imports
keep working even if the old execution package is absent.
"""

from __future__ import annotations

import atexit
import os
from concurrent.futures import ThreadPoolExecutor

_MAX_WORKERS = max(4, min(32, (os.cpu_count() or 4) * 2))

_executor = ThreadPoolExecutor(
    max_workers=_MAX_WORKERS,
    thread_name_prefix="qcviz-exec",
)


@atexit.register
def _shutdown_executor() -> None:
    try:
        _executor.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass

```

---

## 파일: `src/qcviz_mcp/renderers/__init__.py` (31줄, 703bytes)

```python
"""Rendering utilities — Phase η: 자동 선택 로직."""


def get_best_renderer() -> str:
    try:
        import pyvista  # noqa: F401

        return "pyvista"
    except ImportError:
        pass
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401

        return "playwright"
    except ImportError:
        pass
    return "html_only"


try:
    from qcviz_mcp.renderers.pyvista_renderer import (  # noqa: F401
        is_available as pyvista_available,
    )
    from qcviz_mcp.renderers.pyvista_renderer import (
        render_from_cube_string,
        render_orbital_png,
    )

    HAS_PYVISTA = pyvista_available()
except ImportError:
    HAS_PYVISTA = False

```

---

## 파일: `src/qcviz_mcp/renderers/png_exporter.py` (92줄, 2888bytes)

```python
"""헤드리스 PNG 내보내기.
Playwright + Chromium + SwiftShader로 py3Dmol HTML → PNG 캡처.

선택적 의존성: pip install playwright && playwright install chromium
"""

import asyncio
from pathlib import Path


async def html_to_png(
    html_path: str,
    png_path: str | None = None,
    width: int = 800,
    height: int = 600,
    wait_ms: int = 3000,
    timeout_ms: int = 30000,
) -> dict:
    """HTML 파일을 PNG로 캡처.

    Args:
        html_path: py3Dmol HTML 파일 경로.
        png_path: 출력 PNG 경로. None이면 자동 생성.
        width: 뷰포트 너비 (px).
        height: 뷰포트 높이 (px).
        wait_ms: 3Dmol.js 렌더링 대기 (ms).
        timeout_ms: 전체 타임아웃 (ms).

    Returns:
        dict: {success, png_path, width, height, file_size_bytes, error}.

    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {
            "success": False,
            "error": (
                "Playwright not installed. "
                "Run: pip install playwright && playwright install chromium"
            ),
        }

    if png_path is None:
        png_path = str(Path(html_path).with_suffix(".png"))

    html_uri = Path(html_path).resolve().as_uri()

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--enable-gpu",
                    "--use-angle=swiftshader-webgl",
                    "--enable-unsafe-swiftshader",
                    "--no-sandbox",
                ],
            )
            context = await browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=2,
            )
            page = await context.new_page()
            await page.goto(html_uri, timeout=timeout_ms)
            await page.wait_for_timeout(wait_ms)

            canvas_ok = await page.evaluate(
                "() => { const c = document.querySelector('canvas'); "
                "return c !== null && c.width > 0; }"
            )
            if not canvas_ok:
                await page.wait_for_timeout(wait_ms * 2)

            await page.screenshot(path=png_path, type="png")
            await browser.close()

        file_size = Path(png_path).stat().st_size
        return {
            "success": True,
            "png_path": png_path,
            "width": width * 2,
            "height": height * 2,
            "file_size_bytes": file_size,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def html_to_png_sync(html_path: str, **kwargs) -> dict:
    """동기 래퍼."""
    return asyncio.run(html_to_png(html_path, **kwargs))

```

---

## 파일: `src/qcviz_mcp/renderers/pyvista_renderer.py` (129줄, 3319bytes)

```python
"""PyVista 기반 네이티브 오비탈 렌더러. 브라우저 불필요."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

try:
    import pyvista as pv

    _HAS_PYVISTA = True
except ImportError:
    _HAS_PYVISTA = False


def is_available() -> bool:
    return _HAS_PYVISTA


def cube_to_pyvista_grid(cube_data, origin, axes, npts):
    if not _HAS_PYVISTA:
        raise ImportError("PyVista not installed")
    spacing = tuple(
        float(np.linalg.norm(ax) / max(n - 1, 1)) for ax, n in zip(axes, npts)
    )
    grid = pv.ImageData(dimensions=npts, spacing=spacing, origin=origin)
    grid["orbital"] = cube_data.flatten(order="F")
    return grid


def render_orbital_png(
    cube_data,
    origin,
    axes,
    npts,
    output_path="orbital.png",
    isovalue=0.02,
    window_size=(1920, 1080),
    colors=("blue", "red"),
    background="white",
    show_atoms=None,
) -> str:
    if not _HAS_PYVISTA:
        raise ImportError("PyVista not installed")
    pv.OFF_SCREEN = True
    grid = cube_to_pyvista_grid(cube_data, origin, axes, npts)
    pl = pv.Plotter(off_screen=True, window_size=window_size)
    pl.background_color = background
    try:
        pos = grid.contour([isovalue], scalars="orbital")
        if pos.n_points > 0:
            pl.add_mesh(pos, color=colors[0], opacity=0.6, smooth_shading=True)
    except Exception:
        pass
    try:
        neg = grid.contour([-isovalue], scalars="orbital")
        if neg.n_points > 0:
            pl.add_mesh(neg, color=colors[1], opacity=0.6, smooth_shading=True)
    except Exception:
        pass
    if show_atoms:
        _C = {
            "H": "white",
            "C": "gray",
            "N": "blue",
            "O": "red",
            "F": "green",
            "Fe": "orange",
            "Ti": "silver",
            "Zr": "teal",
            "Mo": "purple",
        }
        for sym, coord in show_atoms:
            pl.add_mesh(
                pv.Sphere(radius=0.3, center=coord),
                color=_C.get(sym, "gray"),
                opacity=1.0,
            )
    pl.camera_position = "iso"
    pl.camera.zoom(1.3)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    pl.screenshot(output_path)
    pl.close()
    logger.info(
        "PyVista PNG: %s (%d bytes)", output_path, Path(output_path).stat().st_size
    )
    return output_path


def render_from_cube_string(
    cube_text,
    output_path="orbital.png",
    isovalue=0.02,
    window_size=(1920, 1080),
    colors=("blue", "red"),
    background="white",
) -> str:
    from qcviz_mcp.backends.pyscf_backend import parse_cube_string

    parsed = parse_cube_string(cube_text)
    _Z = {
        1: "H",
        6: "C",
        7: "N",
        8: "O",
        9: "F",
        16: "S",
        22: "Ti",
        26: "Fe",
        40: "Zr",
        42: "Mo",
    }
    atoms = [(_Z.get(z, "X"), [x, y, zc]) for z, x, y, zc in parsed["atoms"]]
    return render_orbital_png(
        parsed["data"],
        parsed["origin"],
        parsed["axes"],
        parsed["npts"],
        output_path=output_path,
        isovalue=isovalue,
        window_size=window_size,
        colors=colors,
        background=background,
        show_atoms=atoms,
    )

```

---

## 전체 디렉토리 구조

```
./.pytest_cache/.gitignore
./.pytest_cache/CACHEDIR.TAG
./.pytest_cache/README.md
./.pytest_cache/v/cache/lastfailed
./.pytest_cache/v/cache/nodeids
./.ruff_cache/.gitignore
./.ruff_cache/0.15.4/10151179862715634403
./.ruff_cache/0.15.4/10854478206462414267
./.ruff_cache/0.15.4/14675199373438139475
./.ruff_cache/0.15.4/4019606712721790400
./.ruff_cache/0.15.4/7394988735849463560
./.ruff_cache/CACHEDIR.TAG
./AUDIT_REPORT.md
./FULL_CODE_AUDIT.md
./README.md
./docs/20260308.0100.v5고도화.작업지시프롬프트.md
./docs/20260308.0200.전수조사_작업지시서.md
./docs/20260308.0226.v5_사용시나리오.md
./docs/20260310.2322.01.md
./docs/20260310_수정7.md
./docs/20260310_수정요구사항1.md
./docs/20260310_수정요구사항2.md
./docs/20260310_수정요구사항3.md
./docs/20260310_수정요구사항4.md
./docs/20260310_수정요구사항5.md
./docs/20260310_수정요구사항6.md
./docs/DIAGNOSTIC_AND_REPAIR_PROMPT.md
./docs/PROMPT_ADVANCED_FEATURES.md
./docs/PROMPT_ADVANCED_FEATURES_LOADING.md
./docs/PROMPT_BACKEND_UPGRADE.md
./docs/PROMPT_FIX_COLOR_CHARGES.md
./docs/PROMPT_FIX_COLOR_SCHEME.md
./docs/PROMPT_FIX_ESP_COLOR_FINAL.md
./docs/PROMPT_FIX_ESP_TOGGLE.md
./docs/PROMPT_FIX_MOLCHAT_API.md
./docs/PROMPT_FIX_VIEWER.md
./docs/PROMPT_FIX_VIEWER_SCROLL_UI.md
./docs/PROMPT_UI_UPGRADE.md
./docs/SUMMARY_AND_PROMPT.md
./docs/SUMMARY_OF_REQUESTS.md
./docs/TOTAL_DIAGNOSIS_AND_FIX_PROMPT.md
./docs/VERSION02_ULTIMATE_AUDIT_PROMPT.md
./docs/VERSION02_ULTIMATE_AUDIT_PROMPT.result01.md
./docs/VERSION02_ULTIMATE_AUDIT_PROMPT.result02.md
./docs/VERSION02_ULTIMATE_AUDIT_PROMPT.result03.md
./docs/VERSION02_ULTIMATE_AUDIT_PROMPT.작업지시..md
./docs/audit/00-context-prompt.md
./docs/audit/R1-A-backend-pyscf-runner.md
./docs/audit/R1-B-backend-compute.md
./docs/audit/R1-C-agent-llm.md
./docs/audit/R1-D-frontend-results.md
./docs/audit/R1-E-frontend-viewer.md
./docs/audit/R1-F-frontend-chat.md
./docs/audit/R1-G-frontend-app.md
./docs/audit/R1-H-cross-module-contract.md
./docs/audit/R2-A-data-contract.md
./docs/audit/R2-B-error-propagation.md
./docs/audit/R2-C-concurrency-state.md
./docs/audit/R2-D-memory-performance.md
./docs/audit/R2-E-code-dedup.md
./docs/audit/R2-F-ux-security.md
./docs/audit/R3-A-architecture.md
./docs/audit/R3-D-dom-js-css.md
./docs/audit/R3-E-event-bus.md
./docs/audit/R3-P-defensive-programming.md
./docs/audit/R3-R-e2e-trace.md
./docs/audit/R3-S-semantic-correctness.md
./docs/audit/R3-W-websocket-protocol.md
./docs/재검증프롬프트.md
./generate_v3_context.sh
./output/Water_dashboard.html
./output/h2o_visualization.html
./pyproject.toml
./pytest.ini
./requirements.txt
./src/qcviz_mcp.egg-info/PKG-INFO
./src/qcviz_mcp.egg-info/SOURCES.txt
./src/qcviz_mcp.egg-info/dependency_links.txt
./src/qcviz_mcp.egg-info/requires.txt
./src/qcviz_mcp.egg-info/top_level.txt
./src/qcviz_mcp/__init__.py
./src/qcviz_mcp/advisor/__init__.py
./src/qcviz_mcp/advisor/confidence_scorer.py
./src/qcviz_mcp/advisor/execution/cache.py
./src/qcviz_mcp/advisor/execution/worker.py
./src/qcviz_mcp/advisor/literature_validator.py
./src/qcviz_mcp/advisor/methods_drafter.py
./src/qcviz_mcp/advisor/preset_recommender.py
./src/qcviz_mcp/advisor/reference_data/__init__.py
./src/qcviz_mcp/advisor/reference_data/dft_accuracy_table.json
./src/qcviz_mcp/advisor/reference_data/functional_recommendations.json
./src/qcviz_mcp/advisor/reference_data/gmtkn55_subset.json
./src/qcviz_mcp/advisor/reference_data/nist_bonds.json
./src/qcviz_mcp/advisor/script_generator.py
./src/qcviz_mcp/analysis/__init__.py
./src/qcviz_mcp/analysis/charge_transfer.py
./src/qcviz_mcp/analysis/fragment_detector.py
./src/qcviz_mcp/analysis/sanitize.py
./src/qcviz_mcp/app.py
./src/qcviz_mcp/backends/__init__.py
./src/qcviz_mcp/backends/ase_backend.py
./src/qcviz_mcp/backends/base.py
./src/qcviz_mcp/backends/cclib_backend.py
./src/qcviz_mcp/backends/pyscf_backend.py
./src/qcviz_mcp/backends/registry.py
./src/qcviz_mcp/backends/viz_backend.py
./src/qcviz_mcp/compute/disk_cache.py
./src/qcviz_mcp/compute/job_manager.py
./src/qcviz_mcp/compute/pyscf_runner.py
./src/qcviz_mcp/compute/safety_guard.py
./src/qcviz_mcp/config.py
./src/qcviz_mcp/errors.py
./src/qcviz_mcp/execution/__init__.py
./src/qcviz_mcp/execution/cache.py
./src/qcviz_mcp/execution/worker.py
./src/qcviz_mcp/llm/__init__.py
./src/qcviz_mcp/llm/agent.py
./src/qcviz_mcp/llm/bridge.py
./src/qcviz_mcp/llm/prompts.py
./src/qcviz_mcp/llm/providers.py
./src/qcviz_mcp/llm/rule_provider.py
./src/qcviz_mcp/llm/schemas.py
./src/qcviz_mcp/log_config.py
./src/qcviz_mcp/mcp_server.py
./src/qcviz_mcp/observability.py
./src/qcviz_mcp/renderers/__init__.py
./src/qcviz_mcp/renderers/png_exporter.py
./src/qcviz_mcp/renderers/pyvista_renderer.py
./src/qcviz_mcp/security.py
./src/qcviz_mcp/tools/__init__.py
./src/qcviz_mcp/tools/advisor_tools.py
./src/qcviz_mcp/tools/core.py
./src/qcviz_mcp/tools/health.py
./src/qcviz_mcp/utils/__init__.py
./src/qcviz_mcp/validation/__init__.py
./src/qcviz_mcp/web/advisor_flow.py
./src/qcviz_mcp/web/app.py
./src/qcviz_mcp/web/routes/chat.py
./src/qcviz_mcp/web/routes/compute.py
./src/qcviz_mcp/web/static/app.js
./src/qcviz_mcp/web/static/app.js.bak
./src/qcviz_mcp/web/static/auto_fit.md
./src/qcviz_mcp/web/static/bugfix_bundle.md
./src/qcviz_mcp/web/static/chat.js
./src/qcviz_mcp/web/static/chat.js.bak
./src/qcviz_mcp/web/static/create_bundle.py
./src/qcviz_mcp/web/static/debug_history.py
./src/qcviz_mcp/web/static/qcviz_context_bundle.md
./src/qcviz_mcp/web/static/results.js
./src/qcviz_mcp/web/static/results.js.bak
./src/qcviz_mcp/web/static/style.css
./src/qcviz_mcp/web/static/style.css.bak
./src/qcviz_mcp/web/static/viewer.js
./src/qcviz_mcp/web/static/viewer.js.bak
./src/qcviz_mcp/web/templates/index.html
./src/qcviz_mcp/web/templates/index.html.bak
./start_server.sh
./test_3dmol.html
./test_init.js
./test_orbital_cache.py
./test_viewer_js.js
./tests/conftest.py
./tests/test_advisor_drafter.py
./tests/test_advisor_new.py
./tests/test_advisor_preset.py
./tests/test_advisor_scorer.py
./tests/test_advisor_script.py
./tests/test_advisor_validator.py
./tests/test_api_v2.py
./tests/test_app_and_aliases.py
./tests/test_chat_api.py
./tests/test_compute_api.py
./tests/test_job_manager.py
./tests/test_korean_parsing.py
./tests/test_real_pyscf_integration.py
./tests/test_result_contract.py
./tests/test_run_geometry_optimization.py
./tests/test_structure_extraction.py
./v3_patch_context.md
```
