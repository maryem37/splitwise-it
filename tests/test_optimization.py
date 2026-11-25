"""Unit and integration tests for OR-Tools CP-SAT optimization, validation, and scenarios."""
from datetime import date, timedelta
from pathlib import Path
import sys
import types
import pytest

from carveout.loader import load_portfolio
from carveout.models import (
    Asset,
    AssetType,
    Owner,
    Planning,
    Portfolio,
    Relationship,
    RelType,
    TSAService,
)
from carveout.optimization.models import AssetScheduleResult, OptimizationConfig, OptimizationResult
from carveout.optimization.scenarios import run_scenario
from carveout.optimization.solver import _ensure_cp_model, solve_migration_schedule
from carveout.optimization.validation import validate_schedule_constraints
from carveout.strategy import assess_strategies
from carveout.tools.optimization_tools import compare_migration_scenarios, optimize_migration_schedule
from carveout.tools.strategy_tools import (
    compare_asset_strategy_options,
    get_all_strategy_assessments,
    get_asset_strategy_assessment,
)

ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = ROOT / "data" / "portfolio_v1.yaml"
RULES = ROOT / "config" / "strategy_rules.yaml"
CONSTRAINTS = ROOT / "config" / "constraints.yaml"


def test_strategy_tools():
    all_decisions = get_all_strategy_assessments(PORTFOLIO, RULES)
    assert len(all_decisions) == 30

    app01_dec = get_asset_strategy_assessment(PORTFOLIO, RULES, "APP-01")
    assert app01_dec["asset_id"] == "APP-01"
    assert app01_dec["strategy"] == "retain_under_tsa"
    assert "exit_strategy" in app01_dec

    comp = compare_asset_strategy_options(PORTFOLIO, RULES, "APP-06")
    assert comp["current_strategy"] == "migrate"
    assert "clone" in comp["available_strategies"]
    assert "migrate" in comp["available_strategies"]


def test_strategy_tools_unknown_asset_raises_key_error():
    with pytest.raises(KeyError, match="NONEXISTENT"):
        get_asset_strategy_assessment(PORTFOLIO, RULES, "NONEXISTENT")


def test_cpsat_solver_strict_dependency_ordering_and_scc():
    p = load_portfolio(PORTFOLIO)
    strategies = assess_strategies(p, RULES)
    retained = {s["asset_id"] for s in strategies if s.get("strategy") == "retain_under_tsa"}

    cfg = OptimizationConfig(max_solve_time_seconds=5.0)
    res = solve_migration_schedule(
        p, strategies, cfg, scenario_id="test_baseline", constraints_path=CONSTRAINTS
    )

    assert res.status in ("OPTIMAL", "FEASIBLE")
    assert res.total_waves > 0
    assert res.estimated_tsa_cost_total > 0

    # Verify APP-06 and APP-07 remain in the SAME wave (SCC coupling)
    app06_wave = res.asset_schedules["APP-06"].wave
    app07_wave = res.asset_schedules["APP-07"].wave
    assert app06_wave == app07_wave

    # Verify strict dependency ordering between distinct SCCs
    for rel in p.relationships:
        if {rel.source, rel.target} == {"APP-06", "APP-07"}:
            continue
        w_src = res.asset_schedules[rel.source].wave
        w_tgt = res.asset_schedules[rel.target].wave
        if rel.target in retained:
            assert w_src < w_tgt, f"TSA consumer {rel.source} (W{w_src}) must precede {rel.target} (W{w_tgt})"
        else:
            assert w_tgt < w_src, f"Prerequisite {rel.target} (W{w_tgt}) must precede {rel.source} (W{w_src})"

    val = validate_schedule_constraints(p, res, retained, constraints_path=CONSTRAINTS)
    assert val["valid"] is True, f"Constraint violations: {val['violations']}"


