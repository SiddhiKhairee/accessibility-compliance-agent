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
from llm_client import call_llm
from models import AgentName


class ViolationInput(TypedDict):
    id: int
    wcag_rule: str
    element_selector: str
    html_snippet: str
    message: str
    page_url: str


class ReasoningState(TypedDict, total=False):
    violation: ViolationInput
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
        html_snippet=None,
        system_prompt=developer_prompt.SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=DeveloperOutput,
    )
    return {"developer_result": result}


async def verifier_node(state: ReasoningState) -> dict:
    # Phase 2 structural stub only — no LLM call, no Playwright re-check.
    # Phase 3 fills in the real apply-fix-and-reverify logic here without
    # touching graph topology (see agents/verifier/schema.py).
    return {"verifier_result": VerifierOutput()}


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
