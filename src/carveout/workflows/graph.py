"""LangGraph StateGraph builder for Phase 3 Carve-out Copilot with evaluation, critic loop, and interrupt()."""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from carveout.agents.critic_agent import run_critic_agent
from carveout.agents.dependency_agent import run_dependency_agent
from carveout.agents.evaluation_agent import run_evaluation_agent
from carveout.agents.optimization_agent import run_optimization_agent
from carveout.agents.risk_agent import run_risk_agent
from carveout.agents.strategy_agent import run_strategy_agent
from carveout.agents.supervisor import run_supervisor, synthesize_final_response
from carveout.logging_config import set_workflow_context
from carveout.tools.correction_tools import execute_correction_action
from carveout.workflows.approval import check_approval_gate
from carveout.workflows.checkpointer import checkpoint_exists, get_checkpointer, get_default_db_path
from carveout.workflows.metrics import WorkflowExecutionMetrics
from carveout.workflows.routing import (
    route_after_approval,
    route_after_critic,
    route_after_dependency,
    route_after_risk,
    route_after_strategy,
    route_supervisor,
)
from carveout.workflows.state import CarveoutState

logger = logging.getLogger("carveout.workflow")
_DEFAULT_CHECKPOINTER = MemorySaver()


def _wrap_node(node_name: str, node_func: Callable[[CarveoutState], dict[str, Any]]) -> Callable[[CarveoutState], dict[str, Any]]:
    """Wrap workflow nodes with structured logging, timing telemetry, and safe error capture."""
    def wrapped(state: CarveoutState) -> dict[str, Any]:
        set_workflow_context(node_name=node_name)
        logger.info(f"Entering node: {node_name}")
        t0 = time.time()
        try:
            updates = node_func(state)
            duration = round(time.time() - t0, 3)
            logger.info(f"Node completed: {node_name} in {duration:.3f}s")
            timing_record = {"node_name": node_name, "duration_seconds": duration, "status": "success"}
            if isinstance(updates, dict):
                existing_timings = updates.get("node_timings", [])
                updates["node_timings"] = existing_timings + [timing_record]
            return updates
        except Exception as e:
            # Let LangGraph control-flow interrupts bubble up cleanly
            if type(e).__name__ == "GraphInterrupt" or "GraphInterrupt" in str(type(e)):
                raise
            duration = round(time.time() - t0, 3)
            logger.error(f"Node failed: {node_name} after {duration:.3f}s with error: {e}", exc_info=True)
            timing_record = {"node_name": node_name, "duration_seconds": duration, "status": "failed", "error": str(e)}
            return {
                "errors": [f"Failure in {node_name}: {e}"],
                "execution_trace": [f"{node_name}:failed"],
                "workflow_status": "failed",
                "node_timings": [timing_record],
            }
    wrapped.__name__ = f"wrapped_{node_name}"
    return wrapped


def run_correction_node(state: CarveoutState) -> dict[str, Any]:
    """Execute the pending bounded correction action."""
    pending = state.get("pending_correction", {})
    if not pending:
        logger.warning("Correction node invoked with empty pending_correction.")
        return {
            "errors": ["Correction node invoked with empty pending_correction."],
            "execution_trace": ["correction_node:empty"],
        }
    logger.info(f"Executing correction action: {pending.get('action')} (attempt {state.get('correction_attempts', 0) + 1})")
    return execute_correction_action(state, pending)


