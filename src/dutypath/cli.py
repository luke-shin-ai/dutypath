"""Command line for DutyPath.

    dutypath seed              build store/dutypath-rules.rl from data/
    dutypath info              what the snapshot covers, and where it came from
    dutypath assess            assess one shipment file
    dutypath verify-zero-leak  run an assessment and prove the store is untouched
    dutypath footprint         measure the snapshot and print the numbers
    dutypath freshness         judge the snapshot against a date
    dutypath pull-query        print the Cypher a hub uses to serve a market
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

from . import assess as assessment
from . import bom, build, duty, freshness, leak, store

DEFAULT_DATA = os.path.join("data", "extract-2026-11-22")


def _store(args) -> str:
    return args.store or os.environ.get("DUTYPATH_STORE") or store.DEFAULT_STORE


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def cmd_seed(args) -> int:
    path = _store(args)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    if os.path.exists(path):
        os.remove(path)
    conn = store.connect(path)
    conn.autocommit = False
    try:
        counts = build.build(conn, args.data)
        conn.commit()
    finally:
        conn.close()
    print(f"built {path}")
    print(json.dumps(counts, indent=2))
    print(f"bytes {os.path.getsize(path)}")
    return 0


def cmd_info(args) -> int:
    conn = store.connect(_store(args), read_only=True)
    conn.autocommit = False
    try:
        snapshot = store.one(
            conn,
            "MATCH (s:Snapshot) RETURN s.id AS id, toString(s.as_of) AS as_of, "
            "s.rule_version AS rule_version, s.max_age_days AS max_age_days, s.chapters AS chapters",
        )
        agreements = store.rows(
            conn,
            "MATCH (a:Agreement) RETURN a.code AS code, a.market AS market, a.coverage AS coverage, "
            "a.approved_exporter_required AS approved_exporter_required ORDER BY a.code",
        )
        rules = store.rows(
            conn,
            "MATCH (r:OriginRule)-[:FOR]->(a:Agreement) RETURN a.code AS agreement, "
            "count(r) AS rules, sum(CASE WHEN r.structured THEN 0 ELSE 1 END) AS unstructured "
            "ORDER BY a.code",
        )
        rates = store.rows(
            conn,
            "MATCH (r:RateLine)-[:FOR]->(a:Agreement) RETURN a.code AS agreement, count(r) AS lines "
            "ORDER BY a.code",
        )
        sources = store.rows(
            conn, "MATCH (s:Source) RETURN s.id AS id, s.title AS title, toString(s.as_of) AS as_of ORDER BY s.id"
        )
        counts = store.label_counts(conn)
        relationships = store.relationship_count(conn)
    finally:
        conn.close()
    print(json.dumps(
        {
            "snapshot": snapshot,
            "counts": counts,
            "relationships": relationships,
            "agreements": agreements,
            "origin_rules": rules,
            "rate_lines": rates,
            "sources": sources,
        },
        indent=2,
        ensure_ascii=False,
    ))
    return 0


def cmd_assess(args) -> int:
    shipment = _load(args.shipment)
    on = date.fromisoformat(args.on) if args.on else None
    conn = store.connect(_store(args), read_only=True)
    conn.autocommit = False
    try:
        report = assessment.assess(conn, shipment, on)
    finally:
        conn.close()
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        return 0
    print(_render(report))
    return 0


def cmd_verify(args) -> int:
    shipment = _load(args.shipment)
    result = leak.verify(_store(args), shipment)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["pass"] else 1


def cmd_footprint(args) -> int:
    from . import footprint

    result = footprint.measure(_store(args), repeats=args.repeats)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_freshness(args) -> int:
    on = date.fromisoformat(args.on) if args.on else date.today()
    conn = store.connect(_store(args), read_only=True)
    conn.autocommit = False
    try:
        snapshot = store.one(
            conn,
            "MATCH (s:Snapshot) RETURN s.id AS id, toString(s.as_of) AS as_of, "
            "s.rule_version AS rule_version, s.max_age_days AS max_age_days",
        )
    finally:
        conn.close()
    print(json.dumps(freshness.judge(snapshot, on), indent=2))
    return 0


def cmd_pull(args) -> int:
    path = os.path.join("neo4j", "pull_rules.cypher")
    with open(path, encoding="utf-8") as handle:
        print(handle.read() % {"market": args.market})
    return 0


def _render(report: dict) -> str:
    lines = []
    shipment = report["shipment"]
    goods = shipment["goods"]
    lines.append(
        "%s  %s  %s  %s %s"
        % (
            shipment["id"],
            goods["hts8"],
            goods["description"][:60],
            goods["declared_value"],
            goods["currency"],
        )
    )
    lines.append(
        "market %s  assessed %s  snapshot %s (%s, %s)"
        % (
            shipment["market_name"],
            shipment["assessed_on"],
            report["snapshot"]["id"],
            report["snapshot"]["as_of"],
            report["snapshot"]["status"],
        )
    )
    lines.append("")
    for item in report["agreements"]:
        origin = item["origin"]
        lines.append("%-7s origin %-16s rule %s" % (item["agreement"], origin["verdict"],
                                                   (origin.get("rule") or {}).get("code_from", "-")))
        seen = set()
        for step in origin.get("path", [])[:4]:
            if step not in seen:
                lines.append("        path   %s" % step)
                seen.add(step)
        if origin.get("missing"):
            for need in origin["missing"][:3]:
                lines.append("        need   %s" % need)
        rate = item["rate"]
        if rate["percent"] is None:
            lines.append("        rate   not in snapshot: %s" % rate["reason"])
        else:
            lines.append("        rate   %.1f%% (%s, %s)" % (rate["percent"], rate["basis"], rate.get("reason")))
        documents = item["documents"]
        if documents["status"] != "NOT_REQUIRED":
            lines.append("        docs   %s %s" % (documents["status"], documents.get("reason", "")))
        claim = item["claim"]
        if claim["allowed"]:
            lines.append("        claim  allowed, duty %s" % claim["duty"])
        else:
            lines.append("        claim  blocked: %s" % claim["blocked_by"])
        lines.append("")
    mfn = report["mfn"]
    lines.append(
        "MFN     %s%% (%s, as of %s)"
        % (mfn["percent"], mfn["basis"], mfn.get("as_of", "-"))
    )
    claim = report["claim"]
    lines.append("")
    lines.append("decision  %s" % claim["decision"])
    lines.append("duty      %s %s" % (claim["duty"], goods["currency"]))
    lines.append("saving    %s %s" % (claim["saving"], goods["currency"]))
    if claim["exposure"]:
        lines.append("exposure  %s %s" % (claim["exposure"], goods["currency"]))
    lines.append("reason    %s" % claim["reason"])
    deadline = report["deadline"]
    if deadline.get("deadline"):
        lines.append(
            "claim window  %s (%s, %s)"
            % (deadline["deadline"], deadline["status"], deadline["legal_ref"])
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dutypath", description=__doc__)
    parser.add_argument("--store", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed", help="build the store from the extracted sources")
    seed.add_argument("--data", default=DEFAULT_DATA)
    seed.add_argument("--store", default=argparse.SUPPRESS)
    seed.set_defaults(func=cmd_seed)

    info = sub.add_parser("info", help="snapshot metadata, coverage and sources")
    info.add_argument("--store", default=argparse.SUPPRESS)
    info.set_defaults(func=cmd_info)

    run = sub.add_parser("assess", help="assess one shipment file")
    run.add_argument("--shipment", required=True)
    run.add_argument("--on", default=None)
    run.add_argument("--json", action="store_true")
    run.add_argument("--store", default=argparse.SUPPRESS)
    run.set_defaults(func=cmd_assess)

    verify = sub.add_parser("verify-zero-leak", help="prove the store is unchanged by an assessment")
    verify.add_argument("--shipment", required=True)
    verify.add_argument("--store", default=argparse.SUPPRESS)
    verify.set_defaults(func=cmd_verify)

    foot = sub.add_parser("footprint", help="measure the snapshot")
    foot.add_argument("--repeats", type=int, default=30)
    foot.add_argument("--store", default=argparse.SUPPRESS)
    foot.set_defaults(func=cmd_footprint)

    fresh = sub.add_parser("freshness", help="judge the snapshot against a date")
    fresh.add_argument("--on", default=None)
    fresh.add_argument("--store", default=argparse.SUPPRESS)
    fresh.set_defaults(func=cmd_freshness)

    pull = sub.add_parser("pull-query", help="print the hub query a market is served with")
    pull.add_argument("--market", default="US")
    pull.set_defaults(func=cmd_pull)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
