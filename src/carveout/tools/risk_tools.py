"""Deterministic risk tools wrapping conflict detection and risk registers."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from carveout.generation.documents import build_risk_register
from carveout.loader import load_portfolio
from carveout.metrics import calculate_metrics
from carveout.sequencing import compute_waves
from carveout.strategy import assess_strategies


def detect_schedule_conflicts(
    portfolio_path: str | Path,
    rules_path: str | Path,
    constraints_path: str | Path,
) -> list[dict[str, Any]]:
    """Detect TSA overruns, licence expirations, cycle capacity, and target TSA exit violations."""
    p = load_portfolio(portfolio_path)
    strategies = assess_strategies(p, rules_path)
    sequencing = compute_waves(p, constraints_path, strategies=strategies)
    return sequencing.get("conflicts", [])


def generate_risk_register_data(
    portfolio_path: str | Path,
    rules_path: str | Path,
    constraints_path: str | Path,
) -> list[dict[str, Any]]:
    """Compute the deterministic risk register including conflict-driven, near-miss, and structural risks."""
    p = load_portfolio(portfolio_path)
    strategies = assess_strategies(p, rules_path)
    sequencing = compute_waves(p, constraints_path, strategies=strategies)
    return build_risk_register(p, sequencing)


def calculate_tsa_costs(
    portfolio_path: str | Path,
    rules_path: str | Path,
    constraints_path: str | Path,
) -> dict[str, Any]:
    """Calculate deterministic TSA duration (months) and costs per service."""
    p = load_portfolio(portfolio_path)
    strategies = assess_strategies(p, rules_path)
    sequencing = compute_waves(p, constraints_path, strategies=strategies)
    metrics = calculate_metrics(p, sequencing)
    return {
        "tsa_months_needed": metrics["tsa_months_needed"],
        "estimated_tsa_cost": metrics["estimated_tsa_cost"],
        "estimated_tsa_cost_total": metrics["estimated_tsa_cost_total"],
        "latest_planned_completion": metrics["latest_planned_completion"],
    }
