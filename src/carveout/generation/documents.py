"""Build structured separation deliverables from computed portfolio results."""
from __future__ import annotations

import csv
import hashlib
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


def _stable_risk_id(category: str, asset_ids: list[str], qualifier: str = "") -> str:
    """Derive a deterministic risk ID from its category, qualifier, and sorted assets."""
    key = f"{category}|{qualifier}|{','.join(sorted(asset_ids))}"
    num = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) % 1_000_000
    return f"R-{num:06d}"


def build_risk_register(portfolio: Portfolio, waves_result: dict[str, Any]) -> list[dict[str, Any]]:
    asset_by_id = {asset.id: asset for asset in portfolio.assets}
    risks: list[dict[str, Any]] = []

    # Track (conflict_type_key, entity_id) pairs already covered by conflict-driven risks
    # so the structural/near-miss rules don't generate duplicates.
    covered: set[tuple[str, str]] = set()

    for conflict in waves_result.get("conflicts", []):
        ctype = conflict.get("type")
        if ctype == "licence_expires_before_cutover":
            aid = conflict["asset_id"]
            lic_id = conflict["licence_id"]
            covered.add(("licence", lic_id))
            covered.add(("licence_asset", aid))
            assets = [aid]
            risks.append({
                "id": _stable_risk_id("licence_expires_before_cutover", assets, lic_id),
                "risk": f"{aid} cutover blocked by {lic_id} licence expiry.",
                "cause": f"{lic_id} expires on {conflict['expiry']} before planned completion {conflict['planned_completion']}.",
                "likelihood": "high",
                "impact": "critical",
                "owner": "Commercial / product owner",
                "mitigation": "Secure a bridge licence or expedite replacement before expiry.",
                "asset_ids": assets,
            })
        elif ctype in ("tsa_ends_before_cutover", "tsa_extension_required"):
            aid = conflict["asset_id"]
            tsa_id = conflict["tsa_id"]
            covered.add(("tsa_asset", aid))
            covered.add(("tsa", tsa_id))
            hard = ctype == "tsa_ends_before_cutover"
            assets = [aid]
            risks.append({
                "id": _stable_risk_id("tsa_overrun", assets, tsa_id),
                "risk": f"{aid} misses {tsa_id} end date ({conflict['tsa_end']}).",
                "cause": conflict.get("message", f"{aid} requires {tsa_id} past {conflict['tsa_end']}."),
                "likelihood": "high",
                "impact": "critical" if hard else "high",
                "owner": "TSA / separation lead",
                "mitigation": "Accelerate separation or negotiate a formal TSA extension / contingency.",
                "asset_ids": assets,
            })
        elif ctype == "target_tsa_exit_missed":
            assets = sorted(asset_by_id)
            risks.append({
                "id": _stable_risk_id("target_tsa_exit_missed", assets),
                "risk": f"Programme misses target TSA exit ({conflict['target_tsa_exit']}).",
                "cause": conflict.get("message", "Latest planned completion exceeds target TSA exit."),
                "likelihood": "high",
                "impact": "critical",
                "owner": "Programme manager",
                "mitigation": "Parallelise critical-path build work or re-baseline target TSA exit.",
                "asset_ids": assets,
            })
        elif ctype == "cycle_exceeds_wave_capacity":
            members = sorted(conflict.get("assets", []))
            risks.append({
                "id": _stable_risk_id("cycle_exceeds_wave_capacity", members),
                "risk": "Cyclic asset group exceeds wave capacity.",
                "cause": conflict.get("message", "Strongly connected component exceeds max_assets_per_wave."),
                "likelihood": "high",
                "impact": "high",
                "owner": "Application migration lead",
                "mitigation": "Decouple cycle or approve temporary wave capacity exception.",
                "asset_ids": members,
            })

    # ── (a) Near-miss: <45 days margin between asset completion and TSA end_date ──
    tsa_by_id = {svc.id: svc for svc in portfolio.tsa_services}
    # Build flat map: asset_id -> planned_completion (date) from waves
    completion_by_asset: dict[str, date] = {}
    for wave in waves_result.get("waves", []):
        for asset_id, iso in wave.get("asset_completion_dates", {}).items():
            completion_by_asset[asset_id] = date.fromisoformat(iso)

    for asset in portfolio.assets:
        if not asset.tsa_id:
            continue
        tsa = tsa_by_id.get(asset.tsa_id)
        if tsa is None:
            continue
        completion = completion_by_asset.get(asset.id)
        if completion is None:
            continue
        # Skip if already covered by a hard TSA conflict for this asset
        if ("tsa_asset", asset.id) in covered:
            continue
        margin_days = (tsa.end_date - completion).days
        if 0 < margin_days < 45:
            assets = [asset.id]
            risks.append({
                "id": _stable_risk_id("tsa_near_miss", assets, asset.tsa_id),
                "risk": (
                    f"{asset.id} has only {margin_days} days between planned completion "
                    f"({completion.isoformat()}) and {asset.tsa_id} end date ({tsa.end_date.isoformat()})."
                ),
                "cause": f"Near-miss: margin of {margin_days} days is below the 45-day buffer threshold.",
                "likelihood": "medium",
                "impact": "high",
                "owner": "TSA / separation lead",
                "mitigation": (
                    f"Advance {asset.id} cutover by at least {45 - margin_days} days or "
                    f"negotiate a contingency extension on {asset.tsa_id}."
                ),
                "asset_ids": assets,
            })

    # ── (b) Non-extendable TSA with linked assets ──────────────────────────
    for svc in portfolio.tsa_services:
        if svc.extendable:
            continue
        linked = sorted(a.id for a in portfolio.assets if a.tsa_id == svc.id)
        if not linked:
            continue
        # Skip if already covered by a conflict for this TSA
        if ("tsa", svc.id) in covered:
            continue
        risks.append({
            "id": _stable_risk_id("tsa_non_extendable", linked, svc.id),
            "risk": f"{svc.id} is non-extendable and expires on {svc.end_date.isoformat()}.",
            "cause": (
                f"{svc.id} has no extension option; assets {', '.join(linked)} must exit "
                f"before {svc.end_date.isoformat()} with no fallback."
            ),
            "likelihood": "high",
            "impact": "critical",
            "owner": "TSA / separation lead",
            "mitigation": (
                f"Prioritise separation of {svc.id}-linked assets; "
                f"embed a hard-stop milestone in the programme plan."
            ),
            "asset_ids": linked,
        })

    # ── (c) Non-transferable licence on non-retired asset ──────────────────
    for lic in portfolio.licences:
        if lic.transferable:
            continue
        # Skip if a conflict already covers this licence
        if ("licence", lic.id) in covered:
            continue
        non_retired = sorted(
            a.id for a in portfolio.assets
            if a.licence_id == lic.id
        )
        if not non_retired:
            continue
        risks.append({
            "id": _stable_risk_id("licence_non_transferable", non_retired, lic.id),
            "risk": f"Licence {lic.id} ({lic.vendor} {lic.product}) is non-transferable.",
            "cause": (
                f"Assets {', '.join(non_retired)} rely on {lic.id}, which cannot be "
                f"transferred to Nordia; a new licence must be in place before cutover."
            ),
            "likelihood": "medium",
            "impact": "high",
            "owner": "Commercial / product owner",
            "mitigation": (
                f"Renegotiate or replace {lic.id} with a Nordia-owned licence "
                f"before the asset cutover date. Notice period: {lic.notice_period_days} days."
            ),
            "asset_ids": non_retired,
        })

    if any(asset.id == "INF-03" and asset.owner.value == "shared" for asset in portfolio.assets):
        risks.append({"id": _stable_risk_id("shared_identity", ["INF-03"]),
                      "risk": "Shared identity cutover blocks users or applications.",
                      "cause": "INF-03 is a common authentication dependency across the portfolio.",
                      "likelihood": "medium", "impact": "critical", "owner": "Identity lead",
                      "mitigation": "Build target identity in parallel, pilot users, and retain tested rollback.",
                      "asset_ids": ["INF-03"]})
    cycle_groups = cycles(build_graph(portfolio))
    if cycle_groups:
        cycle_assets = sorted({asset_id for group in cycle_groups for asset_id in group})
        risks.append({"id": _stable_risk_id("cyclic_cutover", cycle_assets),
                      "risk": "A cyclic application cutover leaves inconsistent operations.",
                      "cause": "Mutually dependent applications must move in the same cutover window.",
                      "likelihood": "medium", "impact": "high", "owner": "Application migration lead",
                      "mitigation": "Rehearse a joint move, agree rollback thresholds, and validate both sides together.",
                      "asset_ids": cycle_assets})
    sensitive_ids = sorted(asset.id for asset in portfolio.assets if asset.sensitive)
    if sensitive_ids:
        risks.append({"id": _stable_risk_id("sensitive_data", sensitive_ids),
                      "risk": "Sensitive data is exposed or corrupted during migration.",
                      "cause": "Personal or financial data crosses the separation boundary.",
                      "likelihood": "medium", "impact": "critical", "owner": "Data protection officer",
                      "mitigation": "Use encryption, least privilege, masked rehearsals, and signed reconciliation evidence.",
                      "asset_ids": sensitive_ids})
    if len(waves_result["waves"]) > 1:
        all_assets = sorted(asset_by_id)
        risks.append({"id": _stable_risk_id("wave_capacity_delay", all_assets),
                      "risk": "Wave capacity or dependency changes delay cutover dates.",
                      "cause": "Dependencies and specialist capacity concentrate work into sequential waves.",
                      "likelihood": "medium", "impact": "high", "owner": "Programme manager",
                      "mitigation": "Reserve specialist capacity and reforecast TSA needs after each wave.",
                      "asset_ids": all_assets})
    functions: dict[str, list[str]] = {}
    for asset in portfolio.assets:
        if asset.function:
            functions.setdefault(asset.function, []).append(asset.id)
    duplicates = sorted(asset_id for members in functions.values() if len(members) > 1 for asset_id in members)
    if duplicates:
        risks.append({"id": _stable_risk_id("duplicate_crm", duplicates),
                      "risk": "CRM consolidation loses customer history or interrupts support.",
                      "cause": "Two systems provide a duplicate CRM function and contain separate records.",
                      "likelihood": "medium", "impact": "medium", "owner": "Commercial systems lead",
                      "mitigation": "Map and deduplicate records, confirm the destination, and get sign-off before retirement.",
                      "asset_ids": duplicates})

    risks.sort(key=lambda item: (item["id"], tuple(item["asset_ids"]), item["risk"]))
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
    exit_strategy_by_id = {
        item["asset_id"]: item["exit_strategy"]
        for item in strategies
        if "exit_strategy" in item
    }
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
            exit_strategy_by_id=exit_strategy_by_id,
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
