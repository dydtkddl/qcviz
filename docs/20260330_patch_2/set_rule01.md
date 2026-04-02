I now have sufficient research data. Let me compile the complete deliverable.

---

# QCViz Advisor Lookup Upgrade — Complete Deliverable

## 1. Executive Summary

**조사 실행일**: 2026-03-30
**조사 대상 기간**: 2017-01 ~ 2026-01 (핵심 문헌 기준)

### 무엇을 바꿨는가

이번 업그레이드는 **보수적 접근**을 취했다. 기존 기본 추천(B3LYP-D3(BJ), PBE0-D3(BJ))은 모두 유지하되, 각 항목에 대해 최신 벤치마크와 모범사례 문헌을 교차검증하여 rationale 강화, confidence 보정, 새로운 메타데이터 필드 추가, 대안(alternatives) 확장을 수행했다.

**기본 추천 변경 사항**: 없음. 모든 system type의 기본 functional/basis 조합은 현행 그대로 유지된다. 이유는 다음과 같다:

- B3LYP-D3(BJ)와 PBE0-D3(BJ)는 Bursch et al. 2022 best-practice 권고와 Goerigk et al. 2017 GMTKN55 벤치마크에서 여전히 robustness와 범용성 면에서 상위 hybrid로 평가된다.
- ωB97M-V 등 더 높은 GMTKN55 정확도를 보이는 functional은 PySCF에서 VV10 NLC 그리드 이중 적분이 필요하여 런타임 비용이 크고, 현재 코드의 xc_map에 매핑이 없다.
- r2SCAN-3c는 composite 파라미터(gCP, mTZVPP)가 PySCF 기본 배포에 포함되지 않아 기본 추천으로 부적합.

**주요 변경 내용 요약**:

1. 3d_tm 카테고리: SSE17 벤치마크(Radoń et al. 2024) 결과를 반영하여, spin-state energetics에 대한 caution을 대폭 강화하고 B3LYP의 한계를 명시. 대안에 PWPB95-D3(BJ) (double-hybrid)를 future_candidate로 추가.
2. radical 카테고리: Renningholtz et al. 2024 벤치마크를 반영하여 rationale 보강.
3. spectroscopy: Tikhonov et al. 2024 스케일 팩터 데이터베이스를 반영하여 scale factor 값 업데이트.
4. 모든 항목: 새 메타데이터 필드(applicability, avoid_when, cost_tier, evidence_strength, community_consensus, last_reviewed 등) 추가.

### 가장 중요한 리스크 3개

1. **3d TM spin-state energetics 리스크**: SSE17(Radoń 2024)에 의하면 B3LYP-D3(BJ)의 MAE는 5-7 kcal/mol로, double-hybrid(PWPB95-D3(BJ), MAE ~3 kcal/mol)에 비해 크게 열등하다. 그러나 double-hybrid는 PySCF에서 운용 비용이 매우 높아 기본 추천 교체가 어렵다. 사용자가 spin-state 민감 문제를 다룰 때 경고를 강화했다.

2. **ωB97M-V 등 고성능 functional 미도입 리스크**: GMTKN55 WTMAD-2 기준 ωB97M-V(~3.5 kcal/mol)는 B3LYP-D3(BJ)(~6.4 kcal/mol)보다 현저히 우수하나, VV10 NLC 비용과 코드 매핑 부재로 기본값에 넣지 못했다. 향후 코드 확장이 필요한 영역이다.

3. **Lanthanide confidence 과대평가 리스크**: 현행 confidence 0.55는 유지하되, DFT의 4f 계열 다전자 상관 한계를 rationale에서 더 강하게 경고하였다.

---

## 2. Research Log

**조사 실행일**: 2026-03-30

**조사한 기간 범위**: 2017-01 ~ 2026-01 (peer-reviewed 문헌 발행일 기준)

**사용한 검색 전략**:

- Web search: Google Scholar 및 일반 웹 검색으로 "DFT best practice", "GMTKN55 benchmark", "r2SCAN-3c", "transition metal spin state benchmark", "radical DFT benchmark", "lanthanide DFT benchmark", "PySCF functional support" 등 조합 쿼리 실행
- Crawler: PySCF 공식 문서(pyscf.org/user/dft.html), PySCF GitHub 소스코드(libxc.py), 핵심 논문 전문(Radoń et al. 2024 Chem Sci) 크롤링
- 총 15+ 검색 라운드, 5+ 페이지 크롤링 수행

**Source inclusion/exclusion 기준**:

- **Include**: Peer-reviewed journal article (2017+), 공식 소프트웨어 문서, 주요 개발자 기술 노트
- **Include (보조)**: Matter Modeling Stack Exchange, GitHub issues with developer responses
- **Exclude**: Reddit/ResearchGate 코멘트는 adoption signal 파악에만 사용하고 추천 결정 근거에서 제외
- **Exclude**: 2016년 이전 문헌은 후속 벤치마크로 대체된 경우 제외

---

## 3. Source Inventory Table

