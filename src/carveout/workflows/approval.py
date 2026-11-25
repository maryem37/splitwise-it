"""Human-in-the-loop approval gate."""
from __future__ import annotations

from typing import Any
from carveout.workflows.state import CarveoutState


def check_approval_gate(state: CarveoutState) -> dict[str, Any]:
    """Human-in-the-loop gate before persisting any plan or modifying files."""
    status = state.get("approval_status", "pending")
    return {
        "approval_status": status,
        "agent_messages": [{
            "agent": "ApprovalGate",
            "content": f"Human approval status: {status}.",
        }],
    }
