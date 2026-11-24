from pathlib import Path

import pytest

from carveout.evaluate import evaluate_robustness
from carveout.generation.documents import generate_documents
from carveout.generation.guardrails import validate_document_references
from carveout.loader import load_portfolio
from carveout.metrics import calculate_metrics
from carveout.sequencing import compute_waves
from carveout.strategy import assess_strategies


ROOT = Path(__file__).resolve().parents[1]


def test_document_guardrail_rejects_unknown_asset():
    with pytest.raises(ValueError, match="UNKNOWN-99"):
        validate_document_references(
            {"asset_ids": ["UNKNOWN-99"], "wave_numbers": [1]},
            {"APP-01"},
            {1},
        )


def test_template_generation_writes_core_deliverables(tmp_path):
    portfolio = load_portfolio(ROOT / "data/portfolio_v2.yaml")
    strategies = assess_strategies(portfolio, ROOT / "config/strategy_rules.yaml")
    sequencing = compute_waves(portfolio, ROOT / "config/constraints.yaml", strategies)
    metrics = calculate_metrics(portfolio, sequencing)

    written = generate_documents(portfolio, strategies, sequencing, metrics, tmp_path)

    assert (tmp_path / "separation_plan.md").is_file()
    assert (tmp_path / "risk_register.csv").is_file()
    assert (tmp_path / "tsa_exit_schedule.csv").is_file()
    assert all(path.is_file() for path in written)
    assert all((tmp_path / "runbooks" / f"wave-{wave['wave']:02d}.md").is_file()
               for wave in sequencing["waves"])


def test_modified_portfolio_satisfies_robustness_invariants():
    portfolio = load_portfolio(ROOT / "data/portfolio_v2.yaml")
    sequencing = compute_waves(portfolio, ROOT / "config/constraints.yaml")

    result = evaluate_robustness(portfolio, sequencing)

    assert result["dependency_violations"] == 0
    assert result["all_assets_scheduled"]
    assert result["cycles_grouped"]
