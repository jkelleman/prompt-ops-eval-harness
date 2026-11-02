"""PromptOpsEvaluator: scores an agent pipeline against a suite of cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .contracts import AgentExecutionState
from .engine import (
    AgenticIntentCompiler,
    ApprovalRequiredError,
    GroundingError,
    IntentCompilationError,
    SimulatedLakehouseRuntime,
)

Expectation = Literal["verified", "reject_hallucination", "requires_approval"]


@dataclass(frozen=True)
class EvalCase:
    id: str
    intent: str
    expect: Expectation
    approved: bool = False
    source_types: dict[str, str] = field(default_factory=dict)


@dataclass
class CaseResult:
    case: EvalCase
    passed: bool
    outcome: str
    attempts: int = 0
    cu_used: float = 0.0
    healed: bool = False


@dataclass
class EvalReport:
    results: list[CaseResult]

    def _rate(self, pred) -> float:
        cases = [r for r in self.results if pred(r)]
        return sum(r.passed for r in cases) / len(cases) if cases else 1.0

    @property
    def pass_rate(self) -> float:
        return self._rate(lambda r: True)

    @property
    def schema_precision(self) -> float:
        """Share of compiled plans that were fully grounded and executed as expected."""
        return self._rate(lambda r: r.case.expect == "verified")

    @property
    def hallucination_detection_rate(self) -> float:
        return self._rate(lambda r: r.case.expect == "reject_hallucination")

    @property
    def guardrail_enforcement_rate(self) -> float:
        return self._rate(lambda r: r.case.expect == "requires_approval")

    @property
    def recovery_pass_rate(self) -> float:
        """Share of drift cases that self-healed to a verified write."""
        return self._rate(lambda r: bool(r.case.source_types))

    @property
    def total_cu(self) -> float:
        return sum(r.cu_used for r in self.results)

    def scorecard(self) -> str:
        rows = [
            ("Cases", f"{len(self.results)}"),
            ("Overall pass rate", f"{self.pass_rate:.1%}"),
            ("Schema precision", f"{self.schema_precision:.1%}"),
            ("Hallucination detection", f"{self.hallucination_detection_rate:.1%}"),
            ("Guardrail enforcement", f"{self.guardrail_enforcement_rate:.1%}"),
            ("Self-healing recovery", f"{self.recovery_pass_rate:.1%}"),
            ("Capacity Units used", f"{self.total_cu:.2f}"),
        ]
        width = max(len(k) for k, _ in rows)
        lines = [f"{k.ljust(width)}  {v}" for k, v in rows]
        failures = [r for r in self.results if not r.passed]
        if failures:
            lines.append("")
            lines += [f"FAIL {r.case.id}: {r.outcome}" for r in failures]
        return "\n".join(lines)


class PromptOpsEvaluator:
    def __init__(self, compiler: AgenticIntentCompiler, runtime: SimulatedLakehouseRuntime, cu_budget: float = 25.0):
        self.compiler = compiler
        self.runtime = runtime
        self.cu_budget = cu_budget

    def run_case(self, case: EvalCase) -> CaseResult:
        try:
            plan = self.compiler.compile(case.intent)
        except GroundingError as e:
            return CaseResult(case, case.expect == "reject_hallucination", f"rejected: {e}")
        except IntentCompilationError as e:
            return CaseResult(case, False, f"compile error: {e}")

        if case.expect == "reject_hallucination":
            return CaseResult(case, False, "hallucinated column was not caught")

        try:
            result = self.runtime.execute(
                plan, approved=case.approved, source_types=case.source_types, cu_budget=self.cu_budget
            )
        except ApprovalRequiredError as e:
            return CaseResult(case, case.expect == "requires_approval", f"blocked: {e}")

        if case.expect == "requires_approval":
            return CaseResult(case, False, "destructive write ran without approval", result.attempts, result.cu_used)

        ok = result.state is AgentExecutionState.VERIFIED
        return CaseResult(
            case,
            ok,
            result.state.value,
            result.attempts,
            result.cu_used,
            healed=bool(result.envelopes) and ok,
        )

    def run(self, cases: list[EvalCase]) -> EvalReport:
        return EvalReport([self.run_case(c) for c in cases])
