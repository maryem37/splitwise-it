"""Tool wrappers for CP-SAT optimization engine and scenario comparison."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from carveout.optimization.scenarios import run_scenario


def optimize_migration_schedule(
    portfolio_path: str,
    rules_path: str,
    objective: str = "minimize_cost",
    max_solve_time: float = 10.0,
    constraints_path: str | Path | None = None,
) -> dict[str, Any]:
    """Execute CP-SAT optimization on the portfolio and return structured schedule results."""
    from carveout.optimization.models import OptimizationConfig

    cfg = OptimizationConfig(objective=objective, max_solve_time_seconds=max_solve_time)
    res, comp = run_scenario(
        portfolio_path,
        rules_path,
        scenario_type=objective,
        objective=objective,
        config=cfg,
        constraints_path=constraints_path,
    )
    return {
        "optimization_result": res.model_dump(),
        "comparison": comp.model_dump(),
    }


def compare_migration_scenarios(
    portfolio_path: str,
    rules_path: str,
    scenario_type: str = "app_06_delay",
    delay_weeks: int = 12,
    constraints_path: str | Path | None = None,
) -> dict[str, Any]:
    """Simulate an isolated what-if scenario (e.g. 12-week delay on APP-06) and compare to baseline."""
    res, comp = run_scenario(
        portfolio_path,
        rules_path,
        scenario_type=scenario_type,
        delay_weeks=delay_weeks,
        constraints_path=constraints_path,
    )
    return {
        "optimization_result": res.model_dump(),
        "comparison": comp.model_dump(),
    }
