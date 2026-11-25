from datetime import date

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
from carveout.sequencing import compute_waves


def make_portfolio(assets, relationships=(), tsa_services=(), capacity=8):
    return Portfolio(
        planning=Planning(
            company="Example",
            carve_out_description="Test portfolio",
            day1=date(2027, 1, 1),
            cutover_start=date(2027, 3, 1),
            target_tsa_exit=date(2028, 1, 1),
            max_assets_per_wave=capacity,
            weeks_per_wave_gap=2,
        ),
        assets=assets,
        relationships=list(relationships),
        tsa_services=list(tsa_services),
    )


def asset(asset_id, effort_weeks=1, build_effort_weeks=0, tsa_id=None):
    return Asset(
        id=asset_id,
        name=asset_id,
        type=AssetType.APPLICATION,
        owner=Owner.CARVED_OUT,
        criticality=3,
        build_effort_weeks=build_effort_weeks,
        effort_weeks=effort_weeks,
        tsa_id=tsa_id,
    )


def dependency(source, target):
    return Relationship(source=source, target=target, type=RelType.CALLS)


def wave_by_asset(result):
    return {
        asset_id: wave["wave"]
        for wave in result["waves"]
        for asset_id in wave["assets"]
    }


def test_dependencies_are_scheduled_before_consumers():
    portfolio = make_portfolio(
        [asset("APP-A"), asset("DB-B")], [dependency("APP-A", "DB-B")]
    )

    result = compute_waves(portfolio)

    assert wave_by_asset(result)["DB-B"] < wave_by_asset(result)["APP-A"]


def test_cycle_is_kept_in_one_wave():
    portfolio = make_portfolio(
        [asset("APP-A"), asset("APP-B")],
        [dependency("APP-A", "APP-B"), dependency("APP-B", "APP-A")],
    )

    result = compute_waves(portfolio)

    assert wave_by_asset(result)["APP-A"] == wave_by_asset(result)["APP-B"]
    assert result["cycles"] == [["APP-A", "APP-B"]]


def test_tsa_retained_service_exits_after_its_consumers():
    portfolio = make_portfolio(
        [asset("APP-A"), asset("APP-B", tsa_id="TSA-1")],
        [dependency("APP-A", "APP-B")],
        [TSAService(
            id="TSA-1", service="Shared platform", start_date=date(2027, 1, 1),
            end_date=date(2027, 12, 31), monthly_cost=1000,
        )],
    )

    result = compute_waves(
        portfolio,
        strategies=[{"asset_id": "APP-B", "strategy": "retain_under_tsa"}],
    )

    assert wave_by_asset(result)["APP-A"] < wave_by_asset(result)["APP-B"]


def test_wave_gap_starts_after_previous_wave_completion():
    portfolio = make_portfolio(
        [asset("APP-A"), asset("DB-B", effort_weeks=3)],
        [dependency("APP-A", "DB-B")],
    )

    result = compute_waves(portfolio)
    first, second = result["waves"]

    assert first["planned_completion"] == "2027-03-22"
    assert second["planned_start"] == "2027-04-05"


def test_wave_capacity_splits_independent_components():
    portfolio = make_portfolio(
        [asset("APP-A"), asset("APP-B"), asset("APP-C")], capacity=2
    )

    result = compute_waves(portfolio)

    assert len(result["waves"]) == 2
    assert all(len(wave["assets"]) <= 2 for wave in result["waves"])


def test_build_effort_weeks_delays_wave_start_and_triggers_target_tsa_exit_missed():
    # day1 = 2027-01-01; build_effort_weeks=60 -> 2028-02-25 > target_tsa_exit (2028-01-01)
    portfolio = make_portfolio([asset("APP-A", effort_weeks=2, build_effort_weeks=60)])

    result = compute_waves(portfolio)

    assert result["waves"][0]["planned_start"] == "2028-02-25"
    assert result["waves"][0]["planned_completion"] == "2028-03-10"
    assert any(c["type"] == "target_tsa_exit_missed" for c in result["conflicts"])


def test_three_asset_cycle_is_kept_in_one_wave():
    portfolio = make_portfolio(
        [asset("APP-A"), asset("APP-B"), asset("APP-C")],
        [dependency("APP-A", "APP-B"), dependency("APP-B", "APP-C"), dependency("APP-C", "APP-A")],
    )

    result = compute_waves(portfolio)

    waves = wave_by_asset(result)
    assert waves["APP-A"] == waves["APP-B"] == waves["APP-C"]
    assert result["cycles"] == [["APP-A", "APP-B", "APP-C"]]


def test_multiple_cycles_are_each_grouped():
    portfolio = make_portfolio(
        [asset("A1"), asset("A2"), asset("B1"), asset("B2")],
        [
            dependency("A1", "A2"), dependency("A2", "A1"),
            dependency("B1", "B2"), dependency("B2", "B1"),
            dependency("B1", "A1"),
        ],
    )

    result = compute_waves(portfolio)

    waves = wave_by_asset(result)
    assert waves["A1"] == waves["A2"]
    assert waves["B1"] == waves["B2"]
    assert waves["A1"] < waves["B1"]
    assert result["cycles"] == [["A1", "A2"], ["B1", "B2"]]


def test_empty_graph_and_isolated_asset():
    empty = make_portfolio([])
    empty_res = compute_waves(empty)
    assert empty_res["waves"] == []
    assert empty_res["cycles"] == []
    assert empty_res["conflicts"] == []

    isolated = make_portfolio([asset("APP-ISO")])
    iso_res = compute_waves(isolated)
    assert len(iso_res["waves"]) == 1
    assert iso_res["waves"][0]["assets"] == ["APP-ISO"]


def test_retain_to_retain_dependency_respects_reversed_order():
    # APP-14 (retain) depends on APP-01 (retain), which depends on INF-01 (retain)
    portfolio = make_portfolio(
        [asset("APP-14"), asset("APP-01"), asset("INF-01")],
        [dependency("APP-14", "APP-01"), dependency("APP-01", "INF-01")],
    )
    strategies = [
        {"asset_id": "APP-14", "strategy": "retain_under_tsa"},
        {"asset_id": "APP-01", "strategy": "retain_under_tsa"},
        {"asset_id": "INF-01", "strategy": "retain_under_tsa"},
    ]

    result = compute_waves(portfolio, strategies=strategies)

    waves = wave_by_asset(result)
    assert waves["APP-14"] <= waves["APP-01"] <= waves["INF-01"]
