# prompt-ops-eval-harness

[![CI](https://github.com/jkelleman/prompt-ops-eval-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/jkelleman/prompt-ops-eval-harness/actions/workflows/ci.yml)

An evaluation harness for **agentic lakehouse workflows**. It tests whether the
plans an AI agent proposes are safe to run *before* they reach Spark:

- **Strict contracts.** Every plan must validate against Pydantic v2 models. Extra
  fields, unknown write modes, and plans without pre-commit assertions are rejected.
- **Catalog grounding.** Columns and tables are checked against the lakehouse
  catalog, so hallucinated references never execute.
- **Guardrail gates.** Destructive writes (`OVERWRITE`, `DROP PARTITION`) stop until a
  human approves them.
- **Self-healing runtime.** When a run hits schema type drift, the interceptor
  proposes an in-memory AST-style cast patch and retries, within a Capacity Unit (CU) budget.

This is the reference implementation behind the
[Project Osmos case study](https://aiwithjen.com/work/project-osmos).

**[▶ Try the live demo](https://prompt-ops-eval-harness.streamlit.app)**: inject a
hallucination, simulate schema drift, and inspect the plan, PySpark, and self-healing diff.

> **Scope:** execution is **simulated**. The harness ships with a sample catalog and a
> deterministic runtime that reproduces real failure shapes (hallucinated columns,
> type drift, unapproved destructive writes), so evals run offline and in CI with no
> Fabric or Spark connection. Swap in your own catalog to evaluate a real agent's plans.

## Quick start

```bash
pip install -e ".[dev]"
pytest -v                 # contract, grounding, guardrail and self-healing tests
python -m eval_harness    # run the default eval suite and print the scorecard
```

Interactive demo:

```bash
pip install -e ".[demo]"
streamlit run app.py
```

## Scorecard (default suite)

Output of `python -m eval_harness` against the 10 bundled cases:

```text
Cases                    10
Overall pass rate        100.0%
Schema precision         100.0%
Hallucination detection  100.0%
Guardrail enforcement    100.0%
Self-healing recovery    100.0%
Capacity Units used      26.25
```

| Metric | What it measures |
| --- | --- |
| Schema precision | Grounded plans that compiled and executed to a verified write |
| Hallucination detection | Plans with invented tables/columns rejected at compile time |
| Guardrail enforcement | Destructive writes blocked without human approval |
| Self-healing recovery | Type-drift runs repaired in memory and verified |
| Capacity Units used | Illustrative, deterministic CU cost model across all attempts |

## Architecture

```text
intent ──► AgenticIntentCompiler ──► LakehouseExecutionPlan (Pydantic v2)
                 │                          │
                 ▼                          ▼
     LakehouseCatalogResolver       guardrail gate (destructive? → approval)
       (grounding check)                    │
                                            ▼
                               SimulatedLakehouseRuntime ──► VERIFIED
                                            │  ▲
                              type drift ───┘  │ cast patch + retry (CU budget)
                                               │
                                    SelfHealingInterceptor
```

| Module | Contents |
| --- | --- |
| `contracts.py` | `WriteMode`, `AgentExecutionState`, `PreCommitAssertion`, `LakehouseExecutionPlan`, `RemediationAction`, `AgentRecoveryEnvelope` |
| `engine.py` | `LakehouseCatalogResolver`, `AgenticIntentCompiler`, `render_pyspark`, `SelfHealingInterceptor`, `SimulatedLakehouseRuntime` |
| `evaluator.py` | `EvalCase`, `PromptOpsEvaluator`, `EvalReport` |
| `scenarios.py` | Sample catalog and the default suite |
| `app.py` | Streamlit demo: inject hallucinations, simulate drift, inspect plans and patches |

## Writing your own cases

```python
from eval_harness import EvalCase, build_evaluator

my_catalog = {"finance_lh": {"invoices": {"invoice_id": "bigint", "due_date": "date"}}}
cases = [
    EvalCase("ok", "append into finance_lh.invoices columns invoice_id, due_date", "verified"),
    EvalCase("made-up", "append into finance_lh.invoices columns invoice_id, risk_score", "reject_hallucination"),
]
print(build_evaluator(my_catalog).run(cases).scorecard())
```

## License

MIT © 2026 Jen Kelleman
