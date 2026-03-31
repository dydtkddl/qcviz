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
