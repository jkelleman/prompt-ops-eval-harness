"""prompt-ops-eval-harness: contracts, grounding and self-healing evals for lakehouse agents."""

from .contracts import (
    AgentExecutionState,
    AgentRecoveryEnvelope,
    LakehouseExecutionPlan,
    PreCommitAssertion,
    RemediationAction,
    WriteMode,
)
from .engine import (
    AgenticIntentCompiler,
    ApprovalRequiredError,
    GroundingError,
    IntentCompilationError,
    LakehouseCatalogResolver,
    SelfHealingInterceptor,
    SimulatedLakehouseRuntime,
    render_pyspark,
)
from .evaluator import EvalCase, EvalReport, PromptOpsEvaluator
from .scenarios import DEFAULT_SUITE, SAMPLE_CATALOG, build_evaluator

__all__ = [
    "DEFAULT_SUITE",
    "SAMPLE_CATALOG",
    "AgentExecutionState",
    "AgentRecoveryEnvelope",
    "AgenticIntentCompiler",
    "ApprovalRequiredError",
    "EvalCase",
    "EvalReport",
    "GroundingError",
    "IntentCompilationError",
    "LakehouseCatalogResolver",
    "LakehouseExecutionPlan",
    "PreCommitAssertion",
    "PromptOpsEvaluator",
    "RemediationAction",
    "SelfHealingInterceptor",
    "SimulatedLakehouseRuntime",
    "WriteMode",
    "build_evaluator",
    "render_pyspark",
]

__version__ = "0.1.0"
