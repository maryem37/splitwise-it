"""Bounded, read-only correction tools for self-correcting LangGraph loops."""
from __future__ import annotations

from typing import Any

from carveout.agents.dependency_agent import run_dependency_agent
from carveout.agents.risk_agent import run_risk_agent
from carveout.optimization.models import OptimizationConfig
from carveout.optimization.scenarios import run_scenario
from carveout.workflows.state import CarveoutState


def execute_correction_action(state: CarveoutState, correction: dict[str, Any]) -> dict[str, Any]:
    """
    Execute an explicit, bounded correction action without modifying any source YAML files.
    Supported actions:
      - rerun_dependency_investigation
      - rerun_risk_investigation
      - rerun_optimization_with_params
    Includes loop hardening:
      - Prevents duplicate corrections if the identical signature was previously applied.
    """
    action = correction.get("action", "")
    params = correction.get("parameters", {})
    signature = correction.get("signature", action)
    attempts = int(state.get("correction_attempts", 0)) + 1
    existing_history = state.get("correction_history", [])

    # Check for duplicate identical correction signature in history
    previous_signatures = {h.get("signature") for h in existing_history if isinstance(h, dict) and h.get("signature")}
    if signature in previous_signatures:
        blocked_entry = {
            "attempt": attempts,
            "target_agent": correction.get("target_agent", ""),
            "action": action,
            "parameters": params,
            "reason": f"Duplicate correction signature '{signature}' detected; preventing non-progressing cycle.",
            "signature": signature,
            "status": "blocked_duplicate",
        }
        return {
            "correction_attempts": attempts,
            "correction_history": [blocked_entry],
            "pending_correction": {},
            "workflow_status": "blocked",
            "errors": [f"Correction loop stopped: Duplicate correction action '{signature}' detected without parameter progression."],
            "execution_trace": [f"correction_node:duplicate_blocked:{signature}"],
            "agent_messages": [{
                "agent": "CorrectionExecutor",
                "content": f"Correction loop blocked: Repeated identical action '{signature}' detected.",
            }],
        }

    history_entry = {
        "attempt": attempts,
        "target_agent": correction.get("target_agent", ""),
        "action": action,
        "parameters": params,
        "reason": correction.get("reason", ""),
        "signature": signature,
        "status": "applied",
    }

    if action == "rerun_dependency_investigation":
        updates = run_dependency_agent(state)
        updates["correction_attempts"] = attempts
        updates["correction_history"] = [history_entry]
        updates["pending_correction"] = {}
        updates["execution_trace"] = [f"correction_node:{action}"]
        return updates

    if action == "rerun_risk_investigation":
        updates = run_risk_agent(state)
        updates["correction_attempts"] = attempts
        updates["correction_history"] = [history_entry]
        updates["pending_correction"] = {}
        updates["execution_trace"] = [f"correction_node:{action}"]
        return updates

    if action == "rerun_optimization_with_params":
        portfolio_path = state.get("portfolio_path", "")
        rules_path = state.get("rules_path", "")
        constraints_path = state.get("constraints_path") or None

        scenario_type = str(params.get("scenario_type", "minimize_cost"))
        objective = str(params.get("objective", "minimize_cost"))
        delay_weeks = int(params.get("delay_weeks", 12))
        max_waves = min(20, max(4, int(params.get("max_waves", 12))))
        max_solve_time = min(30.0, max(2.0, float(params.get("max_solve_time_seconds", 10.0))))

        cfg = OptimizationConfig(
            objective=objective,
            max_waves=max_waves,
            max_solve_time_seconds=max_solve_time,
        )
        res, comp = run_scenario(
            portfolio_path=portfolio_path,
            rules_path=rules_path,
            scenario_type=scenario_type,
            delay_weeks=delay_weeks,
            objective=objective,
            config=cfg,
            constraints_path=constraints_path,
        )
        opt_payload = {
            "optimization_result": res.model_dump(),
            "comparison": comp.model_dump(),
            "explanation": f"Re-ran CP-SAT optimization ({action}, max_waves={max_waves}, objective={objective}).",
        }
        return {
            "optimization_results": opt_payload,
            "correction_attempts": attempts,
            "correction_history": [history_entry],
            "pending_correction": {},
            "execution_trace": [f"correction_node:{action}"],
            "agent_messages": [{
                "agent": "CorrectionExecutor",
                "content": f"Applied {action} (attempt {attempts}): status={res.status}.",
            }],
        }

    history_entry["status"] = "rejected_unknown_action"
    return {
        "correction_attempts": attempts,
        "correction_history": [history_entry],
        "pending_correction": {},
        "errors": [f"Unsupported correction action: {action}"],
        "execution_trace": [f"correction_node:invalid:{action}"],
    }
