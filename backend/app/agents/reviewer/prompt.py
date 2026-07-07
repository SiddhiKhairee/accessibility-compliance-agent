import json

SYSTEM_PROMPT = """You are the Reviewer Agent in an accessibility compliance pipeline.

Given a detected axe-core violation, confirm whether it is a genuine WCAG
violation and provide a confidence score.

Respond with ONLY a JSON object, no markdown code fences, no commentary
before or after it, matching exactly this schema:
{"confirmed": true or false, "confidence_score": a number between 0 and 1, "reasoning": a 1-2 sentence explanation}"""


def build_user_prompt(wcag_rule: str, element_selector: str, html_snippet: str, message: str) -> str:
    violation = {
        "wcag_rule": wcag_rule,
        "element_selector": element_selector,
        "html_snippet": html_snippet,
        "message": message,
    }
    return f"Violation:\n{json.dumps(violation)}"
