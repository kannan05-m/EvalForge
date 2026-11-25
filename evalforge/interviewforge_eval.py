"""Run evaluation checks against a live InterviewForge pipeline.

Usage:
    export INTERVIEWFORGE_URL="https://<your-render-app>.onrender.com"
    python -m evalforge.interviewforge_eval real_cases/cases.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from evalforge.tracing.store import TraceStore

PROMPT_VERSION = os.environ.get("INTERVIEWFORGE_VERSION", "interviewforge-v1")
SEVERITY_LEVELS = {"low", "medium", "high"}
CALL_TIMEOUT_SECONDS = 180


def call_interviewforge(resume_pdf: Path, jd_text: str) -> dict[str, Any]:
    """POST the API's PDF upload and JD form fields to /api/analyze."""
    url = os.environ["INTERVIEWFORGE_URL"].rstrip("/")
    if not urlsplit(url).path or urlsplit(url).path == "/":
        url += "/api/analyze"
    if resume_pdf.suffix.lower() != ".pdf":
        raise ValueError("InterviewForge requires a PDF resume.")
    pdf_bytes = resume_pdf.read_bytes()
    if not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError(f"Resume file is not a PDF: {resume_pdf.name}")

    boundary = f"EvalForge-{uuid.uuid4().hex}"
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="resume"; filename="{resume_pdf.name}"\r\n'.encode(),
            b"Content-Type: application/pdf\r\n\r\n",
            pdf_bytes,
            b"\r\n",
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="jd"\r\n',
            b"Content-Type: text/plain; charset=utf-8\r\n\r\n",
            jd_text.encode("utf-8"),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=CALL_TIMEOUT_SECONDS) as response:
        result = json.loads(response.read())
    if not isinstance(result, dict):
        raise ValueError("InterviewForge API response must be a JSON object.")
    return result


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """Map the InterviewForge GraphState response to fields the checks need."""
    if not isinstance(raw, dict):
        raise TypeError("InterviewForge response must be an object.")
    raw_gaps = raw.get("gap_skills", raw.get("gaps", []))
    if not isinstance(raw_gaps, list):
        raise ValueError("InterviewForge 'gap_skills' field must be an array.")
    question_fields = (
        "mcq_questions",
        "project_questions",
        "behavioral_questions",
        "weak_spot_questions",
    )
    if any(field in raw for field in question_fields):
        raw_questions = []
        for field in question_fields:
            group = raw.get(field, [])
            if not isinstance(group, list):
                raise ValueError(f"InterviewForge '{field}' field must be an array.")
            raw_questions.extend(group)
    else:
        raw_questions = raw.get("questions", [])
    if not isinstance(raw_questions, list):
        raise ValueError("InterviewForge question fields must be arrays.")
    return {
        "gap_severity": str(raw.get("gap_severity", "")).lower(),
        "gaps": [
            str(gap.get("skill") or gap.get("name") or gap) if isinstance(gap, dict) else str(gap)
            for gap in raw_gaps
        ],
        "questions": [
            str(question.get("q") or question.get("question") or "")
            if isinstance(question, dict)
            else str(question)
            for question in raw_questions
        ],
    }


def _has(haystack: list[str], needle: str) -> bool:
    return any(needle.lower() in item.lower() for item in haystack)


def run_checks(
    case: dict[str, Any], output: dict[str, Any], latency: float
) -> list[dict[str, Any]]:
    gaps, questions = output["gaps"], output["questions"]
    checks: list[tuple[str, bool, str]] = []
    checks.append(
        (
            "schema_valid",
            output["gap_severity"] in SEVERITY_LEVELS
            and bool(questions)
            and all(question.strip() for question in questions),
            "gap_severity is low/medium/high and questions are present",
        )
    )

    if "expected_gap_severity" in case:
        checks.append(
            (
                "severity_matches",
                output["gap_severity"] == case["expected_gap_severity"],
                f"Expected severity {case['expected_gap_severity']!r}, got {output['gap_severity']!r}",
            )
        )

    missed = [skill for skill in case.get("must_flag_gaps", []) if not _has(gaps, skill)]
    checks.append(
        (
            "gap_recall",
            not missed,
            f"Missed real gaps: {missed}" if missed else "All known gaps flagged",
        )
    )

    false_positives = [
        skill for skill in case.get("must_not_flag", []) if _has(gaps, skill)
    ]
    checks.append(
        (
            "no_false_gaps",
            not false_positives,
            f"Flagged skills the resume already shows: {false_positives}"
            if false_positives
            else "No false gaps",
        )
    )

    min_questions = case.get("min_questions", 5)
    max_questions = case.get("max_questions", 25)
    checks.append(
        (
            "question_count",
            min_questions <= len(questions) <= max_questions,
            f"{len(questions)} questions (want {min_questions}-{max_questions})",
        )
    )

    if output["gap_severity"] == "high" and gaps:
        gap_words = {
            word
            for gap in gaps
            for word in re.findall(r"[a-z+#.]{3,}", gap.lower())
        }
        targeting = sum(
            any(word in question.lower() for word in gap_words) for question in questions
        )
        share = targeting / len(questions) if questions else 0
        min_share = case.get("min_gap_question_share", 0.4)
        checks.append(
            (
                "questions_match_gap_severity",
                share >= min_share,
                f"{share:.0%} of questions target gaps (want >= {min_share:.0%})",
            )
        )

    normalized_questions = [
        re.sub(r"\W+", " ", question.lower()).strip() for question in questions
    ]
    checks.append(
        (
            "no_duplicate_questions",
            len(set(normalized_questions)) == len(normalized_questions),
            "No duplicate questions",
        )
    )
    max_latency = case.get("max_latency_s", 120)
    checks.append(
        ("latency_ok", latency <= max_latency, f"Latency {latency:.1f}s (limit {max_latency}s)")
    )
    return [
        {"name": name, "passed": bool(passed), "message": message}
        for name, passed, message in checks
    ]


