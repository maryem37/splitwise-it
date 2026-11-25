"""Independent deterministic validation of optimization schedule results."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from carveout.graph import build_graph, cycles
from carveout.models import Portfolio
from carveout.optimization.models import ConstraintViolation, OptimizationResult


def _as_date(value: date | str) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def validate_schedule_constraints(
    portfolio: Portfolio,
    result: OptimizationResult,
    retained_assets: set[str],
    constraints_path: str | Path | None = None,
    baseline_asset_starts: dict[str, str] | None = None,
    delay_assets: dict[str, int] | None = None,
) -> dict[str, Any]:
    """
    Independently validate an optimization result against all portfolio and
    configuration constraints without trusting solver status alone.

    Checks:
      1. Solver feasibility status
      2. Complete asset coverage
      3. SCC co-location (cycle members share the same wave)
      4. Strict dependency ordering between distinct SCCs
      5. Wave capacity limits
      6. Calendar start/completion dates, durations, and inter-wave gaps
      7. Freeze periods
      8. Delay floors (relative to baseline schedule)
      9. Licence and TSA deadlines (surfaced as existing_conflict / warning)
    """
    findings: list[ConstraintViolation] = []

    if result.status not in ("OPTIMAL", "FEASIBLE"):
        findings.append(ConstraintViolation(
            constraint_name="solver_feasibility",
            entity="portfolio",
            expected="OPTIMAL or FEASIBLE",
            actual=result.status,
            severity="hard",
            explanation=f"Solver returned non-feasible status {result.status}.",
        ))
        return {
            "valid": False,
            "violations": [f.explanation for f in findings],
            "findings": [f.model_dump() for f in findings],
            "hard_violation_count": 1,
            "warning_count": 0,
            "existing_conflict_count": 0,
            "violation_count": 1,
        }

    yaml_cfg: dict[str, Any] = {}
    if constraints_path:
        yaml_cfg = yaml.safe_load(Path(constraints_path).read_text(encoding="utf-8")) or {}
    max_cap = int(yaml_cfg.get("max_assets_per_wave", portfolio.planning.max_assets_per_wave))
    gap_weeks = int(yaml_cfg.get("weeks_per_wave_gap", portfolio.planning.weeks_per_wave_gap))
    freeze_periods: list[dict[str, str]] = yaml_cfg.get("freeze_periods", [])

    asset_by_id = {a.id: a for a in portfolio.assets}
    asset_to_wave = {aid: res.wave for aid, res in result.asset_schedules.items()}

    # 1. All assets scheduled
    missing_assets = sorted(set(asset_by_id) - set(asset_to_wave))
    if missing_assets:
        findings.append(ConstraintViolation(
            constraint_name="asset_coverage",
            entity=",".join(missing_assets),
            expected="All portfolio assets scheduled",
            actual=f"Missing {len(missing_assets)} assets",
            severity="hard",
            explanation=f"Assets missing from schedule: {missing_assets}",
        ))

    # 2. SCC co-location
    g = build_graph(portfolio)
    scc_groups = cycles(g)
    asset_to_scc: dict[str, tuple[str, ...]] = {}
    for group in scc_groups:
        key = tuple(group)
        for aid in group:
            asset_to_scc[aid] = key
        waves_in_scc = {asset_to_wave.get(aid) for aid in group}
        if len(waves_in_scc) != 1:
            findings.append(ConstraintViolation(
                constraint_name="scc_colocation",
                entity=",".join(group),
                expected="Same wave for all SCC members",
                actual=str({aid: asset_to_wave.get(aid) for aid in group}),
                severity="hard",
                explanation=f"SCC {group} split across multiple waves: {waves_in_scc}.",
            ))

    # 3. Strict dependency ordering between distinct SCCs
    for r in portfolio.relationships:
        src, tgt = r.source, r.target
        if src not in asset_to_wave or tgt not in asset_to_wave:
            continue
        if src in asset_to_scc and asset_to_scc.get(src) == asset_to_scc.get(tgt):
            continue
        w_src = asset_to_wave[src]
        w_tgt = asset_to_wave[tgt]
        if tgt in retained_assets:
            if w_src >= w_tgt:
                findings.append(ConstraintViolation(
                    constraint_name="tsa_dependency_ordering",
                    entity=f"{src}->{tgt}",
                    expected=f"wave({src}) < wave({tgt})",
                    actual=f"wave({src})={w_src}, wave({tgt})={w_tgt}",
                    severity="hard",
                    explanation=(
                        f"Consumer {src} (Wave {w_src}) must complete in a strictly earlier wave "
                        f"than TSA-retained service {tgt} (Wave {w_tgt})."
                    ),
                ))
        else:
            if w_tgt >= w_src:
                findings.append(ConstraintViolation(
                    constraint_name="dependency_ordering",
                    entity=f"{src}->{tgt}",
                    expected=f"wave({tgt}) < wave({src})",
                    actual=f"wave({src})={w_src}, wave({tgt})={w_tgt}",
                    severity="hard",
                    explanation=(
                        f"Asset {src} (Wave {w_src}) depends on {tgt} (Wave {w_tgt}), "
                        f"which must complete in a strictly earlier wave."
                    ),
                ))

    # 4. Wave capacity
    wave_counts: dict[int, int] = {}
    for w in asset_to_wave.values():
        wave_counts[w] = wave_counts.get(w, 0) + 1
    for w, c in sorted(wave_counts.items()):
        if c > max_cap:
            findings.append(ConstraintViolation(
                constraint_name="wave_capacity",
                entity=f"Wave-{w}",
                expected=f"<= {max_cap} assets",
                actual=f"{c} assets",
                severity="hard",
                explanation=f"Wave {w} has {c} assets, exceeding max_assets_per_wave={max_cap}.",
            ))

    # 5. Calendar dates, durations, inter-wave gaps, and freeze periods
    sorted_waves = sorted(result.waves, key=lambda w: w["wave"])
    prev_completion: date | None = None
    for w in sorted_waves:
        w_num = w["wave"]
        w_start = _as_date(w["planned_start"])
        w_comp = _as_date(w["planned_completion"])
        w_assets = w["assets"]

        if w_start < portfolio.planning.cutover_start:
            findings.append(ConstraintViolation(
                constraint_name="cutover_start_floor",
                entity=f"Wave-{w_num}",
                expected=f">= {portfolio.planning.cutover_start.isoformat()}",
                actual=w_start.isoformat(),
                severity="hard",
                explanation=f"Wave {w_num} starts before portfolio cutover_start.",
            ))

        if prev_completion is not None:
            min_next = prev_completion + timedelta(weeks=gap_weeks)
            if w_start < min_next:
                findings.append(ConstraintViolation(
                    constraint_name="inter_wave_gap",
                    entity=f"Wave-{w_num}",
                    expected=f">= {min_next.isoformat()} ({gap_weeks}w gap)",
                    actual=w_start.isoformat(),
                    severity="hard",
                    explanation=f"Wave {w_num} violates {gap_weeks}-week stabilization gap after previous wave.",
                ))

        for aid in w_assets:
            a_obj = asset_by_id.get(aid)
            if a_obj:
                min_build_end = portfolio.planning.day1 + timedelta(weeks=a_obj.build_effort_weeks)
                if w_start < min_build_end:
                    findings.append(ConstraintViolation(
                        constraint_name="build_effort_duration",
                        entity=aid,
                        expected=f"start >= {min_build_end.isoformat()}",
                        actual=w_start.isoformat(),
                        severity="hard",
                        explanation=f"Asset {aid} starts before its {a_obj.build_effort_weeks}w build completes.",
                    ))

        expected_effort = max((asset_by_id[aid].effort_weeks for aid in w_assets if aid in asset_by_id), default=0)
        expected_comp = w_start + timedelta(weeks=expected_effort)
        if w_comp != expected_comp:
            findings.append(ConstraintViolation(
                constraint_name="migration_duration",
                entity=f"Wave-{w_num}",
                expected=expected_comp.isoformat(),
                actual=w_comp.isoformat(),
                severity="hard",
                explanation=f"Wave {w_num} completion {w_comp} does not match start + {expected_effort}w effort ({expected_comp}).",
            ))

        for period in freeze_periods:
            f_start = _as_date(period["start"])
            f_end = _as_date(period["end"])
            if f_start <= w_start <= f_end:
                findings.append(ConstraintViolation(
                    constraint_name="freeze_period",
                    entity=f"Wave-{w_num}",
                    expected=f"start outside [{f_start.isoformat()}, {f_end.isoformat()}]",
                    actual=w_start.isoformat(),
                    severity="hard",
                    explanation=f"Wave {w_num} start {w_start} falls inside freeze period {f_start}..{f_end}.",
                ))

        prev_completion = w_comp

    # 6. Delay floor validation
    if delay_assets and baseline_asset_starts:
        for aid, delay_wks in delay_assets.items():
            if delay_wks > 0 and aid in baseline_asset_starts and aid in result.asset_schedules:
                base_start = _as_date(baseline_asset_starts[aid])
                actual_start = _as_date(result.asset_schedules[aid].planned_start)
                min_delayed = base_start + timedelta(weeks=delay_wks)
                if actual_start < min_delayed:
                    findings.append(ConstraintViolation(
                        constraint_name="delay_floor",
                        entity=aid,
                        expected=f">= {min_delayed.isoformat()} (+{delay_wks}w from {base_start.isoformat()})",
                        actual=actual_start.isoformat(),
                        severity="hard",
                        explanation=f"Delayed asset {aid} starts {actual_start} before required +{delay_wks}w shift ({min_delayed}).",
                    ))

    # 7. Licence & TSA deadlines (surfaced as existing_conflict / warning)
    licence_by_id = {lic.id: lic for lic in portfolio.licences}
    tsa_by_id = {svc.id: svc for svc in portfolio.tsa_services}
    for aid, sched in result.asset_schedules.items():
        a_obj = asset_by_id.get(aid)
        if not a_obj:
            continue
        comp_dt = _as_date(sched.planned_completion)
        if a_obj.licence_id and a_obj.licence_id in licence_by_id:
            lic = licence_by_id[a_obj.licence_id]
            if comp_dt > lic.end_date:
                findings.append(ConstraintViolation(
                    constraint_name="licence_deadline",
                    entity=aid,
                    expected=f"<= {lic.end_date.isoformat()} ({lic.id})",
                    actual=comp_dt.isoformat(),
                    severity="existing_conflict",
                    explanation=f"{aid} completes {comp_dt} after licence {lic.id} expiry {lic.end_date}.",
                ))
        if a_obj.tsa_id and a_obj.tsa_id in tsa_by_id:
            svc = tsa_by_id[a_obj.tsa_id]
            if comp_dt > svc.end_date:
                findings.append(ConstraintViolation(
                    constraint_name="tsa_deadline",
                    entity=aid,
                    expected=f"<= {svc.end_date.isoformat()} ({svc.id})",
                    actual=comp_dt.isoformat(),
                    severity="existing_conflict",
                    explanation=f"{aid} completes {comp_dt} after {svc.id} end date {svc.end_date}.",
                ))

    hard_violations = [f for f in findings if f.severity == "hard"]
    warnings = [f for f in findings if f.severity == "warning"]
    existing_conflicts = [f for f in findings if f.severity == "existing_conflict"]

    return {
        "valid": len(hard_violations) == 0,
        "violations": [f.explanation for f in hard_violations],
        "findings": [f.model_dump() for f in findings],
        "hard_violation_count": len(hard_violations),
        "warning_count": len(warnings),
        "existing_conflict_count": len(existing_conflicts),
        "violation_count": len(hard_violations),
    }
