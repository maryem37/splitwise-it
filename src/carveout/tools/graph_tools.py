"""Dependency graph tools wrapping existing deterministic NetworkX algorithms."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from carveout.graph import build_graph, cycles, dependencies, impact, shared_assets
from carveout.loader import load_portfolio
from carveout.models import Portfolio


def _get_portfolio(portfolio_or_path: Portfolio | str | Path) -> Portfolio:
    if isinstance(portfolio_or_path, Portfolio):
        return portfolio_or_path
    return load_portfolio(portfolio_or_path)


def get_asset_dependencies(portfolio_or_path: Portfolio | str | Path, asset_id: str) -> dict[str, Any]:
    """Return direct and transitive prerequisites (assets that asset_id depends on)."""
    p = _get_portfolio(portfolio_or_path)
    g = build_graph(p)
    if asset_id not in g:
        raise KeyError(f"Unknown asset id: {asset_id}")

    # Direct prerequisites: out-edges in dependency graph (source depends on target)
    direct = sorted(g.successors(asset_id))
    transitive = dependencies(g, asset_id)

    return {
        "asset_id": asset_id,
        "direct_dependencies": direct,
        "transitive_dependencies": transitive,
    }


def get_asset_dependants(portfolio_or_path: Portfolio | str | Path, asset_id: str) -> dict[str, Any]:
    """Return direct and transitive dependants (assets that depend on asset_id)."""
    p = _get_portfolio(portfolio_or_path)
    g = build_graph(p)
    if asset_id not in g:
        raise KeyError(f"Unknown asset id: {asset_id}")

    # Direct dependants: in-edges in dependency graph
    direct = sorted(g.predecessors(asset_id))
    transitive = impact(g, asset_id)

    return {
        "asset_id": asset_id,
        "direct_dependants": direct,
        "transitive_dependants": transitive,
    }


def analyze_transitive_impact(portfolio_or_path: Portfolio | str | Path, asset_id: str) -> dict[str, Any]:
    """Complete upstream and downstream impact analysis for an asset."""
    deps = get_asset_dependencies(portfolio_or_path, asset_id)
    impacted = get_asset_dependants(portfolio_or_path, asset_id)
    p = _get_portfolio(portfolio_or_path)
    g = build_graph(p)

    return {
        "asset_id": asset_id,
        "depends_on": deps["transitive_dependencies"],
        "direct_dependencies": deps["direct_dependencies"],
        "depended_on_by": impacted["transitive_dependants"],
        "direct_dependants": impacted["direct_dependants"],
        "is_shared": asset_id in shared_assets(g),
    }


def detect_dependency_cycles(portfolio_or_path: Portfolio | str | Path) -> list[list[str]]:
    """Detect circular dependency cycles in the portfolio."""
    p = _get_portfolio(portfolio_or_path)
    g = build_graph(p)
    return cycles(g)


def identify_blocking_assets(portfolio_or_path: Portfolio | str | Path, min_dependants: int = 3) -> list[dict[str, Any]]:
    """Identify hubs/shared assets that block the largest number of downstream assets."""
    p = _get_portfolio(portfolio_or_path)
    g = build_graph(p)
    results = []
    for asset_id in g.nodes():
        downstream = impact(g, asset_id)
        if len(downstream) >= min_dependants:
            results.append({
                "asset_id": asset_id,
                "name": g.nodes[asset_id].get("name", ""),
                "owner": g.nodes[asset_id].get("owner", ""),
                "downstream_count": len(downstream),
                "downstream_assets": downstream,
            })
    results.sort(key=lambda x: -x["downstream_count"])
    return results
