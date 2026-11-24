from pathlib import Path
import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from carveout.evaluate import evaluate_robustness
from carveout.generation.documents import generate_documents
from carveout.generation.client import generate_narrative
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


def test_groq_narrative_retries_unknown_asset_without_network(tmp_path, monkeypatch):
    responses = [
        {"narrative": "References APP-999.", "referenced_asset_ids": ["APP-999"],
         "referenced_wave_numbers": [1]},
        {"narrative": "The cutover follows its dependencies.", "referenced_asset_ids": ["APP-01"],
         "referenced_wave_numbers": [1]},
    ]
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            content = json.dumps(responses.pop(0))
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=content)
            )])

    class FakeGroq:
        def __init__(self, api_key):
            assert api_key == "test-key"
            self.chat = SimpleNamespace(completions=FakeCompletions())

    groq_module = ModuleType("groq")
    groq_module.Groq = FakeGroq
    dotenv_module = ModuleType("dotenv")
    dotenv_module.load_dotenv = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "groq", groq_module)
    monkeypatch.setitem(sys.modules, "dotenv", dotenv_module)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_MODEL", "test-model")
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Return a JSON narrative.", encoding="utf-8")

    narrative = generate_narrative(
        prompt, {"known_non_asset_ids": []}, {"APP-01"}, {1}, "test-groq"
    )

    assert narrative == "The cutover follows its dependencies."
    assert len(calls) == 2
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert "unknown assets" in calls[1]["messages"][1]["content"]
