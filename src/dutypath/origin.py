"""Origin verdict for one shipment under one agreement.

Three verdicts, the same three the rest of the project uses:

    ORIGINATING      the rule for the good is met by the material list
    NOT_ORIGINATING  the rule is not met, and the material that breaks it is named
    UNDECIDABLE      the snapshot cannot answer, and the missing piece is named

The rule is read from the graph, the tariff hierarchy is walked in the graph,
and the material list arrives in memory with the shipment.  No material, no
value and no shipment identifier is ever written to the store.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import codes, rules, store

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
    value: float
    description: str = ""

    @property
    def originating(self) -> bool:
        return False  # replaced per agreement


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


# The EU Party is named as one party in the agreement and as member states in a
# bill of materials.  The codes are the ISO 3166-1 alpha-2 codes of the states
# that were members when the agreement was signed.
EU_MEMBER_STATES = {
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR",
    "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI",
    "SK",
}


def _is_party(origin: str, parties: set[str]) -> bool:
    value = (origin or "").upper()
    if value == "EU":
        return bool(parties & EU_MEMBER_STATES)
    return value in parties


def _ctc_ok(material_code: str, good_code: str, kind: str) -> tuple[bool, str]:
    level = {"CC": 4, "CTH": 4, "CTSH": 6}[kind]
    good = codes.normalise(good_code)
    material = codes.normalise(material_code)
    if kind == "CC":
        changed = good[:2] != material[:2]
        return changed, ("chapter changes" if changed else "same chapter %s" % material[:2])
    if kind == "CTH":
        changed = good[:4] != material[:4]
        return changed, ("heading changes" if changed else "same heading %s" % material[:4])
    changed = good[:6] != material[:6]
    return changed, ("subheading changes" if changed else "same subheading %s" % material[:6])


def _rvc(materials: list[Material], parties: set[str], fob: float) -> tuple[float, float, float]:
    non_party = sum(m.value for m in materials if not _is_party(m.origin, parties))
    party = sum(m.value for m in materials if _is_party(m.origin, parties))
    if not fob:
        return 0.0, 0.0, non_party
    return (fob - non_party) / fob * 100.0, party / fob * 100.0, non_party


def evaluate(conn, shipment: dict, agreement: str, materials: list[Material] | None = None,
             good_code: str | None = None) -> dict:
    goods = shipment["goods"]
    good_code = good_code or goods.get("hts8") or goods.get("hs6") or goods.get("hs")
    fob = float(goods.get("declared_value") or goods.get("fob") or 0.0)
    if materials is None:
        materials = [
            Material(
                id=str(item.get("id", f"M{index}")),
                code=str(item.get("hts8") or item.get("hs") or ""),
                origin=str(item.get("origin", "")),
                value=float(item.get("value") or 0.0),
                description=str(item.get("description", "")),
            )
            for index, item in enumerate(shipment.get("materials") or [], start=1)
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

    down, up, non_party = _rvc(materials, parties, fob)
    report["rvc_build_down"] = round(down, 2)
    report["rvc_build_up"] = round(up, 2)
    report["non_party_value"] = non_party

    for index, alternative in enumerate(rules.alternatives(rule), start=1):
        check = _check(alternative, index, good_code, materials, parties, fob, shipment)
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
        report["reason"] = "a value the rule needs is not in the shipment"
        return report

    report["verdict"] = NOT_ORIGINATING
    failing = [check for check in report["checks"] if not check["holds"]]
    if failing:
        report["reason"] = failing[0]["reason"]
        report["path"] = failing[0]["path"]
    return report


def _check(alternative: dict, index: int, good_code: str, materials: list[Material],
           parties: set[str], fob: float, shipment: dict) -> Check:
    path: list[str] = []
    reasons: list[str] = []
    missing: list[str] = []
    holds = True

    for kind in alternative["kinds"]:
        for material in materials:
            if _is_party(material.origin, parties):
                continue
            if alternative["excluded"] and any(
                codes.is_under(material.code, excluded) for excluded in alternative["excluded"]
            ):
                holds = False
                reasons.append(
                    "%s %s is in an excluded provision (%s): %s"
                    % (material.id, material.code, ",".join(alternative["excluded"]), material.origin)
                )
                path.append(
                    "%s (%s, %s) -[%s]-> excluded provision %s"
                    % (material.id, material.code, material.origin, kind,
                       ",".join(alternative["excluded"]))
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
            if alternative["group"]:
                low, high = alternative["group"]
                material_digits = material.code.replace(".", "")
                if low.replace(".", "") <= material_digits <= high.replace(".", ""):
                    holds = False
                    reasons.append(
                        "%s %s sits inside %s to %s, the group the rule excludes"
                        % (material.id, material.code, low, high)
                    )
                    path.append(
                        "%s (%s, %s) -[%s]-> inside group %s to %s"
                        % (material.id, material.code, material.origin, kind, low, high)
                    )
                    continue
            ok, why = _ctc_ok(material.code, good_code, kind)
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

    down, up, non_party = _rvc(materials, parties, fob)
    floor_down = alternative["rvc_down"]
    floor_up = alternative["rvc_up"]
    if floor_down or floor_up:
        # A rule that prints both thresholds is the same rule under either
        # method: "not less than 35 percent under the build-up method, or 45
        # percent under the build-down method" is met by either one, so asking
        # for both would refuse a good the agreement accepts.
        if not fob:
            missing.append("declared value to compute regional value content")
        else:
            down_ok = floor_down is not None and down + 1e-9 >= floor_down
            up_ok = floor_up is not None and up + 1e-9 >= floor_up
            if down_ok or up_ok:
                if floor_down is not None and down_ok:
                    path.append(
                        "build down (declared value %s - non party materials %s) / %s = %.2f percent, "
                        "at or above %.0f percent" % (fob, non_party, fob, down, floor_down)
                    )
                if floor_up is not None and up_ok:
                    path.append(
                        "build up %.2f percent is at or above %.0f percent" % (up, floor_up)
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

    if missing:
        return Check(
            index,
            False,
            "cannot decide this alternative: %s" % "; ".join(missing),
            path,
            round(down, 2),
            round(up, 2),
            missing,
        )
    if holds:
        reason = "alternative %d holds" % index
        if not reasons:
            reason = "every non party material changes tariff classification as the rule asks"
        return Check(index, True, reason, path or ["rule %s met" % alternative["text"][:90]],
                     round(down, 2), round(up, 2), [])
    return Check(index, False, "; ".join(reasons), path, round(down, 2), round(up, 2), missing)
