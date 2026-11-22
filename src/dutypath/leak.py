"""Proof that a run leaves the rule book exactly as it found it.

Three observations, each one a number a reader can repeat:

1. the sha256 of the store file before and after an assessment,
2. the label counts in the store, which must show zero shipment, material,
   good, party or verdict nodes,
3. the fact that the material list only ever existed in memory.

Anything the run writes goes to standard output.  This is the whole of the
claim, so there is nothing else to check.
"""

from __future__ import annotations

from datetime import date

from . import assess, bom, store

FORBIDDEN = ("Shipment", "Material", "BomNode", "Good", "Party", "Verdict")


def verify(store_path: str, shipment: dict, on: date | None = None) -> dict:
    before = store.file_sha256(store_path)
    counts_before = _counts(store_path)

    rules_conn = store.connect(store_path, read_only=True)
    order = bom.build(shipment)
    report = assess.assess(rules_conn, shipment, on)
    after_counts = store.label_counts(rules_conn)
    forbidden = {label: after_counts.get(label, 0) for label in FORBIDDEN}
    order.close()
    rules_conn.close()

    after = store.file_sha256(store_path)
    counts_after = _counts(store_path)

    return {
        "store": store_path,
        "sha256_before": before,
        "sha256_after": after,
        "hash_unchanged": bool(before) and before == after,
        "labels_before": counts_before,
        "labels_after": counts_after,
        "labels_unchanged": counts_before == counts_after,
        "forbidden_labels": forbidden,
        "no_shipment_rows": all(count == 0 for count in forbidden.values()),
        "verdict": report["claim"]["decision"],
        "pass": bool(before)
        and before == after
        and counts_before == counts_after
        and all(count == 0 for count in forbidden.values()),
    }


def _counts(path: str) -> dict:
    conn = store.connect(path, read_only=True)
    try:
        return store.label_counts(conn)
    finally:
        conn.close()
