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

import json
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
       r.alternatives_json AS alternatives_json, r.priority AS priority,
       r.agreement AS agreement
ORDER BY r.priority ASC, r.to_norm ASC
LIMIT 1
"""

SPLIT = re.compile(
    r"(?:;|\s)\s*\bor\b(?=\s+(?:a\s+change|no\s+change|assembly|rvc|cth|ctsh|cc|wo|manufacture|the\s+operation))",
    re.IGNORECASE,
)


def resolve(conn, agreement: str, code: str) -> dict | None:
    return store.one(conn, RULE_QUERY, {"agreement": agreement, "norm": codes.normalise(code)})


def split_alternatives(text: str) -> list[str]:
    parts = [part.strip(" ;") for part in SPLIT.split(text)]
    return [part for part in parts if part]


def _level_change(kind: str) -> int:
    return {"CC": 2, "CTH": 4, "CTSH": 6}[kind]


def _rule_interval(rule: dict) -> tuple[str, str] | None:
    """The codes a rule row covers, as the group its own sentence names."""
    low = str(rule.get("code_from") or "").replace(".", "")
    high = str(rule.get("code_to") or "").replace(".", "")
    if not low and not high:
        return None
    low = low or high
    high = high or low
    return (low, high)


def read_alternative(text: str, rule: dict | None = None) -> dict:
    """What one alternative requires, read from its own words.

    ``rule`` is the row the sentence sits in.  A rule that says "outside that
    group" names the interval of its own codes, so the sentence cannot be read
    without the range it belongs to.
    """
    lowered = text.lower()
    kinds = []
    if "from any other chapter" in lowered or "change to chapter" in lowered:
        kinds.append("CC")
    if "from any other heading" in lowered:
        kinds.append("CTH")
    # The EU list says "manufacture from materials of any heading, except that
    # of the product", which is the same condition as a change of heading.
    if not kinds and "materials of any heading, except that of the product" in lowered:
        kinds.append("CTH")
    if not kinds and re.search(r"manufacture from materials of any heading\b", lowered):
        kinds.append("CTH")
    if "from any other subheading" in lowered or "outside subheading" in lowered:
        kinds.append("CTSH")
    # "A change to subheading 8483.40 through 8483.50 from any subheading, except
    # from subheading 8482.10" is the same level change, written without the
    # word other.  The except clauses are read separately below.
    if not kinds and re.search(r"change to (?:subheadings? [\d. throughand]+|the good) ?from any subheading\b", lowered):
        kinds.append("CTSH")
    if not kinds and re.search(r"\bcth\b", lowered):
        kinds.append("CTH")
    if not kinds and re.search(r"\bctsh\b", lowered):
        kinds.append("CTSH")
    if not kinds and re.search(r"\bcc\b", lowered):
        kinds.append("CC")

    excluded = []
    excluded_ranges = []
    for match in re.finditer(r"except from (?:headings?|subheadings?) ([^;]*)", lowered):
        # "except from subheading 8443.91 through 8443.99" bars the whole range,
        # not its two ends, so each clause is read as intervals first.
        for part in re.split(r"[,;]|\bor\b|\band\b", match.group(1)):
            pair = re.search(
                r"(\d{4}(?:\.\d{2})?)\s*(?:through|-|to)\s*(\d{4}(?:\.\d{2})?)", part
            )
            if pair:
                low, high = pair.group(1).replace(".", ""), pair.group(2).replace(".", "")
                excluded_ranges.append((low, high))
                excluded.extend([low, high])
                continue
            excluded.extend(
                token.replace(".", "") for token in re.findall(r"\d{4}(?:\.\d{2})?", part)
            )

    group = None
    match = re.search(
        r"outside (?:of )?(?:subheadings? )?(\d{4}\.\d{2})(?: through |-)(\d{4}\.\d{2})", lowered
    )
    if match:
        group = (match.group(1), match.group(2))
    elif rule is not None and re.search(r"outside (?:of )?that group\b", lowered):
        # "from any other subheading outside that group" means the subheadings
        # the rule itself covers.  Reading it as a plain subheading change lets
        # a material from inside the group through, which is the opposite of
        # what the sentence says.
        group = _rule_interval(rule)

    # "a change from subheading 8513.90, whether or not there is also a change
    # from any other heading" names a source the rule lets through.  The
    # phrase starts with "from subheading", not "from any other subheading",
    # and an except clause is a bar, not a permission, so it is read out first.
    barred = re.sub(r"except from [^;]*", " ", lowered)
    allowed_from = []
    for match in re.finditer(r"(?<!any other )\bfrom subheadings? (\d{4}\.\d{2})", barred):
        allowed_from.append(match.group(1).replace(".", ""))

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

    # The EU ceiling on non originating materials, read as a build down floor.
    match = re.search(
        r"value of all the materials used does not exceed\s*(\d{2})\s*%\s*of the ex-works price",
        lowered,
    )
    if match and rvc_down is None and rvc_up is None:
        rvc_down = 100.0 - float(match.group(1))

    return {
        "text": text.strip(),
        "kinds": kinds,
        "excluded": excluded,
        "excluded_ranges": excluded_ranges,
        "group": group,
        "allowed_from": allowed_from,
        "rvc_down": rvc_down,
        "rvc_up": rvc_up,
        "weight_min": weight_min,
    }


def alternatives(rule: dict) -> list[dict]:
    """The alternatives a rule offers.

    A rule read from a sentence is split at the ``or`` that separates the
    alternatives.  A rule whose alternatives were read out of a table at build
    time carries them as a stored list, so the sentence stays as printed and
    the structure does not depend on splitting it again.
    """
    stored = rule.get("alternatives_json")
    if stored:
        try:
            parsed = json.loads(stored) if isinstance(stored, str) else stored
        except (TypeError, ValueError):
            parsed = None
        if parsed:
            out = []
            for item in parsed:
                out.append(
                    {
                        "text": item.get("text", ""),
                        "kinds": item.get("kinds") or [],
                        "excluded": item.get("excluded") or [],
                        "excluded_ranges": [tuple(pair) for pair in item.get("excluded_ranges") or []],
                        "group": tuple(item["group"]) if item.get("group") else None,
                        "allowed_from": item.get("allowed_from") or [],
                        "rvc_down": item.get("rvc_down"),
                        "rvc_up": item.get("rvc_up"),
                        "weight_min": item.get("weight_min"),
                    }
                )
            return out
    parts = split_alternatives(rule["text"])
    if not parts:
        parts = [rule["text"]]
    return [read_alternative(part, rule) for part in parts]


def condition_count(alternative: dict) -> int:
    """How many tests an alternative actually asks for.

    A sentence the parser read nothing out of has zero, and that is the point of
    counting: an alternative with no test cannot hold, because nothing was
    tested.  An exclusion or a permitted source on its own is not a test either,
    since it only says what to do with a material once a level change is asked
    for.
    """
    count = len(alternative.get("kinds") or [])
    if alternative.get("rvc_down") is not None or alternative.get("rvc_up") is not None:
        count += 1
    if alternative.get("weight_min") is not None:
        count += 1
    return count
