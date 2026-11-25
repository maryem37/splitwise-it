import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import networkx as nx
import pytest
import yaml

from carveout.loader import PortfolioError, load_portfolio, validate_portfolio
from carveout.models import Portfolio

DATA = Path(__file__).resolve().parents[1] / "data" / "portfolio_v1.yaml"


def graph(p):
    g = nx.DiGraph()
    g.add_nodes_from(a.id for a in p.assets)
    g.add_edges_from((r.source, r.target) for r in p.relationships)
    return g


def test_portfolio_is_valid():
    r = validate_portfolio(load_portfolio(DATA))
    assert r["valid"], r["errors"]
    assert r["counts"]["assets"] == 30


def test_exactly_one_cycle():
    g = graph(load_portfolio(DATA))
    cycles = [set(c) for c in nx.strongly_connected_components(g) if len(c) > 1]
    assert cycles == [{"APP-06", "APP-07"}]


def test_dangling_relationship_is_reported():
    raw = yaml.safe_load(DATA.read_text())
    raw["relationships"].append({"source": "APP-01", "target": "APP-999", "type": "CALLS"})
    r = validate_portfolio(Portfolio.model_validate(raw))
    assert not r["valid"]
    assert any("APP-999" in e for e in r["errors"])


def test_duplicate_id_is_reported():
    raw = yaml.safe_load(DATA.read_text())
    raw["assets"].append(dict(raw["assets"][0]))
    r = validate_portfolio(Portfolio.model_validate(raw))
    assert any("Duplicate" in e for e in r["errors"])


def test_bad_schema_fails_clearly(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("planning: {}\nassets: []\nrelationships: []\n")
    with pytest.raises(PortfolioError):
        load_portfolio(bad)


def test_gitignore_covers_cache_and_eval_dirs():
    gitignore = (Path(__file__).resolve().parents[1] / ".gitignore").read_text(encoding="utf-8")
    assert ".pytest_cache/" in gitignore
    assert ".deepeval/" in gitignore
