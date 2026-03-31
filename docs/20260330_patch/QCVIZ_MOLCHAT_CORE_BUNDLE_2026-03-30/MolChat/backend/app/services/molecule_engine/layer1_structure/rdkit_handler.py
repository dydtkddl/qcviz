"""
RDKitHandler – core cheminformatics operations backed by RDKit.

All methods are async-compatible by running CPU-bound RDKit calls
inside ``asyncio.to_thread()`` so they never block the event loop.

Thread-safety: RDKit Mol objects are NOT thread-safe, so every
function creates its own Mol from SMILES/SDF. No shared state.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Lazy import to avoid import-time crash if RDKit is missing
_RDKIT_AVAILABLE: bool | None = None


def _check_rdkit() -> bool:
    global _RDKIT_AVAILABLE
    if _RDKIT_AVAILABLE is None:
        try:
            from rdkit import Chem  # noqa: F401

            _RDKIT_AVAILABLE = True
        except ImportError:
            _RDKIT_AVAILABLE = False
            logger.error("rdkit_not_available")
    return _RDKIT_AVAILABLE


class RDKitHandler:
    """Async wrapper around common RDKit cheminformatics operations."""

    # ═══════════════════════════════════════════
    # Parsing
    # ═══════════════════════════════════════════

    async def parse_smiles(self, smiles: str) -> bool:
        """Return True if the SMILES string is valid."""
        return await asyncio.to_thread(self._parse_smiles_sync, smiles)

    @staticmethod
    def _parse_smiles_sync(smiles: str) -> bool:
        if not _check_rdkit():
            return False
        from rdkit import Chem

        mol = Chem.MolFromSmiles(smiles)
        return mol is not None

    async def canonical_smiles(self, smiles: str) -> str | None:
        """Return the canonical SMILES or None if invalid."""
        return await asyncio.to_thread(self._canonical_smiles_sync, smiles)

    @staticmethod
    def _canonical_smiles_sync(smiles: str) -> str | None:
        if not _check_rdkit():
            return None
        from rdkit import Chem

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        return Chem.MolToSmiles(mol, canonical=True)

    async def count_atoms(self, smiles: str) -> int:
        """Count heavy atoms (non-hydrogen) from SMILES."""
        return await asyncio.to_thread(self._count_atoms_sync, smiles)

    @staticmethod
    def _count_atoms_sync(smiles: str) -> int:
        if not _check_rdkit():
            return 0
        from rdkit import Chem

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return 0
        return mol.GetNumHeavyAtoms()

    # ═══════════════════════════════════════════
    # 3D Generation
    # ═══════════════════════════════════════════

    async def smiles_to_sdf(self, smiles: str, optimize: bool = True) -> str | None:
        """Generate a 3D SDF block from SMILES via ETKDG."""
        return await asyncio.to_thread(self._smiles_to_sdf_sync, smiles, optimize)

    @staticmethod
    def _smiles_to_sdf_sync(smiles: str, optimize: bool = True) -> str | None:
        if not _check_rdkit():
            return None
        from rdkit import Chem
        from rdkit.Chem import AllChem

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None

        mol = Chem.AddHs(mol)

        # ETKDG conformer generation
        params = AllChem.ETKDGv3()
        params.randomSeed = 42
        params.numThreads = 1
        result = AllChem.EmbedMolecule(mol, params)

        if result == -1:
            # Fallback: random coordinates
            AllChem.EmbedMolecule(mol, AllChem.ETKDG())

        if optimize:
            try:
                AllChem.MMFFOptimizeMolecule(mol, maxIters=500)
            except Exception:
                try:
                    AllChem.UFFOptimizeMolecule(mol, maxIters=500)
                except Exception:
                    pass

        return Chem.MolToMolBlock(mol)

    async def smiles_to_xyz(self, smiles: str) -> str | None:
        """Generate XYZ format from SMILES."""
        return await asyncio.to_thread(self._smiles_to_xyz_sync, smiles)

    @staticmethod
    def _smiles_to_xyz_sync(smiles: str) -> str | None:
        if not _check_rdkit():
            return None
        from rdkit import Chem
        from rdkit.Chem import AllChem

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None

        mol = Chem.AddHs(mol)
        params = AllChem.ETKDGv3()
        params.randomSeed = 42
        result = AllChem.EmbedMolecule(mol, params)

        if result == -1:
            return None

        AllChem.MMFFOptimizeMolecule(mol, maxIters=200)
        return Chem.MolToXYZBlock(mol)

    # ═══════════════════════════════════════════
    # Descriptors
    # ═══════════════════════════════════════════

    async def compute_descriptors(self, smiles: str) -> dict[str, Any]:
        """Compute a standard set of molecular descriptors."""
        return await asyncio.to_thread(self._compute_descriptors_sync, smiles)

    @staticmethod
    def _compute_descriptors_sync(smiles: str) -> dict[str, Any]:
        if not _check_rdkit():
            return {}
        from rdkit import Chem
        from rdkit.Chem import Descriptors, Lipinski, rdMolDescriptors

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return {}

        return {
            "molecular_weight": round(Descriptors.ExactMolWt(mol), 4),
            "logp": round(Descriptors.MolLogP(mol), 4),
            "tpsa": round(Descriptors.TPSA(mol), 4),
            "hbd": Lipinski.NumHDonors(mol),
            "hba": Lipinski.NumHAcceptors(mol),
            "rotatable_bonds": Lipinski.NumRotatableBonds(mol),
            "heavy_atom_count": mol.GetNumHeavyAtoms(),
            "ring_count": Descriptors.RingCount(mol),
            "aromatic_rings": Descriptors.NumAromaticRings(mol),
            "fraction_csp3": round(Descriptors.FractionCSP3(mol), 4),
            "num_stereocenters": len(Chem.FindMolChiralCenters(mol, includeUnassigned=True)),
            "qed": round(Descriptors.qed(mol), 4),
            "formal_charge": Chem.GetFormalCharge(mol),
            "num_radical_electrons": Descriptors.NumRadicalElectrons(mol),
            "molar_refractivity": round(Descriptors.MolMR(mol), 4),
            # Lipinski Rule of 5
            "lipinski_violations": sum([
                Descriptors.MolLogP(mol) > 5,
                Descriptors.ExactMolWt(mol) > 500,
                Lipinski.NumHDonors(mol) > 5,
                Lipinski.NumHAcceptors(mol) > 10,
            ]),
        }

    # ═══════════════════════════════════════════
    # Fingerprints
    # ═══════════════════════════════════════════

    async def morgan_fingerprint(
        self, smiles: str, radius: int = 2, n_bits: int = 2048
    ) -> list[int] | None:
        """Compute Morgan (circular) fingerprint as a bit vector."""
        return await asyncio.to_thread(
            self._morgan_fp_sync, smiles, radius, n_bits
        )

    @staticmethod
    def _morgan_fp_sync(smiles: str, radius: int, n_bits: int) -> list[int] | None:
        if not _check_rdkit():
            return None
        from rdkit import Chem
        from rdkit.Chem import AllChem

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None

        fp = AllChem.GetMorganFingerprintAsBitVect(mol, radius, nBits=n_bits)
        return list(fp)

    # ═══════════════════════════════════════════
    # InChI
    # ═══════════════════════════════════════════

    async def smiles_to_inchi(self, smiles: str) -> tuple[str | None, str | None]:
        """Return (InChI, InChIKey) from SMILES."""
        return await asyncio.to_thread(self._smiles_to_inchi_sync, smiles)

    @staticmethod
    def _smiles_to_inchi_sync(smiles: str) -> tuple[str | None, str | None]:
        if not _check_rdkit():
            return None, None
        from rdkit import Chem
        from rdkit.Chem.inchi import MolFromSmiles, MolToInchi, InchiToInchiKey

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None, None

        inchi = MolToInchi(mol)
        if inchi is None:
            return None, None

        inchikey = InchiToInchiKey(inchi)
        return inchi, inchikey