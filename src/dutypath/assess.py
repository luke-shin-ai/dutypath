"""Assess one shipment.

The shipment comes in as JSON, is written to an in memory graph, and leaves as
a report.  The store is opened read only: the snapshot is the rule book, and a
verdict never changes it.
"""

from __future__ import annotations

from datetime import date

from . import deadline, duty, freshness, origin, store, validate
from . import markets as market_rules
from .origin import Material

MARKETS = {"US": "United States", "EU": "European Union", "TR": "Turkiye", "JP": "Japan"}


def _agreements(conn, market: str) -> list[dict]:
    rows = store.rows(
        conn,
        """
        MATCH (a:Agreement)
        WHERE a.code <> 'MFN' AND a.coverage <> 'none'
        RETURN a.code AS code, a.name AS name, a.market AS market, a.coverage AS coverage,
               a.approved_exporter_required AS approved_exporter_required, a.note AS note
        ORDER BY a.code
        """,
    )
    for row in rows:
        row["market_matches"] = row["market"] == market
    rows.sort(key=lambda row: (not row["market_matches"], row["code"]))
    return rows


def assess(conn, shipment: dict, on: date | None = None, order=None) -> dict:
    """Assess one shipment.

    ``order`` is the in memory graph of the shipment.  When it is not given it
    is built here and closed before returning, so the caller never has to know
    about it and the material list never outlives the answer.
    """
    from . import bom

    payload = validate.shipment(shipment)
    owns_order = order is None
    if order is None:
        order = bom.build(payload)
    try:
        return _assess(conn, payload, on, order)
    finally:
        if owns_order:
            order.close()


def _materials_from(order, shipment: dict) -> list[Material]:
    rows = []
    for row in order.execute(
        "MATCH (s:Shipment)-[:CONTAINS]->(m:Material) "
        "OPTIONAL MATCH (m)-[:CLASSIFIED_AS]->(c:Code) "
        "RETURN m.id AS id, m.origin AS origin, m.value AS value, m.description AS description, "
        "c.code AS code ORDER BY m.id"
    ):
        rows.append(
            Material(
                id=str(row["id"]),
                code=str(row["code"] or ""),
                origin=str(row["origin"] or ""),
                value=None if row["value"] is None else float(row["value"]),
                description=str(row["description"] or ""),
            )
        )
    return rows


