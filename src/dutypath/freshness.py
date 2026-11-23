"""Is this snapshot still young enough to trust, and how old are its numbers?

The point of a pulled rulebook is that it ages.  A verdict computed on a
snapshot older than the one the hub now holds is not wrong, it is out of date,
and the report has to say which of the two it is.

One date is not enough to say that.  The snapshot has a date, and each block of
numbers in it came from a document that has its own, which can be years older.
An answer that says only "the snapshot is nine days old" leaves a reader to
believe every figure in it is nine days old; the applied MFN rate of the United
States is the WITS value for 2023, and the claim window is a 2025 strategy
paper.  So ``judge`` takes the component dates and prints them beside the
snapshot date, with the gap in days, whatever the status is.
"""

from __future__ import annotations

from datetime import date

from . import store

STALE = "STALE_SNAPSHOT: resync required"

VINTAGE_QUERY = """
MATCH (r:Hs6Rate)-[:CITED_FROM]->(src:Source)
RETURN 'applied MFN rate' AS block, r.market AS market, src.id AS source, src.title AS title,
       toString(src.as_of) AS as_of, count(r) AS rows
ORDER BY src.id
"""

DEADLINE_VINTAGE_QUERY = """
MATCH (d:DeadlineRule)-[:CITED_FROM]->(src:Source)
RETURN 'post import claim window' AS block, 'ALL' AS market, src.id AS source, src.title AS title,
       toString(src.as_of) AS as_of, count(d) AS rows
ORDER BY src.id
"""

MARKET_NAMES = {"US": "United States", "EU": "European Union", "JP": "Japan"}


def vintages(conn, snapshot: dict | None = None) -> list[dict]:
    """The date each block of numbers speaks for, against the snapshot date.

    Two blocks carry a date of their own that the snapshot date does not cover:
    the applied MFN table, which is a WITS query by year, and the deadline row,
    which is a strategy paper of 2025.  A reader pricing an entry on either needs
    the date of the figure, not the date of the file.
    """
    snap_date = None
    if snapshot and snapshot.get("as_of"):
        snap_date = date.fromisoformat(str(snapshot["as_of"])[:10])
    out = []
    for statement in (VINTAGE_QUERY, DEADLINE_VINTAGE_QUERY):
        for row in store.rows(conn, statement):
            as_of = str(row["as_of"])[:10] if row.get("as_of") else None
            gap = (snap_date - date.fromisoformat(as_of)).days if (snap_date and as_of) else None
            out.append(
                {
                    "block": row["block"],
                    "component": _component(row["block"], row["market"]),
                    "market": row["market"],
                    "source": row["source"],
                    "source_title": row["title"],
                    "as_of": as_of,
                    "rows": row["rows"],
                    "days_before_snapshot_date": gap,
                }
            )
    return out


def judge(snapshot: dict | None, on: date, components: list[dict] | None = None) -> dict:
    if not snapshot:
        return {"id": None, "status": STALE, "reason": "the store has no snapshot row"}
    as_of = date.fromisoformat(str(snapshot["as_of"])[:10])
    max_age = _max_age(snapshot)
    age = (on - as_of).days
    if age < 0:
        # The snapshot was taken after the day it is being asked about, so its
        # lines and its rates are not the ones that stood on that day.  That is
        # not freshness, and a negative age is not a number to print.
        return _result(snapshot, as_of, max_age, 0, False, "BEFORE_SNAPSHOT",
                       "the assessment date %s is earlier than the snapshot date %s, so the "
                       "snapshot's lines and rates do not speak for it"
                       % (on.isoformat(), as_of.isoformat()), components)
    fresh = age <= max_age
    return _result(
        snapshot, as_of, max_age, age, fresh, "FRESH" if fresh else STALE,
        "the snapshot is %d %s old and the limit is %d" % (age, "day" if age == 1 else "days", max_age),
        components,
    )


def _result(snapshot: dict, as_of: date, max_age: int, age: int, fresh: bool, status: str,
            reason: str, components: list[dict] | None) -> dict:
    dated = [item for item in (components or []) if item.get("as_of")]
    caveats = [
        _caveat(item, as_of)
        for item in dated
        if (item.get("days_before_snapshot_date") or 0) > 0
    ]
    return {
        "id": snapshot["id"],
        "as_of": as_of.isoformat(),
        "rule_version": snapshot.get("rule_version"),
        "max_age_days": max_age,
        "age_days": age,
        "fresh": fresh,
        "status": status,
        "reason": reason,
        "data_vintage": dated,
        "caveats": caveats,
    }


def _component(block: str, market: str) -> str:
    if block == "applied MFN rate":
        return "%s applied MFN rate" % MARKET_NAMES.get(market, market)
    return "The post import claim window" if block == "post import claim window" else block


def _caveat(item: dict, snap_date: date) -> str:
    gap = item.get("days_before_snapshot_date") or 0
    if item.get("block") == "post import claim window":
        return (
            "%s: the period comes from a Ministry of Economy and Finance paper dated %s, %d days "
            "before the snapshot date %s" % (item["component"], item["as_of"], gap, snap_date.isoformat())
        )
    return (
        "%s: the values are the WITS figures for %s, as of %s, %d days before the snapshot date %s"
        % (item["component"], item["as_of"][:4], item["as_of"], gap, snap_date.isoformat())
    )


def _max_age(snapshot: dict) -> int:
    for key in ("max_age_days", "max_age"):
        if snapshot.get(key) is not None:
            return int(snapshot[key])
    return 120
