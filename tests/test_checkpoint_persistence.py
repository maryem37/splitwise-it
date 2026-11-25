"""Tests for SQLite checkpoint persistence across workflow invocations."""
from __future__ import annotations

import sqlite3
import pytest
from pathlib import Path

from carveout.workflows.checkpointer import get_checkpointer, get_default_db_path
from carveout.workflows.graph import build_carveout_graph, get_workflow_state, resume_agent_workflow, run_agent_workflow

PORTFOLIO = Path("data/portfolio_v1.yaml")
RULES = Path("config/strategy_rules.yaml")
CONSTRAINTS = Path("config/constraints.yaml")


def test_sqlite_checkpointer_creation(tmp_path: Path):
    db_file = tmp_path / "test_cp.sqlite"
    with get_checkpointer(db_path=db_file) as cp:
        assert cp is not None
        app = build_carveout_graph(checkpointer=cp)
        assert app is not None

    assert db_file.exists()
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    # Check that checkpoints table was created
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cur.fetchall()]
    conn.close()
    assert "checkpoints" in tables


def test_sqlite_persistence_across_sessions(tmp_path: Path):
    """Test pausing via interrupt() and resuming using SQLite database."""
    db_file = tmp_path / "persist.sqlite"
    thread_id = "test-persist-session-1"

    # Run workflow with human review enabled to hit interrupt()
    res1 = run_agent_workflow(
        user_request="Investigate APP-06 delay and optimize",
        portfolio_path=str(PORTFOLIO),
        rules_path=str(RULES),
        constraints_path=str(CONSTRAINTS),
        thread_id=thread_id,
        human_review=True,
        db_path=str(db_file),
    )

    assert "__interrupt__" in res1
    assert db_file.exists()

    # Query snapshot from DB in a separate checkpointer session
    snapshot = get_workflow_state(thread_id=thread_id, db_path=str(db_file))
    assert snapshot is not None
    assert snapshot.values.get("workflow_status") in ("running", "ready_for_review", "pending", "human_review_required")
    assert "approval_node" in str(snapshot.next)

    # Resume workflow from checkpoint using new context
    res2 = resume_agent_workflow(
        thread_id=thread_id,
        decision={"action": "APPROVE", "reviewer": "qa_tester", "comment": "Approved persistence"},
        db_path=str(db_file),
    )

    assert "__interrupt__" not in res2
    assert res2.get("approval_status") == "approved"
    assert res2.get("workflow_status") == "approved"
    assert "Approved by qa_tester" in str(res2.get("agent_messages", []))
