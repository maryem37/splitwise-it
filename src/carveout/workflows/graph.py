"""LangGraph StateGraph builder for Carve-out Copilot with full Phase 2 agent coordination."""
from __future__ import annotations

from typing import Any
from langgraph.graph import StateGraph, START, END

from carveout.agents.dependency_agent import run_dependency_agent
from carveout.agents.optimization_agent import run_optimization_agent
from carveout.agents.risk_agent import run_risk_agent
from carveout.agents.strategy_agent import run_strategy_agent
from carveout.agents.supervisor import run_supervisor, synthesize_final_response
from carveout.workflows.approval import check_approval_gate
from carveout.workflows.routing import (
    route_after_dependency,
    route_after_risk,
    route_after_strategy,
    route_supervisor,
)
from carveout.workflows.state import CarveoutState


def build_carveout_graph() -> StateGraph:
    """Build and compile the multi-agent LangGraph workflow."""
    workflow = StateGraph(CarveoutState)

    # Register Nodes
    workflow.add_node("supervisor_node", run_supervisor)
    workflow.add_node("dependency_node", run_dependency_agent)
    workflow.add_node("strategy_node", run_strategy_agent)
    workflow.add_node("risk_node", run_risk_agent)
    workflow.add_node("optimization_node", run_optimization_agent)
    workflow.add_node("synthesis_node", synthesize_final_response)
    workflow.add_node("approval_node", check_approval_gate)

    # START -> Supervisor
    workflow.add_edge(START, "supervisor_node")

    # Conditional Routing from Supervisor
    workflow.add_conditional_edges(
        "supervisor_node",
        route_supervisor,
        {
            "dependency_node": "dependency_node",
            "strategy_node": "strategy_node",
            "risk_node": "risk_node",
            "optimization_node": "optimization_node",
            "synthesis_node": "synthesis_node",
        },
    )

    # Conditional Routing from Dependency Agent
    workflow.add_conditional_edges(
        "dependency_node",
        route_after_dependency,
        {
            "strategy_node": "strategy_node",
            "risk_node": "risk_node",
            "optimization_node": "optimization_node",
            "synthesis_node": "synthesis_node",
        },
    )

    # Conditional Routing from Strategy Agent
    workflow.add_conditional_edges(
        "strategy_node",
        route_after_strategy,
        {
            "risk_node": "risk_node",
            "optimization_node": "optimization_node",
            "synthesis_node": "synthesis_node",
        },
    )

    # Conditional Routing from Risk Agent
    workflow.add_conditional_edges(
        "risk_node",
        route_after_risk,
        {
            "optimization_node": "optimization_node",
            "synthesis_node": "synthesis_node",
        },
    )

    # Optimization Agent -> Synthesis -> Approval Gate -> END
    workflow.add_edge("optimization_node", "synthesis_node")
    workflow.add_edge("synthesis_node", "approval_node")
    workflow.add_edge("approval_node", END)

    return workflow.compile()


def run_agent_workflow(
    user_request: str,
    portfolio_path: str,
    rules_path: str,
    constraints_path: str,
) -> dict[str, Any]:
    """Execute the compiled LangGraph workflow synchronously."""
    app = build_carveout_graph()

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
        "agent_messages": [],
        "tool_results": [],
        "approval_status": "pending",
        "errors": [],
        "final_response": "",
    }

    return app.invoke(initial_state)
