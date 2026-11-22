"""Unit and boundary tests.

The store is built once per session from data/extract-2026-11-22, into a
temporary file, so a test never touches the committed store.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dutypath import assess, bom, build, codes, deadline, duty, freshness, leak, origin, rates, store  # noqa: E402
from dutypath import rules as rulebook  # noqa: E402

DATA = ROOT / "data" / "extract-2026-11-22"
FIXTURES = ROOT / "fixtures"


@pytest.fixture(scope="session")
def store_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("store") / "dutypath-rules.rl"
    conn = store.connect(str(path))
    conn.autocommit = False
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


# ---------------------------------------------------------------- codes

def test_normalise_pads_a_heading_to_the_top_of_its_interval():
    assert codes.normalise("85") == "85999999"
    assert codes.normalise("8507") == "85079999"
    assert codes.normalise("8507.60") == "85076099"
    assert codes.normalise("85076040") == "85076040"


def test_normalise_low_pads_to_the_bottom():
    assert codes.normalise_low("8507.60") == "85076000"
    assert codes.normalise_low("85") == "85000000"


def test_is_under_reads_levels_from_the_code():
    assert codes.is_under("8507.60", "85")
    assert codes.is_under("8507.60", "8507")
    assert not codes.is_under("8504.40", "8507")


def test_ancestors_go_up_one_level_at_a_time():
    assert codes.ancestors("85076040") == ["85", "8507", "850760"]
    assert codes.ancestors("850760") == ["85", "8507"]
    assert codes.ancestors("8507") == ["85"]


def test_level_of_names_the_three_levels():
    assert codes.level_of("8507") == "heading"
    assert codes.level_of("8507.60") == "subheading"
    assert codes.level_of("85076040") == "line"


# ---------------------------------------------------------------- staging

def test_staging_a_is_duty_free_on_entry_into_force():
    assert rates.staged_rate(4.0, "A", date(2012, 3, 15))["percent"] == 0.0


def test_staging_before_entry_into_force_has_no_rate():
    result = rates.staged_rate(4.0, "A", date(2012, 3, 14))
    assert result["percent"] is None
    assert "entered into force" in result["reason"]


def test_staging_d_first_year_keeps_four_fifths():
    assert rates.staged_rate(6.5, "D", date(2012, 6, 1))["percent"] == 5.2


def test_staging_d_second_year_keeps_three_fifths():
    assert rates.staged_rate(6.5, "D", date(2013, 1, 1))["percent"] == 3.9


def test_staging_d_is_duty_free_from_january_first_of_year_five():
    assert rates.staged_rate(6.5, "D", date(2015, 12, 31))["percent"] == 1.3
    assert rates.staged_rate(6.5, "D", date(2016, 1, 1))["percent"] == 0.0


def test_staging_g_reaches_zero_once_ten_years_have_passed():
    assert rates.staged_rate(5.3, "G", date(2026, 12, 1))["percent"] == 0.0


def test_staging_j_holds_the_base_rate_through_year_eight():
    assert rates.staged_rate(2.5, "J", date(2019, 6, 1))["percent"] == 2.5


def test_staging_j_cuts_in_four_from_year_nine():
    assert rates.staged_rate(4.0, "J", date(2020, 1, 1))["percent"] == 3.0
    assert rates.staged_rate(4.0, "J", date(2021, 1, 1))["percent"] == 2.0
    assert rates.staged_rate(4.0, "J", date(2023, 1, 1))["percent"] == 0.0


def test_staging_i_removes_five_percent_of_the_base_in_year_one():
    assert rates.staged_rate(10.0, "I", date(2012, 3, 15))["percent"] == 9.5
    assert rates.staged_rate(10.0, "I", date(2022, 1, 1))["percent"] == 0.0


def test_staging_k_is_duty_free_from_the_start():
    assert rates.staged_rate(9.9, "K", date(2012, 3, 15))["percent"] == 0.0


def test_staging_without_a_definition_returns_nothing():
    result = rates.staged_rate(5.0, "W", date(2026, 1, 1))
    assert result["percent"] is None
    assert "not defined" in result["reason"]


def test_interim_rates_round_down_to_a_tenth():
    # 3.3 percent over three stages leaves 2.2 in year one, 1.1 in year two.
    assert rates.staged_rate(3.3, "C", date(2012, 4, 1))["percent"] == 2.2
    assert rates.staged_rate(3.3, "C", date(2013, 4, 1))["percent"] == 1.1


# ---------------------------------------------------------------- deadlines

def test_add_months_keeps_the_day():
    assert deadline.add_months(date(2026, 12, 8), 12) == date(2027, 12, 8)


def test_add_months_clamps_to_the_end_of_a_short_month():
    assert deadline.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert deadline.add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)


def test_post_import_claim_is_open_inside_the_year(conn):
    result = deadline.post_import_claim(conn, "KORUS", date(2026, 12, 8), date(2027, 6, 1))
    assert result["status"] == "OPEN"
    assert result["deadline"] == "2027-12-08"


def test_post_import_claim_closes_after_the_year(conn):
    result = deadline.post_import_claim(conn, "KORUS", date(2026, 12, 8), date(2027, 12, 9))
    assert result["status"] == "CLOSED"
    assert result["days_left"] == -1


def test_approval_expired_before_the_claim_date():
    result = deadline.approved_exporter(
        shipment("shipment-8504-converter.json"), "RCEP", True, date(2026, 12, 1)
    )
    assert result["status"] == "EXPIRED"


def test_approval_valid_on_the_claim_date():
    payload = {"approved_exporter": {"agreement": "RCEP", "valid_to": "2027-01-31"}}
    result = deadline.approved_exporter(payload, "RCEP", True, date(2026, 12, 1))
    assert result["status"] == "VALID"


def test_approval_absent_where_the_agreement_needs_one():
    result = deadline.approved_exporter({}, "RCEP", True, date(2026, 12, 1))
    assert result["status"] == "ABSENT"


def test_approval_not_needed_where_the_agreement_does_not_ask():
    result = deadline.approved_exporter({}, "KORUS", False, date(2026, 12, 1))
    assert result["status"] == "NOT_REQUIRED"


# ---------------------------------------------------------------- freshness

def test_a_recent_snapshot_is_fresh():
    result = freshness.judge({"id": "x", "as_of": "2026-11-22", "max_age_days": 120}, date(2026, 12, 1))
    assert result["fresh"] is True
    assert result["status"] == "FRESH"


def test_an_old_snapshot_asks_for_a_resync():
    result = freshness.judge({"id": "x", "as_of": "2026-11-22", "max_age_days": 120}, date(2027, 6, 1))
    assert result["fresh"] is False
    assert "STALE_SNAPSHOT" in result["status"]


def test_a_store_without_a_snapshot_row_is_stale():
    assert "STALE_SNAPSHOT" in freshness.judge(None, date(2026, 12, 1))["status"]


# ---------------------------------------------------------------- rule reading

def test_a_rule_with_two_alternatives_is_split_at_the_or():
    text = (
        "A change to subheading 8507.10 from any other heading; or A change to subheading 8507.10 "
        "from any other subheading, provided that there is a regional value content of not less than: "
        "(a) 35 percent under the build-up method, or (b) 45 percent under the build-down method."
    )
    parts = rulebook.split_alternatives(text)
    assert len(parts) == 2


def test_reading_an_alternative_gives_its_level_and_thresholds():
    text = (
        "A change to subheading 8507.10 from any other subheading, provided that there is a regional "
        "value content of not less than: (a) 35 percent under the build-up method, or "
        "(b) 45 percent under the build-down method."
    )
    read = rulebook.read_alternative(text)
    assert read["kinds"] == ["CTSH"]
    assert read["rvc_down"] == 45.0
    assert read["rvc_up"] == 35.0


def test_reading_a_group_exclusion():
    text = (
        "A change to subheading 8504.32 through 8504.50 from any subheading outside subheading "
        "8504.10 through 8504.50."
    )
    read = rulebook.read_alternative(text)
    assert read["kinds"] == ["CTSH"]
    assert read["group"] == ("8504.10", "8504.50")


def test_a_rcep_rule_in_short_form_is_read():
    read = rulebook.read_alternative("CTSH or RVC40")
    assert "CTSH" in read["kinds"]
    assert read["rvc_down"] == 40.0


# ---------------------------------------------------------------- origin

def test_converter_fails_the_korus_rule_at_the_excluded_group(conn):
    report = origin.evaluate(conn, shipment("shipment-8504-converter.json"), "KORUS")
    assert report["verdict"] == origin.NOT_ORIGINATING
    assert "8504.10" in report["reason"]


def test_same_converter_is_originating_under_rcep_while_korus_refuses_it(conn):
    report = origin.evaluate(conn, shipment("shipment-8504-converter.json"), "RCEP")
    assert report["verdict"] == origin.ORIGINATING
    # China and Japan are parties to RCEP, so nothing in this bill of materials
    # is non originating there, and the value content is the whole shipment.
    assert report["rvc_build_down"] == 100.0
    assert report["non_party_value"] == 0.0


def test_motor_passes_the_heading_change(conn):
    report = origin.evaluate(conn, shipment("shipment-8501-motor.json"), "KORUS")
    assert report["verdict"] == origin.ORIGINATING


def test_battery_parts_fail_because_a_part_is_in_the_same_heading(conn):
    report = origin.evaluate(conn, shipment("shipment-8507-parts.json"), "KORUS")
    assert report["verdict"] == origin.NOT_ORIGINATING
    assert "same heading 8507" in report["reason"]


def test_polymer_cannot_be_decided_without_the_weight_share(conn):
    report = origin.evaluate(conn, shipment("shipment-3901-polymer.json"), "KORUS")
    assert report["verdict"] == origin.UNDECIDABLE
    assert any("polymer" in item for item in report["missing"])


def test_polymer_is_decided_when_the_weight_share_is_supplied(conn):
    payload = shipment("shipment-3901-polymer.json")
    payload["attributes"] = {"originating_polymer_weight_percent": 62}
    report = origin.evaluate(conn, payload, "KORUS")
    assert report["verdict"] == origin.ORIGINATING


def test_polymer_fails_when_the_weight_share_is_too_low(conn):
    payload = shipment("shipment-3901-polymer.json")
    payload["attributes"] = {"originating_polymer_weight_percent": 41}
    report = origin.evaluate(conn, payload, "KORUS")
    assert report["verdict"] in (origin.NOT_ORIGINATING, origin.UNDECIDABLE)


def test_bracket_passes_both_sets_of_rules(conn):
    payload = shipment("shipment-3926-bracket.json")
    assert origin.evaluate(conn, payload, "KORUS")["verdict"] == origin.ORIGINATING
    assert origin.evaluate(conn, payload, "RCEP")["verdict"] == origin.ORIGINATING


def test_an_agreement_without_rules_is_undecidable_and_says_so(conn):
    report = origin.evaluate(conn, shipment("shipment-8501-motor.json"), "EUKOR")
    assert report["verdict"] == origin.UNDECIDABLE
    assert "no origin rule" in report["reason"]


def test_a_material_from_the_other_party_counts_as_originating(conn):
    payload = shipment("shipment-8501-motor.json")
    payload["materials"] = [{"id": "M1", "hts8": "85051100", "origin": "US", "value": 200000}]
    report = origin.evaluate(conn, payload, "KORUS")
    assert report["verdict"] == origin.ORIGINATING


def test_one_material_that_does_not_change_heading_breaks_the_whole_good(conn):
    payload = shipment("shipment-8501-motor.json")
    payload["materials"].append({"id": "M9", "hts8": "85011060", "origin": "CN", "value": 5000})
    report = origin.evaluate(conn, payload, "KORUS")
    assert report["verdict"] == origin.NOT_ORIGINATING


# ---------------------------------------------------------------- duty and claim

def test_applied_mfn_is_used_when_the_line_has_a_single_tariff_line(conn):
    result = duty.mfn_rate(conn, "US", "85076000", "850760")
    assert result["basis"] == "applied_mfn"
    assert result["percent"] == pytest.approx(3.4, abs=0.01)


def test_a_six_digit_average_is_not_used_as_a_rate(conn):
    result = duty.mfn_rate(conn, "US", "39269098", "392690")
    assert result["basis"] == "agreement_base_rate"
    assert result["percent"] == pytest.approx(5.3)


def test_motor_claim_saves_the_base_rate_on_the_declared_value(conn):
    report = assess.assess(conn, shipment("shipment-8501-motor.json"))
    assert report["claim"]["decision"] == "CLAIM KORUS"
    assert report["claim"]["saving"] == pytest.approx(10000.0)


def test_converter_has_no_claim_and_the_gap_is_priced(conn):
    report = assess.assess(conn, shipment("shipment-8504-converter.json"))
    assert report["claim"]["decision"] == "NO CLAIM"
    assert report["claim"]["exposure"] == pytest.approx(7200.0)


def test_an_agreement_for_another_market_cannot_be_claimed(conn):
    report = assess.assess(conn, shipment("shipment-8504-converter.json"))
    rcep = [item for item in report["agreements"] if item["agreement"] == "RCEP"][0]
    assert rcep["market_matches"] is False
    assert rcep["claim"]["allowed"] is False


def test_the_report_carries_the_claim_window(conn):
    report = assess.assess(conn, shipment("shipment-8501-motor.json"))
    assert report["deadline"]["deadline"] == "2027-12-08"


def test_an_old_assessment_date_makes_the_snapshot_stale(conn):
    report = assess.assess(conn, shipment("shipment-8501-motor.json"), date(2027, 6, 1))
    assert report["snapshot"]["fresh"] is False


def test_the_shipment_graph_is_in_memory_only():
    order = bom.build(shipment("shipment-8504-converter.json"))
    try:
        assert bom.good(order)["code"] == "85044095"
        assert len(bom.materials(order)) == 4
        assert bom.hierarchy_of(order, "85043140") == ["85043140", "850431", "8504", "85"]
    finally:
        order.close()


# ---------------------------------------------------------------- store and leak

def test_the_store_carries_the_three_chapters_and_both_agreements(conn):
    counts = store.label_counts(conn)
    assert counts["Chapter"] == 3
    assert counts["OriginRule"] >= 300
    assert counts["RateLine"] >= 800


def test_every_origin_rule_cites_a_source(conn):
    orphan = store.one(
        conn,
        "MATCH (r:OriginRule) WHERE NOT (r)-[:CITED_FROM]->(:Source) RETURN count(r) AS n",
    )
    assert orphan["n"] == 0


def test_every_rate_line_cites_a_source(conn):
    orphan = store.one(
        conn,
        "MATCH (r:RateLine) WHERE NOT (r)-[:CITED_FROM]->(:Source) RETURN count(r) AS n",
    )
    assert orphan["n"] == 0


def test_zero_leak_proof_passes_on_the_committed_rulebook(store_path):
    result = leak.verify(store_path, shipment("shipment-8504-converter.json"))
    assert result["pass"] is True
    assert result["hash_unchanged"] is True
    assert result["no_shipment_rows"] is True


def test_the_leak_proof_would_notice_a_written_shipment(store_path):
    unwritable = store.connect(store_path)
    unwritable.execute("CREATE (:Shipment {id: 'probe'})")
    unwritable.commit()
    unwritable.close()
    try:
        result = leak.verify(store_path, shipment("shipment-8501-motor.json"))
        assert result["pass"] is False
        assert result["no_shipment_rows"] is False
    finally:
        cleanup = store.connect(store_path)
        cleanup.execute("MATCH (s:Shipment) DETACH DELETE s")
        cleanup.commit()
        cleanup.close()


def test_the_snapshot_records_its_own_date_and_version(conn):
    row = store.one(conn, "MATCH (s:Snapshot) RETURN toString(s.as_of) AS as_of, s.rule_version AS v")
    assert row["as_of"] == "2026-11-22"
    assert row["v"] == "1.0"
