"""Neo4j integration: load the portfolio dependency graph into a Neo4j instance
and run Cypher analytics queries.

Usage (standalone):
    python -m carveout.neo4j_store --uri bolt://localhost:7687 \
        --user neo4j --password secret

Usage (via CLI):
    carveout neo4j-load --uri bolt://localhost:7687 --user neo4j --password secret
    carveout neo4j-query --uri bolt://localhost:7687 --user neo4j --password secret \
        --query transitive_deps --asset INF-01
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Portfolio
from .cypher_queries import QUERIES


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

def _driver(uri: str, user: str, password: str):
    """Return a neo4j.GraphDatabase driver (import deferred to avoid hard dep)."""
    try:
        from neo4j import GraphDatabase  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "Neo4j driver not installed. Run: pip install 'carveout-copilot[neo4j]'"
        ) from exc
    return GraphDatabase.driver(uri, auth=(user, password))


# ---------------------------------------------------------------------------
# Schema constraints and indexes
# ---------------------------------------------------------------------------

_CONSTRAINTS = [
    "CREATE CONSTRAINT asset_id IF NOT EXISTS FOR (a:Asset) REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT tsa_id   IF NOT EXISTS FOR (t:TSAService) REQUIRE t.id IS UNIQUE",
    "CREATE CONSTRAINT lic_id   IF NOT EXISTS FOR (l:Licence) REQUIRE l.id IS UNIQUE",
]


def _apply_schema(session) -> None:
    for cql in _CONSTRAINTS:
        session.run(cql)


# ---------------------------------------------------------------------------
# Graph loading
# ---------------------------------------------------------------------------

def load_portfolio(
    portfolio: Portfolio,
    sequencing: dict[str, Any] | None = None,
    uri: str = "bolt://localhost:7687",
    user: str = "neo4j",
    password: str = "password",
    clear: bool = True,
) -> dict[str, int]:
    """
    Load a Portfolio into Neo4j and return a summary dict of created nodes/rels.

    Node labels created:
        :Asset          — every asset in the portfolio
        :TSAService     — every TSA service
        :Licence        — every licence

    Relationship types created:
        :CALLS / :READS_FROM / :WRITES_TO /
        :HOSTED_ON / :AUTHENTICATES_VIA / :CONNECTS_VIA
                        — from portfolio.relationships (source DEPENDS_ON target)
        :COVERED_BY_TSA — Asset → TSAService (via tsa_id)
        :LICENSED_UNDER — Asset → Licence    (via licence_id)

    If sequencing is provided, each Asset node also gets:
        wave, strategy, planned_completion
    """
    # Build lookup maps for enrichment from sequencing output
    wave_map: dict[str, int] = {}
    completion_map: dict[str, str] = {}
    strategy_map: dict[str, str] = {}
    if sequencing:
        for wave in sequencing.get("waves", []):
            for asset_id in wave["assets"]:
                wave_map[asset_id] = wave["wave"]
            for asset_id, dt in wave.get("asset_completion_dates", {}).items():
                completion_map[asset_id] = dt

    driver = _driver(uri, user, password)
    counts: dict[str, int] = {
        "assets": 0, "tsa_services": 0, "licences": 0,
        "dep_rels": 0, "tsa_rels": 0, "lic_rels": 0,
    }

    with driver.session() as session:
        _apply_schema(session)

        if clear:
            session.run("MATCH (n) DETACH DELETE n")

        # ── TSA Services ────────────────────────────────────────────────────
        for tsa in portfolio.tsa_services:
            session.run(
                """
                MERGE (t:TSAService {id: $id})
                SET t.service         = $service,
                    t.provider        = $provider,
                    t.start_date      = $start_date,
                    t.end_date        = $end_date,
                    t.monthly_cost    = $monthly_cost,
                    t.extendable      = $extendable,
                    t.extension_months = $extension_months
                """,
                id=tsa.id,
                service=tsa.service,
                provider=tsa.provider,
                start_date=str(tsa.start_date),
                end_date=str(tsa.end_date),
                monthly_cost=tsa.monthly_cost,
                extendable=tsa.extendable,
                extension_months=tsa.extension_months,
            )
            counts["tsa_services"] += 1

        # ── Licences ────────────────────────────────────────────────────────
        for lic in portfolio.licences:
            session.run(
                """
                MERGE (l:Licence {id: $id})
                SET l.vendor           = $vendor,
                    l.product          = $product,
                    l.end_date         = $end_date,
                    l.transferable     = $transferable,
                    l.annual_cost      = $annual_cost,
                    l.notice_period_days = $notice_period_days
                """,
                id=lic.id,
                vendor=lic.vendor,
                product=lic.product,
                end_date=str(lic.end_date),
                transferable=lic.transferable,
                annual_cost=lic.annual_cost,
                notice_period_days=lic.notice_period_days,
            )
            counts["licences"] += 1

        # ── Assets ──────────────────────────────────────────────────────────
        for asset in portfolio.assets:
            session.run(
                """
                MERGE (a:Asset {id: $id})
                SET a.name               = $name,
                    a.type               = $type,
                    a.owner              = $owner,
                    a.criticality        = $criticality,
                    a.users              = $users,
                    a.function           = $function,
                    a.hosting            = $hosting,
                    a.sensitive          = $sensitive,
                    a.effort_weeks       = $effort_weeks,
                    a.build_effort_weeks = $build_effort_weeks,
                    a.wave               = $wave,
                    a.strategy           = $strategy,
                    a.planned_completion = $planned_completion
                """,
                id=asset.id,
                name=asset.name,
                type=asset.type.value,
                owner=asset.owner.value,
                criticality=asset.criticality,
                users=asset.users,
                function=asset.function or "",
                hosting=asset.hosting or "",
                sensitive=asset.sensitive,
                effort_weeks=asset.effort_weeks,
                build_effort_weeks=asset.build_effort_weeks,
                wave=wave_map.get(asset.id, 0),
                strategy=asset.exit_strategy.value if asset.exit_strategy else "",
                planned_completion=completion_map.get(asset.id, ""),
            )
            counts["assets"] += 1

        # ── Dependency relationships ─────────────────────────────────────────
        for rel in portfolio.relationships:
            session.run(
                f"""
                MATCH (src:Asset {{id: $source}})
                MATCH (tgt:Asset {{id: $target}})
                MERGE (src)-[r:{rel.type.value}]->(tgt)
                SET r.description = $description
                """,
                source=rel.source,
                target=rel.target,
                description=rel.description or "",
            )
            counts["dep_rels"] += 1

        # ── COVERED_BY_TSA relationships ─────────────────────────────────────
        for asset in portfolio.assets:
            if asset.tsa_id:
                session.run(
                    """
                    MATCH (a:Asset {id: $asset_id})
                    MATCH (t:TSAService {id: $tsa_id})
                    MERGE (a)-[:COVERED_BY_TSA]->(t)
                    """,
                    asset_id=asset.id,
                    tsa_id=asset.tsa_id,
                )
                counts["tsa_rels"] += 1

        # ── LICENSED_UNDER relationships ──────────────────────────────────────
        for asset in portfolio.assets:
            if asset.licence_id:
                session.run(
                    """
                    MATCH (a:Asset {id: $asset_id})
                    MATCH (l:Licence {id: $lic_id})
                    MERGE (a)-[:LICENSED_UNDER]->(l)
                    """,
                    asset_id=asset.id,
                    lic_id=asset.licence_id,
                )
                counts["lic_rels"] += 1

    driver.close()
    return counts


# ---------------------------------------------------------------------------
# Query runner
# ---------------------------------------------------------------------------

def run_query(
    query_name: str,
    params: dict[str, Any],
    uri: str = "bolt://localhost:7687",
    user: str = "neo4j",
    password: str = "password",
) -> list[dict[str, Any]]:
    """
    Execute a named Cypher query from cypher_queries.QUERIES and return rows.

    Example:
        rows = run_query("transitive_deps", {"asset_id": "INF-01"})
    """
    if query_name not in QUERIES:
        raise KeyError(
            f"Unknown query '{query_name}'. Available: {', '.join(QUERIES)}"
        )
    cql = QUERIES[query_name]
    driver = _driver(uri, user, password)
    with driver.session() as session:
        result = session.run(cql, **params)
        rows = [dict(record) for record in result]
    driver.close()
    return rows


# ---------------------------------------------------------------------------
# Export Cypher script (no DB needed)
# ---------------------------------------------------------------------------

def export_cypher(
    portfolio: Portfolio,
    sequencing: dict[str, Any] | None,
    path: str | Path,
) -> None:
    """
    Write a standalone .cypher script that recreates the graph in any Neo4j
    instance — useful for sharing, demos, and version control.
    """
    wave_map: dict[str, int] = {}
    completion_map: dict[str, str] = {}
    if sequencing:
        for wave in sequencing.get("waves", []):
            for asset_id in wave["assets"]:
                wave_map[asset_id] = wave["wave"]
            for asset_id, dt in wave.get("asset_completion_dates", {}).items():
                completion_map[asset_id] = dt

    lines: list[str] = [
        "// Carve-out Copilot — generated Cypher script",
        f"// Portfolio: {portfolio.planning.company}",
        "// Run in Neo4j Browser or cypher-shell\n",
        "// ── Clear existing graph ──────────────────────────────────",
        "MATCH (n) DETACH DELETE n;\n",
        "// ── Constraints ───────────────────────────────────────────",
    ]
    for c in _CONSTRAINTS:
        lines.append(c + ";")
    lines.append("")

    # TSA Services
    lines.append("// ── TSA Services ──────────────────────────────────────────")
    for tsa in portfolio.tsa_services:
        lines.append(
            f"CREATE (:TSAService {{id: '{tsa.id}', service: {json.dumps(tsa.service)}, "
            f"start_date: '{tsa.start_date}', end_date: '{tsa.end_date}', "
            f"monthly_cost: {tsa.monthly_cost}, extendable: {str(tsa.extendable).lower()}, "
            f"extension_months: {tsa.extension_months}}});"
        )
    lines.append("")

    # Licences
    lines.append("// ── Licences ──────────────────────────────────────────────")
    for lic in portfolio.licences:
        lines.append(
            f"CREATE (:Licence {{id: '{lic.id}', vendor: '{lic.vendor}', "
            f"product: {json.dumps(lic.product)}, end_date: '{lic.end_date}', "
            f"transferable: {str(lic.transferable).lower()}, annual_cost: {lic.annual_cost}}});"
        )
    lines.append("")

    # Assets
    lines.append("// ── Assets ────────────────────────────────────────────────")
    for a in portfolio.assets:
        strat = a.exit_strategy.value if a.exit_strategy else ""
        wave  = wave_map.get(a.id, 0)
        comp  = completion_map.get(a.id, "")
        lines.append(
            f"CREATE (:Asset {{id: '{a.id}', name: {json.dumps(a.name)}, "
            f"type: '{a.type.value}', owner: '{a.owner.value}', "
            f"criticality: {a.criticality}, users: {a.users}, "
            f"sensitive: {str(a.sensitive).lower()}, effort_weeks: {a.effort_weeks}, "
            f"wave: {wave}, strategy: '{strat}', planned_completion: '{comp}'}});"
        )
    lines.append("")

    # Dependency relationships
    lines.append("// ── Dependency relationships ──────────────────────────────")
    for rel in portfolio.relationships:
        lines.append(
            f"MATCH (s:Asset {{id: '{rel.source}'}}), (t:Asset {{id: '{rel.target}'}})"
        )
        desc = json.dumps(rel.description or "")
        lines.append(
            f"CREATE (s)-[:{rel.type.value} {{description: {desc}}}]->(t);"
        )
    lines.append("")

    # TSA and Licence edges
    lines.append("// ── TSA and Licence relationships ─────────────────────────")
    for a in portfolio.assets:
        if a.tsa_id:
            lines.append(
                f"MATCH (a:Asset {{id: '{a.id}'}}), (t:TSAService {{id: '{a.tsa_id}'}})"
            )
            lines.append("CREATE (a)-[:COVERED_BY_TSA]->(t);")
        if a.licence_id:
            lines.append(
                f"MATCH (a:Asset {{id: '{a.id}'}}), (l:Licence {{id: '{a.licence_id}'}})"
            )
            lines.append("CREATE (a)-[:LICENSED_UNDER]->(l);")

    Path(path).write_text("\n".join(lines), encoding="utf-8")

