from __future__ import annotations

import json
import re
from typing import Any


def run_assertions(
    *, user_input: str, output: str, tool_calls: list[dict[str, Any]], expected_tool: str | None
) -> list[dict[str, Any]]:
    checks = [
        ("non_empty_output", bool(output.strip()), "Assistant output is not empty"),
        ("no_uuid_leak", not re.search(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", output, re.I), "No UUID-like identifiers in output"),
        (
            "valid_output_json",
            "json" not in user_input.lower() or _is_valid_json(output),
            "Output is valid JSON when JSON was requested",
        ),
        (
            "expected_tool_called",
            expected_tool is None or any(call.get("name") == expected_tool for call in tool_calls),
            f"Expected tool {expected_tool!r} was called when required",
        ),
        (
            "no_unexpected_tools",
            all(call.get("name") in {"lookup_customer", "get_order", "request_refund", "create_support_ticket"} for call in tool_calls),
            "Only registered CRM tools were called",
        ),
        (
            "no_tool_for_missing_order",
            not (expected_tool == "get_order" and not re.search(r"\bO-\d+\b", user_input) and tool_calls),
            "No order lookup is made without an order number",
        ),
    ]
    return [{"name": name, "passed": passed, "message": message} for name, passed, message in checks]


def _is_valid_json(output: str) -> bool:
    try:
        json.loads(output)
        return True
    except json.JSONDecodeError:
        return False