def _resolve_case_file(base: Path, relative_path: str) -> Path:
    resolved_base = base.resolve()
    resolved_path = (resolved_base / relative_path).resolve()
    if not resolved_path.is_relative_to(resolved_base):
        raise ValueError(f"Case file must stay inside {resolved_base}: {relative_path}")
    if not resolved_path.is_file():
        raise FileNotFoundError(f"Case file does not exist: {relative_path}")
    return resolved_path


def _read_case_text(base: Path, relative_path: str) -> str:
    return _resolve_case_file(base, relative_path).read_text(encoding="utf-8")


def run(
    cases_path: Path,
    store: TraceStore | None = None,
    caller: Callable[[Path, str], dict[str, Any]] = call_interviewforge,
) -> dict[str, Any]:
    store = store or TraceStore()
    document = json.loads(cases_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("cases"), list):
        raise ValueError("Cases file must contain a JSON object with a 'cases' array.")
    cases = document["cases"]
    if not cases:
        raise ValueError("Cases file must contain at least one evaluation case.")
    suite_version = str(document.get("version", "real-cases-v1"))
    base = cases_path.resolve().parent

    inputs = []
    for case in cases:
        resume_pdf = _resolve_case_file(base, case["resume_path"])
        jd_text = _read_case_text(base, case["jd_path"])
        inputs.append((case, resume_pdf, jd_text))

    rows = []
    for case, resume_pdf, jd_text in inputs:
        start = time.perf_counter()
        error = None
        try:
            output = normalize(caller(resume_pdf, jd_text))
        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            output = {"gap_severity": "", "gaps": [], "questions": []}
            error = f"Pipeline call failed ({type(exc).__name__})."
        latency = time.perf_counter() - start
        details = run_checks(case, output, latency)
        if error:
            details.append({"name": "pipeline_call", "passed": False, "message": error})
        passed = all(detail["passed"] for detail in details)
        store.add_trace(
            user_input=f"resume={case['resume_path']} jd={case['jd_path']}",
            tool_calls=[
                {
                    "name": "interviewforge",
                    "arguments": {
                        "gaps": output["gaps"],
                        "gap_severity": output["gap_severity"],
                    },
                    "result": {},
                }
            ],
            output="\n".join(
                f"{index + 1}. {question}"
                for index, question in enumerate(output["questions"])
            )
            or (error or ""),
            prompt_version=PROMPT_VERSION,
            feature="interviewforge",
            scenario=case["id"],
            suite_version=suite_version,
            assertions_passed=passed,
            assertion_details=details,
        )
        rows.append(
            {
                "id": case["id"],
                "passed": passed,
                "failed_checks": [
                    detail["name"] for detail in details if not detail["passed"]
                ],
            }
        )
    return {"total": len(rows), "passed": sum(row["passed"] for row in rows), "rows": rows}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Evaluate InterviewForge against labeled resume/JD cases.")
    parser.add_argument(
        "cases",
        nargs="?",
        type=Path,
        default=Path("real_cases/cases.json"),
        help="case manifest (default: real_cases/cases.json)",
    )
    args = parser.parse_args(argv)
    result = run(args.cases)
    for row in result["rows"]:
        suffix = "" if row["passed"] else f"  -> {', '.join(row['failed_checks'])}"
        print(f"{'PASS ' if row['passed'] else 'FAIL '}{row['id']}{suffix}")
    print(f"\n{result['passed']}/{result['total']} cases passed")
    raise SystemExit(0 if result["passed"] == result["total"] else 1)


if __name__ == "__main__":
    main()
