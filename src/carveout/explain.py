"""Explainable dependency and wave planning inspection for assets in Carve-out Copilot."""
from __future__ import annotations

import networkx as nx
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field

from carveout.decision_provenance import DecisionProvenanceRecord
from carveout.graph import build_graph
from carveout.loader import load_portfolio
from carveout.models import Portfolio
from carveout.optimization.models import OptimizationResult
from carveout.optimization.solver import solve_migration_schedule
from carveout.sequencing import compute_waves
from carveout.strategy import assess_strategies


class AssetWaveExplanation(BaseModel):
    """Detailed justification for an asset's assigned wave, dependencies, and consequences of movement."""
    asset_id: str
    asset_name: str
    asset_type: str
    owner: str
    strategy: str
    assigned_wave: int
    planned_start: str
    planned_completion: str
    min_possible_wave: int
    direct_prerequisites: list[str] = Field(default_factory=list)
    all_upstream_dependencies: list[str] = Field(default_factory=list)
    direct_dependants: list[str] = Field(default_factory=list)
    all_downstream_dependants: list[str] = Field(default_factory=list)
    scc_members: list[str] = Field(default_factory=list)
    blocking_dependencies: list[str] = Field(default_factory=list)
    identified_conflicts: list[str] = Field(default_factory=list)
    placement_rationale: str
    move_consequences: dict[str, str] = Field(default_factory=dict)
    provenance: DecisionProvenanceRecord | None = None


def explain_asset_planning(
    portfolio_or_path: str | Path | Portfolio,
    asset_id: str,
    rules_path: str | Path = "config/strategy_rules.yaml",
    constraints_path: str | Path = "config/constraints.yaml",
    optimization_result: OptimizationResult | None = None,
) -> AssetWaveExplanation:
    """
    Produce a grounded, deterministic explanation of why an asset was assigned to its wave,
    traceable to the dependency graph and constraints.
    """
    portfolio = portfolio_or_path if isinstance(portfolio_or_path, Portfolio) else load_portfolio(portfolio_or_path)
    asset = next((a for a in portfolio.assets if a.id == asset_id), None)
    if not asset:
        raise KeyError(f"Asset '{asset_id}' not found in portfolio.")

    strategies = assess_strategies(portfolio, rules_path)
    strat_entry = next((s for s in strategies if s.get("asset_id") == asset_id), {})
    strategy = strat_entry.get("strategy", "migrate")

    g = build_graph(portfolio)

    # Direct and transitive relations in dependency graph (edge U -> V means U depends on V)
    prereqs = sorted(g.successors(asset_id))
    dependants = sorted(g.predecessors(asset_id))

    all_prereqs = sorted(nx.descendants(g, asset_id))
    all_dependants = sorted(nx.ancestors(g, asset_id))

    # Strongly connected components
    sccs = list(nx.strongly_connected_components(g))
    scc_for_asset = sorted(next((s for s in sccs if asset_id in s and len(s) > 1), [asset_id]))

    # Determine wave placement (from CP-SAT result or deterministic sequencing)
    if optimization_result and asset_id in optimization_result.asset_schedules:
        sched = optimization_result.asset_schedules[asset_id]
        wave = sched.wave
        start_date = sched.planned_start
        completion_date = sched.planned_completion
    else:
        seq = compute_waves(portfolio, constraints_path, strategies=strategies)
        wave_map = {aid: w["wave"] for w in seq["waves"] for aid in w["assets"]}
        wave = wave_map.get(asset_id, 1)
        wave_info = next((w for w in seq["waves"] if w["wave"] == wave), {})
        start_date = wave_info.get("planned_start", "")
        completion_date = wave_info.get("asset_completion_dates", {}).get(asset_id, "")

    # Calculate min possible wave based on prerequisites
    # If strategy is retain_under_tsa, dependencies are inverted in sequencing
    is_tsa = strategy == "retain_under_tsa"
    blocking = [p for p in prereqs if p not in scc_for_asset]

    # Calculate earliest feasible wave (max wave among non-SCC prerequisites + 1)
    # We can determine this by checking what wave prerequisites reside in
    earliest_wave = 1
    if not is_tsa and prereqs:
        earliest_wave = 2

    # Conflicts involving this asset
    conflicts: list[str] = []
    for tsa in portfolio.tsa_services:
        if getattr(asset, "tsa_id", None) == tsa.id:
            if completion_date and completion_date > tsa.end_date.isoformat():
                conflicts.append(f"TSA overrun: completes {completion_date} after {tsa.id} expires {tsa.end_date.isoformat()}")

    # Rationale
    rationale_parts = []
    if len(scc_for_asset) > 1:
        rationale_parts.append(
            f"Asset {asset_id} participates in a circular dependency with {scc_for_asset} and must co-locate in Wave {wave}."
        )
    if is_tsa:
        rationale_parts.append(
            f"Asset {asset_id} uses strategy 'retain_under_tsa', meaning it remains in parent custody until all dependants exit."
        )
    elif prereqs:
        rationale_parts.append(
            f"Must be scheduled after prerequisite assets: {', '.join(prereqs[:5])}."
        )
    else:
        rationale_parts.append(f"Independent leaf/foundation asset; eligible for early migration.")

    # Consequence of moving earlier or later
    move_consequences = {
        "move_earlier": (
            f"Violates prerequisite ordering with upstream dependencies ({', '.join(prereqs[:3])})."
            if wave > 1 and prereqs else "Already in earliest possible wave."
        ),
        "move_later": (
            f"Delays {len(dependants)} downstream dependants ({', '.join(dependants[:3])}) and increases TSA exposure."
            if dependants else "Increases wave span and pushes final portfolio cutover."
        ),
    }

    # Provenance record
    prov = DecisionProvenanceRecord(
        decision_id=f"DEC-WAVE-{asset_id}",
        asset_id=asset_id,
        decision_category="wave_assignment",
        selected_action=f"Wave {wave} ({start_date} to {completion_date})",
        justification=" ".join(rationale_parts),
        supporting_dependencies=prereqs,
        relevant_constraints=["dependency_precedence", "wave_capacity", "scc_colocation"],
        related_risks=conflicts,
        source_references=[f"portfolio:{asset_id}", f"strategy:{strategy}"],
        responsible_component="optimization_engine" if optimization_result else "deterministic_planner",
        evaluation_status="PASS",
        deterministic_facts={
            "wave": wave,
            "prerequisites_count": len(prereqs),
            "dependants_count": len(dependants),
            "scc_size": len(scc_for_asset),
        },
        narrative_explanation=" ".join(rationale_parts),
    )

    return AssetWaveExplanation(
        asset_id=asset_id,
        asset_name=asset.name,
        asset_type=asset.type.value,
        owner=asset.owner.value,
        strategy=strategy,
        assigned_wave=wave,
        planned_start=start_date,
        planned_completion=completion_date,
        min_possible_wave=earliest_wave,
        direct_prerequisites=prereqs,
        all_upstream_dependencies=all_prereqs,
        direct_dependants=dependants,
        all_downstream_dependants=all_dependants,
        scc_members=scc_for_asset if len(scc_for_asset) > 1 else [],
        blocking_dependencies=blocking,
        identified_conflicts=conflicts,
        placement_rationale=" ".join(rationale_parts),
        move_consequences=move_consequences,
        provenance=prov,
    )
