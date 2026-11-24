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


def asset(asset_id, effort_weeks=1, tsa_id=None):
    return Asset(
        id=asset_id,
        name=asset_id,
        type=AssetType.APPLICATION,
        owner=Owner.CARVED_OUT,
        criticality=3,
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
