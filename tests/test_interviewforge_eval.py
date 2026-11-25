from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from evalforge.interviewforge_eval import normalize, run
from evalforge.tracing.store import TraceStore


def test_normalize_maps_interviewforge_graph_state_fields():
    output = normalize(
        {
            "gap_severity": "HIGH",
            "gap_skills": ["Kubernetes", "RTOS"],
            "mcq_questions": [{"q": "Which Kubernetes object?"}],
            "project_questions": [{"q": "Describe your project."}],
            "behavioral_questions": [{"q": "How did you collaborate?"}],
            "weak_spot_questions": [{"q": "How would you learn RTOS?"}],
        }
    )

    assert output == {
        "gap_severity": "high",
        "gaps": ["Kubernetes", "RTOS"],
        "questions": [
            "Which Kubernetes object?",
            "Describe your project.",
            "How did you collaborate?",
            "How would you learn RTOS?",
        ],
    }


def test_run_records_results_without_storing_resume_or_jd_text(tmp_path: Path):
    (tmp_path / "resumes").mkdir()
    (tmp_path / "jds").mkdir()
    (tmp_path / "resumes" / "resume.pdf").write_bytes(b"%PDF-private-resume")
    (tmp_path / "jds" / "job.txt").write_text("PRIVATE JOB DESCRIPTION", encoding="utf-8")
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "version": "suite-test",
                "cases": [
                    {
                        "id": "strong-fit",
                        "resume_path": "resumes/resume.pdf",
                        "jd_path": "jds/job.txt",
                        "expected_gap_severity": "low",
                        "must_not_flag": ["Python"],
                        "min_questions": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    store = TraceStore(tmp_path / "traces.sqlite3")
    caller_inputs = []

    def caller(resume_pdf: Path, jd: str) -> dict:
        caller_inputs.append((resume_pdf.read_bytes(), jd))
        return {
            "gap_severity": "low",
            "gaps": [],
            "questions": ["What Python projects have you built?"],
        }

    result = run(cases_path, store=store, caller=caller)
    trace = store.list_traces(limit=1)[0]

    assert result["passed"] == result["total"] == 1
    assert caller_inputs == [(b"%PDF-private-resume", "PRIVATE JOB DESCRIPTION")]
    assert trace["suite_version"] == "suite-test"
    assert "PRIVATE RESUME" not in trace["input"]
    assert "PRIVATE JOB DESCRIPTION" not in trace["input"]


def test_run_rejects_case_paths_outside_manifest_directory(tmp_path: Path):
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "invalid-path",
                        "resume_path": "../outside.txt",
                        "jd_path": "../outside.txt",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must stay inside"):
        run(cases_path, store=TraceStore(tmp_path / "traces.sqlite3"), caller=lambda *_: {})


def test_pipeline_timeout_is_reported_and_saved_as_failed_trace(tmp_path: Path):
    (tmp_path / "resume.pdf").write_bytes(b"%PDF-resume")
    (tmp_path / "jd.txt").write_text("job", encoding="utf-8")
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "timeout",
                        "resume_path": "resume.pdf",
                        "jd_path": "jd.txt",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    store = TraceStore(tmp_path / "traces.sqlite3")

    def timeout(*_args):
        raise TimeoutError("endpoint exceeded timeout")

    result = run(cases_path, store=store, caller=timeout)
    trace = store.list_traces(limit=1)[0]
    details = json.loads(trace["assertion_details"])

    assert result["rows"][0]["failed_checks"][-1] == "pipeline_call"
    assert trace["assertions_passed"] == 0
    assert any("Pipeline call failed (TimeoutError)." in detail["message"] for detail in details)


def test_call_uses_multipart_upload_and_appends_analyze_route(tmp_path: Path):
    from evalforge.interviewforge_eval import call_interviewforge

    resume_pdf = tmp_path / "resume.pdf"
    resume_pdf.write_bytes(b"%PDF-test")
    response = type("Response", (), {"read": lambda self: b'{"gap_severity":"low"}'})()
    context = type(
        "ResponseContext",
        (),
        {
            "__enter__": lambda self: response,
            "__exit__": lambda self, *_args: None,
        },
    )()

    with patch.dict(os.environ, {"INTERVIEWFORGE_URL": "https://example.test"}):
        with patch("evalforge.interviewforge_eval.urllib.request.urlopen", return_value=context) as urlopen:
            result = call_interviewforge(resume_pdf, "AI internship description")

    request = urlopen.call_args.args[0]
    request_body = request.data
    assert request.full_url == "https://example.test/api/analyze"
    assert request.headers["Content-type"].startswith("multipart/form-data; boundary=")
    assert b'name="resume"; filename="resume.pdf"' in request_body
    assert b'name="jd"' in request_body
    assert b"AI internship description" in request_body
    assert result == {"gap_severity": "low"}
