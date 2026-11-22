"""Dates the law puts on a claim.

Two deadlines decide whether a preference survives:

* a post import claim has to be made inside the window the law gives, counted
  from the import declaration, and
* an approved exporter approval, where the agreement requires one, has to be
  valid on the day the preference is claimed for.

Both are read from the store; the window length is a row with a citation, not
a number in the code.
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
    return shipment.get("approved_exporter") or {}


def approved_exporter(shipment: dict, agreement: str, required: bool, claimed_on: date) -> dict:
    approval = _approval_for(shipment, agreement)
    covers = approval.get("agreement") in (agreement, "ALL", None)
    if not approval:
        return {
            "status": "ABSENT" if required else "NOT_REQUIRED",
            "required": required,
            "reason": "this agreement needs an approved exporter approval"
            if required
            else "this agreement does not need an approved exporter approval",
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
