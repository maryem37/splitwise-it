"""Human-in-the-loop approval gate using LangGraph interrupt()."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langgraph.types import interrupt

from carveout.workflows.state import CarveoutState, HumanApprovalDecision


def _build_approval_payload(state: CarveoutState) -> dict[str, Any]:
    eval_rep = state.get("evaluation_report", {})
    critic_dec = state.get("critic_decision", {})
    opt_data = state.get("optimization_results", {})
    comp = opt_data.get("comparison", {})
    opt_res = opt_data.get("optimization_result", {})

    return {
        "requested_action": "HUMAN_APPROVAL",
        "allowed_decisions": ["APPROVE", "REJECT", "REQUEST_REVISION"],
        "user_request": state.get("user_request", ""),
        "scenario": comp.get("scenario_id", "baseline"),
        "evaluation_report": eval_rep,
        "critic_decision": critic_dec,
        "hard_violations": eval_rep.get("hard_violations", []),
        "warnings": eval_rep.get("warnings", []),
        "existing_conflicts": eval_rep.get("existing_conflicts", []),
        "tsa_cost": comp.get("scenario_tsa_cost", state.get("risk_assessment", {}).get("tsa_cost_total", 0.0)),
        "tsa_delta": comp.get("additional_tsa_cost", 0.0),
        "latest_completion_date": comp.get("scenario_completion", opt_res.get("latest_completion_date", "")),
        "total_waves": comp.get("scenario_waves", opt_res.get("total_waves", 0)),
    }


def check_approval_gate(state: CarveoutState) -> dict[str, Any]:
    """
    Human-in-the-loop gate.
    When enable_human_interrupt=True, pauses execution via LangGraph interrupt()
    until resumed with Command(resume={"action": "APPROVE" | "REJECT" | "REQUEST_REVISION", ...}).
    When enable_human_interrupt=False (non-interactive mode), marks ready_for_review.
    """
    if not state.get("enable_human_interrupt", False):
        return {
            "approval_status": "ready_for_review",
            "workflow_status": state.get("workflow_status") or "ready_for_review",
            "execution_trace": ["approval_node:ready_for_review"],
            "agent_messages": [{
                "agent": "ApprovalGate",
                "content": "Non-interactive run completed; approval status: ready_for_review.",
            }],
        }

    payload = _build_approval_payload(state)
    raw_decision = interrupt(payload)

    if isinstance(raw_decision, str):
        raw_decision = {"action": raw_decision}
    elif not isinstance(raw_decision, dict):
        raw_decision = {"action": "REJECT", "comment": f"Invalid payload type: {type(raw_decision).__name__}"}

    action_val = str(raw_decision.get("action", "")).strip().upper()
    if action_val not in ("APPROVE", "REJECT", "REQUEST_REVISION"):
        # Explicit validation: Reject unrecognised actions
        action_val = "REJECT"
        if not raw_decision.get("comment"):
            raw_decision["comment"] = f"Invalid approval action '{raw_decision.get('action')}' supplied; defaulted to REJECT."

    decision = HumanApprovalDecision.model_validate({
        "action": action_val,
        "reviewer": raw_decision.get("reviewer") or "human_reviewer",
        "comment": raw_decision.get("comment") or "",
        "timestamp": raw_decision.get("timestamp") or datetime.now(timezone.utc).isoformat(),
    })

    history_entry = decision.model_dump()

    if decision.action == "APPROVE":
        return {
            "approval_status": "approved",
            "workflow_status": "approved",
            "human_approval": history_entry,
            "approval_history": [history_entry],
            "execution_trace": ["approval_node:APPROVE"],
            "agent_messages": [{
                "agent": "ApprovalGate",
                "content": f"Approved by {decision.reviewer}.",
            }],
        }

    if decision.action == "REQUEST_REVISION":
        attempts = int(state.get("correction_attempts", 0))
        max_attempts = int(state.get("max_correction_attempts", 2))
        if attempts < max_attempts:
            return {
                "approval_status": "revision_requested",
                "workflow_status": "revision_requested",
                "human_approval": history_entry,
                "approval_history": [history_entry],
                "pending_correction": {
                    "target_agent": "optimization_agent",
                    "action": "rerun_optimization_with_params",
                    "parameters": {
                        "scenario_type": payload["scenario"],
                        "objective": "balanced",
                    },
                    "reason": f"Human requested revision: {decision.comment or 're-optimize'}",
                    "signature": f"human_rev:{attempts + 1}",
                },
                "execution_trace": ["approval_node:REQUEST_REVISION"],
                "agent_messages": [{
                    "agent": "ApprovalGate",
                    "content": f"Revision requested by {decision.reviewer}; routing to bounded correction.",
                }],
            }
        return {
            "approval_status": "revision_limit_reached",
            "workflow_status": "revision_limit_reached",
            "human_approval": history_entry,
            "approval_history": [history_entry],
            "execution_trace": ["approval_node:REVISION_LIMIT_REACHED"],
            "agent_messages": [{
                "agent": "ApprovalGate",
                "content": "Human requested revision, but maximum correction attempts reached.",
            }],
        }

    # REJECT
    return {
        "approval_status": "rejected",
        "workflow_status": "rejected",
        "human_approval": history_entry,
        "approval_history": [history_entry],
        "execution_trace": ["approval_node:REJECT"],
        "agent_messages": [{
            "agent": "ApprovalGate",
            "content": f"Rejected by {decision.reviewer}: {decision.comment}",
        }],
    }
