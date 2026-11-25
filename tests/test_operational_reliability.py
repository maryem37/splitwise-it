"""Tests for Phase 3.2 checkpoint operational resilience and error handling."""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path
import pytest

from carveout.workflows.checkpointer import checkpoint_exists, get_checkpointer, validate_db_path
from carveout.workflows.graph import get_workflow_state, resume_agent_workflow, run_agent_workflow

PORTFOLIO = Path("data/portfolio_v1.yaml")
RULES = Path("config/strategy_rules.yaml")
CONSTRAINTS = Path("config/constraints.yaml")


def test_validate_db_path_rejects_directory(tmp_path: Path):
    test_dir = tmp_path / "some_dir"
    test_dir.mkdir()
    with pytest.raises(ValueError, match="Cannot initialize checkpoint storage"):
        validate_db_path(test_dir)


def test_connection_cleanup_and_wal_mode(tmp_path: Path):
    db_file = tmp_path / "wal_test.sqlite"
    with get_checkpointer(db_path=db_file) as saver:
        assert saver is not None

    assert db_file.exists()
    with sqlite3.connect(str(db_file)) as conn:
        journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert journal_mode.lower() == "wal"


def test_resume_non_existent_thread_raises_error(tmp_path: Path):
    db_file = tmp_path / "empty_db.sqlite"
    # Ensure file exists with schema
    with get_checkpointer(db_path=db_file) as saver:
        pass

    assert not checkpoint_exists("non_existent_thread_xyz", db_path=db_file)

    with pytest.raises(FileNotFoundError, match="No existing checkpoint found"):
        resume_agent_workflow(
            thread_id="non_existent_thread_xyz",
            decision={"action": "APPROVE"},
            db_path=str(db_file),
        )


def test_empty_thread_id_validation():
    with pytest.raises(ValueError, match="A valid, non-empty thread_id is required"):
        get_workflow_state(thread_id="")

    with pytest.raises(ValueError, match="A valid, non-empty thread_id is required"):
        resume_agent_workflow(thread_id="   ", decision={"action": "APPROVE"})


def test_cli_error_handling_missing_checkpoint(tmp_path: Path):
    db_file = tmp_path / "cli_test.sqlite"
    with get_checkpointer(db_path=db_file) as saver:
        pass

    # Status on non-existent thread returns exit code 1
    proc_status = subprocess.run(
        [
            sys.executable,
            "-m", "carveout.cli",
            "agent-status",
            "--thread-id", "missing-id-123",
            "--db-path", str(db_file),
        ],
        capture_output=True,
        text=True,
    )
    assert proc_status.returncode == 1
    assert "No checkpoint found for thread ID: missing-id-123" in proc_status.stdout

    # Resume on non-existent thread returns exit code 1 with explicit error
    proc_resume = subprocess.run(
        [
            sys.executable,
            "-m", "carveout.cli",
            "agent-resume",
            "--thread-id", "missing-id-123",
            "--action", "APPROVE",
            "--db-path", str(db_file),
        ],
        capture_output=True,
        text=True,
    )
    assert proc_resume.returncode == 1
    assert "No existing checkpoint found" in proc_resume.stderr


def test_cli_invalid_action_rejected(tmp_path: Path):
    proc = subprocess.run(
        [
            sys.executable,
            "-m", "carveout.cli",
            "agent-resume",
            "--thread-id", "any-thread",
            "--action", "SUPER_APPROVE_INVALID",
        ],
        capture_output=True,
        text=True,
    )
    # argparse returns code 2 for invalid choice
    assert proc.returncode == 2
