"""Tests for Phase 3 Critic Agent decision policy."""
from pathlib import Path
from carveout.agents.critic_agent import evaluate_critic_decision
from carveout.workflows.state import EvaluationReport

ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = str(ROOT / "data" / "portfolio_v1.yaml")
RULES = str(ROOT / "config" / "strategy_rules.yaml")
CONSTRAINTS = str(ROOT / "config" / "constraints.yaml")


def _base_state(report: EvaluationReport, attempts: int = 0, max_attempts: int = 2, solver_status: str = "OPTIMAL"):
    return {
        "user_request": "Optimize schedule",
        "portfolio_path": PORTFOLIO,
        "rules_path": RULES,
        "constraints_path": CONSTRAINTS,
        "evaluation_report": report.model_dump(),
        "correction_attempts": attempts,
        "max_correction_attempts": max_attempts,
        "correction_history": [],
        "optimization_results": {
            "optimization_result": {"status": solver_status, "objective_name": "minimize_cost"},
            "comparison": {"scenario_id": "minimize_cost"},
        },
    }


def test_critic_accepts_clean_pass():
    rep = EvaluationReport(
        evaluation_id="EVAL-1", status="PASS", overall_score=1.0, evidence_coverage=1.0,
        planning_validity=True, financial_validity=True, execution_validity=True,
    )
    dec = evaluate_critic_decision(_base_state(rep))  # type: ignore[arg-type]
    assert dec.decision == "ACCEPTED"
    assert dec.requires_human_approval is True


def test_critic_routes_existing_conflicts_to_human_review():
    rep = EvaluationReport(
        evaluation_id="EVAL-2", status="PASS_WITH_WARNINGS", overall_score=1.0, evidence_coverage=1.0,
        planning_validity=True, financial_validity=True, execution_validity=True,
        existing_conflicts=[{"constraint_name": "licence_deadline", "entity": "APP-08", "explanation": "LIC-04"}],
    )
    dec = evaluate_critic_decision(_base_state(rep))  # type: ignore[arg-type]
    assert dec.decision == "HUMAN_REVIEW_REQUIRED"
    assert dec.requires_human_approval is True


def test_critic_triggers_correction_on_hard_failure_then_blocks_at_limit():
    rep = EvaluationReport(
        evaluation_id="EVAL-3", status="FAIL", overall_score=0.5, evidence_coverage=1.0,
        planning_validity=False, financial_validity=True, execution_validity=True,
        hard_violations=[{"constraint_name": "scc_colocation", "entity": "APP-06,APP-07", "explanation": "Split SCC"}],
    )
    dec1 = evaluate_critic_decision(_base_state(rep, attempts=0, max_attempts=2))  # type: ignore[arg-type]
    assert dec1.decision == "CORRECTION_REQUIRED"
    assert dec1.correction_request is not None

    dec2 = evaluate_critic_decision(_base_state(rep, attempts=2, max_attempts=2))  # type: ignore[arg-type]
    assert dec2.decision == "BLOCKED"


def test_critic_blocks_infeasible_after_retry_exhausted():
    rep = EvaluationReport(
        evaluation_id="EVAL-4", status="FAIL", overall_score=0.5, evidence_coverage=1.0,
        planning_validity=False, financial_validity=True, execution_validity=True,
    )
    dec = evaluate_critic_decision(_base_state(rep, attempts=1, max_attempts=1, solver_status="INFEASIBLE"))  # type: ignore[arg-type]
    assert dec.decision == "BLOCKED"
