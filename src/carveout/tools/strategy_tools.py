"""Deterministic strategy tool wrappers calling carveout.strategy.assess_strategies."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from carveout.loader import load_portfolio
from carveout.models import Portfolio
from carveout.strategy import assess_strategies


def get_all_strategy_assessments(
    portfolio_or_path: Portfolio | str | Path,
    rules_path: str | Path,
) -> list[dict[str, Any]]:
    """Return the complete deterministic strategy decisions for all assets in the portfolio."""
    p = portfolio_or_path if isinstance(portfolio_or_path, Portfolio) else load_portfolio(portfolio_or_path)
    return assess_strategies(p, rules_path)


def get_asset_strategy_assessment(
    portfolio_or_path: Portfolio | str | Path,
    rules_path: str | Path,
    asset_id: str,
) -> dict[str, Any]:
    """Return deterministic strategy evaluation, confidence, matching rule, and reason for an asset."""
    assessments = get_all_strategy_assessments(portfolio_or_path, rules_path)
    for dec in assessments:
        if dec["asset_id"] == asset_id:
            return dec
    raise KeyError(f"Asset id {asset_id} not found in strategy assessments.")


def compare_asset_strategy_options(
    portfolio_or_path: Portfolio | str | Path,
    rules_path: str | Path,
    asset_id: str,
) -> dict[str, Any]:
    """
    Compare current deterministic strategy assignment with available portfolio-level strategies.
    Note: The existing strategy rule engine is deterministic (first-match wins). Any alternatives
    must be represented as explicit proposals subject to approval and constraints.
    """
    p = portfolio_or_path if isinstance(portfolio_or_path, Portfolio) else load_portfolio(portfolio_or_path)
    asset = next((a for a in p.assets if a.id == asset_id), None)
    if not asset:
        raise KeyError(f"Asset id {asset_id} not found in portfolio.")

    current = get_asset_strategy_assessment(p, rules_path, asset_id)

    # Standard candidate strategies
    candidate_strategies = ["clone", "migrate", "rebuild", "retire", "retain_under_tsa"]
    implications: dict[str, str] = {
        "clone": "Creates a distinct replica in the target environment; requires target infrastructure ready.",
        "migrate": "Moves application and data to target environment during planned cutover window.",
        "rebuild": "Constructs new target solution from scratch; incurs build_effort_weeks prior to cutover.",
        "retire": "Decommissions legacy system without replacement or data transfer to carved-out entity.",
        "retain_under_tsa": "Keeps asset hosted by Parent under TSA until cutover completes; incurs monthly TSA fee.",
    }

    return {
        "asset_id": asset_id,
        "name": asset.name,
        "owner": asset.owner.value,
        "criticality": asset.criticality,
        "current_strategy": current["strategy"],
        "exit_strategy": current.get("exit_strategy"),
        "rule_matched": current.get("rule"),
        "confidence": current.get("confidence"),
        "reason": current.get("reason", []),
        "available_strategies": candidate_strategies,
        "strategy_implications": implications,
    }
