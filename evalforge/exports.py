from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evalforge.tracing.store import TraceStore


def export_passing_jsonl(store: TraceStore, path: str | Path) -> int:
    traces = store.list_traces(limit=100_000)
    exported = 0
    with Path(path).open("w", encoding="utf-8") as file:
        for trace in traces:
            approved_output = trace["final_output"] or trace["output"]
            if trace["is_good"] != 1 or trace["assertions_passed"] != 1:
                continue
            file.write(
                json.dumps(
                    {"messages": [{"role": "user", "content": trace["input"]},
                                  {"role": "assistant", "content": approved_output}]},
                    ensure_ascii=False,
                )
                + "\n"
            )
            exported += 1
    return exported


def failure_test_draft(trace: dict[str, Any]) -> dict[str, Any]:
    critique = trace["critique"] or "Human-labeled bad trace."
    return {
        "id": f"reviewed-failure-{trace['id']}",
        "feature": trace["feature"],
        "input": trace["input"],
        "expected_tool": None,
        "expected_output_contains": "",
        "review_note": f"{critique} Decide expected behavior before adding this case.",
    }
