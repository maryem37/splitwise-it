"""Tests for Phase 1 agent tool wrappers."""
from pathlib import Path
import pytest

from carveout.tools.graph_tools import (
    analyze_transitive_impact,
    detect_dependency_cycles,
    get_asset_dependants,
    get_asset_dependencies,
    identify_blocking_assets,
)
from carveout.tools.planning_tools import (
    compute_baseline_plan,
    get_asset_schedule,
    validate_portfolio_data,
)
from carveout.tools.risk_tools import (
    calculate_tsa_costs,
    detect_schedule_conflicts,
    generate_risk_register_data,
)
from carveout.tools.neo4j_tools import query_graph_analytics

ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = ROOT / "data" / "portfolio_v1.yaml"
RULES = ROOT / "config" / "strategy_rules.yaml"
CONSTRAINTS = ROOT / "config" / "constraints.yaml"


def test_graph_tools_dependencies_and_dependants():
    deps = get_asset_dependencies(PORTFOLIO, "DB-01")
    assert "INF-01" in deps["transitive_dependencies"]
    assert "direct_dependencies" in deps

    dependants = get_asset_dependants(PORTFOLIO, "DB-01")
    assert "APP-01" in dependants["transitive_dependants"]

    impact = analyze_transitive_impact(PORTFOLIO, "DB-01")
    assert "INF-01" in impact["depends_on"]
    assert "APP-01" in impact["depended_on_by"]
    assert isinstance(impact["is_shared"], bool)


def test_graph_tools_cycles_and_blockers():
    cycles = detect_dependency_cycles(PORTFOLIO)
    assert isinstance(cycles, list)
    assert len(cycles) > 0  # portfolio_v1 has at least 1 cycle

    blockers = identify_blocking_assets(PORTFOLIO, min_dependants=2)
    assert len(blockers) > 0
    assert "downstream_count" in blockers[0]


def test_planning_tools_baseline_and_schedule():
    val = validate_portfolio_data(PORTFOLIO)
    assert val["valid"] is True

    plan = compute_baseline_plan(PORTFOLIO, RULES, CONSTRAINTS)
    assert "waves" in plan
    assert "metrics" in plan
    assert "conflicts" in plan

    sched = get_asset_schedule(PORTFOLIO, RULES, CONSTRAINTS, "APP-01")
    assert "wave" in sched
    assert "planned_completion" in sched


def test_risk_tools():
    conflicts = detect_schedule_conflicts(PORTFOLIO, RULES, CONSTRAINTS)
    assert isinstance(conflicts, list)

    risks = generate_risk_register_data(PORTFOLIO, RULES, CONSTRAINTS)
    assert len(risks) > 0
    assert all("id" in r and "risk" in r for r in risks)

    costs = calculate_tsa_costs(PORTFOLIO, RULES, CONSTRAINTS)
    assert costs["estimated_tsa_cost_total"] > 0
    assert "tsa_months_needed" in costs


def test_neo4j_tools_graceful_when_offline():
    # Calling named query when Neo4j is offline returns a graceful error dictionary, not an unhandled crash
    res = query_graph_analytics("cycles", uri="bolt://127.0.0.1:9999")
    assert len(res) == 1
    assert "error" in res[0]
