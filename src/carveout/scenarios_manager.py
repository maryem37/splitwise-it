"""Reproducible what-if scenario execution without modifying original portfolio YAML."""
from __future__ import annotations

import copy
import yaml
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field

from carveout.loader import load_portfolio
from carveout.models import Portfolio, Asset
from carveout.optimization.models import OptimizationConfig, OptimizationResult
from carveout.optimization.solver import solve_migration_schedule
from carveout.optimization.validation import validate_schedule_constraints
from carveout.strategy import assess_strategies


class WhatIfScenarioConfig(BaseModel):
    """Specification of an isolated what-if scenario."""
    scenario_id: str
    scenario_name: str
    description: str
    delay_weeks: dict[str, int] = Field(default_factory=dict)
    tsa_rate_multiplier: float = 1.0
    objective: str = "minimize_cost"
    max_waves: int = 12


class WhatIfScenarioResult(BaseModel):
    scenario_id: str
    scenario_name: str
    baseline_tsa_cost: float
    scenario_tsa_cost: float
    tsa_cost_delta: float
    baseline_completion: str
    scenario_completion: str
    total_waves: int
    solver_status: str
    is_feasible: bool
    affected_assets: list[str] = Field(default_factory=list)
    impact_summary: str
    assumptions: list[str] = Field(default_factory=list)


def run_what_if_scenario(
    portfolio_or_path: str | Path | Portfolio,
    scenario_cfg: WhatIfScenarioConfig | dict[str, Any],
    rules_path: str | Path = "config/strategy_rules.yaml",
    constraints_path: str | Path = "config/constraints.yaml",
) -> WhatIfScenarioResult:
    """
    Execute a what-if scenario in complete memory isolation, guaranteeing that original YAMLs are untouched.
    """
    cfg = scenario_cfg if isinstance(scenario_cfg, WhatIfScenarioConfig) else WhatIfScenarioConfig.model_validate(scenario_cfg)

    # Deepcopy portfolio to guarantee immutability
    base_p = portfolio_or_path if isinstance(portfolio_or_path, Portfolio) else load_portfolio(portfolio_or_path)
    isolated_portfolio = copy.deepcopy(base_p)

    # Apply scenario adjustments to isolated copy if requested (e.g. rate changes)
    if cfg.tsa_rate_multiplier != 1.0:
        for t in isolated_portfolio.tsa_services:
            t.monthly_cost = round(t.monthly_cost * cfg.tsa_rate_multiplier, 2)

    strategies = assess_strategies(isolated_portfolio, rules_path)
    retained_assets = {s["asset_id"] for s in strategies if s.get("strategy") == "retain_under_tsa"}

    # Compute baseline
    base_res = solve_migration_schedule(
        isolated_portfolio,
        strategies,
        OptimizationConfig(objective="minimize_cost", max_waves=cfg.max_waves),
        "baseline",
        constraints_path=constraints_path,
    )
    base_starts = {aid: s.planned_start for aid, s in base_res.asset_schedules.items()}

    # Compute scenario
    scen_opt_cfg = OptimizationConfig(objective=cfg.objective, max_waves=cfg.max_waves)
    scen_res = solve_migration_schedule(
        isolated_portfolio,
        strategies,
        scen_opt_cfg,
        scenario_id=cfg.scenario_id,
        delay_assets=cfg.delay_weeks or None,
        baseline_asset_starts=base_starts if cfg.delay_weeks else None,
        constraints_path=constraints_path,
    )

    validation = validate_schedule_constraints(
        isolated_portfolio,
        scen_res,
        retained_assets,
        constraints_path=constraints_path,
        baseline_asset_starts=base_starts if cfg.delay_weeks else None,
        delay_assets=cfg.delay_weeks or None,
    )

    base_cost = base_res.estimated_tsa_cost_total
    scen_cost = scen_res.estimated_tsa_cost_total
    delta_cost = round(scen_cost - base_cost, 2)

    affected = list(cfg.delay_weeks.keys())
    impact = (
        f"Scenario '{cfg.scenario_name}' completed with status {scen_res.status}. "
        f"TSA Cost: ${scen_cost:,.2f} (Delta: ${delta_cost:+,.2f}). "
        f"Completion: {scen_res.latest_completion_date} (Baseline: {base_res.latest_completion_date}). "
        f"Total Waves: {scen_res.total_waves}."
    )

    assumptions = [
        "Original portfolio YAML configuration was preserved without in-place mutation.",
        f"Objective: {cfg.objective} with max waves limit {cfg.max_waves}.",
    ]
    if cfg.tsa_rate_multiplier != 1.0:
        assumptions.append(f"TSA rates scaled by factor of {cfg.tsa_rate_multiplier:.2f}x.")

    return WhatIfScenarioResult(
        scenario_id=cfg.scenario_id,
        scenario_name=cfg.scenario_name,
        baseline_tsa_cost=base_cost,
        scenario_tsa_cost=scen_cost,
        tsa_cost_delta=delta_cost,
        baseline_completion=base_res.latest_completion_date,
        scenario_completion=scen_res.latest_completion_date,
        total_waves=scen_res.total_waves,
        solver_status=scen_res.status,
        is_feasible=validation["valid"],
        affected_assets=affected,
        impact_summary=impact,
        assumptions=assumptions,
    )
