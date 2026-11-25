from pathlib import Path
import csv
import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from carveout.dashboard import export_dashboard
from carveout.evaluate import evaluate_results, evaluate_robustness
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
    arguments = (prompt, {"known_non_asset_ids": []}, {"APP-01"}, {1}, log_name, tmp_path / "logs")
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


def test_evaluate_matches_risks_by_theme_and_scans_markdown_hallucinations(tmp_path):
    portfolio = load_portfolio(ROOT / "data/portfolio_v1.yaml")
    strategies = assess_strategies(portfolio, ROOT / "config/strategy_rules.yaml")
    sequencing = compute_waves(portfolio, ROOT / "config/constraints.yaml", strategies)
    # Give generated risks completely different IDs (X-99) to prove matching is not by ID
    risks = [{
        "id": "X-99",
        "risk": "ERP separation misses TSA-01 end date.",
        "cause": "Shared ERP and data.",
        "asset_ids": ["APP-01", "DB-01"],
    }]
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "separation_plan.md").write_text("Mentions ghost asset APP-999 and TSA-01.", encoding="utf-8")

    summary = evaluate_results(
        portfolio, ROOT / "data/expert_plan_v1.yaml", strategies, sequencing, risks,
        tmp_path / "eval", docs_dir=docs_dir,
    )

    assert summary["risk_coverage_percent"] > 0
    assert summary["hallucination_count"] == 1
    assert summary["hallucination_assets"] == ["APP-999"]


def test_dashboard_tracks_pipeline_data_and_has_svg_arrowheads(tmp_path):
    portfolio = load_portfolio(ROOT / "data/portfolio_v1.yaml")
    strategies = assess_strategies(portfolio, ROOT / "config/strategy_rules.yaml")
    sequencing = compute_waves(portfolio, ROOT / "config/constraints.yaml", strategies)
    metrics = calculate_metrics(portfolio, sequencing)
    risks = build_risk_register(portfolio, sequencing)

    dash_path = export_dashboard(portfolio, strategies, sequencing, metrics, risks, tmp_path / "dashboard.html")
    html = dash_path.read_text(encoding="utf-8")

    assert '"marker"' in html
    assert "marker-end" in html
    assert metrics["latest_planned_completion"] in html

    # Mutate effort_weeks on INF-01 and verify dashboard updates dynamically
    for asset in portfolio.assets:
        if asset.id == "INF-01":
            asset.effort_weeks = 20
    seq2 = compute_waves(portfolio, ROOT / "config/constraints.yaml", strategies)
    metrics2 = calculate_metrics(portfolio, seq2)
    risks2 = build_risk_register(portfolio, seq2)
    dash2 = export_dashboard(portfolio, strategies, seq2, metrics2, risks2, tmp_path / "dashboard2.html").read_text(encoding="utf-8")

    assert metrics2["latest_planned_completion"] != metrics["latest_planned_completion"]
    assert metrics2["latest_planned_completion"] in dash2


# ── Commit 1: exit_strategy field ──────────────────────────────────────────

def test_exit_strategy_in_strategy_decisions():
    """assess_strategies must include exit_strategy for every retain_under_tsa asset."""
    portfolio = load_portfolio(ROOT / "data/portfolio_v1.yaml")
    strategies = assess_strategies(portfolio, ROOT / "config/strategy_rules.yaml")
    retain_decisions = [d for d in strategies if d["strategy"] == "retain_under_tsa"]
    assert retain_decisions, "Expected at least one retain_under_tsa asset"
    missing = [d["asset_id"] for d in retain_decisions if "exit_strategy" not in d]
    assert not missing, f"Missing exit_strategy in decisions for: {missing}"


def test_exit_strategy_missing_raises_value_error(tmp_path):
    """An asset with retain_under_tsa and no exit_strategy must raise ValueError."""
    import yaml
    from carveout.loader import load_portfolio as _load
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(
        "planning:\n"
        "  company: Test\n"
        "  carve_out_description: test\n"
        "  day1: 2027-01-04\n"
        "  cutover_start: 2027-03-01\n"
        "  target_tsa_exit: 2027-12-31\n"
        "assets:\n"
        "  - {id: X-01, name: X, type: application, owner: shared, criticality: 3, users: 0}\n"
        "relationships: []\n",
        encoding="utf-8",
    )
    portfolio = _load(bad_yaml)
    # Inject a retain_under_tsa rule that covers X-01 without exit_strategy
    import types, yaml as _yaml
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        "rules:\n"
        "  - name: retain_x\n"
        "    asset_ids: [X-01]\n"
        "    strategy: retain_under_tsa\n"
        "    reason: test\n"
        "    confidence: 0.9\n"
        "default:\n"
        "  strategy: migrate\n"
        "  reason: default\n"
        "  confidence: 0.5\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="exit_strategy"):
        assess_strategies(portfolio, rules_path)


