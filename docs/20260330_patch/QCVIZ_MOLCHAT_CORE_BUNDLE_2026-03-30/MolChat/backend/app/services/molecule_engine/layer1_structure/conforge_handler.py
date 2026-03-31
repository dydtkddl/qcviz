"""
ConforgeHandler – high-quality 3D conformer generation using CDPKit CONFORGE.

CONFORGE produces physically realistic 3D structures that are far superior
to RDKit ETKDG for complex molecules (macrocycles, bridged rings, etc.).

Pipeline position: Stage 2 (after PubChem 3D, before RDKit fallback).
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_CDPKIT_AVAILABLE: bool | None = None


def _check_cdpkit() -> bool:
    global _CDPKIT_AVAILABLE
    if _CDPKIT_AVAILABLE is None:
        try:
            import CDPL.Chem  # noqa: F401
            import CDPL.ConfGen  # noqa: F401
            _CDPKIT_AVAILABLE = True
        except ImportError:
            _CDPKIT_AVAILABLE = False
            logger.warning("cdpkit_not_available")
    return _CDPKIT_AVAILABLE


class ConforgeHandler:
    """Async wrapper for CDPKit CONFORGE conformer generation."""

    def __init__(self, timeout_ms: int = 10000, max_atoms: int = 300):
        self._timeout_ms = timeout_ms
        self._max_atoms = max_atoms

    async def smiles_to_sdf(self, smiles: str) -> str | None:
        """Generate a 3D SDF block from SMILES using CONFORGE."""
        return await asyncio.to_thread(self._smiles_to_sdf_sync, smiles)

    def _smiles_to_sdf_sync(self, smiles: str) -> str | None:
        if not _check_cdpkit():
            return None

        import CDPL.Chem as Chem
        import CDPL.ConfGen as ConfGen

        t0 = time.perf_counter()

        try:
            # Handle multi-component SMILES: use largest fragment
            target_smiles = smiles
            if "." in smiles:
                fragments = smiles.split(".")
                # Pick the largest fragment by length (proxy for complexity)
                target_smiles = max(fragments, key=len)
                logger.debug("conforge_using_largest_fragment",
                           original_components=len(fragments),
                           selected=target_smiles[:60])

            # Parse SMILES
            mol = Chem.BasicMolecule()
            if not Chem.parseSMILES(target_smiles, mol):
                logger.warning("conforge_smiles_parse_failed", smiles=target_smiles[:80])
                return None

            if mol.numAtoms > self._max_atoms:
                logger.info("conforge_too_many_atoms", atoms=mol.numAtoms, max=self._max_atoms)
                return None

            # Prepare molecule (with error handling for each step)
            try:
                Chem.perceiveComponents(mol, False)
            except Exception:
                pass
            try:
                Chem.perceiveSSSR(mol, False)
            except Exception:
                logger.debug("conforge_sssr_fallback")
            try:
                Chem.setRingFlags(mol, False)
            except Exception:
                pass
            try:
                Chem.calcImplicitHydrogenCounts(mol, False)
            except Exception:
                pass
            try:
                Chem.perceiveHybridizationStates(mol, False)
            except Exception:
                pass
            try:
                Chem.setAromaticityFlags(mol, False)
            except Exception:
                pass
            try:
                Chem.makeHydrogenComplete(mol)
            except Exception:
                pass
            try:
                Chem.calcImplicitHydrogenCounts(mol, False)
                Chem.perceiveHybridizationStates(mol, False)
            except Exception:
                pass

            # Generate conformers
            cg = ConfGen.ConformerGenerator()
            cg.settings.timeout = self._timeout_ms
            cg.settings.minRMSD = 0.5

            status = cg.generate(mol)
            num_confs = cg.getNumConformers()

            elapsed = (time.perf_counter() - t0) * 1000

            if num_confs == 0:
                logger.warning("conforge_no_conformers", smiles=target_smiles[:80],
                             status=status, elapsed_ms=round(elapsed))
                return None

            # Get best conformer and convert to SDF
            conf = cg.getConformer(0)
            sdf = self._conformer_to_sdf(mol, conf)

            logger.info("conforge_success", atoms=mol.numAtoms,
                       conformers=num_confs, elapsed_ms=round(elapsed))
            return sdf

        except Exception as exc:
            logger.error("conforge_error", error=str(exc), smiles=smiles[:80])
            return None
    def _conformer_to_sdf(self, mol, conf) -> str:
        """Convert a CDPKit molecule + conformer data to V2000 SDF string."""
        import CDPL.Chem as Chem

        n_atoms = mol.numAtoms
        n_bonds = mol.numBonds

        lines = []
        # Header (3 lines)
        lines.append("CONFORGE_generated")
        lines.append("  CDPKit/CONFORGE  3D")
        lines.append("")

        # Counts line
        lines.append(f"{n_atoms:3d}{n_bonds:3d}  0  0  0  0  0  0  0999 V2000")

        # Atom block
        for i in range(n_atoms):
            atom = mol.getAtom(i)
            symbol = Chem.getSymbol(atom)
            # Fallback: if symbol is empty, derive from atomic number
            if not symbol or not symbol.strip():
                try:
                    anum = Chem.getType(atom)
                    ELEMENT_MAP = {1:"H",6:"C",7:"N",8:"O",9:"F",15:"P",16:"S",17:"Cl",35:"Br",53:"I"}
                    symbol = ELEMENT_MAP.get(anum, "X")
                except Exception:
                    symbol = "H"  # most likely hydrogen
            # Fallback: if symbol is empty, derive from atomic number
            if not symbol or not symbol.strip():
                try:
                    anum = Chem.getType(atom)
                    ELEMENT_MAP = {1:"H",6:"C",7:"N",8:"O",9:"F",15:"P",16:"S",17:"Cl",35:"Br",53:"I"}
                    symbol = ELEMENT_MAP.get(anum, "X")
                except Exception:
                    symbol = "H"  # most likely hydrogen
            vec = conf[i]
            x, y, z = vec[0], vec[1], vec[2]
            charge = 0
            try:
                charge = Chem.getFormalCharge(atom)
            except:
                pass
            # V2000 charge mapping: 0=0, 1=+3, 2=+2, 3=+1, 4=doublet, 5=-1, 6=-2, 7=-3
            chg_map = {0: 0, 1: 3, 2: 2, 3: 1, -1: 5, -2: 6, -3: 7}
            chg_val = chg_map.get(charge, 0)
            lines.append(
                f"{x:10.4f}{y:10.4f}{z:10.4f} {symbol:<3s} 0  {chg_val}  0  0  0  0  0  0  0  0  0  0"
            )

        # Bond block
        for i in range(n_bonds):
            bond = mol.getBond(i)
            a1 = mol.getAtomIndex(bond.getBegin()) + 1  # 1-indexed
            a2 = mol.getAtomIndex(bond.getEnd()) + 1
            order = Chem.getOrder(bond)
            lines.append(f"{a1:3d}{a2:3d}{order:3d}  0  0  0  0")

        # Properties + end
        lines.append("M  END")
        lines.append("$$$$")
        lines.append("")

        return "\n".join(lines)

    async def smiles_to_xyz(self, smiles: str) -> str | None:
        """Generate XYZ format from SMILES using CONFORGE."""
        return await asyncio.to_thread(self._smiles_to_xyz_sync, smiles)

    def _smiles_to_xyz_sync(self, smiles: str) -> str | None:
        if not _check_cdpkit():
            return None

        import CDPL.Chem as Chem
        import CDPL.ConfGen as ConfGen

        try:
            mol = Chem.BasicMolecule()
            if not Chem.parseSMILES(smiles, mol):
                return None

            Chem.perceiveComponents(mol, False)
            Chem.perceiveSSSR(mol, False)
            Chem.setRingFlags(mol, False)
            Chem.calcImplicitHydrogenCounts(mol, False)
            Chem.perceiveHybridizationStates(mol, False)
            Chem.setAromaticityFlags(mol, False)
            Chem.makeHydrogenComplete(mol)

            cg = ConfGen.ConformerGenerator()
            cg.settings.timeout = self._timeout_ms
            status = cg.generate(mol)

            if cg.getNumConformers() == 0:
                return None

            conf = cg.getConformer(0)
            return self._conformer_to_xyz(mol, conf)

        except Exception:
            return None

    def _conformer_to_xyz(self, mol, conf) -> str:
        """Convert CDPKit molecule + conformer to XYZ string."""
        import CDPL.Chem as Chem
        n = mol.numAtoms
        lines = [str(n), "Generated by CONFORGE (CDPKit)"]
        for i in range(n):
            atom = mol.getAtom(i)
            sym = Chem.getSymbol(atom)
            if not sym or not sym.strip():
                try:
                    anum = Chem.getType(atom)
                    ELEMENT_MAP = {1:"H",6:"C",7:"N",8:"O",9:"F",15:"P",16:"S",17:"Cl",35:"Br",53:"I"}
                    sym = ELEMENT_MAP.get(anum, "X")
                except Exception:
                    sym = "H"
            if not sym or not sym.strip():
                try:
                    anum = Chem.getType(atom)
                    ELEMENT_MAP = {1:"H",6:"C",7:"N",8:"O",9:"F",15:"P",16:"S",17:"Cl",35:"Br",53:"I"}
                    sym = ELEMENT_MAP.get(anum, "X")
                except Exception:
                    sym = "H"
            vec = conf[i]
            lines.append(f"{sym:<2s}  {vec[0]:12.6f}  {vec[1]:12.6f}  {vec[2]:12.6f}")
        lines.append("")
        return "\n".join(lines)
