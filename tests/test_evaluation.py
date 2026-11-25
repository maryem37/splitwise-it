"""Tests for Phase 3 Evaluation Agent and benchmark suite."""
from pathlib import Path
from carveout.agents.evaluation_agent import evaluate_workflow_state
from carveout.evaluation.benchmarks import run_benchmark_suite
from carveout.workflows.graph import run_agent_workflow

ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = str(ROOT / "data" / "portfolio_v1.yaml")
RULES = str(ROOT / "config" / "strategy_rules.yaml")
CONSTRAINTS = str(ROOT / "config" / "constraints.yaml")


def test_evaluation_valid_schedule_and_existing_conflicts():
    state = run_agent_workflow(
        "Optimize schedule to minimize cost",
        PORTFOLIO,
        RULES,
        CONSTRAINTS,
        thread_id="eval-valid",
    )
    rep = state["evaluation_report"]
    # portfolio_v1 has pre-existing LIC-04 conflict on APP-08 -> PASS_WITH_WARNINGS
    assert rep["status"] in ("PASS", "PASS_WITH_WARNINGS")
    assert rep["planning_validity"] is True
    assert rep["financial_validity"] is True
    assert rep["hard_violations"] == []
    assert len(rep["existing_conflicts"]) >= 1


def test_evaluation_hard_violation_fails_and_cannot_pass():
    state = run_agent_workflow(
        "Optimize schedule to minimize cost",
        PORTFOLIO,
        RULES,
        CONSTRAINTS,
        thread_id="eval-hard",
    )
    bad_state = dict(state)
    opt_res = dict(state["optimization_results"]["optimization_result"])
    scheds = dict(opt_res["asset_schedules"])
    scheds["APP-06"] = {**scheds["APP-06"], "wave": 1}
    scheds["APP-07"] = {**scheds["APP-07"], "wave": 4}
    opt_res["asset_schedules"] = scheds
    bad_state["optimization_results"] = {
        "optimization_result": opt_res,
        "comparison": state["optimization_results"]["comparison"],
    }
    rep = evaluate_workflow_state(bad_state)  # type: ignore[arg-type]
    assert rep.status == "FAIL"
    assert rep.planning_validity is False
    assert len(rep.hard_violations) >= 1


def test_evaluation_missing_evidence_is_incomplete():
    state = {
        "user_request": "Analyze dependencies",
        "portfolio_path": PORTFOLIO,
        "rules_path": RULES,
        "constraints_path": CONSTRAINTS,
        "required_agents": ["dependency_agent"],
        "dependency_analysis": {},
        "agent_messages": [],
        "errors": [],
    }
    rep = evaluate_workflow_state(state)  # type: ignore[arg-type]
    assert rep.status == "INCOMPLETE"
    assert rep.missing_evidence


def test_evaluation_benchmark_suite_runs_all_10_cases():
    results = run_benchmark_suite()
    assert len(results) == 10
    assert results[0]["eval_status"] in ("PASS", "PASS_WITH_WARNINGS")
    assert results[2]["eval_status"] == "FAIL"
    assert results[4]["critic_decision"] == "BLOCKED"
    assert results[7]["final_approval_status"] == "approved"
    assert results[8]["final_approval_status"] == "rejected"
