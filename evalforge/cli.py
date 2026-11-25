from __future__ import annotations

import argparse
import json
from pathlib import Path

from evalforge.exports import export_passing_jsonl, failure_test_draft
from evalforge.judge.judge import judge_trace
from evalforge.runner import load_scenarios, run_suite
from evalforge.synth.prompts import build_generation_prompt
from evalforge.tracing.store import TraceStore


def main() -> None:
    parser = argparse.ArgumentParser(prog="evalforge")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("eval", help="Run the hand-written scenario suite and persist traces")
    synth = subparsers.add_parser("synth", help="Generate diverse cases with a configured LLM")
    synth.add_argument("--count", type=int, default=10)
    synth.add_argument("--refine-rounds", type=int, default=1)
    synth.add_argument("--output", type=Path, default=Path("generated-cases.json"))
    judge = subparsers.add_parser("judge", help="Judge traces and report alignment against human labels")
    judge.add_argument("--limit", type=int, default=50)
    export = subparsers.add_parser("export", help="Export human-approved passing traces as JSONL")
    export.add_argument("--output", type=Path, default=Path("fine-tuning.jsonl"))
    draft = subparsers.add_parser("failure-draft", help="Export a bad labeled trace as a test-case draft")
    draft.add_argument("trace_id", type=int)
    draft.add_argument("--output", type=Path, default=Path("failure-test-draft.json"))
    args = parser.parse_args()
    store = TraceStore()

    if args.command == "eval":
        result = run_suite(store)
        print(json.dumps({key: value for key, value in result.items() if key != "results"}, indent=2))
        for row in result["results"]:
            print(f"{'PASS' if row['passed'] else 'FAIL'} {row['scenario']} (trace {row['trace_id']})")
        if result["passed"] != result["total"]:
            raise SystemExit(1)
    elif args.command == "synth":
        from evalforge.llm import chat_completion
        from evalforge.synth.prompts import REFINEMENT_PROMPT

        seed_cases = load_scenarios()["scenarios"]
        parsed = _parse_cases(chat_completion(build_generation_prompt(seed_cases, args.count)))
        feedback = _validate_cases(parsed, seed_cases)
        for _ in range(max(args.refine_rounds, 0)):
            prompt = REFINEMENT_PROMPT.format(
                cases=json.dumps(parsed, ensure_ascii=False),
                feedback=feedback or "No schema, duplicate, or tool-name issues were found.",
            )
            parsed = _parse_cases(chat_completion(prompt))
            feedback = _validate_cases(parsed, seed_cases)
        if feedback:
            raise SystemExit(f"Generated cases did not pass validation: {feedback}")
        args.output.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
        print(f"Wrote {len(parsed)} candidate cases to {args.output}; review before merging.")
    elif args.command == "judge":
        unjudged = [trace for trace in store.list_traces(limit=args.limit) if trace["judge_version"] is None]
        for trace in unjudged:
            judge_trace(store, trace)
        print(json.dumps(store.judge_alignment(), indent=2))
    elif args.command == "export":
        count = export_passing_jsonl(store, args.output)
        print(f"Exported {count} human-approved, assertion-passing examples to {args.output}.")
    elif args.command == "failure-draft":
        trace = next((row for row in store.list_traces(limit=100_000) if row["id"] == args.trace_id), None)
        if not trace or trace["is_good"] != 0:
            raise SystemExit("Trace not found or not human-labeled bad.")
        args.output.write_text(json.dumps(failure_test_draft(trace), indent=2), encoding="utf-8")
        print(f"Wrote test draft to {args.output}; set the expected behavior before adding it.")


def _parse_cases(raw: str) -> list[dict]:
    try:
        cases = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SystemExit(f"Generator did not return valid JSON: {error}") from error
    if not isinstance(cases, list) or not all(isinstance(case, dict) for case in cases):
        raise SystemExit("Generator response must be a JSON array of case objects.")
    return cases


def _validate_cases(cases: list[dict], seed_cases: list[dict]) -> str:
    required = {"id", "feature", "input", "expected_tool", "expected_output_contains"}
    tools = {None, "lookup_customer", "get_order", "request_refund", "create_support_ticket"}
    seen_inputs = {case["input"].strip().casefold() for case in seed_cases}
    seen_ids = {case["id"] for case in seed_cases}
    problems = []
    for index, case in enumerate(cases):
        missing = required - case.keys()
        if missing:
            problems.append(f"case {index}: missing {', '.join(sorted(missing))}")
            continue
        valid_strings = all(
            isinstance(case[field], str) and case[field].strip()
            for field in ("id", "feature", "input")
        )
        if not valid_strings:
            problems.append(f"case {index}: id, feature, and input must be non-empty strings")
        expected_tool = case["expected_tool"]
        if expected_tool is not None and (
            not isinstance(expected_tool, str) or expected_tool not in tools
        ):
            problems.append(f"case {index}: unknown expected_tool {case['expected_tool']!r}")
        if not isinstance(case["expected_output_contains"], str):
            problems.append(f"case {index}: expected_output_contains must be a string")
        if valid_strings:
            normalized_input = case["input"].strip().casefold()
            if normalized_input in seen_inputs:
                problems.append(f"case {index}: duplicate input")
            seen_inputs.add(normalized_input)
            if case["id"] in seen_ids:
                problems.append(f"case {index}: duplicate id")
            seen_ids.add(case["id"])
    return "; ".join(problems)


if __name__ == "__main__":
    main()
