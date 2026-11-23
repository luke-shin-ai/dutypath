"""Dates the law puts on a claim.

Two deadlines decide whether a preference survives:

* a post import claim has to be made inside the window the law gives, counted
  from the import declaration, and
* an approved exporter approval, where the agreement requires one, has to be
  valid on the day the preference is claimed for.

Both are read from the store; the window length is a row with a citation, not
a number in the code.

An approval only decides anything where the agreement asks for one.  KORUS does
not, so a stale KORUS approval on file is a note about the file, not a reason to
refuse a preference the agreement grants without it.  Where the agreement does
ask, every status other than a valid approval is a bar: absent, expired, not
yet valid, or an approval written for a different agreement.

The EU agreement carves one consignment out of that requirement: at or under a
value ceiling, any exporter may sign the origin declaration, and the approval
is what a larger consignment needs.  The ceiling is printed in euro, so a value
stated in another currency cannot be measured against it here; this snapshot
carries no exchange rate and does not invent one.
"""

from __future__ import annotations

from datetime import date

from . import store

DEADLINE_QUERY = """
MATCH (d:DeadlineRule)-[:CITED_FROM]->(src:Source)
WHERE d.agreement = 'ALL' OR d.agreement = $agreement
RETURN d.id AS id, d.basis AS basis, d.months AS months, d.label AS label,
       d.status AS status, d.legal_ref AS legal_ref, d.note AS note,
       src.id AS source, src.title AS source_title
ORDER BY d.months DESC
LIMIT 1
"""


