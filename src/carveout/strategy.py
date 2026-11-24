"""Explainable, ordered strategy rule engine."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import Portfolio


def _matches(rule: dict[str, Any], asset: Any) -> bool:
    if "asset_ids" in rule and asset.id not in rule["asset_ids"]:
        return False
    if "owners" in rule and asset.owner.value not in rule["owners"]:
        return False
    if "types" in rule and asset.type.value not in rule["types"]:
        return False
    if "minimum_criticality" in rule and asset.criticality < rule["minimum_criticality"]:
        return False
    if "maximum_users" in rule and asset.users > rule["maximum_users"]:
        return False
    return True


def assess_strategies(
    portfolio: Portfolio, rules_path: str | Path
) -> list[dict[str, Any]]:
    """Return one deterministic strategy decision, with provenance, per asset."""
    config = yaml.safe_load(Path(rules_path).read_text(encoding="utf-8"))
    rules = config.get("rules", [])
    decisions = []
    for asset in portfolio.assets:
        matched = next((rule for rule in rules if _matches(rule, asset)), None)
        if matched:
            strategy = matched["strategy"]
            decisions.append({
                "asset_id": asset.id,
                "strategy": strategy,
                "reason": [matched["reason"]],
                "confidence": float(matched.get("confidence", 0.5)),
                "rule": matched["name"],
                **({"exit_strategy": asset.exit_strategy.value}
                   if strategy == "retain_under_tsa" and asset.exit_strategy else {}),
            })
        else:
            fallback = config.get("default", {})
            strategy = fallback.get("strategy", "migrate")
            decisions.append({
                "asset_id": asset.id,
                "strategy": strategy,
                "reason": [fallback.get("reason", "Default pending review.")],
                "confidence": float(fallback.get("confidence", 0.5)),
                "rule": "default",
                **({"exit_strategy": asset.exit_strategy.value}
                   if strategy == "retain_under_tsa" and asset.exit_strategy else {}),
            })
    missing_exits = [
        item["asset_id"] for item in decisions
        if item["strategy"] == "retain_under_tsa" and "exit_strategy" not in item
    ]
    if missing_exits:
        raise ValueError(
            "Assets retained under TSA need an exit_strategy: "
            + ", ".join(missing_exits)
        )
    return decisions