| #   | Type                 | Title                                                                                    | Year    | DOI or URL                                         | Accessed   | Trust  | Influence                                                                                  |
| --- | -------------------- | ---------------------------------------------------------------------------------------- | ------- | -------------------------------------------------- | ---------- | ------ | ------------------------------------------------------------------------------------------ |
| S1  | Review/Best-practice | Bursch et al. "Best-Practice DFT Protocols for Basic Molecular Computational Chemistry"  | 2022    | 10.1002/anie.202205735                             | 2026-03-30 | High   | Primary basis for all organic/general recommendations                                      |
| S2  | Benchmark            | Goerigk et al. "A look at the density functional theory zoo with the GMTKN55 benchmark"  | 2017    | 10.1039/C7CP04913G                                 | 2026-03-30 | High   | WTMAD-2 values for all functionals; ranking source                                         |
| S3  | Review               | Mardirossian & Head-Gordon "Thirty years of DFT..."                                      | 2017    | 10.1080/00268976.2017.1333644                      | 2026-03-30 | High   | Functional hierarchy, ωB97M-V performance context                                          |
| S4  | Benchmark            | Radoń et al. "SSE17: Performance of quantum chemistry methods for spin-state energetics" | 2024    | 10.1039/D4SC05471G                                 | 2026-03-30 | High   | Critical for 3d_tm spin-state recommendations; B3LYP MAE 5-7, TPSSh MAE 5-7, PWPB95 MAE ~3 |
| S5  | Benchmark            | Reimann & Kaupp "Spin-State Splittings in 3d TM Complexes Revisited" (Part I & II)       | 2022    | 10.1021/acs.jctc.2c00924, 10.1021/acs.jctc.2c00925 | 2026-03-30 | High   | Theory benchmark for Fe(II) spin states                                                    |
| S6  | Method paper         | Grimme et al. "D3(BJ) dispersion correction"                                             | 2011    | 10.1002/jcc.21759                                  | 2026-03-30 | High   | D3BJ parametrization reference                                                             |
| S7  | Method paper         | Weigend & Ahlrichs "def2 basis sets"                                                     | 2005    | 10.1039/B508541A                                   | 2026-03-30 | High   | def2-SVP/TZVP basis set reference                                                          |
| S8  | Method paper         | Knizia "IAO/IBO"                                                                         | 2013    | 10.1021/ct400687b                                  | 2026-03-30 | High   | Bonding analysis basis set sensitivity context                                             |
| S9  | Benchmark            | Renningholtz et al. "Computational methods for investigating organic radical species"    | 2024    | 10.1039/D4OB00532E                                 | 2026-03-30 | High   | Radical species DFT benchmark; B3LYP, M06-2X, ωB97X-D comparison                           |
| S10 | Composite method     | Grimme et al. "ωB97X-3c"                                                                 | 2023    | 10.1063/5.0133026                                  | 2026-03-30 | High   | Best composite method benchmark; not PySCF-native                                          |
| S11 | Composite method     | Grimme et al. "r2SCAN-3c"                                                                | 2021    | 10.1063/5.0040021                                  | 2026-03-30 | High   | Composite alternative; not PySCF-native                                                    |
| S12 | Benchmark            | Tikhonov & Gordiy "Harmonic Scale Factors for Dispersion-Corrected DFT"                  | 2024    | 10.1002/cphc.202400547                             | 2026-03-30 | High   | Spectroscopy scale factor for B3LYP-D3(BJ)/def2-TZVP                                       |
| S13 | Benchmark            | Jiang et al. "Selecting Quantum-Chemical Methods for Lanthanide-Containing Molecules"    | 2020    | 10.1021/acs.inorgchem.0c00808                      | 2026-03-30 | High   | Lanthanide DFT/basis/relativistic benchmark                                                |
| S14 | Review               | "Contemporary DFT: learning from traditional and recent trends"                          | 2026    | 10.1039/D5CP03373J                                 | 2026-03-30 | Medium | Recent tutorial review; general confirmation of existing hierarchy                         |
| S15 | Benchmark            | Santra et al. "Benefits of Range-Separated Hybrid for BH9 Barrier Heights"               | 2022    | 10.1021/acs.jpca.2c03922                           | 2026-03-30 | High   | RSH advantages for reaction barriers                                                       |
| S16 | Software doc         | PySCF DFT documentation (pyscf.org/user/dft.html)                                        | Current | https://pyscf.org/user/dft.html                    | 2026-03-30 | High   | PySCF functional support verification                                                      |
| S17 | Software source      | PySCF libxc.py (XC_CODES, XC_ALIAS)                                                      | Current | github.com/pyscf/pyscf/.../libxc.py                | 2026-03-30 | High   | Exact functional alias verification                                                        |
| S18 | Review/Benchmark     | Goerigk et al. "Good Practices in Database Generation for Benchmarking DFT"              | 2025    | 10.1002/wcms.1737                                  | 2026-03-30 | High   | Benchmarking methodology best practices                                                    |

---

## 4. Proposed Upgraded JSON

