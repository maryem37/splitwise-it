"""Pydantic request and response schemas for the Carve-out Copilot REST API."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "carveout-copilot-api"
    version: str = "0.1.0"


class PortfolioSummaryItem(BaseModel):
    portfolio_id: str
    company: str
    description: str
    asset_count: int
    tsa_count: int


class WorkflowLaunchRequest(BaseModel):
    user_request: str = Field(..., min_length=3, max_length=2000)
    portfolio_id: str = Field(default="portfolio_v1", max_length=64)
    thread_id: str | None = Field(default=None, max_length=128)
    human_review: bool = False
    max_correction_attempts: int = Field(default=2, ge=0, le=3)


class WorkflowLaunchResponse(BaseModel):
    thread_id: str
    workflow_status: str
    approval_status: str
    interrupted: bool
    evaluation_status: str | None = None
    critic_decision: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    final_response: str = ""
    errors: list[str] = Field(default_factory=list)


class WorkflowStatusResponse(BaseModel):
    thread_id: str
    workflow_status: str
    approval_status: str
    interrupted: bool
    next_nodes: list[str] = Field(default_factory=list)
    evaluation_status: str | None = None
    critic_decision: str | None = None
    correction_attempts: int = 0
    max_correction_attempts: int = 2
    metrics: dict[str, Any] = Field(default_factory=dict)
    interrupt_payload: dict[str, Any] | None = None


class WorkflowResumeRequest(BaseModel):
    action: Literal["APPROVE", "REJECT", "REQUEST_REVISION"]
    reviewer: str = Field(default="api_reviewer", min_length=1, max_length=128)
    comment: str = Field(default="", max_length=1000)


class ScenarioRunRequest(BaseModel):
    portfolio_id: str = Field(default="portfolio_v1", max_length=64)
    scenario_id: str = Field(default="custom_whatif", max_length=64)
    scenario_name: str = Field(default="Custom What-If Scenario", max_length=128)
    description: str = Field(default="API what-if scenario", max_length=500)
    delay_weeks: dict[str, int] = Field(default_factory=dict)
    tsa_rate_multiplier: float = Field(default=1.0, gt=0.0, le=10.0)
    objective: Literal["minimize_cost", "minimize_duration", "balanced"] = "minimize_cost"
    max_waves: int = Field(default=12, ge=1, le=20)
