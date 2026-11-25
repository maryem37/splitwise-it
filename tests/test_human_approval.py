"""Tests for Phase 3 real LangGraph interrupt(), checkpointing, and thread_id resume."""
from pathlib import Path
from langgraph.checkpoint.memory import MemorySaver

from carveout.workflows.graph import resume_agent_workflow, run_agent_workflow

ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = Path(ROOT / "data" / "portfolio_v1.yaml")
RULES = str(ROOT / "config" / "strategy_rules.yaml")
CONSTRAINTS = str(ROOT / "config" / "constraints.yaml")


def test_human_approval_interrupt_and_approve_resume():
    cp = MemorySaver()
    before_yaml = PORTFOLIO.read_text(encoding="utf-8")

    paused = run_agent_workflow(
        "What happens if we delay APP-06 by three months, and how can we minimize the additional TSA cost?",
        str(PORTFOLIO),
        RULES,
        CONSTRAINTS,
        thread_id="hitl-approve-1",
        human_review=True,
        checkpointer=cp,
    )
    assert "__interrupt__" in paused
    payload = paused["__interrupt__"][0].value
    assert payload["requested_action"] == "HUMAN_APPROVAL"
    assert "APPROVE" in payload["allowed_decisions"]

    resumed = resume_agent_workflow(
        "hitl-approve-1",
        {"action": "APPROVE", "reviewer": "alice", "comment": "Accepted."},
        checkpointer=cp,
    )
    assert "__interrupt__" not in resumed
    assert resumed["approval_status"] == "approved"
    assert resumed["human_approval"]["reviewer"] == "alice"
    assert resumed["final_response"]
    assert PORTFOLIO.read_text(encoding="utf-8") == before_yaml


def test_human_approval_reject_terminates_safely():
    cp = MemorySaver()
    paused = run_agent_workflow(
        "Optimize schedule to minimize cost",
        str(PORTFOLIO),
        RULES,
        CONSTRAINTS,
        thread_id="hitl-reject-1",
        human_review=True,
        checkpointer=cp,
    )
    assert "__interrupt__" in paused

    resumed = resume_agent_workflow(
        "hitl-reject-1",
        {"action": "REJECT", "reviewer": "bob", "comment": "Too much TSA cost"},
        checkpointer=cp,
    )
    assert resumed["approval_status"] == "rejected"
    assert resumed["workflow_status"] == "rejected"
    assert resumed["human_approval"]["action"] == "REJECT"


def test_human_approval_request_revision_loops_within_bound():
    cp = MemorySaver()
    paused = run_agent_workflow(
        "Optimize schedule to minimize cost",
        str(PORTFOLIO),
        RULES,
        CONSTRAINTS,
        thread_id="hitl-rev-1",
        human_review=True,
        max_correction_attempts=2,
        checkpointer=cp,
    )
    assert "__interrupt__" in paused

    # Request revision -> executes correction_node -> re-evaluates -> pauses again for approval
    paused_again = resume_agent_workflow(
        "hitl-rev-1",
        {"action": "REQUEST_REVISION", "reviewer": "carol", "comment": "Try balanced"},
        checkpointer=cp,
    )
    assert paused_again["correction_attempts"] == 1
    assert "__interrupt__" in paused_again

    final = resume_agent_workflow(
        "hitl-rev-1",
        {"action": "APPROVE", "reviewer": "carol"},
        checkpointer=cp,
    )
    assert final["approval_status"] == "approved"
    assert len(final["approval_history"]) == 2
