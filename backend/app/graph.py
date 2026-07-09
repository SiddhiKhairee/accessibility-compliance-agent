"""
graph.py — the Phase 2 LangGraph reasoning layer: exactly 4 nodes
(Reviewer, Impact, Developer, Verifier), linear edges, no more per
CLAUDE.md ("do not add a 5th node without an explicit, distinct
responsibility").

Each node is a pure function over a shared per-violation state dict — none
of them touch the database. The caller (main.py's run_scan) invokes the
compiled graph once per violation and only commits DB writes after the
full graph succeeds; a failure at any node propagates straight out of
`reasoning_graph.ainvoke(...)` with nothing written for that violation.
See llm_client.py and the plan
(C:\\Users\\siddh\\.claude\\plans\\delegated-sniffing-lollipop.md) for the
full error-handling contract.
"""
from typing import TypedDict

from langgraph.graph import END, StateGraph

from agents.developer import prompt as developer_prompt
from agents.developer.schema import DeveloperOutput
from agents.impact import prompt as impact_prompt
from agents.impact.schema import ImpactOutput
from agents.reviewer import prompt as reviewer_prompt
from agents.reviewer.schema import ReviewerOutput
from agents.verifier.schema import VerifierOutput
from llm_client import IMPACT_FALLBACK_MODEL_NAME, call_llm
from models import AgentName, FixFailureReason, FixVerificationStatus
from verifier import verify_fix


class ViolationInput(TypedDict):
    id: int
    wcag_rule: str
    element_selector: str
    html_snippet: str
    message: str
    page_url: str


class ReasoningState(TypedDict, total=False):
    violation: ViolationInput
    # Page-scoped, not violation-scoped — every violation on the same page
    # shares the same baseline (the full set of violations detected on that
    # page before any fix was applied). Threaded in by main.py's run_scan so
    # verifier_node never has to query the DB (see module docstring).
    baseline_violations: list[dict]
    reviewer_result: ReviewerOutput
    impact_result: ImpactOutput
    developer_result: DeveloperOutput
    verifier_result: VerifierOutput


async def reviewer_node(state: ReasoningState) -> dict:
    v = state["violation"]
    user_prompt = reviewer_prompt.build_user_prompt(
        v["wcag_rule"], v["element_selector"], v["html_snippet"], v["message"]
    )
    result = await call_llm(
        agent_name=AgentName.Reviewer,
        wcag_rule=v["wcag_rule"],
        html_snippet=v["html_snippet"],
        system_prompt=reviewer_prompt.SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=ReviewerOutput,
    )
    return {"reviewer_result": result}


async def impact_node(state: ReasoningState) -> dict:
    v = state["violation"]
    page_url_lower = v["page_url"].lower()

    matched_pattern = next(
        (p for p in impact_prompt.CRITICAL_PATH_PATTERNS if p in page_url_lower), None
    )
    if matched_pattern is not None:
        # URL-pattern heuristic hit — no LLM call, per design.md Section 4.
        # Deterministic max risk score: a definitive pattern match doesn't
        # need a nuanced LLM judgment, only the ambiguous case does.
        result = ImpactOutput(
            is_critical_path=True,
            business_risk_score=1.0,
            reasoning_text=f"Page URL matched critical-path pattern '{matched_pattern}' (design.md Section 4).",
        )
        return {"impact_result": result}

    user_prompt = impact_prompt.build_user_prompt(v["page_url"], v["wcag_rule"])
    result = await call_llm(
        agent_name=AgentName.Impact,
        wcag_rule=v["wcag_rule"],
        html_snippet=None,
        system_prompt=impact_prompt.SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=ImpactOutput,
        # Impact's ambiguous-case judgment (a single risk score + reasoning)
        # is coarser than Developer's fix-generation, making it a reasonable
        # candidate for a smaller/cheaper model — Reviewer/Developer keep
        # the fix-quality-critical MODEL_NAME (Phase 3 cost-optimization
        # scope, see llm_client.py).
        model=IMPACT_FALLBACK_MODEL_NAME,
    )
    return {"impact_result": result}


async def developer_node(state: ReasoningState) -> dict:
    v = state["violation"]
    user_prompt = developer_prompt.build_user_prompt(
        v["wcag_rule"], v["element_selector"], v["html_snippet"], v["message"]
    )
    result = await call_llm(
        agent_name=AgentName.Developer,
        wcag_rule=v["wcag_rule"],
        # Real html_snippet (was None) — needed now that Developer is
        # cacheable too (Phase 3, see llm_client.py's generalized cache key).
        html_snippet=v["html_snippet"],
        system_prompt=developer_prompt.SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=DeveloperOutput,
        # On a cache hit, llm_client.py always overrides target_selector with
        # this value rather than trusting the cached one — target_selector
        # is a verbatim copy of the input, not independently generated
        # content, so this fully neutralizes the one real Developer-caching
        # risk (see llm_client.py module docstring).
        element_selector=v["element_selector"],
    )
    return {"developer_result": result}


async def verifier_node(state: ReasoningState) -> dict:
    v = state["violation"]
    baseline = state["baseline_violations"]
    developer_result = state["developer_result"]

    attempt = await verify_fix(
        page_url=v["page_url"],
        original_wcag_rule=v["wcag_rule"],
        original_element_selector=v["element_selector"],
        target_selector=developer_result.target_selector,
        proposed_code_diff=developer_result.proposed_code_diff,
        baseline=baseline,
    )

    retry_count = 0
    if attempt.outcome != "verified":
        # Mechanical retry only: same proposed_code_diff, freshly reloaded
        # page, no new Developer LLM call. The retry's own outcome is always
        # authoritative for the final verdict, even if the first attempt had
        # a cleaner signal — one deterministic rule, no special-casing.
        retry_count = 1
        attempt = await verify_fix(
            page_url=v["page_url"],
            original_wcag_rule=v["wcag_rule"],
            original_element_selector=v["element_selector"],
            target_selector=developer_result.target_selector,
            proposed_code_diff=developer_result.proposed_code_diff,
            baseline=baseline,
        )

    if attempt.outcome == "verified":
        result = VerifierOutput(
            verification_status=FixVerificationStatus.verified,
            retry_count=retry_count,
        )
    elif attempt.outcome in ("violation_persists", "new_violation"):
        # Fix applied cleanly, detector reran cleanly, but the violation
        # persists or a new one appeared — a confident automated "no", not a
        # tooling failure.
        result = VerifierOutput(
            verification_status=FixVerificationStatus.rejected,
            retry_count=retry_count,
        )
    else:  # "error" — a technical failure that persisted through the retry
        result = VerifierOutput(
            verification_status=FixVerificationStatus.manual_review,
            failure_reason=FixFailureReason(attempt.failure_reason),
            retry_count=retry_count,
        )
    return {"verifier_result": result}


def _build_graph():
    graph = StateGraph(ReasoningState)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("impact", impact_node)
    graph.add_node("developer", developer_node)
    graph.add_node("verifier", verifier_node)
    graph.set_entry_point("reviewer")
    graph.add_edge("reviewer", "impact")
    graph.add_edge("impact", "developer")
    graph.add_edge("developer", "verifier")
    graph.add_edge("verifier", END)
    return graph.compile()


reasoning_graph = _build_graph()
