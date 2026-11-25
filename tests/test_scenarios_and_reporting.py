"""Tests for Phase 4 what-if scenarios, report generation, and CLI subcommands."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
import pytest

from carveout.decision_report import export_report_json, export_report_markdown, generate_decision_report
from carveout.loader import load_portfolio
from carveout.scenarios_manager import WhatIfScenarioConfig, run_what_if_scenario

PORTFOLIO = Path("data/portfolio_v1.yaml")
RULES = Path("config/strategy_rules.yaml")
CONSTRAINTS = Path("config/constraints.yaml")


def test_what_if_scenario_isolation_and_yaml_immutability():
    initial_bytes = PORTFOLIO.read_bytes()

    cfg = WhatIfScenarioConfig(
        scenario_id="test_delay_inf01",
        scenario_name="Test Delay INF-01",
        description="Delay INF-01 by 8 weeks",
        delay_weeks={"INF-01": 8},
        tsa_rate_multiplier=1.2,
    )

    p_before = load_portfolio(PORTFOLIO)
    res = run_what_if_scenario(p_before, cfg, rules_path=RULES, constraints_path=CONSTRAINTS)
    p_after = load_portfolio(PORTFOLIO)

    post_bytes = PORTFOLIO.read_bytes()
    assert initial_bytes == post_bytes, "Original portfolio YAML file was modified!"
    assert [t.monthly_cost for t in p_before.tsa_services] == [t.monthly_cost for t in p_after.tsa_services], "Portfolio in-memory models were mutated!"
    assert res.solver_status in ("OPTIMAL", "FEASIBLE")
    assert res.total_waves > 0
    assert res.scenario_tsa_cost > 0


def test_generate_and_export_decision_reports(tmp_path: Path):
    p = load_portfolio(PORTFOLIO)
    report = generate_decision_report(p, rules_path=RULES, constraints_path=CONSTRAINTS)

    assert report.company == "Nordia Retail"
    assert len(report.wave_explanations) == len(p.assets)

    # Test Markdown export
    md_file = tmp_path / "decision_report.md"
    export_report_markdown(report, md_file)
    assert md_file.exists()
    content_md = md_file.read_text(encoding="utf-8")
    assert "# IT Separation Decision & Planning Report" in content_md
    assert "Nordia Retail" in content_md
    assert "Executive Summary & Plan Comparison" in content_md

    # Test JSON export
    json_file = tmp_path / "decision_report.json"
    export_report_json(report, json_file)
    assert json_file.exists()
    raw = json.loads(json_file.read_text(encoding="utf-8"))
    assert raw["company"] == "Nordia Retail"
    assert "plan_comparison" in raw


def test_cli_explain_command():
    proc = subprocess.run(
        [sys.executable, "-m", "carveout.cli", "explain", "APP-06"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "ASSET PLANNING EXPLANATION: APP-06" in proc.stdout
    assert "Participating SCC  : APP-06, APP-07" in proc.stdout


def test_cli_compare_command():
    proc = subprocess.run(
        [sys.executable, "-m", "carveout.cli", "compare", "--scenario", "minimize_cost"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "PLAN COMPARISON: BASELINE vs OPTIMIZED" in proc.stdout
    assert "TSA Cost" in proc.stdout


def test_cli_scenario_command():
    proc = subprocess.run(
        [
            sys.executable,
            "-m", "carveout.cli",
            "scenario",
            "--delay-asset", "APP-06",
            "--delay-weeks", "12",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "WHAT-IF SCENARIO:" in proc.stdout
    assert "Solver Status     :" in proc.stdout