def build_carveout_graph(checkpointer: Any | None = None) -> Any:
    """Build and compile the LangGraph workflow with bounded critic loop and human interrupt()."""
    workflow = StateGraph(CarveoutState)

    # Nodes wrapped with observability and error capture
    workflow.add_node("supervisor_node", _wrap_node("supervisor_node", run_supervisor))
    workflow.add_node("dependency_node", _wrap_node("dependency_node", run_dependency_agent))
    workflow.add_node("strategy_node", _wrap_node("strategy_node", run_strategy_agent))
    workflow.add_node("risk_node", _wrap_node("risk_node", run_risk_agent))
    workflow.add_node("optimization_node", _wrap_node("optimization_node", run_optimization_agent))
    workflow.add_node("evaluation_node", _wrap_node("evaluation_node", run_evaluation_agent))
    workflow.add_node("critic_node", _wrap_node("critic_node", run_critic_agent))
    workflow.add_node("correction_node", _wrap_node("correction_node", run_correction_node))
    workflow.add_node("approval_node", _wrap_node("approval_node", check_approval_gate))
    workflow.add_node("synthesis_node", _wrap_node("synthesis_node", synthesize_final_response))

    # Entry
    workflow.add_edge(START, "supervisor_node")

    workflow.add_conditional_edges(
        "supervisor_node",
        route_supervisor,
        {
            "dependency_node": "dependency_node",
            "strategy_node": "strategy_node",
            "risk_node": "risk_node",
            "optimization_node": "optimization_node",
            "evaluation_node": "evaluation_node",
        },
    )

    workflow.add_conditional_edges(
        "dependency_node",
        route_after_dependency,
        {
            "strategy_node": "strategy_node",
            "risk_node": "risk_node",
            "optimization_node": "optimization_node",
            "evaluation_node": "evaluation_node",
        },
    )

    workflow.add_conditional_edges(
        "strategy_node",
        route_after_strategy,
        {
            "risk_node": "risk_node",
            "optimization_node": "optimization_node",
            "evaluation_node": "evaluation_node",
        },
    )

    workflow.add_conditional_edges(
        "risk_node",
        route_after_risk,
        {
            "optimization_node": "optimization_node",
            "evaluation_node": "evaluation_node",
        },
    )

    workflow.add_edge("optimization_node", "evaluation_node")
    workflow.add_edge("evaluation_node", "critic_node")

    workflow.add_conditional_edges(
        "critic_node",
        route_after_critic,
        {
            "correction_node": "correction_node",
            "approval_node": "approval_node",
            "synthesis_node": "synthesis_node",
        },
    )

    workflow.add_edge("correction_node", "evaluation_node")

    workflow.add_conditional_edges(
        "approval_node",
        route_after_approval,
        {
            "correction_node": "correction_node",
            "synthesis_node": "synthesis_node",
        },
    )

    workflow.add_edge("synthesis_node", END)

    cp = checkpointer if checkpointer is not None else _DEFAULT_CHECKPOINTER
    return workflow.compile(checkpointer=cp)


def run_agent_workflow(
    user_request: str,
    portfolio_path: str,
    rules_path: str,
    constraints_path: str,
    thread_id: str = "default-thread",
    human_review: bool = False,
    max_correction_attempts: int = 2,
    checkpointer: Any | None = None,
    db_path: str | None = None,
    in_memory: bool = False,
) -> dict[str, Any]:
    """Execute the compiled LangGraph workflow with checkpointing and metrics support."""
    set_workflow_context(thread_id=thread_id, workflow_status="running")
    logger.info(f"Starting workflow run for thread '{thread_id}' (human_review={human_review})")

    metrics = WorkflowExecutionMetrics(thread_id=thread_id)

    initial_state: CarveoutState = {
        "user_request": user_request,
        "portfolio_path": str(portfolio_path),
        "rules_path": str(rules_path),
        "constraints_path": str(constraints_path),
        "intent": "",
        "required_agents": [],
        "next_agent": "",
        "dependency_analysis": {},
        "risk_assessment": {},
        "strategy_recommendations": [],
        "optimization_results": {},
        "evaluation_results": {},
        "evaluation_report": {},
        "critic_decision": {},
        "correction_attempts": 0,
        "max_correction_attempts": max(0, min(3, int(max_correction_attempts))),
        "correction_history": [],
        "pending_correction": {},
        "human_review_required": False,
        "human_approval": {},
        "approval_history": [],
        "workflow_status": "running",
        "execution_trace": [],
        "enable_human_interrupt": human_review,
        "agent_messages": [],
        "tool_results": [],
        "approval_status": "pending",
        "errors": [],
        "final_response": "",
        "metrics": {},
        "node_timings": [],
    }

    config = {"configurable": {"thread_id": thread_id}}

    try:
        if checkpointer is not None:
            app = build_carveout_graph(checkpointer=checkpointer)
            result = app.invoke(initial_state, config=config)
        else:
            with get_checkpointer(db_path=db_path, in_memory=in_memory) as cp:
                app = build_carveout_graph(checkpointer=cp)
                result = app.invoke(initial_state, config=config)
    except Exception as exc:
        logger.error(f"Workflow invocation failed for thread '{thread_id}': {exc}", exc_info=True)
        metrics.finalize(workflow_status="failed")
        metrics.error = str(exc)
        return {
            "workflow_status": "failed",
            "errors": [f"Workflow execution failed: {exc}"],
            "metrics": metrics.model_dump(),
        }

    # Evaluate execution status
    if "__interrupt__" in result:
        logger.info(f"Workflow interrupted at approval node for thread '{thread_id}'")
        metrics.interruptions_count += 1
        metrics.finalize(workflow_status="interrupted")
        set_workflow_context(workflow_status="interrupted")
    else:
        status = result.get("workflow_status") or "completed"
        logger.info(f"Workflow completed for thread '{thread_id}' with status: {status}")
        metrics.finalize(workflow_status=status)
        set_workflow_context(workflow_status=status)

    metrics.evaluation_status = result.get("evaluation_report", {}).get("status")
    metrics.critic_decision = result.get("critic_decision", {}).get("decision")
    opt_res = result.get("optimization_results", {}).get("optimization_result", {})
    metrics.optimization_status = opt_res.get("status")
    metrics.correction_iterations = int(result.get("correction_attempts", 0))

    result["metrics"] = metrics.model_dump()
    return result


