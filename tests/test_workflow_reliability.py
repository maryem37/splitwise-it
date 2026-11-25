"""Reliability tests: duplicate prevention, invalid payload safety, and portfolio immutability."""
from __future__ import annotations

import hashlib
from pathlib import Path
import pytest

from carveout.tools.correction_tools import execute_correction_action
from carveout.workflows.approval import check_approval_gate
from carveout.workflows.state import CarveoutState

PORTFOLIO = Path("data/portfolio_v1.yaml")
RULES = Path("config/strategy_rules.yaml")
CONSTRAINTS = Path("config/constraints.yaml")


def test_correction_loop_prevents_duplicate_actions():
    """Verify that repeated identical correction signatures immediately trigger blocked status."""
    dummy_state: CarveoutState = {
        "correction_attempts": 1,
        "correction_history": [
            {
                "attempt": 1,
                "action": "rerun_dependency_investigation",
                "signature": "rerun_dep_1",
                "status": "applied",
            }
        ],
    }

    correction = {
        "action": "rerun_dependency_investigation",
        "signature": "rerun_dep_1", # Duplicate signature
        "target_agent": "dependency_agent",
        "parameters": {},
    }

    res = execute_correction_action(dummy_state, correction)
    assert res.get("workflow_status") == "blocked"
    assert "Duplicate correction action" in res.get("errors", [""])[0]
    assert res["correction_history"][0]["status"] == "blocked_duplicate"


def test_approval_gate_invalid_payload_handling():
    """Verify approval gate handles unknown decisions safely by defaulting to REJECT."""
    from unittest.mock import patch

    dummy_state: CarveoutState = {
        "enable_human_interrupt": True,
        "evaluation_report": {"hard_violations": []},
        "critic_decision": {"decision": "APPROVE"},
        "optimization_results": {},
    }

    # Simulate interrupt returning an invalid arbitrary payload
    with patch("carveout.workflows.approval.interrupt", return_value={"action": "INVALID_RANDOM_ACTION", "comment": "test"}):
        res = check_approval_gate(dummy_state)
        assert res.get("approval_status") == "rejected"
        assert res.get("human_approval", {}).get("action") == "REJECT"


def test_portfolio_yaml_immutability():
    """Verify that the source portfolio YAML is untouched before and after workflow execution."""
    initial_hash = hashlib.sha256(PORTFOLIO.read_bytes()).hexdigest()

    dummy_state: CarveoutState = {
        "portfolio_path": str(PORTFOLIO),
        "rules_path": str(RULES),
        "constraints_path": str(CONSTRAINTS),
        "correction_attempts": 0,
        "correction_history": [],
    }

    correction = {
        "action": "rerun_optimization_with_params",
        "target_agent": "optimization_agent",
        "parameters": {"scenario_type": "minimize_cost", "max_waves": 8},
        "signature": "sig_opt_immutability",
    }

    execute_correction_action(dummy_state, correction)

    post_hash = hashlib.sha256(PORTFOLIO.read_bytes()).hexdigest()
    assert initial_hash == post_hash, "Source portfolio.yaml was modified during correction!"
