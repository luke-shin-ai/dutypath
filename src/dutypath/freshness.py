"""Is this snapshot still young enough to trust?

The point of a pulled rulebook is that it ages.  A verdict computed on a
snapshot older than the one the hub now holds is not wrong, it is out of date,
and the report has to say which of the two it is.
"""

from __future__ import annotations

from datetime import date

STALE = "STALE_SNAPSHOT: resync required"


def judge(snapshot: dict | None, on: date) -> dict:
    if not snapshot:
        return {"id": None, "status": STALE, "reason": "the store has no snapshot row"}
    as_of = date.fromisoformat(str(snapshot["as_of"])[:10])
    max_age = _max_age(snapshot)
    age = (on - as_of).days
    if age < 0:
        # The snapshot was taken after the day it is being asked about, so its
        # lines and its rates are not the ones that stood on that day.  That is
        # not freshness, and a negative age is not a number to print.
        return {
            "id": snapshot["id"],
            "as_of": as_of.isoformat(),
            "rule_version": snapshot.get("rule_version"),
            "max_age_days": max_age,
            "age_days": 0,
            "fresh": False,
            "status": "BEFORE_SNAPSHOT",
            "reason": "the assessment date %s is earlier than the snapshot date %s, so the "
                      "snapshot's lines and rates do not speak for it" % (on.isoformat(), as_of.isoformat()),
        }
    fresh = age <= max_age
    return {
        "id": snapshot["id"],
        "as_of": as_of.isoformat(),
        "rule_version": snapshot.get("rule_version"),
        "max_age_days": max_age,
        "age_days": age,
        "fresh": fresh,
        "status": "FRESH" if fresh else STALE,
        "reason": "the snapshot is %d %s old and the limit is %d"
        % (age, "day" if age == 1 else "days", max_age),
    }


def _max_age(snapshot: dict) -> int:
    for key in ("max_age_days", "max_age"):
        if snapshot.get(key) is not None:
            return int(snapshot[key])
    return 120
