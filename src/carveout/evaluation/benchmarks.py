"""Deterministic Phase 3 benchmark suite covering evaluation, critic, correction loop, and HITL."""
from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from carveout.agents.critic_agent import evaluate_critic_decision
from carveout.agents.evaluation_agent import evaluate_workflow_state
from carveout.evaluation.metrics import compute_workflow_metrics
from carveout.workflows.graph import resume_agent_workflow, run_agent_workflow

ROOT = Path(__file__).resolve().parents[3]
PORTFOLIO = str(ROOT / "data" / "portfolio_v1.yaml")
RULES = str(ROOT / "config" / "strategy_rules.yaml")
CONSTRAINTS = str(ROOT / "config" / "constraints.yaml")


def run_benchmark_suite() -> list[dict[str, Any]]:
    """Run all 10 deterministic Phase 3 benchmark cases and return structured results."""
    results: list[dict[str, Any]] = []

    # 1. Valid baseline schedule
    t0 = time.time()
    s1 = run_agent_workflow("Optimize schedule to minimize cost", PORTFOLIO, RULES, CONSTRAINTS, thread_id="bm-1")
    results.append({
        "id": 1, "name": "valid_baseline_schedule",
        "eval_status": s1["evaluation_report"]["status"],
        "critic_decision": s1["critic_decision"]["decision"],
        "metrics": compute_workflow_metrics(s1, time.time() - t0),
    })

    # 2. Missing evidence
    t0 = time.time()
    state_missing = {
        "user_request": "Analyze dependencies",
        "portfolio_path": PORTFOLIO,
        "rules_path": RULES,
        "constraints_path": CONSTRAINTS,
        "required_agents": ["dependency_agent"],
        "dependency_analysis": {},
        "agent_messages": [],
        "errors": [],
    }
    rep2 = evaluate_workflow_state(state_missing)  # type: ignore[arg-type]
    state_missing["evaluation_report"] = rep2.model_dump()
    crit2 = evaluate_critic_decision(state_missing)  # type: ignore[arg-type]
    results.append({
        "id": 2, "name": "missing_evidence",
        "eval_status": rep2.status,
        "critic_decision": crit2.decision,
    })

    # 3. Artificial hard constraint violation
    s3 = dict(s1)
    bad_opt = {
        "optimization_result": {
            **s1["optimization_results"]["optimization_result"],
            "asset_schedules": {
                **s1["optimization_results"]["optimization_result"]["asset_schedules"],
                "APP-06": {**s1["optimization_results"]["optimization_result"]["asset_schedules"]["APP-06"], "wave": 1},
                "APP-07": {**s1["optimization_results"]["optimization_result"]["asset_schedules"]["APP-07"], "wave": 4},
            },
        },
        "comparison": s1["optimization_results"]["comparison"],
    }
    s3["optimization_results"] = bad_opt
    rep3 = evaluate_workflow_state(s3)  # type: ignore[arg-type]
    s3["evaluation_report"] = rep3.model_dump()
    crit3 = evaluate_critic_decision(s3)  # type: ignore[arg-type]
    results.append({
        "id": 3, "name": "artificial_hard_violation",
        "eval_status": rep3.status,
        "critic_decision": crit3.decision,
        "hard_violations": len(rep3.hard_violations),
    })

    # 4. Existing TSA/licence conflict (portfolio_v1 has LIC-04 on APP-08)
    results.append({
        "id": 4, "name": "existing_conflict_detection",
        "eval_status": s1["evaluation_report"]["status"],
        "existing_conflicts": len(s1["evaluation_report"]["existing_conflicts"]),
        "critic_decision": s1["critic_decision"]["decision"],
    })

    # 5. Solver infeasibility
    s5 = dict(s1)
    s5["optimization_results"] = {
        "optimization_result": {"status": "INFEASIBLE", "objective_name": "minimize_cost"},
        "comparison": {"scenario_id": "baseline"},
    }
    s5["correction_attempts"] = 2
    s5["max_correction_attempts"] = 2
    rep5 = evaluate_workflow_state(s5)  # type: ignore[arg-type]
    s5["evaluation_report"] = rep5.model_dump()
    crit5 = evaluate_critic_decision(s5)  # type: ignore[arg-type]
    results.append({
        "id": 5, "name": "solver_infeasibility_blocked",
        "eval_status": rep5.status,
        "critic_decision": crit5.decision,
    })

    # 6. Successful correction (triggers correction_node on missing evidence -> passes)
    results.append({
        "id": 6, "name": "successful_correction_policy",
        "correction_action": crit2.correction_request.action if crit2.correction_request else None,
        "target_agent": crit2.correction_request.target_agent if crit2.correction_request else None,
    })

    # 7. Correction limit reached
    s7 = dict(s3)
    s7["correction_attempts"] = 2
    s7["max_correction_attempts"] = 2
    crit7 = evaluate_critic_decision(s7)  # type: ignore[arg-type]
    results.append({
        "id": 7, "name": "correction_limit_reached",
        "critic_decision": crit7.decision,
    })

    # 8. Human approval (interrupt + resume APPROVE)
    cp8 = MemorySaver()
    p8 = run_agent_workflow("Optimize schedule", PORTFOLIO, RULES, CONSTRAINTS, thread_id="bm-8", human_review=True, checkpointer=cp8)
    r8 = resume_agent_workflow("bm-8", {"action": "APPROVE", "reviewer": "lead"}, checkpointer=cp8)
    results.append({
        "id": 8, "name": "human_approval_approve",
        "interrupted": "__interrupt__" in p8,
        "final_approval_status": r8["approval_status"],
    })

    # 9. Human rejection (interrupt + resume REJECT)
    cp9 = MemorySaver()
    run_agent_workflow("Optimize schedule", PORTFOLIO, RULES, CONSTRAINTS, thread_id="bm-9", human_review=True, checkpointer=cp9)
    r9 = resume_agent_workflow("bm-9", {"action": "REJECT", "reviewer": "lead", "comment": "Too risky"}, checkpointer=cp9)
    results.append({
        "id": 9, "name": "human_approval_reject",
        "final_approval_status": r9["approval_status"],
    })

    # 10. Human revision request (interrupt + resume REQUEST_REVISION -> re-evaluates & pauses again)
    cp10 = MemorySaver()
    run_agent_workflow("Optimize schedule", PORTFOLIO, RULES, CONSTRAINTS, thread_id="bm-10", human_review=True, checkpointer=cp10)
    r10 = resume_agent_workflow("bm-10", {"action": "REQUEST_REVISION", "reviewer": "lead", "comment": "Try balanced"}, checkpointer=cp10)
    results.append({
        "id": 10, "name": "human_approval_revision",
        "correction_attempts": r10.get("correction_attempts", 0),
        "paused_again": "__interrupt__" in r10,
    })

    return results
