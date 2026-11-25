from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evalforge.app.crm import SupportAssistant
from evalforge.tests_eval import run_assertions
from evalforge.tracing.store import TraceStore


SCENARIO_FILE = Path(__file__).with_name("scenarios.yaml")


def load_scenarios(path: Path = SCENARIO_FILE) -> dict[str, Any]:
    # JSON is a valid YAML 1.2 subset; this keeps the starter runnable without a YAML dependency.
    return json.loads(path.read_text(encoding="utf-8"))


def run_suite(
    store: TraceStore, assistant: SupportAssistant | None = None, scenarios: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    assistant = assistant or SupportAssistant()
    suite = load_scenarios()
    cases = scenarios if scenarios is not None else suite["scenarios"]
    results: list[dict[str, Any]] = []
    for case in cases:
        output, calls = assistant.run(case["input"])
        serialized_calls = [
            {"name": call.name, "arguments": call.arguments, "result": call.result} for call in calls
        ]
        assertion_details = run_assertions(
            user_input=case["input"],
            output=output,
            tool_calls=serialized_calls,
            expected_tool=case["expected_tool"],
        )
        scenario_passed = (
            all(assertion["passed"] for assertion in assertion_details)
            and (case.get("expected_output_contains", "").lower() in output.lower())
        )
        if case.get("expected_output_contains") and case["expected_output_contains"].lower() not in output.lower():
            assertion_details.append(
                {
                    "name": "expected_output_contains",
                    "passed": False,
                    "message": f"Output contains {case['expected_output_contains']!r}",
                }
            )
        trace_id = store.add_trace(
            user_input=case["input"],
            tool_calls=serialized_calls,
            output=output,
            prompt_version=assistant.prompt_version,
            feature=case["feature"],
            scenario=case["id"],
            suite_version=suite["version"],
            assertions_passed=scenario_passed,
            assertion_details=assertion_details,
        )
        results.append(
            {
                "trace_id": trace_id,
                "scenario": case["id"],
                "feature": case["feature"],
                "passed": scenario_passed,
                "output": output,
                "assertions": assertion_details,
            }
        )
    return {"total": len(results), "passed": sum(row["passed"] for row in results), "results": results}
