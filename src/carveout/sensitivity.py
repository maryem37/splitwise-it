"""Scenario sensitivity and Monte Carlo schedule/cost simulation."""
from __future__ import annotations

from collections import Counter
import csv
from datetime import date
import json
import math
from pathlib import Path
import random
from typing import Any

from .metrics import calculate_metrics
from .models import Portfolio
from .sequencing import _add_months, compute_waves


def _clone_portfolio(portfolio: Portfolio) -> Portfolio:
    return Portfolio.model_validate(portfolio.model_dump())


def _evaluate_scenario(
    name: str,
    portfolio: Portfolio,
    constraints_path: str | Path | None,
    strategies: list[dict[str, Any]],
    extra_tsa_cost: float = 0.0,
) -> dict[str, Any]:
    sequencing = compute_waves(portfolio, constraints_path, strategies)
    metrics = calculate_metrics(portfolio, sequencing)
    latest = date.fromisoformat(metrics["latest_planned_completion"])
    margin_days = (portfolio.planning.target_tsa_exit - latest).days
    total_cost = round(metrics["estimated_tsa_cost_total"] + extra_tsa_cost, 2)
    return {
        "scenario": name,
        "wave_count": metrics["wave_count"],
        "latest_planned_completion": metrics["latest_planned_completion"],
        "estimated_tsa_cost_total": total_cost,
        "conflict_count": len(sequencing["conflicts"]),
        "margin_to_target_days": margin_days,
        "details": "",
    }


def _apply_max_parallel_builds(portfolio: Portfolio, max_parallel: int = 3) -> None:
    """Greedy LPT scheduling of build_effort_weeks across `max_parallel` slots."""
    build_assets = sorted(
        (asset for asset in portfolio.assets if asset.build_effort_weeks > 0),
        key=lambda asset: (-asset.build_effort_weeks, asset.id),
    )
    slots = [0] * max_parallel
    for asset in build_assets:
        idx = min(range(max_parallel), key=lambda k: slots[k])
        finish = slots[idx] + asset.build_effort_weeks
        slots[idx] = finish
        asset.build_effort_weeks = finish


def _run_monte_carlo(
    portfolio: Portfolio,
    constraints_path: str | Path | None,
    strategies: list[dict[str, Any]],
    trials: int = 1000,
    seed: int = 42,
    variant: str = "per_asset",
    dist_name: str = "skewed (0.8, 1.0, 1.5)",
    low: float = 0.8,
    mode: float = 1.0,
    high: float = 1.5,
) -> tuple[dict[str, Any], dict[str, Any]]:
    rng = random.Random(seed)
    completions: list[date] = []
    costs: list[float] = []
    wave_counts: list[int] = []
    conflict_counts: list[int] = []
    meets_target = 0

    for _ in range(trials):
        sim = _clone_portfolio(portfolio)
        if variant == "global":
            factor = rng.triangular(low, high, mode)
            for asset in sim.assets:
                if asset.build_effort_weeks > 0:
                    asset.build_effort_weeks = max(0, round(asset.build_effort_weeks * factor))
                if asset.effort_weeks > 0:
                    asset.effort_weeks = max(1, round(asset.effort_weeks * factor))
        else:
            for asset in sim.assets:
                if asset.build_effort_weeks > 0:
                    asset.build_effort_weeks = max(
                        0, round(asset.build_effort_weeks * rng.triangular(low, high, mode))
                    )
                if asset.effort_weeks > 0:
                    asset.effort_weeks = max(
                        1, round(asset.effort_weeks * rng.triangular(low, high, mode))
                    )
        seq = compute_waves(sim, constraints_path, strategies)
        metrics = calculate_metrics(sim, seq)
        latest = date.fromisoformat(metrics["latest_planned_completion"])
        completions.append(latest)
        costs.append(metrics["estimated_tsa_cost_total"])
        wave_counts.append(metrics["wave_count"])
        conflict_counts.append(len(seq["conflicts"]))
        if latest <= sim.planning.target_tsa_exit:
            meets_target += 1

    sorted_dates = sorted(completions)
    mean_date = date.fromordinal(round(sum(d.toordinal() for d in completions) / trials))
    p50_date = sorted_dates[int(0.50 * (trials - 1))]
    p80_date = sorted_dates[int(0.80 * (trials - 1))]
    p90_date = sorted_dates[int(0.90 * (trials - 1))]
    prob_target = round(100.0 * meets_target / trials, 2)
    mean_conflicts = round(sum(conflict_counts) / trials, 2)
    conflict_dist = {str(k): v for k, v in sorted(Counter(conflict_counts).items())}

    mc_stats = {
        "variant": variant,
        "law": dist_name,
        "trials": trials,
        "seed": seed,
        "mean_completion": mean_date.isoformat(),
        "p50_completion": p50_date.isoformat(),
        "p80_completion": p80_date.isoformat(),
        "p90_completion": p90_date.isoformat(),
        "target_tsa_exit": portfolio.planning.target_tsa_exit.isoformat(),
        "target_exit_probability_percent": prob_target,
        "mean_conflict_count": mean_conflicts,
        "conflict_count_distribution": conflict_dist,
        "mean_tsa_cost": round(sum(costs) / trials, 2),
        "mean_wave_count": round(sum(wave_counts) / trials, 2),
        "p50_margin_days": (portfolio.planning.target_tsa_exit - p50_date).days,
    }
    row = {
        "scenario": f"monte_carlo_{variant}_{dist_name.split()[0]}_{trials}",
        "wave_count": mc_stats["mean_wave_count"],
        "latest_planned_completion": f"P50={p50_date.isoformat()} / P80={p80_date.isoformat()}",
        "estimated_tsa_cost_total": mc_stats["mean_tsa_cost"],
        "conflict_count": mean_conflicts,
        "margin_to_target_days": mc_stats["p50_margin_days"],
        "details": f"P(on_time)={prob_target}%, P90={p90_date.isoformat()}, conflicts={json.dumps(conflict_dist)}",
    }
    return row, mc_stats


