"""The rows the browser rebuilds the graph from.

The demo's engine panel cannot open the committed ``.rl`` file: the wasm
package opens an in-memory database or its own OPFS store and nothing else.  So
``scripts/build_wasm_seed.py`` exports the graph as rows, and the worker
rebuilds it in the engine.  These tests hold that export to the store:

* the export names the snapshot it came from, and the counts and labels match,
* the copied query files are the committed Cypher, character for character,
* rebuilding from the export with the worker's own statements answers the
  committed queries the same way the store does.

No browser and no network, so a plain ``pytest`` run covers it.  The browser
itself is checked by ``scripts/check_wasm_demo.py``.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dutypath import codes, store  # noqa: E402

SEED = ROOT / "docs" / "demo" / "wasm" / "dutypath-graph.json"
QUERIES = ROOT / "docs" / "demo" / "wasm" / "dutypath-queries.json"
CYPHER = ROOT / "cypher"
STORE = ROOT / "store" / "dutypath-rules.rl"


@pytest.fixture(scope="module")
def seed() -> dict:
    return json.loads(SEED.read_text(encoding="utf-8"))


def rebuild(seed: dict):
    """The same statements the worker sends, against an in-memory database."""
    import relate

    db = relate.connect(":memory:")
    for label, item in seed["labels"].items():
        db.execute(
            "CREATE CONSTRAINT %s_%s IF NOT EXISTS FOR (n:%s) REQUIRE n.%s IS UNIQUE"
            % (label.lower(), item["key"].lower(), label, item["key"])
        )
    for label, item in seed["labels"].items():
        db.execute("UNWIND $rows AS row CREATE (n:%s) SET n = row" % label, {"rows": item["rows"]})
    for group in seed["relationships"]:
        statement = (
            "UNWIND $pairs AS p MATCH (a:%s {%s: p[0]}), (b:%s {%s: p[1]}) "
            "CREATE (a)-[:%s]->(b)"
            % (group["from"], group["from_key"], group["to"], group["to_key"], group["type"])
        )
        db.execute(statement, {"pairs": group["pairs"]})
    return db


def run(db, name: str, params) -> list[dict]:
    text = (CYPHER / name).read_text(encoding="utf-8")
    return [dict(row) for row in db.execute(text, params)]


def test_the_export_names_the_snapshot_it_came_from(seed):
    import hashlib

    digest = hashlib.sha256(STORE.read_bytes()).hexdigest()
    assert seed["source"]["sha256"] == digest
    assert seed["source"]["bytes"] == STORE.stat().st_size


def test_the_counts_are_the_store_numbers(seed):
    assert seed["counts"] == {"nodes": 5454, "relationships": 13559}
    assert sum(len(item["rows"]) for item in seed["labels"].values()) == 5454
    assert sum(len(item["pairs"]) for item in seed["relationships"]) == 13559
    assert sorted(seed["labels"]) == sorted(
        ["Agreement", "Chapter", "DeadlineRule", "Heading", "Hs6Rate", "HsInterval",
         "OriginRule", "RateLine", "Snapshot", "Source", "Subheading"]
    )


def test_every_node_is_keyed_once(seed):
    for label, item in seed["labels"].items():
        keys = [row[item["key"]] for row in item["rows"]]
        assert len(keys) == len(set(keys)), label
        assert "" not in keys, label


def test_the_copied_queries_are_the_committed_files():
    copied = json.loads(QUERIES.read_text(encoding="utf-8"))
    names = sorted(path.name for path in CYPHER.glob("*.cypher"))
    assert sorted(copied) == names
    for name in names:
        assert copied[name] == (CYPHER / name).read_text(encoding="utf-8"), name


def test_the_rebuilt_graph_counts_itself(seed):
    db = rebuild(seed)
    assert [row["n"] for row in db.execute("MATCH (n) RETURN count(n) AS n")] == [5454]
    assert [row["r"] for row in db.execute("MATCH ()-[r]->() RETURN count(r) AS r")] == [13559]


def test_the_rebuilt_graph_answers_like_the_store(seed, tmp_path):
    """One memory graph, one copy of the store, the same questions."""
    import relate

    copy = tmp_path / "snapshot.rl"
    shutil.copyfile(STORE, copy)
    disk = relate.connect(str(copy))
    memory = rebuild(seed)
    try:
        for path in sorted((ROOT / "fixtures").glob("shipment-*.json")):
            shipment = json.loads(path.read_text(encoding="utf-8"))
            market_codes = (shipment.get("goods") or {}).get("market_codes") or {}
            norms = {market: codes.normalise(code) for market, code in market_codes.items()}
            params = {"codes": market_codes, "norms": norms}
            assert run(memory, "06-market-comparison.cypher", params) == run(
                disk, "06-market-comparison.cypher", params
            ), path.name

            rows = run(memory, "06-market-comparison.cypher", params)
            for row in rows:
                market = row["market"]
                rate_params = {"code": market_codes[market], "market": market, "agreement": row["agreement"]}
                assert run(memory, "03-rate-on-a-date.cypher", rate_params) == run(
                    disk, "03-rate-on-a-date.cypher", rate_params
                ), path.name + " " + market

            materials = [
                {
                    "id": line["id"],
                    "start_norm": codes.normalise_low(line["hts8"]),
                    "end_norm": codes.normalise(line["hts8"]),
                }
                for line in shipment.get("materials") or []
            ]
            rule = run(memory, "01-rule-for-a-good.cypher", {
                "agreement": rows[0]["agreement"], "norm": norms[rows[0]["market"]]
            })
            if rule:
                for alternative in (1, 2):
                    join_params = {"rule": rule[0]["rule"], "alternative": alternative, "materials": materials}
                    assert run(memory, "07-material-against-rule.cypher", join_params) == run(
                        disk, "07-material-against-rule.cypher", join_params
                    ), path.name + " materials"
    finally:
        disk.close()
