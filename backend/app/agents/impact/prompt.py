# URL-pattern heuristics per design.md Section 4 — checked by the Impact
# node before ever calling the LLM. The LLM (SYSTEM_PROMPT/build_user_prompt
# below) is only a fallback for URLs that don't match any of these.
CRITICAL_PATH_PATTERNS = [
    "checkout", "cart", "payment",
    "login", "signin", "signup", "register",
    "contact", "search",
]

SYSTEM_PROMPT = """You are the Impact Agent in an accessibility compliance pipeline.

A page's URL didn't match any of our known critical-path patterns
(checkout, cart, payment, login, signin, signup, register, contact,
search). Given the page URL and the WCAG rule violated on it, judge
whether this page still represents a required step in a core user task
(transacting, authenticating, searching, or primary navigation) rather
than supplementary content, and estimate a business risk score.

Respond with ONLY a JSON object, no markdown code fences, no commentary
before or after it, matching exactly this schema:
{"is_critical_path": true or false, "business_risk_score": a number between 0 and 1, "reasoning_text": a 1-2 sentence explanation}"""


def build_user_prompt(page_url: str, wcag_rule: str) -> str:
    return f'Page URL: {page_url}\nWCAG rule violated: {wcag_rule}'
