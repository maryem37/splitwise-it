"""Agentic workflow evaluation metrics."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel


class AgentExecutionMetrics(BaseModel):
    task_completed: bool
    expected_agents_count: int
    executed_agents_count: int
    agent_coverage: float
    missing_evidence_count: int
    correction_attempts: int
    error_count: int


class PlanningMetrics(BaseModel):
    feasible: bool
    hard_violation_count: int
    existing_conflict_count: int
    tsa_cost: float
    completion_date: str
    wave_count: int


class WorkflowMetrics(BaseModel):
    total_trace_steps: int
    correction_iterations: int
    approval_status: str
    workflow_status: str
    duration_seconds: float


def compute_workflow_metrics(state: dict[str, Any], duration_seconds: float = 0.0) -> dict[str, Any]:
    """Compute structured agent, planning, and workflow metrics from a completed/paused state."""
    req = state.get("required_agents", [])
    messages = state.get("agent_messages", [])
    executed = {m.get("agent") for m in messages}
    name_map = {
        "dependency_agent": "DependencyAgent",
        "risk_agent": "RiskAgent",
        "strategy_agent": "StrategyAgent",
        "optimization_agent": "OptimizationAgent",
    }
    matched = sum(1 for a in req if name_map.get(a) in executed)
    eval_rep = state.get("evaluation_report", {})
    opt_data = state.get("optimization_results", {})
    opt_res = opt_data.get("optimization_result", {})

    agent_m = AgentExecutionMetrics(
        task_completed=bool(state.get("final_response")) or state.get("approval_status") in ("approved", "rejected"),
        expected_agents_count=len(req),
        executed_agents_count=matched,
        agent_coverage=round(matched / max(1, len(req)), 4),
        missing_evidence_count=len(eval_rep.get("missing_evidence", [])),
        correction_attempts=int(state.get("correction_attempts", 0)),
        error_count=len(state.get("errors", [])),
    )

    planning_m = PlanningMetrics(
        feasible=bool(eval_rep.get("planning_validity", False)),
        hard_violation_count=len(eval_rep.get("hard_violations", [])),
        existing_conflict_count=len(eval_rep.get("existing_conflicts", [])),
        tsa_cost=float(opt_res.get("estimated_tsa_cost_total", state.get("risk_assessment", {}).get("tsa_cost_total", 0.0))),
        completion_date=str(opt_res.get("latest_completion_date", state.get("risk_assessment", {}).get("latest_planned_completion", ""))),
        wave_count=int(opt_res.get("total_waves", 0)),
    )

    workflow_m = WorkflowMetrics(
        total_trace_steps=len(state.get("execution_trace", [])),
        correction_iterations=int(state.get("correction_attempts", 0)),
        approval_status=str(state.get("approval_status", "pending")),
        workflow_status=str(state.get("workflow_status", "unknown")),
        duration_seconds=round(duration_seconds, 4),
    )

    return {
        "agent_metrics": agent_m.model_dump(),
        "planning_metrics": planning_m.model_dump(),
        "workflow_metrics": workflow_m.model_dump(),
    }
