"""
QCViz-MCP Advisor Package -- Experimentalist Autonomy Modules.

Provides intelligent assistance for experimental chemists performing
computational chemistry verification without specialist knowledge.

Version: 1.1.0
"""

__version__ = "1.1.0"

__all__ = [
    "PresetRecommender",
    "PresetRecommendation",
    "MethodsSectionDrafter",
    "MethodsDraft",
    "CalculationRecord",
    "ReproducibilityScriptGenerator",
    "LiteratureEnergyValidator",
    "ValidationRequest",
    "ValidationResult",
    "BondValidation",
    "ConfidenceScorer",
    "ConfidenceReport",
]

from qcviz_mcp.advisor.preset_recommender import (
    PresetRecommender,
    PresetRecommendation,
)
from qcviz_mcp.advisor.methods_drafter import (
    MethodsSectionDrafter,
    MethodsDraft,
    CalculationRecord,
)
from qcviz_mcp.advisor.script_generator import (
    ReproducibilityScriptGenerator,
)
from qcviz_mcp.advisor.literature_validator import (
    LiteratureEnergyValidator,
    ValidationRequest,
    ValidationResult,
    BondValidation,
)
from qcviz_mcp.advisor.confidence_scorer import (
    ConfidenceScorer,
    ConfidenceReport,
)
