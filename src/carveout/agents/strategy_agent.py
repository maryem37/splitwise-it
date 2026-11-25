"""Strategy Recommendation Agent: evaluates exit strategies using deterministic rules."""
from __future__ import annotations

import re
from typing import Any

from carveout.config import GROQ_API_KEY, GROQ_MODEL
from carveout.tools.strategy_tools import (
    compare_asset_strategy_options,
    get_all_strategy_assessments,
    get_asset_strategy_assessment,
)
from carveout.workflows.state import CarveoutState


def _extract_asset_ids(text: str) -> list[str]:
    pattern = re.compile(r"\b[A-Z]{2,4}-\d{2}\b")
    return sorted(set(pattern.findall(text)))


def run_strategy_agent(state: CarveoutState) -> dict[str, Any]:
    """Execute strategy evaluation using deterministic rule engine decisions."""
    portfolio_path = state.get("portfolio_path")
    rules_path = state.get("rules_path")
    user_request = state.get("user_request", "")

    mentioned_assets = _extract_asset_ids(user_request)
    all_decisions = get_all_strategy_assessments(portfolio_path, rules_path)

    findings: dict[str, Any] = {
        "all_strategies_count": len(all_decisions),
        "investigated_strategies": {},
        "proposals": [],
    }

    lines = []
    if mentioned_assets:
        for aid in mentioned_assets:
            try:
                comp = compare_asset_strategy_options(portfolio_path, rules_path, aid)
                findings["investigated_strategies"][aid] = comp
                strat = comp["current_strategy"]
                exit_str = f" (exit: {comp['exit_strategy']})" if comp.get("exit_strategy") else ""
                lines.append(
                    f"- Asset **{aid}** ({comp['name']}): Assigned `{strat}`{exit_str} "
                    f"via rule `{comp['rule_matched']}` (confidence: {comp['confidence']:.2f}). "
                    f"Reason: {', '.join(comp['reason'])}"
                )
            except KeyError:
                lines.append(f"- Asset **{aid}** not found in portfolio.")
    else:
        # Overview breakdown
        counts: dict[str, int] = {}
        for d in all_decisions:
            s = d["strategy"]
            counts[s] = counts.get(s, 0) + 1
        lines.append(f"- Evaluated deterministic strategies across {len(all_decisions)} assets:")
        for s, c in sorted(counts.items()):
            lines.append(f"  * `{s}`: {c} assets")

    deterministic_summary = "\n".join(lines)

    # Optional LLM reasoning enhancement
    llm_reasoning = ""
    if GROQ_API_KEY:
        try:
            from langchain_groq import ChatGroq
            from langchain_core.messages import SystemMessage, HumanMessage

            llm = ChatGroq(model=GROQ_MODEL, temperature=0.0, api_key=GROQ_API_KEY)
            prompt = (
                f"User request: {user_request}\n"
                f"Deterministic strategy decisions:\n{findings}\n\n"
                "Synthesize a factual IT separation strategy recommendation. "
                "Explain the justification, technical dependencies, and risk tradeoffs. "
                "Never override rule-based decisions or invent ungrounded scores."
            )
            resp = llm.invoke([
                SystemMessage(content="You are an expert IT Separation Strategy Advisor."),
                HumanMessage(content=prompt),
            ])
            llm_reasoning = resp.content
        except Exception:
            llm_reasoning = deterministic_summary
    else:
        llm_reasoning = deterministic_summary

    findings["explanation"] = llm_reasoning

    return {
        "strategy_recommendations": [findings],
        "agent_messages": [{
            "agent": "StrategyAgent",
            "content": f"Evaluated strategies for {mentioned_assets or 'portfolio'}.",
        }],
    }