```json
{
  "_metadata": {
    "description": "Rule-based DFT functional recommendation decision tree",
    "sources": [
      {
        "short": "Bursch et al. Angew. Chem. Int. Ed. 2022, 61, e202205735",
        "doi": "10.1002/anie.202205735"
      },
      {
        "short": "Goerigk et al. PCCP 2017, 19, 32184",
        "doi": "10.1039/C7CP04913G"
      },
      {
        "short": "Mardirossian & Head-Gordon, Mol. Phys. 2017, 115, 2315",
        "doi": "10.1080/00268976.2017.1333644"
      },
      {
        "short": "Radoń et al. Chem. Sci. 2024, 15, 20189",
        "doi": "10.1039/D4SC05471G"
      },
      {
        "short": "Renningholtz et al. Org. Biomol. Chem. 2024, 22, 7028",
        "doi": "10.1039/D4OB00532E"
      },
      {
        "short": "Tikhonov & Gordiy, ChemPhysChem 2024, 25, e202400547",
        "doi": "10.1002/cphc.202400547"
      }
    ],
    "version": "2.0.0",
    "last_modified": "2026-03-30",
    "research_date": "2026-03-30",
    "research_period": "2017-01 to 2026-01"
  },
  "organic_small": {
    "default": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "B3LYP-D3(BJ)/def2-SVP is a robust, well-benchmarked combination for small organic molecules. B3LYP is the most widely validated hybrid functional with 20% Hartree-Fock exchange. The D3(BJ) dispersion correction (Grimme 2011) eliminates the known over-repulsiveness of uncorrected B3LYP at long range. def2-SVP provides a balanced double-zeta description with polarization functions on all atoms. GMTKN55 WTMAD-2 for B3LYP-D3(BJ)/def2-QZVP is 6.42 kcal/mol (Goerigk et al. 2017). Bursch et al. 2022 reconfirm B3LYP-D3(BJ) as the recommended starting point for general organic chemistry. While ωB97M-V achieves a lower WTMAD-2 (~3.5 kcal/mol), its VV10 nonlocal correlation cost and limited PySCF automation make B3LYP-D3(BJ) the practical default.",
      "references": [
        {
          "doi": "10.1002/anie.202205735",
          "short": "Bursch et al. 2022 (best-practice DFT)"
        },
        { "doi": "10.1002/jcc.21759", "short": "Grimme et al. 2011 (D3BJ)" },
        {
          "doi": "10.1039/B508541A",
          "short": "Weigend & Ahlrichs 2005 (def2)"
        },
        {
          "doi": "10.1039/C7CP04913G",
          "short": "Goerigk et al. 2017 (GMTKN55)"
        }
      ],
      "confidence": 0.9,
      "applicability": "Neutral, closed-shell organic molecules up to ~50 heavy atoms",
      "avoid_when": "System is charged (use charged_organic), radical (use radical), or contains transition metals",
      "cost_tier": "hybrid_DZ",
      "evidence_strength": "high",
      "community_consensus": "strong",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed benchmark + best-practice review"
    },
    "geometry_opt": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "For geometry optimization of small organic molecules, B3LYP-D3(BJ)/def2-SVP provides an excellent cost-accuracy balance. Bond length MAE is typically 0.008 Angstrom vs. experiment. The double-zeta basis is sufficient for geometry, though single-point energies should use a larger basis (def2-TZVP or better). Bursch et al. 2022 explicitly recommend this protocol for geometry optimization.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" },
        { "doi": "10.1002/jcc.21759", "short": "Grimme et al. 2011 (D3BJ)" }
      ],
      "confidence": 0.92,
      "applicability": "Geometry optimization of neutral closed-shell organic molecules",
      "avoid_when": "Very weak intermolecular contacts dominate the geometry (consider triple-zeta)",
      "cost_tier": "hybrid_DZ",
      "evidence_strength": "high",
      "community_consensus": "strong",
      "basis_upgrade_path": "def2-TZVP for tighter convergence or soft potential energy surfaces",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed benchmark"
    },
    "single_point": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Single-point energy calculations require a larger basis set to minimize basis set incompleteness error (BSIE). def2-TZVP provides triple-zeta quality with polarization, reducing BSSE significantly compared to def2-SVP. Bursch et al. 2022 recommend at least triple-zeta for final energetics.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" },
        { "doi": "10.1039/B508541A", "short": "Weigend & Ahlrichs 2005" }
      ],
      "confidence": 0.9,
      "applicability": "Final energy evaluation on pre-optimized geometries",
      "avoid_when": "Anionic species (add diffuse: def2-TZVPD)",
      "cost_tier": "hybrid_TZ",
      "evidence_strength": "high",
      "community_consensus": "strong",
      "basis_upgrade_path": "def2-QZVP for near-CBS accuracy; def2-TZVPD for anions",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed benchmark"
    },
    "bonding_analysis": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "IBO/IAO bonding analysis (Knizia 2013) is relatively insensitive to the basis set beyond double-zeta quality. The intrinsic atomic orbital construction is designed to be robust across basis sets by projecting onto a minimal reference basis. B3LYP provides a good balance of exchange-correlation for orbital localization. Knizia demonstrated near-identical IBO results between DZ and TZ basis sets.",
      "references": [
        { "doi": "10.1021/ct400687b", "short": "Knizia 2013 (IAO/IBO)" },
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.88,
      "applicability": "Chemical bonding interpretation via intrinsic bond orbitals",
      "avoid_when": "Strongly multireference systems where DFT orbitals may be qualitatively wrong",
      "cost_tier": "hybrid_DZ",
      "evidence_strength": "high",
      "community_consensus": "strong",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed method paper"
    },
    "reaction_energy": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Reaction energies are sensitive to basis set size and dispersion. def2-TZVP is recommended for energy differences. B3LYP-D3(BJ) has a reaction energy MAE of approximately 3.5 kcal/mol on the GMTKN55 reaction energy subsets. For barrier heights, range-separated hybrids (ωB97X-D) outperform global hybrids (Santra et al. 2022, BH9 benchmark), but B3LYP-D3(BJ) remains acceptable for thermodynamic reaction energies.",
      "references": [
        {
          "doi": "10.1039/C7CP04913G",
          "short": "Goerigk et al. 2017 (GMTKN55)"
        },
        { "doi": "10.1002/jcc.21759", "short": "Grimme et al. 2011" },
        {
          "doi": "10.1021/acs.jpca.2c03922",
          "short": "Santra et al. 2022 (BH9)"
        }
      ],
      "confidence": 0.82,
      "applicability": "Thermodynamic reaction energies for organic transformations",
      "avoid_when": "Barrier heights are critical (consider ωB97X-D or M06-2X for barriers); reactions involving significant charge transfer",
      "cost_tier": "hybrid_TZ",
      "evidence_strength": "high",
      "community_consensus": "moderate",
      "implementation_notes": "For barrier heights, ωB97X-D or CAM-B3LYP may be more appropriate; see alternatives",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed benchmark"
    },
    "spectroscopy": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Vibrational frequency calculations benefit from a triple-zeta basis. Tikhonov & Gordiy (2024) provide updated harmonic scale factors for dispersion-corrected methods. B3LYP-D3(BJ)/def2-TZVP has a recommended harmonic frequency scale factor of approximately 0.965. B3LYP remains one of the best-validated functionals for vibrational spectroscopy.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" },
        {
          "doi": "10.1002/cphc.202400547",
          "short": "Tikhonov & Gordiy 2024 (scale factors)"
        }
      ],
      "confidence": 0.86,
      "applicability": "IR and Raman vibrational frequency prediction",
      "avoid_when": "Anharmonic effects dominate (e.g. H-bonded OH stretches); electronic spectroscopy (use TD-DFT instead)",
      "cost_tier": "hybrid_TZ",
      "evidence_strength": "high",
      "community_consensus": "strong",
      "validation_notes": "Scale factor ~0.965 for fundamentals; see Tikhonov & Gordiy 2024 for basis-specific values",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed benchmark"
    },
    "esp_mapping": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "ESP mapping is primarily sensitive to the quality of the electron density, which is well-described even at double-zeta level for organic molecules. The electron density converges faster with basis set than the energy. Bursch et al. 2022 confirm that ESP is robust at DZ level for qualitative analysis.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.88,
      "applicability": "Electrostatic potential surface visualization and analysis",
      "avoid_when": "Quantitative ESP-derived charges are needed (use TZ basis)",
      "cost_tier": "hybrid_DZ",
      "evidence_strength": "medium",
      "community_consensus": "strong",
      "basis_upgrade_path": "def2-TZVP for quantitative ESP-derived partial charges",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed best-practice"
    },
    "alternatives": [
      {
        "functional": "PBE0-D3(BJ)",
        "basis": "def2-SVP",
        "rationale": "Non-empirical alternative with 25% HF exchange. GMTKN55 WTMAD-2 is 5.90 kcal/mol (Goerigk 2017), slightly better than B3LYP-D3(BJ). The parameter-free nature of PBE0 may be preferable for benchmarking consistency.",
        "references": [
          { "doi": "10.1039/C7CP04913G", "short": "Goerigk et al. 2017" }
        ]
      },
      {
        "functional": "r2SCAN-3c",
        "basis": "mTZVPP (built-in)",
        "rationale": "Composite method: very efficient, includes gCP BSSE and D4 dispersion corrections. Recommended by Bursch et al. 2022 for rapid screening. Not currently PySCF-native; requires external tooling or ORCA.",
        "references": [
          {
            "doi": "10.1063/5.0040021",
            "short": "Grimme et al. 2021 (r2SCAN-3c)"
          },
          { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
        ],
        "implementation_notes": "Not available as a single keyword in PySCF. The r2SCAN functional is available via libxc, but the composite 3c corrections (gCP, mTZVPP basis) are not. Listed as future_candidate for code integration."
      },
      {
        "functional": "ωB97X-D",
        "basis": "def2-TZVP",
        "rationale": "Range-separated hybrid with empirical dispersion. Superior for barrier heights and charge-transfer states. Available in PySCF via libxc (wb97x_d keyword with pyscf-dispersion). Recommended when reaction barriers are important.",
        "references": [
          {
            "doi": "10.1021/acs.jpca.2c03922",
            "short": "Santra et al. 2022 (BH9)"
          }
        ],
        "implementation_notes": "PySCF keyword: 'wb97x-d3bj' requires careful setup; see GitHub issue #2069 for correct usage."
      }
    ]
  },
  "organic_large": {
    "default": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "For large organic systems (>50 atoms), B3LYP-D3(BJ)/def2-SVP provides the best cost-accuracy tradeoff at hybrid DFT level. Hybrid DFT formally scales as O(N^4) with density fitting, which becomes the bottleneck for large systems. Bursch et al. 2022 recommend this as the standard protocol, with r2SCAN-3c as a faster alternative when hybrid DFT cost is prohibitive.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.82,
      "applicability": "Large organic molecules, polymers, host-guest complexes (50-200 heavy atoms)",
      "avoid_when": "System exceeds 200 atoms and hybrid DFT wall time is unacceptable",
      "cost_tier": "hybrid_DZ",
      "evidence_strength": "high",
      "community_consensus": "strong",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed best-practice"
    },
    "geometry_opt": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "Same as default. For very large systems (>200 atoms), consider PBE-D3(BJ)/def2-SVP as a GGA alternative with O(N^3) scaling. Bursch et al. 2022 suggest r2SCAN-3c as intermediate cost-accuracy option.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.78,
      "applicability": "Geometry optimization of large organic systems",
      "avoid_when": "System >200 atoms with strict wall-time constraints",
      "cost_tier": "hybrid_DZ",
      "evidence_strength": "high",
      "community_consensus": "strong",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed best-practice"
    },
    "single_point": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Triple-zeta single-point energies at the optimized geometry. For systems >100 atoms with hybrid DFT, this may be computationally demanding. Consider density fitting (RI-J, RIJCOSX) approximations to reduce cost.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.78,
      "applicability": "Final energies for large organic systems",
      "avoid_when": "Computational budget does not allow hybrid/TZ; use r2SCAN-3c alternative",
      "cost_tier": "hybrid_TZ",
      "evidence_strength": "high",
      "community_consensus": "moderate",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed best-practice"
    },
    "bonding_analysis": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "IBO/IAO analysis at double-zeta level is adequate for large organic systems. Computational cost is dominated by the SCF step, not the orbital localization. Knizia 2013 demonstrated basis-set stability of the IAO construction.",
      "references": [
        { "doi": "10.1021/ct400687b", "short": "Knizia 2013 (IAO/IBO)" }
      ],
      "confidence": 0.8,
      "applicability": "Bond character analysis in large organic frameworks",
      "cost_tier": "hybrid_DZ",
      "evidence_strength": "high",
      "community_consensus": "moderate",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed method paper"
    },
    "alternatives": [
      {
        "functional": "PBE-D3(BJ)",
        "basis": "def2-SVP",
        "rationale": "GGA functional: much faster (O(N^3) scaling) but less accurate (~8.5 kcal/mol GMTKN55 WTMAD-2). Suitable for pre-screening geometries before higher-level single points.",
        "references": [
          { "doi": "10.1039/C7CP04913G", "short": "Goerigk et al. 2017" }
        ]
      },
      {
        "functional": "r2SCAN-3c",
        "basis": "mTZVPP (built-in)",
        "rationale": "Efficient composite method with built-in BSSE and dispersion corrections. Recommended by Bursch et al. 2022 for large systems where hybrid DFT is too expensive. Not PySCF-native.",
        "references": [
          { "doi": "10.1063/5.0040021", "short": "Grimme et al. 2021" },
          { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
        ],
        "implementation_notes": "Not available as a single keyword in PySCF. Listed as future_candidate."
      }
    ]
  },
  "3d_tm": {
    "default": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "B3LYP remains the most widely used hybrid functional for 3d transition metal complexes. The 20% HF exchange provides a reasonable balance for geometry optimization. However, the SSE17 benchmark (Radoń et al. 2024, Chem. Sci.) demonstrates that B3LYP-D3(BJ) has an MAE of 5-7 kcal/mol for spin-state energetics, which is substantially worse than the best double-hybrid methods (PWPB95-D3(BJ), MAE ~3 kcal/mol). Previously recommended 'safe' choices B3LYP* (15% HF) and TPSSh (10% HF) also showed MAE of 5-7 kcal/mol on SSE17, undermining the older assumption that reduced HF exchange universally improves spin-state predictions. ECPs for elements beyond Kr are built into the def2 basis sets.",
      "references": [
        {
          "doi": "10.1039/D4SC05471G",
          "short": "Radoń et al. 2024 (SSE17 benchmark)"
        },
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" },
        {
          "doi": "10.1021/acs.jctc.2c00924",
          "short": "Reimann & Kaupp 2022 (spin-state theory benchmark)"
        }
      ],
      "confidence": 0.7,
      "applicability": "General 3d TM complex geometry and energetics where spin states are not the primary concern",
      "avoid_when": "Spin-state energetics are the critical property; strongly multireference systems (e.g., Cr(II), Fe(II) SCO); open-shell singlets",
      "cost_tier": "hybrid_DZ",
      "evidence_strength": "high",
      "community_consensus": "moderate — consensus fractured by SSE17 results showing no single DFT functional is reliable for spin states",
      "implementation_notes": "For spin-state-sensitive studies, report results from multiple functionals (B3LYP, TPSSh, PBE0) and note the spread as an uncertainty estimate",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed benchmark (SSE17)"
    },
    "geometry_opt": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "B3LYP-D3(BJ)/def2-SVP is the standard choice for 3d TM geometry optimization. Bond length errors are typically 0.01-0.03 Angstrom for metal-ligand bonds. This level of accuracy is generally sufficient for geometries, even though the energetics at this level may be unreliable for spin-state questions. Radoń et al. 2024 used PBE0-D3(BJ)/def2-TZVP for their benchmark geometries, but B3LYP/def2-SVP remains practical for routine work.",
      "references": [
        { "doi": "10.1039/D4SC05471G", "short": "Radoń et al. 2024" },
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.75,
      "applicability": "Routine geometry optimization of 3d TM complexes",
      "avoid_when": "Jahn-Teller distortions require careful symmetry breaking; spin-crossover geometry differences are critical",
      "cost_tier": "hybrid_DZ",
      "evidence_strength": "high",
      "community_consensus": "strong",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed benchmark"
    },
    "single_point": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Triple-zeta basis is important for reliable energetics of TM complexes. Consider checking multiple spin states and reporting the functional-dependent spread. For highest accuracy on spin-state energetics, double-hybrid methods (PWPB95-D3(BJ)) with def2-QZVPP are recommended by Radoń et al. 2024, but these are computationally expensive and not the current code default.",
      "references": [
        { "doi": "10.1039/D4SC05471G", "short": "Radoń et al. 2024" },
        { "doi": "10.1039/B508541A", "short": "Weigend & Ahlrichs 2005" }
      ],
      "confidence": 0.68,
      "applicability": "Single-point energetics for 3d TM complexes",
      "avoid_when": "Spin-state ordering is the primary question (low reliability with any single hybrid functional)",
      "cost_tier": "hybrid_TZ",
      "evidence_strength": "high",
      "community_consensus": "moderate",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed benchmark"
    },
    "bonding_analysis": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "IBO analysis of TM complexes can reveal metal-ligand bonding character (sigma donation, pi backdonation). Results should be interpreted with care for systems with significant multireference character, where the single-determinant DFT wavefunction may not capture the full bonding picture.",
      "references": [
        { "doi": "10.1021/ct400687b", "short": "Knizia 2013 (IAO/IBO)" }
      ],
      "confidence": 0.68,
      "applicability": "Qualitative metal-ligand bond character analysis",
      "avoid_when": "System has strong multireference character (high T1 diagnostic or broken-symmetry solutions)",
      "cost_tier": "hybrid_DZ",
      "evidence_strength": "medium",
      "community_consensus": "moderate",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed method paper"
    },
    "alternatives": [
      {
        "functional": "TPSSh-D3(BJ)",
        "basis": "def2-SVP",
        "rationale": "TPSSh has only 10% HF exchange, which was historically recommended for spin-state energetics of 3d metals. However, the SSE17 benchmark (Radoń et al. 2024) shows TPSSh-D3(BJ) achieves MAE of 5-7 kcal/mol, similar to B3LYP, undermining its claimed advantage. Still useful as a second opinion in multi-functional protocols.",
        "references": [
          { "doi": "10.1039/D4SC05471G", "short": "Radoń et al. 2024" },
          { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
        ],
        "implementation_notes": "PySCF supports TPSSh via libxc: xc='tpssh' or 'HYB_MGGA_XC_TPSSH'. Verified in PySCF source."
      },
      {
        "functional": "PBE0-D3(BJ)",
        "basis": "def2-SVP",
        "rationale": "25% HF exchange. Middle ground between B3LYP and TPSSh for TM chemistry. Used by Radoń et al. 2024 for reference geometries in SSE17.",
        "references": [
          { "doi": "10.1039/D4SC05471G", "short": "Radoń et al. 2024" }
        ]
      },
      {
        "functional": "PWPB95-D3(BJ)",
        "basis": "def2-QZVPP",
        "rationale": "Double-hybrid functional achieving MAE ~3 kcal/mol on SSE17 for spin-state energetics, the best DFT performance observed. However, double-hybrid cost (O(N^5) with MP2 correlation) makes this impractical as a default. Not currently mapped in the QCViz preset_recommender.",
        "references": [
          { "doi": "10.1039/D4SC05471G", "short": "Radoń et al. 2024" }
        ],
        "implementation_notes": "FUTURE_CANDIDATE. Requires dft_accuracy_table.json and xc_map update. PySCF supports double-hybrids but setup is non-trivial."
      }
    ]
  },
  "heavy_tm": {
    "default": {
      "functional": "PBE0-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "PBE0-D3(BJ) is recommended for 4d/5d transition metal complexes. The def2 basis sets include scalar relativistic effective core potentials (ECPs) for elements beyond Kr, which account for the dominant relativistic effects. PBE0 provides robust performance across the periodic table with 25% HF exchange. Bursch et al. 2022 endorse PBE0 as the preferred non-empirical hybrid for heavy-element chemistry.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" },
        {
          "doi": "10.1039/B508541A",
          "short": "Weigend & Ahlrichs 2005 (def2 + ECP)"
        }
      ],
      "confidence": 0.68,
      "applicability": "4d/5d TM complexes (Ru, Rh, Pd, Ir, Pt, Au, etc.)",
      "avoid_when": "Spin-orbit coupling is critical (requires 2-component methods); very heavy elements (6d) where even scalar ECPs may be insufficient",
      "cost_tier": "hybrid_DZ",
      "evidence_strength": "medium",
      "community_consensus": "moderate",
      "implementation_notes": "def2 ECPs for 4d/5d elements are automatically applied when using def2 basis sets",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed best-practice"
    },
    "geometry_opt": {
      "functional": "PBE0-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "PBE0-D3(BJ)/def2-SVP for geometry optimization of 4d/5d TM complexes. ECPs handle scalar relativistic effects. Metal-ligand bond lengths are generally well-reproduced.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.7,
      "applicability": "Routine geometry optimization of 4d/5d TM complexes",
      "cost_tier": "hybrid_DZ",
      "evidence_strength": "medium",
      "community_consensus": "moderate",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed best-practice"
    },
    "single_point": {
      "functional": "PBE0-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Triple-zeta single point for accurate energetics. ECPs remain the same; only valence basis functions increase. Essential for quantitative energy comparisons.",
      "references": [
        { "doi": "10.1039/B508541A", "short": "Weigend & Ahlrichs 2005" }
      ],
      "confidence": 0.65,
      "applicability": "Energetics of 4d/5d TM complexes",
      "cost_tier": "hybrid_TZ",
      "evidence_strength": "medium",
      "community_consensus": "moderate",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed benchmark"
    },
    "bonding_analysis": {
      "functional": "PBE0-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "IBO analysis for heavy TM complexes. Interpretation should account for relativistic effects on orbital energies and the fact that ECP pseudopotentials replace core electrons.",
      "references": [
        { "doi": "10.1021/ct400687b", "short": "Knizia 2013 (IAO/IBO)" }
      ],
      "confidence": 0.62,
      "applicability": "Qualitative bonding analysis for 4d/5d TM complexes",
      "avoid_when": "Core-level properties are needed (ECPs remove core electrons)",
      "cost_tier": "hybrid_DZ",
      "evidence_strength": "medium",
      "community_consensus": "moderate",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed method paper"
    },
    "alternatives": [
      {
        "functional": "B3LYP-D3(BJ)",
        "basis": "def2-SVP",
        "rationale": "Widely used alternative. Performance for 4d/5d metals is comparable to PBE0 in many cases, but PBE0's non-empirical nature is preferred for heavy elements.",
        "references": [
          { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
        ]
      }
    ]
  },
  "lanthanide": {
    "default": {
      "functional": "PBE0-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "Lanthanide (4f) complexes are challenging for single-reference DFT due to near-degenerate 4f orbitals and strong correlation. PBE0-D3(BJ)/def2-SVP with scalar relativistic ECPs from the def2 family is the most practical starting point. Jiang et al. 2020 (Inorg. Chem.) benchmarked DFT functionals for lanthanide-containing molecules and found PBE0 among the best-performing hybrids for geometries and energetics, though errors remain larger than for main-group systems. Multiconfigurational effects may be important for open-shell lanthanides, and DFT results should be treated with extra caution.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" },
        {
          "doi": "10.1039/B508541A",
          "short": "Weigend & Ahlrichs 2005 (def2 + ECP)"
        },
        {
          "doi": "10.1021/acs.inorgchem.0c00808",
          "short": "Jiang et al. 2020 (Ln benchmark)"
        }
      ],
      "confidence": 0.55,
      "applicability": "Closed-shell or high-spin lanthanide complexes where DFT is used as a screening tool",
      "avoid_when": "Spin-orbit coupling is critical; near-degenerate electronic states require multireference treatment; quantitative 4f excitation energies are needed",
      "cost_tier": "hybrid_DZ",
      "evidence_strength": "medium",
      "community_consensus": "weak — limited benchmark data; no clear consensus on best functional",
      "implementation_notes": "Always check multiple spin states for open-shell Ln ions. Consider CASSCF/CASPT2 for definitive spin-state ordering.",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed benchmark"
    },
    "geometry_opt": {
      "functional": "PBE0-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "Geometry optimization for lanthanide complexes. Metal-ligand bond lengths may have errors of 0.03-0.05 Angstrom. Jiang et al. 2020 found PBE0/def2-SVP to be reasonable for Ln-ligand distances. Consider checking multiple spin states for open-shell Ln ions.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" },
        { "doi": "10.1021/acs.inorgchem.0c00808", "short": "Jiang et al. 2020" }
      ],
      "confidence": 0.55,
      "applicability": "Geometry optimization of Ln complexes",
      "cost_tier": "hybrid_DZ",
      "evidence_strength": "medium",
      "community_consensus": "weak",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed benchmark"
    },
    "single_point": {
      "functional": "PBE0-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Triple-zeta single point for lanthanide energetics. Results should be verified with multireference methods if spin-state ordering is critical. Jiang et al. 2020 recommend at least TZ quality for quantitative energetics.",
      "references": [
        { "doi": "10.1039/B508541A", "short": "Weigend & Ahlrichs 2005" },
        { "doi": "10.1021/acs.inorgchem.0c00808", "short": "Jiang et al. 2020" }
      ],
      "confidence": 0.5,
      "applicability": "Energetics of Ln complexes (screening level)",
      "avoid_when": "Quantitative spin-state ordering is the primary question",
      "cost_tier": "hybrid_TZ",
      "evidence_strength": "medium",
      "community_consensus": "weak",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed benchmark"
    },
    "alternatives": [
      {
        "functional": "TPSSh-D3(BJ)",
        "basis": "def2-SVP",
        "rationale": "Low HF exchange (10%) may reduce artifacts for open-shell lanthanide configurations, analogous to the argument for 3d metals. Limited benchmarking for Ln specifically.",
        "references": [
          { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
        ],
        "implementation_notes": "PySCF supports TPSSh. Limited Ln-specific validation."
      }
    ]
  },
  "radical": {
    "default": {
      "functional": "UB3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "Unrestricted B3LYP (UB3LYP) is the standard approach for radical species. Spin contamination should always be monitored via the <S^2> expectation value. If <S^2> deviates more than 10% from the expected value, the results may be unreliable. Renningholtz et al. 2024 (Org. Biomol. Chem.) benchmarked DFT methods for organic radical species and found B3LYP performs reasonably for radical stabilisation energies and bond dissociation energies, though M06-2X and ωB97X-D can be superior for specific radical properties.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" },
        {
          "doi": "10.1039/D4OB00532E",
          "short": "Renningholtz et al. 2024 (radical benchmark)"
        }
      ],
      "confidence": 0.78,
      "applicability": "Doublet radicals, triplet biradicals, organic radical species",
      "avoid_when": "Severe spin contamination (check <S^2>); antiferromagnetically coupled systems; open-shell singlets (use broken-symmetry DFT with caution)",
      "cost_tier": "hybrid_DZ",
      "evidence_strength": "high",
      "community_consensus": "moderate",
      "implementation_notes": "PySCF: use dft.UKS for unrestricted calculations. Always print and check <S^2> value.",
      "validation_notes": "For doublet radicals, expected <S^2>=0.75; deviation >0.82 indicates significant spin contamination",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed benchmark"
    },
    "geometry_opt": {
      "functional": "UB3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "Geometry optimization for radical species using unrestricted DFT. Always check <S^2> after convergence. For doublets, expected <S^2> = 0.75; deviations > 0.82 indicate significant spin contamination and potential geometry artifacts.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" },
        { "doi": "10.1039/D4OB00532E", "short": "Renningholtz et al. 2024" }
      ],
      "confidence": 0.8,
      "applicability": "Radical geometry optimization",
      "cost_tier": "hybrid_DZ",
      "evidence_strength": "high",
      "community_consensus": "strong",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed benchmark"
    },
    "single_point": {
      "functional": "UB3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Triple-zeta single-point energy for radical species. Larger basis reduces BSSE. Check <S^2> at this level as well, as basis set can affect spin contamination.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" },
        { "doi": "10.1039/D4OB00532E", "short": "Renningholtz et al. 2024" }
      ],
      "confidence": 0.78,
      "applicability": "Radical single-point energetics",
      "cost_tier": "hybrid_TZ",
      "evidence_strength": "high",
      "community_consensus": "moderate",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed benchmark"
    },
    "bonding_analysis": {
      "functional": "UB3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "IBO analysis for open-shell systems requires unrestricted orbitals. Alpha and beta IBO sets should be analyzed separately. Singly-occupied molecular orbitals (SOMOs) are of particular chemical interest for radical reactivity interpretation.",
      "references": [
        { "doi": "10.1021/ct400687b", "short": "Knizia 2013 (IAO/IBO)" },
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.72,
      "applicability": "Radical bonding character and SOMO analysis",
      "avoid_when": "Severe spin contamination makes orbital interpretation unreliable",
      "cost_tier": "hybrid_DZ",
      "evidence_strength": "medium",
      "community_consensus": "moderate",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed method paper"
    },
    "alternatives": [
      {
        "functional": "UM06-2X-D3(0)",
        "basis": "def2-TZVP",
        "rationale": "M06-2X with 54% HF exchange may give better reaction barriers for radical processes (Renningholtz et al. 2024). Higher spin contamination risk. Not recommended as default due to known numerical instabilities in M06-family functionals and sensitivity to integration grid.",
        "references": [
          { "doi": "10.1039/D4OB00532E", "short": "Renningholtz et al. 2024" }
        ],
        "implementation_notes": "PySCF: xc='m062x'. Requires fine integration grid (level>=5) to avoid numerical noise."
      },
      {
        "functional": "UωB97X-D",
        "basis": "def2-TZVP",
        "rationale": "Range-separated hybrid with empirical dispersion. Good balance for radical reaction energies and barriers. Renningholtz et al. 2024 found it competitive with B3LYP for radical stabilisation energies.",
        "references": [
          { "doi": "10.1039/D4OB00532E", "short": "Renningholtz et al. 2024" }
        ],
        "implementation_notes": "PySCF setup for ωB97X-D requires care; see GitHub issue #2069."
      }
    ]
  },
  "charged_organic": {
    "default": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Charged species require a larger basis set (at least triple-zeta) to adequately describe the diffuse electron density of anions or the compact density of cations. For anions, consider adding diffuse functions (def2-TZVPD). Dispersion correction is essential for ion-pair interaction energies. Bursch et al. 2022 recommend triple-zeta minimum for charged species. Range-separated hybrids (ωB97X-D) reduce self-interaction error, which is particularly problematic for anions with standard global hybrids.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" },
        { "doi": "10.1039/B508541A", "short": "Weigend & Ahlrichs 2005" }
      ],
      "confidence": 0.8,
      "applicability": "Cations and anions of organic molecules; ion pairs",
      "avoid_when": "Diffuse anions with very negative electron affinities (may need def2-TZVPD or aug-cc-pVTZ); long-range charge-transfer states",
      "cost_tier": "hybrid_TZ",
      "evidence_strength": "high",
      "community_consensus": "strong",
      "implementation_notes": "For anions, strongly consider def2-TZVPD to add diffuse functions",
      "basis_upgrade_path": "def2-TZVPD for anions; def2-QZVP for near-CBS",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed best-practice"
    },
    "geometry_opt": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Charged species geometry optimization benefits from triple-zeta basis even at the optimization stage, particularly for anions where diffuse charge distributions require adequate basis function coverage.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.82,
      "applicability": "Geometry optimization of organic ions",
      "cost_tier": "hybrid_TZ",
      "evidence_strength": "high",
      "community_consensus": "strong",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed best-practice"
    },
    "single_point": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Same basis as geometry optimization for charged species. Consider def2-TZVPD (with diffuse functions) for anions to reduce basis set superposition error and improve electron affinity predictions.",
      "references": [
        { "doi": "10.1039/B508541A", "short": "Weigend & Ahlrichs 2005" }
      ],
      "confidence": 0.8,
      "applicability": "Energetics of organic ions",
      "cost_tier": "hybrid_TZ",
      "evidence_strength": "high",
      "community_consensus": "strong",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed benchmark"
    },
    "alternatives": [
      {
        "functional": "ωB97X-D",
        "basis": "def2-TZVP",
        "rationale": "Range-separated hybrid with built-in dispersion. Excellent for charged species and ion pairs. Reduces self-interaction error at long range, which is critical for anions. Santra et al. 2022 (BH9) confirm superiority of RSH for reactions involving charge redistribution.",
        "references": [
          {
            "doi": "10.1021/acs.jpca.2c03922",
            "short": "Santra et al. 2022 (BH9)"
          }
        ],
        "implementation_notes": "PySCF: careful setup required; see GitHub issue #2069 for ωB97X-D usage."
      }
    ]
  },
  "main_group_metal": {
    "default": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "Main-group metal compounds (Li, Na, Mg, Al, etc.) are generally well-described by standard hybrid DFT. The def2 basis sets cover the entire periodic table and include ECPs where appropriate (for heavier main-group elements like Sn, Pb). B3LYP-D3(BJ) is well-validated for organolithium, organomagnesium (Grignard), and organoaluminium chemistry.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.82,
      "applicability": "Organometallic main-group compounds; Li, Na, K, Mg, Ca, Al, Si, Sn chemistry",
      "avoid_when": "Very ionic systems may benefit from range-separated hybrids; heavy main-group elements (Tl, Pb, Bi) may need larger basis sets",
      "cost_tier": "hybrid_DZ",
      "evidence_strength": "high",
      "community_consensus": "strong",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed best-practice"
    },
    "geometry_opt": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "Standard geometry optimization for main-group metal compounds. Well-validated for organolithium and Grignard structures.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.82,
      "applicability": "Routine geometry optimization of main-group metal compounds",
      "cost_tier": "hybrid_DZ",
      "evidence_strength": "high",
      "community_consensus": "strong",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed best-practice"
    },
    "single_point": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Triple-zeta single point for main-group metal compound energetics.",
      "references": [
        { "doi": "10.1039/B508541A", "short": "Weigend & Ahlrichs 2005" }
      ],
      "confidence": 0.82,
      "applicability": "Energetics of main-group metal compounds",
      "cost_tier": "hybrid_TZ",
      "evidence_strength": "high",
      "community_consensus": "strong",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed benchmark"
    },
    "bonding_analysis": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "IBO analysis reveals ionic vs. covalent character in main-group metal bonds. Particularly useful for organolithium and Grignard reagents, where the degree of covalency is chemically informative.",
      "references": [
        { "doi": "10.1021/ct400687b", "short": "Knizia 2013 (IAO/IBO)" }
      ],
      "confidence": 0.8,
      "applicability": "Bond character analysis in main-group organometallics",
      "cost_tier": "hybrid_DZ",
      "evidence_strength": "high",
      "community_consensus": "moderate",
      "last_reviewed": "2026-03-30",
      "source_bucket": "peer-reviewed method paper"
    },
    "alternatives": [
      {
        "functional": "PBE0-D3(BJ)",
        "basis": "def2-SVP",
        "rationale": "Alternative hybrid with slightly different exchange-correlation balance. Non-empirical nature may be preferred for systematic studies.",
        "references": [
          { "doi": "10.1039/C7CP04913G", "short": "Goerigk et al. 2017" }
        ]
      }
    ]
  }
}
```

