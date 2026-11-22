"""One bill of materials, three markets, three answers.

The question the tool prices is not "what is the rate" but "where do I declare
this shipment".  The same material list goes to the United States under KORUS,
to the European Union under the Korea-EU agreement, and to Japan under RCEP, and
each agreement asks its own origin question and prints its own rate.

Three things make the answers differ, and the comparison keeps them apart:

* the origin rule - KORUS may exclude a heading the EU rule allows,
* the rate schedule - one market may already be duty free, another may exclude
  the line for Korean goods,
* the document - the EU and RCEP routes need an approved exporter, KORUS does
  not.

Each market is priced in the shipment's own currency: the declared value is
multiplied by that market's percentage, so the amounts compare directly without
a currency conversion this snapshot could not support.
"""

from __future__ import annotations

from datetime import date

from . import deadline, duty, freshness, origin, store

MARKET_AGREEMENT = {"US": "KORUS", "EU": "EUKOR", "JP": "RCEP"}
MARKET_NAMES = {
    "US": "United States",
    "EU": "European Union",
    "JP": "Japan",
}
MARKET_NOMENCLATURE = {"US": "HTS eight digit", "EU": "CN eight digit", "JP": "Japan nine digit"}


def code_for_market(shipment: dict, market: str) -> str | None:
    """The good's tariff line in one market's nomenclature.

    A classification is a decision the exporter makes per nomenclature, so the
    shipment states it.  When it does not, the market is undecidable rather than
    priced on a code from another market's naming.
    """
    goods = shipment.get("goods") or {}
    codes = goods.get("market_codes") or {}
    value = codes.get(market)
    if value:
        return str(value)
    if market == "US":
        code = goods.get("hts8")
        return str(code) if code else None
    return None


def compare(conn, shipment: dict, on: date | None = None) -> dict:
    goods = shipment.get("goods") or {}
    declared = float(goods.get("declared_value") or 0.0)
    currency = goods.get("currency") or "USD"
    when = on or date.fromisoformat(str(shipment.get("export_date") or shipment.get("import_date"))[:10])
    import_date = date.fromisoformat(str(shipment.get("import_date") or when.isoformat())[:10])

    snap = store.one(
        conn,
        "MATCH (s:Snapshot) RETURN s.id AS id, toString(s.as_of) AS as_of, s.rule_version AS rule_version",
    )
    fresh = freshness.judge(snap, when)

    blocks = []
    for market, agreement in MARKET_AGREEMENT.items():
        blocks.append(_market(conn, shipment, market, agreement, when, declared, currency))

    priced = [block for block in blocks if block["duty"]["amount"] is not None and block["claim"]["allowed"]]
    best = min(priced, key=lambda block: block["duty"]["amount"]) if priced else None
    cheapest = min(
        [block for block in blocks if block["duty"]["amount"] is not None],
        key=lambda block: block["duty"]["amount"],
        default=None,
    )
    dearest = max(
        [block for block in blocks if block["duty"]["amount"] is not None],
        key=lambda block: block["duty"]["amount"],
        default=None,
    )

    return {
        "shipment": {
            "id": shipment.get("shipment_id"),
            "description": goods.get("description", ""),
            "declared_value": declared,
            "currency": currency,
            "assessed_on": when.isoformat(),
            "import_date": import_date.isoformat(),
            "materials": len(shipment.get("materials") or []),
            "codes": {market: code_for_market(shipment, market) for market in MARKET_AGREEMENT},
        },
        "snapshot": fresh,
        "markets": blocks,
        "best_claim": {
            "market": best["market"] if best else None,
            "agreement": best["agreement"] if best else None,
            "duty": best["duty"]["amount"] if best else None,
            "saving": best["claim"]["saving"] if best else None,
        },
        "ranking": {
            "cheapest": cheapest["market"] if cheapest else None,
            "dearest": dearest["market"] if dearest else None,
            "spread": round(dearest["duty"]["amount"] - cheapest["duty"]["amount"], 2)
            if (cheapest and dearest)
            else None,
            "currency": currency,
        },
        "claim_window": deadline.post_import_claim(conn, "KORUS", import_date, when),
    }


