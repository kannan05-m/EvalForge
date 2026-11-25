from __future__ import annotations

import json

import streamlit as st

from evalforge.tracing.store import TraceStore

st.set_page_config(page_title="EvalForge", layout="wide")
st.title("EvalForge · CRM trace review")
store = TraceStore()
all_traces = store.list_traces(limit=100_000)
features = sorted({row["feature"] for row in all_traces if row["feature"]})
selected_feature = st.selectbox("Feature", ["All", *features])
filtered = [row for row in all_traces if selected_feature == "All" or row["feature"] == selected_feature]
scenarios = sorted({row["scenario"] for row in filtered if row["scenario"]})
selected_scenario = st.selectbox("Scenario", ["All", *scenarios])
filtered = [row for row in filtered if selected_scenario == "All" or row["scenario"] == selected_scenario]

rates = store.pass_rates()
if rates:
    st.subheader("Assertion pass rates by prompt and suite version")
    for row in rates:
        rate = row["passed"] / row["total"] if row["total"] else 0
        st.write(f"{row['day']} · {row['prompt_version']} / {row['suite_version']}: {rate:.0%} ({row['passed']}/{row['total']})")
alignment = store.judge_alignment()
st.subheader("Judge alignment vs. human labels")
left, middle, right = st.columns(3)
left.metric("Labeled traces judged", alignment["n"])
middle.metric("Precision", "—" if alignment["precision"] is None else f"{alignment['precision']:.1%}")
right.metric("Recall", "—" if alignment["recall"] is None else f"{alignment['recall']:.1%}")

st.subheader("Review traces")
for trace in filtered:
    with st.expander(f"#{trace['id']} · {trace['scenario'] or 'ad hoc'} · {trace['created_at']}"):
        st.caption(f"Prompt: {trace['prompt_version']} · Suite: {trace['suite_version']}")
        st.markdown("**Input**")
        st.write(trace["input"])
        st.markdown("**Tool calls**")
        st.code(json.dumps(json.loads(trace["tool_calls"]), indent=2), language="json")
        st.markdown("**Assistant output**")
        st.write(trace["output"])
        if trace["judge_version"]:
            st.info(f"Judge ({trace['judge_version']}): {'good' if trace['judge_is_good'] else 'bad'} — {trace['judge_critique']}")
        with st.form(f"label-{trace['id']}"):
            source_options = ["Human", "Assistant"]
            source_index = 1 if trace["label_source"] == "assistant" else 0
            review_source = st.radio("Review source", source_options, index=source_index, horizontal=True)
            label_options = ["Choose a label", "Good", "Bad"]
            label_index = 1 if trace["is_good"] == 1 else 2 if trace["is_good"] == 0 else 0
            label = st.radio("Question quality", label_options, index=label_index, horizontal=True)
            critique = st.text_area("Critique", value=trace["critique"] or "")
            final_output = st.text_area("Editable final output", value=trace["final_output"] or trace["output"])
            submitted = st.form_submit_button("Save label")
            if submitted:
                if label == "Choose a label":
                    st.error("Choose Good or Bad before saving.")
                else:
                    store.save_label(
                        trace["id"],
                        label == "Good",
                        critique,
                        final_output,
                        source=review_source.lower(),
                    )
                    st.success("Label saved. Rerun the app to refresh exports and metrics.")