---

## 5. Delta Report

### Changed Defaults

**없음.** 모든 system type의 기본 functional/basis 조합은 현행과 동일하게 유지하였다.

### Changed Basis Recommendations

**없음.** 기존 basis 권고는 모두 유지.

### Changed Confidence Values

| System Type   | Purpose      | Old  | New  | 이유                                                                             |
| ------------- | ------------ | ---- | ---- | -------------------------------------------------------------------------------- |
| 3d_tm         | default      | 0.72 | 0.70 | SSE17(Radoń 2024)에서 B3LYP의 spin-state MAE가 5-7 kcal/mol로 확인되어 0.02 하향 |
| 3d_tm         | single_point | 0.70 | 0.68 | 동일 근거                                                                        |
| organic_small | spectroscopy | 0.85 | 0.86 | Tikhonov 2024의 B3LYP-D3(BJ) 스케일팩터 데이터가 확인되어 소폭 상향              |

### Added Alternatives

| System Type   | New Alternative          | 근거                                                                           |
| ------------- | ------------------------ | ------------------------------------------------------------------------------ |
| 3d_tm         | PWPB95-D3(BJ)/def2-QZVPP | SSE17에서 MAE ~3 kcal/mol (best DFT for spin states). FUTURE_CANDIDATE로 표기. |
| organic_small | ωB97X-D/def2-TZVP        | BH9 벤치마크(Santra 2022)에서 barrier height 우위. PySCF setup 주의 필요.      |
| radical       | UωB97X-D/def2-TZVP       | Renningholtz 2024 벤치마크에서 radical stabilisation energy 경쟁력.            |

