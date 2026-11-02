"""Sample catalog and default evaluation suite."""

from __future__ import annotations

from .engine import (
    AgenticIntentCompiler,
    Catalog,
    LakehouseCatalogResolver,
    SelfHealingInterceptor,
    SimulatedLakehouseRuntime,
)
from .evaluator import EvalCase, PromptOpsEvaluator

SAMPLE_CATALOG: Catalog = {
    "sales_lh": {
        "orders_daily": {
            "order_id": "bigint",
            "order_date": "date",
            "customer_id": "bigint",
            "region": "string",
            "net_amount": "decimal(18,2)",
        },
        "customers": {
            "customer_id": "bigint",
            "segment": "string",
            "signup_date": "date",
        },
    },
    "telemetry_lh": {
        "device_events": {
            "event_id": "string",
            "device_id": "string",
            "event_ts": "timestamp",
            "event_type": "string",
        },
    },
}

DEFAULT_SUITE: list[EvalCase] = [
    # Grounded plans that should run cleanly
    EvalCase("append-orders", "append into sales_lh.orders_daily columns order_id, order_date, net_amount", "verified"),
    EvalCase("merge-customers", "merge into sales_lh.customers columns customer_id, segment", "verified"),
    EvalCase("append-telemetry", "append into telemetry_lh.device_events", "verified"),
    # Hallucinated columns the contract layer must reject
    EvalCase("hallucinated-revenue", "append into sales_lh.orders_daily columns order_id, gross_revenue", "reject_hallucination"),
    EvalCase("hallucinated-churn", "merge into sales_lh.customers columns customer_id, churn_score", "reject_hallucination"),
    EvalCase("hallucinated-table", "append into sales_lh.order_lines columns order_id", "reject_hallucination"),
    # Destructive writes must stop at the guardrail gate
    EvalCase("overwrite-unapproved", "overwrite into sales_lh.orders_daily columns order_id, order_date", "requires_approval"),
    EvalCase("drop-partition-unapproved", "drop partition on telemetry_lh.device_events columns event_id partition event_ts", "requires_approval"),
    # Schema drift that self-healing should repair
    EvalCase(
        "drift-order-date",
        "overwrite into sales_lh.orders_daily columns order_id, order_date",
        "verified",
        approved=True,
        source_types={"order_date": "string"},
    ),
    EvalCase(
        "drift-event-ts",
        "append into telemetry_lh.device_events columns event_id, event_ts",
        "verified",
        source_types={"event_ts": "string"},
    ),
]


def build_evaluator(catalog: Catalog | None = None, cu_budget: float = 25.0) -> PromptOpsEvaluator:
    resolver = LakehouseCatalogResolver(catalog or SAMPLE_CATALOG)
    interceptor = SelfHealingInterceptor(resolver)
    runtime = SimulatedLakehouseRuntime(resolver, interceptor)
    return PromptOpsEvaluator(AgenticIntentCompiler(resolver), runtime, cu_budget=cu_budget)
