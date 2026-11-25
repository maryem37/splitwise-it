"""Build structured separation deliverables from computed portfolio results."""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..graph import build_graph, cycles, dependencies
from ..models import Portfolio
from .client import generate_narrative
from .guardrails import validate_document_references


ROOT = Path(__file__).resolve().parents[3]


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_risk_register(portfolio: Portfolio, waves_result: dict[str, Any]) -> list[dict[str, Any]]:
    asset_by_id = {asset.id: asset for asset in portfolio.assets}
    risks: list[dict[str, Any]] = []
    next_idx = 1

    def _next_id() -> str:
        nonlocal next_idx
        rid = f"R-{next_idx:02d}"
        next_idx += 1
        return rid

    for conflict in waves_result.get("conflicts", []):
        ctype = conflict.get("type")
        if ctype == "licence_expires_before_cutover":
            aid = conflict["asset_id"]
            lic_id = conflict["licence_id"]
            risks.append({
                "id": _next_id(),
                "risk": f"{aid} cutover blocked by {lic_id} licence expiry.",
                "cause": f"{lic_id} expires on {conflict['expiry']} before planned completion {conflict['planned_completion']}.",
                "likelihood": "high",
                "impact": "critical",
                "owner": "Commercial / product owner",
                "mitigation": "Secure a bridge licence or expedite replacement before expiry.",
                "asset_ids": [aid],
            })
        elif ctype in ("tsa_ends_before_cutover", "tsa_extension_required"):
            aid = conflict["asset_id"]
            tsa_id = conflict["tsa_id"]
            hard = ctype == "tsa_ends_before_cutover"
            risks.append({
                "id": _next_id(),
                "risk": f"{aid} misses {tsa_id} end date ({conflict['tsa_end']}).",
                "cause": conflict.get("message", f"{aid} requires {tsa_id} past {conflict['tsa_end']}."),
                "likelihood": "high",
                "impact": "critical" if hard else "high",
                "owner": "TSA / separation lead",
                "mitigation": "Accelerate separation or negotiate a formal TSA extension / contingency.",
                "asset_ids": [aid],
            })
        elif ctype == "target_tsa_exit_missed":
            risks.append({
                "id": _next_id(),
                "risk": f"Programme misses target TSA exit ({conflict['target_tsa_exit']}).",
                "cause": conflict.get("message", "Latest planned completion exceeds target TSA exit."),
                "likelihood": "high",
                "impact": "critical",
                "owner": "Programme manager",
                "mitigation": "Parallelise critical-path build work or re-baseline target TSA exit.",
                "asset_ids": sorted(asset_by_id),
            })
        elif ctype == "cycle_exceeds_wave_capacity":
            members = sorted(conflict.get("assets", []))
            risks.append({
                "id": _next_id(),
                "risk": "Cyclic asset group exceeds wave capacity.",
                "cause": conflict.get("message", "Strongly connected component exceeds max_assets_per_wave."),
                "likelihood": "high",
                "impact": "high",
                "owner": "Application migration lead",
                "mitigation": "Decouple cycle or approve temporary wave capacity exception.",
                "asset_ids": members,
            })

    if any(asset.id == "INF-03" and asset.owner.value == "shared" for asset in portfolio.assets):
        risks.append({"id": _next_id(), "risk": "Shared identity cutover blocks users or applications.",
                      "cause": "INF-03 is a common authentication dependency across the portfolio.",
                      "likelihood": "medium", "impact": "critical", "owner": "Identity lead",
                      "mitigation": "Build target identity in parallel, pilot users, and retain tested rollback.",
                      "asset_ids": ["INF-03"]})
    cycle_groups = cycles(build_graph(portfolio))
    if cycle_groups:
        risks.append({"id": _next_id(), "risk": "A cyclic application cutover leaves inconsistent operations.",
                      "cause": "Mutually dependent applications must move in the same cutover window.",
                      "likelihood": "medium", "impact": "high", "owner": "Application migration lead",
                      "mitigation": "Rehearse a joint move, agree rollback thresholds, and validate both sides together.",
                      "asset_ids": sorted({asset_id for group in cycle_groups for asset_id in group})})
    sensitive_ids = sorted(asset.id for asset in portfolio.assets if asset.sensitive)
    if sensitive_ids:
        risks.append({"id": _next_id(), "risk": "Sensitive data is exposed or corrupted during migration.",
                      "cause": "Personal or financial data crosses the separation boundary.",
                      "likelihood": "medium", "impact": "critical", "owner": "Data protection officer",
                      "mitigation": "Use encryption, least privilege, masked rehearsals, and signed reconciliation evidence.",
                      "asset_ids": sensitive_ids})
    if len(waves_result["waves"]) > 1:
        risks.append({"id": _next_id(), "risk": "Wave capacity or dependency changes delay cutover dates.",
                      "cause": "Dependencies and specialist capacity concentrate work into sequential waves.",
                      "likelihood": "medium", "impact": "high", "owner": "Programme manager",
                      "mitigation": "Reserve specialist capacity and reforecast TSA needs after each wave.",
                      "asset_ids": sorted(asset_by_id)})
    functions: dict[str, list[str]] = {}
    for asset in portfolio.assets:
        if asset.function:
            functions.setdefault(asset.function, []).append(asset.id)
    duplicates = sorted(asset_id for members in functions.values() if len(members) > 1 for asset_id in members)
    if duplicates:
        risks.append({"id": _next_id(), "risk": "CRM consolidation loses customer history or interrupts support.",
                      "cause": "Two systems provide a duplicate CRM function and contain separate records.",
                      "likelihood": "medium", "impact": "medium", "owner": "Commercial systems lead",
                      "mitigation": "Map and deduplicate records, confirm the destination, and get sign-off before retirement.",
                      "asset_ids": duplicates})
    return risks