def _market(conn, shipment, market: str, agreement: str, when: date, declared: float, currency: str) -> dict:
    code = code_for_market(shipment, market)
    row = store.one(
        conn,
        "MATCH (a:Agreement {code: $code}) RETURN a.name AS name, a.market AS market, "
        "a.coverage AS coverage, a.approved_exporter_required AS approved_exporter_required, "
        "a.note AS note, a.in_force AS in_force",
        {"code": agreement},
    ) or {}
    mfn = duty.mfn_rate(conn, market, code or "", (code or "")[:6])
    mfn_amount = duty.duty_amount(mfn["percent"], declared)

    block = {
        "market": market,
        "market_name": MARKET_NAMES.get(market, market),
        "agreement": agreement,
        "agreement_name": row.get("name"),
        "code": code,
        "nomenclature": MARKET_NOMENCLATURE.get(market),
        "origin": None,
        "rate": {"percent": None, "reason": "the good has no classification in this market's nomenclature"},
        "mfn": {**mfn, "amount": mfn_amount},
        "documents": {"status": "UNKNOWN"},
        "claim": {"allowed": False, "blocked_by": "classification: the shipment states no line for this "
        "market's nomenclature", "duty": None, "saving": None},
        "duty": {"amount": mfn_amount, "currency": currency, "basis": "MFN"},
        "missing": [],
    }

    if code is None:
        block["missing"] = [
            "the good's %s code for %s" % (MARKET_NOMENCLATURE.get(market, "tariff"), MARKET_NAMES.get(market))
        ]
        block["verdict"] = "UNDECIDABLE"
        return block

    verdict = origin.evaluate(conn, shipment, agreement, good_code=code)
    rate = duty.line_rate(conn, market, agreement, code, when)
    approval = deadline.approved_exporter(
        shipment, agreement, bool(row.get("approved_exporter_required")), when
    )

    block["origin"] = verdict
    block["rate"] = rate
    block["documents"] = approval
    block["missing"] = list(verdict.get("missing") or [])

    allowed = True
    blocked = None
    if verdict["verdict"] != origin.ORIGINATING:
        allowed = False
        blocked = "origin: %s" % verdict["verdict"]
    elif rate["percent"] is None:
        allowed = False
        blocked = "rate: %s" % rate["reason"]
    elif approval["status"] in ("EXPIRED", "NOT_YET_VALID", "ABSENT"):
        allowed = False
        blocked = "document: approved exporter %s" % approval["status"].lower()

    claim_duty = duty.duty_amount(rate["percent"], declared) if allowed else None
    preferential_duty = duty.duty_amount(rate["percent"], declared)
    block["potential"] = {
        "rate": rate["percent"],
        "duty": preferential_duty,
        "saving": round(mfn_amount - preferential_duty, 2)
        if (preferential_duty is not None and mfn_amount is not None)
        else None,
    }
    block["claim"] = {
        "allowed": allowed,
        "blocked_by": blocked,
        "rate": rate["percent"],
        "duty": claim_duty,
        "saving": round(mfn_amount - claim_duty, 2) if (allowed and claim_duty is not None and mfn_amount is not None) else None,
    }
    block["duty"] = {
        "amount": claim_duty if allowed else mfn_amount,
        "currency": currency,
        "basis": agreement if allowed else "MFN",
    }
    block["verdict"] = (
        "CLAIM"
        if allowed
        else ("UNDECIDABLE" if verdict["verdict"] == origin.UNDECIDABLE else "NO CLAIM")
    )
    block["excluded_materials"] = [
        item for item in (verdict.get("path") or []) if "excluded provision" in item or "inside group" in item
    ]
    return block
