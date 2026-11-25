"""Tests for Phase 3 bounded correction loop and duplicate-signature prevention."""
from pathlib import Path
from carveout.agents.critic_agent import evaluate_critic_decision
from carveout.tools.correction_tools import execute_correction_action
from carveout.workflows.state import EvaluationReport

ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = str(ROOT / "data" / "portfolio_v1.yaml")
RULES = str(ROOT / "config" / "strategy_rules.yaml")
CONSTRAINTS = str(ROOT / "config" / "constraints.yaml")


def test_correction_loop_executes_and_prevents_identical_repeat():
    rep = EvaluationReport(
        evaluation_id="EVAL-LOOP", status="FAIL", overall_score=0.5, evidence_coverage=1.0,
        planning_validity=False, financial_validity=True, execution_validity=True,
    )
    state = {
        "user_request": "Optimize schedule",
        "portfolio_path": PORTFOLIO,
        "rules_path": RULES,
        "constraints_path": CONSTRAINTS,
        "evaluation_report": rep.model_dump(),
        "correction_attempts": 0,
        "max_correction_attempts": 2,
        "correction_history": [],
        "optimization_results": {
            "optimization_result": {"status": "INFEASIBLE", "objective_name": "minimize_cost"},
            "comparison": {"scenario_id": "minimize_cost"},
        },
    }
    dec = evaluate_critic_decision(state)  # type: ignore[arg-type]
    assert dec.decision == "CORRECTION_REQUIRED"
    assert dec.correction_request is not None
    sig = dec.correction_request.signature

    # Apply correction
    updates = execute_correction_action(state, dec.correction_request.model_dump())  # type: ignore[arg-type]
    assert updates["correction_attempts"] == 1
    assert len(updates["correction_history"]) == 1
    assert updates["optimization_results"]["optimization_result"]["status"] == "OPTIMAL"

    # If the exact same failure recurred with signature already in correction_history, critic must NOT repeat it
    state["correction_attempts"] = 1
    state["correction_history"] = updates["correction_history"]
    dec2 = evaluate_critic_decision(state)  # type: ignore[arg-type]
    assert sig == "opt:increase_max_waves:16"
    assert dec2.decision == "BLOCKED"
