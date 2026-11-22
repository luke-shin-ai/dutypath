"""Duty, saving and the one number that matters.

The money is always computed from a rate row in the store, and every rate row
carries where it came from and what date it speaks for.  When the snapshot has
no rate for a line, the answer is that it has none; no rate is filled in from
outside the snapshot and no example figure is printed.
"""

from __future__ import annotations

from datetime import date

from . import rates as staging
from . import store

LINE_QUERY = """
MATCH (r:RateLine {hts8: $hts8, market: $market, agreement: $agreement})
MATCH (r)-[:CITED_FROM]->(src:Source)
RETURN r.hts8 AS hts8, r.description AS description, r.base_rate_percent AS base_rate_percent,
       r.base_rate_text AS base_rate_text, r.base_rate_kind AS base_rate_kind,
       r.staging AS staging, r.currency AS currency, src.id AS source, src.title AS source_title,
       src.as_of AS source_as_of
"""

HS6_QUERY = """
MATCH (r:Hs6Rate {hs6: $hs6, market: $market})
MATCH (r)-[:CITED_FROM]->(src:Source)
RETURN r.percent AS percent, r.lines AS lines, r.exact AS exact, r.year AS year,
       src.id AS source, src.title AS source_title
"""


def line_rate(conn, market: str, agreement: str, hts8: str, on: date) -> dict:
    """Rate for one tariff line under one agreement on one date."""
    row = store.one(conn, LINE_QUERY, {"hts8": hts8, "market": market, "agreement": agreement})
    if row is None:
        return {
            "percent": None,
            "basis": "not_in_snapshot",
            "reason": "%s has no %s rate line for %s in this snapshot"
            % (market, agreement, hts8),
        }
    if row["base_rate_kind"] != "percent":
        return {
            "percent": None,
            "basis": "specific_rate",
            "reason": "the base rate is %r, a specific duty this engine does not compute"
            % row["base_rate_text"],
        }
    staged = staging.staged_rate(row["base_rate_percent"], row["staging"], on)
    return {
        "percent": staged["percent"],
        "basis": "staged",
        "staging": row["staging"],
        "base_rate_percent": row["base_rate_percent"],
        "reason": staged["reason"],
        "source": row["source"],
        "source_title": row["source_title"],
        "line": hts8,
        "currency": row["currency"],
    }


def mfn_rate(conn, market: str, hts8: str, hs6: str) -> dict:
    """The rate a shipment pays when no agreement is claimed."""
    applied = store.one(conn, HS6_QUERY, {"hs6": hs6, "market": market})
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
    base = store.one(conn, LINE_QUERY, {"hts8": hts8, "market": market, "agreement": "KORUS"})
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
