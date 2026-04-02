전수조사 데이터를 체계적으로 CSV로 정리합니다. 출처별로 비교 가능한 모든 수치를 추출합니다.

---

## CSV 1: 에너지 정확도 비교 (Energy Accuracy Comparison)

```csv
source_id,source_short,source_full,year,molecule,method_functional,basis_set,comparison_pair,code_A,code_B,energy_A_hartree,energy_B_hartree,energy_diff_hartree,energy_diff_microhartree,energy_diff_kcal_mol,comparison_type,notes
GH688,GitHub #688,pyscf/pyscf issue 688,2024,formaldehyde (CH2O),PBE,6-31G**,PySCF vs Gaussian,PySCF,Gaussian,-114.364993,-114.367370,0.002377,2377.0,1.492,total_energy,default grid settings; grid refinement reduces gap
GH688,GitHub #688,pyscf/pyscf issue 688,2024,formaldehyde (CH2O),PBE,6-31G**,PySCF vs GAMESS,PySCF,GAMESS,-114.364993,-114.367397,0.002404,2404.0,1.509,total_energy,default grid settings
GH688,GitHub #688,pyscf/pyscf issue 688,2024,formaldehyde (CH2O),PBE,6-31G**,PySCF vs NWChem,PySCF,NWChem,-114.364993,-114.367400,0.002407,2407.0,1.511,total_energy,default grid settings
GH688,GitHub #688,pyscf/pyscf issue 688,2024,formaldehyde (CH2O),PBE,6-31G**,Gaussian vs GAMESS,Gaussian,GAMESS,-114.367370,-114.367397,0.000027,27.0,0.017,total_energy,reference codes agree tightly
GH688,GitHub #688,pyscf/pyscf issue 688,2024,formaldehyde (CH2O),PBE,6-31G**,Gaussian vs NWChem,Gaussian,NWChem,-114.367370,-114.367400,0.000030,30.0,0.019,total_energy,reference codes agree tightly
GPU4PySCF_v1,Wu et al. 2024,GPU4PySCF v1.0 WIREs arXiv:2404.09452,2024,various molecules,B3LYP,def2-SVP,GPU4PySCF vs Q-Chem 6.1,GPU4PySCF,Q-Chem 6.1,,,,<10,<0.006,SCF_energy,Appendix B; multiple molecules; energy discrepancy consistently single-digit μHartree
GPU4PySCF_v1,Wu et al. 2024,GPU4PySCF v1.0 WIREs arXiv:2404.09452,2024,various molecules,B3LYP,def2-TZVPP,GPU4PySCF vs Q-Chem 6.1,GPU4PySCF,Q-Chem 6.1,,,,<10,<0.006,SCF_energy,Appendix B
GPU4PySCF_v1,Wu et al. 2024,GPU4PySCF v1.0 WIREs arXiv:2404.09452,2024,various molecules,B3LYP,def2-QZVP,GPU4PySCF vs Q-Chem 6.1,GPU4PySCF,Q-Chem 6.1,,,,<10,<0.006,SCF_energy,Appendix B
GPU4PySCF_v1,Wu et al. 2024,GPU4PySCF v1.0 WIREs arXiv:2404.09452,2024,various molecules,wB97M-V,def2-TZVPP,GPU4PySCF vs Q-Chem 6.1,GPU4PySCF,Q-Chem 6.1,,,,<10,<0.006,SCF_energy,Appendix B
GPU4PySCF_v1,Wu et al. 2024,GPU4PySCF v1.0 WIREs arXiv:2404.09452,2024,various molecules,PBE0,def2-TZVPP,GPU4PySCF vs Q-Chem 6.1,GPU4PySCF,Q-Chem 6.1,,,,<10,<0.006,SCF_energy,Appendix B
GPU4PySCF_v1,Wu et al. 2024,GPU4PySCF v1.0 WIREs arXiv:2404.09452,2024,various molecules,M06-2X,def2-TZVPP,GPU4PySCF vs Q-Chem 6.1,GPU4PySCF,Q-Chem 6.1,,,,<10,<0.006,SCF_energy,Appendix B
GPU4PySCF_v1,Wu et al. 2024,GPU4PySCF v1.0 WIREs arXiv:2404.09452,2024,various molecules,various,various,GPU4PySCF vs Q-Chem 6.1 (gradient),GPU4PySCF,Q-Chem 6.1,,,,,<0.006,gradient,Appendix C; gradient discrepancy also μHartree/Bohr level
GPU4PySCF_v1,Wu et al. 2024,GPU4PySCF v1.0 WIREs arXiv:2404.09452,2024,various molecules,various,various,GPU4PySCF vs Q-Chem 6.1 (solvation),GPU4PySCF,Q-Chem 6.1,,,,<10,<0.006,solvation_energy,Appendix D; C-PCM/IEF-PCM/SMD comparison
Li2025_JPCA,Li et al. 2025,GPU4PySCF J. Phys. Chem. A 10.1021/acs.jpca.4c05876,2025,various (polyglycine/RNA),RHF,STO-3G,GPU4PySCF vs GAMESS,GPU4PySCF,GAMESS,,,,<10,<0.006,total_energy,Table 1; wall-time + energy comparison
Li2025_JPCA,Li et al. 2025,GPU4PySCF J. Phys. Chem. A 10.1021/acs.jpca.4c05876,2025,various (polyglycine/RNA),RHF,6-31G,GPU4PySCF vs GAMESS,GPU4PySCF,GAMESS,,,,<10,<0.006,total_energy,Table 1
Li2025_JPCA,Li et al. 2025,GPU4PySCF J. Phys. Chem. A 10.1021/acs.jpca.4c05876,2025,various (polyglycine/RNA),RHF,6-31G(d),GPU4PySCF vs GAMESS,GPU4PySCF,GAMESS,,,,<10,<0.006,total_energy,Table 1
Li2025_JPCA,Li et al. 2025,GPU4PySCF J. Phys. Chem. A 10.1021/acs.jpca.4c05876,2025,various,DFT,pc-1,GPU4PySCF vs ORCA,GPU4PySCF,ORCA,,,,<10,<0.006,total_energy,Table 2; most direct PySCF-ORCA comparison available
Li2025_JPCA,Li et al. 2025,GPU4PySCF J. Phys. Chem. A 10.1021/acs.jpca.4c05876,2025,various,DFT,pc-2,GPU4PySCF vs ORCA,GPU4PySCF,ORCA,,,,<10,<0.006,total_energy,Table 2
Li2025_JPCA,Li et al. 2025,GPU4PySCF J. Phys. Chem. A 10.1021/acs.jpca.4c05876,2025,various,DFT,pc-3,GPU4PySCF vs ORCA,GPU4PySCF,ORCA,,,,<10,<0.006,total_energy,Table 2
Li2025_JPCA,Li et al. 2025,GPU4PySCF J. Phys. Chem. A 10.1021/acs.jpca.4c05876,2025,various,DFT,pc-1,GPU4PySCF vs LSDalton,GPU4PySCF,LSDalton,,,,<10,<0.006,total_energy,Table 2
Li2025_JPCA,Li et al. 2025,GPU4PySCF J. Phys. Chem. A 10.1021/acs.jpca.4c05876,2025,various,DFT,pc-2,GPU4PySCF vs LSDalton,GPU4PySCF,LSDalton,,,,<10,<0.006,total_energy,Table 2
Li2025_JPCA,Li et al. 2025,GPU4PySCF J. Phys. Chem. A 10.1021/acs.jpca.4c05876,2025,various,DFT,pc-3,GPU4PySCF vs LSDalton,GPU4PySCF,LSDalton,,,,<10,<0.006,total_energy,Table 2
Li2025_JPCA,Li et al. 2025,GPU4PySCF J. Phys. Chem. A 10.1021/acs.jpca.4c05876,2025,various,DFT,pc-1/2/3,GPU4PySCF vs ORCA (atomization),GPU4PySCF,ORCA,,,,<10,<0.006,atomization_energy,Table 2; atomization energy comparison
Rowan2025,Rowan Blog 2025,Vandezande GPU4PySCF Blog rowansci.com,2025,linear alkanes (C1-C20),r2SCAN,def2-TZVP,GPU4PySCF vs PySCF CPU,GPU4PySCF,PySCF_CPU,,,,<1,<0.001,total_energy,Figure 6; diff smaller than density fitting error
Rowan2025,Rowan Blog 2025,Vandezande GPU4PySCF Blog rowansci.com,2025,linear alkanes,r2SCAN,def2-SVP,GPU4PySCF vs PySCF CPU,GPU4PySCF,PySCF_CPU,,,,<1,<0.001,total_energy,all basis sets tested
Rowan2025,Rowan Blog 2025,Vandezande GPU4PySCF Blog rowansci.com,2025,linear alkanes,r2SCAN,def2-QZVP,GPU4PySCF vs PySCF CPU,GPU4PySCF,PySCF_CPU,,,,<1,<0.001,total_energy,all basis sets tested
Rowan2025,Rowan Blog 2025,Vandezande GPU4PySCF Blog rowansci.com,2025,linear alkanes,r2SCAN,def2-QZVPPD,GPU4PySCF vs PySCF CPU,GPU4PySCF,PySCF_CPU,,,,<1,<0.001,total_energy,all basis sets tested
JoltQC2025,JoltQC arXiv 2025,JoltQC arXiv:2507.09772,2025,various,various,various,JoltQC vs GPU4PySCF,JoltQC,GPU4PySCF,,,,,<0.006,total_energy,GPU4PySCF used as accuracy reference baseline
SciPy2025,Sahara et al. 2025,SciPy Proceedings dvta2583,2025,CCl3CCl2PO3H2+4H2O (38 atoms),RPBE,DZP,PySCF vs SIESTA,PySCF,SIESTA,,,,,chemical_accuracy,total_energy,85 configurations; chemical accuracy maintained
```

