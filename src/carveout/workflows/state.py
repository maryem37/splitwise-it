"""Shared typed workflow state for Carve-out Copilot LangGraph orchestration."""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict
from pydantic import BaseModel, Field


class DependencyFindings(BaseModel):
    target_asset: str
    direct_dependencies: list[str] = Field(default_factory=list)
    transitive_dependencies: list[str] = Field(default_factory=list)
    direct_dependants: list[str] = Field(default_factory=list)
    transitive_dependants: list[str] = Field(default_factory=list)
    cycles_detected: list[list[str]] = Field(default_factory=list)
    critical_path: list[str] = Field(default_factory=list)
    blocking_assets: list[str] = Field(default_factory=list)
    explanation: str = ""


class RiskRecord(BaseModel):
    id: str
    risk: str
    cause: str
    likelihood: str
    impact: str
    owner: str
    mitigation: str
    asset_ids: list[str] = Field(default_factory=list)
    category: str = "general"
    deterministic: bool = True


class RiskFindings(BaseModel):
    tsa_conflicts: list[dict[str, Any]] = Field(default_factory=list)
    licence_conflicts: list[dict[str, Any]] = Field(default_factory=list)
    risk_register: list[RiskRecord] = Field(default_factory=list)
    tsa_cost_summary: dict[str, float] = Field(default_factory=dict)
    total_tsa_cost: float = 0.0
    explanation: str = ""


class AgentMessage(BaseModel):
    agent: str
    content: str
    timestamp: str = ""


def _merge_dict(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    if not left:
        return right or {}
    if not right:
        return left
    res = dict(left)
    res.update(right)
    return res


class CarveoutState(TypedDict):
    # Inputs
    user_request: str
    portfolio_path: str
    rules_path: str
    constraints_path: str

    # Intent & Routing
    intent: str
    required_agents: list[str]
    next_agent: str

    # Agent Findings
    dependency_analysis: Annotated[dict[str, Any], _merge_dict]
    risk_assessment: Annotated[dict[str, Any], _merge_dict]
    strategy_recommendations: Annotated[list[dict[str, Any]], operator.add]
    optimization_results: Annotated[dict[str, Any], _merge_dict]
    evaluation_results: Annotated[dict[str, Any], _merge_dict]

    # Shared Context / Logs
    agent_messages: Annotated[list[dict[str, Any]], operator.add]
    tool_results: Annotated[list[dict[str, Any]], operator.add]
    approval_status: str
    errors: Annotated[list[str], operator.add]

    # Final Output
    final_response: str
