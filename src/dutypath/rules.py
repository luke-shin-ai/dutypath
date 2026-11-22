"""Origin rules: find the one that applies, and read what it asks for.

A rule sentence has alternatives ("a change to heading X; or a change to
subheading X with a regional value content of 45 percent").  Each alternative
is a set of conditions that must all hold.  The rule passes when one
alternative holds.

Nothing is guessed.  A rule whose sentence this module cannot divide, or whose
condition needs a value the shipment did not supply, produces an undecidable
verdict with the missing piece named.
"""

from __future__ import annotations

import re

from . import codes, store

RULE_QUERY = """
MATCH (r:OriginRule {agreement: $agreement})
WHERE r.from_norm <= $norm AND r.to_norm >= $norm
RETURN r.id AS id, r.level AS level, r.code_from AS code_from, r.code_to AS code_to,
       r.text AS text, r.kinds AS kinds, r.rvc_build_down AS rvc_build_down,
       r.rvc_build_up AS rvc_build_up, r.excluded_from AS excluded_from,
       r.group_exclude_from AS group_from, r.group_exclude_to AS group_to,
       r.originating_weight_min AS weight_min, r.structured AS structured,
       r.priority AS priority, r.agreement AS agreement
ORDER BY r.priority ASC, r.to_norm ASC
LIMIT 1
"""

SPLIT = re.compile(
    r"(?:;\s*)?\bor\b(?=\s+(?:a\s+change|no\s+change|assembly|rvc|cth|ctsh|cc|wo))",
    re.IGNORECASE,
)


def resolve(conn, agreement: str, code: str) -> dict | None:
    return store.one(conn, RULE_QUERY, {"agreement": agreement, "norm": codes.normalise(code)})


def split_alternatives(text: str) -> list[str]:
    parts = [part.strip(" ;") for part in SPLIT.split(text)]
    return [part for part in parts if part]


def _level_change(kind: str) -> int:
    return {"CC": 2, "CTH": 4, "CTSH": 6}[kind]


def read_alternative(text: str) -> dict:
    """What one alternative requires, read from its own words."""
    lowered = text.lower()
    kinds = []
    if "from any other chapter" in lowered or "change to chapter" in lowered:
        kinds.append("CC")
    if "from any other heading" in lowered:
        kinds.append("CTH")
    if "from any other subheading" in lowered or "outside subheading" in lowered:
        kinds.append("CTSH")
    if not kinds and re.search(r"\bcth\b", lowered):
        kinds.append("CTH")
    if not kinds and re.search(r"\bctsh\b", lowered):
        kinds.append("CTSH")
    if not kinds and re.search(r"\bcc\b", lowered):
        kinds.append("CC")

    excluded = []
    for match in re.finditer(r"except from (?:headings?|subheadings?) ([\d., andor-]+)", lowered):
        for token in re.findall(r"\d{4}(?:\.\d{2})?", match.group(1)):
            excluded.append(token.replace(".", ""))
    group = None
    match = re.search(r"outside (?:subheadings? )?(\d{4}\.\d{2})(?: through |-)(\d{4}\.\d{2})", lowered)
    if match:
        group = (match.group(1), match.group(2))

    rvc_down = None
    rvc_up = None
    match = re.search(r"rvc\s?(\d{2})(?:/(\d{2}))?", lowered)
    if match:
        rvc_down = float(match.group(1))
        if match.group(2):
            rvc_up = float(match.group(2))
    if "regional value content" in lowered or "value added" in lowered:
        down = re.search(r"(\d{2}) percent under the build-down", lowered)
        up = re.search(r"(\d{2}) percent under the build-up", lowered)
        single = re.search(r"regional value content of not less than (\d{2}) percent", lowered)
        added = re.search(r"(\d{2})\s?% value added", lowered)
        if down:
            rvc_down = float(down.group(1))
        if up:
            rvc_up = float(up.group(1))
        if single and not (down or up):
            rvc_down = float(single.group(1))
        if added and not (down or up or single):
            rvc_down = float(added.group(1))

    weight_min = None
    match = re.search(r"originating polymer content.{0,140}?not less than (\d{2}) percent by weight", lowered)
    if match:
        weight_min = float(match.group(1))

    return {
        "text": text.strip(),
        "kinds": kinds,
        "excluded": excluded,
        "group": group,
        "rvc_down": rvc_down,
        "rvc_up": rvc_up,
        "weight_min": weight_min,
    }


def alternatives(rule: dict) -> list[dict]:
    parts = split_alternatives(rule["text"])
    if not parts:
        parts = [rule["text"]]
    return [read_alternative(part) for part in parts]