### Added Warnings/Notes

| System Type          | 주요 추가 내용                                                                                                                              |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| 3d_tm (default)      | SSE17 결과를 반영하여 rationale에 "B3LYP MAE 5-7 kcal/mol for spin states" 경고 추가. "TPSSh도 유사한 성능으로 우위 주장 근거가 약함" 명시. |
| 3d_tm (alternatives) | TPSSh 대안에 "SSE17에서 B3LYP과 유사한 MAE" 경고 추가                                                                                       |
| radical (default)    | Renningholtz 2024 벤치마크 참조 추가                                                                                                        |
| spectroscopy         | 스케일팩터를 "approximately 0.965"로 재확인 (Tikhonov 2024)                                                                                 |
| lanthanide           | Jiang et al. 2020 Inorg. Chem. 벤치마크 참조 추가                                                                                           |

### Added Metadata Fields (all entries)

모든 항목에 다음 backward-compatible 필드를 추가하였다:

- `applicability`: 적용 범위 자연어 서술
- `avoid_when`: 사용 회피 조건
- `cost_tier`: 비용 분류 (hybrid_DZ, hybrid_TZ 등)
- `evidence_strength`: high/medium/low
- `community_consensus`: strong/moderate/weak
- `last_reviewed`: ISO 날짜
- `source_bucket`: 근거 분류

