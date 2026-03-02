"""Rendering helpers for result-level evaluation traces."""

from __future__ import annotations

from typing import Any

import streamlit as st


def render_result_inspector(trace: dict[str, Any] | None) -> None:
    if trace is None:
        st.info("Select a result to inspect detailed evaluation trace.")
        return

    st.subheader("Result Inspector")

    test_case = trace.get("test_case", {})
    model_output = trace.get("model_output", {})
    normalization = trace.get("normalization", {})
    oracle_eval = trace.get("oracle_evaluation", {})

    st.markdown("**A. Test Case**")
    c1, c2 = st.columns(2)
    c1.write(f"**test_case_id:** {test_case.get('test_case_id', '-')}")
    c1.write(f"**category:** {test_case.get('category', '-')}")
    c1.write(f"**test_source:** {test_case.get('test_source', '-')}")
    c2.write(f"**oracle_type:** {test_case.get('oracle_type', '-')}")
    c2.write(f"**run_id:** {trace.get('run_id', '-')}")
    st.markdown("**prompt**")
    st.code(str(test_case.get("prompt", "")), language="text")
    st.markdown("**expected_answer**")
    st.code(str(test_case.get("expected_answer", "")), language="text")

    st.markdown("**B. Model Output**")
    c3, c4 = st.columns(2)
    c3.write(f"**provider:** {model_output.get('provider', '-')}")
    c3.write(f"**model_name:** {model_output.get('model_name', '-')}")
    c3.write(f"**evaluation_mode:** {model_output.get('evaluation_mode', '-')}")
    c4.write(f"**latency_ms:** {model_output.get('latency_ms', '-')}")
    c4.write(f"**attempt_index:** {model_output.get('attempt_index', '-')}")
    st.markdown("**raw_output**")
    st.code(str(model_output.get("raw_output", "")), language="text")

    st.markdown("**C. Normalization**")
    c5, c6 = st.columns(2)
    c5.markdown("**normalized_expected**")
    c5.code(str(normalization.get("normalized_expected", "")), language="text")
    c6.markdown("**normalized_output**")
    c6.code(str(normalization.get("normalized_output", "")), language="text")

    st.markdown("**D. Oracle Evaluation Trace**")
    passed = bool(oracle_eval.get("is_correct", False))
    try:
        score_value = float(oracle_eval.get("score", 0.0) or 0.0)
    except (TypeError, ValueError):
        score_value = 0.0
    if passed:
        st.success(f"Pass | score={score_value:.3f}")
    else:
        st.error(f"Fail | score={score_value:.3f}")

    st.write(f"**error_type:** {oracle_eval.get('error_type', '') or '-'}")
    st.write(f"**explanation:** {oracle_eval.get('explanation', '') or '-'}")
    render_oracle_trace(oracle_eval.get("details", {}), str(oracle_eval.get("oracle_type", "")))

    with st.expander("E. Raw Payloads"):
        st.markdown("**Raw stored result fields**")
        st.json(trace.get("raw_result", {}))
        st.markdown("**Raw oracle details JSON**")
        st.code(str(trace.get("raw_oracle_details", "")), language="json")


def render_oracle_trace(details: dict[str, Any], oracle_type: str) -> None:
    if not details:
        st.info("No oracle details available for this result (legacy record or skipped evaluation).")
        return

    st.write(f"**oracle_type:** {oracle_type or '-'}")
    # Keep this generic so any oracle-specific fields are still visible during demos.
    st.json(details)
