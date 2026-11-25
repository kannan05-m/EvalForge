from __future__ import annotations

import json

from evalforge.app.crm import SupportAssistant
from evalforge.cli import _validate_cases
from evalforge.exports import export_passing_jsonl, failure_test_draft
from evalforge.runner import load_scenarios, run_suite
from evalforge.tests_eval import run_assertions
from evalforge.tracing.store import TraceStore


def test_scenario_suite_runs_and_traces_every_case(tmp_path):
    store = TraceStore(tmp_path / "traces.sqlite3")
    result = run_suite(store)

    traces = store.list_traces(limit=20)
    assert result["total"] == len(load_scenarios()["scenarios"]) == 10
    assert len(traces) == 10
    assert result["passed"] == result["total"] == 10
    assert all(trace["assertions_passed"] in (0, 1) for trace in traces)


def test_assertions_detect_missing_tool_and_uuid_leak():
    checks = run_assertions(
        user_input="Check order O-501",
        output="Order details: 3fa85f64-5717-4562-b3fc-2c963f66afa6",
        tool_calls=[],
        expected_tool="get_order",
    )

    assert not next(item for item in checks if item["name"] == "no_uuid_leak")["passed"]
    assert not next(item for item in checks if item["name"] == "expected_tool_called")["passed"]


def test_json_assertion_uses_user_request_and_validates_actual_json():
    invalid = run_assertions(
        user_input="Return JSON for order O-501.",
        output="The order is delivered.",
        tool_calls=[],
        expected_tool=None,
    )
    ordinary = run_assertions(
        user_input="Where is order O-501?",
        output="The order is delivered.",
        tool_calls=[],
        expected_tool=None,
    )

    assert not next(item for item in invalid if item["name"] == "valid_output_json")["passed"]
    assert next(item for item in ordinary if item["name"] == "valid_output_json")["passed"]


def test_no_order_identifier_does_not_call_order_tool():
    assistant = SupportAssistant()
    output, tool_calls = assistant.run("Can you tell me where my order is?")

    assert "order number" in output
    assert tool_calls == []


def test_export_requires_human_approval_and_assertion_pass(tmp_path):
    store = TraceStore(tmp_path / "traces.sqlite3")
    run_suite(store, scenarios=[load_scenarios()["scenarios"][6]])
    trace = store.list_traces(limit=1)[0]
    store.save_label(trace["id"], True, "Correct and useful.", "Order O-501 is delivered.")
    export_path = tmp_path / "approved.jsonl"

    assert export_passing_jsonl(store, export_path) == 1
    record = json.loads(export_path.read_text(encoding="utf-8").strip())
    assert record["messages"][1]["content"] == "Order O-501 is delivered."


def test_export_excludes_assistant_review_labels(tmp_path):
    store = TraceStore(tmp_path / "traces.sqlite3")
    run_suite(store, scenarios=[load_scenarios()["scenarios"][6]])
    trace = store.list_traces(limit=1)[0]
    store.save_label(trace["id"], True, "Assistant review.", "Reviewed answer.", source="assistant")

    assert export_passing_jsonl(store, tmp_path / "approved.jsonl") == 0


def test_bad_trace_failure_draft_preserves_scenario_context():
    draft = failure_test_draft({"id": 8, "feature": "refunds", "input": "Refund?", "critique": "Missing order check."})

    assert draft["feature"] == "refunds"
    assert draft["input"] == "Refund?"
    assert "expected behavior" in draft["review_note"]


def test_judge_alignment_reports_precision_and_recall(tmp_path):
    store = TraceStore(tmp_path / "traces.sqlite3")
    trace_ids = [
        store.add_trace(user_input=f"input {index}", tool_calls=[], output="output", prompt_version="v1")
        for index in range(4)
    ]
    store.save_label(trace_ids[0], True, "", "output")
    store.save_label(trace_ids[1], False, "", "output")
    store.save_label(trace_ids[2], True, "", "output")
    store.add_judge_result(trace_ids[0], "judge-v1", "", True)
    store.add_judge_result(trace_ids[1], "judge-v1", "", True)
    store.add_judge_result(trace_ids[2], "judge-v1", "", False)
    store.save_label(trace_ids[3], False, "Assistant review only.", "output", source="assistant")
    store.add_judge_result(trace_ids[3], "judge-v1", "", False)

    metrics = store.judge_alignment("judge-v1")
    assert metrics == {"n": 3, "precision": 0.5, "recall": 0.5, "tp": 1, "fp": 1, "fn": 1}


def test_synthetic_case_validation_rejects_seed_duplicates_and_unknown_tools():
    seeds = load_scenarios()["scenarios"]
    generated = [
        {
            "id": "new-case",
            "feature": "order_status",
            "input": seeds[0]["input"],
            "expected_tool": "delete_customer",
            "expected_output_contains": "done",
        }
    ]

    feedback = _validate_cases(generated, seeds)

    assert "duplicate input" in feedback
    assert "unknown expected_tool" in feedback
