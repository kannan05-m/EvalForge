# EvalForge

EvalForge is a small evaluation workbench for a deliberately limited customer-support CRM assistant. It is designed to make the evaluation loop visible: start with a baseline, write scenario-level assertions, inspect real traces, and fix failures rather than trusting a single aggregate score.

The assistant has four CRM tools: customer lookup, order lookup, refund-request recording, and support-ticket creation. Refunds are recorded as requests only; no external system is changed. Its local sample data is fictional. The first measured pass was **6/10 scenarios**: punctuation on order IDs, account-email phrasing, and support requests mentioning an account caused failures. The starter now fixes those scoped failures; the current version is re-measured by CI on each push and pull request. Treat the first-run figure as this local starter's baseline, not a result on production traffic.

## Run the baseline

Requires Python 3.11 or later.

```bash
python -m pip install -e ".[test]"
pytest
evalforge eval
```

Each evaluation run writes input, tool calls, output, assertion results, feature/scenario, prompt version, and suite version into `evalforge.sqlite3`. Set `EVALFORGE_DB` to store the database elsewhere.

## Review and learn

```bash
python -m pip install -e ".[ui]"
streamlit run viewer/app.py
```

Filter traces, label each response good/bad, record a critique, and edit its final output. Human and assistant review labels are distinguished; judge alignment and fine-tuning exports use human labels only. The dashboard reports assertion pass rates by date, prompt version, and suite version.

Synthetic test generation and the LLM judge use an OpenAI-compatible endpoint. They are opt-in: configure `OPENAI_API_KEY`, and optionally `OPENAI_BASE_URL` and `EVALFORGE_MODEL`, before running these commands. The generator seeds from the hand-written suite, validates candidates, and runs a refinement round by default; inspect generated cases before merging. Do not send sensitive trace data to a provider without reviewing its data-handling terms.

```bash
evalforge synth --count 20 --refine-rounds 1 --output generated-cases.json
evalforge judge --limit 50
```

Generated cases are candidates, not trusted tests; review them and add approved cases to [scenarios.yaml](evalforge/scenarios.yaml). The generation prompt supports seed-and-refine feedback through `evalforge.synth.prompts`.

Export only human-approved traces that also passed assertions:

```bash
evalforge export --output fine-tuning.jsonl
evalforge failure-draft TRACE_ID --output failure-test-draft.json
```

Failure drafts intentionally leave the expected tool/output for a human to decide. Never treat unreviewed traces as training data.

## Measuring improvement

Record a baseline with `evalforge eval`, make a focused prompt or assistant change, then rerun the same scenarios. Compare pass rates across prompt versions in the dashboard. Add reviewed failure modes as new scenarios so the suite grows with the system. Judge alignment is reported as precision and recall against human labels, not raw agreement. No performance numbers are claimed here: establish them from your own runs and reviewed traces.

## Evaluate InterviewForge

The optional live-pipeline adapter uses hand-labeled resume/JD cases and writes each result to the same SQLite trace store. Resume and JD text is kept under `real_cases/resumes/` and `real_cases/jds/`; both directories are Git-ignored. The included manifest has two strong-fit pairs from the supplied resumes and one supplied internship description. Add more weak-fit and mismatched-domain JDs before treating this small set as a broad benchmark.

```bash
export INTERVIEWFORGE_URL="https://<your-render-app>.onrender.com"
python -m evalforge.interviewforge_eval real_cases/cases.json
```

The adapter posts each resume PDF and JD as multipart form fields to `/api/analyze`, then normalizes the returned `GraphState` fields. It records only file paths—not resume or JD text—in local traces. Review the configured endpoint and its data handling before running with personal data.

On the supplied two-pair run, both cases passed the rule-based checks. A separate assistant review marked one question set Good and one Bad, with critiques saved as assistant reviews—not human ground truth. This small, strong-fit-only sample is not a broad quality benchmark.
