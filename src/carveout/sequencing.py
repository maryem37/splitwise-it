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


def _wave_start(
    candidate: date, freeze_periods: list[dict[str, str]]
) -> date:
    """Move a planned start past any freeze period that contains it."""
    while True:
        blocked = next((period for period in freeze_periods
                       if date.fromisoformat(period["start"]) <= candidate
                       <= date.fromisoformat(period["end"])), None)
        if blocked is None:
            return candidate
        candidate = date.fromisoformat(blocked["end"]) + timedelta(days=1)


def compute_waves(
    portfolio: Portfolio, constraints_path: str | Path | None = None
) -> dict[str, Any]:
    config = {}
    if constraints_path:
        config = yaml.safe_load(Path(constraints_path).read_text(encoding="utf-8")) or {}
    capacity = int(config.get("max_assets_per_wave", portfolio.planning.max_assets_per_wave))
    gap_weeks = int(config.get("weeks_per_wave_gap", portfolio.planning.weeks_per_wave_gap))
    freeze_periods = config.get("freeze_periods", [])

    graph = build_graph(portfolio)
    condensed = nx.condensation(graph)
    # Input edges point from a consumer to its prerequisite. Reverse to schedule
    # prerequisites first in the condensation DAG.
    prerequisites_first = condensed.reverse(copy=True)
    depths: dict[int, int] = {}
    for component in nx.topological_sort(prerequisites_first):
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
    previous_start = portfolio.planning.cutover_start - timedelta(weeks=gap_weeks)
    for number, wave_assets in enumerate(scheduled_assets, start=1):
        candidate = (portfolio.planning.cutover_start if number == 1
                     else previous_start + timedelta(weeks=gap_weeks))
        start = _wave_start(candidate, freeze_periods)
        previous_start = start
        completion = start + timedelta(
            weeks=max((asset_by_id[item].effort_weeks for item in wave_assets), default=0)
        )
        depends_on = sorted({
            asset_to_wave[relation.target]
            for relation in portfolio.relationships
            if relation.source in wave_assets
            and relation.target in asset_to_wave
            and asset_to_wave[relation.target] < number
        })
        wave_conflicts: list[dict[str, Any]] = []
        for asset_id in wave_assets:
            asset = asset_by_id[asset_id]
            if asset.licence_id:
                licence = licence_by_id.get(asset.licence_id)
                if licence and completion > licence.end_date:
                    wave_conflicts.append({
                        "type": "licence_expires_before_cutover",
                        "asset_id": asset_id,
                        "licence_id": licence.id,
                        "expiry": licence.end_date.isoformat(),
                        "planned_completion": completion.isoformat(),
                    })
            if asset.tsa_id:
                service = tsa_by_id.get(asset.tsa_id)
                if service and completion > service.end_date:
                    extension_end = _add_months(service.end_date, service.extension_months)
                    within_extension = service.extendable and completion <= extension_end
                    wave_conflicts.append({
                        "type": "tsa_extension_required" if within_extension else "tsa_ends_before_cutover",
                        "asset_id": asset_id,
                        "tsa_id": service.id,
                        "tsa_end": service.end_date.isoformat(),
                        "extension_end": extension_end.isoformat() if service.extendable else None,
                        "planned_completion": completion.isoformat(),
                        "message": (
                            f"{asset_id} needs {service.id} through {completion.isoformat()}, "
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
            "conflicts": wave_conflicts,
        })

    return {
        "waves": waves,
        "cycles": cycles(graph),
        "conflicts": conflicts,
        "constraints": {
            "max_assets_per_wave": capacity,
            "weeks_per_wave_gap": gap_weeks,
            "freeze_periods": freeze_periods,
        },
    }