def test_scenario_delays_zero_four_twelve_weeks_and_immutability():
    before_text = PORTFOLIO.read_text(encoding="utf-8")

    res_base, comp_base = run_scenario(
        str(PORTFOLIO), str(RULES), scenario_type="baseline", constraints_path=CONSTRAINTS
    )
    base_start = date.fromisoformat(res_base.asset_schedules["APP-06"].planned_start)

    # 0-week delay matches baseline
    res_0, comp_0 = run_scenario(
        str(PORTFOLIO), str(RULES), scenario_type="app_06_delay", delay_weeks=0, constraints_path=CONSTRAINTS
    )
    assert comp_0.is_feasible is True
    assert date.fromisoformat(res_0.asset_schedules["APP-06"].planned_start) == base_start

    # 4-week delay shifts APP-06 and APP-07 by >= 4 weeks
    res_4, comp_4 = run_scenario(
        str(PORTFOLIO), str(RULES), scenario_type="app_06_delay", delay_weeks=4, constraints_path=CONSTRAINTS
    )
    assert comp_4.is_feasible is True
    assert res_4.asset_schedules["APP-06"].wave == res_4.asset_schedules["APP-07"].wave
    start_4 = date.fromisoformat(res_4.asset_schedules["APP-06"].planned_start)
    assert start_4 >= base_start + timedelta(weeks=4)

    # 12-week delay shifts APP-06 and APP-07 by >= 12 weeks
    res_12, comp_12 = run_scenario(
        str(PORTFOLIO), str(RULES), scenario_type="app_06_delay", delay_weeks=12, constraints_path=CONSTRAINTS
    )
    assert comp_12.is_feasible is True
    assert res_12.asset_schedules["APP-06"].wave == res_12.asset_schedules["APP-07"].wave
    start_12 = date.fromisoformat(res_12.asset_schedules["APP-06"].planned_start)
    assert start_12 >= base_start + timedelta(weeks=12)
    assert res_12.asset_schedules["APP-06"].planned_start == res_12.asset_schedules["APP-07"].planned_start

    # Original portfolio YAML untouched
    after_text = PORTFOLIO.read_text(encoding="utf-8")
    assert before_text == after_text


def test_freeze_periods_respected_and_validated(tmp_path):
    constraints_file = tmp_path / "constraints_freeze.yaml"
    # Wave 1 normally starts 2027-03-01; freeze 2027-03-01..2027-03-21 pushes it to 2027-03-22
    constraints_file.write_text(
        "max_assets_per_wave: 8\n"
        "weeks_per_wave_gap: 2\n"
        "freeze_periods:\n"
        "  - start: '2027-03-01'\n"
        "    end: '2027-03-21'\n",
        encoding="utf-8",
    )
    res, comp = run_scenario(
        str(PORTFOLIO), str(RULES), scenario_type="baseline", constraints_path=constraints_file
    )
    assert comp.is_feasible is True
    w1_start = date.fromisoformat(res.waves[0]["planned_start"])
    assert w1_start >= date(2027, 3, 22)

    # Independent validator catches a schedule whose start violates a freeze period
    p = load_portfolio(PORTFOLIO)
    strategies = assess_strategies(p, RULES)
    retained = {s["asset_id"] for s in strategies if s.get("strategy") == "retain_under_tsa"}
    bad_res = res.model_copy(deep=True)
    bad_res.waves[0]["planned_start"] = "2027-03-10"
    val = validate_schedule_constraints(p, bad_res, retained, constraints_path=constraints_file)
    assert val["valid"] is False
    assert any(f["constraint_name"] == "freeze_period" for f in val["findings"])


