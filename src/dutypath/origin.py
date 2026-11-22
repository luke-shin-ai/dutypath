"""Origin verdict for one shipment under one agreement.

Three verdicts, the same three the rest of the project uses:

    ORIGINATING      the rule for the good is met by the material list
    NOT_ORIGINATING  the rule is not met, and the material that breaks it is named
    UNDECIDABLE      the snapshot cannot answer, and the missing piece is named

The rule is read from the graph, the tariff hierarchy is walked in the graph,
and the material list arrives in memory with the shipment.  No material, no
value and no shipment identifier is ever written to the store.

What the verdict refuses to do is the part worth reading.  A material with no
classification, a bill of materials with no lines, a material with no value
where the rule prices one, a code written too coarsely for the level the rule
tests, and an alternative the parser could not read: each of those is
``UNDECIDABLE`` with the piece named.  None of them is a pass.  A test that did
not run is not a test that was met.

One assumption is worth stating: the build-up figure counts a material whose
origin is a party as a party material.  The bill of materials does not carry
whether that material itself meets an origin rule, so the figure is the
agreement's own party content, not the accumulated originating content of the
whole supply chain.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import codes, rules, store, validate

ORIGINATING = "ORIGINATING"
NOT_ORIGINATING = "NOT_ORIGINATING"
UNDECIDABLE = "UNDECIDABLE"

PARTY_QUERY = """
MATCH (a:Agreement {code: $code})
RETURN a.code AS code, a.market AS market, a.coverage AS coverage,
       a.approved_exporter_required AS approved_exporter_required,
       a.in_force AS in_force, a.note AS note
