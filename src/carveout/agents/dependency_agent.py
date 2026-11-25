"""Dependency Analysis Agent: investigates direct, transitive, circular, and blocking dependencies."""
from __future__ import annotations

import re
from typing import Any

from carveout.config import GROQ_API_KEY, GROQ_MODEL
from carveout.tools.graph_tools import (
    analyze_transitive_impact,
    detect_dependency_cycles,
    get_asset_dependants,
    get_asset_dependencies,
    identify_blocking_assets,
)
from carveout.workflows.state import CarveoutState


def _extract_asset_ids(text: str) -> list[str]:
    pattern = re.compile(r"\b[A-Z]{2,4}-\d{2}\b")
    return sorted(set(pattern.findall(text)))


def run_dependency_agent(state: CarveoutState) -> dict[str, Any]:
    """Execute dependency investigation using deterministic NetworkX graph tools."""
    portfolio_path = state.get("portfolio_path")
    user_request = state.get("user_request", "")

    mentioned_assets = _extract_asset_ids(user_request)
    findings: dict[str, Any] = {
        "investigated_assets": {},
        "portfolio_cycles": detect_dependency_cycles(portfolio_path),
        "blocking_assets": identify_blocking_assets(portfolio_path, min_dependants=3),
    }

    explanation_parts = []

    for aid in mentioned_assets:
        try:
            impact_data = analyze_transitive_impact(portfolio_path, aid)
            deps = impact_data["depends_on"]
            dependants = impact_data["depended_on_by"]
            findings["investigated_assets"][aid] = impact_data

            part = (
                f"- Asset **{aid}** depends on {len(deps)} prerequisites "
                f"({', '.join(deps) if deps else 'none'}), "
                f"and is depended upon by {len(dependants)} downstream assets "
                f"({', '.join(dependants) if dependants else 'none'})."
            )
            if impact_data["is_shared"]:
                part += " (It is marked as SHARED infrastructure/service)."
            explanation_parts.append(part)
        except KeyError:
            findings["investigated_assets"][aid] = {"error": f"Asset {aid} not found in portfolio"}
            explanation_parts.append(f"- Asset **{aid}** was not found in the portfolio.")

    cycles_found = findings["portfolio_cycles"]
    if cycles_found:
        cycle_str = ", ".join([" <-> ".join(c) for c in cycles_found])
        explanation_parts.append(f"- Dependency cycles detected: {cycle_str}.")
    else:
        explanation_parts.append("- No circular dependencies detected in the portfolio.")

    deterministic_summary = "\n".join(explanation_parts)

    # Optional LLM reasoning enhancement
    llm_reasoning = ""
    if GROQ_API_KEY:
        try:
            from langchain_groq import ChatGroq
            from langchain_core.messages import SystemMessage, HumanMessage

            llm = ChatGroq(model=GROQ_MODEL, temperature=0.0, api_key=GROQ_API_KEY)
            prompt = (
                f"User request: {user_request}\n"
                f"Deterministic dependency findings:\n{findings}\n\n"
                "Synthesize a concise, factual dependency impact assessment for an IT separation architect. "
                "Do not invent any asset IDs or relationships not present in the data."
            )
            resp = llm.invoke([
                SystemMessage(content="You are an expert IT Carve-out Dependency Graph Architect."),
                HumanMessage(content=prompt)
            ])
            llm_reasoning = resp.content
        except Exception:
            llm_reasoning = deterministic_summary
    else:
        llm_reasoning = deterministic_summary

    findings["explanation"] = llm_reasoning

    return {
        "dependency_analysis": findings,
        "agent_messages": [{
            "agent": "DependencyAgent",
            "content": f"Completed dependency analysis for {mentioned_assets or 'portfolio'}.",
        }],
    }
