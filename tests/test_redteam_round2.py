"""Regression tests for the second red team round.

Five answers the engine gave that a reader could not rely on:

* a material from Split in 2026 was not an EU party material, and one from
  Leeds in 2012 was not either, because the party list was frozen on the wrong
  day and carried the wrong two states;
* a consignment worth EUR 4,000 to the EU was refused for want of an approved
  exporter, though the agreement lets any exporter sign below its ceiling;
* the rate was read on the export date, so a shipment that crossed New Year
  between leaving Korea and entering the market was priced on the wrong year of
  the schedule;
* the snapshot called itself fresh while the applied MFN rate under it was the
  2023 WITS figure, three years older than the snapshot date;
* the MCP server opened any path a caller named and returned every row a
  statement matched.

Each test below is the input that used to get the wrong answer, and the
assertion is the answer the engine gives now.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dutypath import deadline, duty, freshness, markets, origin, store  # noqa: E402
from dutypath import mcp as server  # noqa: E402

DATA = ROOT / "data" / "extract-2026-11-22"
FIXTURES = ROOT / "fixtures"


@pytest.fixture(scope="session")
def store_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("store") / "dutypath-rules.rl"
    conn = store.connect(str(path))
    conn.autocommit = False
    from dutypath import build

    build.build(conn, str(DATA))
    conn.commit()
    conn.close()
    return str(path)


@pytest.fixture()
def conn(store_path):
    connection = store.connect(store_path)
    connection.autocommit = False
    yield connection
    connection.close()


def shipment(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as handle:
        return json.load(handle)


def case(materials, good="85044095", value=480000.0, currency="USD", eu_code="85044090") -> dict:
    return {
        "shipment_id": "RT2-1",
        "market": "US",
        "export_date": "2026-12-01",
        "import_date": "2026-12-08",
        "goods": {"hts8": good, "declared_value": value, "currency": currency,
                  "market_codes": {"US": good, "EU": eu_code, "JP": "850440090"}},
        "materials": materials,
    }


# --------------------------------------------------------------- EU parties


def test_the_eu_party_is_the_twenty_seven_members_of_today():
    members = origin.eu_member_states()
    assert len(members) == 27
    assert "HR" in members, "Croatia joined the Union on 2013-07-01"
    assert "GB" not in members, "the United Kingdom left on 2020-01-31"


def test_the_member_list_moves_with_the_day_it_is_asked_about():
    before_croatia = origin.eu_member_states(date(2013, 6, 30))
    assert "HR" not in before_croatia
    during_transition = origin.eu_member_states(date(2019, 6, 1))
    assert "GB" in during_transition and "HR" in during_transition
    after_brexit = origin.eu_member_states(date(2020, 2, 1))
    assert "GB" not in after_brexit


def test_a_croatian_material_is_a_party_material_in_2026(conn):
    payload = case([{"id": "M1", "hts8": "85043180", "origin": "HR", "value": 150000}],
                   good="85044090", value=480000)
    report = origin.evaluate(conn, payload, "EUKOR", good_code="85044090")
    assert report["non_party_value"] == 0.0
    assert report["verdict"] == origin.ORIGINATING


def test_a_british_material_is_not_a_party_material_in_2026(conn):
    payload = case([{"id": "M1", "hts8": "85043180", "origin": "GB", "value": 150000}],
                   good="85044090", value=200000)
    report = origin.evaluate(conn, payload, "EUKOR", good_code="85044090")
    assert report["non_party_value"] == 150000.0
    assert report["verdict"] == origin.NOT_ORIGINATING


def test_a_british_material_was_a_party_material_while_it_was_a_member(conn):
    payload = case([{"id": "M1", "hts8": "85043180", "origin": "GB", "value": 150000}],
                   good="85044090", value=200000)
    report = origin.evaluate(conn, payload, "EUKOR", good_code="85044090",
                             on=date(2012, 5, 1))
    assert report["non_party_value"] == 0.0
    assert report["verdict"] == origin.ORIGINATING


def test_a_croatian_material_before_accession_is_not_a_party_material(conn):
    payload = case([{"id": "M1", "hts8": "85043180", "origin": "HR", "value": 150000}],
                   good="85044090", value=200000)
    report = origin.evaluate(conn, payload, "EUKOR", good_code="85044090",
                             on=date(2013, 6, 30))
    assert report["non_party_value"] == 150000.0


# ------------------------------------------------------- the value ceiling


def _eu_self_declared(conn, value: float, currency: str, materials=None) -> dict:
    payload = case(materials or [{"id": "M1", "hts8": "85043180", "origin": "DE", "value": 1000}],
                   good="85044090", value=value, currency=currency)
    report = markets.compare(conn, payload)
    return [block for block in report["markets"] if block["market"] == "EU"][0]


def test_a_consignment_under_the_ceiling_needs_no_approval(conn):
    eu = _eu_self_declared(conn, 4000, "EUR")
    assert eu["origin"]["verdict"] == origin.ORIGINATING
    assert eu["documents"]["status"] == "NOT_REQUIRED"
    assert eu["documents"]["value_ceiling"]["allowed"] is True
    assert "any exporter" in eu["documents"]["reason"]
    assert eu["claim"]["allowed"] is True


def test_the_ceiling_itself_is_included(conn):
    eu = _eu_self_declared(conn, 6000, "EUR")
    assert eu["documents"]["status"] == "NOT_REQUIRED"
    assert eu["claim"]["allowed"] is True


def test_one_cent_over_the_ceiling_needs_the_approval(conn):
    eu = _eu_self_declared(conn, 6000.01, "EUR")
    assert eu["documents"]["status"] == "ABSENT"
    assert eu["documents"]["required"] is True
    assert eu["claim"]["allowed"] is False
    assert "approved exporter" in eu["claim"]["blocked_by"]
    assert "EUR 6000" in eu["documents"]["reason"]


def test_a_value_in_another_currency_is_not_measured_against_a_euro_ceiling(conn):
    eu = _eu_self_declared(conn, 4000, "USD")
    assert eu["documents"]["status"] == "ABSENT"
    assert "no exchange rate" in eu["documents"]["reason"]
    assert eu["claim"]["allowed"] is False


def test_the_ceiling_is_not_read_into_an_agreement_that_has_none():
    for agreement in ("KORUS", "RCEP", "TURKOR"):
        test = deadline.self_declaration(agreement, "EUR", 10.0)
        assert test["applies"] is False


def test_the_ceiling_does_not_waive_an_approval_that_is_on_file_but_expired(conn):
    payload = case([{"id": "M1", "hts8": "85043180", "origin": "DE", "value": 1000}],
                   good="85044090", value=4000, currency="EUR")
    payload["approved_exporters"] = [
        {"agreement": "EUKOR", "valid_from": "2020-01-01", "valid_to": "2024-01-01"}
    ]
    eu = [block for block in markets.compare(conn, payload)["markets"] if block["market"] == "EU"][0]
    assert eu["documents"]["status"] == "EXPIRED"
    assert eu["documents"]["required"] is False
    assert eu["claim"]["allowed"] is True


# ------------------------------------------------------------ the rate date


def test_the_rate_is_read_on_the_import_date_not_the_export_date(conn):
    payload = shipment("shipment-3901-polymer.json")
    payload["export_date"] = "2026-12-28"
    payload["import_date"] = "2027-01-05"
    report = markets.compare(conn, payload)
    japan = [block for block in report["markets"] if block["market"] == "JP"][0]
    # Japan prints 1.9 percent for year 5 and 1.8 for year 6.
    assert report["shipment"]["assessed_on"] == "2027-01-05"
    assert report["shipment"]["date_basis"] == "import_date"
    assert japan["rate"]["percent"] == pytest.approx(1.8)
    assert japan["rate"]["reason"] == "year 6 of the schedule prints 1.8 percent"


def test_an_export_on_the_same_day_would_have_paid_the_earlier_year(conn):
    payload = shipment("shipment-3901-polymer.json")
    payload["export_date"] = "2026-12-28"
    payload["import_date"] = "2027-01-05"
    report = markets.compare(conn, payload, date(2026, 12, 28))
    japan = [block for block in report["markets"] if block["market"] == "JP"][0]
    assert report["shipment"]["date_basis"].startswith("the date given")
    assert japan["rate"]["percent"] == pytest.approx(1.9)


def test_the_exchange_rate_of_a_rate_line_follows_the_entry_date(conn):
    on = date(2027, 1, 5)
    early = duty.line_rate(conn, "JP", "RCEP", "390110090", date(2026, 12, 28))
    late = duty.line_rate(conn, "JP", "RCEP", "390110090", on)
    assert early["percent"] == pytest.approx(1.9)
    assert late["percent"] == pytest.approx(1.8)


def test_a_shipment_with_no_date_at_all_is_an_input_error(conn):
    from dutypath import validate

    payload = case([{"id": "M1", "hts8": "85043180", "origin": "DE", "value": 1000}],
                   good="85044090")
    payload.pop("export_date")
    payload.pop("import_date")
    with pytest.raises(validate.InputError) as error:
        markets.compare(conn, payload)
    assert "import_date" in str(error.value)


# ------------------------------------------------------- the data vintage


def test_a_fresh_snapshot_still_names_the_year_of_its_mfn_rows(conn):
    vintage = freshness.vintages(conn, {"as_of": "2026-11-22"})
    mfn = [item for item in vintage if item["block"] == "applied MFN rate"][0]
    assert mfn["source"] == "SRC-WITS-2023"
    assert mfn["as_of"] == "2023-12-31"
    assert mfn["days_before_snapshot_date"] == 1057
    deadline_row = [item for item in vintage if item["block"] == "post import claim window"][0]
    assert deadline_row["as_of"] == "2025-02-12"
    assert deadline_row["days_before_snapshot_date"] == 648


def test_the_claim_window_carries_its_own_date_in_the_caveat(conn):
    report = markets.compare(conn, shipment("shipment-8501-motor.json"))
    caveat = " ".join(report["snapshot"]["caveats"])
    assert "2025-02-12" in caveat
    assert "648 days" in caveat


def test_the_snapshot_caveat_reaches_the_comparison(conn):
    report = markets.compare(conn, shipment("shipment-8504-converter.json"))
    snapshot = report["snapshot"]
    assert snapshot["status"] == "FRESH"
    assert snapshot["data_vintage"][0]["as_of"] == "2023-12-31"
    caveat = " ".join(snapshot["caveats"])
    assert "2023-12-31" in caveat
    assert "2026-11-22" in caveat
    assert "1057 days" in caveat


def test_the_mfn_row_the_report_prices_carries_its_own_date(conn):
    # 8507.60 has a single tariff line behind it, so the WITS value is a rate
    # this engine prices with, and that rate is the 2023 one.
    us_mfn = duty.mfn_rate(conn, "US", "85076000", "850760")
    assert us_mfn["basis"] == "applied_mfn"
    assert us_mfn["as_of"] == "2023-12-31"
    assert us_mfn["source"] == "SRC-WITS-2023"


def test_a_snapshot_without_components_keeps_the_fields_empty():
    plain = freshness.judge({"id": "x", "as_of": "2026-11-22", "max_age_days": 120}, date(2026, 12, 1))
    assert plain["data_vintage"] == []
    assert plain["caveats"] == []


# ------------------------------------------------------- the MCP boundary


def test_a_shipment_path_outside_the_working_directory_is_refused(store_path):
    tool = server.Server(store_path)
    try:
        outside = str((ROOT / ".." / ".." / ".." / "etc" / "passwd").resolve())
        with pytest.raises(ValueError) as error:
            tool.compare_markets({"shipment_path": outside})
        message = str(error.value)
        assert "working directory" in message
        assert "root:" not in message
        with pytest.raises(ValueError):
            tool.assess_shipment({"shipment_path": "../../../../etc/passwd"})
        with pytest.raises(ValueError):
            tool.verify_zero_leak({"shipment_path": "/etc/hostname"})
    finally:
        tool.close()


def test_a_shipment_path_inside_the_working_directory_still_works(store_path):
    tool = server.Server(store_path)
    try:
        report = tool.compare_markets({"shipment_path": "fixtures/shipment-8504-converter.json"})
        assert report["shipment"]["id"] == "SHP-2026-1201-001"
    finally:
        tool.close()


def test_the_graph_reader_stops_at_five_hundred_rows(store_path):
    tool = server.Server(store_path)
    try:
        # A rate line per row is well over the cap, so the call has to stop.
        answer = tool.read_cypher({"statement": "MATCH (r:RateLine) RETURN r.code AS code"})
        assert answer["limit"] == 500
        assert answer["count"] == 500
        assert answer["truncated"] is True
        assert "500" in answer["note"]
    finally:
        tool.close()


def test_a_caller_can_ask_for_fewer_rows_but_not_for_more(store_path):
    tool = server.Server(store_path)
    try:
        small = tool.read_cypher({"statement": "MATCH (r:OriginRule) RETURN r.id AS id", "limit": 3})
        assert small["count"] == 3 and small["truncated"] is True
        larger = tool.read_cypher(
            {"statement": "MATCH (r:OriginRule) RETURN r.id AS id", "limit": 10_000}
        )
        assert larger["limit"] == 500
        with pytest.raises(ValueError):
            tool.read_cypher({"statement": "MATCH (n) RETURN n", "limit": "all"})
    finally:
        tool.close()


def test_a_short_read_is_not_marked_truncated(store_path):
    tool = server.Server(store_path)
    try:
        answer = tool.read_cypher(
            {"statement": "MATCH (r:OriginRule) WHERE r.id = 'OR-0001' RETURN r.id AS id"}
        )
        assert answer["count"] == 1
        assert answer["truncated"] is False
        assert answer["note"] is None
    finally:
        tool.close()
