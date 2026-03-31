# 🛠️ QCViz-MCP v5: 분자 구조 파싱 오류 및 MolChat API 연동 점검 작업 지시서

현재 시스템에서 사용자가 자연어로 분자 구조 시각화를 요청할 때, 분자 이름이 제대로 파싱되지 않아 외부 API(PubChem 및 MolChat) 조회에서 404 에러가 발생하며 전체 파이프라인이 중단되는 심각한 버그가 보고되었습니다.

아래 에러 로그와 원인 분석을 읽고 백엔드 코드(`core.py` 및 `compute.py`)를 개선해 주세요.

---

## 🛑 문제 상황: 자연어 쿼리 404 에러 및 구조 해석 실패

**에러 로그:**
```text
Could not resolve structure 'the HOMO orbital of formaldehyde': 분자 구조를 확보하지 못했습니다. XYZ 좌표를 직접 제공하거나, 인식 가능한 분자명/SMILES를 입력해 주세요. 원인: 분자 이름 'the HOMO orbital of formaldehyde'을(를) SMILES로 변환하지 못했습니다: HTTP Error 404: PUGREST.NotFound
```

**상황 분석:**
사용자가 "Show the HOMO orbital of formaldehyde"라고 입력했을 때, 백엔드의 Heuristic Planner가 이 문장 속에서 "formaldehyde"라는 분자 이름만 추출해내지 못하고 `"the HOMO orbital of formaldehyde"`라는 문장 통째로 `MoleculeResolver`에 넘겨버렸습니다.
PubChem API는 당연히 저런 긴 이름의 화학물질을 알지 못하므로 404 Not Found를 반환했고, 뒤이어 3D 구조를 생성해주는 **MolChat API (`http://psid.aizen.co.kr/molchat/api/v1/molecules/generate-3d`)** 까지 넘어가지도 못하고 실패했습니다.

---

## ✅ 해결 요구사항 (Action Items)

### 1. `MoleculeResolver`의 Noise 필터링 강화 (`core.py`)
현재 `MoleculeResolver`로 넘어오는 인자가 완전히 정제되지 않을 수 있음을 감안하여, `PubChem` API를 호출하기 직전에 문자열에서 자연어 노이즈("the", "orbital", "homo", "of" 등)를 제거하는 최후의 방어선을 구축해야 합니다.

### 2. MolChat API 연동 상태 점검 및 예외 처리 강화 (`core.py`)
현재 QCViz-MCP는 다음 2단계 구조를 갖습니다.
1. 분자명 -> PubChem API -> Canonical SMILES 획득
2. SMILES -> MolChat API (`/molecules/generate-3d`) -> 3D XYZ 좌표 획득

MolChat API 호출 자체는 정상적으로 작동하고 있으나, 간혹 MolChat API 서버가 죽어있거나 응답이 지연될 때를 대비해 타임아웃을 늘리거나 명확한 에러 메시지(예: `MolChat API 서버 장애: 3D 구조 생성 불가`)를 프론트엔드로 전달하도록 예외 처리를 고도화하세요.

---

## 📄 참고 코드 컨텍스트 (수정 대상)

### `version02/src/qcviz_mcp/tools/core.py` (PubChem 및 MolChat 연동부)

```python
    @classmethod
    def _resolve_name_to_smiles(cls, name: str) -> str:
        # ❌ 현재 로직: name이 "the HOMO orbital of formaldehyde"로 들어오면 그대로 API에 전송됨
        # 💡 지시사항: 여기서 정규식을 사용해 노이즈를 걷어내는 로직을 추가하세요.
        import re
        clean_name = re.sub(r"(?i)\b(?:the|of|orbital|homo|lumo|mo|esp|map|charge|charges|mulliken|partial)\b", "", name).strip()
        quoted = urllib.parse.quote(clean_name, safe="")
        
        direct_url = (
            f"{cls.PUBCHEM_BASE}/compound/name/{quoted}/property/CanonicalSMILES,IsomericSMILES/JSON"
        )
        # ... (API 호출)

    @classmethod
    def _generate_xyz_via_molchat(cls, smiles: str) -> str:
        """SMILES를 받아 Aizen MolChat API를 통해 3D XYZ 구조를 반환"""
        url = f"{cls.MOLCHAT_BASE}/molecules/generate-3d"
        payload = json.dumps({"smiles": smiles}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            # 💡 지시사항: 타임아웃을 넉넉히(예: 30초) 주고, 에러 시 명확하게 로깅하세요.
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                # ...
```

### `version02/src/qcviz_mcp/web/routes/compute.py` (NLP 파서 수정 필요)
```python
def _fallback_extract_structure_query(message: str) -> Optional[str]:
    # 💡 지시사항: 이 함수 내의 정규식 패턴들이 "Show the HOMO orbital of formaldehyde"에서
    # 정확히 "formaldehyde" 1단어만 뽑아내도록 정규표현식 매칭 그룹을 수정하세요.
    patterns = [
        r"(?i)(?:for|of|on|about)\s+(?:the\s+)?([a-zA-Z][a-zA-Z0-9_\- ]{1,40})",
        # ...
    ]
```

이 지시서를 통해 다른 LLM이 PubChem API 404 문제를 해결하고 MolChat 기반 3D 생성 파이프라인을 견고하게 만들 수 있도록 수정된 코드를 제시받으세요.