def compute_critical_path(
    portfolio: Portfolio,
    constraints_path: str | Path | None,
    strategies: list[dict[str, Any]],
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Compute critical-path assets and +2-week tornado delay impact per asset."""
    base_seq = compute_waves(portfolio, constraints_path, strategies)
    base_metrics = calculate_metrics(portfolio, base_seq)
    base_end = date.fromisoformat(base_metrics["latest_planned_completion"])
    wave_by_asset = {
        asset_id: wave["wave"]
        for wave in base_seq["waves"]
        for asset_id in wave["assets"]
    }

    tornado: list[dict[str, Any]] = []
    for asset in portfolio.assets:
        sim = _clone_portfolio(portfolio)
        for sim_asset in sim.assets:
            if sim_asset.id == asset.id:
                sim_asset.effort_weeks += 2
                break
        seq = compute_waves(sim, constraints_path, strategies)
        metrics = calculate_metrics(sim, seq)
        delayed_end = date.fromisoformat(metrics["latest_planned_completion"])
        impact_days = (delayed_end - base_end).days
        tornado.append({
            "asset_id": asset.id,
            "name": asset.name,
            "wave": wave_by_asset.get(asset.id, 0),
            "base_completion": base_end.isoformat(),
            "delayed_completion": delayed_end.isoformat(),
            "impact_days": impact_days,
        })

    tornado.sort(key=lambda row: (-row["impact_days"], row["wave"], row["asset_id"]))
    critical_assets = sorted(
        (row for row in tornado if row["impact_days"] > 0),
        key=lambda row: (row["wave"], -row["impact_days"], row["asset_id"]),
    )

    if output_dir is not None:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Critical path and tornado analysis",
            "",
            f"Base programme completion: `{base_end.isoformat()}`",
            "",
            "## Critical path (ordered by wave)",
            "",
        ]
        if critical_assets:
            for item in critical_assets:
                lines.append(
                    f"1. `{item['asset_id']}` ({item['name']}, Wave {item['wave']}) — "
                    f"+{item['impact_days']} days impact on +2w delay"
                )
        else:
            lines.append("No single-asset +2w delay shifts the programme completion date.")
        lines.extend([
            "",
            "## Tornado analysis (+2 weeks per asset, sorted by impact)",
            "",
            "| Asset | Name | Wave | Delayed completion | Impact (days) |",
            "|---|---|---:|---|---:|",
        ])
        for row in tornado:
            lines.append(
                f"| `{row['asset_id']}` | {row['name']} | {row['wave']} | "
                f"{row['delayed_completion']} | {row['impact_days']} |"
            )
        (out / "critical_path.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {"base_completion": base_end.isoformat(), "critical_path": critical_assets, "tornado": tornado}


def run_sensitivity(
    portfolio: Portfolio,
    constraints_path: str | Path | None,
    strategies: list[dict[str, Any]],
    output_dir: str | Path,
    trials: int = 1000,
    seed: int = 42,
) -> dict[str, Any]:
    """Run deterministic sensitivity scenarios + Monte Carlo and write CSV/MD reports."""
    rows: list[dict[str, Any]] = []

    # 1. Base
    rows.append(_evaluate_scenario("base", _clone_portfolio(portfolio), constraints_path, strategies))

    # 2. All builds delayed by 4 weeks
    p_delay = _clone_portfolio(portfolio)
    for asset in p_delay.assets:
        if asset.build_effort_weeks > 0:
            asset.build_effort_weeks += 4
    rows.append(_evaluate_scenario("all_builds_delayed_4w", p_delay, constraints_path, strategies))

    # 3. build_effort_weeks +30%
    p_plus30 = _clone_portfolio(portfolio)
    for asset in p_plus30.assets:
        if asset.build_effort_weeks > 0:
            asset.build_effort_weeks = math.ceil(asset.build_effort_weeks * 1.3)
    rows.append(_evaluate_scenario("build_effort_plus_30pct", p_plus30, constraints_path, strategies))

    # 4. At most 3 parallel builds (greedy LPT)
    p_par3 = _clone_portfolio(portfolio)
    _apply_max_parallel_builds(p_par3, max_parallel=3)
    rows.append(_evaluate_scenario("max_3_parallel_builds", p_par3, constraints_path, strategies))

    # 5. TSA-01 extended by 6 months (+6 * monthly_cost, recalculate conflicts)
    p_tsa01 = _clone_portfolio(portfolio)
    extra_cost = 0.0
    for svc in p_tsa01.tsa_services:
        if svc.id == "TSA-01":
            svc.end_date = _add_months(svc.end_date, 6)
            extra_cost = 6 * svc.monthly_cost
            break
    rows.append(_evaluate_scenario("tsa_01_extended_6m", p_tsa01, constraints_path, strategies, extra_tsa_cost=extra_cost))

    # 6. Monte Carlo (2 variants x 2 laws with the same seed)
    mc_configs = [
        ("global", "skewed (0.8, 1.0, 1.5)", 0.8, 1.0, 1.5),
        ("global", "symmetric (0.9, 1.0, 1.1)", 0.9, 1.0, 1.1),
        ("per_asset", "skewed (0.8, 1.0, 1.5)", 0.8, 1.0, 1.5),
        ("per_asset", "symmetric (0.9, 1.0, 1.1)", 0.9, 1.0, 1.1),
    ]
    mc_variants: list[dict[str, Any]] = []
    for variant, dist_name, low, mode, high in mc_configs:
        mc_row, mc_item = _run_monte_carlo(
            portfolio, constraints_path, strategies,
            trials=trials, seed=seed, variant=variant,
            dist_name=dist_name, low=low, mode=mode, high=high,
        )
        rows.append(mc_row)
        mc_variants.append(mc_item)
    mc_stats = next(item for item in mc_variants if item["variant"] == "per_asset" and item["law"].startswith("skewed"))

    # 7. Mitigation scenarios (a, b, c) with Monte Carlo probability & cost per gained point
    base_row = rows[0]
    base_cost = base_row["estimated_tsa_cost_total"]
    base_prob = mc_stats["target_exit_probability_percent"]

    def _apply_tsa_extensions(target: Portfolio) -> float:
        added = 0.0
        for svc in target.tsa_services:
            if svc.id == "TSA-01":
                svc.end_date = _add_months(svc.end_date, 6)
                added += 6 * svc.monthly_cost
            elif svc.id == "TSA-04":
                svc.end_date = _add_months(svc.end_date, 3)
                added += 3 * svc.monthly_cost
        return added

    def _apply_erp_early_start(target: Portfolio) -> None:
        for asset in target.assets:
            if asset.id == "APP-01":
                asset.build_effort_weeks = max(1, asset.build_effort_weeks // 2)
                asset.effort_weeks = max(1, asset.effort_weeks - 1)
                break

    mitigations: list[dict[str, Any]] = []
    mitigation_specs: list[tuple[str, Any]] = [
        ("mitigation_tsa01_6m_tsa04_3m", lambda p: _apply_tsa_extensions(p)),
        ("mitigation_erp_early_start", lambda p: (_apply_erp_early_start(p), 0.0)[1]),
        ("mitigation_combined", lambda p: (_apply_erp_early_start(p), _apply_tsa_extensions(p))[1]),
    ]
    for name, mutator in mitigation_specs:
        p_mit = _clone_portfolio(portfolio)
        extra_mit_cost = mutator(p_mit)
        det_row = _evaluate_scenario(name, p_mit, constraints_path, strategies, extra_tsa_cost=extra_mit_cost)
        _, mit_mc = _run_monte_carlo(
            p_mit, constraints_path, strategies,
            trials=trials, seed=seed, variant="per_asset",
            dist_name="skewed (0.8, 1.0, 1.5)", low=0.8, mode=1.0, high=1.5,
        )
        prob = mit_mc["target_exit_probability_percent"]
        prob_gain = round(prob - base_prob, 2)
        extra_cost_vs_base = round(det_row["estimated_tsa_cost_total"] - base_cost, 2)
        cost_per_pt = round(extra_cost_vs_base / prob_gain, 2) if prob_gain > 0 else None
        mitigations.append({
            "scenario": name,
            "latest_planned_completion": det_row["latest_planned_completion"],
            "estimated_tsa_cost_total": det_row["estimated_tsa_cost_total"],
            "conflict_count": det_row["conflict_count"],
            "target_exit_probability_percent": prob,
            "prob_gain_points": prob_gain,
            "extra_cost_vs_base": extra_cost_vs_base,
            "cost_per_probability_point": cost_per_pt,
        })

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    columns = [
        "scenario", "wave_count", "latest_planned_completion",
        "estimated_tsa_cost_total", "conflict_count", "margin_to_target_days", "details",
    ]
    with (out / "sensitivity.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    md_lines = [
        "# Sensitivity analysis",
        "",
        f"Target TSA exit: `{portfolio.planning.target_tsa_exit.isoformat()}`",
        "",
        "## Scenarios",
        "",
        "| Scenario | Waves | Latest completion | TSA cost | Conflicts | Margin to target (days) |",
        "|---|---:|---|---:|---:|---:|",
    ]
    for row in rows:
        md_lines.append(
            f"| {row['scenario']} | {row['wave_count']} | {row['latest_planned_completion']} | "
            f"{row['estimated_tsa_cost_total']:,.2f} | {row['conflict_count']} | {row['margin_to_target_days']} |"
        )
    md_lines.extend([
        "",
        f"## Monte Carlo ({trials} trials, seed={seed})",
        "",
        "| Variante | Loi | Moyenne | P50 | P80 | P90 | Prob. target_tsa_exit | Conflits moyens |",
        "|---|---|---|---|---|---|---:|---:|",
    ])
    for item in mc_variants:
        md_lines.append(
            f"| {item['variant']} | {item['law']} | {item['mean_completion']} | "
            f"{item['p50_completion']} | {item['p80_completion']} | {item['p90_completion']} | "
            f"{item['target_exit_probability_percent']}% | {item['mean_conflict_count']} |"
        )
    md_lines.extend([
        "",
        f"### Conflict count distribution ({mc_stats['variant']}, {mc_stats['law']})",
        "",
    ])
    for count_str, freq in mc_stats["conflict_count_distribution"].items():
        md_lines.append(f"- `{count_str}` conflicts: {freq} / {mc_stats['trials']} trials")
    md_lines.extend([
        "",
        "## Mitigation scenarios",
        "",
        "| Scenario | Latest completion | TSA cost | Conflicts | Prob. target_tsa_exit | Gain (pts) | Extra cost / pt |",
        "|---|---|---:|---:|---:|---:|---:|",
    ])
    for mit in mitigations:
        cpp = f"{mit['cost_per_probability_point']:,.2f}" if mit["cost_per_probability_point"] is not None else "N/A"
        md_lines.append(
            f"| {mit['scenario']} | {mit['latest_planned_completion']} | "
            f"{mit['estimated_tsa_cost_total']:,.2f} | {mit['conflict_count']} | "
            f"{mit['target_exit_probability_percent']}% | {mit['prob_gain_points']} | {cpp} |"
        )
    (out / "sensitivity.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    critical = compute_critical_path(portfolio, constraints_path, strategies, output_dir=out)

    return {
        "scenarios": rows,
        "monte_carlo": mc_stats,
        "monte_carlo_variants": mc_variants,
        "mitigations": mitigations,
        "critical_path": critical,
    }
