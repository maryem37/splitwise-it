"""OR-Tools CP-SAT constraint programming scheduler for carve-out migration portfolios."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import sys
import time
import types
from typing import Any

import yaml

# ortools.sat.python.cp_model imports pandas solely for optional type-hint aliases
# (pd.DataFrame, pd.Series, pd.Index). On Windows hosts with Smart App Control,
# unsigned pandas C-extensions can fail with OSError (WinError 4551) or ImportError.
# We only install a minimal type-alias stub if importing pandas fails with ImportError/OSError.
def _ensure_cp_model() -> Any:
    try:
        from ortools.sat.python import cp_model
        return cp_model
    except (ImportError, OSError) as first_err:
        if "pandas" in sys.modules:
            raise first_err
        try:
            import pandas  # noqa: F401
            raise first_err
        except (ImportError, OSError):
            fake_pd = types.ModuleType("pandas")
            fake_pd.DataFrame = type("DataFrame", (), {})
            fake_pd.Series = type("Series", (), {})
            fake_pd.Index = type("Index", (), {})
            sys.modules["pandas"] = fake_pd
            from ortools.sat.python import cp_model
            return cp_model


from carveout.graph import build_graph, cycles
from carveout.models import Portfolio
from carveout.optimization.models import (
    AssetScheduleResult,
    OptimizationConfig,
    OptimizationResult,
)
from carveout.sequencing import _add_months, _wave_start


def solve_migration_schedule(
    portfolio: Portfolio,
    strategies: list[dict[str, Any]],
    config: OptimizationConfig | None = None,
    scenario_id: str = "baseline",
    delay_assets: dict[str, int] | None = None,
    baseline_asset_starts: dict[str, str] | None = None,
    constraints_path: str | Path | None = None,
) -> OptimizationResult:
    """
    Construct and solve a discrete wave scheduling optimization model using CP-SAT.

    Hard Constraints:
      1. Unit coupling (SCC): All assets in a strongly connected component share one wave.
      2. Strict dependency ordering between distinct SCCs:
         - Normal edge (source depends on target): wave[target] < wave[source]
         - Retain-under-TSA target: wave[source] < wave[target]
      3. Wave capacity: assets in wave w <= max_assets_per_wave.
      4. Wave span: wave[u] <= max_wave for all migration units u.
      5. Delay wave shift: delayed units with delay_weeks > 0 are shifted strictly past
         their baseline wave if a baseline schedule is provided.
    """
    cp_model = _ensure_cp_model()
    cfg = config or OptimizationConfig()
    start_time = time.time()

    # Load constraints.yaml if provided (matching sequencing.py)
    yaml_cfg: dict[str, Any] = {}
    if constraints_path:
        yaml_cfg = yaml.safe_load(Path(constraints_path).read_text(encoding="utf-8")) or {}
    max_cap = int(yaml_cfg.get("max_assets_per_wave", cfg.max_assets_per_wave or portfolio.planning.max_assets_per_wave))
    gap_weeks = int(yaml_cfg.get("weeks_per_wave_gap", cfg.gap_weeks if cfg.gap_weeks is not None else portfolio.planning.weeks_per_wave_gap))
    freeze_periods: list[dict[str, str]] = yaml_cfg.get("freeze_periods", [])

    model = cp_model.CpModel()

    assets = portfolio.assets
    asset_by_id = {a.id: a for a in assets}
    retained_assets = {
        s["asset_id"] for s in strategies if s.get("strategy") == "retain_under_tsa"
    }
    strategy_map = {s["asset_id"]: s.get("strategy", "migrate") for s in strategies}

    # Identify Strongly Connected Components (cycles)
    g = build_graph(portfolio)
    detected_cycles = cycles(g)

    # Map each asset to a migration unit ID (SCCs form coupled units)
    asset_to_unit: dict[str, int] = {}
    unit_members: dict[int, list[str]] = {}
    current_unit = 0

    for group in detected_cycles:
        for aid in group:
            asset_to_unit[aid] = current_unit
        unit_members[current_unit] = list(group)
        current_unit += 1

    for a in assets:
        if a.id not in asset_to_unit:
            asset_to_unit[a.id] = current_unit
            unit_members[current_unit] = [a.id]
            current_unit += 1

    max_w = cfg.max_waves

    # Decision variables: wave assignment for each migration unit
    unit_wave_vars = {
        u: model.NewIntVar(1, max_w, f"unit_wave_{u}")
        for u in unit_members
    }
    asset_wave_vars = {
        a.id: unit_wave_vars[asset_to_unit[a.id]]
        for a in assets
    }

    max_wave_var = model.NewIntVar(1, max_w, "max_wave")
    for u in unit_members:
        model.Add(unit_wave_vars[u] <= max_wave_var)

    # 1. Strict Dependency Constraints between DISTINCT SCCs (matches sequencing.py)
    for rel in portfolio.relationships:
        src, tgt = rel.source, rel.target
        if src in asset_wave_vars and tgt in asset_wave_vars:
            if asset_to_unit[src] == asset_to_unit[tgt]:
                # Within the same SCC, assets already share unit_wave_vars[u]
                continue
            if tgt in retained_assets:
                model.Add(asset_wave_vars[src] < asset_wave_vars[tgt])
            else:
                model.Add(asset_wave_vars[tgt] < asset_wave_vars[src])

    # 2. Capacity Constraints per Wave
    is_in_wave = {}
    for a in assets:
        for w in range(1, max_w + 1):
            is_in_wave[a.id, w] = model.NewBoolVar(f"in_wave_{a.id}_{w}")
            model.Add(asset_wave_vars[a.id] == w).OnlyEnforceIf(is_in_wave[a.id, w])
            model.Add(asset_wave_vars[a.id] != w).OnlyEnforceIf(is_in_wave[a.id, w].Not())

    for w in range(1, max_w + 1):
        model.Add(sum(is_in_wave[a.id, w] for a in assets) <= max_cap)

    # 3. Delay Constraints on Migration Units
    if delay_assets:
        for aid, delay_wks in delay_assets.items():
            if aid in asset_wave_vars and delay_wks > 0:
                min_wave_shift = max(1, round(delay_wks / (gap_weeks + 2)))
                model.Add(asset_wave_vars[aid] >= min_wave_shift)

    # 4. Lexicographic Weighted Objectives using actual TSA monthly rates
    # For each TSA service, tsa_max_wave[s] >= wave[a] for all linked assets a.
    # Because weights are strictly positive, at optimality tsa_max_wave[s] == max(wave[a]).
    tsa_rate_terms = []
    total_monthly_rates = 0
    for svc in portfolio.tsa_services:
        linked_ids = [a.id for a in assets if a.tsa_id == svc.id]
        if not linked_ids or svc.monthly_cost <= 0:
            continue
        rate_int = max(1, int(round(svc.monthly_cost)))
        total_monthly_rates += rate_int
        svc_max_w = model.NewIntVar(1, max_w, f"tsa_max_wave_{svc.id}")
        for aid in linked_ids:
            model.Add(asset_wave_vars[aid] <= svc_max_w)
        tsa_rate_terms.append(rate_int * svc_max_w)

    tsa_rate_weighted_proxy = sum(tsa_rate_terms) if tsa_rate_terms else 0

    if cfg.objective == "minimize_duration":
        # Strictly lexicographic: max_wave_var in [1..max_w], tsa_rate_weighted_proxy <= total_monthly_rates * max_w
        M_dur = total_monthly_rates * max_w + 1
        model.Minimize(max_wave_var * M_dur + tsa_rate_weighted_proxy)
        obj_desc = (
            "Lexicographic: minimize total wave span (max_wave) first, "
            "breaking ties by rate-weighted TSA exit waves."
        )
    elif cfg.objective == "minimize_cost":
        # Strictly lexicographic: minimize rate-weighted TSA exit waves first, then max_wave
        M_cost = max_w + 1
        model.Minimize(tsa_rate_weighted_proxy * M_cost + max_wave_var)
        obj_desc = (
            "Lexicographic wave-proxy: minimize sum(monthly_rate * max_wave[tsa_service]) first, "
            "breaking ties by total wave span. Note: calendar-month cost is computed post-solve from exact dates."
        )
    else:  # balanced
        avg_rate = max(1, total_monthly_rates // max(1, len(tsa_rate_terms)))
        model.Minimize(tsa_rate_weighted_proxy + avg_rate * max_wave_var)
        obj_desc = (
            "Balanced weighted objective: rate-weighted TSA exit waves + average_monthly_rate * max_wave."
        )

    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = cfg.max_solve_time_seconds
    solver.parameters.num_search_workers = cfg.num_search_workers
    solver.parameters.random_seed = cfg.random_seed

    status_code = solver.Solve(model)
    solve_duration = time.time() - start_time

    status_name_map = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN",
    }
    status_str = status_name_map.get(status_code, "UNKNOWN")

    if status_str not in ("OPTIMAL", "FEASIBLE"):
        return OptimizationResult(
            status=status_str,
            objective_name=cfg.objective,
            objective_description=obj_desc,
            objective_value=None,
            best_bound=None,
            solve_duration_seconds=round(solve_duration, 4),
            scenario_id=scenario_id,
            explanation=f"CP-SAT solver returned {status_str}.",
        )

    # Map solver integer waves to calendar schedule dates
    solved_waves_dict: dict[int, list[str]] = {}
    for a in assets:
        assigned_w = int(solver.Value(asset_wave_vars[a.id]))
        solved_waves_dict.setdefault(assigned_w, []).append(a.id)

    sorted_wave_nums = sorted(solved_waves_dict.keys())
    waves_list: list[dict[str, Any]] = []
    asset_schedules: dict[str, AssetScheduleResult] = {}

    cur_start = portfolio.planning.cutover_start
    licence_by_id = {l.id: l for l in portfolio.licences}
    tsa_by_id = {s.id: s for s in portfolio.tsa_services}
    conflicts: list[dict[str, Any]] = []

    for w_num in sorted_wave_nums:
        w_assets = sorted(solved_waves_dict[w_num])
        max_build = max(
            (portfolio.planning.day1 + timedelta(weeks=asset_by_id[aid].build_effort_weeks)
             for aid in w_assets),
            default=cur_start,
        )
        delay_floors = []
        if delay_assets:
            for aid in w_assets:
                if aid in delay_assets and delay_assets[aid] > 0:
                    if baseline_asset_starts and aid in baseline_asset_starts:
                        base_dt = date.fromisoformat(baseline_asset_starts[aid])
                    else:
                        base_dt = portfolio.planning.cutover_start
                    delay_floors.append(base_dt + timedelta(weeks=delay_assets[aid]))
        delay_floor = max(delay_floors, default=cur_start)

        candidate_start = max(cur_start, max_build, delay_floor)
        w_start = _wave_start(candidate_start, freeze_periods)
        max_effort = max((asset_by_id[aid].effort_weeks for aid in w_assets), default=0)
        w_comp = w_start + timedelta(weeks=max_effort)

        w_conflicts = []
        comp_dates_map = {}
        for aid in w_assets:
            a_obj = asset_by_id[aid]
            a_comp = w_start + timedelta(weeks=a_obj.effort_weeks)
            comp_dates_map[aid] = a_comp.isoformat()

            if a_obj.licence_id and a_obj.licence_id in licence_by_id:
                lic = licence_by_id[a_obj.licence_id]
                if a_comp > lic.end_date:
                    w_conflicts.append({
                        "type": "licence_expires_before_cutover",
                        "asset_id": aid,
                        "licence_id": lic.id,
                        "expiry": lic.end_date.isoformat(),
                        "planned_completion": a_comp.isoformat(),
                    })
            if a_obj.tsa_id and a_obj.tsa_id in tsa_by_id:
                svc = tsa_by_id[a_obj.tsa_id]
                if a_comp > svc.end_date:
                    ext_end = _add_months(svc.end_date, svc.extension_months)
                    within_ext = svc.extendable and a_comp <= ext_end
                    w_conflicts.append({
                        "type": "tsa_extension_required" if within_ext else "tsa_ends_before_cutover",
                        "asset_id": aid,
                        "tsa_id": svc.id,
                        "tsa_end": svc.end_date.isoformat(),
                        "planned_completion": a_comp.isoformat(),
                    })

            asset_schedules[aid] = AssetScheduleResult(
                asset_id=aid,
                name=a_obj.name,
                wave=w_num,
                start_week=0,
                completion_week=a_obj.effort_weeks,
                planned_start=w_start.isoformat(),
                planned_completion=a_comp.isoformat(),
                strategy=strategy_map.get(aid, "migrate"),
            )

        conflicts.extend(w_conflicts)
        waves_list.append({
            "wave": w_num,
            "assets": w_assets,
            "planned_start": w_start.isoformat(),
            "planned_completion": w_comp.isoformat(),
            "asset_completion_dates": comp_dates_map,
            "conflicts": w_conflicts,
        })
        cur_start = w_comp + timedelta(weeks=gap_weeks)

    latest_date = max(
        (date.fromisoformat(w["planned_completion"]) for w in waves_list),
        default=portfolio.planning.day1,
    )

    # Safe explicit lookup by wave number (avoids positional waves_list[w_num - 1] IndexError)
    wave_by_num = {w["wave"]: w for w in waves_list}

    # Calculate TSA cost using exact calendar-month formula (matching metrics.calculate_metrics)
    tsa_cost_by_service: dict[str, float] = {}
    for svc in portfolio.tsa_services:
        linked_ids = {a.id for a in portfolio.assets if a.tsa_id == svc.id}
        comp_dates = [
            date.fromisoformat(wave_by_num[w_num]["asset_completion_dates"][aid])
            for w_num in sorted_wave_nums
            for aid in linked_ids.intersection(wave_by_num[w_num]["assets"])
            if aid in wave_by_num[w_num]["asset_completion_dates"]
        ]
        end = max(comp_dates, default=svc.start_date)
        months = max(0, (end.year - svc.start_date.year) * 12
                     + end.month - svc.start_date.month
                     + (1 if end.day > svc.start_date.day else 0))
        tsa_cost_by_service[svc.id] = round(months * svc.monthly_cost, 2)

    total_tsa_cost = round(sum(tsa_cost_by_service.values()), 2)

    return OptimizationResult(
        status=status_str,
        objective_name=cfg.objective,
        objective_description=obj_desc,
        objective_value=float(solver.ObjectiveValue()),
        best_bound=float(solver.BestObjectiveBound()) if solver.BestObjectiveBound() else None,
        solve_duration_seconds=round(solve_duration, 4),
        total_waves=len(waves_list),
        latest_completion_date=latest_date.isoformat(),
        estimated_tsa_cost_total=total_tsa_cost,
        tsa_cost_by_service=tsa_cost_by_service,
        conflicts=conflicts,
        asset_schedules=asset_schedules,
        waves=waves_list,
        scenario_id=scenario_id,
        explanation=(
            f"CP-SAT solver achieved {status_str} solution across {len(waves_list)} waves. "
            f"Latest completion: {latest_date.isoformat()}, Total TSA Cost: ${total_tsa_cost:,.2f}."
        ),
    )