def resume_agent_workflow(
    thread_id: str,
    decision: dict[str, Any] | str,
    checkpointer: Any | None = None,
    db_path: str | None = None,
    in_memory: bool = False,
) -> dict[str, Any]:
    """Resume a paused workflow at the human_approval interrupt() using the same thread_id."""
    if not thread_id or not thread_id.strip():
        raise ValueError("Cannot resume workflow: A valid, non-empty thread_id is required.")

    set_workflow_context(thread_id=thread_id, workflow_status="resuming")
    logger.info(f"Resuming workflow for thread '{thread_id}'")

    config = {"configurable": {"thread_id": thread_id}}

    try:
        if checkpointer is not None:
            app = build_carveout_graph(checkpointer=checkpointer)
            result = app.invoke(Command(resume=decision), config=config)
        else:
            # Check existence first if persistent
            if not in_memory and not checkpoint_exists(thread_id, db_path=db_path):
                raise FileNotFoundError(
                    f"No existing checkpoint found for thread '{thread_id}'. "
                    "Cannot resume a non-existent or uncheckpointed workflow."
                )

            with get_checkpointer(db_path=db_path, in_memory=in_memory) as cp:
                app = build_carveout_graph(checkpointer=cp)
                result = app.invoke(Command(resume=decision), config=config)
    except Exception as exc:
        logger.error(f"Workflow resumption failed for thread '{thread_id}': {exc}", exc_info=True)
        raise

    if "__interrupt__" in result:
        logger.info(f"Workflow interrupted again for thread '{thread_id}'")
        set_workflow_context(workflow_status="interrupted")
    else:
        status = result.get("workflow_status") or "completed"
        logger.info(f"Resumed workflow finished for thread '{thread_id}' with status: {status}")
        set_workflow_context(workflow_status=status)

    return result


def get_workflow_state(
    thread_id: str,
    checkpointer: Any | None = None,
    db_path: str | None = None,
    in_memory: bool = False,
) -> Any:
    """Retrieve the latest checkpointed StateSnapshot for a given thread_id."""
    if not thread_id or not thread_id.strip():
        raise ValueError("Cannot inspect workflow: A valid, non-empty thread_id is required.")

    config = {"configurable": {"thread_id": thread_id}}

    if checkpointer is not None:
        app = build_carveout_graph(checkpointer=checkpointer)
        return app.get_state(config)

    with get_checkpointer(db_path=db_path, in_memory=in_memory) as cp:
        app = build_carveout_graph(checkpointer=cp)
        return app.get_state(config)
