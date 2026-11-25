"""Shared typed workflow state for Carve-out Copilot LangGraph orchestration."""
from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict
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


class EvaluationFinding(BaseModel):
    finding_id: str
    category: Literal["evidence", "planning", "financial", "execution"]
    severity: Literal["hard", "warning", "existing_conflict", "info"]
    description: str
    evidence: str = ""
    affected_assets: list[str] = Field(default_factory=list)
    recommended_action: str = ""


class EvaluationReport(BaseModel):
    evaluation_id: str
    status: Literal["PASS", "PASS_WITH_WARNINGS", "FAIL", "INCOMPLETE"]
    overall_score: float = Field(ge=0.0, le=1.0)
    evidence_coverage: float = Field(ge=0.0, le=1.0)
    planning_validity: bool
    financial_validity: bool
    execution_validity: bool
    hard_violations: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    existing_conflicts: list[dict[str, Any]] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    checked_constraints: list[str] = Field(default_factory=list)
    evaluation_summary: str = ""


class CorrectionRequest(BaseModel):
    target_agent: Literal["dependency_agent", "risk_agent", "optimization_agent"]
    action: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    reason: str
    signature: str


class CriticDecision(BaseModel):
    decision: Literal["ACCEPTED", "CORRECTION_REQUIRED", "HUMAN_REVIEW_REQUIRED", "BLOCKED"]
    rationale: str
    findings: list[EvaluationFinding] = Field(default_factory=list)
    correction_request: CorrectionRequest | None = None
    requires_human_approval: bool = False


class HumanApprovalDecision(BaseModel):
    action: Literal["APPROVE", "REJECT", "REQUEST_REVISION"]
    reviewer: str = "human_reviewer"
    comment: str = ""
    timestamp: str = ""


def _merge_dict(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    if not left:
        return right or {}
    if not right:
        return left
    res = dict(left)
    res.update(right)
    return res


class CarveoutState(TypedDict, total=False):
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

    # Phase 3: Evaluation, Critic, Correction Loop & Human-in-the-Loop
    evaluation_report: Annotated[dict[str, Any], _merge_dict]
    critic_decision: Annotated[dict[str, Any], _merge_dict]
    correction_attempts: int
    max_correction_attempts: int
    correction_history: Annotated[list[dict[str, Any]], operator.add]
    pending_correction: Annotated[dict[str, Any], _merge_dict]
    human_review_required: bool
    human_approval: Annotated[dict[str, Any], _merge_dict]
    approval_history: Annotated[list[dict[str, Any]], operator.add]
    workflow_status: str
    execution_trace: Annotated[list[str], operator.add]
    enable_human_interrupt: bool

    # Shared Context / Logs
    agent_messages: Annotated[list[dict[str, Any]], operator.add]
    tool_results: Annotated[list[dict[str, Any]], operator.add]
    approval_status: str
    errors: Annotated[list[str], operator.add]

    # Final Output
    final_response: str

    # Observability & Metrics (Phase 3.2)
    metrics: Annotated[dict[str, Any], _merge_dict]
    node_timings: Annotated[list[dict[str, Any]], operator.add]