def test_non_contiguous_wave_numbers_validation():
    p = Portfolio(
        planning=Planning(
            company="Test",
            carve_out_description="Non-contiguous waves",
            day1=date(2027, 1, 1),
            cutover_start=date(2027, 3, 1),
            target_tsa_exit=date(2027, 12, 31),
            max_assets_per_wave=8,
            weeks_per_wave_gap=2,
        ),
        assets=[
            Asset(id="A-1", name="A1", type=AssetType.APPLICATION, owner=Owner.CARVED_OUT, criticality=3, effort_weeks=2),
            Asset(id="A-2", name="A2", type=AssetType.APPLICATION, owner=Owner.CARVED_OUT, criticality=3, effort_weeks=2),
        ],
        relationships=[Relationship(source="A-2", target="A-1", type=RelType.CALLS)],
    )
    res = OptimizationResult(
        status="OPTIMAL",
        total_waves=2,
        latest_completion_date="2027-04-12",
        waves=[
            {
                "wave": 1,
                "assets": ["A-1"],
                "planned_start": "2027-03-01",
                "planned_completion": "2027-03-15",
                "asset_completion_dates": {"A-1": "2027-03-15"},
                "conflicts": [],
            },
            {
                "wave": 3,
                "assets": ["A-2"],
                "planned_start": "2027-03-29",
                "planned_completion": "2027-04-12",
                "asset_completion_dates": {"A-2": "2027-04-12"},
                "conflicts": [],
            },
        ],
        asset_schedules={
            "A-1": AssetScheduleResult(
                asset_id="A-1", name="A1", wave=1, start_week=0, completion_week=2,
                planned_start="2027-03-01", planned_completion="2027-03-15", strategy="migrate"
            ),
            "A-2": AssetScheduleResult(
                asset_id="A-2", name="A2", wave=3, start_week=0, completion_week=2,
                planned_start="2027-03-29", planned_completion="2027-04-12", strategy="migrate"
            ),
        },
    )
    val = validate_schedule_constraints(p, res, set())
    assert val["valid"] is True


def test_minimize_cost_prefers_cheaper_tsa_order():
    # Two independent assets with capacity=1: A-EXPENSIVE ($100k/mo) vs A-CHEAP ($10k/mo)
    # minimize_cost must schedule A-EXPENSIVE in Wave 1 and A-CHEAP in Wave 2.
    p = Portfolio(
        planning=Planning(
            company="CostTest",
            carve_out_description="Cost priority",
            day1=date(2027, 1, 1),
            cutover_start=date(2027, 3, 1),
            target_tsa_exit=date(2027, 12, 31),
            max_assets_per_wave=1,
            weeks_per_wave_gap=4,
        ),
        assets=[
            Asset(id="A-CHEAP", name="Cheap", type=AssetType.APPLICATION, owner=Owner.CARVED_OUT, criticality=3, effort_weeks=4, tsa_id="TSA-LOW"),
            Asset(id="A-EXP", name="Expensive", type=AssetType.APPLICATION, owner=Owner.CARVED_OUT, criticality=3, effort_weeks=4, tsa_id="TSA-HIGH"),
        ],
        relationships=[],
        tsa_services=[
            TSAService(id="TSA-LOW", service="Low", start_date=date(2027, 1, 1), end_date=date(2027, 12, 31), monthly_cost=10000),
            TSAService(id="TSA-HIGH", service="High", start_date=date(2027, 1, 1), end_date=date(2027, 12, 31), monthly_cost=100000),
        ],
    )
    strats = [
        {"asset_id": "A-CHEAP", "strategy": "migrate"},
        {"asset_id": "A-EXP", "strategy": "migrate"},
    ]
    res = solve_migration_schedule(p, strats, OptimizationConfig(objective="minimize_cost", max_assets_per_wave=1, gap_weeks=4))
    assert res.status == "OPTIMAL"
    assert res.asset_schedules["A-EXP"].wave == 1
    assert res.asset_schedules["A-CHEAP"].wave == 2


def test_pandas_compat_with_and_without_pandas(monkeypatch):
    # 1. With mock pandas available in sys.modules
    fake_pd = types.ModuleType("pandas")
    fake_pd.DataFrame = object
    fake_pd.Series = object
    fake_pd.Index = object
    monkeypatch.setitem(sys.modules, "pandas", fake_pd)
    cp_mod = _ensure_cp_model()
    assert hasattr(cp_mod, "CpModel")

    # 2. When pandas is absent / blocked
    monkeypatch.delitem(sys.modules, "pandas", raising=False)
    cp_mod2 = _ensure_cp_model()
    assert hasattr(cp_mod2, "CpModel")


def test_optimization_tools():
    opt_res = optimize_migration_schedule(
        str(PORTFOLIO), str(RULES), objective="minimize_cost", constraints_path=CONSTRAINTS
    )
    assert opt_res["optimization_result"]["status"] in ("OPTIMAL", "FEASIBLE")

    comp_res = compare_migration_scenarios(
        str(PORTFOLIO), str(RULES), scenario_type="app_06_delay", delay_weeks=12, constraints_path=CONSTRAINTS
    )
    assert comp_res["comparison"]["scenario_id"] == "app_06_delay"
