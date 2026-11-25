import csv
from datetime import date
from pathlib import Path

from carveout.loader import load_portfolio
from carveout.metrics import calculate_metrics
from carveout.sensitivity import compute_critical_path, run_sensitivity
from carveout.sequencing import compute_waves
from carveout.strategy import assess_strategies


ROOT = Path(__file__).resolve().parents[1]


def test_critical_path_and_tornado_sorted_descending(tmp_path):
    portfolio = load_portfolio(ROOT / "data/portfolio_v1.yaml")
    strategies = assess_strategies(portfolio, ROOT / "config/strategy_rules.yaml")
    constraints = ROOT / "config/constraints.yaml"

    result = compute_critical_path(portfolio, constraints, strategies, output_dir=tmp_path)
    tornado = result["tornado"]
    assert len(tornado) == len(portfolio.assets)
    # Must be sorted by impact_days descending
    impacts = [row["impact_days"] for row in tornado]
    assert impacts == sorted(impacts, reverse=True)
    assert any(row["impact_days"] > 0 for row in tornado)
    # Critical path assets must be ordered by wave ascending
    cp_waves = [row["wave"] for row in result["critical_path"]]
    assert cp_waves == sorted(cp_waves)

    cp_md = (tmp_path / "critical_path.md").read_text(encoding="utf-8")
    assert "# Critical path and tornado analysis" in cp_md
    assert "## Tornado analysis" in cp_md


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

    # Verify all scenarios and 4 Monte Carlo variants exist in CSV and MD
    with (out1 / "sensitivity.csv").open(encoding="utf-8-sig") as f:
        csv_rows = list(csv.DictReader(f))
    assert len(csv_rows) == 9
    mc = res1["monte_carlo"]
    assert mc["trials"] == 1000
    assert mc["p50_completion"] <= mc["p80_completion"] <= mc["p90_completion"]
    assert 0.0 <= mc["target_exit_probability_percent"] <= 100.0
    assert sum(mc["conflict_count_distribution"].values()) == 1000

    variants = res1["monte_carlo_variants"]
    assert len(variants) == 4
    assert {(v["variant"], v["law"]) for v in variants} == {
        ("global", "skewed (0.8, 1.0, 1.5)"),
        ("global", "symmetric (0.9, 1.0, 1.1)"),
        ("per_asset", "skewed (0.8, 1.0, 1.5)"),
        ("per_asset", "symmetric (0.9, 1.0, 1.1)"),
    }
    md_text = (out1 / "sensitivity.md").read_text(encoding="utf-8")
    assert "| Variante | Loi | Moyenne | P50 | P80 | P90 |" in md_text
