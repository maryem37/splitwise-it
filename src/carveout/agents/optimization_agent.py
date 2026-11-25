"""Optimization Agent: configures and executes OR-Tools CP-SAT scheduling scenarios."""
from __future__ import annotations

import re
from typing import Any

from carveout.config import GROQ_API_KEY, GROQ_MODEL
from carveout.tools.optimization_tools import (
    compare_migration_scenarios,
    optimize_migration_schedule,
)
from carveout.workflows.state import CarveoutState


def run_optimization_agent(state: CarveoutState) -> dict[str, Any]:
    """Execute CP-SAT optimization according to user goals and scenario triggers."""
    portfolio_path = state.get("portfolio_path")
    rules_path = state.get("rules_path")
    constraints_path = state.get("constraints_path")
    user_request = state.get("user_request", "").lower()

    # Determine scenario and objective from request
    is_delay_scenario = "delay" in user_request and "app-06" in user_request
    delay_weeks = 12
    # Check if custom number of weeks or months specified
    match = re.search(r"(\d+)\s*(?:month|w|week)", user_request)
    if match:
        val = int(match.group(1))
        if "month" in match.group(0):
            delay_weeks = val * 4
        else:
            delay_weeks = val

    if is_delay_scenario:
        scenario_data = compare_migration_scenarios(
            portfolio_path,
            rules_path,
            scenario_type="app_06_delay",
            delay_weeks=delay_weeks,
            constraints_path=constraints_path,
        )
    elif "duration" in user_request or "fast" in user_request or "time" in user_request:
        scenario_data = optimize_migration_schedule(
            portfolio_path, rules_path, objective="minimize_duration", constraints_path=constraints_path
        )
    else:
        scenario_data = optimize_migration_schedule(
            portfolio_path, rules_path, objective="minimize_cost", constraints_path=constraints_path
        )

    res = scenario_data["optimization_result"]
    comp = scenario_data["comparison"]

    lines = [
        f"- **CP-SAT Solver Status:** `{res['status']}` (duration: {res['solve_duration_seconds']:.2f}s).",
        f"- **Scenario Evaluated:** `{comp['scenario_name']}`.",
        f"- **TSA Cost Comparison:** Baseline `${comp['baseline_tsa_cost']:,.2f}` $\\rightarrow$ Scenario `${comp['scenario_tsa_cost']:,.2f}` (Delta: `${comp['additional_tsa_cost']:+,.2f}`).",
        f"- **Latest Completion:** Baseline `{comp['baseline_completion']}` $\\rightarrow$ Scenario `{comp['scenario_completion']}`.",
        f"- **Migration Waves:** Baseline `{comp['baseline_waves']}` $\\rightarrow$ Scenario `{comp['scenario_waves']}` waves.",
        f"- **Identified Conflicts:** {len(res['conflicts'])} conflicts.",
    ]
    if comp["affected_assets"]:
        lines.append(f"- **Coupled Assets Directly Shifted:** {', '.join(comp['affected_assets'])}.")

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
                f"CP-SAT Optimization & Comparison:\n{comp}\n\n"
                "Synthesize a clear, actionable optimization comparison for executive decision makers. "
                "Highlight the exact numerical delta in TSA cost, schedule impacts, and trade-offs. "
                "Ground all values strictly in the solver output."
            )
            resp = llm.invoke([
                SystemMessage(content="You are an expert Operations Research & IT Portfolio Optimization Lead."),
                HumanMessage(content=prompt),
            ])
            llm_reasoning = resp.content
        except Exception:
            llm_reasoning = deterministic_summary
    else:
        llm_reasoning = deterministic_summary

    scenario_data["explanation"] = llm_reasoning

    return {
        "optimization_results": scenario_data,
        "agent_messages": [{
            "agent": "OptimizationAgent",
            "content": f"Completed CP-SAT solve for {comp['scenario_name']} (Status: {res['status']}).",
        }],
    }
