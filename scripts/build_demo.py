"""Build the static judgement screen's data bundle.

The page under docs/demo is self contained: it opens from the file system, it
makes no network call, and everything it shows was computed by the engine in
this repository.  This script is what computes it:

    python scripts/build_demo.py --store store/dutypath-rules.rl

It writes ``docs/demo/dutypath-demo.json``:

* the snapshot's identity, size and sha256, so the page can compare the hash of
  a rule file the reader selects on their own machine against the hash the
  bundle was built from,
* one entry per shipment (the five fixtures and the twelve benchmark goods),
  carrying the engine's three market comparison,
* the rate rows those ships need, exactly as the snapshot holds them: a base
  rate and a staging category for the US and the EU, and the printed yearly
  cells for Japan.

The page re-does the arithmetic on a date the reader picks, from those rows. The
origin verdict is not recomputed in the browser: it comes from the engine, and
the page says so.  ``tests/test_demo.py`` re-runs the engine and the JavaScript
and fails if either the bundle or the arithmetic drifts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dutypath import markets, store  # noqa: E402


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_cases() -> list[dict]:
    cases = []
    for path in sorted((ROOT / "fixtures").glob("shipment-*.json")):
        with open(path, encoding="utf-8") as handle:
            cases.append(json.load(handle))
    gold_path = ROOT / "benchmark" / "gold.json"
    if gold_path.exists():
        for item in json.loads(gold_path.read_text(encoding="utf-8")):
            cases.append(item["shipment"])
    return cases


def rate_rows(conn, shipment: dict) -> dict:
    rows = {}
    for market, agreement in markets.MARKET_AGREEMENT.items():
        code = markets.code_for_market(shipment, market)
        if not code:
            continue
        row = store.one(
            conn,
            "MATCH (r:RateLine {code: $code, market: $market, agreement: $agreement}) "
            "RETURN r.code AS code, r.base_rate_percent AS base_rate_percent, "
            "r.base_rate_text AS base_rate_text, r.base_rate_kind AS base_rate_kind, "
            "r.staging AS staging, r.years AS years, r.partner AS partner, r.currency AS currency "
            "ORDER BY CASE WHEN r.partner = 'KR' THEN 0 ELSE 1 END LIMIT 1",
            {"code": code, "market": market, "agreement": agreement},
        )
        if row is None:
            continue
        rows["%s:%s" % (market, code)] = {
            "market": market,
            "agreement": agreement,
            "code": code,
            "base_rate_percent": row["base_rate_percent"],
            "base_rate_text": row["base_rate_text"],
            "base_rate_kind": row["base_rate_kind"],
            "staging": row["staging"],
            "years": row["years"],
            "partner": row["partner"],
            "currency": row["currency"],
        }
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", default=os.path.join("store", "dutypath-rules.rl"))
    parser.add_argument("--out", default=os.path.join("docs", "demo", "dutypath-demo.json"))
    args = parser.parse_args()

    conn = store.connect(args.store, read_only=True)
    conn.autocommit = False
    snapshot = store.one(
        conn,
        "MATCH (s:Snapshot) RETURN s.id AS id, toString(s.as_of) AS as_of, "
        "s.rule_version AS rule_version, s.max_age_days AS max_age_days",
    )
    cases = []
    rows = {}
    for shipment in load_cases():
        report = markets.compare(conn, shipment)
        cases.append(
            {
                "id": shipment.get("import_id") or shipment.get("shipment_id"),
                "description": (shipment.get("goods") or {}).get("description", ""),
                "shipment": shipment,
                "report": report,
            }
        )
        rows.update(rate_rows(conn, shipment))
    conn.close()

    bundle = {
        "generated_by": "scripts/build_demo.py",
        "snapshot": snapshot,
        "store": {
            "path": args.store,
            "bytes": os.path.getsize(args.store),
            "sha256": sha256(args.store),
        },
        "cases": cases,
        "rates": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, indent=1, ensure_ascii=False), encoding="utf-8")
    # A classic script carrying the same object, so the page also opens from
    # the file system, where fetch of a neighbouring file is blocked.
    script = out.with_name("dutypath-demo.js")
    script.write_text(
        "window.DUTYPATH_DEMO = " + json.dumps(bundle, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "out": str(out),
        "cases": len(cases),
        "rate_rows": len(rows),
        "store_sha256": bundle["store"]["sha256"],
        "bytes": out.stat().st_size,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