def test_separation_plan_contains_exit_strategy_column(tmp_path):
    """separation_plan.md must have an 'Exit Strategy' column with values for retained assets."""
    portfolio = load_portfolio(ROOT / "data/portfolio_v1.yaml")
    strategies = assess_strategies(portfolio, ROOT / "config/strategy_rules.yaml")
    sequencing = compute_waves(portfolio, ROOT / "config/constraints.yaml", strategies)
    metrics = calculate_metrics(portfolio, sequencing)
    generate_documents(portfolio, strategies, sequencing, metrics, tmp_path)

    plan = (tmp_path / "separation_plan.md").read_text(encoding="utf-8")
    assert "Exit Strategy" in plan
    # Verify at least one exit_strategy value appears (e.g. rebuild or migrate)
    assert any(
        d.get("exit_strategy") and d["exit_strategy"] in plan
        for d in strategies
        if d["strategy"] == "retain_under_tsa"
    )


def test_runbook_shows_exit_strategy_for_retained_assets(tmp_path):
    """Runbooks for retain_under_tsa assets must display 'post-TSA exit strategy'."""
    portfolio = load_portfolio(ROOT / "data/portfolio_v1.yaml")
    strategies = assess_strategies(portfolio, ROOT / "config/strategy_rules.yaml")
    sequencing = compute_waves(portfolio, ROOT / "config/constraints.yaml", strategies)
    metrics = calculate_metrics(portfolio, sequencing)
    generate_documents(portfolio, strategies, sequencing, metrics, tmp_path)

    # APP-01 is retain_under_tsa with exit_strategy: rebuild
    tsa_wave_num = next(w["wave"] for w in sequencing["waves"] if "APP-01" in w["assets"])
    runbook = (tmp_path / "runbooks" / f"wave-{tsa_wave_num:02d}.md").read_text(encoding="utf-8")
    assert "post-TSA exit strategy" in runbook
    assert "rebuild" in runbook


# ── Commit 2: enhanced risk register ──────────────────────────────────────

def test_risk_register_near_miss_tsa_margin(tmp_path):
    """build_risk_register must generate a near-miss risk when margin < 45 days."""
    from datetime import date, timedelta
    from carveout.models import Portfolio, Planning, Asset, TSAService, AssetType, Owner

    today = date(2027, 3, 1)
    tsa_end = date(2027, 6, 1)
    # planned_completion = tsa_end - 20 days → margin = 20 days < 45 → triggers risk
    completion = tsa_end - timedelta(days=20)

    portfolio = Portfolio(
        planning=Planning(
            company="Test", carve_out_description="test",
            day1=date(2027, 1, 4), cutover_start=today,
            target_tsa_exit=date(2027, 12, 31),
        ),
        assets=[Asset(
            id="A-01", name="Test App", type=AssetType.APPLICATION,
            owner=Owner.SHARED, criticality=3, users=0,
            tsa_id="TSA-X", effort_weeks=2, exit_strategy="migrate",
        )],
        relationships=[],
        tsa_services=[TSAService(
            id="TSA-X", service="test service", start_date=date(2027, 1, 4),
            end_date=tsa_end, monthly_cost=10000, extendable=False,
        )],
    )
    # Fake waves_result with no conflicts and correct asset_completion_dates
    waves_result = {
        "waves": [{
            "wave": 1,
            "assets": ["A-01"],
            "planned_start": today.isoformat(),
            "planned_completion": completion.isoformat(),
            "asset_completion_dates": {"A-01": completion.isoformat()},
            "depends_on_waves": [],
            "conflicts": [],
        }],
        "conflicts": [],
    }
    risks = build_risk_register(portfolio, waves_result)
    near_miss = [r for r in risks if "20 days" in r["risk"] or "margin" in r["cause"].lower()]
    assert near_miss, f"Expected a near-miss risk, got: {[r['risk'] for r in risks]}"
    assert any("A-01" in r["asset_ids"] for r in near_miss)
    # Margin must be cited
    assert any("20" in r["risk"] for r in near_miss)


