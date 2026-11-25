"""Workflow execution metrics tracking per-thread execution durations and outcomes."""
from __future__ import annotations

import time
from typing import Any
from pydantic import BaseModel, Field


class AgentTiming(BaseModel):
    node_name: str
    duration_seconds: float = 0.0
    status: str = "success"
    error: str | None = None


class WorkflowExecutionMetrics(BaseModel):
    """Execution telemetry captured during a workflow run or resumption."""
    thread_id: str
    start_time: float = Field(default_factory=time.time)
    end_time: float = 0.0
    total_duration_seconds: float = 0.0
    agent_timings: list[AgentTiming] = Field(default_factory=list)
    correction_iterations: int = 0
    interruptions_count: int = 0
    resumptions_count: int = 0
    evaluation_status: str | None = None
    critic_decision: str | None = None
    optimization_status: str | None = None
    workflow_status: str = "initialized"
    error: str | None = None

    def record_node(self, node_name: str, duration: float, status: str = "success", error: str | None = None) -> None:
        self.agent_timings.append(AgentTiming(
            node_name=node_name,
            duration_seconds=round(duration, 3),
            status=status,
            error=error,
        ))

    def finalize(self, workflow_status: str | None = None) -> None:
        if self.end_time == 0.0:
            self.end_time = time.time()
        self.total_duration_seconds = round(self.end_time - self.start_time, 3)
        if workflow_status:
            self.workflow_status = workflow_status
