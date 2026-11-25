"""Immutable scenario management, delay injection, and baseline comparisons."""
from __future__ import annotations

from pathlib import Path
from pydantic import BaseModel, Field

from carveout.loader import load_portfolio
from carveout.optimization.models import OptimizationConfig, OptimizationResult
from carveout.optimization.solver import solve_migration_schedule
from carveout.optimization.validation import validate_schedule_constraints
from carveout.strategy import assess_strategies


class ScenarioComparison(BaseModel):
    scenario_id: str
    scenario_name: str
    description: str
    baseline_completion: str
    scenario_completion: str
    baseline_tsa_cost: float
    scenario_tsa_cost: float
    additional_tsa_cost: float
    baseline_waves: int
    scenario_waves: int
    baseline_conflicts: int
    scenario_conflicts: int
    solver_status: str
    is_feasible: bool
    affected_assets: list[str] = Field(default_factory=list)
    tradeoff_summary: str = ""


def run_scenario(
    portfolio_path: str,
    rules_path: str,
    scenario_type: str = "baseline",
    delay_weeks: int = 12,
    objective: str = "minimize_cost",
    config: OptimizationConfig | None = None,
    constraints_path: str | Path | None = None,
) -> tuple[OptimizationResult, ScenarioComparison]:
    """
    Execute optimization for a specific scenario without mutating the original portfolio YAML.
    Scenarios:
      - 'baseline': optimal baseline CP-SAT schedule
      - 'app_06_delay': N-week delay on coupled APP-06 / APP-07 unit relative to baseline start
      - 'minimize_cost': rate-weighted TSA exit wave minimization
      - 'minimize_duration': lexicographic wave-span minimization
      - 'balanced': combined cost and duration objective
    """
    p = load_portfolio(portfolio_path)
    strategies = assess_strategies(p, rules_path)
    retained_assets = {s["asset_id"] for s in strategies if s.get("strategy") == "retain_under_tsa"}

    cfg = config or OptimizationConfig(objective=objective)

    # 1. Always compute true baseline CP-SAT schedule first for comparison
    baseline_res = solve_migration_schedule(
        p,
        strategies,
        OptimizationConfig(objective="minimize_cost"),
        "baseline",
        constraints_path=constraints_path,
    )
    baseline_starts = {aid: sched.planned_start for aid, sched in baseline_res.asset_schedules.items()}

    # 2. Run scenario
    delay_map: dict[str, int] = {}
    affected: list[str] = []
    desc = ""

    if scenario_type == "app_06_delay":
        # Coupled unit: APP-06 and APP-07 share an SCC
        delay_map = {"APP-06": delay_weeks, "APP-07": delay_weeks}
        affected = ["APP-06", "APP-07"]
        desc = f"{delay_weeks}-week cutover delay applied to coupled unit {affected} relative to baseline start."
        scenario_res = solve_migration_schedule(
            p,
            strategies,
            cfg,
            scenario_id=scenario_type,
            delay_assets=delay_map,
            baseline_asset_starts=baseline_starts,
            constraints_path=constraints_path,
        )
    else:
        cfg.objective = objective if scenario_type in ("minimize_cost", "minimize_duration", "balanced") else cfg.objective
        desc = f"Schedule optimization with objective '{cfg.objective}'."
        scenario_res = solve_migration_schedule(
            p,
            strategies,
            cfg,
            scenario_id=scenario_type,
            constraints_path=constraints_path,
        )

    # Independent validation against hard constraints
    val = validate_schedule_constraints(
        p,
        scenario_res,
        retained_assets,
        constraints_path=constraints_path,
        baseline_asset_starts=baseline_starts if delay_map else None,
        delay_assets=delay_map or None,
    )

    base_cost = baseline_res.estimated_tsa_cost_total
    scen_cost = scenario_res.estimated_tsa_cost_total
    delta_cost = round(scen_cost - base_cost, 2)

    summary_parts = [
        f"Scenario '{scenario_type}' solved with status {scenario_res.status} in {scenario_res.solve_duration_seconds:.2f}s.",
        f"TSA Cost: ${scen_cost:,.2f} vs Baseline ${base_cost:,.2f} (Delta: ${delta_cost:+,.2f}).",
        f"Completion: {scenario_res.latest_completion_date} vs Baseline {baseline_res.latest_completion_date}.",
        f"Waves: {scenario_res.total_waves} vs Baseline {baseline_res.total_waves}.",
        f"Conflicts: {len(scenario_res.conflicts)} detected.",
    ]
    if not val["valid"]:
        summary_parts.append(f"Constraint Violations: {', '.join(val['violations'])}")

    comparison = ScenarioComparison(
        scenario_id=scenario_type,
        scenario_name=scenario_type.replace("_", " ").title(),
        description=desc,
        baseline_completion=baseline_res.latest_completion_date,
        scenario_completion=scenario_res.latest_completion_date,
        baseline_tsa_cost=base_cost,
        scenario_tsa_cost=scen_cost,
        additional_tsa_cost=delta_cost,
        baseline_waves=baseline_res.total_waves,
        scenario_waves=scenario_res.total_waves,
        baseline_conflicts=len(baseline_res.conflicts),
        scenario_conflicts=len(scenario_res.conflicts),
        solver_status=scenario_res.status,
        is_feasible=val["valid"],
        affected_assets=affected,
        tradeoff_summary=" ".join(summary_parts),
    )

    return scenario_res, comparison