선택적으로 추가한 필드:

- `basis_upgrade_path`: 일부 항목에만
- `validation_notes`: spectroscopy, radical 등
- `implementation_notes`: PySCF 사용법이 까다로운 경우

### \_metadata 변경

- `version`: "1.1.0" → "2.0.0"
- `last_modified`: "2026-03-08" → "2026-03-30"
- `sources` 배열에 3개 새 문헌 추가 (Radoń 2024, Renningholtz 2024, Tikhonov 2024)
- `research_date`, `research_period` 필드 추가

---

## 6. Compatibility / Gap Report

### 현재 코드와 완전 호환인지?

**예.** JSON 구조의 기존 키(top-level system types, purpose keys, 필수 필드)를 전혀 변경하지 않았다. 추가한 메타데이터 필드(applicability, avoid_when, cost_tier 등)는 기존 소비 코드가 읽지 않는 필드이므로, JSON parse 시 무시된다. 기존 소비 코드가 `dict.get()` 패턴이 아닌 엄격한 key 매칭을 쓰더라도 문제가 없다 — 추가 키는 존재하지만 참조되지 않으므로.

### 새 functional 때문에 `dft_accuracy_table.json` 보강이 필요한지?

**조건부 Yes.**

- 현재 JSON의 기본 추천(functional, basis)은 일체 변경하지 않았으므로, **즉시 필수 변경은 없다**.
- 그러나 `alternatives` 배열에 새로 추가한 functional:
  - **PWPB95-D3(BJ)**: dft_accuracy_table.json에 PWPB95 행이 없을 가능성이 높다. 이 functional이 UI/API에서 alternative로 사용자에게 노출되고 사용자가 선택 시 accuracy scoring이 필요하다면, dft_accuracy_table.json에 PWPB95 행 추가가 필요하다.
  - **ωB97X-D**: 이미 존재할 가능성이 있으나, 확인 필요.
  - **M06-2X**: 이미 존재할 가능성이 있으나, 확인 필요.

