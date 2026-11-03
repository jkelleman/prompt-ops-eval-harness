# prompt-ops-eval-harness

[![CI](https://github.com/jkelleman/prompt-ops-eval-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/jkelleman/prompt-ops-eval-harness/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**An eval harness that checks whether an AI agent's words match what it's allowed to do.**

When an agent says *"I'll append yesterday's orders to the sales table,"* that sentence
is a promise. This harness turns the promise into a structured plan, holds it to a
contract, grounds it against what actually exists, pauses for a human when the stakes
are high, and reports back in plain terms when something goes wrong. Every one of those
steps is a conversation design decision expressed as code.

**[▶ Try the live demo](https://prompt-ops-eval-harness.streamlit.app)** · inject a
hallucination, simulate schema drift, and watch the agent plan, pause, and recover.

## Why a conversation designer built an eval harness

Agentic conversation design doesn't stop at the reply. Once an agent can *act*, the
design surface extends to the plan it proposes, the moment it asks permission, and the
story it tells after a failure. Those moments need the same rigor as a prompt, and they
need to be testable.

| Design question | How the harness answers it |
| --- | --- |
| What is the agent allowed to say it will do? | **Strict contracts.** Plans validate against Pydantic v2 models. Extra fields, unknown actions, and plans with no success criteria are rejected. |
| Is the agent describing things that exist? | **Grounding.** Every table and column is checked against the catalog, so hallucinated references never run. |
| When should the agent stop and ask? | **Human-in-the-loop gates.** Destructive actions (`OVERWRITE`, `DROP PARTITION`) wait for explicit approval. |
| What does the agent say when it fails? | **Recovery envelopes.** Each failure produces a structured report: what broke, which attempt, and the fix it proposes. |
| How do we know it's working? | **Scorecards.** A suite of cases scores hallucination detection, guardrail enforcement, and self-healing as numbers you can track in CI. |

This is the reference implementation behind the
[Project Osmos case study](https://aiwithjen.com/work/project-osmos).

## What it tests

The domain is a data lakehouse, a place where a wrong sentence from an agent has real
consequences. The default suite covers four failure shapes:

1. **Grounded requests** that should run cleanly.
2. **Hallucinations**: the agent names a column or table that doesn't exist.
3. **Risky actions**: the agent wants to overwrite or drop data without asking.
4. **Drift**: the data arrives in a different shape than expected, and the agent has to
   notice, explain, and repair it within a cost budget.

> **Scope:** execution is **simulated**. A sample catalog and a deterministic runtime
> reproduce real failure shapes, so evals run offline and in CI with no Spark or
> Microsoft Fabric connection. Swap in your own catalog to evaluate a real agent's plans.

## Quick start

```bash
pip install -e ".[dev]"
pytest -v                 # contract, grounding, guardrail and self-healing tests
python -m eval_harness    # run the default suite and print the scorecard
```

Interactive demo:

```bash
pip install -e ".[demo]"
streamlit run app.py
```

## Scorecard (default suite)

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
| Schema precision | Grounded plans that ran to a verified result |
| Hallucination detection | Plans with invented tables or columns rejected before running |
| Guardrail enforcement | Destructive actions blocked without human approval |
| Self-healing recovery | Drift failures repaired and verified |
| Capacity Units used | Illustrative, deterministic cost across all attempts |

## How a request moves through the harness

```text
intent ──► AgenticIntentCompiler ──► LakehouseExecutionPlan (the agent's promise)
                 │                          │
                 ▼                          ▼
     LakehouseCatalogResolver       guardrail gate (destructive? → ask a human)
       (does this exist?)                   │
                                            ▼
                               SimulatedLakehouseRuntime ──► VERIFIED
                                            │  ▲
                                 drift ─────┘  │ proposed fix + retry (cost budget)
                                               │
                                    SelfHealingInterceptor
                                  (reports an AgentRecoveryEnvelope)
```

The agent moves through six explicit states: `planned`, `awaiting_approval`,
`running_remote`, `healing`, `verified`, `failed`. Naming the states is what makes the
experience designable: each one is a moment where the user should know what's happening.

| Module | Contents |
| --- | --- |
| `contracts.py` | The vocabulary: write modes, execution states, assertions, plans, recovery envelopes |
| `engine.py` | Intent compiler, catalog grounding, simulated runtime, self-healing interceptor |
| `evaluator.py` | `EvalCase`, `PromptOpsEvaluator`, `EvalReport` and the scorecard |
| `scenarios.py` | Sample catalog and the default suite |
| `app.py` | Streamlit demo |

## Write your own cases

```python
from eval_harness import EvalCase, build_evaluator

my_catalog = {"finance_lh": {"invoices": {"invoice_id": "bigint", "due_date": "date"}}}
cases = [
    EvalCase("ok", "append into finance_lh.invoices columns invoice_id, due_date", "verified"),
    EvalCase("made-up", "append into finance_lh.invoices columns invoice_id, risk_score", "reject_hallucination"),
]
print(build_evaluator(my_catalog).run(cases).scorecard())
```

## About

Built by **Jen Kelleman**, an AI content design engineer and agentic conversation
designer. I design how AI agents talk, ask, act, and recover, and I build the
evaluations that prove it works.

[aiwithjen.com](https://aiwithjen.com) · [More code](https://aiwithjen.com/code) · [GitHub](https://github.com/jkelleman)

## License

MIT © 2026 Jen Kelleman
