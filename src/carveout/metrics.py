"""Summary measures calculated from portfolio dependencies and planned waves."""
from __future__ import annotations

from datetime import date
from typing import Any

import networkx as nx

from .graph import build_graph, cycles
from .models import Portfolio


def calculate_metrics(portfolio: Portfolio, sequencing: dict[str, Any]) -> dict[str, Any]:
    graph = build_graph(portfolio)
    condensed = nx.condensation(graph)
    dag = condensed.reverse(copy=True)
    longest_chain = len(nx.dag_longest_path(dag)) if dag.number_of_nodes() else 0
    latest_completion = max(
        (date.fromisoformat(wave["planned_completion"]) for wave in sequencing["waves"]),
        default=portfolio.planning.day1,
    )
    tsa_months: dict[str, int] = {}
    tsa_cost: dict[str, float] = {}
    for service in portfolio.tsa_services:
        # Count calendar months from TSA start through the latest asset cutover
        # that explicitly references this service; extension exposure is capped
        # by the actual planned duration.
        linked_ids = {asset.id for asset in portfolio.assets if asset.tsa_id == service.id}
        completions = [
            date.fromisoformat(wave["asset_completion_dates"][asset_id])
            for wave in sequencing["waves"]
            for asset_id in linked_ids.intersection(wave["assets"])
        ]
        end = max(completions, default=service.start_date)
        months = max(0, (end.year - service.start_date.year) * 12
                     + end.month - service.start_date.month
                     + (1 if end.day > service.start_date.day else 0))
        tsa_months[service.id] = months
        tsa_cost[service.id] = round(months * service.monthly_cost, 2)
    return {
        "wave_count": len(sequencing["waves"]),
        "longest_dependency_chain_components": longest_chain,
        "cycle_count": len(cycles(graph)),
        "tsa_months_needed": tsa_months,
        "estimated_tsa_cost": tsa_cost,
        "estimated_tsa_cost_total": round(sum(tsa_cost.values()), 2),
        "latest_planned_completion": latest_completion.isoformat(),
    }