def generate_documents(
    portfolio: Portfolio,
    strategies: list[dict[str, Any]],
    waves_result: dict[str, Any],
    metrics: dict[str, Any],
    output_dir: str | Path,
    use_ai: bool = False,
) -> list[Path]:
    """Render core Markdown and CSV deliverables from computed JSON only."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    known_assets = {asset.id for asset in portfolio.assets}
    wave_numbers = {wave["wave"] for wave in waves_result["waves"]}
    graph = build_graph(portfolio)
    asset_by_id = {asset.id: asset for asset in portfolio.assets}
    tsa_rows = []
    for service in portfolio.tsa_services:
        linked_ids = {asset.id for asset in portfolio.assets if asset.tsa_id == service.id}
        linked_waves = [wave for wave in waves_result["waves"]
                        if linked_ids.intersection(wave["assets"])]
        completions = [
            date.fromisoformat(wave["asset_completion_dates"][asset_id])
            for wave in linked_waves
            for asset_id in linked_ids.intersection(wave["assets"])
        ]
        latest = max(completions, default=None)
        tsa_rows.append({
            "tsa_id": service.id, "service": service.service,
            "planned_exit": latest.isoformat() if latest else service.start_date.isoformat(),
            "linked_waves": ", ".join(str(wave["wave"]) for wave in linked_waves),
            "monthly_cost": service.monthly_cost,
            "estimated_cost": metrics["estimated_tsa_cost"].get(service.id, 0),
            "overrun_risk": "yes" if latest and latest > service.end_date else "no",
        })
    risks = build_risk_register(portfolio, waves_result)
    all_refs = {"asset_ids": sorted(known_assets), "wave_numbers": sorted(wave_numbers)}
    validate_document_references(all_refs, known_assets, wave_numbers)
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "document_inputs.json").write_text(json.dumps({
        "portfolio": portfolio.model_dump(mode="json"), "strategies": strategies,
        "waves": waves_result, "metrics": metrics, "risks": risks,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape())
    plan = env.get_template("separation_plan.md.j2").render(
        company=portfolio.planning.company, description=portfolio.planning.carve_out_description,
        strategies=strategies, waves=waves_result["waves"], metrics=metrics,
    )
    plan_doc = {"asset_ids": sorted(known_assets), "wave_numbers": sorted(wave_numbers)}
    validate_document_references(plan_doc, known_assets, wave_numbers)
    plan_narrative = ""
    if use_ai:
        plan_narrative = generate_narrative(
            ROOT / "prompts" / "plan_narrative_v1.md",
            {"company": portfolio.planning.company,
             "description": portfolio.planning.carve_out_description,
             "strategies": strategies, "waves": waves_result["waves"], "metrics": metrics,
             "known_non_asset_ids": [item.id for item in portfolio.licences]
             + [item.id for item in portfolio.tsa_services]},
            known_assets, wave_numbers, "plan-narrative",
        )
    (output / "separation_plan.md").write_text(
        plan.replace("## Executive summary", "## Executive summary\n\n" + plan_narrative),
        encoding="utf-8",
    )

    written = [output / "separation_plan.md"]
    strategy_by_id = {item["asset_id"]: item["strategy"] for item in strategies}
    runbooks_dir = output / "runbooks"
    if runbooks_dir.exists():
        for old_runbook in runbooks_dir.glob("wave-*.md"):
            old_runbook.unlink()
    for wave in waves_result["waves"]:
        wave_assets = [asset_by_id[item] for item in wave["assets"]]
        runbook_doc = {"asset_ids": wave["assets"], "wave_numbers": [wave["wave"]]}
        validate_document_references(runbook_doc, known_assets, wave_numbers)
        runbook = env.get_template("cutover_runbook.md.j2").render(
            wave=wave, assets=wave_assets, strategy_by_id=strategy_by_id,
            dependencies={asset_id: dependencies(graph, asset_id) for asset_id in wave["assets"]},
        )
        runbook_path = output / "runbooks" / f"wave-{wave['wave']:02d}.md"
        runbook_path.parent.mkdir(parents=True, exist_ok=True)
        if use_ai:
            retired_ids = [aid for aid in wave["assets"] if strategy_by_id.get(aid) == "retire"]
            narrative = generate_narrative(
                ROOT / "prompts" / "runbook_narrative_v1.md",
                {"wave": wave, "assets": [asset.model_dump(mode="json") for asset in wave_assets],
                 "retired_asset_ids": retired_ids,
                 "is_final_wave": wave["wave"] == max(wave_numbers, default=0),
                 "known_non_asset_ids": [item.id for item in portfolio.licences]
                 + [item.id for item in portfolio.tsa_services]},
                known_assets, wave_numbers, f"runbook-wave-{wave['wave']:02d}",
            )
            runbook = runbook.replace("## Scope", "## Scope\n\n" + narrative)
        runbook_path.write_text(runbook, encoding="utf-8")
        written.append(runbook_path)

    csv_risks = [{**risk, "asset_ids": ";".join(risk["asset_ids"])} for risk in risks]
    _write_csv(output / "risk_register.csv", csv_risks,
               ["id", "risk", "cause", "likelihood", "impact", "owner", "mitigation", "asset_ids"])
    risk_narrative = ""
    if use_ai:
        risk_narrative = generate_narrative(
            ROOT / "prompts" / "risk_narrative_v1.md",
            {"risks": risks,
             "known_non_asset_ids": [item.id for item in portfolio.licences]
             + [item.id for item in portfolio.tsa_services]
             + [item["id"] for item in risks]},
            known_assets, wave_numbers, "risk-register-narrative",
        )
    (output / "risk_register.md").write_text(
        "# Risk register\n\n" + (risk_narrative + "\n\n" if risk_narrative else "") + "\n".join(
            f"## {risk['id']} — {risk['risk']}\n\n- Cause: {risk['cause']}\n- Likelihood: {risk['likelihood']}\n"
            f"- Impact: {risk['impact']}\n- Owner: {risk['owner']}\n- Mitigation: {risk['mitigation']}\n- Assets: {', '.join(risk['asset_ids'])}\n"
            for risk in risks), encoding="utf-8")
    hubs = sorted(graph.in_degree, key=lambda item: (-item[1], item[0]))[:5]
    (output / "dependency_summary.md").write_text(
        "# Dependency summary\n\n## Highest-impact dependencies\n\n" +
        "\n".join(f"- `{asset_id}`: {degree} dependent assets" for asset_id, degree in hubs) +
        "\n\n## Cycles\n\n" + ("\n".join(f"- {', '.join(group)}" for group in cycles(graph)) or "No cycles detected.") + "\n",
        encoding="utf-8")
    _write_csv(output / "tsa_exit_schedule.csv", tsa_rows,
               ["tsa_id", "service", "planned_exit", "linked_waves", "monthly_cost", "estimated_cost", "overrun_risk"])
    written.extend([output / "tsa_exit_schedule.csv", output / "risk_register.csv", output / "risk_register.md", output / "dependency_summary.md"])
    return written