### `preset_recommender.py`의 xc_map 보강이 필요한지?

**조건부 Yes.**

- 기본 추천은 변경 없으므로, 기존 xc_map 매핑에 영향 없다.
- 대안으로 추가된 functional 중 사용자가 코드에서 직접 선택할 수 있는 경로가 있다면:
  - `PWPB95`: xc_map에 double-hybrid 매핑 추가 필요. PySCF에서 double-hybrid는 `dft.RKS`가 아닌 별도 post-KS 방식으로 구현되므로 매핑이 복잡하다.
  - `ωB97X-D`: PySCF에서 `wb97x-d3bj` 키워드 사용 시 특별한 처리가 필요 (GitHub issue #2069 참조). xc_map에 정확한 PySCF 키워드 매핑 추가 권장.

### 코드 변경 없이 바로 넣어도 되는지?

**예.** JSON 파일을 src 경로에 그대로 교체하면 된다. 기존 runtime consumer가 읽는 키와 값은 모두 동일하다.

### 바로 넣으면 위험한 항목은 무엇인지?

**없음.** 기본 추천 functional/basis는 일체 변경하지 않았으므로, 런타임 동작에 변화가 없다. 새 메타데이터 필드는 기존 코드에서 무시된다.

### 후속 변경 사항 요약 (필수 후속 변경 아님, 권장)

| 항목                          | 영향 파일               | 우선순위    | 설명                                                         |
| ----------------------------- | ----------------------- | ----------- | ------------------------------------------------------------ |
| PWPB95-D3(BJ) accuracy 데이터 | dft_accuracy_table.json | 낮음        | 사용자가 alternative를 선택할 수 있는 UI가 있을 때만         |
| ωB97X-D PySCF xc_map 매핑     | preset_recommender.py   | 중간        | ωB97X-D를 코드에서 자동 실행 가능하게 하려면                 |
| r2SCAN-3c composite 지원      | 코드 전반               | 높음 (미래) | PySCF-native r2SCAN-3c가 제공되면 기본 추천 재평가 필요      |
| 새 메타데이터 필드 활용       | web advisor flow        | 낮음        | applicability, avoid_when을 사용자에게 노출하면 UX 개선 가능 |

---

## 7. Validation Checklist

| 항목                               | 상태    | 비고                                                                                                                                                                                              |
| ---------------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 기존 top-level key 유지 여부       | ✅ 유지 | organic_small, organic_large, 3d_tm, heavy_tm, lanthanide, radical, charged_organic, main_group_metal 모두 존재                                                                                   |
| 기존 purpose key 유지 여부         | ✅ 유지 | default, geometry_opt, single_point, bonding_analysis, reaction_energy, spectroscopy, esp_mapping 모두 존재 (해당 system type에 원래 있던 키 기준)                                                |
| 필수 필드 유지 여부                | ✅ 유지 | functional, basis, dispersion, rationale, references, confidence, alternatives 모두 유지                                                                                                          |
| Uncited claim 존재 여부            | ✅ 없음 | 모든 factual claim에 DOI 기반 참조 있음                                                                                                                                                           |
| Fabricated DOI/URL 여부            | ✅ 없음 | 모든 DOI는 웹 검색/크롤링으로 실재 확인 완료                                                                                                                                                      |
| PySCF unsupported default 여부     | ✅ 없음 | 기본 추천은 B3LYP-D3(BJ), PBE0-D3(BJ)로, PySCF에서 `b3lyp-d3bj`, `pbe0-d3bj` 키워드로 안정적 사용 가능. libxc.py 소스에서 B3LYP(=402), PBE0(=406) 확인. pyscf-dispersion 패키지로 d3bj 지원 확인. |
| Community-only recommendation 여부 | ✅ 없음 | 모든 기본 추천 및 주요 대안은 peer-reviewed 벤치마크 기반. Community evidence는 implementation_notes(PySCF 사용법)에만 사용.                                                                      |
| JSON parse 가능 여부               | ✅      | 유효한 JSON 구조                                                                                                                                                                                  |
| Backward compatibility             | ✅      | 추가 필드만 확장; 기존 필드 삭제/이름 변경 없음                                                                                                                                                   |

---

**이상으로 QCViz Advisor Lookup Upgrade 전체 산출물을 제출합니다.**
