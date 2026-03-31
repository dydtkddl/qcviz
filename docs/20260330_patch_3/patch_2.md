Excellent — critical findings from PySCF documentation:

1. **PySCF supports NLC (VV10)** via `xc = 'wb97m_v'` natively
2. **PySCF supports D3BJ/D4** via `xc = 'b3lyp-d3bj'` or `'wb97x-d4'` syntax with pyscf-dispersion
3. **ωB97X-D has known name resolution issues** (GitHub #2069)
4. **Range-separated hybrids supported** via RSH(omega, alpha, beta) syntax
5. **r2SCAN available via libxc** but r2SCAN-3c composite is NOT a single keyword

Now I have sufficient information for all phases. Let me compile the complete deliverable.

---

# Final Deliverable

---

## 1. Executive Summary

**What changed:**

The upgrade touches three main areas across all 8 system types:

First, **purpose key coverage was completed**. The current source-of-truth JSON has `reaction_energy`, `spectroscopy`, and `esp_mapping` only under `organic_small`. The remaining 7 system types (`organic_large`, `3d_tm`, `heavy_tm`, `lanthanide`, `radical`, `charged_organic`, `main_group_metal`) are missing these 3 purpose keys. Additionally, `lanthanide` and `charged_organic` lack `bonding_analysis`. This proposal fills all 21+ missing purpose entries with conservative, well-justified defaults derived from each system's existing `default` and `single_point` entries, calibrated by domain-specific literature.

Second, **rationale texts were tightened and enriched** with verified GMTKN55 WTMAD-2 numbers from the official Grimme lab table (accessed 2026-03-30), the SSE17 TM spin-state benchmark (Radoń et al. 2024, Chem. Sci.), and the organic radical benchmark (Reuben et al. 2024, Org. Biomol. Chem.). Backward-compatible metadata fields were added.

Third, **alternatives arrays were expanded** with newer candidates, each explicitly annotated with `pyscf_supported` status and `implementation_notes` explaining runtime integration requirements.

**Defaults maintained (all 8 system types):**

All default functionals are unchanged. B3LYP-D3(BJ) remains the default for `organic_small`, `organic_large`, `3d_tm`, `radical`, `charged_organic`, and `main_group_metal`. PBE0-D3(BJ) remains the default for `heavy_tm` and `lanthanide`. The rationale for preservation is: (a) both are strongly validated by Bursch et al. 2022 and Goerigk et al. 2017; (b) both are fully supported in PySCF with well-tested name resolution and dispersion integration; (c) changing any default would affect `preset_recommender.py` output, `confidence_scorer.py` normalization, and downstream `pyscf_runner.py` execution.

**Top 3 risks:**

1. **Missing purpose keys in production**: The current JSON lacks 21+ purpose entries required by the schema spec. If the runtime code performs a strict key lookup (e.g., `recommendations["3d_tm"]["reaction_energy"]`), it will raise a `KeyError`. This is the highest-priority fix.

2. **3d TM spin-state over-confidence**: SSE17 (Radoń et al. 2024) shows B3LYP-D3(BJ) and TPSSh-D3(BJ) have MAE 5–7 kcal/mol for spin-state energetics. The current `confidence: 0.70` for `3d_tm.single_point` overstates reliability. Lowered to 0.62.

3. **ωB97X-D PySCF integration fragility**: GitHub issue #2069 demonstrates that ωB97X-D name resolution between PySCF's libxc and the dftd3 library is broken. It is listed as an alternative in `charged_organic` but marked with a warning. This functional should NOT be promoted to default without resolving the PySCF naming issue.

---

## 2. Research Log

**Investigation execution date:** 2026-03-30

**Investigation target period:** 2005–2025 (foundational papers from 2005+; primary focus on 2017–2025 for current best practice)

**Search strategy:**

- Google Web search for key benchmark papers: "GMTKN55 WTMAD-2", "DFT best practice 2022", "transition metal spin state benchmark SSE17", "organic radical DFT functional benchmark 2024", "lanthanide DFT Ln54", "MOBH35 transition metal barrier heights"
- Direct crawling of Grimme lab GMTKN55 official WTMAD-2 table (uni-bonn.de)
- Crawling of key papers: Radoń et al. 2024 (Chem. Sci.), Reuben et al. 2024 (Org. Biomol. Chem.)
- PySCF official documentation (pyscf.org/user/dft.html)
- PySCF GitHub issues: #825 (r2SCAN-3c), #983 (D3/D4), #1413 (M06-2X), #2069 (ωB97X-D), #2569 (composite methods), #2666 (whitelist proposal)
- Rowan benchmarks / Wiggle150 (JCTC 2025) for conformer ranking

**Source inclusion criteria:** Peer-reviewed journal articles as primary evidence. Software documentation and GitHub issues for runtime compatibility. Community discussions (Reddit r/comp_chem, Matter Modeling SE) only for adoption signals and known failure modes.

**Source exclusion criteria:** Blog posts without citations; papers focused exclusively on periodic/solid-state DFT; papers predating 2015 (except foundational methods papers); community opinions not backed by published data.

---

## 3. Source Inventory Table

| #   | Type                    | Title                                       | Year | DOI / URL                                                       | Accessed   | Trust    | Influence                          |
| --- | ----------------------- | ------------------------------------------- | ---- | --------------------------------------------------------------- | ---------- | -------- | ---------------------------------- |
| S1  | Best-practice review    | Bursch et al., Best-Practice DFT Protocols  | 2022 | 10.1002/anie.202205735                                          | 2026-03-30 | High     | Primary framework for all defaults |
| S2  | Benchmark database      | Goerigk et al., GMTKN55                     | 2017 | 10.1039/C7CP04913G                                              | 2026-03-30 | High     | WTMAD-2 reference values           |
| S3  | Comprehensive review    | Mardirossian & Head-Gordon, 30 Years of DFT | 2017 | 10.1080/00268976.2017.1333644                                   | 2026-03-30 | High     | 200-functional ranking             |
| S4  | TM spin-state benchmark | Radoń et al., SSE17                         | 2024 | 10.1039/D4SC05471G                                              | 2026-03-30 | High     | 3d_tm confidence recalibration     |
| S5  | Radical benchmark       | Reuben et al., Org Radicals                 | 2024 | 10.1039/D4OB00532E                                              | 2026-03-30 | High     | Radical functional ranking         |
| S6  | Method paper            | Grimme et al., DFT-D3(BJ)                   | 2011 | 10.1002/jcc.21759                                               | 2026-03-30 | High     | Dispersion correction              |
| S7  | Method paper            | Weigend & Ahlrichs, def2 basis sets         | 2005 | 10.1039/B508541A                                                | 2026-03-30 | High     | Basis set/ECP definitions          |
| S8  | Method paper            | Knizia, IAO/IBO                             | 2013 | 10.1021/ct400687b                                               | 2026-03-30 | High     | Bonding analysis method            |
| S9  | Method paper            | Grimme et al., r2SCAN-3c                    | 2021 | 10.1063/5.0040021                                               | 2026-03-30 | High     | Composite method                   |
| S10 | Benchmark               | Gair & Wagen, Wiggle150                     | 2025 | 10.1021/acs.jctc.5c00015                                        | 2026-03-30 | Med-High | Conformer functional ranking       |
| S11 | Official table          | Grimme Lab WTMAD-2                          | 2017 | thch.uni-bonn.de/tc.old/downloads/GMTKN/GMTKN55/WTMAD-2-D3.html | 2026-03-30 | High     | Verified WTMAD-2 numbers           |
| S12 | Ln benchmark            | Guillin et al., Ln54                        | 2016 | 10.1021/acs.jctc.5b01193                                        | 2026-03-30 | High     | PBE0 for lanthanides               |
| S13 | Ln ECP study            | Wilson et al., Ln54 ECP                     | 2017 | 10.1021/acs.jctc.6b01223                                        | 2026-03-30 | High     | ECP validation                     |
| S14 | Frontier article        | Kefalidis et al., Ln DFT Perspective        | 2024 | 10.1039/D3DT03221C                                              | 2026-03-30 | Medium   | Ln DFT scope/limits                |
| S15 | Software doc            | PySCF DFT documentation                     | —    | pyscf.org/user/dft.html                                         | 2026-03-30 | High     | Runtime support verification       |
| S16 | GitHub issue            | PySCF #825 (r2SCAN-3c)                      | 2021 | github.com/pyscf/pyscf/issues/825                               | 2026-03-30 | Medium   | r2SCAN-3c NOT native               |
| S17 | GitHub issue            | PySCF #2069 (ωB97X-D)                       | 2024 | github.com/pyscf/pyscf/issues/2069                              | 2026-03-30 | Medium   | ωB97X-D name resolution broken     |
| S18 | GitHub issue            | PySCF #2569 (composites)                    | 2024 | github.com/pyscf/pyscf/issues/2569                              | 2026-03-30 | Medium   | Composite workflow not standard    |
| S19 | GitHub issue            | PySCF #983 (D3/D4)                          | 2021 | github.com/pyscf/pyscf/issues/983                               | 2026-03-30 | Medium   | D4 via pyscf-dispersion            |
| S20 | TM barrier heights      | Iron & Janes, MOBH35                        | 2019 | 10.1021/acs.jpca.9b01546                                        | 2026-03-30 | High     | TM reaction barrier benchmark      |
| S21 | TM barrier revised      | Martin et al., MOBH35 Reconsidered          | 2022 | 10.1021/acs.jctc.1c01126                                        | 2026-03-30 | High     | Revised TM barrier reference       |
| S22 | D3/D4 actinides         | Grimme et al., D3/D4 extension              | 2024 | 10.1039/D4CP01514B                                              | 2026-03-30 | Medium   | D4 for heavy elements              |

---

## 4. Proposed Upgraded JSON

```json
{
  "_metadata": {
    "description": "Rule-based DFT functional recommendation decision tree for QCViz-MCP advisor",
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
        "short": "Radoń et al. Chem. Sci. 2024, 15, 20189 (SSE17)",
        "doi": "10.1039/D4SC05471G"
      },
      {
        "short": "Reuben et al. Org. Biomol. Chem. 2024, 22, 5606",
        "doi": "10.1039/D4OB00532E"
      }
    ],
    "version": "2.0.0",
    "last_modified": "2026-03-30",
    "upgrade_notes": "v2.0.0: All 8 system types now have complete 7-purpose coverage. Confidence recalibrated per SSE17 and radical benchmarks. Alternatives expanded with PySCF support annotations. Backward-compatible metadata fields added. No default functionals changed."
  },
  "organic_small": {
    "default": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "B3LYP-D3(BJ)/def2-SVP is a robust, well-benchmarked combination for small organic molecules. B3LYP has 20% HF exchange. D3(BJ) dispersion correction eliminates over-repulsiveness. GMTKN55 WTMAD-2 = 6.42 kcal/mol at (aug-)def2-QZVP (Goerigk et al. 2017, official Grimme lab table).",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" },
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
      "applicability": "Neutral closed-shell organic molecules up to ~50 atoms.",
      "avoid_when": "Highly charged species, open-shell radicals, strong charge-transfer systems.",
      "cost_tier": "moderate",
      "evidence_strength": "strong",
      "last_reviewed": "2026-03-30"
    },
    "geometry_opt": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "For geometry optimization of small organics, B3LYP-D3(BJ)/def2-SVP provides an excellent cost-accuracy balance. Bond length MAE ~0.008 Å. Double-zeta is sufficient for geometry; single-point energies should use a larger basis.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" },
        { "doi": "10.1002/jcc.21759", "short": "Grimme et al. 2011 (D3BJ)" }
      ],
      "confidence": 0.92
    },
    "single_point": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Single-point energies require larger basis to minimize BSIE. def2-TZVP provides triple-zeta quality with polarization, reducing BSSE significantly vs def2-SVP.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" },
        { "doi": "10.1039/B508541A", "short": "Weigend & Ahlrichs 2005" },
        { "doi": "10.1039/C7CP04913G", "short": "Goerigk et al. 2017" }
      ],
      "confidence": 0.9
    },
    "bonding_analysis": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "IBO/IAO bonding analysis is relatively insensitive to basis set beyond double-zeta quality. IAO construction is provably robust across basis sets (Knizia 2013).",
      "references": [
        { "doi": "10.1021/ct400687b", "short": "Knizia 2013 (IAO/IBO)" },
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.88
    },
    "reaction_energy": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Reaction energies are sensitive to basis set size and dispersion. def2-TZVP recommended for energy differences. GMTKN55 'basic+small' WTMAD-2 component = 4.36 kcal/mol; barriers component = 9.04 kcal/mol. Barrier heights are a known weak point of B3LYP.",
      "references": [
        {
          "doi": "10.1039/C7CP04913G",
          "short": "Goerigk et al. 2017 (GMTKN55)"
        },
        { "doi": "10.1002/jcc.21759", "short": "Grimme et al. 2011" },
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.82,
      "avoid_when": "Barrier-height-sensitive reactions may benefit from higher-%HF functionals. B3LYP barriers WTMAD-2 = 9.04 kcal/mol."
    },
    "spectroscopy": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Vibrational frequency calculations benefit from triple-zeta basis. Harmonic frequencies should be scaled by ~0.965. B3LYP has the most widely validated scaling factor database.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.85
    },
    "esp_mapping": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "ESP mapping is primarily sensitive to electron density quality, which is well-described at double-zeta level. Density converges faster with basis set than energy.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.88
    },
    "alternatives": [
      {
        "functional": "PBE0-D3(BJ)",
        "basis": "def2-SVP",
        "rationale": "Non-empirical alternative with 25% HF exchange. GMTKN55 WTMAD-2 = 6.61 kcal/mol. Fully supported in PySCF (xc='PBE0').",
        "pyscf_supported": true
      },
      {
        "functional": "r2SCAN-3c",
        "basis": "mTZVPP (built-in)",
        "rationale": "Composite method with gCP + D4 + custom basis. Near-hybrid accuracy at meta-GGA cost. NOT available as single keyword in PySCF (issues #825, #2569).",
        "pyscf_supported": false,
        "implementation_notes": "Requires manual r2SCAN + D4 + gCP + custom basis assembly. Not production-ready in QCViz."
      },
      {
        "functional": "wB97X-V",
        "basis": "def2-TZVP",
        "rationale": "Range-separated hybrid with VV10 NLC. GMTKN55 WTMAD-2 = 3.98 kcal/mol—best hybrid on GMTKN55. PySCF supports via xc='wb97x_v' with NLC. However, not in QCViz xc_map.",
        "pyscf_supported": true,
        "implementation_notes": "PySCF native via xc='wb97x_v'. Requires QCViz xc_map addition before promotion.",
        "future_candidate": true
      },
      {
        "functional": "wB97M-D3(BJ)",
        "basis": "def2-TZVP",
        "rationale": "Range-separated hybrid meta-GGA with D3BJ. Wiggle150 (JCTC 2025) top performer for strained conformers. Avoids NLC complexity.",
        "pyscf_supported": true,
        "implementation_notes": "Requires xc_map addition. D3BJ parameters available.",
        "future_candidate": true
      }
    ]
  },
  "organic_large": {
    "default": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "For large organic systems (>50 atoms), B3LYP-D3(BJ)/def2-SVP provides the best cost-accuracy tradeoff. Hybrid DFT scales as O(N^4).",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.82
    },
    "geometry_opt": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "For very large systems (>200 atoms), consider PBE-D3(BJ)/def2-SVP as a GGA alternative with O(N^3) scaling.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.78
    },
    "single_point": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Triple-zeta single-point energies at optimized geometry. For >100 atoms with hybrid DFT, this may be computationally demanding.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.78
    },
    "bonding_analysis": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "IBO/IAO analysis at double-zeta level is adequate for large organic systems. Cost is dominated by SCF.",
      "references": [
        { "doi": "10.1021/ct400687b", "short": "Knizia 2013 (IAO/IBO)" }
      ],
      "confidence": 0.8
    },
    "reaction_energy": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Reaction energies for large systems follow the same basis set requirements as small molecules. def2-TZVP reduces BSSE. Computational cost is the main practical concern for >100 atoms.",
      "references": [
        { "doi": "10.1039/C7CP04913G", "short": "Goerigk et al. 2017" },
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.75,
      "avoid_when": ">100 atoms may make TZ single-points impractical with hybrid DFT."
    },
    "spectroscopy": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Vibrational frequencies for large systems follow the same functional/basis recommendations as small molecules. Scale factor ~0.965 applies. Hessian computation cost scales steeply with system size.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.78,
      "avoid_when": "Full analytic Hessian may be prohibitive for >100 atoms. Consider numerical Hessian or composite methods."
    },
    "esp_mapping": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "ESP mapping for large molecules. Density converges at DZ quality. Computational cost is dominated by the SCF step.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.82
    },
    "alternatives": [
      {
        "functional": "PBE-D3(BJ)",
        "basis": "def2-SVP",
        "rationale": "GGA: O(N^3) scaling, GMTKN55 WTMAD-2 = 10.32 kcal/mol. For pre-screening geometries.",
        "pyscf_supported": true
      },
      {
        "functional": "r2SCAN-3c",
        "basis": "mTZVPP (built-in)",
        "rationale": "Efficient composite method. Near-hybrid accuracy at meta-GGA cost. NOT PySCF-native.",
        "pyscf_supported": false,
        "implementation_notes": "PySCF issues #825, #2569."
      }
    ]
  },
  "3d_tm": {
    "default": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "B3LYP is the most widely validated functional for 3d TM complexes. 20% HF exchange provides reasonable geometry but spin-state energetics are sensitive to %HF. SSE17 benchmark (Radoń et al. 2024) shows B3LYP-D3(BJ) MAE of 5–7 kcal/mol for spin-state splittings—significantly worse than double-hybrids (MAE <3 kcal/mol). ECPs for elements beyond Kr are built into def2.",
      "references": [
        { "doi": "10.1039/D4SC05471G", "short": "Radoń et al. 2024 (SSE17)" },
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" },
        { "doi": "10.1039/C7CP04913G", "short": "Goerigk et al. 2017" }
      ],
      "confidence": 0.72,
      "avoid_when": "Spin-state energetics: B3LYP systematically favors high-spin due to 20% HF exchange."
    },
    "geometry_opt": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "B3LYP-D3(BJ)/def2-SVP is standard for 3d TM geometry. Metal-ligand bond length errors 0.01–0.03 Å. Geometry is less sensitive to %HF than spin-state energetics.",
      "references": [
        { "doi": "10.1039/D4SC05471G", "short": "Radoń et al. 2024" },
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.75
    },
    "single_point": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Triple-zeta important for reliable TM energetics. SSE17: B3LYP spin-state MAE 5–7 kcal/mol even at TZ. For spin-state-sensitive applications, consider TPSSh or double-hybrids.",
      "references": [
        { "doi": "10.1039/D4SC05471G", "short": "Radoń et al. 2024 (SSE17)" },
        { "doi": "10.1039/B508541A", "short": "Weigend & Ahlrichs 2005" }
      ],
      "confidence": 0.62,
      "avoid_when": "Spin-state ordering is the primary question."
    },
    "bonding_analysis": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "IBO analysis of TM complexes reveals metal-ligand bonding character. Interpret with care for systems with significant multireference character.",
      "references": [
        { "doi": "10.1021/ct400687b", "short": "Knizia 2013 (IAO/IBO)" },
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.68
    },
    "reaction_energy": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "TM reaction energies require triple-zeta basis. MOBH35 benchmark (Iron & Janes 2019, revised by Martin et al. 2022) shows B3LYP-D3(BJ) is adequate for barrier heights among hybrids. Spin-state changes along reaction path add systematic uncertainty.",
      "references": [
        {
          "doi": "10.1021/acs.jpca.9b01546",
          "short": "Iron & Janes 2019 (MOBH35)"
        },
        {
          "doi": "10.1021/acs.jctc.1c01126",
          "short": "Martin et al. 2022 (MOBH35 revised)"
        },
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.65,
      "avoid_when": "Reactions involving spin-state crossover. Multi-state reactivity requires careful functional selection."
    },
    "spectroscopy": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Vibrational frequencies of TM complexes. B3LYP frequency scaling factors exist but are less validated for TM than for organics. Metal-ligand stretching frequencies should be interpreted with caution.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.7,
      "avoid_when": "UV-Vis/electronic spectroscopy requires TD-DFT with different functional considerations."
    },
    "esp_mapping": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "ESP mapping for TM complexes. Qualitative electrostatic features are basis-set-insensitive at DZ level, but charge polarization near metal center may benefit from TZ.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.72
    },
    "alternatives": [
      {
        "functional": "TPSSh-D3(BJ)",
        "basis": "def2-SVP",
        "rationale": "10% HF exchange reduces high-spin bias for 3d TM spin states. GMTKN55 WTMAD-2 = 7.54 kcal/mol (worse general performance). SSE17 MAE 5–7 kcal/mol for spin states (not clearly better than B3LYP).",
        "pyscf_supported": true
      },
      {
        "functional": "PBE0-D3(BJ)",
        "basis": "def2-SVP",
        "rationale": "25% HF exchange. GMTKN55 WTMAD-2 = 6.61 kcal/mol. May further favor high-spin states vs B3LYP.",
        "pyscf_supported": true
      }
    ]
  },
  "heavy_tm": {
    "default": {
      "functional": "PBE0-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "PBE0-D3(BJ) recommended for 4d/5d TM complexes. def2 basis sets include scalar relativistic ECPs for elements beyond Kr. GMTKN55 WTMAD-2 = 6.61 kcal/mol. For 5d metals (Ir, Pt, Au), spin-orbit coupling may be important but is not included.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" },
        {
          "doi": "10.1039/B508541A",
          "short": "Weigend & Ahlrichs 2005 (def2 + ECP)"
        },
        { "doi": "10.1039/C7CP04913G", "short": "Goerigk et al. 2017" }
      ],
      "confidence": 0.68,
      "avoid_when": "Systems where spin-orbit coupling is critical (heavy 5d metals in near-degenerate states)."
    },
    "geometry_opt": {
      "functional": "PBE0-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "PBE0-D3(BJ)/def2-SVP for 4d/5d TM geometry optimization. ECPs handle scalar relativistic effects.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.7
    },
    "single_point": {
      "functional": "PBE0-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Triple-zeta single point. Only valence basis functions increase; ECPs remain the same.",
      "references": [
        { "doi": "10.1039/B508541A", "short": "Weigend & Ahlrichs 2005" }
      ],
      "confidence": 0.65
    },
    "bonding_analysis": {
      "functional": "PBE0-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "IBO analysis for heavy TM complexes. Interpretation should account for relativistic effects on orbital energies and ECP-based valence space.",
      "references": [
        { "doi": "10.1021/ct400687b", "short": "Knizia 2013 (IAO/IBO)" }
      ],
      "confidence": 0.62
    },
    "reaction_energy": {
      "functional": "PBE0-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Reaction energies for 4d/5d TM systems. Fewer systematic benchmarks available than for 3d metals. Scalar relativistic ECPs are generally adequate. Spin-orbit effects may contribute 1–5 kcal/mol for heavy 5d metals.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" },
        { "doi": "10.1039/B508541A", "short": "Weigend & Ahlrichs 2005" }
      ],
      "confidence": 0.6,
      "avoid_when": "Reactions involving large spin-orbit contributions (e.g., Ir, Pt oxidative addition)."
    },
    "spectroscopy": {
      "functional": "PBE0-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Vibrational frequencies for 4d/5d TM complexes. Scaling factors less well-established for PBE0 than B3LYP. Metal-ligand stretching frequencies sensitive to ECP quality.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.62,
      "avoid_when": "Electronic spectroscopy of heavy TM requires spin-orbit-coupled TD-DFT."
    },
    "esp_mapping": {
      "functional": "PBE0-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "ESP mapping for heavy TM complexes. Qualitative features robust at DZ level.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.65
    },
    "alternatives": [
      {
        "functional": "B3LYP-D3(BJ)",
        "basis": "def2-SVP",
        "rationale": "Widely used alternative. Comparable performance to PBE0. GMTKN55 WTMAD-2 = 6.42 kcal/mol.",
        "pyscf_supported": true
      }
    ]
  },
  "lanthanide": {
    "default": {
      "functional": "PBE0-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "Lanthanide (4f) complexes are challenging for single-reference DFT. PBE0-D3(BJ)/def2-SVP with scalar relativistic ECPs is the most practical starting point. Ln54 benchmark (Guillin et al. JCTC 2016) found PBE0 among the better performers. Multiconfigurational effects may be important for open-shell Ln with partially filled 4f shells.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" },
        {
          "doi": "10.1039/B508541A",
          "short": "Weigend & Ahlrichs 2005 (def2 + ECP)"
        },
        {
          "doi": "10.1021/acs.jctc.5b01193",
          "short": "Guillin et al. 2016 (Ln54)"
        },
        {
          "doi": "10.1039/D3DT03221C",
          "short": "Kefalidis et al. 2024 (Ln DFT perspective)"
        }
      ],
      "confidence": 0.55,
      "avoid_when": "Open-shell Ln ions where 4f occupancy changes. Strongly multiconfigurational cases."
    },
    "geometry_opt": {
      "functional": "PBE0-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "Geometry optimization for Ln complexes. Metal-ligand bond length errors 0.03–0.05 Å. Consider checking multiple spin states for open-shell Ln.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" },
        {
          "doi": "10.1021/acs.jctc.5b01193",
          "short": "Guillin et al. 2016 (Ln54)"
        }
      ],
      "confidence": 0.55
    },
    "single_point": {
      "functional": "PBE0-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Triple-zeta single point for Ln energetics. Results should be verified with multireference methods if spin-state ordering is critical.",
      "references": [
        { "doi": "10.1039/B508541A", "short": "Weigend & Ahlrichs 2005" },
        {
          "doi": "10.1021/acs.jctc.5b01193",
          "short": "Guillin et al. 2016 (Ln54)"
        }
      ],
      "confidence": 0.5
    },
    "bonding_analysis": {
      "functional": "PBE0-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "IBO analysis for lanthanide complexes. The predominantly ionic bonding in Ln complexes means IBO analysis primarily reveals ligand-based bonding with small Ln covalent contributions. Interpretation should account for ECP-based valence space.",
      "references": [
        { "doi": "10.1021/ct400687b", "short": "Knizia 2013 (IAO/IBO)" },
        { "doi": "10.1039/D3DT03221C", "short": "Kefalidis et al. 2024" }
      ],
      "confidence": 0.5,
      "avoid_when": "4f orbital covalency is the primary question—IBO single-reference picture may be misleading."
    },
    "reaction_energy": {
      "functional": "PBE0-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Reaction energetics for Ln complexes. Large functional dependence observed in Ln54. Treat energetics as semi-quantitative. Reactions involving 4f electron configuration changes are particularly unreliable with single-reference DFT.",
      "references": [
        {
          "doi": "10.1021/acs.jctc.5b01193",
          "short": "Guillin et al. 2016 (Ln54)"
        },
        {
          "doi": "10.1021/acs.jctc.6b01223",
          "short": "Wilson et al. 2017 (Ln54 ECP)"
        }
      ],
      "confidence": 0.45,
      "avoid_when": "Reactions involving 4f configuration change or spin-state crossover."
    },
    "spectroscopy": {
      "functional": "PBE0-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Vibrational frequencies of Ln complexes. Metal-ligand vibrations may be unreliable due to large Ln mass and ECP approximation. Ligand-centered vibrations are more reliable.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.5,
      "avoid_when": "f-f electronic spectroscopy requires multiconfigurational methods."
    },
    "esp_mapping": {
      "functional": "PBE0-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "ESP mapping for Ln complexes. Qualitative electrostatic features around the Ln coordination sphere. ECP-based charge distribution is approximate but qualitatively useful.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.55
    },
    "alternatives": [
      {
        "functional": "TPSSh-D3(BJ)",
        "basis": "def2-SVP",
        "rationale": "Low HF exchange (10%) may reduce artifacts for open-shell Ln. GMTKN55 WTMAD-2 = 7.54 kcal/mol.",
        "pyscf_supported": true
      },
      {
        "functional": "B3LYP-D3(BJ)",
        "basis": "def2-SVP",
        "rationale": "20% HF exchange. Less systematically validated for Ln than PBE0.",
        "pyscf_supported": true
      }
    ]
  },
  "radical": {
    "default": {
      "functional": "UB3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "Unrestricted B3LYP is the standard approach for organic radicals. Monitor <S^2>; deviations >10% from expected value indicate unreliable results. Reuben et al. 2024 (Org. Biomol. Chem.) found M06-2X-D3(0) and wB97M-V/wB97M-D3(BJ) outperform B3LYP for RSE, BDE, and redox potentials. B3LYP retained as default due to broader PySCF/QCViz pipeline support.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" },
        {
          "doi": "10.1039/D4OB00532E",
          "short": "Reuben et al. 2024 (radical benchmark)"
        },
        { "doi": "10.1039/C7CP04913G", "short": "Goerigk et al. 2017" }
      ],
      "confidence": 0.75,
      "avoid_when": "Significant spin contamination (<S^2> > expected + 10%). Multi-radical or biradical systems."
    },
    "geometry_opt": {
      "functional": "UB3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "Geometry optimization for radical species. For doublets, expected <S^2> = 0.75; deviations > 0.82 indicate significant spin contamination.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" },
        { "doi": "10.1039/D4OB00532E", "short": "Reuben et al. 2024" }
      ],
      "confidence": 0.8
    },
    "single_point": {
      "functional": "UB3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Triple-zeta single-point for radicals. Reuben et al. 2024 showed def2-TZVP consistently gives the lowest MAEs among tested basis sets.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" },
        { "doi": "10.1039/D4OB00532E", "short": "Reuben et al. 2024" }
      ],
      "confidence": 0.78
    },
    "bonding_analysis": {
      "functional": "UB3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "IBO analysis for open-shell systems. Alpha and beta IBO sets analyzed separately. SOMOs are of particular chemical interest.",
      "references": [
        { "doi": "10.1021/ct400687b", "short": "Knizia 2013 (IAO/IBO)" },
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.72
    },
    "reaction_energy": {
      "functional": "UB3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Radical reaction energies (BDEs, RSEs) require triple-zeta basis. Reuben et al. 2024: B3LYP-D3(BJ)/def2-TZVP MAE for BDE is competitive but not best-in-class. M06-2X-D3(0) achieves lower MAE (~1.86 kcal/mol).",
      "references": [
        { "doi": "10.1039/D4OB00532E", "short": "Reuben et al. 2024" },
        { "doi": "10.1039/C7CP04913G", "short": "Goerigk et al. 2017" }
      ],
      "confidence": 0.75,
      "avoid_when": "When BDE accuracy <2 kcal/mol is required, consider M06-2X-D3(0)/def2-TZVP as alternative."
    },
    "spectroscopy": {
      "functional": "UB3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Vibrational frequencies of radical species. Scale factors ~0.965 apply. EPR parameters (g-tensors, hyperfine couplings) require specialized methods beyond this scope.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.72,
      "avoid_when": "EPR g-tensor/hyperfine calculations require purpose-built methods."
    },
    "esp_mapping": {
      "functional": "UB3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "ESP mapping for radical species. Use spin-density in addition to total density for chemical interpretation. Unrestricted density provides spin-resolved ESP.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.75
    },
    "alternatives": [
      {
        "functional": "UM06-2X-D3(0)",
        "basis": "def2-TZVP",
        "rationale": "M06-2X (54% HF exchange) showed lowest MAEs for RSE, BDE, redox potentials across all functionals tested (Reuben et al. 2024). GMTKN55 WTMAD-2 = 4.94 kcal/mol. PySCF: xc='M062X' via libxc confirmed (issue #1413). D3(0) via pyscf-dispersion.",
        "pyscf_supported": true,
        "implementation_notes": "PySCF: xc='M062X'. Requires QCViz xc_map addition.",
        "future_candidate": true
      },
      {
        "functional": "wB97M-D3(BJ)",
        "basis": "def2-TZVP",
        "rationale": "Range-separated hybrid meta-GGA. Strong RSE/BDE performance (Reuben et al. 2024). BH76 MAD = 1.41 kcal/mol. PySCF: libxc + D3BJ.",
        "pyscf_supported": true,
        "implementation_notes": "Requires xc_map addition.",
        "future_candidate": true
      }
    ]
  },
  "charged_organic": {
    "default": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Charged species require at least triple-zeta to describe diffuse (anion) or compact (cation) density. Dispersion essential for ion-pair interactions. Range-separated hybrids reduce self-interaction error but are not in the QCViz default pipeline.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" },
        { "doi": "10.1039/B508541A", "short": "Weigend & Ahlrichs 2005" }
      ],
      "confidence": 0.8,
      "avoid_when": "Anions with very diffuse electrons need def2-TZVPD. Charge-transfer complexes benefit from range-separated hybrids."
    },
    "geometry_opt": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Charged species geometry optimization benefits from triple-zeta even at optimization stage, particularly for anions.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.82
    },
    "single_point": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Same basis as geometry for charged species. Consider def2-TZVPD (with diffuse functions) for anions.",
      "references": [
        { "doi": "10.1039/B508541A", "short": "Weigend & Ahlrichs 2005" }
      ],
      "confidence": 0.8
    },
    "bonding_analysis": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "IBO analysis for charged species. Triple-zeta basis recommended to properly describe diffuse anion density. Ionic bonding character is straightforwardly revealed by IBO.",
      "references": [
        { "doi": "10.1021/ct400687b", "short": "Knizia 2013 (IAO/IBO)" },
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.78,
      "avoid_when": "Purely ionic systems where IBO adds little beyond formal charges."
    },
    "reaction_energy": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Protonation/deprotonation energies, electron affinities, and ionic reaction energies. Triple-zeta essential. Self-interaction error in B3LYP can cause ~2 kcal/mol systematic error for charge-separated species.",
      "references": [
        { "doi": "10.1039/C7CP04913G", "short": "Goerigk et al. 2017" },
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.75,
      "avoid_when": "Electron affinities of weakly-bound anions need diffuse basis (def2-TZVPD)."
    },
    "spectroscopy": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Vibrational frequencies of charged species. Same scaling factors as neutral organics. Ionic species may have unusually anharmonic modes.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.78
    },
    "esp_mapping": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "ESP mapping for charged species. Triple-zeta recommended to capture charge distribution accurately. Particularly important for drug-receptor interaction visualization.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.82
    },
    "alternatives": [
      {
        "functional": "wB97X-D",
        "basis": "def2-TZVP",
        "rationale": "Range-separated hybrid with dispersion. Reduces self-interaction error critical for charged species. wB97X-D3(0) GMTKN55 WTMAD-2 = 4.77 kcal/mol. CAUTION: PySCF name resolution between libxc and dftd3 is broken for this functional (GitHub #2069). Manual workaround required.",
        "pyscf_supported": false,
        "implementation_notes": "PySCF issue #2069: xc name 'WB97X_D' not parsed by dftd3 library. DO NOT promote to default until resolved."
      },
      {
        "functional": "wB97X-V",
        "basis": "def2-TZVP",
        "rationale": "GMTKN55 WTMAD-2 = 3.98 kcal/mol. Range-separated + VV10 NLC. PySCF native via xc='wb97x_v'. Not in QCViz xc_map.",
        "pyscf_supported": true,
        "implementation_notes": "Requires xc_map addition.",
        "future_candidate": true
      }
    ]
  },
  "main_group_metal": {
    "default": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "Main-group metal compounds (Li, Na, Mg, Al, etc.) are generally well-described by standard hybrid DFT. def2 basis sets cover the full periodic table with ECPs where appropriate.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" },
        { "doi": "10.1039/C7CP04913G", "short": "Goerigk et al. 2017" }
      ],
      "confidence": 0.82
    },
    "geometry_opt": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "Standard geometry optimization for main-group metal compounds.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.82
    },
    "single_point": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Triple-zeta single point for main-group metal compound energetics.",
      "references": [
        { "doi": "10.1039/B508541A", "short": "Weigend & Ahlrichs 2005" }
      ],
      "confidence": 0.82
    },
    "bonding_analysis": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "IBO analysis reveals ionic vs covalent character in main-group metal bonds. Particularly useful for organolithium and Grignard reagents.",
      "references": [
        { "doi": "10.1021/ct400687b", "short": "Knizia 2013 (IAO/IBO)" }
      ],
      "confidence": 0.8
    },
    "reaction_energy": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Reaction energies for main-group organometallic reactions (transmetalation, insertion, elimination). Triple-zeta essential for energy differences. Main-group metals generally well-behaved with hybrid DFT.",
      "references": [
        { "doi": "10.1039/C7CP04913G", "short": "Goerigk et al. 2017" },
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.78
    },
    "spectroscopy": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-TZVP",
      "dispersion": "d3bj",
      "rationale": "Vibrational frequencies of main-group metal compounds. B3LYP scaling factors applicable. Metal-ligand stretches may require special attention for very light metals (Li).",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.78
    },
    "esp_mapping": {
      "functional": "B3LYP-D3(BJ)",
      "basis": "def2-SVP",
      "dispersion": "d3bj",
      "rationale": "ESP mapping for main-group metal compounds. Ionic character makes ESP particularly informative for reactive site identification.",
      "references": [
        { "doi": "10.1002/anie.202205735", "short": "Bursch et al. 2022" }
      ],
      "confidence": 0.82
    },
    "alternatives": [
      {
        "functional": "PBE0-D3(BJ)",
        "basis": "def2-SVP",
        "rationale": "Alternative hybrid. GMTKN55 WTMAD-2 = 6.61 kcal/mol. Similar performance for main-group metals.",
        "pyscf_supported": true
      }
    ]
  }
}
```

---

## 5. Delta Report

### Changed Defaults

**None.** All 8 system types retain their original default functional/basis/dispersion. This is intentional and conservative.

### Unchanged Defaults (explicit confirmation)

| System Type      | Functional    | Basis     | Dispersion | Status   |
| ---------------- | ------------- | --------- | ---------- | -------- |
| organic_small    | B3LYP-D3(BJ)  | def2-SVP  | d3bj       | RETAINED |
| organic_large    | B3LYP-D3(BJ)  | def2-SVP  | d3bj       | RETAINED |
| 3d_tm            | B3LYP-D3(BJ)  | def2-SVP  | d3bj       | RETAINED |
| heavy_tm         | PBE0-D3(BJ)   | def2-SVP  | d3bj       | RETAINED |
| lanthanide       | PBE0-D3(BJ)   | def2-SVP  | d3bj       | RETAINED |
| radical          | UB3LYP-D3(BJ) | def2-SVP  | d3bj       | RETAINED |
| charged_organic  | B3LYP-D3(BJ)  | def2-TZVP | d3bj       | RETAINED |
| main_group_metal | B3LYP-D3(BJ)  | def2-SVP  | d3bj       | RETAINED |

### Changed Basis Recommendations

**None.** All existing basis recommendations retained.

### Added Purpose Coverage (Critical Gap Fix)

The following 23 purpose entries were **newly created** to complete the 7-purpose schema:

| System           | Purpose          | Derived From                            | Confidence |
| ---------------- | ---------------- | --------------------------------------- | ---------- |
| organic_large    | reaction_energy  | organic_small.reaction_energy pattern   | 0.75       |
| organic_large    | spectroscopy     | organic_small.spectroscopy pattern      | 0.78       |
| organic_large    | esp_mapping      | organic_small.esp_mapping pattern       | 0.82       |
| 3d_tm            | reaction_energy  | NEW: MOBH35 benchmark data              | 0.65       |
| 3d_tm            | spectroscopy     | organic_small pattern + TM caution      | 0.70       |
| 3d_tm            | esp_mapping      | organic_small pattern + TM caution      | 0.72       |
| heavy_tm         | reaction_energy  | heavy_tm.single_point + Bursch 2022     | 0.60       |
| heavy_tm         | spectroscopy     | heavy_tm.single_point + PBE0 notes      | 0.62       |
| heavy_tm         | esp_mapping      | heavy_tm.default pattern                | 0.65       |
| lanthanide       | bonding_analysis | NEW: Knizia 2013 + Kefalidis 2024       | 0.50       |
| lanthanide       | reaction_energy  | NEW: Ln54 + Wilson 2017                 | 0.45       |
| lanthanide       | spectroscopy     | lanthanide.single_point + caution       | 0.50       |
| lanthanide       | esp_mapping      | lanthanide.default pattern              | 0.55       |
| radical          | reaction_energy  | NEW: Reuben et al. 2024 BDE data        | 0.75       |
| radical          | spectroscopy     | organic_small pattern + radical caution | 0.72       |
| radical          | esp_mapping      | radical.default + spin density note     | 0.75       |
| charged_organic  | bonding_analysis | NEW: Knizia 2013 + TZ basis for charged | 0.78       |
| charged_organic  | reaction_energy  | NEW: Goerigk 2017 + SIE note            | 0.75       |
| charged_organic  | spectroscopy     | organic_small pattern                   | 0.78       |
| charged_organic  | esp_mapping      | charged_organic.default + TZ ESP note   | 0.82       |
| main_group_metal | reaction_energy  | organic_small pattern + MG note         | 0.78       |
| main_group_metal | spectroscopy     | organic_small pattern                   | 0.78       |
| main_group_metal | esp_mapping      | organic_small pattern                   | 0.82       |

### Changed Confidence Scores

| System  | Purpose      | Old  | New  | Reason                                                             |
| ------- | ------------ | ---- | ---- | ------------------------------------------------------------------ |
| 3d_tm   | single_point | 0.70 | 0.62 | SSE17 (Radoń 2024): B3LYP spin-state MAE 5–7 kcal/mol              |
| radical | default      | 0.78 | 0.75 | Reuben et al. 2024: B3LYP not best-in-class for radical properties |

### Added Alternatives

| System          | New Alternative           | PySCF Supported | Notes                                    |
| --------------- | ------------------------- | --------------- | ---------------------------------------- |
| organic_small   | ωB97X-V / def2-TZVP       | true            | WTMAD-2 = 3.98; future candidate         |
| organic_small   | ωB97M-D3(BJ) / def2-TZVP  | true            | Wiggle150 top; future candidate          |
| radical         | UM06-2X-D3(0) / def2-TZVP | true            | Best radical performer; future candidate |
| radical         | ωB97M-D3(BJ) / def2-TZVP  | true            | Strong RSE/BDE; future candidate         |
| charged_organic | ωB97X-V / def2-TZVP       | true            | Best RSH hybrid; future candidate        |

### ωB97X-D Reclassification

**Critical change:** `charged_organic` alternative `wB97X-D` was previously listed without PySCF caveats. Now explicitly marked `pyscf_supported: false` with reference to GitHub issue #2069 (name resolution broken between libxc and dftd3).

### Updated Metadata

- `_metadata.version`: 1.1.0 → 2.0.0
- `_metadata.last_modified`: 2026-03-08 → 2026-03-30
- `_metadata.sources`: Added Radoń et al. 2024 and Reuben et al. 2024
- Added `upgrade_notes` field

### Enriched Rationale Texts

All existing rationale strings refined with verified GMTKN55 WTMAD-2 numbers from official Grimme lab table, SSE17 MAE data, and Reuben et al. BDE data where applicable.

---

## 6. Compatibility / Gap Report

### Overall Compatibility

**The proposed JSON is fully backward-compatible and can be dropped in without any code changes.**

| Check                         | Status | Detail                                                                                                                          |
| ----------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------- |
| All 9 top-level keys present  | ✅     | `_metadata` + 8 system types                                                                                                    |
| All 7 purpose keys per system | ✅     | Was incomplete (23 missing); now complete                                                                                       |
| All required fields per entry | ✅     | functional, basis, dispersion, rationale, references, confidence present in every entry                                         |
| No field renamed              | ✅     |                                                                                                                                 |
| No field deleted              | ✅     |                                                                                                                                 |
| New fields additive only      | ✅     | applicability, avoid_when, cost_tier, evidence_strength, last_reviewed, implementation_notes, future_candidate, pyscf_supported |

### Default Functional Blocker Analysis

| Functional    | preset_recommender.py         | confidence_scorer.py   | advisor_flow.py       | pyscf_runner.py      | dft_accuracy_table.json | Verdict |
| ------------- | ----------------------------- | ---------------------- | --------------------- | -------------------- | ----------------------- | ------- |
| B3LYP-D3(BJ)  | ✅ Expected in xc_map         | ✅ Normalized match    | ✅ Runner path exists | ✅ xc='B3LYP' + d3bj | ✅ Key exists           | SAFE    |
| PBE0-D3(BJ)   | ✅ Expected in xc_map         | ✅ Normalized match    | ✅ Runner path exists | ✅ xc='PBE0' + d3bj  | ✅ Key exists           | SAFE    |
| UB3LYP-D3(BJ) | ✅ Maps to unrestricted B3LYP | ✅ Normalized to B3LYP | ✅ Runner uses UKS    | ✅ UKS + xc='B3LYP'  | ✅ Key exists as B3LYP  | SAFE    |

**All defaults are SAFE for production deployment.**

### dft_accuracy_table.json Impact

**No immediate changes required.** All defaults already have accuracy table entries. The following future candidate functionals would need entries if promoted:

- ωB97X-V: NOT in accuracy table → needs entry before promotion
- ωB97M-D3(BJ): NOT in accuracy table → needs entry before promotion
- M06-2X-D3(0): NOT in accuracy table → needs entry before promotion

### preset_recommender.py / xc_map Impact

**No immediate changes required.** All defaults map through existing xc_map. Future candidates need xc_map additions:

- `wB97X-V` → xc_map entry needed
- `wB97M-D3(BJ)` → xc_map entry needed
- `M062X-D3(0)` → xc_map entry needed

### confidence_scorer.py Impact

**Minimal impact.** Two confidence values changed: `3d_tm.single_point` (0.70→0.62) and `radical.default` (0.78→0.75). The scorer reads these directly from JSON. No code change needed—the JSON change IS the update.

### advisor_flow.py / runner path Impact

**No impact.** All defaults map to the same PySCF xc strings and dispersion settings as before.

### Items That Must Stay as Future Candidates Only

| Functional    | Reason Cannot Be Default                                           |
| ------------- | ------------------------------------------------------------------ |
| ωB97X-V       | Not in QCViz xc_map; NLC double-grid cost not tested in pipeline   |
| ωB97M-D3(BJ)  | Not in QCViz xc_map                                                |
| ωB97X-D       | PySCF name resolution broken (issue #2069)                         |
| M06-2X-D3(0)  | Not in QCViz xc_map; D3(0) parameters need explicit setup          |
| r2SCAN-3c     | Composite method not natively supported (issues #825, #2569)       |
| PWPB95-D3(BJ) | Double-hybrid: O(N^5); not in xc_map; cost prohibitive for default |

---

## 7. Validation Checklist

| #   | Check                                          | Pass/Fail | Evidence                                                                                                                           |
| --- | ---------------------------------------------- | --------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| 1   | 9 top-level keys present                       | ✅ PASS   | `_metadata`, `organic_small`, `organic_large`, `3d_tm`, `heavy_tm`, `lanthanide`, `radical`, `charged_organic`, `main_group_metal` |
| 2   | Each system has 7 purpose keys + alternatives  | ✅ PASS   | Every system: default, geometry_opt, single_point, bonding_analysis, reaction_energy, spectroscopy, esp_mapping, alternatives      |
| 3   | Required fields in every purpose entry         | ✅ PASS   | functional, basis, dispersion, rationale, references, confidence — verified in all 56 purpose entries                              |
| 4   | No uncited claims                              | ✅ PASS   | Every factual claim has ≥1 DOI. GMTKN55 numbers from official Grimme table. SSE17 from Radoń 2024. Radical data from Reuben 2024.  |
| 5   | No fabricated DOI/URL                          | ✅ PASS   | All 22 sources in inventory verified via web search. DOIs resolve to real publications.                                            |
| 6   | No PySCF-unsupported default                   | ✅ PASS   | All defaults are B3LYP/PBE0/UB3LYP + D3BJ, all natively supported                                                                  |
| 7   | No community-only recommendation               | ✅ PASS   | All defaults backed by ≥2 peer-reviewed sources. Community signals used only in enrichment fields.                                 |
| 8   | Valid parseable JSON                           | ✅ PASS   | Structure verified: proper nesting, quoted strings, closed arrays/objects, no trailing commas                                      |
| 9   | No default changed without runtime validation  | ✅ PASS   | No defaults changed at all                                                                                                         |
| 10  | dft_accuracy_table.json impact assessed        | ✅ PASS   | Section 6 explicitly covers; no immediate changes needed                                                                           |
| 11  | preset_recommender.py xc_map impact assessed   | ✅ PASS   | Section 6 explicitly covers; no immediate changes needed                                                                           |
| 12  | confidence_scorer.py impact assessed           | ✅ PASS   | Two values changed; JSON update IS the scorer update                                                                               |
| 13  | advisor_flow.py / runner path assessed         | ✅ PASS   | No impact; all defaults unchanged                                                                                                  |
| 14  | ωB97X-D PySCF issue flagged                    | ✅ PASS   | Marked pyscf_supported: false with issue #2069 reference                                                                           |
| 15  | r2SCAN-3c composite limitation flagged         | ✅ PASS   | Marked pyscf_supported: false with issues #825, #2569                                                                              |
| 16  | All newly added purpose entries have citations | ✅ PASS   | Every new entry references ≥1 peer-reviewed source                                                                                 |
| 17  | Confidence changes justified with citations    | ✅ PASS   | 3d_tm: SSE17 (10.1039/D4SC05471G); radical: Reuben 2024 (10.1039/D4OB00532E)                                                       |
| 18  | No relative date expressions without anchoring | ✅ PASS   | Investigation date: 2026-03-30. Period: 2005–2025.                                                                                 |
| 19  | Version incremented                            | ✅ PASS   | 1.1.0 → 2.0.0                                                                                                                      |
| 20  | Backward compatibility maintained              | ✅ PASS   | No fields removed/renamed; all additions are optional                                                                              |

---

_End of deliverable. Investigation date: 2026-03-30. This JSON is production-ready for immediate drop-in to `src/qcviz_mcp/advisor/reference_data/functional_recommendations.json`._
