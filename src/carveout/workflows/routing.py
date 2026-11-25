"""Workflow routing logic for multi-agent delegation across all specialized agents."""
from __future__ import annotations

from typing import Literal
from carveout.workflows.state import CarveoutState


def route_supervisor(state: CarveoutState) -> Literal["dependency_node", "strategy_node", "risk_node", "optimization_node", "synthesis_node"]:
    """Route from supervisor to the first assigned agent."""
    req = state.get("required_agents", [])
    if "dependency_agent" in req:
        return "dependency_node"
    if "strategy_agent" in req:
        return "strategy_node"
    if "risk_agent" in req:
        return "risk_node"
    if "optimization_agent" in req:
        return "optimization_node"
    return "synthesis_node"


def route_after_dependency(state: CarveoutState) -> Literal["strategy_node", "risk_node", "optimization_node", "synthesis_node"]:
    """Route from dependency agent to subsequent required agents."""
    req = state.get("required_agents", [])
    if "strategy_agent" in req:
        return "strategy_node"
    if "risk_agent" in req:
        return "risk_node"
    if "optimization_agent" in req:
        return "optimization_node"
    return "synthesis_node"


def route_after_strategy(state: CarveoutState) -> Literal["risk_node", "optimization_node", "synthesis_node"]:
    """Route from strategy agent to risk or optimization or synthesis."""
    req = state.get("required_agents", [])
    if "risk_agent" in req:
        return "risk_node"
    if "optimization_agent" in req:
        return "optimization_node"
    return "synthesis_node"


def route_after_risk(state: CarveoutState) -> Literal["optimization_node", "synthesis_node"]:
    """Route from risk agent to optimization or synthesis."""
    req = state.get("required_agents", [])
    if "optimization_agent" in req:
        return "optimization_node"
    return "synthesis_node"
