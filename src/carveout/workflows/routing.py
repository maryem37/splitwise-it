"""Workflow routing logic for multi-agent delegation, critic loop, and approval."""
from __future__ import annotations

from typing import Literal
from carveout.workflows.state import CarveoutState


def route_supervisor(state: CarveoutState) -> Literal["dependency_node", "strategy_node", "risk_node", "optimization_node", "evaluation_node"]:
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
    return "evaluation_node"


def route_after_dependency(state: CarveoutState) -> Literal["strategy_node", "risk_node", "optimization_node", "evaluation_node"]:
    """Route from dependency agent to subsequent required agents or evaluation."""
    req = state.get("required_agents", [])
    if "strategy_agent" in req:
        return "strategy_node"
    if "risk_agent" in req:
        return "risk_node"
    if "optimization_agent" in req:
        return "optimization_node"
    return "evaluation_node"


def route_after_strategy(state: CarveoutState) -> Literal["risk_node", "optimization_node", "evaluation_node"]:
    """Route from strategy agent to risk, optimization, or evaluation."""
    req = state.get("required_agents", [])
    if "risk_agent" in req:
        return "risk_node"
    if "optimization_agent" in req:
        return "optimization_node"
    return "evaluation_node"


def route_after_risk(state: CarveoutState) -> Literal["optimization_node", "evaluation_node"]:
    """Route from risk agent to optimization or evaluation."""
    req = state.get("required_agents", [])
    if "optimization_agent" in req:
        return "optimization_node"
    return "evaluation_node"


def route_after_critic(state: CarveoutState) -> Literal["correction_node", "approval_node", "synthesis_node"]:
    """Route based on CriticDecision with bounded correction safeguards."""
    critic = state.get("critic_decision", {})
    decision = critic.get("decision", "ACCEPTED")
    attempts = int(state.get("correction_attempts", 0))
    max_attempts = int(state.get("max_correction_attempts", 2))
    pending = state.get("pending_correction", {})

    if decision == "CORRECTION_REQUIRED" and pending and attempts < max_attempts:
        return "correction_node"
    if decision == "BLOCKED":
        return "synthesis_node"
    return "approval_node"


def route_after_approval(state: CarveoutState) -> Literal["correction_node", "synthesis_node"]:
    """Route after human approval: APPROVE/REJECT -> synthesis; REQUEST_REVISION -> correction if within limit."""
    status = state.get("approval_status", "")
    pending = state.get("pending_correction", {})
    attempts = int(state.get("correction_attempts", 0))
    max_attempts = int(state.get("max_correction_attempts", 2))

    if status == "revision_requested" and pending and attempts < max_attempts:
        return "correction_node"
    return "synthesis_node"
