"""Critic Agent: applies deterministic decision policy over EvaluationReport findings."""
from __future__ import annotations

import hashlib
from typing import Any

from carveout.config import GROQ_API_KEY, GROQ_MODEL
from carveout.workflows.state import (
    CarveoutState,
    CorrectionRequest,
    CriticDecision,
    EvaluationFinding,
    EvaluationReport,
)


def _make_finding(
    category: str,
    severity: str,
    description: str,
    evidence: str = "",
    affected_assets: list[str] | None = None,
    recommended_action: str = "",
) -> EvaluationFinding:
    fid = "FND-" + hashlib.sha256(f"{category}|{severity}|{description}".encode("utf-8")).hexdigest()[:6].upper()
    return EvaluationFinding(
        finding_id=fid,
        category=category,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        description=description,
        evidence=evidence,
        affected_assets=affected_assets or [],
        recommended_action=recommended_action,
    )


def evaluate_critic_decision(state: CarveoutState) -> CriticDecision:
    """
    Produce a deterministic CriticDecision from EvaluationReport and workflow state.
    An LLM may refine the rationale text, but NEVER overrides the deterministic decision.
    """
    raw_report = state.get("evaluation_report", {})
    report = EvaluationReport.model_validate(raw_report)
    attempts = int(state.get("correction_attempts", 0))
    max_attempts = int(state.get("max_correction_attempts", 2))
    history = state.get("correction_history", [])
    used_signatures = {item.get("signature") for item in history}

    findings: list[EvaluationFinding] = []
    for hv in report.hard_violations:
        findings.append(_make_finding(
            category="planning",
            severity="hard",
            description=hv.get("explanation", str(hv)),
            evidence=f"constraint={hv.get('constraint_name', 'unknown')}",
            affected_assets=[hv["entity"]] if hv.get("entity") else [],
            recommended_action="Re-run optimization or resolve hard constraint violation.",
        ))
    for ec in report.existing_conflicts:
        findings.append(_make_finding(
            category="financial",
            severity="existing_conflict",
            description=ec.get("explanation", str(ec)),
            evidence=f"expected={ec.get('expected', '')}, actual={ec.get('actual', '')}",
            affected_assets=[ec["entity"]] if ec.get("entity") else [],
            recommended_action="Review and accept or mitigate pre-existing deadline conflict.",
        ))
    for w in report.warnings:
        findings.append(_make_finding(
            category="planning",
            severity="warning",
            description=w.get("explanation", str(w)),
            evidence=w.get("constraint_name", ""),
            affected_assets=[w["entity"]] if w.get("entity") else [],
            recommended_action="Verify non-blocking warning prior to execution.",
        ))
    for me in report.missing_evidence:
        findings.append(_make_finding(
            category="evidence",
            severity="hard",
            description=me,
            recommended_action="Re-run missing investigation agent.",
        ))

    opt_data = state.get("optimization_results", {})
    opt_res = opt_data.get("optimization_result", {})
    solver_status = opt_res.get("status", "")

    # Deterministic policy (never overridden by LLM)
    correction_req: CorrectionRequest | None = None
    decision: str
    rationale: str
    requires_human = False

    if solver_status in ("INFEASIBLE", "MODEL_INVALID"):
        # Only attempt bounded parameter change if not already tried
        sig = "opt:increase_max_waves:16"
        if attempts < max_attempts and sig not in used_signatures and solver_status == "INFEASIBLE":
            decision = "CORRECTION_REQUIRED"
            correction_req = CorrectionRequest(
                target_agent="optimization_agent",
                action="rerun_optimization_with_params",
                parameters={
                    "scenario_type": opt_data.get("comparison", {}).get("scenario_id", "minimize_cost"),
                    "objective": opt_res.get("objective_name", "minimize_cost"),
                    "max_waves": 16,
                },
                reason="Solver returned INFEASIBLE; retrying with expanded max_waves=16.",
                signature=sig,
            )
            rationale = f"Solver returned {solver_status}. Requesting bounded optimization retry with max_waves=16."
        else:
            decision = "BLOCKED"
            rationale = f"Schedule is {solver_status}; no permitted parameter adjustment can resolve infeasibility."

    elif report.status == "FAIL":
        sig = f"opt:reoptimize:{attempts + 1}"
        if attempts < max_attempts and sig not in used_signatures and opt_data:
            decision = "CORRECTION_REQUIRED"
            correction_req = CorrectionRequest(
                target_agent="optimization_agent",
                action="rerun_optimization_with_params",
                parameters={
                    "scenario_type": opt_data.get("comparison", {}).get("scenario_id", "minimize_cost"),
                    "objective": opt_res.get("objective_name", "minimize_cost"),
                    "max_waves": 12,
                },
                reason=f"Hard validation failure: {report.hard_violations[0].get('explanation', '') if report.hard_violations else 'planning invalid'}",
                signature=sig,
            )
            rationale = "Hard constraint violations detected; triggering bounded re-optimization."
        else:
            decision = "BLOCKED"
            rationale = (
                f"Hard constraint violations remain after {attempts} correction attempt(s); "
                "plan is blocked from approval."
            )

    elif report.status == "INCOMPLETE":
        if attempts < max_attempts:
            missing_text = " ".join(report.missing_evidence).lower()
            if "dependency" in missing_text and "dep:rerun" not in used_signatures:
                correction_req = CorrectionRequest(
                    target_agent="dependency_agent",
                    action="rerun_dependency_investigation",
                    parameters={},
                    reason="Missing dependency_analysis evidence.",
                    signature="dep:rerun",
                )
            elif "risk" in missing_text and "risk:rerun" not in used_signatures:
                correction_req = CorrectionRequest(
                    target_agent="risk_agent",
                    action="rerun_risk_investigation",
                    parameters={},
                    reason="Missing risk_assessment evidence.",
                    signature="risk:rerun",
                )
            elif "opt:rerun_missing" not in used_signatures:
                correction_req = CorrectionRequest(
                    target_agent="optimization_agent",
                    action="rerun_optimization_with_params",
                    parameters={"scenario_type": "minimize_cost", "objective": "minimize_cost"},
                    reason="Missing optimization_results evidence.",
                    signature="opt:rerun_missing",
                )

        if correction_req is not None:
            decision = "CORRECTION_REQUIRED"
            rationale = f"Incomplete evidence ({len(report.missing_evidence)} item(s)); requesting targeted agent re-run."
        else:
            decision = "HUMAN_REVIEW_REQUIRED"
            requires_human = True
            rationale = f"Evidence remains incomplete after {attempts} correction attempt(s); escalating to human review."

    elif report.existing_conflicts or report.warnings:
        decision = "HUMAN_REVIEW_REQUIRED"
        requires_human = True
        rationale = (
            f"Schedule is structurally valid with {len(report.existing_conflicts)} existing conflict(s) "
            f"and {len(report.warnings)} warning(s) requiring human business acceptance."
        )
    else:
        decision = "ACCEPTED"
        requires_human = True
        rationale = "All evidence, planning, financial, and execution checks passed with zero violations."

    # Optional LLM narrative refinement for rationale ONLY (decision is immutable)
    if GROQ_API_KEY:
        try:
            from langchain_groq import ChatGroq
            from langchain_core.messages import HumanMessage, SystemMessage

            llm = ChatGroq(model=GROQ_MODEL, temperature=0.0, api_key=GROQ_API_KEY)
            resp = llm.invoke([
                SystemMessage(content="Summarize this deterministic Critic decision in 2 concise sentences. Do not change the decision."),
                HumanMessage(content=f"Decision={decision}. Rationale={rationale}. Summary={report.evaluation_summary}"),
            ])
            if resp.content and decision in resp.content.upper():
                rationale = resp.content
        except Exception:
            pass

    return CriticDecision(
        decision=decision,  # type: ignore[arg-type]
        rationale=rationale,
        findings=findings,
        correction_request=correction_req,
        requires_human_approval=requires_human,
    )


def run_critic_agent(state: CarveoutState) -> dict[str, Any]:
    """LangGraph node wrapper for the Critic Agent."""
    decision = evaluate_critic_decision(state)
    return {
        "critic_decision": decision.model_dump(),
        "pending_correction": decision.correction_request.model_dump() if decision.correction_request else {},
        "human_review_required": decision.requires_human_approval,
        "workflow_status": decision.decision.lower(),
        "execution_trace": [f"critic_node:{decision.decision}"],
        "agent_messages": [{
            "agent": "CriticAgent",
            "content": f"Decision: {decision.decision} — {decision.rationale}",
        }],
    }
