"""Tests for Phase 3.2 structured logging, context propagation, and execution metrics."""
from __future__ import annotations

import json
import logging
from pathlib import Path
import pytest

from carveout.logging_config import (
    JsonFormatter,
    clear_workflow_context,
    configure_logging,
    get_workflow_context,
    set_workflow_context,
)
from carveout.workflows.graph import run_agent_workflow
from carveout.workflows.metrics import WorkflowExecutionMetrics

PORTFOLIO = Path("data/portfolio_v1.yaml")
RULES = Path("config/strategy_rules.yaml")
CONSTRAINTS = Path("config/constraints.yaml")


def test_workflow_context_and_json_formatter():
    clear_workflow_context()
    assert get_workflow_context()["thread_id"] == ""

    set_workflow_context(thread_id="test-thread-obs", node_name="risk_node", workflow_status="running")
    ctx = get_workflow_context()
    assert ctx["thread_id"] == "test-thread-obs"
    assert ctx["node_name"] == "risk_node"

    # Test JSON formatter output
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="carveout.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Test structured log message",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)
    parsed = json.loads(formatted)
    assert parsed["message"] == "Test structured log message"
    assert parsed["thread_id"] == "test-thread-obs"
    assert parsed["node_name"] == "risk_node"
    assert parsed["level"] == "INFO"

    clear_workflow_context()


def test_workflow_metrics_model_lifecycle():
    metrics = WorkflowExecutionMetrics(thread_id="thread-metrics-1")
    assert metrics.thread_id == "thread-metrics-1"
    assert metrics.workflow_status == "initialized"

    metrics.record_node("dependency_node", 0.125, status="success")
    metrics.record_node("risk_node", 0.085, status="success")
    metrics.finalize(workflow_status="completed")

    assert metrics.total_duration_seconds >= 0.0
    assert len(metrics.agent_timings) == 2
    assert metrics.agent_timings[0].node_name == "dependency_node"
    assert metrics.agent_timings[0].duration_seconds == 0.125
    assert metrics.workflow_status == "completed"


def test_workflow_execution_captures_metrics_and_timings(tmp_path: Path):
    db_file = tmp_path / "obs_test.sqlite"
    res = run_agent_workflow(
        user_request="Investigate dependencies and TSA risks",
        portfolio_path=str(PORTFOLIO),
        rules_path=str(RULES),
        constraints_path=str(CONSTRAINTS),
        thread_id="obs-exec-thread",
        human_review=False,
        db_path=str(db_file),
    )

    assert "metrics" in res
    metrics = res["metrics"]
    assert metrics["thread_id"] == "obs-exec-thread"
    assert metrics["total_duration_seconds"] > 0
    assert "node_timings" in res
    assert len(res["node_timings"]) >= 4  # supervisor, dependency, risk, evaluation, critic, synthesis
    node_names = [t["node_name"] for t in res["node_timings"]]
    assert "dependency_node" in node_names
    assert "risk_node" in node_names
