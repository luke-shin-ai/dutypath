"""Write the rule graph as the data a browser can rebuild it from.

The demo runs the real Relate engine in the tab (``@relate/relate-wasm``).
That package opens an in-memory database or its own OPFS store, and it has no
call that opens an existing ``.rl`` file, so the page cannot hand it the
snapshot bytes.  What it can do is rebuild the same graph inside the engine
from the rows this script exports, then answer the same Cypher the CLI answers.

    python scripts/build_wasm_seed.py --store store/dutypath-rules.rl

It writes ``docs/demo/wasm/dutypath-graph.json``:

* the identity of the snapshot it was exported from (path, bytes, sha256), so
  a reader can check the export against the committed file,
* every node, grouped by label, with the property its label is keyed on,
* every relationship, grouped by type and the two labels it joins, as pairs of
  those keys.

The export is read only.  ``final_checkpoint`` runs when a store is closed, so
the script opens a copy in a temporary file and leaves the committed ``.rl``
alone.  ``tests/test_wasm_seed.py`` rebuilds the graph from this file with the
same statements the worker runs and compares its answers with the store.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# One key per label, the same one the store's constraints require.
KEYS = {
    "Agreement": "code",
    "Chapter": "code",
    "DeadlineRule": "id",
    "Heading": "code",
    "Hs6Rate": "id",
    "HsInterval": "id",
    "OriginRule": "id",
    "RateLine": "id",
    "Snapshot": "id",
    "Source": "id",
    "Subheading": "code",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def plain(value):
    """JSON shaped copy of a property value: dates become ISO strings."""
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, list):
        return [plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", default=os.path.join("store", "dutypath-rules.rl"))
    parser.add_argument("--out", default=os.path.join("docs", "demo", "wasm", "dutypath-graph.json"))
    args = parser.parse_args()

    store_path = Path(args.store)
    source_sha = sha256(store_path)

    import relate  # the relate-db wheel, the same engine the .rl was built with

    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "snapshot.rl"
        shutil.copyfile(store_path, copy)
        conn = relate.connect(str(copy))

        labels = {}
        for label, key in KEYS.items():
            rows = [
                plain(dict(row)["properties"])
                for row in conn.execute(
                    "MATCH (n:%s) RETURN properties(n) AS properties ORDER BY n.%s" % (label, key)
                )
            ]
            if not rows:
                continue
            keys = [str(row.get(key, "")) for row in rows]
            if len(set(keys)) != len(keys) or "" in keys:
                raise SystemExit("label %s is not uniquely keyed on %s" % (label, key))
            labels[label] = {"key": key, "rows": rows}

        relationships = []
        groups = [
            dict(row)
            for row in conn.execute(
                "MATCH (a)-[r]->(b) "
                "RETURN type(r) AS type, labels(a)[0] AS from_label, labels(b)[0] AS to_label, "
                "count(*) AS count ORDER BY type, from_label, to_label"
            )
        ]
        for group in groups:
            kind = group["type"]
            from_label = group["from_label"]
            to_label = group["to_label"]
            from_key = KEYS[from_label]
            to_key = KEYS[to_label]
            rows = [
                dict(row)
                for row in conn.execute(
                    "MATCH (a:%s)-[:%s]->(b:%s) RETURN a.%s AS from_key, b.%s AS to_key "
                    "ORDER BY from_key, to_key"
                    % (from_label, kind, to_label, from_key, to_key)
                )
            ]
            relationships.append(
                {
                    "type": kind,
                    "from": from_label,
                    "to": to_label,
                    "from_key": from_key,
                    "to_key": to_key,
                    "pairs": [[str(row["from_key"]), str(row["to_key"])] for row in rows],
                }
            )
        conn.close()

    node_count = sum(len(item["rows"]) for item in labels.values())
    rel_count = sum(len(item["pairs"]) for item in relationships)
    payload = {
        "generated_by": "scripts/build_wasm_seed.py",
        "engine": "relate",
        "source": {
            "path": args.store,
            "bytes": store_path.stat().st_size,
            "sha256": source_sha,
        },
        "counts": {"nodes": node_count, "relationships": rel_count},
        "labels": labels,
        "relationships": relationships,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # The worker runs the committed query files verbatim: the site serves
    # docs/ as its root, so cypher/ is not reachable from the page.  The text is
    # copied, not retyped, and tests/test_wasm_seed.py compares the copy with
    # the files.
    cypher_dir = ROOT / "cypher"
    queries = {}
    for name in sorted(os.listdir(cypher_dir)):
        if name.endswith(".cypher"):
            queries[name] = (cypher_dir / name).read_text(encoding="utf-8")
    queries_out = out.with_name("dutypath-queries.json")
    queries_out.write_text(json.dumps(queries, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({
        "out": str(out),
        "nodes": node_count,
        "relationships": rel_count,
        "labels": {label: len(item["rows"]) for label, item in labels.items()},
        "bytes": out.stat().st_size,
        "queries": str(queries_out),
        "source_sha256": source_sha,
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
