import csv
from datetime import date
from pathlib import Path

from carveout.loader import load_portfolio
from carveout.metrics import calculate_metrics
from carveout.sensitivity import run_sensitivity
from carveout.sequencing import compute_waves
from carveout.strategy import assess_strategies


ROOT = Path(__file__).resolve().parents[1]


def test_sensitivity_is_deterministic_and_base_matches_run_all(tmp_path):
    portfolio = load_portfolio(ROOT / "data/portfolio_v1.yaml")
    strategies = assess_strategies(portfolio, ROOT / "config/strategy_rules.yaml")
    constraints = ROOT / "config/constraints.yaml"

    out1 = tmp_path / "s1"
    out2 = tmp_path / "s2"
    res1 = run_sensitivity(portfolio, constraints, strategies, out1)
    res2 = run_sensitivity(portfolio, constraints, strategies, out2)

    assert res1 == res2
    assert (out1 / "sensitivity.csv").read_text(encoding="utf-8") == (out2 / "sensitivity.csv").read_text(encoding="utf-8")
    assert (out1 / "sensitivity.md").read_text(encoding="utf-8") == (out2 / "sensitivity.md").read_text(encoding="utf-8")

    # Base scenario must match run-all waves & metrics exactly
    base_seq = compute_waves(portfolio, constraints, strategies)
    base_metrics = calculate_metrics(portfolio, base_seq)
    base_row = next(row for row in res1["scenarios"] if row["scenario"] == "base")
    assert base_row["wave_count"] == base_metrics["wave_count"]
    assert base_row["latest_planned_completion"] == base_metrics["latest_planned_completion"]
    assert base_row["estimated_tsa_cost_total"] == base_metrics["estimated_tsa_cost_total"]
    assert base_row["conflict_count"] == len(base_seq["conflicts"])
    expected_margin = (portfolio.planning.target_tsa_exit - date.fromisoformat(base_metrics["latest_planned_completion"])).days
    assert base_row["margin_to_target_days"] == expected_margin

    # Verify all 6 scenarios and Monte Carlo stats exist in CSV and MD
    with (out1 / "sensitivity.csv").open(encoding="utf-8-sig") as f:
        csv_rows = list(csv.DictReader(f))
    assert len(csv_rows) == 6
    mc = res1["monte_carlo"]
    assert mc["trials"] == 1000
    assert mc["p50_completion"] <= mc["p80_completion"]
    assert 0.0 <= mc["target_exit_probability_percent"] <= 100.0
    assert sum(mc["conflict_count_distribution"].values()) == 1000