def test_risk_register_non_extendable_tsa(tmp_path):
    """build_risk_register must flag non-extendable TSA with linked assets."""
    from datetime import date
    from carveout.models import Portfolio, Planning, Asset, TSAService, AssetType, Owner

    portfolio = Portfolio(
        planning=Planning(
            company="Test", carve_out_description="test",
            day1=date(2027, 1, 4), cutover_start=date(2027, 3, 1),
            target_tsa_exit=date(2027, 12, 31),
        ),
        assets=[Asset(
            id="B-01", name="B App", type=AssetType.APPLICATION,
            owner=Owner.SHARED, criticality=3, users=0,
            tsa_id="TSA-NE", effort_weeks=2, exit_strategy="migrate",
        )],
        relationships=[],
        tsa_services=[TSAService(
            id="TSA-NE", service="non-ext service", start_date=date(2027, 1, 4),
            end_date=date(2027, 12, 31), monthly_cost=5000, extendable=False,
        )],
    )
    completion = date(2027, 6, 1)
    waves_result = {
        "waves": [{
            "wave": 1, "assets": ["B-01"],
            "planned_start": date(2027, 3, 1).isoformat(),
            "planned_completion": completion.isoformat(),
            "asset_completion_dates": {"B-01": completion.isoformat()},
            "depends_on_waves": [], "conflicts": [],
        }],
        "conflicts": [],
    }
    risks = build_risk_register(portfolio, waves_result)
    non_ext_risks = [r for r in risks if "non-extendable" in r["risk"].lower() or "TSA-NE" in r["risk"]]
    assert non_ext_risks, f"Expected non-extendable TSA risk, got: {[r['risk'] for r in risks]}"
    assert any("B-01" in r["asset_ids"] for r in non_ext_risks)


def test_risk_register_non_transferable_licence(tmp_path):
    """build_risk_register must flag non-transferable licences on non-retired assets."""
    from datetime import date
    from carveout.models import Portfolio, Planning, Asset, Licence, AssetType, Owner

    portfolio = Portfolio(
        planning=Planning(
            company="Test", carve_out_description="test",
            day1=date(2027, 1, 4), cutover_start=date(2027, 3, 1),
            target_tsa_exit=date(2027, 12, 31),
        ),
        assets=[Asset(
            id="C-01", name="C App", type=AssetType.APPLICATION,
            owner=Owner.CARVED_OUT, criticality=3, users=0,
            licence_id="LIC-NT", effort_weeks=2,
        )],
        relationships=[],
        licences=[Licence(
            id="LIC-NT", vendor="TestVendor", product="Test Product",
            end_date=date(2028, 12, 31), transferable=False,
            annual_cost=50000, notice_period_days=90,
        )],
    )
    waves_result = {
        "waves": [{
            "wave": 1, "assets": ["C-01"],
            "planned_start": date(2027, 3, 1).isoformat(),
            "planned_completion": date(2027, 4, 1).isoformat(),
            "asset_completion_dates": {"C-01": date(2027, 4, 1).isoformat()},
            "depends_on_waves": [], "conflicts": [],
        }],
        "conflicts": [],
    }
    risks = build_risk_register(portfolio, waves_result)
    lic_risks = [r for r in risks if "LIC-NT" in r["risk"]]
    assert lic_risks, f"Expected non-transferable licence risk, got: {[r['risk'] for r in risks]}"
    assert any("C-01" in r["asset_ids"] for r in lic_risks)
    assert any("90" in r["mitigation"] for r in lic_risks)


def test_risk_register_no_duplicate_with_conflict(tmp_path):
    """When a conflict already covers a TSA, non-extendable TSA risk must NOT be duplicated."""
    from datetime import date
    from carveout.models import Portfolio, Planning, Asset, TSAService, AssetType, Owner

    portfolio = Portfolio(
        planning=Planning(
            company="Test", carve_out_description="test",
            day1=date(2027, 1, 4), cutover_start=date(2027, 3, 1),
            target_tsa_exit=date(2027, 12, 31),
        ),
        assets=[Asset(
            id="D-01", name="D App", type=AssetType.APPLICATION,
            owner=Owner.SHARED, criticality=3, users=0,
            tsa_id="TSA-DUP", effort_weeks=2, exit_strategy="migrate",
        )],
        relationships=[],
        tsa_services=[TSAService(
            id="TSA-DUP", service="dup service", start_date=date(2027, 1, 4),
            end_date=date(2027, 6, 30), monthly_cost=5000, extendable=False,
        )],
    )
    # Conflict already covers TSA-DUP
    waves_result = {
        "waves": [{
            "wave": 1, "assets": ["D-01"],
            "planned_start": date(2027, 3, 1).isoformat(),
            "planned_completion": date(2027, 8, 1).isoformat(),
            "asset_completion_dates": {"D-01": date(2027, 8, 1).isoformat()},
            "depends_on_waves": [], "conflicts": [],
        }],
        "conflicts": [{
            "type": "tsa_ends_before_cutover",
            "asset_id": "D-01",
            "tsa_id": "TSA-DUP",
            "tsa_end": "2027-06-30",
            "planned_completion": "2027-08-01",
        }],
    }
    risks = build_risk_register(portfolio, waves_result)
    tsa_dup_risks = [r for r in risks if "TSA-DUP" in r["risk"]]
    # Only the conflict-driven risk should appear, not the structural non-extendable one too
    assert len(tsa_dup_risks) == 1, f"Expected exactly 1 TSA-DUP risk, got {len(tsa_dup_risks)}"
