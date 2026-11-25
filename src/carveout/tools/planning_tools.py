"""Deterministic planning and wave execution tools."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from carveout.loader import load_portfolio, validate_portfolio
from carveout.metrics import calculate_metrics
from carveout.models import Portfolio
from carveout.sequencing import compute_waves
from carveout.strategy import assess_strategies


def validate_portfolio_data(portfolio_path: str | Path) -> dict[str, Any]:
    """Validate portfolio integrity, schemas, IDs, and dangling links."""
    p = load_portfolio(portfolio_path)
    return validate_portfolio(p)


def compute_baseline_plan(
    portfolio_path: str | Path,
    rules_path: str | Path,
    constraints_path: str | Path,
) -> dict[str, Any]:
    """Compute the deterministic baseline migration plan (waves, metrics, conflicts)."""
    p = load_portfolio(portfolio_path)
    strategies = assess_strategies(p, rules_path)
    sequencing = compute_waves(p, constraints_path, strategies=strategies)
    metrics = calculate_metrics(p, sequencing)

    return {
        "strategies": strategies,
        "waves": sequencing["waves"],
        "cycles": sequencing["cycles"],
        "conflicts": sequencing["conflicts"],
        "metrics": metrics,
    }


def get_asset_schedule(
    portfolio_path: str | Path,
    rules_path: str | Path,
    constraints_path: str | Path,
    asset_id: str,
) -> dict[str, Any]:
    """Find planned wave and cutover completion date for a specific asset."""
    plan = compute_baseline_plan(portfolio_path, rules_path, constraints_path)
    for wave in plan["waves"]:
        if asset_id in wave["assets"]:
            return {
                "asset_id": asset_id,
                "wave": wave["wave"],
                "planned_start": wave["planned_start"],
                "planned_completion": wave["asset_completion_dates"].get(asset_id, wave["planned_completion"]),
                "wave_depends_on": wave["depends_on_waves"],
            }
    raise KeyError(f"Asset {asset_id} not scheduled in any wave.")
