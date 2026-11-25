"""Safe, parameterized Neo4j analytical query tools."""
from __future__ import annotations

import os
from typing import Any

from carveout.cypher_queries import QUERIES


def query_graph_analytics(
    query_name: str,
    params: dict[str, Any] | None = None,
    uri: str | None = None,
    user: str | None = None,
    password: str | None = None,
) -> list[dict[str, Any]]:
    """Execute allowlisted parameterized Cypher query against Neo4j if available."""
    if query_name not in QUERIES:
        raise KeyError(f"Unknown named query '{query_name}'. Available: {list(QUERIES.keys())}")

    neo4j_uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = user or os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = password or os.getenv("NEO4J_PASSWORD", "password")

    try:
        from carveout.neo4j_store import run_query
        return run_query(query_name, params or {}, uri=neo4j_uri, user=neo4j_user, password=neo4j_password)
    except Exception as exc:
        # Return graceful status when Neo4j is offline or not installed
        return [{"error": f"Neo4j query unavailable: {exc}"}]
