"""
Layer 2 – Quantum-chemical calculations.

Components:
  • XTBRunner          – subprocess wrapper for xTB (GFN2-xTB)
  • PropertyCalculator – RDKit descriptors + xTB-derived properties
  • ConformerGenerator – systematic conformer search
  • CalculationQueue   – Celery/Redis task queue for async jobs
"""

from app.services.molecule_engine.layer2_calculation.xtb_runner import XTBRunner
from app.services.molecule_engine.layer2_calculation.property_calc import PropertyCalculator
from app.services.molecule_engine.layer2_calculation.conformer import ConformerGenerator
from app.services.molecule_engine.layer2_calculation.task_queue import CalculationQueue

__all__ = [
    "XTBRunner",
    "PropertyCalculator",
    "ConformerGenerator",
    "CalculationQueue",
]