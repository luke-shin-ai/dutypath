"""The staging schedule.

Annex 2-B of the KORUS chapter 2 says what each staging category does to the
base rate and when.  The arithmetic here is that paragraph, nothing else:

* year one is the year the Agreement entered into force (2012),
* from year two each stage takes effect on January 1,
* interim rates are rounded down to the nearest tenth of a percentage point,
* categories A to K are the equal stage, percentage and freeze schedules.

A category the paragraph does not define returns ``None`` rather than a guess.
"""

from __future__ import annotations

from datetime import date

ENTRY_INTO_FORCE = date(2012, 3, 15)

EQUAL_STAGES = {"A": 1, "B": 2, "C": 3, "D": 5, "E": 6, "F": 7, "G": 10, "H": 15}

# Category I: cumulative share of the base rate removed, by year of the agreement.
PERCENT_OF_BASE_REMOVED = {
    1: 5, 2: 10, 3: 17, 4: 24, 5: 31, 6: 41, 7: 51, 8: 63, 9: 80, 10: 100,
}


def year_of(on: date) -> int | None:
    if on < ENTRY_INTO_FORCE:
        return None
    return on.year - ENTRY_INTO_FORCE.year + 1


def round_down(value: float) -> float:
    """Down to a tenth, after taking the binary noise off the product."""
    return int(round(value, 6) * 10 + 1e-9) / 10.0


def staged_rate(base_percent: float | None, staging: str | None, on: date) -> dict:
    """Preferential rate for one tariff line on one date.

    Returns ``{"percent": float | None, "reason": str}``.  A ``None`` percent
    means the schedule in this snapshot cannot answer for that date.
    """
    if base_percent is None:
        return {"percent": None, "reason": "base rate is not an ad valorem percentage"}
    if not staging:
        return {"percent": None, "reason": "no staging category on the line"}
    year = year_of(on)
    if year is None:
        return {
            "percent": None,
            "reason": "date is before the Agreement entered into force on %s" % ENTRY_INTO_FORCE,
        }
    category = staging.strip().upper()

    if category == "K":
        return {"percent": 0.0, "reason": "category K keeps duty free treatment"}
    if category == "A":
        return {"percent": 0.0, "reason": "category A eliminated on entry into force"}
    if category in EQUAL_STAGES:
        stages = EQUAL_STAGES[category]
        if year >= stages:
            return {
                "percent": 0.0,
                "reason": "category %s is duty free from January 1 of year %d" % (category, stages),
            }
        rate = round_down(base_percent * (stages - year) / stages)
        return {
            "percent": rate,
            "reason": "category %s, stage %d of %d equal annual cuts" % (category, year, stages),
        }
    if category == "I":
        removed = PERCENT_OF_BASE_REMOVED.get(min(year, 10), 100)
        rate = round_down(base_percent * (100 - removed) / 100)
        return {
            "percent": rate,
            "reason": "category I removes %d percent of the base rate by year %d" % (removed, min(year, 10)),
        }
    if category == "J":
        if year <= 8:
            return {"percent": base_percent, "reason": "category J holds the base rate through year eight"}
        if year >= 12:
            return {"percent": 0.0, "reason": "category J is duty free from January 1 of year 12"}
        rate = round_down(base_percent * (12 - year) / 4)
        return {"percent": rate, "reason": "category J, stage %d of four cuts" % (year - 8)}
    return {"percent": None, "reason": "staging category %r is not defined in Annex 2-B" % staging}
