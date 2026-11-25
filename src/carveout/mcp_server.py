"""Read-only MCP tools for inspecting and planning a carve-out portfolio."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .graph import build_graph, dependencies, impact
from .loader import load_portfolio, validate_portfolio
from .metrics import calculate_metrics
from .models import AssetType, Owner, Portfolio
from .sequencing import compute_waves
from .strategy import assess_strategies


ROOT = Path(__file__).resolve().parents[2]


def _configured_path(variable: str, default: str) -> Path:
    value = os.environ.get(variable)
    path = Path(value).expanduser() if value else ROOT / default
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def _load_portfolio() -> Portfolio:
    portfolio = load_portfolio(_configured_path("CARVEOUT_PORTFOLIO", "data/portfolio_v1.yaml"))
    report = validate_portfolio(portfolio)
    if not report["valid"]:
        raise ValueError(f"Invalid portfolio: {report['errors']}")
    return portfolio


def portfolio_summary() -> dict[str, Any]:
    """Return portfolio counts and planning dates without writing files."""
    portfolio = _load_portfolio()
    return {
        "company": portfolio.planning.company,
        "planning": {
            "day1": portfolio.planning.day1.isoformat(),
            "cutover_start": portfolio.planning.cutover_start.isoformat(),
            "target_tsa_exit": portfolio.planning.target_tsa_exit.isoformat(),
            "max_assets_per_wave": portfolio.planning.max_assets_per_wave,
        },
        "counts": {
            "assets": len(portfolio.assets),
            "relationships": len(portfolio.relationships),
            "licences": len(portfolio.licences),
            "tsa_services": len(portfolio.tsa_services),
            "sensitive_assets": sum(asset.sensitive for asset in portfolio.assets),
        },
    }


def list_assets(
    asset_type: str | None = None,
    owner: str | None = None,
    sensitive_only: bool = False,
) -> list[dict[str, Any]]:
    """List asset metadata with optional type, owner, and sensitivity filters."""
    valid_types = {item.value for item in AssetType}
    valid_owners = {item.value for item in Owner}
    if asset_type is not None and asset_type not in valid_types:
        raise ValueError(f"Unknown asset type {asset_type!r}; expected one of {sorted(valid_types)}.")
    if owner is not None and owner not in valid_owners:
        raise ValueError(f"Unknown owner {owner!r}; expected one of {sorted(valid_owners)}.")

    portfolio = _load_portfolio()
    return [
        {
            "id": asset.id,
            "name": asset.name,
            "type": asset.type.value,
            "owner": asset.owner.value,
            "criticality": asset.criticality,
            "users": asset.users,
            "function": asset.function,
            "sensitive": asset.sensitive,
            "build_effort_weeks": asset.build_effort_weeks,
            "effort_weeks": asset.effort_weeks,
            "licence_id": asset.licence_id,
            "tsa_id": asset.tsa_id,
        }
        for asset in portfolio.assets
        if (asset_type is None or asset.type.value == asset_type)
        and (owner is None or asset.owner.value == owner)
        and (not sensitive_only or asset.sensitive)
    ]


def asset_dependencies(asset_id: str) -> dict[str, Any]:
    """Return prerequisites and dependants for an asset; edges mean source depends on target."""
    portfolio = _load_portfolio()
    graph = build_graph(portfolio)
    if asset_id not in graph:
        raise KeyError(f"Unknown asset id: {asset_id}")
    return {
        "asset_id": asset_id,
        "depends_on": dependencies(graph, asset_id),
        "depended_on_by": impact(graph, asset_id),
    }


def compute_plan() -> dict[str, Any]:
    """Compute strategies, waves, metrics, and conflicts in memory only."""
    portfolio = _load_portfolio()
    rules_path = _configured_path("CARVEOUT_RULES", "config/strategy_rules.yaml")
    constraints_path = _configured_path("CARVEOUT_CONSTRAINTS", "config/constraints.yaml")
    strategies = assess_strategies(portfolio, rules_path)
    sequencing = compute_waves(portfolio, constraints_path, strategies)
    return {
        "strategies": strategies,
        "waves": sequencing["waves"],
        "cycles": sequencing["cycles"],
        "conflicts": sequencing["conflicts"],
        "metrics": calculate_metrics(portfolio, sequencing),
    }


def create_server() -> Any:
    """Create the MCP server, importing the optional SDK only when requested."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError("Install the MCP extra with `pip install -e \".[mcp]\"`.") from exc

    server = FastMCP("carveout-copilot")
    server.tool()(portfolio_summary)
    server.tool()(list_assets)
    server.tool()(asset_dependencies)
    server.tool()(compute_plan)
    return server


def main() -> None:
    """Run the read-only server over the MCP stdio transport."""
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
