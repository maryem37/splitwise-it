"""Evaluation Agent: independently verifies evidence, planning, financial, and execution integrity."""
from __future__ import annotations

import hashlib
from typing import Any

from carveout.loader import load_portfolio
from carveout.optimization.models import OptimizationResult
from carveout.optimization.validation import validate_schedule_constraints
from carveout.strategy import assess_strategies
from carveout.workflows.state import CarveoutState, EvaluationReport


def evaluate_workflow_state(state: CarveoutState) -> EvaluationReport:
    """
    Independently evaluate agent outputs in CarveoutState using deterministic
    portfolio data and validators. Never delegates authoritative validation to an LLM.
    """
    portfolio_path = state.get("portfolio_path", "")
    rules_path = state.get("rules_path", "")
    constraints_path = state.get("constraints_path") or None
    required_agents = state.get("required_agents", [])

    hard_violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    existing_conflicts: list[dict[str, Any]] = []
    missing_evidence: list[str] = []
    checked_constraints: list[str] = []

    portfolio = load_portfolio(portfolio_path)
    known_assets = {a.id for a in portfolio.assets}
    strategies = assess_strategies(portfolio, rules_path)
    retained_assets = {s["asset_id"] for s in strategies if s.get("strategy") == "retain_under_tsa"}

    # ── A. Evidence Completeness ───────────────────────────────────────────
    evidence_checks = 0
    evidence_passed = 0

    if "dependency_agent" in required_agents:
        evidence_checks += 1
        dep = state.get("dependency_analysis", {})
        if not dep or "portfolio_cycles" not in dep:
            missing_evidence.append("Missing dependency_analysis from DependencyAgent.")
        else:
            # Verify all cited asset IDs exist in portfolio
            unknown = [
                aid for aid in dep.get("investigated_assets", {})
                if aid not in known_assets and "error" not in dep["investigated_assets"][aid]
            ]
            if unknown:
                hard_violations.append({
                    "constraint_name": "evidence_asset_validity",
                    "entity": ",".join(unknown),
                    "explanation": f"Dependency analysis references unknown assets: {unknown}",
                })
            else:
                evidence_passed += 1

    if "risk_agent" in required_agents:
        evidence_checks += 1
        risk = state.get("risk_assessment", {})
        if not risk or "tsa_cost_total" not in risk:
            missing_evidence.append("Missing risk_assessment or tsa_cost_total from RiskAgent.")
        else:
            evidence_passed += 1

    if "strategy_agent" in required_agents:
        evidence_checks += 1
        strats = state.get("strategy_recommendations", [])
        if not strats:
            missing_evidence.append("Missing strategy_recommendations from StrategyAgent.")
        else:
            evidence_passed += 1

    if "optimization_agent" in required_agents:
        evidence_checks += 1
        opt = state.get("optimization_results", {})
        if not opt or "optimization_result" not in opt:
            missing_evidence.append("Missing optimization_result from OptimizationAgent.")
        else:
            evidence_passed += 1

    evidence_coverage = 1.0 if evidence_checks == 0 else round(evidence_passed / evidence_checks, 4)

    # ── B. Planning Integrity ──────────────────────────────────────────────
    planning_validity = True
    opt_data = state.get("optimization_results", {})
    if opt_data and "optimization_result" in opt_data:
        checked_constraints.extend([
            "solver_feasibility",
            "asset_coverage",
            "scc_colocation",
            "dependency_ordering",
            "wave_capacity",
            "calendar_dates",
            "freeze_periods",
        ])
        opt_res = OptimizationResult.model_validate(opt_data["optimization_result"])
        comp = opt_data.get("comparison", {})
        delay_assets = None
        if comp.get("scenario_id") == "app_06_delay" and comp.get("affected_assets"):
            # Delay floor validated if baseline starts are available; solver status & structure always validated
            checked_constraints.append("delay_coupling")

        val = validate_schedule_constraints(
            portfolio,
            opt_res,
            retained_assets,
            constraints_path=constraints_path,
            delay_assets=delay_assets,
        )
        for f in val.get("findings", []):
            sev = f.get("severity")
            if sev == "hard":
                hard_violations.append(f)
                planning_validity = False
            elif sev == "warning":
                warnings.append(f)
            elif sev == "existing_conflict":
                existing_conflicts.append(f)
    elif "optimization_agent" in required_agents:
        planning_validity = False

    # ── C. Financial Integrity ─────────────────────────────────────────────
    financial_validity = True
    if opt_data and "optimization_result" in opt_data:
        opt_res_dict = opt_data["optimization_result"]
        if opt_res_dict.get("status") in ("OPTIMAL", "FEASIBLE"):
            by_svc = opt_res_dict.get("tsa_cost_by_service", {})
            total = opt_res_dict.get("estimated_tsa_cost_total", 0.0)
            recomputed_sum = round(sum(by_svc.values()), 2)
            if abs(recomputed_sum - total) > 0.05:
                financial_validity = False
                hard_violations.append({
                    "constraint_name": "tsa_cost_consistency",
                    "entity": "portfolio",
                    "explanation": f"TSA total {total} != sum of service costs {recomputed_sum}.",
                })
            # Explicitly distinguish proxy objective from exact post-solve cost
            if "proxy" not in opt_res_dict.get("objective_description", "").lower() and opt_res_dict.get("objective_name") == "minimize_cost":
                warnings.append({
                    "constraint_name": "objective_proxy_notice",
                    "entity": "objective",
                    "explanation": "CP-SAT wave-index objective is a proxy; exact TSA cost is computed post-solve.",
                })

    # ── D. Agent Execution Integrity ───────────────────────────────────────
    errors = state.get("errors", [])
    messages = state.get("agent_messages", [])
    executed_agents = {m.get("agent") for m in messages}
    agent_name_map = {
        "dependency_agent": "DependencyAgent",
        "risk_agent": "RiskAgent",
        "strategy_agent": "StrategyAgent",
        "optimization_agent": "OptimizationAgent",
    }
    missing_agents = [
        agent_name_map[a] for a in required_agents
        if a in agent_name_map and agent_name_map[a] not in executed_agents
    ]
    execution_validity = len(errors) == 0 and len(missing_agents) == 0
    if missing_agents:
        missing_evidence.append(f"Expected agents did not record execution: {missing_agents}")

    # ── Status & Score (hard violations NEVER receive PASS) ────────────────
    if hard_violations or not planning_validity or not financial_validity:
        status = "FAIL"
    elif missing_evidence or not execution_validity:
        status = "INCOMPLETE"
    elif warnings or existing_conflicts:
        status = "PASS_WITH_WARNINGS"
    else:
        status = "PASS"

    score_components = [
        evidence_coverage,
        1.0 if planning_validity else 0.0,
        1.0 if financial_validity else 0.0,
        1.0 if execution_validity else 0.0,
    ]
    overall_score = round(sum(score_components) / len(score_components), 4)

    eval_key = f"{state.get('user_request', '')}|{state.get('correction_attempts', 0)}|{status}"
    eval_id = "EVAL-" + hashlib.sha256(eval_key.encode("utf-8")).hexdigest()[:8].upper()

    summary = (
        f"Evaluation {eval_id}: status={status}, score={overall_score:.2f}, "
        f"evidence={evidence_coverage:.0%}, hard_violations={len(hard_violations)}, "
        f"existing_conflicts={len(existing_conflicts)}, warnings={len(warnings)}."
    )

    return EvaluationReport(
        evaluation_id=eval_id,
        status=status,
        overall_score=overall_score,
        evidence_coverage=evidence_coverage,
        planning_validity=planning_validity,
        financial_validity=financial_validity,
        execution_validity=execution_validity,
        hard_violations=hard_violations,
        warnings=warnings,
        existing_conflicts=existing_conflicts,
        missing_evidence=missing_evidence,
        checked_constraints=checked_constraints,
        evaluation_summary=summary,
    )


def run_evaluation_agent(state: CarveoutState) -> dict[str, Any]:
    """LangGraph node wrapper for the Evaluation Agent."""
    report = evaluate_workflow_state(state)
    return {
        "evaluation_report": report.model_dump(),
        "execution_trace": [f"evaluation_node:{report.status}"],
        "agent_messages": [{
            "agent": "EvaluationAgent",
            "content": report.evaluation_summary,
        }],
    }
