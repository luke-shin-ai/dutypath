"""Nomenclature helpers.

One code space for every level, so a heading range, a subheading range and a
tariff line compare with plain string ordering: digits only, padded to eight
characters with nines.  The padding is what makes 39.16 - 39.26 contain
3926.90 without a second comparison rule.
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
    digits = re.sub(r"[^0-9]", "", str(code))
    if len(digits) <= 4:
        return "heading"
    if len(digits) == 6:
        return "subheading"
    return "line"


def chapter_of(code: str) -> str:
    return re.sub(r"[^0-9]", "", str(code))[:2]


def heading_of(code: str) -> str:
    return re.sub(r"[^0-9]", "", str(code))[:4]


def subheading_of(code: str) -> str:
    digits = re.sub(r"[^0-9]", "", str(code))
    return digits[:6]


def is_under(child: str, parent: str) -> bool:
    """True when child sits inside parent at whatever level parent names."""
    child_norm = normalise(child)
    digits = re.sub(r"[^0-9]", "", str(parent))
    if not digits:
        return False
    return child_norm[: len(digits)] == digits


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
