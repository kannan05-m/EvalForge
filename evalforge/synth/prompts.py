GENERATION_PROMPT = """\
You generate evaluation cases for a fictional customer-support CRM assistant.
Return only a JSON array with objects containing: id, feature, input, expected_tool,
expected_output_contains. Include diverse natural phrasing, ambiguity, missing identifiers,
invalid identifiers, and adversarial-but-benign requests. Never invent real personal data.
Seed cases: {seed_cases}
Refinement feedback from prior validation: {feedback}
Generate {count} new cases. Do not copy seed inputs.
"""

REFINEMENT_PROMPT = """\
Review these generated CRM evaluation cases for duplicates, missing edge cases, and invalid
expected tools. Return a JSON array of corrected cases only.
Generated cases: {cases}
Validation feedback: {feedback}
"""


def build_generation_prompt(seed_cases: list[dict], count: int, feedback: str = "") -> str:
    import json

    return GENERATION_PROMPT.format(
        seed_cases=json.dumps(seed_cases, ensure_ascii=False),
        feedback=feedback,
        count=count,
    )
