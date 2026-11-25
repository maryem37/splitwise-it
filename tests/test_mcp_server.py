import asyncio
import json
import os
from pathlib import Path
import sys

import pytest

from carveout.mcp_server import (
    asset_dependencies,
    compute_plan,
    list_assets,
    portfolio_summary,
)


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def reference_portfolio(monkeypatch):
    monkeypatch.setenv("CARVEOUT_PORTFOLIO", str(ROOT / "data" / "portfolio_v1.yaml"))
    monkeypatch.setenv("CARVEOUT_RULES", str(ROOT / "config" / "strategy_rules.yaml"))
    monkeypatch.setenv("CARVEOUT_CONSTRAINTS", str(ROOT / "config" / "constraints.yaml"))


def test_portfolio_summary_reports_input_counts(reference_portfolio):
    summary = portfolio_summary()

    assert summary["counts"]["assets"] == 30
    assert summary["counts"]["relationships"] == 61
    assert summary["planning"]["target_tsa_exit"] == "2027-12-31"


def test_list_assets_filters_by_type_owner_and_sensitivity(reference_portfolio):
    assets = list_assets(asset_type="datastore", owner="carved_out", sensitive_only=True)

    assert assets
    assert all(
        asset["type"] == "datastore"
        and asset["owner"] == "carved_out"
        and asset["sensitive"]
        for asset in assets
    )


def test_asset_dependencies_reports_prerequisites_and_dependants(reference_portfolio):
    result = asset_dependencies("DB-01")

    assert "INF-01" in result["depends_on"]
    assert "APP-01" in result["depended_on_by"]


def test_compute_plan_returns_deterministic_results(reference_portfolio):
    result = compute_plan()

    assert result["metrics"]["wave_count"] == len(result["waves"])
    assert result["cycles"]


def test_list_assets_rejects_unknown_filter():
    with pytest.raises(ValueError, match="Unknown asset type"):
        list_assets(asset_type="service")


def test_stdio_server_advertises_read_only_tools():
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def inspect_server():
        env = os.environ.copy()
        env["CARVEOUT_PORTFOLIO"] = str(ROOT / "data" / "portfolio_v1.yaml")
        env["CARVEOUT_RULES"] = str(ROOT / "config" / "strategy_rules.yaml")
        env["CARVEOUT_CONSTRAINTS"] = str(ROOT / "config" / "constraints.yaml")
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "carveout.mcp_server"],
            env=env,
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                assert names == {
                    "portfolio_summary",
                    "list_assets",
                    "asset_dependencies",
                    "compute_plan",
                }
                summary_result = await session.call_tool("portfolio_summary", {})
                assert not summary_result.isError
                summary = json.loads(summary_result.content[0].text)
                assert summary["counts"]["assets"] == 30

                assets_result = await session.call_tool(
                    "list_assets",
                    {"asset_type": "datastore", "owner": "carved_out", "sensitive_only": True},
                )
                assert not assets_result.isError
                assets = [json.loads(item.text) for item in assets_result.content]
                assert assets
                assert all(asset["sensitive"] for asset in assets)

                dependency_result = await session.call_tool(
                    "asset_dependencies", {"asset_id": "DB-01"}
                )
                assert not dependency_result.isError
                dependency_data = json.loads(dependency_result.content[0].text)
                assert "APP-01" in dependency_data["depended_on_by"]

                plan_result = await session.call_tool("compute_plan", {})
                assert not plan_result.isError
                plan = json.loads(plan_result.content[0].text)
                assert plan["metrics"]["wave_count"] == len(plan["waves"])

    asyncio.run(inspect_server())
