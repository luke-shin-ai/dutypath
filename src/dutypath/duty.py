"""Duty, saving and the one number that matters.

The money is always computed from a rate row in the store, and every rate row
carries where it came from and what date it speaks for.  When the snapshot has
no rate for a line, the answer is that it has none; no rate is filled in from
outside the snapshot and no example figure is printed.

Three markets mean three schedules and three kinds of row:

* the United States under KORUS prints a base rate and a staging category,
* the European Union under the Korea-EU agreement prints a base rate and a
  numbered category,
* Japan under RCEP prints the rate for every single year.

``line_rate`` reads whichever of the three the row is and hands the arithmetic
to ``rates``, so the number a verdict prints is the number the row supports.
"""

from __future__ import annotations

from datetime import date

from . import rates as staging
from . import store

LINE_QUERY = """
MATCH (r:RateLine {code: $code, market: $market, agreement: $agreement})
MATCH (r)-[:CITED_FROM]->(src:Source)
RETURN r.code AS code, r.description AS description, r.base_rate_percent AS base_rate_percent,
       r.base_rate_text AS base_rate_text, r.base_rate_kind AS base_rate_kind,
       r.staging AS staging, r.years AS years, r.partner AS partner,
       r.currency AS currency, src.id AS source, src.title AS source_title,
       src.as_of AS source_as_of
ORDER BY CASE WHEN r.partner = 'KR' THEN 0 ELSE 1 END
LIMIT 1
"""

HS6_QUERY = """
MATCH (r:Hs6Rate {hs6: $hs6, market: $market})
MATCH (r)-[:CITED_FROM]->(src:Source)
RETURN r.percent AS percent, r.lines AS lines, r.exact AS exact, r.year AS year,
       src.id AS source, src.title AS source_title
"""


def line_rate(conn, market: str, agreement: str, code: str, on: date) -> dict:
    """Rate for one tariff line under one agreement on one date."""
    row = store.one(conn, LINE_QUERY, {"code": code, "market": market, "agreement": agreement})
    if row is None:
        return {
            "percent": None,
            "basis": "not_in_snapshot",
            "reason": "%s has no %s rate line for %s in this snapshot" % (market, agreement, code),
            "line": code,
        }
    if agreement in ("KORUS", "EUKOR") and row["base_rate_kind"] != "percent":
        return {
            "percent": None,
            "basis": "specific_rate",
            "reason": "the base rate is %r, a specific duty this engine does not compute"
            % row["base_rate_text"],
            "line": code,
            "source": row["source"],
            "source_title": row["source_title"],
        }

    if agreement == "KORUS":
        staged = staging.staged_rate(row["base_rate_percent"], row["staging"], on)
    elif agreement == "EUKOR":
        staged = staging.eu_staged_rate(row["base_rate_percent"], row["staging"], on)
    else:
        # The printed schedule carries the rate of every year, including a
        # compound duty that this engine cannot compute and a U cell.
        staged = staging.printed_rate(row["years"], row["staging"], on)

    return {
        "percent": staged["percent"],
        "basis": staged.get("basis", "staged"),
        "staging": row["staging"],
        "base_rate_percent": row["base_rate_percent"],
        "base_rate_text": row["base_rate_text"],
        "reason": staged["reason"],
        "source": row["source"],
        "source_title": row["source_title"],
        "line": code,
        "partner": row.get("partner"),
        "currency": row["currency"],
    }


def mfn_rate(conn, market: str, code: str, hs6: str | None = None) -> dict:
    """The rate a shipment pays when no agreement is claimed."""
    if market == "US":
        return _us_mfn(conn, code, hs6 or code[:6])
    row = store.one(
        conn,
        LINE_QUERY,
        {"code": code, "market": market, "agreement": _agreement_of(market)},
    )
    if row is None:
        return {"percent": None, "basis": "not_in_snapshot", "reason": "no MFN rate for this line"}
    if row["base_rate_kind"] != "percent":
        return {
            "percent": None,
            "basis": "specific_rate",
            "reason": "the base rate is %r, a specific duty this engine does not compute"
            % row["base_rate_text"],
            "source": row["source"],
        }
    return {
        "percent": row["base_rate_percent"],
        "basis": "schedule_base_rate",
        "as_of": str(row["source_as_of"])[:10],
        "reason": "the base rate printed in the schedule; it is the MFN rate on the date the "
        "schedule records, not a live MFN query",
        "source": row["source"],
        "source_title": row["source_title"],
    }


def _agreement_of(market: str) -> str:
    return {"US": "KORUS", "EU": "EUKOR", "JP": "RCEP"}.get(market, "KORUS")


def _us_mfn(conn, hts8: str, hs6: str) -> dict:
    applied = store.one(conn, HS6_QUERY, {"hs6": hs6, "market": "US"})
    if applied and applied["exact"]:
        return {
            "percent": applied["percent"],
            "basis": "applied_mfn",
            "as_of": "%s-12-31" % applied["year"],
            "lines": applied["lines"],
            "reason": "applied MFN rate, the six digit line has a single tariff line",
            "source": applied["source"],
            "source_title": applied["source_title"],
        }
    base = store.one(conn, LINE_QUERY, {"code": hts8, "market": "US", "agreement": "KORUS"})
    if base and base["base_rate_kind"] == "percent":
        return {
            "percent": base["base_rate_percent"],
            "basis": "agreement_base_rate",
            "as_of": "2006-01-01",
            "reason": "the base rate recorded in the agreement schedule; the applied MFN of this line "
                      "after 2006 is not in this snapshot",
            "source": base["source"],
            "source_title": base["source_title"],
        }
    if applied:
        return {
            "percent": None,
            "basis": "ambiguous",
            "reason": "the six digit line has %d tariff lines; an average of them is not a rate for this "
                      "shipment and this snapshot has no line level applied rate" % applied["lines"],
            "source": applied["source"],
        }
    return {"percent": None, "basis": "not_in_snapshot", "reason": "no MFN rate for this line"}


def duty_amount(percent: float | None, value: float) -> float | None:
    if percent is None:
        return None
    return round(value * percent / 100.0, 2)
