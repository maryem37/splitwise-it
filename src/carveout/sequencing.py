"""Dependency-first wave planning with SCC grouping and date constraints."""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import networkx as nx
import yaml

from .graph import build_graph, cycles
from .models import Portfolio


def _add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _as_date(value: date | str) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def _wave_start(
    candidate: date, freeze_periods: list[dict[str, str]]
) -> date:
    """Move a planned start past any freeze period that contains it."""
    while True:
        blocked = next((period for period in freeze_periods
                       if _as_date(period["start"]) <= candidate
                       <= _as_date(period["end"])), None)
        if blocked is None:
            return candidate
        candidate = _as_date(blocked["end"]) + timedelta(days=1)


def _planning_graph(portfolio: Portfolio, strategies: list[dict[str, Any]] | None) -> nx.DiGraph:
    """Keep TSA-provided services available and schedule their exit after consumers."""
    graph = build_graph(portfolio)
    if not strategies:
        return graph
    retained = {
        item["asset_id"] for item in strategies
        if item.get("strategy") == "retain_under_tsa"
    }
    for service_id in sorted(retained):
        if service_id not in graph:
            continue
        consumers = sorted(graph.predecessors(service_id))
        for consumer in consumers:
            attrs = dict(graph.get_edge_data(consumer, service_id) or {})
            graph.remove_edge(consumer, service_id)
            graph.add_edge(service_id, consumer, **attrs)
    return graph


def compute_waves(
    portfolio: Portfolio,
    constraints_path: str | Path | None = None,
    strategies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    config = {}
    if constraints_path:
        config = yaml.safe_load(Path(constraints_path).read_text(encoding="utf-8")) or {}
    capacity = int(config.get("max_assets_per_wave", portfolio.planning.max_assets_per_wave))
    gap_weeks = int(config.get("weeks_per_wave_gap", portfolio.planning.weeks_per_wave_gap))
    freeze_periods = config.get("freeze_periods", [])

    source_graph = build_graph(portfolio)
    graph = _planning_graph(portfolio, strategies)
    condensed = nx.condensation(graph)
    # Input edges point from a consumer to its prerequisite. Reverse to schedule
    # prerequisites first in the condensation DAG.
    prerequisites_first = condensed.reverse(copy=True)
    asset_prerequisites_first = graph.reverse(copy=True)
    depths: dict[int, int] = {}
    component_key = lambda node: tuple(sorted(condensed.nodes[node]["members"]))
    for component in nx.lexicographical_topological_sort(
        prerequisites_first, key=component_key
    ):
        depths[component] = 1 + max(
            (depths[parent] for parent in prerequisites_first.predecessors(component)),
            default=0,
        )

    by_depth: dict[int, list[tuple[str, ...]]] = {}
    for component, depth in depths.items():
        members = tuple(sorted(condensed.nodes[component]["members"]))
        by_depth.setdefault(depth, []).append(members)

    # Keep every strongly connected component intact while splitting oversized
    # levels into capacity-limited consecutive waves.
    scheduled_assets: list[list[str]] = []
    conflicts: list[dict[str, Any]] = []
    for depth in sorted(by_depth):
        components = sorted(by_depth[depth])
        current: list[str] = []
        for members in components:
            if len(members) > capacity:
                conflicts.append({
                    "type": "cycle_exceeds_wave_capacity",
                    "assets": list(members),
                    "message": f"Strongly connected group has {len(members)} assets; capacity is {capacity}.",
                })
            if current and len(current) + len(members) > capacity:
                scheduled_assets.append(current)
                current = []
            current.extend(members)
        if current:
            scheduled_assets.append(current)

    asset_to_wave = {
        asset_id: wave_number
        for wave_number, wave_assets in enumerate(scheduled_assets, start=1)
        for asset_id in wave_assets
    }
    asset_by_id = {asset.id: asset for asset in portfolio.assets}
    licence_by_id = {licence.id: licence for licence in portfolio.licences}
    tsa_by_id = {service.id: service for service in portfolio.tsa_services}

    waves: list[dict[str, Any]] = []
    previous_completion = portfolio.planning.cutover_start
    for number, wave_assets in enumerate(scheduled_assets, start=1):
        candidate = (portfolio.planning.cutover_start if number == 1 else
                     previous_completion + timedelta(weeks=gap_weeks))
        start = _wave_start(candidate, freeze_periods)
        completion = start + timedelta(
            weeks=max((asset_by_id[item].effort_weeks for item in wave_assets), default=0)
        )
        previous_completion = completion
        depends_on = sorted({
            asset_to_wave[dependency]
            for asset_id in wave_assets
            for dependency in asset_prerequisites_first.predecessors(asset_id)
            if dependency in asset_to_wave and asset_to_wave[dependency] < number
        })
        wave_conflicts: list[dict[str, Any]] = []
        for asset_id in wave_assets:
            asset = asset_by_id[asset_id]
            asset_completion = start + timedelta(weeks=asset.effort_weeks)
            if asset.licence_id:
                licence = licence_by_id.get(asset.licence_id)
                if licence and asset_completion > licence.end_date:
                    wave_conflicts.append({
                        "type": "licence_expires_before_cutover",
                        "asset_id": asset_id,
                        "licence_id": licence.id,
                        "expiry": licence.end_date.isoformat(),
                        "planned_completion": asset_completion.isoformat(),
                    })
            if asset.tsa_id:
                service = tsa_by_id.get(asset.tsa_id)
                if service and asset_completion > service.end_date:
                    extension_end = _add_months(service.end_date, service.extension_months)
                    within_extension = service.extendable and asset_completion <= extension_end
                    wave_conflicts.append({
                        "type": "tsa_extension_required" if within_extension else "tsa_ends_before_cutover",
                        "asset_id": asset_id,
                        "tsa_id": service.id,
                        "tsa_end": service.end_date.isoformat(),
                        "extension_end": extension_end.isoformat() if service.extendable else None,
                        "planned_completion": asset_completion.isoformat(),
                        "message": (
                            f"{asset_id} needs {service.id} through {asset_completion.isoformat()}, "
                            f"but the TSA ends {service.end_date.isoformat()}."
                        ),
                    })
        conflicts.extend(wave_conflicts)
        waves.append({
            "wave": number,
            "assets": sorted(wave_assets),
            "depends_on_waves": depends_on,
            "planned_start": start.isoformat(),
            "planned_completion": completion.isoformat(),
            "asset_completion_dates": {
                asset_id: (start + timedelta(weeks=asset_by_id[asset_id].effort_weeks)).isoformat()
                for asset_id in sorted(wave_assets)
            },
            "conflicts": wave_conflicts,
        })

    return {
        "waves": waves,
        "cycles": cycles(source_graph),
        "conflicts": conflicts,
        "constraints": {
            "max_assets_per_wave": capacity,
            "weeks_per_wave_gap": gap_weeks,
            "freeze_periods": freeze_periods,
        },
    }
