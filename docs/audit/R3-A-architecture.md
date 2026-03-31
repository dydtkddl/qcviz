---
audit_round: 3
category: A (Architecture)
priority: P3
related_files: [compute.py, pyscf_runner.py]
defects: "A1/A2 Multi-worker 문서화, A7 단위 테스트 케이스 목록"
---

# R3-A: 아키텍처

> 3차 감사 | Perspective 7 | 문서화 2건

---

## A1/A2: Multi-worker 문서화 — **P3**

현재 아키텍처는 **단일 worker**를 전제로 설계되었습니다.

```bash
# 서버 시작 시 권장 설정:
uvicorn qcviz_mcp.web.app:app --workers 1 --host 0.0.0.0 --port 8000
```

### Multi-worker 환경의 문제점

| 문제                         | 원인                              | 영향                           |
| ---------------------------- | --------------------------------- | ------------------------------ |
| Job 조회 불가                | `InMemoryJobManager`는 프로세스별 | worker A의 job을 B에서 못 찾음 |
| WebSocket progress 수신 불가 | WS 연결은 특정 worker에 바인딩    | 다른 worker의 이벤트 미수신    |
| SCF cache 히트율 감소        | `_SCF_CACHE`도 프로세스별         | 캐시 히트율 ∝ 1/workers        |

### 장기 마이그레이션 방향

- Redis 기반 job store (`rq` 또는 `celery`)
- Redis pub/sub 기반 WebSocket broadcast
- Redis 기반 SCF 결과 캐시

---

## A7: 단위 테스트 케이스 목록 — **P3**

| #   | 함수                         | 테스트 케이스                                              |
| --- | ---------------------------- | ---------------------------------------------------------- |
| 1   | `_normalize_method_name`     | "b3lyp"→"B3LYP", "HF"→"HF", "m062x"→"M06-2X", None→"B3LYP" |
| 2   | `_normalize_basis_name`      | "6-31g*"→"6-31G*", "def2svp"→"def2-SVP", None→"def2-SVP"   |
| 3   | `_normalize_esp_preset`      | "acs"→"acs", "grayscale"→"greyscale", ""→"acs"             |
| 4   | `_looks_like_xyz`            | 유효 XYZ, 빈 문자열, 숫자만, None                          |
| 5   | `_strip_xyz_header`          | header 있는 XYZ, header 없는 XYZ, 빈 문자열                |
| 6   | `_formula_from_symbols`      | ["C","H","H","H","H"]→"CH4", ["O","H","H"]→"H2O"           |
| 7   | `_guess_bonds`               | water (2 bonds), methane (4 bonds), single atom (0)        |
| 8   | `_resolve_orbital_selection` | "HOMO", "LUMO", "HOMO-2", "LUMO+3", "5" (1-based)          |
| 9   | `_compute_esp_auto_range`    | 정상 배열, 빈 배열, 모두 NaN, 극성 큰 값                   |
| 10  | `_finalize_result_contract`  | 빈 dict, 에너지만 있는 dict, NaN 에너지                    |

---

## 3차 감사 전체 결함 요약 및 우선순위

| #   | Perspective | ID    | 설명                          | 심각도 |
| --- | ----------- | ----- | ----------------------------- | ------ |
| 1   | 시맨틱      | S6    | isovalue 모드별 분리          | **P0** |
| 2   | DOM         | D2    | `grpESP` DOM 미존재           | **P0** |
| 3   | 이벤트      | E3    | `result:cleared` 미처리       | **P0** |
| 4   | WS          | W5    | progress 0~1 vs 0~100         | **P0** |
| 5   | 시맨틱      | S1/S2 | orbital index 0/1-based 혼용  | **P1** |
| 6   | 시맨틱      | S5    | `_COVALENT_RADII` 누락        | **P1** |
| 7   | 방어        | P2    | 미지원 method 조용한 fallback | **P1** |
| 8   | 방어        | P5    | orbitals sort 방어            | **P1** |
| 9   | 방어        | P8    | berny callback 호환           | **P1** |
| 10  | 복원        | R3    | 연속 계산 progress 혼동       | **P1** |
| 11  | IVS-4       | —     | 에러 후 status 영구 고착      | **P1** |
| 12  | 시맨틱      | S4    | ESP range clipping 상한       | **P2** |
| 13  | DOM         | D5    | `chat-msg--system` CSS        | **P2** |
| 14  | 아키텍처    | A1/A2 | multi-worker 문서화           | **P3** |

**P0 수정 4건, P1 수정 7건, P2 수정 2건, P3 문서화 1건.**

1차~3차 총 **44건**의 결함 식별 및 수정 완료.

---

→ [00-context-prompt.md](00-context-prompt.md) 참조
