"""Data models for OR-Tools CP-SAT carve-out migration schedule optimization."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class OptimizationConfig(BaseModel):
    max_solve_time_seconds: float = 10.0
    num_search_workers: int = 1
    random_seed: int = 42
    max_waves: int = 12
    max_assets_per_wave: int = 8
    gap_weeks: int = 2
    objective: str = "minimize_cost"  # "minimize_cost" | "minimize_duration" | "balanced"


class ConstraintViolation(BaseModel):
    constraint_name: str
    entity: str
    expected: str
    actual: str
    severity: Literal["hard", "warning", "existing_conflict"] = "hard"
    explanation: str


class AssetScheduleResult(BaseModel):
    asset_id: str
    name: str
    wave: int
    start_week: int
    completion_week: int
    planned_start: str
    planned_completion: str
    strategy: str


class OptimizationResult(BaseModel):
    status: str  # "OPTIMAL" | "FEASIBLE" | "INFEASIBLE" | "MODEL_INVALID" | "UNKNOWN"
    objective_name: str = "minimize_cost"
    objective_description: str = ""
    objective_value: float | None = None
    best_bound: float | None = None
    solve_duration_seconds: float = 0.0
    total_waves: int = 0
    latest_completion_date: str = ""
    estimated_tsa_cost_total: float = 0.0
    tsa_cost_by_service: dict[str, float] = Field(default_factory=dict)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    asset_schedules: dict[str, AssetScheduleResult] = Field(default_factory=dict)
    waves: list[dict[str, Any]] = Field(default_factory=list)
    scenario_id: str = "baseline"
    explanation: str = ""
