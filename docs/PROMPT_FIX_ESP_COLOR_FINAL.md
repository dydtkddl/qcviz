# 🛠️ QCViz-MCP v5: ESP 렌더링 무반응(TypeError) 및 Color Scheme 완벽 해결 & Charge 시각화 고도화 작업 지시서

현재 3D 뷰어와 결과 패널에서 아래 3가지 이슈를 해결하고 고도화해야 합니다. 특히 ESP 버튼이 "먹통"이 된 근본적인 원인(3Dmol.js API 호환성)을 정확히 수정해야 합니다. 

---

## 🛑 요구사항 1: ESP 토글 먹통(무반응) 현상 및 Color Scheme 렌더링 버그 수정
**문제 상황:** 하단의 `selectColorScheme`에서 테마를 바꾸면 오비탈은 바뀌는데 ESP 버튼을 누르면 아무 반응이 없거나 백지 상태가 됩니다(먹통).
**원인 분석:** 이전 패치에서 `volscheme`에 Gradient 객체(`new $3Dmol.Gradient...`)를 직접 넣거나 잘못된 `createGradient` 함수를 매핑하면서 3Dmol.js 내부에서 `TypeError`가 발생해 렌더링이 조용히 중단(try-catch에 먹힘)되고 있었습니다. 3Dmol.js에서 볼륨 데이터를 바탕으로 다른 볼륨 데이터의 표면에 색상을 입힐 때의 올바른 API는 `colorschememap`과 `colorscheme` 객체(문자열 매핑)를 사용하는 것입니다.

**해결 지시:**
`viewer.js` 내의 `renderESP`와 `switchVizMode("esp")` 분기를 찾아, `voldata` / `volscheme`을 사용하던 잘못된 코드를 걷어내고 다음과 같은 3Dmol.js 공식 구문으로 전면 수정하세요.

```javascript
          viewer.addIsosurface(densVol, {
            isoval: espDensityIso, // 또는 state.espDensityIso
            colorschememap: espVol, // 매핑할 대상 볼륨 데이터
            colorscheme: { gradient: scheme.espGradient, min: minVal, max: maxVal }, // "rwb" 등의 문자열 그라디언트
            alpha: state.opacity,
            smoothness: 3
          });
```

## 🛑 요구사항 2: 원자 라벨(Atom Label)에 전하량별(+/-) 색상 부여
**문제 상황:** 현재 3D 뷰어에서 Labels를 켜면 모두 동일한 배경색(흑/백)으로 나옵니다.
**지시:** `viewer.js`의 `addLabels(viewer, result)` 함수를 전면 수정하세요. 
- 해당 원자의 전하(`charge`) 값이 **양수(+)이면 파란색 계열**, **음수(-)이면 빨간색 계열**의 배경색/글자색이 지정되도록 합니다.
- 전하량의 절대값 크기에 따라 색상의 진하기(투명도, alpha)를 `0.25 ~ 0.8` 사이로 비례하게(Intensity 정규화) 적용하여 직관성을 더하세요.

## 🛑 요구사항 3: Charges 탭 버터플라이 차트(Butterfly Chart) 시각화 + 여백 및 눈금 추가
**문제 상황:** `results.js`의 `renderCharges(r)` 함수가 표(Table) 형태로만 되어 있어 가독성이 떨어지며, 이전 구현 시 막대가 끝까지 차버려 답답했습니다.
**지시:** `results.js`의 `renderCharges` 함수를 수정하여 수평 버터플라이 차트(Butterfly Chart)를 구현하세요.
- 0을 기준으로 양수(+)는 오른쪽 파란색 막대, 음수(-)는 왼쪽 빨간색 막대.
- `plotMax`를 `maxAbs * 1.15` 등으로 설정하여 **막대가 닿지 않도록 양옆에 15% 여백(Margin)**을 주세요.
- 차트 상단/하단에 `-max`, `-half`, `0`, `+half`, `+max` 를 표시하는 **X축 눈금(Ticks)** HTML/CSS 구조를 추가하세요.

---

## 📄 참고 코드 컨텍스트 (수정 대상)

### 1. `viewer.js` (문제의 ESP 렌더링 부분)
```javascript
// 현재 에러를 유발하는 잘못된 형태 (voldata, volscheme 혼용 및 함수 타입 오류)
          viewer.addIsosurface(densVol, {
            isoval: state.isovalue,
            color: "white",
            voldata: espVol,
            volscheme: createGradient(...) // ❌ 여기서 터지면서 ESP가 아예 안 그려짐!
          });
```

이 지시서를 바탕으로 1) ESP 렌더링 API 호환성 복구, 2) 3D 라벨 동적 색상, 3) 여백이 포함된 버터플라이 차트 세 가지를 모두 완벽히 충족하는 코드를 작성하세요.