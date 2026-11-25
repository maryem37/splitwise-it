from pathlib import Path
import csv
import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from carveout.evaluate import evaluate_robustness
from carveout.generation.documents import build_risk_register, generate_documents
from carveout.generation.client import generate_narrative
from carveout.generation import client as groq_client
from carveout.generation.guardrails import validate_document_references, validate_narrative_content
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
        "rate_limit",
        {"narrative": "References APP-999.", "referenced_asset_ids": ["APP-999"],
         "referenced_wave_numbers": [1]},
        {"narrative": "The cutover follows its dependencies.", "referenced_asset_ids": ["APP-01"],
         "referenced_wave_numbers": [1]},
    ]
    calls = []
    sleeps = []

    class FakeRateLimitError(Exception):
        def __init__(self, message):
            super().__init__(message)
            self.response = SimpleNamespace(headers={"retry-after": "0.01"})

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            result = responses.pop(0)
            if result == "rate_limit":
                raise FakeRateLimitError("429 rate limit")
            content = json.dumps(result)
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=content)
            )])

    class FakeGroq:
        def __init__(self, api_key, max_retries):
            assert api_key == "test-key"
            assert max_retries == 0
            self.chat = SimpleNamespace(completions=FakeCompletions())

    groq_module = ModuleType("groq")
    groq_module.Groq = FakeGroq
    groq_module.RateLimitError = FakeRateLimitError
    dotenv_module = ModuleType("dotenv")
    dotenv_module.load_dotenv = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "groq", groq_module)
    monkeypatch.setitem(sys.modules, "dotenv", dotenv_module)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_MODEL", "test-model")
    monkeypatch.setattr(groq_client.time, "sleep", sleeps.append)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Return a JSON narrative.", encoding="utf-8")

    log_name = f"test-groq-{tmp_path.name}"
    arguments = (prompt, {"known_non_asset_ids": []}, {"APP-01"}, {1}, log_name)
    narrative = generate_narrative(*arguments)

    assert narrative == "The cutover follows its dependencies."
    assert len(calls) == 3
    assert sleeps == [0.1]
    assert calls[0]["temperature"] == 0
    assert calls[0]["response_format"]["type"] == "json_schema"
    assert calls[0]["response_format"]["json_schema"]["strict"] is True
    assert "unknown assets" in calls[2]["messages"][1]["content"]
    assert generate_narrative(*arguments) == narrative
    assert len(calls) == 3  # A rerun reuses the validated narrative from the logs.


def test_tsa_exit_schedule_uses_last_asset_and_cleans_stale_runbooks_and_csv_semicolons(tmp_path):
    portfolio = load_portfolio(ROOT / "data/portfolio_v1.yaml")
    strategies = assess_strategies(portfolio, ROOT / "config/strategy_rules.yaml")
    sequencing = compute_waves(portfolio, ROOT / "config/constraints.yaml", strategies)
    metrics = calculate_metrics(portfolio, sequencing)

    stale = tmp_path / "runbooks" / "wave-99.md"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("stale", encoding="utf-8")

    generate_documents(portfolio, strategies, sequencing, metrics, tmp_path)

    assert not stale.exists()

    with (tmp_path / "tsa_exit_schedule.csv").open(encoding="utf-8-sig") as stream:
        tsa_rows = {row["tsa_id"]: row for row in csv.DictReader(stream)}
    # TSA-03 is linked to INF-03 (Wave 1) and APP-10 (Wave 2, effort 2w) -> APP-10 asset completion date
    app10_wave = next(w for w in sequencing["waves"] if "APP-10" in w["assets"])
    assert tsa_rows["TSA-03"]["planned_exit"] == app10_wave["asset_completion_dates"]["APP-10"]

    with (tmp_path / "risk_register.csv").open(encoding="utf-8-sig") as stream:
        risk_rows = list(csv.DictReader(stream))
    assert all("[" not in row["asset_ids"] for row in risk_rows)
    assert any(";" in row["asset_ids"] for row in risk_rows)

    risks = build_risk_register(portfolio, sequencing)
    for conflict in sequencing["conflicts"]:
        if "asset_id" in conflict:
            assert any(conflict["asset_id"] in r["asset_ids"] for r in risks)

    missed_seq = {**sequencing, "conflicts": [*sequencing["conflicts"], {
        "type": "target_tsa_exit_missed",
        "target_tsa_exit": "2027-12-31",
        "latest_planned_completion": "2028-02-01",
        "message": "Latest planned completion 2028-02-01 exceeds target TSA exit 2027-12-31.",
    }]}
    missed_risks = build_risk_register(portfolio, missed_seq)
    assert any("target TSA exit" in r["risk"] for r in missed_risks)


def test_runbook_steps_use_strategy_specific_verbs(tmp_path):
    portfolio = load_portfolio(ROOT / "data/portfolio_v1.yaml")
    strategies = assess_strategies(portfolio, ROOT / "config/strategy_rules.yaml")
    sequencing = compute_waves(portfolio, ROOT / "config/constraints.yaml", strategies)
    metrics = calculate_metrics(portfolio, sequencing)

    generate_documents(portfolio, strategies, sequencing, metrics, tmp_path)

    wave1 = (tmp_path / "runbooks" / "wave-01.md").read_text(encoding="utf-8")
    assert "Decommission and retire `INF-05`" in wave1
    assert "Clone and configure `INF-04`" in wave1
    assert "Rebuild and cut over `DB-01`" in wave1
    assert "Migrate and cut over `DB-02`" in wave1

    tsa_wave_num = next(w["wave"] for w in sequencing["waves"] if "APP-01" in w["assets"])
    tsa_wave = (tmp_path / "runbooks" / f"wave-{tsa_wave_num:02d}.md").read_text(encoding="utf-8")
    assert "Exit TSA once all dependents have moved `APP-01`" in tsa_wave


def test_guardrails_reject_ungrounded_claims_and_invented_dates():
    with pytest.raises(ValueError, match="guarantee"):
        validate_narrative_content("Guaranteeing uninterrupted service.")
    with pytest.raises(ValueError, match="uninterrupted"):
        validate_narrative_content("Provides uninterrupted cutover.")
    with pytest.raises(ValueError, match="independent"):
        validate_narrative_content("Each wave is independent of others.")
    with pytest.raises(ValueError, match="agreement"):
        validate_narrative_content("Extend the security agreement before cutover.")
    with pytest.raises(ValueError, match="re-host"):
        validate_narrative_content("Confirm the DB was re-hosted.", has_retired_assets=True)
    with pytest.raises(ValueError, match="final"):
        validate_narrative_content("This is the final wave.", is_final_wave=False)
    with pytest.raises(ValueError, match="2099-01-01"):
        validate_narrative_content("Cutover on 2099-01-01.", known_dates={"2027-03-01"})

    # Valid transitional service agreement and known date pass
    validate_narrative_content(
        "Transitional service agreement ends on 2027-09-30.",
        known_dates={"2027-09-30"},
        has_retired_assets=False,
        is_final_wave=False,
    )
