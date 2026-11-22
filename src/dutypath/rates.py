"""The staging schedule.

Three agreements, three ways of saying the same thing, and the arithmetic of
each one is the arithmetic of the document that prints it:

* **KORUS.**  Annex 2-B of the chapter 2 says what each staging category does
to the base rate and when.  Year one is the year the Agreement entered into
force (2012), from year two each stage takes effect on January 1, interim rates
are rounded down to a tenth of a percentage point, and categories A to K are
the equal stage, percentage and freeze schedules.

* **Korea-EU.**  Annex 2-A prints the categories as numbers.  Category ``0`` is
eliminated on entry into force; category ``n`` is removed in n+1 equal annual
stages beginning on the date of entry into force, so the line is free on the
first day of year n+1; ``E`` stays at the base rate; ``X`` carries no
obligation.  Year one begins on 1 July 2011, and interim rates are rounded
down to a tenth.

* **RCEP, Japan.**  The schedule prints a rate for every year rather than a
category, so nothing is computed: the row's own cell for that year is used, and
a cell that prints ``U`` means the line is excluded for that partner.

A category the document does not define returns ``None`` rather than a guess.
"""


from __future__ import annotations

from datetime import date

ENTRY_INTO_FORCE = date(2012, 3, 15)
EU_ENTRY_INTO_FORCE = date(2011, 7, 1)
RCEP_JAPAN_ENTRY_INTO_FORCE = date(2022, 1, 1)

# EU categories: the number in the schedule is the number of years over which
# the base rate is removed in equal instalments, duty free from year n+1.
EU_EQUAL_CATEGORIES = (2, 3, 5, 6, 7, 10, 12, 13, 15, 18, 20, 21)
EXCLUDED = "U"

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


def eu_year(on: date) -> int | None:
    if on < EU_ENTRY_INTO_FORCE:
        return None
    return on.year - EU_ENTRY_INTO_FORCE.year + 1


def eu_staged_rate(base_percent: float | None, staging: str | None, on: date) -> dict:
    """The EU schedule's arithmetic, on the date the goods are entered."""
    if base_percent is None:
        return {"percent": None, "reason": "the schedule prints a specific duty, not a percentage"}
    if not staging:
        return {"percent": None, "reason": "no staging category on the line"}
    year = eu_year(on)
    if year is None:
        return {
            "percent": None,
            "reason": "date is before the Agreement entered into force on %s" % EU_ENTRY_INTO_FORCE,
        }
    category = staging.strip().upper()
    if category == "0":
        return {"percent": 0.0, "reason": "category 0 is eliminated on entry into force"}
    if category == "E":
        return {
            "percent": base_percent,
            "reason": "category E keeps the base rate, so the preference saves nothing on this line",
        }
    if category == "X":
        return {"percent": None, "reason": "category X carries no commitment on this line"}
    try:
        years = int(category)
    except ValueError:
        return {"percent": None, "reason": "staging category %r is not defined in Annex 2-A" % staging}
    if years not in EU_EQUAL_CATEGORIES:
        return {"percent": None, "reason": "staging category %r is not defined in Annex 2-A" % staging}
    stages = years + 1
    if year >= stages:
        return {
            "percent": 0.0,
            "reason": "category %d is duty free from the first day of year %d" % (years, stages),
        }
    return {
        "percent": round_down(base_percent * (stages - year) / stages),
        "reason": "category %d, stage %d of %d equal annual cuts" % (years, year, stages),
    }


def rcep_year(on: date) -> int | None:
    """Year of the RCEP schedule, counted from the entry into force for Japan."""
    if on < RCEP_JAPAN_ENTRY_INTO_FORCE:
        return None
    return on.year - RCEP_JAPAN_ENTRY_INTO_FORCE.year + 1


def printed_rate(years: list[str] | None, staging: str | None, on: date) -> dict:
    """The rate a schedule prints for one year, read as printed.

    ``years`` is the row's own ``Year 1`` .. ``Year 21 and subsequent`` cells.
    Nothing is interpolated: a year the row does not print is a year this
    snapshot cannot answer for.
    """
    year = rcep_year(on)
    if year is None:
        return {
            "percent": None,
            "reason": "date is before the Agreement entered into force for Japan on %s"
            % RCEP_JAPAN_ENTRY_INTO_FORCE,
        }
    cells = list(years or [])
    if not cells:
        return {"percent": None, "reason": "the schedule row prints no yearly rate"}
    index = min(year, 21) - 1
    if index >= len(cells):
        return {"percent": None, "reason": "the schedule row ends before year %d" % year}
    cell = (cells[index] or "").strip()
    if not cell:
        return {"percent": None, "reason": "the schedule prints no rate for year %d" % year}
    if cell.upper() == EXCLUDED:
        return {
            "percent": None,
            "basis": "excluded",
            "reason": "year %d prints U: this line is excluded from the schedule for this partner, so the MFN rate applies"
            % year,
        }
    percent = parse_percent(cell)
    if percent is None:
        return {
            "percent": None,
            "reason": "year %d is %r, a specific or compound duty this engine does not compute" % (year, cell),
        }
    return {"percent": percent, "reason": "year %d of the schedule prints %s percent" % (year, ("%g" % percent))}


def parse_percent(text: str) -> float | None:
    """A rate cell as a percentage, or ``None`` when it is not one."""
    value = (text or "").strip()
    if not value:
        return None
    if value.lower() == "free":
        return 0.0
    if "%" in value or "yen" in value.lower() or "whichever" in value.lower():
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    # The sheet stores 3.9 percent as 0.039.
    if number <= 1.0 and "." in value:
        return round(number * 100.0, 4)
    return number


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
