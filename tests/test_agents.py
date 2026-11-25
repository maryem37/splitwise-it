"""Tests for Phase 2 multi-agent orchestration including Strategy and Optimization Agents."""
from pathlib import Path
import pytest

from carveout.agents.supervisor import classify_intent, run_supervisor
from carveout.workflows.graph import build_carveout_graph, run_agent_workflow

ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = ROOT / "data" / "portfolio_v1.yaml"
RULES = ROOT / "config" / "strategy_rules.yaml"
CONSTRAINTS = ROOT / "config" / "constraints.yaml"


def test_intent_classification_phase2():
    # Strategy intent
    c_strat = classify_intent("What is our recommended strategy for APP-01?")
    assert "strategy_agent" in c_strat["required_agents"]

    # Optimization intent
    c_opt = classify_intent("Optimize the migration schedule to minimize total TSA cost.")
    assert "optimization_agent" in c_opt["required_agents"]

    # Full composite delay intent
    c_comp = classify_intent("What happens if we delay APP-06 by three months, and how can we minimize the additional TSA cost?")
    assert "dependency_agent" in c_comp["required_agents"]
    assert "risk_agent" in c_comp["required_agents"]
    assert "optimization_agent" in c_comp["required_agents"]


def test_langgraph_workflow_end_to_end_delay_scenario():
    """Verify primary agentic scenario: delay APP-06 with dependency, risk, and CP-SAT optimization."""
    query = "What happens if we delay APP-06 by three months, and how can we minimize the additional TSA cost?"
    result = run_agent_workflow(
        user_request=query,
        portfolio_path=str(PORTFOLIO),
        rules_path=str(RULES),
        constraints_path=str(CONSTRAINTS),
    )

    assert result["approval_status"] == "ready_for_review"
    assert "dependency_analysis" in result
    assert "risk_assessment" in result
    assert "optimization_results" in result

    # Verify CP-SAT optimization executed
    opt = result["optimization_results"]
    assert "optimization_result" in opt
    assert "comparison" in opt
    comp = opt["comparison"]
    assert comp["scenario_id"] == "app_06_delay"
    assert "APP-06" in comp["affected_assets"]
    assert "APP-07" in comp["affected_assets"]
    assert isinstance(comp["additional_tsa_cost"], float)

    # Verify agent messages trace full handoff chain
    messages = result["agent_messages"]
    agents_involved = [m["agent"] for m in messages]
    assert "Supervisor" in agents_involved
    assert "DependencyAgent" in agents_involved
    assert "RiskAgent" in agents_involved
    assert "OptimizationAgent" in agents_involved
    assert "ApprovalGate" in agents_involved

    # Verify final response integrates solver output
    final = result["final_response"]
    assert "APP-06" in final
    assert "Optimization" in final or "CP-SAT" in final
