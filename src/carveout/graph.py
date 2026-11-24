"""Portfolio dependency graph and deterministic graph queries.

An edge ``source -> target`` means source depends on target.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import networkx as nx

from .models import Owner, Portfolio


def build_graph(portfolio: Portfolio) -> nx.DiGraph:
    graph = nx.DiGraph()
    for asset in portfolio.assets:
        graph.add_node(asset.id, **asset.model_dump(mode="json"))
    for relation in portfolio.relationships:
        graph.add_edge(
            relation.source,
            relation.target,
            type=relation.type.value,
            description=relation.description or "",
        )
    return graph


def dependencies(graph: nx.DiGraph, asset_id: str) -> list[str]:
    """Assets that ``asset_id`` depends on (directly or transitively)."""
    _require_asset(graph, asset_id)
    return sorted(nx.descendants(graph, asset_id))


def impact(graph: nx.DiGraph, asset_id: str) -> list[str]:
    """Assets that depend on ``asset_id`` and may be affected if it moves."""
    _require_asset(graph, asset_id)
    return sorted(nx.ancestors(graph, asset_id))


def shared_assets(graph: nx.DiGraph) -> list[str]:
    return sorted(
        asset_id for asset_id, attrs in graph.nodes(data=True)
        if attrs.get("owner") == Owner.SHARED.value
    )


def cycles(graph: nx.DiGraph) -> list[list[str]]:
    return sorted(
        (sorted(component) for component in nx.strongly_connected_components(graph)
         if len(component) > 1),
        key=lambda component: component[0],
    )


def export_graph(graph: nx.DiGraph, path: str | Path) -> None:
    """Write portable JSON graph data for downstream reports and visualizers."""
    data: dict[str, Any] = nx.node_link_data(graph)
    Path(path).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def export_html(graph: nx.DiGraph, path: str | Path) -> None:
    """Write a self-contained graph page using the vis-network CDN."""
    nodes = [
        {"id": asset_id, "label": f"{asset_id} · {attrs.get('name', '')}",
         "group": attrs.get("owner", "unknown"), "title": attrs.get("type", "")}
        for asset_id, attrs in sorted(graph.nodes(data=True))
    ]
    edges = [
        {"from": source, "to": target, "label": attrs.get("type", "")}
        for source, target, attrs in sorted(graph.edges(data=True))
    ]
    payload = json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False)
    html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Nordia Retail dependency graph</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>body{{font:14px system-ui;margin:0}}#graph{{height:95vh;border:1px solid #ddd}}</style></head>
<body><h1>Portfolio dependency graph</h1><div id="graph"></div>
<script>const data={payload};const container=document.getElementById('graph');
new vis.Network(container,{{nodes:new vis.DataSet(data.nodes),edges:new vis.DataSet(data.edges)}},
{{layout:{{improvedLayout:true}},physics:{{stabilization:true}},edges:{{arrows:'to',smooth:true}}}});</script></body></html>'''
    Path(path).write_text(html, encoding="utf-8")


def _require_asset(graph: nx.DiGraph, asset_id: str) -> None:
    if asset_id not in graph:
        raise KeyError(f"Unknown asset id: {asset_id}")
