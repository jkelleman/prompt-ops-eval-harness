import pytest
from pydantic import ValidationError

from eval_harness import (
    AgentExecutionState,
    ApprovalRequiredError,
    DEFAULT_SUITE,
    GroundingError,
    LakehouseExecutionPlan,
    PreCommitAssertion,
    WriteMode,
    build_evaluator,
)


def _plan(**overrides):
    data = dict(
        task_id="t1",
        target_lakehouse="sales_lh",
        target_table="orders_daily",
        write_mode=WriteMode.APPEND,
        columns=["order_id"],
        assertions=[PreCommitAssertion(name="rows", kind="row_count_min", threshold=1)],
    )
    data.update(overrides)
    return LakehouseExecutionPlan(**data)


def test_strict_contract_rejects_missing_assertions_and_unknown_fields():
    with pytest.raises(ValidationError):
        _plan(assertions=[])
    with pytest.raises(ValidationError):
        _plan(confidence="high")  # agents can't smuggle in extra fields
    with pytest.raises(ValidationError):
        _plan(write_mode="truncate")  # not a supported write mode


def test_hallucinated_columns_are_rejected_at_compile_time(compiler):
    with pytest.raises(GroundingError) as exc:
        compiler.compile("append into sales_lh.orders_daily columns order_id, gross_revenue")
    assert exc.value.unknown == ["gross_revenue"]


def test_destructive_writes_require_approval(compiler, runtime):
    plan = compiler.compile("overwrite into sales_lh.orders_daily columns order_id, order_date")
    assert plan.requires_approval
    with pytest.raises(ApprovalRequiredError):
        runtime.execute(plan)
    assert runtime.execute(plan, approved=True).state is AgentExecutionState.VERIFIED


def test_self_healing_patches_type_drift_in_memory(compiler, runtime):
    plan = compiler.compile("append into sales_lh.orders_daily columns order_id, order_date")
    result = runtime.execute(plan, source_types={"order_date": "string"})

    assert result.state is AgentExecutionState.VERIFIED
    assert result.attempts == 2
    (envelope,) = result.envelopes
    assert envelope.state is AgentExecutionState.HEALING
    assert envelope.remediation.to_type == "date"
    assert 'col("order_date").cast("date")' in result.code


def test_cu_budget_stops_runaway_retries(compiler, runtime):
    plan = compiler.compile("append into sales_lh.orders_daily columns order_id, order_date")
    result = runtime.execute(plan, source_types={"order_date": "string"}, cu_budget=3.0)
    assert result.state is AgentExecutionState.FAILED


def test_default_suite_scorecard():
    report = build_evaluator().run(DEFAULT_SUITE)
    assert report.pass_rate == 1.0, report.scorecard()
    assert report.hallucination_detection_rate == 1.0
    assert report.recovery_pass_rate == 1.0
    assert sum(r.healed for r in report.results) == 2
