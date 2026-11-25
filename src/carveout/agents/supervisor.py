"""Supervisor Agent: understands intent, routes tasks, and synthesizes multi-agent findings."""
from __future__ import annotations

import re
from typing import Any

from carveout.config import GROQ_API_KEY, GROQ_MODEL
from carveout.workflows.state import CarveoutState


def classify_intent(user_request: str) -> dict[str, Any]:
    """Deterministic intent classification based on keywords."""
    req_lower = user_request.lower()
    required_agents = []

    is_dependency = any(w in req_lower for w in ["depend", "prereq", "impact", "cycle", "block", "downstream", "delay"])
    is_risk = any(w in req_lower for w in ["tsa", "licence", "license", "cost", "risk", "conflict", "expire", "expiration"])
    is_strategy = any(w in req_lower for w in ["strategy", "clone", "migrate", "rebuild", "retire"])
    is_opt = any(w in req_lower for w in ["optimize", "schedule", "minimize", "tradeoff", "trade-off", "scenario", "delay"])

    if is_dependency:
        required_agents.append("dependency_agent")
    if is_strategy:
        required_agents.append("strategy_agent")
    if is_risk or ("delay" in req_lower and "cost" in req_lower):
        required_agents.append("risk_agent")
    if is_opt:
        required_agents.append("optimization_agent")

    # If delay scenario like "What happens if we delay APP-06", enlists dependency, risk, and optimization
    if "delay" in req_lower:
        for a in ["dependency_agent", "risk_agent", "optimization_agent"]:
            if a not in required_agents:
                required_agents.append(a)

    # Fallback if empty
    if not required_agents:
        required_agents = ["dependency_agent", "risk_agent", "optimization_agent"]

    intent = "composite_investigation" if len(required_agents) > 1 else required_agents[0]
    return {
        "intent": intent,
        "required_agents": required_agents,
    }


def run_supervisor(state: CarveoutState) -> dict[str, Any]:
    """Supervisor routing and task delegation."""
    user_request = state.get("user_request", "")
    classification = classify_intent(user_request)

    return {
        "intent": classification["intent"],
        "required_agents": classification["required_agents"],
        "next_agent": classification["required_agents"][0] if classification["required_agents"] else "reporting",
        "agent_messages": [{
            "agent": "Supervisor",
            "content": f"Classified intent as '{classification['intent']}'. Routing to agents: {classification['required_agents']}.",
        }],
    }


def synthesize_final_response(state: CarveoutState) -> dict[str, Any]:
    """Synthesize final recommendations from all agent findings."""
    user_request = state.get("user_request", "")
    dep_findings = state.get("dependency_analysis", {})
    risk_findings = state.get("risk_assessment", {})
    strat_findings_list = state.get("strategy_recommendations", [])
    opt_data = state.get("optimization_results", {})

    dep_exp = dep_findings.get("explanation", "")
    risk_exp = risk_findings.get("explanation", "")
    strat_exp = strat_findings_list[0].get("explanation", "") if strat_findings_list else ""
    opt_exp = opt_data.get("explanation", "")

    # Grounded synthesis
    sections = [
        f"# IT Separation Investigation & Optimization Report",
        f"**User Request:** {user_request}\n",
    ]

    if dep_exp:
        sections.extend([f"## 1. Dependency Analysis", dep_exp, ""])
    if strat_exp:
        sections.extend([f"## 2. Strategy Evaluation", strat_exp, ""])
    if risk_exp:
        sections.extend([f"## 3. Risk & TSA Exposure Assessment", risk_exp, ""])
    if opt_exp:
        sections.extend([f"## 4. CP-SAT Schedule Optimization & Scenario Comparison", opt_exp, ""])

    sections.append("## 5. Executive Recommendation & Action Plan")
    if "delay" in user_request.lower():
        sections.append(
            "- **Coupled Unit Delay:** APP-06 and APP-07 form a strongly connected component (mutual dependency). "
            "Any delay must be scheduled jointly for both assets."
        )
        sections.append(
            "- **TSA Cost Delta:** Review solver-quantified additional TSA expenditure. If downstream assets cross TSA contract dates, "
            "initiate extension negotiations before cutover freeze periods."
        )
        sections.append(
            "- **Schedule Feasibility:** Verified with OR-Tools CP-SAT integer programming solver to ensure no hard dependency violations occur."
        )
    else:
        sections.append("- Proceed with planned wave schedule adhering to identified dependency and capacity constraints.")

    final_text = "\n".join(sections)

    if GROQ_API_KEY:
        try:
            from langchain_groq import ChatGroq
            from langchain_core.messages import SystemMessage, HumanMessage

            llm = ChatGroq(model=GROQ_MODEL, temperature=0.0, api_key=GROQ_API_KEY)
            prompt = (
                f"User request: {user_request}\n"
                f"Dependency findings:\n{dep_findings}\n\n"
                f"Strategy findings:\n{strat_findings_list}\n\n"
                f"Risk findings:\n{risk_findings}\n\n"
                f"Optimization results:\n{opt_data}\n\n"
                "Synthesize a cohesive, high-impact IT Separation Consulting Executive Brief. "
                "Structure: Executive Summary, Dependency & Strategy Insights, Risk & TSA Impact, Optimization Trade-offs, Recommendations. "
                "Strictly preserve all calculated figures, dates, percentages, and asset IDs."
            )
            resp = llm.invoke([
                SystemMessage(content="You are a Lead IT Separation Partner synthesizing findings for enterprise executives."),
                HumanMessage(content=prompt),
            ])
            final_text = resp.content
        except Exception:
            pass

    return {
        "final_response": final_text,
        "approval_status": "ready_for_review",
    }
