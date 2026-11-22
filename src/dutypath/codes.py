"""Nomenclature helpers.

One code space for every level, so a heading range, a subheading range and a
tariff line compare with plain string ordering: digits only, padded to eight
characters with nines.  The padding is what makes 39.16 - 39.26 contain
3926.90 without a second comparison rule.

A code the exporter writes short names a level, not a tariff line: ``8504`` is
the heading, and it covers every line from 8504.00 to 8504.99.  ``span`` gives
that whole interval, and ``interval_relation`` says whether a code sits inside,
outside or across another interval.  Without it, a heading written where the
rule asks for a subheading would pass every interval test, because a padded
heading reads as the top line of its own interval.
"""

from __future__ import annotations

import re


def normalise(code: str) -> str:
    digits = re.sub(r"[^0-9]", "", str(code))
    if not digits:
        return ""
    if len(digits) < 8:
        return digits.ljust(8, "9")
    return digits[:8]


def normalise_low(code: str) -> str:
    """Lower bound of the interval a code names, so a range test is one compare."""
    digits = re.sub(r"[^0-9]", "", str(code))
    if not digits:
        return ""
    if len(digits) < 8:
        return digits.ljust(8, "0")
    return digits[:8]


def level_of(code: str) -> str:
    digits = stated_digits(code)
    if len(digits) <= 4:
        return "heading"
    if len(digits) == 6:
        return "subheading"
    if len(digits) > 8:
        return "line"
    return "line"


def level_name_of(code: str) -> str:
    """The level the code is written at, in the words a reader knows."""
    digits = stated_digits(code)
    if len(digits) <= 2:
        return "chapter"
    if len(digits) <= 4:
        return "heading"
    if len(digits) <= 6:
        return "subheading"
    return "tariff line"


def chapter_of(code: str) -> str:
    return re.sub(r"[^0-9]", "", str(code))[:2]


def heading_of(code: str) -> str:
    return re.sub(r"[^0-9]", "", str(code))[:4]


def subheading_of(code: str) -> str:
    digits = re.sub(r"[^0-9]", "", str(code))
    return digits[:6]


def stated_digits(code: str) -> str:
    """The digits the exporter wrote, with no padding: the level of the statement."""
    return re.sub(r"[^0-9]", "", str(code))


def span(code: str) -> tuple[str, str] | None:
    """The lowest and highest eight digit line a stated code can name.

    ``85043140`` spans itself.  ``8504`` spans 85040000 to 85049999, because a
    heading does not say which of its lines the material is.
    """
    digits = stated_digits(code)
    if not digits:
        return None
    if len(digits) > 8:
        digits = digits[:8]
    return digits.ljust(8, "0"), digits.ljust(8, "9")


def interval_relation(code: str, low: str, high: str) -> str:
    """Where a code sits against a low..high interval, at any stated level.

    ``inside``   every line the code can name is in the interval,
    ``outside``  none of them is,
    ``across``   the code is stated too coarsely, so the interval cuts it and
                 the answer needs the finer classification.
    """
    bounds = span(code)
    low_span = span(low)
    high_span = span(high)
    if bounds is None or low_span is None or high_span is None:
        return "across"
    start, end = bounds
    floor = low_span[0]
    ceiling = high_span[1]
    if end < floor or start > ceiling:
        return "outside"
    if start >= floor and end <= ceiling:
        return "inside"
    return "across"


def is_under(child: str, parent: str) -> bool:
    """True when child sits inside parent at whatever level parent names.

    A child stated more coarsely than the parent is not under it: ``8504`` does
    not sit inside ``8504.40``.  Read the level first when that distinction
    matters, and use ``interval_relation`` for intervals.
    """
    child_digits = stated_digits(child)
    digits = stated_digits(parent)
    if not child_digits or not digits:
        return False
    if len(child_digits) < len(digits):
        return False
    return child_digits[: len(digits)] == digits


def ancestors(code: str) -> list[str]:
    """Chapter, heading and subheading codes above a code, nearest last.

    A code never appears in its own ancestor list, whatever level it names.
    """
    digits = re.sub(r"[^0-9]", "", str(code))
    out = []
    for length in (2, 4, 6):
        if len(digits) > length:
            out.append(digits[:length])
    return out
