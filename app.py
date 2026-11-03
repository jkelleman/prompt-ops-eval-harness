"""Interactive Streamlit demo for prompt-ops-eval-harness.

Run locally:  pip install -e ".[demo]"  &&  streamlit run app.py
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent / "src"))

from eval_harness import (
    DEFAULT_SUITE,
    SAMPLE_CATALOG,
    AgenticIntentCompiler,
    ApprovalRequiredError,
    GroundingError,
    IntentCompilationError,
    LakehouseCatalogResolver,
    SelfHealingInterceptor,
    SimulatedLakehouseRuntime,
    build_evaluator,
    render_pyspark,
)

st.set_page_config(page_title="PromptOps Eval Harness", page_icon="🧪", layout="wide")

resolver = LakehouseCatalogResolver(SAMPLE_CATALOG)
compiler = AgenticIntentCompiler(resolver)
runtime = SimulatedLakehouseRuntime(resolver, SelfHealingInterceptor(resolver))

# --- Sidebar: catalog selection & test controls -----------------------------
st.sidebar.header("Fabric workspace")
st.sidebar.caption("Simulated catalog · no live Fabric connection")
lakehouse = st.sidebar.selectbox("Lakehouse", list(SAMPLE_CATALOG))
table = st.sidebar.selectbox("Delta table", list(SAMPLE_CATALOG[lakehouse]))
schema = SAMPLE_CATALOG[lakehouse][table]
st.sidebar.table({"column": list(schema), "type": list(schema.values())})

st.sidebar.header("Test controls")
mode = st.sidebar.radio("Write mode", ["append", "merge", "overwrite", "drop partition"])
columns = st.sidebar.multiselect("Columns", list(schema), default=list(schema)[:2])
inject_hallucination = st.sidebar.checkbox("Inject schema hallucination")
drift_column = st.sidebar.selectbox("Simulate Spark schema drift on", ["(none)", *columns])
approved = st.sidebar.checkbox("Human approval granted", value=False)
cu_budget = st.sidebar.slider("CU budget", 1.0, 40.0, 25.0, 0.5)

cols = list(columns) + (["projected_ltv_score"] if inject_hallucination else [])
intent = f"{mode} {'on' if mode == 'drop partition' else 'into'} {lakehouse}.{table}"
if cols:
    intent += " columns " + ", ".join(cols)

st.title("PromptOps Eval Harness")
st.caption("Contract validation, catalog grounding, guardrail gates and self-healing for lakehouse agents.")
st.code(intent, language="text")

# --- Compile & execute -------------------------------------------------------
plan = result = None
hallucinations: list[str] = []
status = ""
try:
    plan = compiler.compile(intent)
    source_types = {drift_column: "string"} if drift_column != "(none)" else {}
    result = runtime.execute(plan, approved=approved, source_types=source_types, cu_budget=cu_budget)
    status = result.state.value
except GroundingError as e:
    hallucinations = e.unknown
    status = "rejected (hallucination)"
except ApprovalRequiredError:
    status = "awaiting approval"
except IntentCompilationError as e:
    status = f"compile error: {e}"

m1, m2, m3, m4 = st.columns(4)
m1.metric("Run state", status)
m2.metric("Contract validation", "pass" if plan else "fail")
m3.metric("Hallucinations detected", len(hallucinations))
m4.metric("CU used / cap", f"{result.cu_used:.2f} / {cu_budget:.1f}" if result else f"0 / {cu_budget:.1f}")

if hallucinations:
    st.error(f"Rejected before execution. Not in catalog: {', '.join(hallucinations)}")
elif status == "awaiting approval":
    st.warning("Destructive write. Grant human approval in the sidebar to run it.")

tab_plan, tab_code, tab_assert, tab_heal, tab_suite = st.tabs(
    ["Execution plan", "Compiled PySpark", "Pre-commit assertions", "Self-healing", "Eval suite"]
)

with tab_plan:
    if plan:
        st.json(plan.model_dump(mode="json"))
    else:
        st.info("No valid plan. The contract layer rejected this intent.")

with tab_code:
    if result:
        st.code(result.code, language="python")
    elif plan:
        st.code(render_pyspark(plan), language="python")

with tab_assert:
    if plan:
        for a in plan.assertions:
            st.write(f"- **{a.name}** · `{a.kind}`" + (f" on `{a.column}`" if a.column else ""))

with tab_heal:
    if result and result.envelopes:
        for env in result.envelopes:
            st.write(f"Attempt {env.attempt}: `{env.error_message}`")
            if env.remediation:
                st.code(
                    f"- {env.remediation.patch_before}\n+ {env.remediation.patch_after}",
                    language="diff",
                )
        st.success(f"Final state: {result.state.value} after {result.attempts} attempt(s)")
    else:
        st.info("Pick a column under 'Simulate Spark schema drift' to watch the recovery loop.")

with tab_suite:
    report = build_evaluator(cu_budget=cu_budget).run(DEFAULT_SUITE)
    st.text(report.scorecard())
    st.dataframe(
        [
            {"case": r.case.id, "expect": r.case.expect, "passed": r.passed, "outcome": r.outcome}
            for r in report.results
        ],
        use_container_width=True,
    )
