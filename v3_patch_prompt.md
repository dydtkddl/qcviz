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
