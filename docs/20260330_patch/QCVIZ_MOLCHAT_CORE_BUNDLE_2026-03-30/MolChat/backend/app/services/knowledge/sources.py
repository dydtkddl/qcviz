"""
KnowledgeSources – pre-built knowledge content for the RAG pipeline.

Sources:
  1. **Safety** – GHS hazard codes, toxicity data, handling precautions.
  2. **Property** – explanations of molecular properties (LogP, TPSA, etc.).
  3. **Ontology** – chemical classification, IUPAC naming, functional groups.
  4. **FAQ** – frequently asked chemistry questions and answers.

Data can be loaded from:
  • Hardcoded Python dicts (initial seed data).
  • JSON/JSONL files (bulk import).
  • External APIs (PubChem, Wikipedia — future).

This module provides ``seed_knowledge()`` to populate the knowledge base
on first startup.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.services.knowledge.indexer import KnowledgeIndexer

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════
# Seed data definitions
# ═══════════════════════════════════════════════

_SAFETY_CHUNKS: list[dict[str, Any]] = [
    {
        "title": "GHS Hazard Classification Overview",
        "content": (
            "The Globally Harmonized System (GHS) classifies chemicals into hazard categories: "
            "physical hazards (flammable, explosive, oxidizing), health hazards (acute toxicity, "
            "carcinogenicity, mutagenicity, reproductive toxicity), and environmental hazards "
            "(aquatic toxicity). Each hazard is identified by H-statements (e.g., H200–H400 series) "
            "and pictograms. When handling any chemical, consult the Safety Data Sheet (SDS) "
            "for specific precautions, PPE requirements, and emergency procedures."
        ),
        "source": "safety",
        "category": "ghs",
        "tags": ["GHS", "hazard", "classification", "safety"],
    },
    {
        "title": "Laboratory Chemical Handling Best Practices",
        "content": (
            "General laboratory safety principles: (1) Always wear appropriate PPE — lab coat, "
            "safety goggles, gloves matched to the chemical being handled. (2) Work in a fume hood "
            "when handling volatile or toxic substances. (3) Never pipette by mouth. (4) Label all "
            "containers with compound name, concentration, date, and hazard warnings. (5) Know the "
            "location of safety showers, eyewash stations, fire extinguishers, and spill kits. "
            "(6) Dispose of chemical waste according to institutional EHS guidelines — never pour "
            "chemicals down the drain unless specifically approved."
        ),
        "source": "safety",
        "category": "handling",
        "tags": ["lab safety", "PPE", "handling", "waste disposal"],
    },
    {
        "title": "Common Solvent Hazards",
        "content": (
            "Solvents are among the most frequently handled chemicals in laboratories. Key hazards: "
            "Dichloromethane (DCM) — suspected carcinogen, CNS depressant, use in fume hood. "
            "Diethyl ether — extremely flammable, forms explosive peroxides on storage. "
            "Methanol — toxic by ingestion and inhalation, can cause blindness. "
            "Acetonitrile — flammable, toxic, metabolized to cyanide. "
            "DMSO — rapidly penetrates skin and carries dissolved solutes into the body. "
            "THF — flammable, forms peroxides, irritant. "
            "Always check the SDS before using any solvent and use the minimum quantity needed."
        ),
        "source": "safety",
        "category": "solvents",
        "tags": ["solvents", "hazards", "DCM", "ether", "methanol"],
    },
]

_PROPERTY_CHUNKS: list[dict[str, Any]] = [
    {
        "title": "LogP (Partition Coefficient)",
        "content": (
            "LogP (octanol-water partition coefficient) measures a molecule's lipophilicity — "
            "its preference for a lipid (non-polar) environment over an aqueous (polar) one. "
            "LogP = log10([solute]octanol / [solute]water). "
            "A positive LogP indicates lipophilicity; negative indicates hydrophilicity. "
            "For oral drugs, ideal LogP is typically 1–3 (Lipinski guideline: ≤ 5). "
            "High LogP (>5) correlates with poor aqueous solubility, high plasma protein binding, "
            "and potential accumulation in fatty tissues. "
            "LogP can be measured experimentally (shake-flask method) or computed (CLogP, XLogP, ALogP). "
            "Related: LogD (pH-dependent distribution coefficient for ionizable molecules)."
        ),
        "source": "property",
        "category": "physicochemical",
        "tags": ["LogP", "lipophilicity", "partition coefficient", "solubility"],
    },
    {
        "title": "Topological Polar Surface Area (TPSA)",
        "content": (
            "TPSA is the sum of polar atom surface areas (N, O, S, and attached H atoms) "
            "computed from a 2D representation. It predicts passive membrane permeability: "
            "TPSA < 140 Å² generally indicates good oral absorption; TPSA < 90 Å² predicts "
            "blood-brain barrier penetration. TPSA is topology-based (fast, conformer-independent) "
            "unlike 3D polar surface area. "
            "Veber's rules: oral bioavailability is favorable when TPSA ≤ 140 Å² AND "
            "rotatable bonds ≤ 10. TPSA is widely used in drug discovery lead optimization."
        ),
        "source": "property",
        "category": "physicochemical",
        "tags": ["TPSA", "polar surface area", "permeability", "absorption"],
    },
    {
        "title": "Lipinski's Rule of Five",
        "content": (
            "Lipinski's Rule of Five (Ro5) predicts oral bioavailability of drug candidates. "
            "A compound is likely to have poor absorption if it violates more than one rule: "
            "(1) Molecular weight > 500 Da, (2) LogP > 5, (3) H-bond donors > 5, "
            "(4) H-bond acceptors > 10. The name 'Rule of Five' comes from all cutoffs being "
            "multiples of 5. Important exceptions: natural products, antibiotics, vitamins, "
            "and transporter substrates often violate Ro5 yet remain orally bioavailable. "
            "Ro5 was published by Christopher Lipinski in 1997 (Adv Drug Deliv Rev 23:3–25). "
            "Modern extensions include Veber's rules (TPSA, rotatable bonds) and the "
            "Beyond Rule of Five (bRo5) concept for larger molecules."
        ),
        "source": "property",
        "category": "drug_likeness",
        "tags": ["Lipinski", "Rule of Five", "drug-likeness", "oral bioavailability"],
    },
    {
        "title": "QED (Quantitative Estimate of Drug-likeness)",
        "content": (
            "QED is a composite score (0–1) combining eight molecular properties into a single "
            "drug-likeness metric: molecular weight, LogP, H-bond donors, H-bond acceptors, "
            "polar surface area, rotatable bonds, aromatic rings, and structural alerts. "
            "QED uses desirability functions based on the distribution of properties in approved "
            "oral drugs. A QED > 0.67 is considered 'favorable', while QED < 0.34 is 'unfavorable'. "
            "QED was introduced by Bickerton et al. (2012, Nature Chemistry 4:90–98). "
            "Unlike binary Lipinski filters, QED provides a continuous score that better captures "
            "the multi-objective nature of drug optimization."
        ),
        "source": "property",
        "category": "drug_likeness",
        "tags": ["QED", "drug-likeness", "scoring", "lead optimization"],
    },
    {
        "title": "HOMO-LUMO Gap",
        "content": (
            "The HOMO-LUMO gap is the energy difference between the Highest Occupied Molecular "
            "Orbital (HOMO) and the Lowest Unoccupied Molecular Orbital (LUMO). It is a key "
            "indicator of molecular stability and reactivity. A large gap (> 5 eV) indicates "
            "high kinetic stability and low chemical reactivity ('hard' molecule). A small gap "
            "(< 2 eV) suggests high reactivity and potential conductivity ('soft' molecule). "
            "In organic electronics, materials with small HOMO-LUMO gaps are sought for "
            "light absorption and charge transport. The gap can be computed with DFT or "
            "semi-empirical methods like GFN2-xTB. Units are typically eV (electron volts). "
            "Related: chemical hardness η = (ELUMO - EHOMO)/2, electronegativity χ = -(EHOMO + ELUMO)/2."
        ),
        "source": "property",
        "category": "quantum",
        "tags": ["HOMO", "LUMO", "gap", "reactivity", "orbital energy"],
    },
]

_ONTOLOGY_CHUNKS: list[dict[str, Any]] = [
    {
        "title": "Functional Group Classification",
        "content": (
            "Organic molecules are classified by their functional groups — specific atom arrangements "
            "that determine chemical reactivity: "
            "Hydroxyl (-OH): alcohols, phenols. Carbonyl (C=O): aldehydes (R-CHO), ketones (R-CO-R'). "
            "Carboxyl (-COOH): carboxylic acids. Amino (-NH2): amines. Amide (-CONH2): amides. "
            "Ester (-COOR): esters. Ether (-O-): ethers. Thiol (-SH): thiols. "
            "Nitro (-NO2): nitro compounds. Phosphate (-OPO3): organophosphates. "
            "Sulfonyl (-SO2-): sulfonamides, sulfones. Halides (-F, -Cl, -Br, -I): alkyl/aryl halides. "
            "Multiple functional groups on the same molecule create complex reactivity patterns."
        ),
        "source": "ontology",
        "category": "functional_groups",
        "tags": ["functional groups", "organic chemistry", "classification"],
    },
    {
        "title": "IUPAC Nomenclature Basics",
        "content": (
            "IUPAC systematic nomenclature provides unambiguous names for chemical compounds. "
            "For organic compounds: (1) Find the longest carbon chain (parent chain). "
            "(2) Number from the end nearest the first substituent. "
            "(3) Name substituents as prefixes with position numbers. "
            "(4) Suffix indicates the principal functional group: "
            "-ane (alkane), -ene (alkene), -yne (alkyne), -ol (alcohol), -al (aldehyde), "
            "-one (ketone), -oic acid (carboxylic acid), -amine (amine). "
            "Examples: 2-methylpropan-1-ol, 3-ethylpent-2-ene, 2,4-dinitrophenol. "
            "Stereochemistry: E/Z for alkenes, R/S for chiral centers, cis/trans for cyclic compounds."
        ),
        "source": "ontology",
        "category": "nomenclature",
        "tags": ["IUPAC", "nomenclature", "naming", "organic chemistry"],
    },
    {
        "title": "Molecular Representations: SMILES, InChI, and SMARTS",
        "content": (
            "SMILES (Simplified Molecular-Input Line-Entry System): a line notation for molecules. "
            "Atoms are written as element symbols; bonds as - (single), = (double), # (triple). "
            "Branches use parentheses; rings use digit pairs. Example: c1ccccc1 = benzene. "
            "Canonical SMILES: unique, deterministic form for each molecule. "
            "InChI (International Chemical Identifier): a layered canonical identifier. "
            "Format: InChI=1S/formula/connections/H-atoms/charge/stereochemistry. "
            "InChIKey: 27-character hash of InChI for database indexing (e.g., BSYNRYMUTXBXSQ-UHFFFAOYSA-N = aspirin). "
            "SMARTS: extension of SMILES for substructure queries, supports atom/bond wildcards. "
            "Example: [CX3](=O)[OX2H1] matches carboxylic acid groups."
        ),
        "source": "ontology",
        "category": "representations",
        "tags": ["SMILES", "InChI", "InChIKey", "SMARTS", "notation"],
    },
]

_FAQ_CHUNKS: list[dict[str, Any]] = [
    {
        "title": "What is a conformer?",
        "content": (
            "A conformer (conformational isomer) is one of many possible 3D arrangements of a "
            "molecule that arise from rotation around single bonds. Unlike constitutional isomers "
            "(different connectivity) or stereoisomers (different spatial arrangement of fixed bonds), "
            "conformers interconvert freely at room temperature. The lowest-energy conformer is the "
            "global minimum on the potential energy surface. Conformational analysis is important in "
            "drug design: the bioactive conformer may not be the lowest-energy one. Tools like ETKDG "
            "(RDKit), OMEGA, and molecular dynamics can generate conformer ensembles."
        ),
        "source": "ontology",
        "category": "faq",
        "tags": ["conformer", "3D structure", "energy", "rotation"],
    },
    {
        "title": "What is GFN2-xTB?",
        "content": (
            "GFN2-xTB is a semi-empirical quantum mechanical method developed by Stefan Grimme's group. "
            "GFN stands for 'Geometry, Frequency, Non-covalent interactions'; xTB means 'extended Tight Binding'. "
            "It provides reasonable accuracy for: geometry optimizations, vibrational frequencies, "
            "thermodynamic properties, non-covalent interactions, and conformer energies. "
            "GFN2-xTB covers most of the periodic table (Z=1–86) and handles molecules up to ~1000 atoms. "
            "Typical accuracy: bond lengths ±0.02 Å, angles ±2°, reaction energies ±5 kcal/mol. "
            "Speed: ~1000× faster than DFT (B3LYP/def2-SVP) for geometry optimization. "
            "Limitations: less reliable for transition metals, excited states, and very accurate energetics."
        ),
        "source": "ontology",
        "category": "faq",
        "tags": ["xTB", "GFN2", "semi-empirical", "quantum chemistry", "Grimme"],
    },
]


# ═══════════════════════════════════════════════
# Source manager
# ═══════════════════════════════════════════════

class KnowledgeSources:
    """Manage knowledge source data and seeding."""

    def __init__(self, indexer: KnowledgeIndexer) -> None:
        self._indexer = indexer

    async def seed_all(self, force: bool = False) -> dict[str, Any]:
        """Seed all built-in knowledge sources.

        Args:
            force: If True, delete existing data before re-seeding.
        """
        results: dict[str, Any] = {}

        sources = {
            "safety": _SAFETY_CHUNKS,
            "property": _PROPERTY_CHUNKS,
            "ontology": _ONTOLOGY_CHUNKS + _FAQ_CHUNKS,
        }

        for source_name, chunks in sources.items():
            if force:
                deleted = await self._indexer.delete_by_source(source_name)
                logger.info(
                    "seed_cleared",
                    source=source_name,
                    deleted=deleted,
                )

            result = await self._indexer.bulk_import(
                chunks, generate_embeddings=True
            )
            results[source_name] = result

        total = sum(r.get("imported", 0) for r in results.values())
        logger.info("seed_all_completed", total_imported=total, details=results)
        return results

    async def seed_from_file(
        self,
        file_path: str,
        source: str,
        *,
        force: bool = False,
    ) -> dict[str, int]:
        """Import knowledge chunks from a JSON or JSONL file.

        Expected format:
          JSON: [{"title": "...", "content": "...", "tags": [...]}]
          JSONL: one JSON object per line
        """
        import json
        from pathlib import Path

        path = Path(file_path)
        if not path.exists():
            logger.error("seed_file_not_found", path=file_path)
            return {"error": 1}

        chunks: list[dict[str, Any]] = []

        if path.suffix == ".jsonl":
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        data = json.loads(line)
                        data.setdefault("source", source)
                        chunks.append(data)
        else:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        item.setdefault("source", source)
                    chunks = data

        if force:
            await self._indexer.delete_by_source(source)

        result = await self._indexer.bulk_import(chunks, generate_embeddings=True)
        logger.info("seed_from_file_completed", path=file_path, **result)
        return result

    async def get_stats(self) -> dict[str, Any]:
        """Return statistics about the knowledge base."""
        return await self._indexer.stats()

    @staticmethod
    def available_sources() -> list[dict[str, str]]:
        """List all built-in knowledge source types."""
        return [
            {
                "name": "safety",
                "description": "GHS hazard data, handling precautions, solvent hazards",
                "chunk_count": str(len(_SAFETY_CHUNKS)),
            },
            {
                "name": "property",
                "description": "Molecular property explanations (LogP, TPSA, QED, HOMO-LUMO, etc.)",
                "chunk_count": str(len(_PROPERTY_CHUNKS)),
            },
            {
                "name": "ontology",
                "description": "Chemical classification, IUPAC naming, SMILES/InChI notation, FAQ",
                "chunk_count": str(len(_ONTOLOGY_CHUNKS) + len(_FAQ_CHUNKS)),
            },
        ]