"""Catalog grounding, intent compilation, simulated execution and self-healing.

Execution is simulated: there is no live Spark or Fabric connection. The
simulator reproduces the failure shapes the harness is designed to test
(hallucinated columns, schema type drift) deterministically, so evaluations
are repeatable offline and in CI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .contracts import (
    AgentExecutionState,
    AgentRecoveryEnvelope,
    LakehouseExecutionPlan,
    PreCommitAssertion,
    RemediationAction,
    WriteMode,
)

# lakehouse -> table -> column -> type
Catalog = dict[str, dict[str, dict[str, str]]]


class GroundingError(ValueError):
    """The plan references tables or columns that are not in the catalog."""

    def __init__(self, message: str, unknown: list[str]):
        super().__init__(message)
        self.unknown = unknown


class IntentCompilationError(ValueError):
    """The intent could not be compiled into a plan."""


class ApprovalRequiredError(PermissionError):
    """A destructive write was attempted without human approval."""


@dataclass
class SparkTypeMismatch(Exception):
    """Simulated Spark AnalysisException for a column type drift."""

    column: str
    expected: str
    actual: str

    def __str__(self) -> str:
        return (
            f"AnalysisException: column '{self.column}' is {self.actual} "
            f"but the target expects {self.expected}"
        )


class LakehouseCatalogResolver:
    """Grounds agent plans against the real table schemas."""

    def __init__(self, catalog: Catalog):
        self.catalog = catalog

    def schema(self, lakehouse: str, table: str) -> dict[str, str]:
        try:
            return self.catalog[lakehouse][table]
        except KeyError:
            raise GroundingError(
                f"Unknown table {lakehouse}.{table}", [f"{lakehouse}.{table}"]
            ) from None

    def unknown_columns(self, lakehouse: str, table: str, columns: list[str]) -> list[str]:
        known = self.schema(lakehouse, table)
        return [c for c in columns if c not in known]

    def ground(self, plan: LakehouseExecutionPlan) -> None:
        unknown = self.unknown_columns(plan.target_lakehouse, plan.target_table, plan.columns)
        for a in plan.assertions:
            if a.column and a.column not in plan.columns and a.column not in unknown:
                if a.column not in self.schema(plan.target_lakehouse, plan.target_table):
                    unknown.append(a.column)
        if unknown:
            raise GroundingError(
                f"Hallucinated column(s) for {plan.qualified_table}: {', '.join(unknown)}",
                unknown,
            )


_INTENT = re.compile(
    r"^(?P<mode>append|merge|overwrite|drop partition)\s+"
    r"(?:into|on|in)\s+(?P<lh>[\w-]+)\.(?P<table>\w+)"
    r"(?:\s+columns\s+(?P<cols>[\w\s,]+?))?"
    r"(?:\s+partition\s+(?P<part>\w+))?\s*$",
    re.IGNORECASE,
)


class AgenticIntentCompiler:
    """Turns a constrained natural-language intent into a validated plan.

    Example intent: "append into sales_lh.orders_daily columns order_id, order_date"
    """

    def __init__(self, resolver: LakehouseCatalogResolver):
        self.resolver = resolver
        self._counter = 0

    def compile(self, intent: str) -> LakehouseExecutionPlan:
        m = _INTENT.match(intent.strip())
        if not m:
            raise IntentCompilationError(f"Could not parse intent: {intent!r}")

        mode = WriteMode(m["mode"].lower().replace(" ", "_"))
        lakehouse, table = m["lh"], m["table"]
        schema = self.resolver.schema(lakehouse, table)
        cols = [c.strip() for c in (m["cols"] or "").split(",") if c.strip()] or list(schema)

        assertions = [PreCommitAssertion(name="non_empty_write", kind="row_count_min", threshold=1)]
        key = cols[0]
        assertions.append(PreCommitAssertion(name=f"{key}_not_null", kind="not_null", column=key))
        if m["part"]:
            assertions.append(
                PreCommitAssertion(name="partition_present", kind="partition_exists", column=m["part"])
            )

        self._counter += 1
        plan = LakehouseExecutionPlan(
            task_id=f"task-{self._counter:04d}",
            target_lakehouse=lakehouse,
            target_table=table,
            write_mode=mode,
            columns=cols,
            assertions=assertions,
        )
        self.resolver.ground(plan)  # raises GroundingError on hallucinated columns
        return plan


def render_pyspark(plan: LakehouseExecutionPlan, casts: dict[str, str] | None = None) -> str:
    """Render the plan as the PySpark code the agent would submit."""
    casts = casts or {}
    lines = [f'df = spark.read.table("staging.{plan.target_table}")']
    select = []
    for c in plan.columns:
        expr = f'col("{c}")'
        if c in casts:
            expr = f'{expr}.cast("{casts[c]}")'
        select.append(f'{expr}.alias("{c}")' if c in casts else expr)
    lines.append(f"df = df.select({', '.join(select)})")
    spark_mode = {"append": "append", "merge": "append", "overwrite": "overwrite", "drop_partition": "overwrite"}
    lines.append(
        f'df.write.format("delta").mode("{spark_mode[plan.write_mode.value]}")'
        f'.saveAsTable("{plan.qualified_table}")'
    )
    return "\n".join(lines)


@dataclass
class ExecutionResult:
    state: AgentExecutionState
    code: str
    attempts: int
    cu_used: float
    envelopes: list[AgentRecoveryEnvelope] = field(default_factory=list)


class SelfHealingInterceptor:
    """Catches type drift at runtime and patches the code in memory."""

    def __init__(self, resolver: LakehouseCatalogResolver, max_attempts: int = 2):
        self.resolver = resolver
        self.max_attempts = max_attempts

    def remediate(self, plan: LakehouseExecutionPlan, err: SparkTypeMismatch, attempt: int) -> AgentRecoveryEnvelope:
        expected = self.resolver.schema(plan.target_lakehouse, plan.target_table).get(err.column)
        if expected is None:
            return AgentRecoveryEnvelope(
                task_id=plan.task_id,
                error_type="SparkTypeMismatch",
                error_message=str(err),
                attempt=attempt,
                state=AgentExecutionState.FAILED,
            )
        action = RemediationAction(
            kind="cast_column",
            column=err.column,
            from_type=err.actual,
            to_type=expected,
            patch_before=f'col("{err.column}")',
            patch_after=f'col("{err.column}").cast("{expected}").alias("{err.column}")',
        )
        return AgentRecoveryEnvelope(
            task_id=plan.task_id,
            error_type="SparkTypeMismatch",
            error_message=str(err),
            attempt=attempt,
            state=AgentExecutionState.HEALING,
            remediation=action,
        )


class SimulatedLakehouseRuntime:
    """Deterministic stand-in for a Fabric Spark session.

    `source_types` describes the staging data actually arriving; columns whose
    source type differs from the catalog type fail unless the code casts them.
    """

    # Capacity Unit cost model (illustrative, deterministic)
    BASE_CU = {"append": 2.0, "merge": 4.0, "overwrite": 5.0, "drop_partition": 3.0}
    PER_COLUMN_CU = 0.25

    def __init__(self, resolver: LakehouseCatalogResolver, interceptor: SelfHealingInterceptor):
        self.resolver = resolver
        self.interceptor = interceptor

    def _attempt_cost(self, plan: LakehouseExecutionPlan) -> float:
        return self.BASE_CU[plan.write_mode.value] + self.PER_COLUMN_CU * len(plan.columns)

    def execute(
        self,
        plan: LakehouseExecutionPlan,
        *,
        approved: bool = False,
        source_types: dict[str, str] | None = None,
        cu_budget: float = 25.0,
    ) -> ExecutionResult:
        if plan.requires_approval and not approved:
            raise ApprovalRequiredError(
                f"{plan.write_mode.value} on {plan.qualified_table} requires human approval"
            )

        schema = self.resolver.schema(plan.target_lakehouse, plan.target_table)
        source_types = source_types or {}
        casts: dict[str, str] = {}
        envelopes: list[AgentRecoveryEnvelope] = []
        cu = 0.0

        for attempt in range(1, self.interceptor.max_attempts + 2):
            code = render_pyspark(plan, casts)
            cu += self._attempt_cost(plan)
            if cu > cu_budget:
                return ExecutionResult(AgentExecutionState.FAILED, code, attempt, cu, envelopes)

            drift = next(
                (
                    c
                    for c in plan.columns
                    if c in source_types and source_types[c] != schema[c] and c not in casts
                ),
                None,
            )
            if drift is None:
                return ExecutionResult(AgentExecutionState.VERIFIED, code, attempt, cu, envelopes)

            if attempt > self.interceptor.max_attempts:
                break
            err = SparkTypeMismatch(column=drift, expected=schema[drift], actual=source_types[drift])
            envelope = self.interceptor.remediate(plan, err, attempt)
            envelopes.append(envelope)
            if envelope.remediation is None:
                break
            casts[envelope.remediation.column] = envelope.remediation.to_type

        return ExecutionResult(AgentExecutionState.FAILED, render_pyspark(plan, casts), attempt, cu, envelopes)