def add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    day = min(value.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                          31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def post_import_claim(conn, agreement: str, import_date: date, claimed_on: date) -> dict:
    rule = store.one(conn, DEADLINE_QUERY, {"agreement": agreement})
    if rule is None:
        return {"status": "UNKNOWN", "reason": "no claim window for this agreement in the snapshot"}
    deadline = add_months(import_date, int(rule["months"]))
    days_left = (deadline - claimed_on).days
    return {
        "status": "OPEN" if days_left >= 0 else "CLOSED",
        "import_date": import_date.isoformat(),
        "deadline": deadline.isoformat(),
        "days_left": days_left,
        "months": int(rule["months"]),
        "legal_ref": rule["legal_ref"],
        "note": rule["note"],
        "source": rule["source"],
        "source_title": rule["source_title"],
    }


BLOCKING = {
    "ABSENT": "no approved exporter approval is on file for this agreement",
    "EXPIRED": "the approved exporter approval expired before the claim date",
    "NOT_YET_VALID": "the approved exporter approval is not valid yet on the claim date",
    "OTHER_AGREEMENT": "the approval on file is written for another agreement",
}

# The ceiling under which the protocol's Article 16(1) lets any exporter make
# out the declaration: "any consignment consisting of one or more packages
# containing originating products whose total value does not exceed 6,000
# euros".  It is a figure from the protocol, not a setting, and it is in euro.
LOW_VALUE_CEILING_EUR = 6000.0


def self_declaration(agreement: str, currency: str | None, declared_value: float | None) -> dict:
    """Whether the value of this consignment lets any exporter sign for it.

    ``applies`` is false where the agreement has no such exception, and the
    reason says which case this is: under the ceiling and signed by the
    exporter, over it and needing an approval, or in a currency the ceiling
    cannot be measured in.
    """
    if agreement != "EUKOR":
        return {
            "applies": False,
            "allowed": False,
            "ceiling_eur": None,
            "reason": "this agreement has no value ceiling for a declaration by any exporter",
        }
    stated = str(currency or "").upper()
    if declared_value is None:
        return {
            "applies": True,
            "allowed": False,
            "ceiling_eur": LOW_VALUE_CEILING_EUR,
            "currency": stated or None,
            "reason": "the consignment states no value, so the ceiling cannot be tested",
        }
    if stated != "EUR":
        return {
            "applies": True,
            "allowed": False,
            "ceiling_eur": LOW_VALUE_CEILING_EUR,
            "currency": stated or None,
            "declared_value": declared_value,
            "reason": "the ceiling is EUR %.0f and the value is stated in %s, and this snapshot carries "
                      "no exchange rate" % (LOW_VALUE_CEILING_EUR, stated or "no currency"),
        }
    if float(declared_value) <= LOW_VALUE_CEILING_EUR + 1e-9:
        return {
            "applies": True,
            "allowed": True,
            "ceiling_eur": LOW_VALUE_CEILING_EUR,
            "currency": "EUR",
            "declared_value": declared_value,
            "reason": "the consignment is EUR %.2f, at or under the EUR %.0f ceiling, so any exporter "
                      "may sign the origin declaration and no approval is needed"
                      % (float(declared_value), LOW_VALUE_CEILING_EUR),
        }
    return {
        "applies": True,
        "allowed": False,
        "ceiling_eur": LOW_VALUE_CEILING_EUR,
        "currency": "EUR",
        "declared_value": declared_value,
        "reason": "the consignment is EUR %.2f and the ceiling is EUR %.0f"
                  % (float(declared_value), LOW_VALUE_CEILING_EUR),
    }


def requirement(agreement: str, required_by_agreement: bool, currency: str | None,
                declared_value: float | None) -> tuple[bool, dict]:
    """Whether this shipment needs an approval, and the value test behind it."""
    exception = self_declaration(agreement, currency, declared_value)
    return (bool(required_by_agreement) and not exception["allowed"]), exception


def blocks_claim(approval: dict | None) -> tuple[bool, str | None]:
    """Whether the approval on file bars the preference, and why.

    The requirement comes from the agreement, not from the file: an approval
    that this agreement does not ask for cannot block a claim under it.
    """
    if not approval or not approval.get("required"):
        return False, None
    status = approval.get("status")
    if status == "VALID":
        return False, None
    if status in BLOCKING:
        return True, "document: %s" % BLOCKING[status]
    return True, "document: approved exporter %s" % str(status).lower()


def _approval_for(shipment: dict, agreement: str) -> dict:
    """The approval on file for this agreement, from one or from a list.

    An exporter holds an approval per agreement, so a shipment may carry
    ``approved_exporters`` as a list.  The single ``approved_exporter`` form is
    still read, so a shipment written before the list existed keeps working.
    """
    many = shipment.get("approved_exporters")
    if isinstance(many, list) and many:
        for item in many:
            if isinstance(item, dict) and item.get("agreement") in (agreement, "ALL"):
                return item
        for item in many:
            if isinstance(item, dict) and item.get("agreement"):
                # An approval exists, just not for this agreement: the answer is
                # that, not that there is no approval at all.
                return item
    return shipment.get("approved_exporter") or {}


def approved_exporter(shipment: dict, agreement: str, required: bool, claimed_on: date,
                      exemption: dict | None = None) -> dict:
    """The approval on file, and whether this shipment needs one at all.

    ``exemption`` is the value test ``requirement`` returned.  When it lets the
    exporter sign the declaration itself, the status says so instead of saying
    that the agreement never asks.
    """
    approval = _approval_for(shipment, agreement)
    covers = approval.get("agreement") in (agreement, "ALL", None)
    if not approval:
        reason = ("this agreement needs an approved exporter approval"
                  if required
                  else "this agreement does not need an approved exporter approval")
        if exemption and exemption.get("applies"):
            if exemption.get("allowed"):
                reason = exemption["reason"]
            elif required:
                reason = "%s; %s" % (reason, exemption["reason"])
        return {
            "status": "ABSENT" if required else "NOT_REQUIRED",
            "required": required,
            "reason": reason,
            "value_ceiling": exemption if exemption and exemption.get("applies") else None,
        }
    if not covers:
        return {
            "status": "OTHER_AGREEMENT",
            "required": required,
            "reason": "the approval on file is for %s" % approval.get("agreement"),
            "valid_to": approval.get("valid_to"),
        }
    valid_to = approval.get("valid_to")
    valid_from = approval.get("valid_from")
    if valid_to and claimed_on > date.fromisoformat(str(valid_to)[:10]):
        return {
            "status": "EXPIRED",
            "required": required,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "reason": "approval expired on %s, before the claim date %s"
            % (str(valid_to)[:10], claimed_on.isoformat()),
            "ref": approval.get("ref"),
        }
    if valid_from and claimed_on < date.fromisoformat(str(valid_from)[:10]):
        return {
            "status": "NOT_YET_VALID",
            "required": required,
            "valid_from": valid_from,
            "reason": "approval starts on %s" % str(valid_from)[:10],
        }
    return {
        "status": "VALID",
        "required": required,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "ref": approval.get("ref"),
    }
