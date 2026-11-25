"""Named Cypher query catalogue for the carve-out dependency graph.

Each entry in QUERIES is a parameterised Cypher string.
Run them with neo4j_store.run_query(name, params) or paste them
directly into Neo4j Browser / cypher-shell.
"""

QUERIES: dict[str, str] = {

    # ------------------------------------------------------------------
    # 1. TRANSITIVE DEPENDENCIES
    #    "What must be ready BEFORE this asset can be migrated?"
    #    Returns all assets reachable by following any dependency edge.
    # ------------------------------------------------------------------
    "transitive_deps": """
        MATCH (a:Asset {id: $asset_id})-[*1..]->(dep:Asset)
        RETURN DISTINCT dep.id   AS id,
                        dep.name AS name,
                        dep.wave AS wave,
                        dep.strategy AS strategy
        ORDER BY dep.wave, dep.id
    """,

    # ------------------------------------------------------------------
    # 2. TRANSITIVE IMPACT
    #    "What breaks if this asset is not ready on time?"
    #    Returns all assets that (directly or transitively) depend on it.
    # ------------------------------------------------------------------
    "transitive_impact": """
        MATCH (dep:Asset)-[*1..]->(a:Asset {id: $asset_id})
        RETURN DISTINCT dep.id   AS id,
                        dep.name AS name,
                        dep.wave AS wave,
                        dep.strategy AS strategy
        ORDER BY dep.wave, dep.id
    """,

    # ------------------------------------------------------------------
    # 3. ASSETS IN CONFLICT WITH TSA DEADLINES
    #    "Which assets are planned to complete AFTER their TSA expires?"
    # ------------------------------------------------------------------
    "tsa_conflicts": """
        MATCH (a:Asset)-[:COVERED_BY_TSA]->(t:TSAService)
        WHERE a.planned_completion > t.end_date
          AND a.planned_completion <> ''
        RETURN a.id                AS asset_id,
               a.name              AS asset_name,
               a.wave              AS wave,
               t.id                AS tsa_id,
               t.service           AS tsa_service,
               t.end_date          AS tsa_end,
               t.extendable        AS extendable,
               a.planned_completion AS planned_completion
        ORDER BY a.wave, a.id
    """,

    # ------------------------------------------------------------------
    # 4. LICENCE EXPIRY RISK
    #    "Which assets have a licence that expires before their cutover?"
    # ------------------------------------------------------------------
    "licence_conflicts": """
        MATCH (a:Asset)-[:LICENSED_UNDER]->(l:Licence)
        WHERE a.planned_completion > l.end_date
          AND a.planned_completion <> ''
        RETURN a.id                AS asset_id,
               a.name              AS asset_name,
               a.wave              AS wave,
               l.id                AS licence_id,
               l.product           AS product,
               l.end_date          AS licence_expiry,
               a.planned_completion AS planned_completion
        ORDER BY a.wave, a.id
    """,

    # ------------------------------------------------------------------
    # 5. CRITICAL PATH (longest wave chain)
    #    "What is the sequence of waves that determines the project end date?"
    # ------------------------------------------------------------------
    "critical_path": """
        MATCH path = (start:Asset)-[*]->(end:Asset)
        WHERE NOT ()-[]->(start)
          AND NOT (end)-[]->()
        WITH path, length(path) AS depth
        ORDER BY depth DESC
        LIMIT 1
        RETURN [n IN nodes(path) | n.id + ' (W' + toString(n.wave) + ')'] AS critical_path,
               depth
    """,

    # ------------------------------------------------------------------
    # 6. CIRCULAR DEPENDENCIES (cycle detection)
    #    "Which assets call each other and must be migrated together?"
    # ------------------------------------------------------------------
    "cycles": """
        MATCH (a:Asset)-[r]->(b:Asset)-[r2]->(a)
        RETURN DISTINCT a.id AS asset_1, b.id AS asset_2,
               type(r) AS rel_1, type(r2) AS rel_2
    """,

    # ------------------------------------------------------------------
    # 7. SHARED ASSETS (blocker analysis)
    #    "Which parent-owned / shared assets are holding up the most assets?"
    # ------------------------------------------------------------------
    "shared_blockers": """
        MATCH (blocker:Asset {owner: 'shared'})<-[*1..]-(dependent:Asset)
        WITH blocker, count(DISTINCT dependent) AS blocked_count
        ORDER BY blocked_count DESC
        RETURN blocker.id       AS id,
               blocker.name     AS name,
               blocker.wave     AS wave,
               blocker.strategy AS strategy,
               blocked_count
    """,

    # ------------------------------------------------------------------
    # 8. ASSETS BY WAVE
    #    "Show me all assets in a given wave with their strategy."
    # ------------------------------------------------------------------
    "assets_by_wave": """
        MATCH (a:Asset {wave: $wave})
        RETURN a.id                AS id,
               a.name              AS name,
               a.type              AS type,
               a.owner             AS owner,
               a.strategy          AS strategy,
               a.criticality       AS criticality,
               a.planned_completion AS planned_completion
        ORDER BY a.type, a.id
    """,

    # ------------------------------------------------------------------
    # 9. TSA COST PER SERVICE
    #    "How much does each TSA service cost based on planned durations?"
    # ------------------------------------------------------------------
    "tsa_cost_summary": """
        MATCH (a:Asset)-[:COVERED_BY_TSA]->(t:TSAService)
        WHERE a.planned_completion <> ''
        WITH t,
             max(a.planned_completion) AS latest_cutover,
             count(a)                  AS asset_count
        RETURN t.id              AS tsa_id,
               t.service         AS service,
               t.monthly_cost    AS monthly_cost,
               t.end_date        AS contracted_end,
               t.extendable      AS extendable,
               latest_cutover,
               asset_count
        ORDER BY t.id
    """,

    # ------------------------------------------------------------------
    # 10. SENSITIVE DATA ASSETS
    #     "Which assets hold personal or financial data (GDPR / compliance)?"
    # ------------------------------------------------------------------
    "sensitive_assets": """
        MATCH (a:Asset {sensitive: true})
        OPTIONAL MATCH (a)-[:COVERED_BY_TSA]->(t:TSAService)
        RETURN a.id       AS id,
               a.name     AS name,
               a.type     AS type,
               a.owner    AS owner,
               a.wave     AS wave,
               a.strategy AS strategy,
               t.id       AS tsa_id
        ORDER BY a.wave, a.id
    """,

    # ------------------------------------------------------------------
    # 11. WAVE DEPENDENCY MAP
    #     "Which waves must complete before a given wave can start?"
    # ------------------------------------------------------------------
    "wave_predecessors": """
        MATCH (a:Asset {wave: $wave})-[*1..]->(dep:Asset)
        WHERE dep.wave < $wave
        RETURN DISTINCT dep.wave AS predecessor_wave
        ORDER BY dep.wave
    """,

    # ------------------------------------------------------------------
    # 12. FULL DEPENDENCY GRAPH EXPORT
    #     "Return every node and relationship for external visualisation."
    # ------------------------------------------------------------------
    "full_graph": """
        MATCH (a:Asset)
        OPTIONAL MATCH (a)-[r]->(b)
        RETURN a.id   AS from_id,
               a.name AS from_name,
               a.wave AS from_wave,
               type(r) AS rel_type,
               b.id   AS to_id,
               b.name AS to_name
        ORDER BY a.wave, a.id
    """,
}

