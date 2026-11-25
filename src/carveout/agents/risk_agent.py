"""Risk Assessment Agent: identifies TSA overruns, licence deadlines, and operational exposures."""
from __future__ import annotations

import re
from typing import Any

from carveout.config import GROQ_API_KEY, GROQ_MODEL
from carveout.tools.risk_tools import (
    calculate_tsa_costs,
    detect_schedule_conflicts,
    generate_risk_register_data,
)
from carveout.workflows.state import CarveoutState


def _extract_asset_ids(text: str) -> list[str]:
    pattern = re.compile(r"\b[A-Z]{2,4}-\d{2}\b")
    return sorted(set(pattern.findall(text)))


def run_risk_agent(state: CarveoutState) -> dict[str, Any]:
    """Execute risk assessment using deterministic conflict detection and risk register models."""
    portfolio_path = state.get("portfolio_path")
    rules_path = state.get("rules_path")
    constraints_path = state.get("constraints_path")
    user_request = state.get("user_request", "")

    conflicts = detect_schedule_conflicts(portfolio_path, rules_path, constraints_path)
    risk_register = generate_risk_register_data(portfolio_path, rules_path, constraints_path)
    costs = calculate_tsa_costs(portfolio_path, rules_path, constraints_path)

    mentioned_assets = _extract_asset_ids(user_request)

    # Filter or highlight risks relevant to mentioned assets
    relevant_risks = []
    if mentioned_assets:
        for r in risk_register:
            if any(aid in r.get("asset_ids", []) for aid in mentioned_assets):
                relevant_risks.append(r)
    else:
        relevant_risks = risk_register

    findings: dict[str, Any] = {
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "total_risks_identified": len(risk_register),
        "relevant_risks": relevant_risks,
        "tsa_cost_total": costs["estimated_tsa_cost_total"],
        "tsa_months_needed": costs["tsa_months_needed"],
        "latest_planned_completion": costs["latest_planned_completion"],
    }

    # Deterministic narrative
    lines = [
        f"- Identified {len(conflicts)} hard schedule conflicts and {len(risk_register)} total risk items.",
        f"- Baseline estimated TSA exposure: ${costs['estimated_tsa_cost_total']:,.2f}.",
    ]
    if mentioned_assets:
        lines.append(f"- Relevant risks for {', '.join(mentioned_assets)}: {len(relevant_risks)} items identified.")
        for r in relevant_risks[:3]:
            lines.append(f"  * [{r['id']}] {r['risk']} (Likelihood: {r['likelihood']}, Impact: {r['impact']})")

    deterministic_summary = "\n".join(lines)

    # Optional LLM reasoning
    llm_reasoning = ""
    if GROQ_API_KEY:
        try:
            from langchain_groq import ChatGroq
            from langchain_core.messages import SystemMessage, HumanMessage

            llm = ChatGroq(model=GROQ_MODEL, temperature=0.0, api_key=GROQ_API_KEY)
            prompt = (
                f"User request: {user_request}\n"
                f"Deterministic risk findings:\n{findings}\n\n"
                "Synthesize an IT separation risk assessment. Clearly cite TSA cost exposures, "
                "licence expiration risks, and mitigation recommendations. Ground all numbers strictly in findings."
            )
            resp = llm.invoke([
                SystemMessage(content="You are an expert IT M&A Separation Risk Assessor."),
                HumanMessage(content=prompt)
            ])
            llm_reasoning = resp.content
        except Exception:
            llm_reasoning = deterministic_summary
    else:
        llm_reasoning = deterministic_summary

    findings["explanation"] = llm_reasoning

    return {
        "risk_assessment": findings,
        "agent_messages": [{
            "agent": "RiskAgent",
            "content": f"Identified {len(conflicts)} conflicts and {len(relevant_risks)} relevant risks.",
        }],
    }
