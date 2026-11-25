"""Tests for cross-process workflow resumption using CLI commands."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
import pytest

PORTFOLIO = Path("data/portfolio_v1.yaml")
RULES = Path("config/strategy_rules.yaml")
CONSTRAINTS = Path("config/constraints.yaml")


def test_cross_process_workflow_resume(tmp_path: Path):
    """
    Process A: Runs carveout agent with --human-review and SQLite db, stops at interrupt.
    Process B: Checks carveout agent-status, inspects waiting state.
    Process C: Runs carveout agent-resume with APPROVE decision, executes to completion.
    """
    db_file = tmp_path / "cross_process.sqlite"
    thread_id = "cp-thread-99"

    # Process A: Start workflow via python script simulating Process A exit at interrupt
    script_process_a = f"""
import sys
from carveout.workflows.graph import run_agent_workflow

res = run_agent_workflow(
    user_request="Investigate dependencies and TSA risks",
    portfolio_path=r"{PORTFOLIO}",
    rules_path=r"{RULES}",
    constraints_path=r"{CONSTRAINTS}",
    thread_id="{thread_id}",
    human_review=True,
    db_path=r"{db_file}",
)
if "__interrupt__" in res:
    sys.exit(42) # Custom exit code indicating paused at interrupt
sys.exit(0)
"""
    proc_a = subprocess.run(
        [sys.executable, "-c", script_process_a],
        capture_output=True,
        text=True,
    )
    assert proc_a.returncode == 42, f"Expected interrupt exit 42, got {proc_a.returncode}: {proc_a.stderr}"
    assert db_file.exists()

    # Process B: Inspect status via CLI subcommand
    proc_b = subprocess.run(
        [
            sys.executable,
            "-m", "carveout.cli",
            "agent-status",
            "--thread-id", thread_id,
            "--db-path", str(db_file),
        ],
        capture_output=True,
        text=True,
    )
    assert proc_b.returncode == 0, f"agent-status failed: {proc_b.stderr}"
    assert f"CARVEOUT COPILOT WORKFLOW STATUS: {thread_id}" in proc_b.stdout
    assert "Interrupted     : True" in proc_b.stdout

    # Process C: Resume via CLI subcommand in completely independent process
    proc_c = subprocess.run(
        [
            sys.executable,
            "-m", "carveout.cli",
            "agent-resume",
            "--thread-id", thread_id,
            "--action", "APPROVE",
            "--reviewer", "external_operator",
            "--comment", "Approved in separate process",
            "--db-path", str(db_file),
        ],
        capture_output=True,
        text=True,
    )
    assert proc_c.returncode == 0, f"agent-resume failed: {proc_c.stderr}"
    assert "Approval status: approved" in proc_c.stdout
    assert "Workflow status: approved" in proc_c.stdout

    # Verify status in DB is now finished/approved
    proc_d = subprocess.run(
        [
            sys.executable,
            "-m", "carveout.cli",
            "agent-status",
            "--thread-id", thread_id,
            "--db-path", str(db_file),
        ],
        capture_output=True,
        text=True,
    )
    assert proc_d.returncode == 0
    assert "Approval Status : approved" in proc_d.stdout
    assert "Interrupted     : False" in proc_d.stdout
