"""
ConformerGenerator – systematic conformer search and ranking.

Uses RDKit's ETKDG algorithm to generate multiple 3D conformers,
then optionally ranks them by MMFF energy or xTB single-point energy.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.services.molecule_engine.layer1_structure.rdkit_handler import _check_rdkit

logger = structlog.get_logger(__name__)


@dataclass
class Conformer:
    """A single conformer with energy and coordinates."""

    conformer_id: int
    energy: float | None = None      # kcal/mol (MMFF) or Hartree (xTB)
    energy_unit: str = "kcal/mol"
    rmsd_to_best: float = 0.0
    xyz_data: str = ""
    sdf_data: str = ""
    is_minimum: bool = False


@dataclass
class ConformerEnsemble:
    """Result of a conformer search."""

    smiles: str
    num_generated: int = 0
    num_converged: int = 0
    conformers: list[Conformer] = field(default_factory=list)
    best_conformer_id: int | None = None
    method: str = "ETKDG+MMFF"
    elapsed_seconds: float = 0.0


class ConformerGenerator:
    """Generate and rank conformer ensembles."""

    async def generate(
        self,
        smiles: str,
        *,
        num_conformers: int = 50,
        max_iterations: int = 500,
        rms_threshold: float = 0.5,
        energy_window: float = 10.0,  # kcal/mol above global minimum
        optimize: bool = True,
        num_threads: int = 1,
    ) -> ConformerEnsemble:
        """Generate conformers using ETKDG and rank by MMFF energy.

        Args:
            smiles: Input SMILES.
            num_conformers: Number of initial conformers to embed.
            max_iterations: Max MMFF optimization iterations.
            rms_threshold: RMSD threshold for deduplication (Å).
            energy_window: Keep conformers within this window (kcal/mol).
            optimize: Whether to MMFF-optimize.
            num_threads: RDKit thread count for embedding.
        """
        return await asyncio.to_thread(
            self._generate_sync,
            smiles,
            num_conformers,
            max_iterations,
            rms_threshold,
            energy_window,
            optimize,
            num_threads,
        )

    @staticmethod
    def _generate_sync(
        smiles: str,
        num_conformers: int,
        max_iterations: int,
        rms_threshold: float,
        energy_window: float,
        optimize: bool,
        num_threads: int,
    ) -> ConformerEnsemble:
        import time

        ensemble = ConformerEnsemble(smiles=smiles)

        if not _check_rdkit():
            return ensemble

        from rdkit import Chem
        from rdkit.Chem import AllChem, rdMolAlign

        t0 = time.perf_counter()

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return ensemble

        mol = Chem.AddHs(mol)

        # ── Embed ──
        params = AllChem.ETKDGv3()
        params.randomSeed = 42
        params.numThreads = num_threads
        params.pruneRmsThresh = rms_threshold

        cids = AllChem.EmbedMultipleConfs(mol, numConfs=num_conformers, params=params)
        ensemble.num_generated = len(cids)

        if not cids:
            return ensemble

        # ── Optimize ──
        energies: dict[int, float] = {}
        if optimize:
            results = AllChem.MMFFOptimizeMoleculeConfs(
                mol, maxIters=max_iterations, numThreads=num_threads
            )
            for cid, (converged, energy) in zip(cids, results):
                if converged == 0:  # 0 = converged
                    energies[cid] = energy
                    ensemble.num_converged += 1
                else:
                    energies[cid] = energy  # Keep even unconverged
        else:
            # Single-point MMFF energy
            for cid in cids:
                ff = AllChem.MMFFGetMoleculeForceField(
                    mol, AllChem.MMFFGetMoleculeProperties(mol), confId=cid
                )
                if ff:
                    energies[cid] = ff.CalcEnergy()

        if not energies:
            return ensemble

        # ── Rank & filter ──
        min_energy = min(energies.values())

        conformer_list: list[Conformer] = []
        for cid in sorted(energies, key=lambda c: energies[c]):
            e = energies[cid]
            if (e - min_energy) > energy_window:
                continue

            # RMSD to best
            rmsd = 0.0
            if conformer_list:
                best_cid = conformer_list[0].conformer_id
                rmsd = AllChem.GetConformerRMS(mol, best_cid, cid)

            conf_obj = Conformer(
                conformer_id=cid,
                energy=round(e, 4),
                energy_unit="kcal/mol",
                rmsd_to_best=round(rmsd, 4),
                sdf_data=Chem.MolToMolBlock(mol, confId=cid),
                xyz_data=Chem.MolToXYZBlock(mol, confId=cid),
                is_minimum=(cid == min(energies, key=energies.get)),
            )
            conformer_list.append(conf_obj)

        ensemble.conformers = conformer_list
        ensemble.best_conformer_id = conformer_list[0].conformer_id if conformer_list else None
        ensemble.elapsed_seconds = time.perf_counter() - t0

        logger.info(
            "conformers_generated",
            smiles=smiles[:50],
            generated=ensemble.num_generated,
            kept=len(conformer_list),
            elapsed=f"{ensemble.elapsed_seconds:.2f}s",
        )

        return ensemble