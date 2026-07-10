import json

SYSTEM_PROMPT = """You are the Developer Agent in an accessibility compliance pipeline.

Given a confirmed WCAG violation, propose a concrete code fix anchored to
the exact element that violates the rule. Use the rule-specific guidance
below for this violation's rule.

Respond with ONLY a JSON object, no markdown code fences, no commentary
before or after it, matching exactly this schema:
{"proposed_code_diff": the corrected HTML/CSS snippet for this element, "target_selector": the exact CSS selector this fix applies to (reuse the element_selector given to you, do not invent a new one)}"""

# Rule-specific fix guidance for each of the 9 locked v1 rules
# (backend/app/detector.py's LOCKED_RULE_IDS) — a generic "fix this"
# instruction doesn't give the model enough to propose a concrete diff.
RULE_GUIDANCE = {
    "image-alt": "Add a concise, descriptive `alt` attribute to the image based on its context in the surrounding HTML.",
    "input-image-alt": "Add a concise, descriptive `alt` attribute to the image-type input based on its context.",
    "color-contrast": "Adjust the foreground and/or background color values to reach at least a 4.5:1 contrast ratio, keeping the change visually minimal.",
    "label": "Add an associated `<label>` element (or `aria-label`/`aria-labelledby`) so the form field has an accessible name.",
    "button-name": "Add visible text content, `aria-label`, or `aria-labelledby` so the button has an accessible name.",
    "aria-input-field-name": "Add `aria-label` or `aria-labelledby` so the ARIA input field has an accessible name.",
    "tabindex": "Remove the positive `tabindex` value (or set it to `0`) so it no longer disrupts the natural tab order.",
    "html-has-lang": (
        "This fix is applied as a targeted attribute change, not a full HTML "
        "replacement (target_selector is the `<html>` element itself, and "
        "regenerating the whole page as proposed_code_diff would be both "
        "unreliable and destructive if combined with other fixes on the same "
        "page). Set `proposed_code_diff` to ONLY the page's actual BCP 47 "
        "language code (e.g. `en`, `en-US`) based on the page's content — do "
        "NOT include the `<html>` tag, the `lang` attribute name, quotes, or "
        "any other markup."
    ),
    "html-lang-valid": (
        "This fix is applied as a targeted attribute change, not a full HTML "
        "replacement (target_selector is the `<html>` element itself, and "
        "regenerating the whole page as proposed_code_diff would be both "
        "unreliable and destructive if combined with other fixes on the same "
        "page). Set `proposed_code_diff` to ONLY the corrected, valid BCP 47 "
        "language code (e.g. `en`, `en-US`) — do NOT include the `<html>` "
        "tag, the `lang` attribute name, quotes, or any other markup."
    ),
    "bypass": "Add a skip-navigation link as the first focusable element, pointing to the main content region.",
    "skip-link": "Ensure the skip-navigation link is present, focusable, and points to a valid target id.",
    "duplicate-id-aria": "Rename one of the duplicate `id` values so ARIA/label references resolve unambiguously.",
    "list": "Ensure list items are wrapped in a proper `<ul>`/`<ol>` parent rather than appearing outside a list container.",
    "listitem": "Ensure `<li>` elements are direct children of a `<ul>` or `<ol>`.",
    "definition-list": "Ensure `<dl>` only contains properly grouped `<dt>`/`<dd>` children.",
    "link-name": "Add visible text content, `aria-label`, or `aria-labelledby` so the link has an accessible name.",
}


def build_user_prompt(wcag_rule: str, element_selector: str, html_snippet: str, message: str) -> str:
    violation = {
        "wcag_rule": wcag_rule,
        "element_selector": element_selector,
        "html_snippet": html_snippet,
        "message": message,
    }
    guidance = RULE_GUIDANCE.get(wcag_rule, "Propose the minimal correct fix for this WCAG violation.")
    return f"Violation:\n{json.dumps(violation)}\n\nFix guidance for {wcag_rule}: {guidance}"