"""


@dataclass
class Material:
    id: str
    code: str
    origin: str
    value: float | None
    description: str = ""


@dataclass
class Check:
    alternative: int
    holds: bool
    reason: str
    path: list[str] = field(default_factory=list)
    rvc_down: float | None = None
    rvc_up: float | None = None
    missing: list[str] = field(default_factory=list)


def _parties(agreement: str) -> set[str]:
    if agreement == "KORUS":
        return {"KR", "US"}
    if agreement == "RCEP":
        return {"KR", "CN", "JP", "AU", "NZ", "SG", "MY", "TH", "VN", "ID", "PH", "BN", "KH", "LA", "MM"}
    if agreement == "EUKOR":
        return {"KR"} | EU_MEMBER_STATES
    return {"KR"}


# The EU Party is one party in the agreement and many member states in a bill of
# materials.  These are the ISO 3166-1 alpha-2 codes of the states that were
# members on 2011-07-01, the day the agreement entered into force.  Croatia
# joined the Union in 2013 and the United Kingdom left in 2020; neither date is
# this snapshot's, and moving the set would change a verdict without a source.
EU_MEMBER_STATES = {
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GB", "GR",
    "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI",
    "SK",
}


def _is_party(origin: str, parties: set[str]) -> bool:
    value = (origin or "").upper()
    if value == "EU":
        return bool(parties & EU_MEMBER_STATES)
    return value in parties


LEVEL_OF_KIND = {"CC": 2, "CTH": 4, "CTSH": 6}
LEVEL_WORDS = {2: "chapter", 4: "heading", 6: "subheading"}


def _ctc_ok(material_code: str, good_code: str, kind: str) -> tuple[bool | None, str]:
    """Whether a material changes classification at the level the rule names.

    The good's prefix is the interval the material has to fall outside, and the
    material is a statement that may be coarser than that interval.  Three
    answers follow: outside passes, inside fails, and a material whose own span
    straddles the interval is ``None``, because the exporter has not said enough
    to answer.
    """
    level = LEVEL_OF_KIND[kind]
    good = codes.stated_digits(good_code)
    if len(good) < level:
        return None, "the good is stated at %s level and a %s change needs the %s" % (
            codes.level_name_of(good_code), kind, LEVEL_WORDS[level]
        )
    prefix = good[:level]
    relation = codes.interval_relation(material_code, prefix, prefix)
    word = LEVEL_WORDS[level]
    if relation == "across":
        return None, "a finer classification than the %s this material is stated at, to place it " \
                     "against %s %s" % (codes.level_name_of(material_code), word, _pretty(prefix))
    if relation == "outside":
        return True, ("chapter changes" if level == 2 else
                      "heading changes" if level == 4 else "subheading changes")
    if kind == "CC":
        return False, "same chapter %s" % prefix
    if kind == "CTH":
        return False, "same heading %s" % prefix
    return False, "same subheading %s" % prefix


def _rvc(materials: list[Material], parties: set[str], fob: float | None) -> dict:
    unknown = [m.id for m in materials if m.value is None]
    non_party = sum(m.value for m in materials if m.value is not None and not _is_party(m.origin, parties))
    party = sum(m.value for m in materials if m.value is not None and _is_party(m.origin, parties))
    if unknown or not fob:
        return {"down": None, "up": None, "non_party": None if unknown else non_party,
                "unknown_values": unknown, "no_fob": not fob}
    return {
        "down": (fob - non_party) / fob * 100.0,
        "up": party / fob * 100.0,
        "non_party": non_party,
        "unknown_values": [],
        "no_fob": False,
    }


def evaluate(conn, shipment: dict, agreement: str, materials: list[Material] | None = None,
             good_code: str | None = None, rule: dict | None = None) -> dict:
    payload = validate.shipment(shipment, require_declared=False)
    goods = payload["goods"]
    good_code = good_code or goods.get("hts8") or goods.get("hs6") or goods.get("hs")
    fob = float(goods.get("declared_value") or 0.0) or None
    if materials is None:
        materials = [
            Material(
                id=str(item.get("id", f"M{index}")),
                code=str(item.get("hts8") or item.get("hs") or ""),
                origin=str(item.get("origin", "")),
                value=item.get("value"),
                description=str(item.get("description", "")),
            )
            for index, item in enumerate(payload.get("materials") or [], start=1)
        ]
    parties = _parties(agreement)
    agreement_row = store.one(conn, PARTY_QUERY, {"code": agreement})

    report = {
        "agreement": agreement,
        "good": good_code,
        "rule": None,
        "verdict": UNDECIDABLE,
        "reason": None,
        "path": [],
        "checks": [],
        "rvc_build_down": None,
        "rvc_build_up": None,
        "non_party_value": None,
        "missing": [],
        "parties": sorted(parties),
        "agreement_note": (agreement_row or {}).get("note"),
        "coverage": (agreement_row or {}).get("coverage"),
        "approved_exporter_required": bool((agreement_row or {}).get("approved_exporter_required")),
    }

    if agreement_row is None:
        report["reason"] = f"agreement {agreement} is not in this snapshot"
        return report

    if rule is None:
        rule = rules.resolve(conn, agreement, good_code)
    if rule is None:
        report["reason"] = (
            "no origin rule for %s under %s in this snapshot" % (good_code, agreement)
        )
        report["missing"] = ["origin rule for %s" % good_code]
        return report
    report["rule"] = {
        "id": rule["id"],
        "level": rule["level"],
        "code_from": rule["code_from"],
        "code_to": rule["code_to"],
        "text": rule["text"],
    }

    if not rule["structured"]:
        if "as specified" in rule["text"].lower():
            report["reason"] = (
                "the rule defers to split headings or subheadings that this snapshot does not model"
            )
            report["missing"] = ["the split level rule for %s" % good_code]
        else:
            report["reason"] = "the rule sentence could not be read into conditions"
        report["missing"] = ["a structured form of the rule"]
        return report

    content = _rvc(materials, parties, fob)
    report["rvc_build_down"] = None if content["down"] is None else round(content["down"], 2)
    report["rvc_build_up"] = None if content["up"] is None else round(content["up"], 2)
    report["non_party_value"] = content["non_party"]

    if not materials:
        # Nothing was given to test.  An empty bill of materials meets no rule;
        # it is the exporter's input that is missing, not the engine's answer.
        report["reason"] = "the bill of materials has no material lines, so no condition can be tested"
        report["missing"] = ["the bill of materials: at least one material line"]
        return report

    unclassified = [m.id for m in materials if not codes.stated_digits(m.code)]
    if unclassified:
        # A line with no classification cannot be placed against any rule, and
        # pretending it passed is how a bill of materials gets better by being
        # less complete.  The value content could still be computed, but the
        # exporter is one code away from a verdict and is told which line.
        report["reason"] = (
            "the bill of materials has a material with no tariff classification, so no material "
            "can be tested against the rule"
        )
        report["missing"] = ["the tariff classification of material %s" % ", ".join(unclassified)]
        return report

    # The intervals the rule names are nodes hanging off it, so the material
    # list meets them in the graph once per alternative rather than in a Python
    # loop per material.  The join sends codes, never a shipment.
    for index, alternative in enumerate(rules.alternatives(rule), start=1):
        check = _check(conn, rule, alternative, index, good_code, materials, parties, fob,
                       payload, content)
        report["checks"].append(check.__dict__)
        if check.missing:
            report["missing"].extend(item for item in check.missing if item not in report["missing"])
        if check.holds:
            report["verdict"] = ORIGINATING
            report["reason"] = check.reason
            report["path"] = check.path
            return report

    if report["missing"]:
        report["verdict"] = UNDECIDABLE
        report["reason"] = "cannot decide under this rule: %s" % "; ".join(report["missing"][:3])
        return report

    report["verdict"] = NOT_ORIGINATING
    failing = [check for check in report["checks"] if not check["holds"]]
    if failing:
        report["reason"] = failing[0]["reason"]
        report["path"] = failing[0]["path"]
    return report


def _pretty(code: str) -> str:
    """A code as the schedule prints it, for a sentence a reader reads."""
    return codes.pretty(code)


def _check(conn, rule: dict, alternative: dict, index: int, good_code: str,
           materials: list[Material], parties: set[str], fob: float | None,
           shipment: dict, content: dict) -> Check:
    path: list[str] = []
    reasons: list[str] = []
    satisfied: list[str] = []
    missing: list[str] = []
    holds = True

    down = content["down"]
    up = content["up"]
    non_party = content["non_party"]

    if rules.condition_count(alternative) == 0:
        text = (alternative.get("text") or "").strip()
        return Check(
            index,
            False,
            "cannot decide this alternative: its sentence asks for a condition this parser did "
            "not read (%s)" % (text[:120] or "empty sentence"),
            [],
            None if down is None else round(down, 2),
            None if up is None else round(up, 2),
            ["a testable reading of the alternative: %s" % (text[:100] or "empty sentence")],
        )

    # One join for the whole alternative: every material in the bill of
    # materials against every interval node the rule carries.
    # The key is the line's position, so two materials that share an id are
    # still two materials here.
    hits = rules.material_intervals(
        conn, rule["id"], index,
        [(position, material.code) for position, material in enumerate(materials)
         if codes.stated_digits(material.code)],
    ) if alternative["kinds"] else {}

    for kind in alternative["kinds"]:
        for position, material in enumerate(materials):
            if _is_party(material.origin, parties):
                continue
            if not codes.stated_digits(material.code):
                missing.append("the tariff classification of material %s" % material.id)
                continue
            material_hits = hits.get(str(position)) or []
            barred = None
            for hit in material_hits:
                if hit["kind"] != "excluded":
                    continue
                if hit["relation"] == "across":
                    missing.append(
                        "a finer classification for material %s, which is stated at %s level and "
                        "sits across the exclusion %s"
                        % (material.id, codes.level_name_of(material.code), hit["label"])
                    )
                    barred = "unknown"
                    break
                barred = hit["label"]
                break
            if barred == "unknown":
                continue
            if barred is not None:
                holds = False
                reasons.append(
                    "%s %s is in an excluded provision (%s): %s"
                    % (material.id, material.code, barred, material.origin)
                )
                path.append(
                    "%s (%s, %s) -[%s]-> excluded provision %s"
                    % (material.id, material.code, material.origin, kind, barred)
                )
                continue
            if alternative.get("allowed_from") and any(
                codes.is_under(material.code, allowed) for allowed in alternative["allowed_from"]
            ):
                path.append(
                    "%s (%s, %s) -[%s]-> permitted material from subheading %s"
                    % (material.id, material.code, material.origin, kind,
                       ",".join(alternative["allowed_from"]))
                )
                continue
            group_hits = [hit for hit in material_hits if hit["kind"] == "group"]
            if alternative["group"] and group_hits:
                low, high = alternative["group"]
                relation = group_hits[0]["relation"]
                if relation == "across":
                    missing.append(
                        "a finer classification for material %s, which is stated at %s level and "
                        "sits across the group %s to %s the rule excludes"
                        % (material.id, codes.level_name_of(material.code), _pretty(low), _pretty(high))
                    )
                    continue
                if relation == "inside":
                    holds = False
                    reasons.append(
                        "%s %s sits inside %s to %s, the group the rule excludes"
                        % (material.id, material.code, _pretty(low), _pretty(high))
                    )
                    path.append(
                        "%s (%s, %s) -[%s]-> inside group %s to %s" % (material.id, material.code,
                                                                      material.origin, kind, _pretty(low),
                                                                      _pretty(high))
                    )
                    continue
            ok, why = _ctc_ok(material.code, good_code, kind)
            if ok is None:
                missing.append("a finer classification for material %s: %s" % (material.id, why))
                continue
            if ok:
                path.append(
                    "%s (%s, %s) -[%s]-> %s" % (material.id, material.code, material.origin, kind, why)
                )
                continue
            holds = False
            reasons.append(
                "%s %s from %s: %s, so the %s requirement fails"
                % (material.id, material.code, material.origin or "unknown origin", why, kind)
            )
            path.append(
                "%s (%s, %s) -[%s]-> %s"
                % (material.id, material.code, material.origin or "?", kind, why)
            )
        tested = [m for m in materials if not _is_party(m.origin, parties) and codes.stated_digits(m.code)]
        if tested:
            satisfied.append(
                "every non party material (%d tested) changes classification as the %s requirement asks"
                % (len(tested), kind)
            )
        else:
            satisfied.append(
                "no non party material is in the bill of materials, so the %s requirement is met "
                "without a material test" % kind
            )

    floor_down = alternative["rvc_down"]
    floor_up = alternative["rvc_up"]
    if floor_down is not None or floor_up is not None:
        # A rule that prints both thresholds is the same rule under either
        # method: "not less than 35 percent under the build-up method, or 45
        # percent under the build-down method" is met by either one, so asking
        # for both would refuse a good the agreement accepts.
        if down is None or up is None:
            if content["unknown_values"]:
                missing.append(
                    "a declared value for material %s, which the regional value content is "
                    "computed from" % ", ".join(content["unknown_values"])
                )
            if content["no_fob"]:
                missing.append("declared value to compute regional value content")
        else:
            down_ok = floor_down is not None and down + 1e-9 >= floor_down
            up_ok = floor_up is not None and up + 1e-9 >= floor_up
            if down_ok or up_ok:
                if down_ok:
                    path.append(
                        "build down (declared value %s - non party materials %s) / %s = %.2f percent, "
                        "at or above %.0f percent" % (fob, non_party, fob, down, floor_down)
                    )
                    satisfied.append(
                        "regional value content %.2f percent on the build down method meets the "
                        "%.0f percent the rule asks for" % (down, floor_down)
                    )
                if up_ok:
                    path.append(
                        "build up %.2f percent is at or above %.0f percent" % (up, floor_up)
                    )
                    satisfied.append(
                        "regional value content %.2f percent on the build up method meets the "
                        "%.0f percent the rule asks for" % (up, floor_up)
                    )
            else:
                holds = False
                reasons.append(
                    "regional value content %.2f percent under the build down and %.2f percent under "
                    "the build up are both under the thresholds the rule asks for (%.0f down, %.0f up)"
                    % (down, up, floor_down or 0.0, floor_up or 0.0)
                )
                path.append(
                    "build down %.2f percent, build up %.2f percent, non party materials %s"
                    % (down, up, non_party)
                )

    if alternative["weight_min"]:
        supplied = (shipment.get("attributes") or {}).get("originating_polymer_weight_percent")
        if supplied is None:
            missing.append(
                "originating polymer content as a share of total polymer weight (percent), "
                "the rule asks for at least %.0f" % alternative["weight_min"]
            )
        elif float(supplied) + 1e-9 < alternative["weight_min"]:
            holds = False
            reasons.append(
                "originating polymer content %.1f percent is under %.0f percent by weight"
                % (float(supplied), alternative["weight_min"])
            )
        else:
            path.append(
                "originating polymer content %.1f percent meets %.0f percent"
                % (float(supplied), alternative["weight_min"])
            )
            satisfied.append(
                "originating polymer content %.1f percent by weight meets the %.0f percent the rule "
                "asks for" % (float(supplied), alternative["weight_min"])
            )

    rounded_down = None if down is None else round(down, 2)
    rounded_up = None if up is None else round(up, 2)

    if missing:
        return Check(
            index,
            False,
            "cannot decide this alternative: %s" % "; ".join(missing),
            path,
            rounded_down,
            rounded_up,
            missing,
        )
    if holds:
        return Check(index, True, "; ".join(satisfied) or "alternative %d holds" % index,
                     path or ["rule %s met" % alternative["text"][:90]], rounded_down, rounded_up, [])
    return Check(index, False, "; ".join(reasons), path, rounded_down, rounded_up, missing)
