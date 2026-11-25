"""Tests for Phase 4 decision provenance, asset explanations, and plan comparisons."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from carveout.comparison import compare_baseline_and_optimized
from carveout.decision_provenance import DecisionProvenanceRecord, DecisionProvenanceRegistry
from carveout.explain import explain_asset_planning
from carveout.loader import load_portfolio

PORTFOLIO = Path("data/portfolio_v1.yaml")
RULES = Path("config/strategy_rules.yaml")
CONSTRAINTS = Path("config/constraints.yaml")


def test_decision_provenance_registry():
    registry = DecisionProvenanceRegistry(execution_id="exec-001")
    record = DecisionProvenanceRecord(
        decision_id="DEC-001",
        asset_id="APP-06",
        decision_category="wave_assignment",
        selected_action="Wave 3",
        justification="SCC co-location with APP-07",
        supporting_dependencies=["APP-01", "APP-07"],
        deterministic_facts={"wave": 3},
    )
    registry.add_record(record)
    assert len(registry.records) == 1
    found = registry.get_for_asset("APP-06")
    assert len(found) == 1
    assert found[0].decision_id == "DEC-001"
    assert found[0].deterministic_facts["wave"] == 3


def test_explain_asset_planning_grounded_in_dependencies():
    p = load_portfolio(PORTFOLIO)
    exp = explain_asset_planning(p, "APP-06", rules_path=RULES, constraints_path=CONSTRAINTS)

    assert exp.asset_id == "APP-06"
    assert exp.assigned_wave >= 1
    assert "APP-07" in exp.scc_members
    assert "APP-07" in exp.direct_prerequisites
    assert "circular dependency" in exp.placement_rationale.lower()
    assert "Violates prerequisite ordering" in exp.move_consequences["move_earlier"] or "earliest" in exp.move_consequences["move_earlier"]
    assert exp.provenance is not None
    assert exp.provenance.decision_id == "DEC-WAVE-APP-06"


def test_explain_asset_planning_not_found():
    p = load_portfolio(PORTFOLIO)
    with pytest.raises(KeyError, match="not found in portfolio"):
        explain_asset_planning(p, "NON_EXISTENT_APP", rules_path=RULES, constraints_path=CONSTRAINTS)


def test_compare_baseline_and_optimized():
    rep = compare_baseline_and_optimized(
        PORTFOLIO,
        rules_path=RULES,
        constraints_path=CONSTRAINTS,
        optimized_scenario="minimize_cost",
    )

    assert rep.baseline.total_waves > 0
    assert rep.optimized.total_waves > 0
    assert rep.baseline.tsa_cost > 0
    assert rep.optimized.tsa_cost > 0
    assert rep.optimized.solver_status in ("OPTIMAL", "FEASIBLE")
    assert "CP-SAT" in rep.tradeoff_analysis
    assert "proxy objective" in rep.objective_vs_financial_note