---

## CSV 2: 속도/성능 비교 (Performance Benchmark)

```csv
source_id,source_short,year,molecule,method,basis_set,code,hardware,n_cores_or_gpu,wall_time_seconds,relative_speedup_vs,speedup_factor,cost_usd,notes
r2bench,r2compchem benchmark,2020,C20,B3LYP,6-31G(d),Gaussian 09,CPU,1,191.4,,,,"PySCF 1.7 era; old version"
r2bench,r2compchem benchmark,2020,C20,B3LYP,6-31G(d),ORCA 4,CPU,1,573.0,,,,"single core"
r2bench,r2compchem benchmark,2020,C20,B3LYP,6-31G(d),Turbomole 7,CPU,1,205.0,,,,"single core"
r2bench,r2compchem benchmark,2020,C20,B3LYP,6-31G(d),PySCF 1.7,CPU,1,1758.9,,,,"single core; old version; very tight defaults"
r2bench,r2compchem benchmark,2020,C20,B3LYP,6-31G(d),Gaussian 09,CPU,16,24.9,,,,"16 cores"
r2bench,r2compchem benchmark,2020,C20,B3LYP,6-31G(d),ORCA 4,CPU,16,45.5,,,,"16 cores"
r2bench,r2compchem benchmark,2020,C20,B3LYP,6-31G(d),Turbomole 7,CPU,16,14.2,,,,"16 cores"
r2bench,r2compchem benchmark,2020,C20,B3LYP,6-31G(d),PySCF 1.7,CPU,16,135.5,,,,"16 cores; old version"
SciPy2025,Sahara et al. 2025,2025,38-atom phosphate+4H2O,RPBE,DZP,SIESTA,CPU,,,,,,460.50,"85 configs total cost"
SciPy2025,Sahara et al. 2025,2025,38-atom phosphate+4H2O,RPBE,DZP,PySCF,CPU,,,SIESTA,3.7x,,125.35,"85 configs total cost"
SciPy2025,Sahara et al. 2025,2025,38-atom phosphate+4H2O,RPBE,DZP,GPU4PySCF,GPU,,,SIESTA,390x,,7.99,"85 configs total cost; GPU acceleration"
GH2334,GitHub #2334,2024,various,DFT,various,PySCF,CPU,,,,,,"Hessian much slower than ORCA/Gaussian; speed issue not accuracy"
GH2334,GitHub #2334,2024,various,DFT,various,ORCA,CPU,,,,,,"Hessian faster than PySCF CPU"
GH2334,GitHub #2334,2024,various,DFT,various,Gaussian,CPU,,,,,,"Hessian faster than PySCF CPU"
Rowan2025,Rowan Blog 2025,2025,linear alkanes,r2SCAN,def2-TZVP,GPU4PySCF,GPU,,,Psi4 CPU,10-50x,,"Figure benchmarks; GPU4PySCF significantly faster"
```