def _assess(conn, shipment: dict, on: date | None, order) -> dict:
    shipment = validate.shipment(shipment)
    goods = shipment.get("goods") or {}
    hts8 = str(goods.get("hts8") or "")
    hs6 = str(goods.get("hs6") or hts8[:6])
    market = shipment.get("market") or "US"
    declared = float(goods.get("declared_value") or 0.0)
    currency = goods.get("currency") or "USD"
    when, date_basis = market_rules.assessment_date(shipment, on)
    import_date = date.fromisoformat(str(shipment.get("import_date") or when.isoformat())[:10])

    snap = store.one(
        conn,
        "MATCH (s:Snapshot) RETURN s.id AS id, toString(s.as_of) AS as_of, "
        "s.rule_version AS rule_version, s.max_age_days AS max_age_days",
    )
    fresh = freshness.judge(snap, when, freshness.vintages(conn, snap))

    mfn = duty.mfn_rate(conn, market, (shipment.get("goods") or {}).get("market_codes", {}).get(market) or hts8, hs6)
    mfn_duty = duty.duty_amount(mfn["percent"], declared)
    materials = _materials_from(order, shipment)

    results = []
    for agreement_row in _agreements(conn, market):
        # A classification is a decision per nomenclature.  The verdict for an
        # agreement is computed on the good's code in that agreement's own
        # market, so a United States shipment does not get a RCEP verdict priced
        # off an HTS line.
        agreement_code = market_rules.code_for_market(shipment, agreement_row["market"])
        if agreement_code is None:
            verdict = {
                "agreement": agreement_row["code"],
                "good": None,
                "rule": None,
                "verdict": origin.UNDECIDABLE,
                "reason": "the shipment states no %s code, so this agreement's origin rule "
                          "cannot be tested" % market_rules.MARKET_NOMENCLATURE.get(
                              agreement_row["market"], "tariff"),
                "path": [],
                "checks": [],
                "missing": ["the good's %s code for %s" % (
                    market_rules.MARKET_NOMENCLATURE.get(agreement_row["market"], "tariff"),
                    market_rules.MARKET_NAMES.get(agreement_row["market"], agreement_row["market"]))],
                "rvc_build_down": None,
                "rvc_build_up": None,
                "non_party_value": None,
            }
        else:
            verdict = origin.evaluate(
                conn, shipment, agreement_row["code"], materials, good_code=agreement_code, on=when
            )
        if agreement_row["market_matches"]:
            if agreement_code is None:
                rate = {
                    "percent": None,
                    "basis": "no_classification",
                    "reason": "the shipment states no tariff line for %s, and a code from another "
                    "nomenclature is not a classification in this one" % market_rules.MARKET_NAMES.get(market, market),
                }
            else:
                rate = duty.line_rate(conn, market, agreement_row["code"], agreement_code, when)
        else:
            rate = {
                "percent": None,
                "basis": "market_not_covered",
                "reason": "this agreement covers %s, not %s" % (agreement_row["market"], market),
            }
        required, exemption = deadline.requirement(
            agreement_row["code"], bool(agreement_row["approved_exporter_required"]), currency, declared
        )
        approval = deadline.approved_exporter(
            shipment, agreement_row["code"], required, when, exemption
        )
        preference_allowed = True
        block = None
        if not agreement_row["market_matches"]:
            preference_allowed = False
            block = "market: this agreement covers %s" % agreement_row["market"]
        elif verdict["verdict"] != origin.ORIGINATING:
            preference_allowed = False
            block = "origin: %s" % verdict["verdict"]
        elif rate["percent"] is None:
            preference_allowed = False
            block = "rate: %s" % rate["reason"]
        else:
            document_bar, document_reason = deadline.blocks_claim(approval)
            if document_bar:
                preference_allowed = False
                block = document_reason

        claim_duty = duty.duty_amount(rate["percent"], declared) if preference_allowed else None
        results.append(
            {
                "agreement": agreement_row["code"],
                "name": agreement_row["name"],
                "coverage": agreement_row["coverage"],
                "market": agreement_row["market"],
                "market_matches": agreement_row["market_matches"],
                "origin": verdict,
                "rate": rate,
                "documents": approval,
                "claim": {
                    "allowed": preference_allowed,
                    "blocked_by": block,
                    "duty": claim_duty,
                    "saving": round(mfn_duty - claim_duty, 2)
                    if (preference_allowed and claim_duty is not None and mfn_duty is not None)
                    else None,
                },
            }
        )

    claimable = [item for item in results if item["claim"]["allowed"]]
    best = min(claimable, key=lambda item: item["rate"]["percent"]) if claimable else None

    report = {
        "shipment": {
            "id": shipment.get("shipment_id"),
            "market": market,
            "market_name": MARKETS.get(market, market),
            "assessed_on": when.isoformat(),
            "date_basis": date_basis,
            "import_date": import_date.isoformat(),
            "goods": {
                "hts8": hts8,
                "hs6": hs6,
                "description": goods.get("description", ""),
                "declared_value": declared,
                "currency": currency,
            },
            "materials": len(shipment.get("materials") or []),
        },
        "snapshot": fresh,
        "mfn": {**mfn, "duty": mfn_duty},
        "agreements": results,
        "claim": _decision(best, mfn_duty, results),
        "deadline": deadline.post_import_claim(conn, "KORUS" if market == "US" else "RCEP", import_date, when),
    }
    return report


def _decision(best: dict | None, mfn_duty: float | None, results: list[dict]) -> dict:
    if best is not None:
        return {
            "decision": "CLAIM %s" % best["agreement"],
            "agreement": best["agreement"],
            "rate": best["rate"]["percent"],
            "duty": best["claim"]["duty"],
            "saving": best["claim"]["saving"],
            "exposure": 0.0,
            "reason": "%s origin holds, the rate is in the snapshot and the documents are in order"
            % best["agreement"],
        }
    reasons = []
    for item in results:
        if item["claim"]["blocked_by"]:
            reasons.append("%s: %s" % (item["agreement"], item["claim"]["blocked_by"]))
    return {
        "decision": "NO CLAIM",
        "agreement": None,
        "rate": None,
        "duty": mfn_duty,
        "saving": 0.0,
        "exposure": mfn_duty,
        "reason": "; ".join(reasons) if reasons else "no agreement applies to this market",
    }