---

## CSV 3: 문헌 메타데이터 (Source Registry)

```csv
source_id,authors,title,journal_or_venue,year,doi_or_url,peer_reviewed,comparison_codes,comparison_type,key_finding
GPU4PySCF_v1,"Wu, X.; Sun, Q. et al.",Enhancing GPU-acceleration in the Python-based Simulations of Chemistry Framework,WIREs Comput. Mol. Sci.,2024,10.1002/wcms.70008 | arXiv:2404.09452,yes,Q-Chem 6.1,energy+gradient+solvation,Single-digit μHartree agreement across multiple functionals and basis sets
Li2025_JPCA,"Li, R.; Sun, Q.; Zhang, X.; Chan, G. K.-L.",Introducing GPU Acceleration into PySCF,J. Phys. Chem. A,2025,10.1021/acs.jpca.4c05876,yes,"GAMESS, ORCA, LSDalton",energy+atomization,μHartree agreement; most direct PySCF-ORCA comparison available
Pu2025_APL,"Pu, Z.; Sun, Q. et al.",Enhancing PySCF-based QC Simulations with Modern Hardware,APL Computational Physics,2025,10.1063/5.XXXXXX | arXiv:2506.06661,yes,GAMESS,S22 benchmark,Accuracy maintained with performance enhancements
SciPy2025,"Sahara et al.",Comparative Performance Analysis of Modern DFT Implementations,Proc. SciPy 2025,2025,proceedings.scipy.org/articles/dvta2583,yes,SIESTA,energy+speed+cost,Chemical accuracy maintained; 390x speedup with GPU4PySCF
JoltQC2025,various,Designing QC algorithms with JIT compilation,arXiv,2025,arXiv:2507.09772,preprint,GPU4PySCF,energy,GPU4PySCF used as accuracy reference baseline
Rowan2025,"Vandezande, J.",GPU-Accelerated DFT with GPU4PySCF,Rowan Scientific Blog,2025,rowansci.com/blog/gpu4pyscf,no,"Psi4, PySCF CPU",energy+speed,Energy diff smaller than density fitting error; 10-50x faster than Psi4
GH688,community,Total energy differences among pyscf and other codes,GitHub Issue #688,2024,github.com/pyscf/pyscf/issues/688,no,"Gaussian, GAMESS, NWChem",energy,~2.4 mHartree gap with default grid; resolved by grid refinement
GH2334,community,PySCF Hessian much slower than ORCA and Gaussian,GitHub Issue #2334,2024,github.com/pyscf/pyscf/issues/2334,no,"ORCA, Gaussian",speed (Hessian),CPU PySCF Hessian slower; GPU4PySCF addresses this
r2bench,r2compchem,benchmark-qm,GitHub,2020,github.com/r2compchem/benchmark-qm,no,"Gaussian 09, ORCA 4, Turbomole 7, NWChem, Psi4, etc.",speed,PySCF 1.7 slower on CPU; old version with tight defaults
PySCF_orig,"Sun, Q. et al.",PySCF: the Python-based simulations of chemistry framework,WIREs Comput. Mol. Sci.,2018,10.1002/wcms.1340,yes,,foundational,Original PySCF paper; ~1400 citations
PySCF_update,"Sun, Q. et al.",Recent developments in the PySCF program package,J. Chem. Phys.,2020,10.1063/5.0006074,yes,,foundational,PySCF update paper; standard reference
```

---

**파일 3개 정리:**

| 파일명                      | 내용                  | 행 수 | 용도                               |
| --------------------------- | --------------------- | ----- | ---------------------------------- |
| `energy_accuracy.csv`       | 에너지 비교 수치 전체 | 27행  | 그래프용 (μHartree 차이 막대/점)   |
| `performance_benchmark.csv` | 속도/비용 비교        | 17행  | 참고용 (슬라이드에는 안 넣을 예정) |
| `source_registry.csv`       | 문헌 메타데이터       | 11행  | 출처 추적/각주용                   |

`energy_accuracy.csv`에서 `energy_diff_microhartree` 컬럼이 그래프 y축 값이 됩니다. `<10` 같은 부등호 값은 Python에서 파싱할 때 숫자로 변환해야 하니, 로컬에서 `<10` → `10` (upper bound), `<1` → `1`로 처리하시면 됩니다.
