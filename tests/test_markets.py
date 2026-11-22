"""Tests for the three market comparison, the two new schedules and the MCP server.

The store is built once per session from data/extract-2026-11-22, the same way
the other suite does it, so a test never touches the committed snapshot.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dutypath import build, duty, markets, origin, rates, store  # noqa: E402
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


# ---------------------------------------------------------------- EU schedule


def test_eu_category_zero_is_free_on_entry_into_force():
    assert rates.eu_staged_rate(3.3, "0", date(2011, 7, 1))["percent"] == 0.0


def test_eu_schedule_has_no_answer_before_entry_into_force():
    result = rates.eu_staged_rate(3.3, "0", date(2011, 6, 30))
    assert result["percent"] is None
    assert "entered into force" in result["reason"]


def test_eu_category_three_is_removed_in_four_equal_stages():
    # 6.5 percent over four stages: 4.8, 3.2, 1.6, free on the first day of year four.
    assert rates.eu_staged_rate(6.5, "3", date(2011, 7, 1))["percent"] == 4.8
    assert rates.eu_staged_rate(6.5, "3", date(2012, 7, 1))["percent"] == 3.2
    assert rates.eu_staged_rate(6.5, "3", date(2013, 7, 1))["percent"] == 1.6
    assert rates.eu_staged_rate(6.5, "3", date(2014, 7, 1))["percent"] == 0.0


def test_eu_category_five_is_removed_in_six_equal_stages():
    assert rates.eu_staged_rate(5.7, "5", date(2011, 7, 1))["percent"] == 4.7
    assert rates.eu_staged_rate(5.7, "5", date(2015, 7, 1))["percent"] == 0.9
    assert rates.eu_staged_rate(5.7, "5", date(2016, 7, 1))["percent"] == 0.0


def test_eu_category_e_keeps_the_base_rate():
    result = rates.eu_staged_rate(6.5, "E", date(2026, 12, 1))
    assert result["percent"] == 6.5
    assert "saves nothing" in result["reason"]


def test_eu_category_not_in_the_annex_has_no_rate():
    result = rates.eu_staged_rate(6.5, "99", date(2026, 12, 1))
    assert result["percent"] is None
    assert "not defined" in result["reason"]


# ---------------------------------------------------------------- Japan schedule


def test_japan_year_one_begins_on_entry_into_force():
    cells = ["3.5", "3.2", "2.8", "2.4", "2.1"]
    assert rates.printed_rate(cells, "SCHEDULE", date(2022, 1, 1))["percent"] == 3.5
    assert rates.printed_rate(cells, "SCHEDULE", date(2026, 12, 1))["percent"] == 2.1


def test_japan_prints_u_for_an_excluded_line():
    result = rates.printed_rate(["U"] * 5, "U", date(2026, 12, 1))
    assert result["percent"] is None
    assert result["basis"] == "excluded"
    assert "MFN rate applies" in result["reason"]


def test_japan_compound_duty_is_not_computed():
    result = rates.printed_rate(
        ["21 yen/kg or 6.1 %, which-ever is the less"] * 5, "SCHEDULE", date(2023, 6, 1)
    )
    assert result["percent"] is None
    assert "does not compute" in result["reason"]


def test_japan_before_entry_into_force_has_no_rate():
    assert rates.printed_rate(["Free"], "FREE", date(2021, 12, 31))["percent"] is None


def test_japan_free_cell_is_zero():
    assert rates.printed_rate(["Free"] * 5, "FREE", date(2026, 1, 1))["percent"] == 0.0


# ---------------------------------------------------------------- rate lookup


def test_eu_line_rate_is_read_from_the_eu_schedule(conn):
    result = duty.line_rate(conn, "EU", "EUKOR", "85044090", date(2026, 12, 1))
    assert result["percent"] == 0.0
    assert result["source"] == "SRC-EUKOR-2A"
    assert result["base_rate_percent"] == 3.3


def test_japan_uses_the_korea_row_when_the_schedule_carries_one(conn):
    result = duty.line_rate(conn, "JP", "RCEP", "390110090", date(2026, 12, 1))
    assert result["partner"] == "KR"
    assert result["percent"] == 1.9


def test_japan_excluded_line_is_reported_not_priced(conn):
    result = duty.line_rate(conn, "JP", "RCEP", "390110020", date(2026, 12, 1))
    assert result["percent"] is None
    assert result["basis"] == "excluded"


def test_a_market_without_the_line_says_not_in_snapshot(conn):
    result = duty.line_rate(conn, "JP", "RCEP", "999999999", date(2026, 12, 1))
    assert result["basis"] == "not_in_snapshot"


def test_eu_mfn_baseline_is_the_schedule_base_rate(conn):
    result = duty.mfn_rate(conn, "EU", "85044090")
    assert result["basis"] == "schedule_base_rate"
    assert result["percent"] == pytest.approx(3.3)


# ---------------------------------------------------------------- EU rules


def test_eu_rule_for_a_converter_is_a_value_ceiling_and_not_a_heading_change(conn):
    rule = rulebook.resolve(conn, "EUKOR", "85044090")
    assert rule["code_from"] == "8504"
    alternatives = rulebook.alternatives(rule)
    assert len(alternatives) == 1
    assert alternatives[0]["kinds"] == []
    assert alternatives[0]["rvc_down"] == 55.0


def test_eu_rule_for_chapter_84_offers_two_alternatives(conn):
    rule = rulebook.resolve(conn, "EUKOR", "84135000")
    alternatives = rulebook.alternatives(rule)
    assert len(alternatives) == 2
    assert alternatives[0]["kinds"] == ["CTH"]
    assert alternatives[1]["rvc_down"] == 50.0


def test_eu_polymer_rule_asks_for_a_heading_change_or_a_tight_ceiling(conn):
    rule = rulebook.resolve(conn, "EUKOR", "39011090")
    alternatives = rulebook.alternatives(rule)
    assert [item["kinds"] for item in alternatives] == [["CTH"], []]
    assert alternatives[1]["rvc_down"] == 75.0


def test_eu_material_from_a_member_state_counts_as_a_party_material(conn):
    payload = shipment("shipment-8504-converter.json")
    payload["materials"] = [{"id": "M1", "hts8": "85043180", "origin": "DE", "value": 400000}]
    report = origin.evaluate(conn, payload, "EUKOR", good_code="85044090")
    assert report["verdict"] == origin.ORIGINATING
    assert report["non_party_value"] == 0.0


# ---------------------------------------------------------------- comparison


def test_the_converter_is_refused_by_korus_and_accepted_by_the_eu(conn):
    report = markets.compare(conn, shipment("shipment-8504-converter.json"))
    by_market = {block["market"]: block for block in report["markets"]}
    assert by_market["US"]["origin"]["verdict"] == origin.NOT_ORIGINATING
    assert by_market["US"]["claim"]["allowed"] is False
    assert by_market["US"]["duty"]["amount"] == pytest.approx(7200.0)
    assert by_market["EU"]["origin"]["verdict"] == origin.ORIGINATING
    assert by_market["EU"]["claim"]["allowed"] is True
    assert by_market["EU"]["duty"]["amount"] == 0.0
    assert report["best_claim"]["market"] == "EU"


def test_the_converter_loses_the_rcep_claim_to_an_expired_approval(conn):
    report = markets.compare(conn, shipment("shipment-8504-converter.json"))
    japan = [block for block in report["markets"] if block["market"] == "JP"][0]
    assert japan["origin"]["verdict"] == origin.ORIGINATING
    assert japan["documents"]["status"] == "EXPIRED"
    assert japan["claim"]["allowed"] is False
    assert "approved exporter expired" in japan["claim"]["blocked_by"]


def test_the_polymer_is_undecidable_in_the_us_and_originating_in_the_eu(conn):
    report = markets.compare(conn, shipment("shipment-3901-polymer.json"))
    by_market = {block["market"]: block for block in report["markets"]}
    assert by_market["US"]["verdict"] == "UNDECIDABLE"
    assert any("polymer" in item for item in by_market["US"]["missing"])
    assert by_market["EU"]["origin"]["verdict"] == origin.ORIGINATING
    # The weight share KORUS asks for is not something the EU rule reads at all.
    assert by_market["EU"]["potential"]["saving"] == pytest.approx(58500.0)


def test_japan_prices_the_polymer_on_the_korea_row_of_the_schedule(conn):
    report = markets.compare(conn, shipment("shipment-3901-polymer.json"))
    japan = [block for block in report["markets"] if block["market"] == "JP"][0]
    assert japan["rate"]["percent"] == pytest.approx(1.9)
    assert japan["mfn"]["percent"] == pytest.approx(2.8)
    assert japan["potential"]["saving"] == pytest.approx(8100.0)


def test_the_bracket_can_be_claimed_in_all_three_markets(conn):
    report = markets.compare(conn, shipment("shipment-3926-bracket.json"))
    # The bracket fixture carries an approval for the EU and for RCEP.
    assert [block["claim"]["allowed"] for block in report["markets"]] == [True, True, True]
    japan = [block for block in report["markets"] if block["market"] == "JP"][0]
    assert japan["duty"]["amount"] == pytest.approx(2520.0)


def test_a_market_without_a_classification_is_undecidable_and_names_the_gap(conn):
    payload = shipment("shipment-8501-motor.json")
    payload["goods"].pop("market_codes")
    report = markets.compare(conn, payload)
    eu = [block for block in report["markets"] if block["market"] == "EU"][0]
    assert eu["verdict"] == "UNDECIDABLE"
    assert "classification" in eu["claim"]["blocked_by"]
    assert any("code for European Union" in item for item in eu["missing"])


def test_the_ranking_names_the_spread_between_the_cheapest_and_dearest_route(conn):
    report = markets.compare(conn, shipment("shipment-8507-parts.json"))
    assert report["ranking"]["cheapest"] == "JP"
    assert report["ranking"]["dearest"] == "US"
    assert report["ranking"]["spread"] == pytest.approx(35000.0)


def test_the_comparison_carries_the_claim_window(conn):
    report = markets.compare(conn, shipment("shipment-8501-motor.json"))
    assert report["claim_window"]["deadline"] == "2027-12-08"
    assert report["claim_window"]["status"] == "OPEN"


def test_an_old_date_makes_the_snapshot_stale_in_the_comparison(conn):
    report = markets.compare(conn, shipment("shipment-8501-motor.json"), date(2027, 6, 1))
    assert report["snapshot"]["fresh"] is False


# ---------------------------------------------------------------- store shape


def test_every_eu_and_japan_rate_line_cites_a_source(conn):
    orphan = store.one(
        conn,
        "MATCH (r:RateLine) WHERE r.market IN ['EU','JP'] AND NOT (r)-[:CITED_FROM]->(:Source) "
        "RETURN count(r) AS n",
    )
    assert orphan["n"] == 0


def test_the_snapshot_covers_three_markets_with_rates(conn):
    rows = store.rows(
        conn,
        "MATCH (r:RateLine)-[:FOR]->(a:Agreement) RETURN a.code AS agreement, count(r) AS lines "
        "ORDER BY agreement",
    )
    counts = {row["agreement"]: row["lines"] for row in rows}
    assert counts["KORUS"] >= 800
    assert counts["EUKOR"] >= 1700
    assert counts["RCEP"] >= 1200


def test_every_japan_row_carries_its_printed_years(conn):
    broken = store.one(
        conn,
        "MATCH (r:RateLine {market: 'JP'}) WHERE size(r.years) <> 21 RETURN count(r) AS n",
    )
    assert broken["n"] == 0


def test_eu_rules_carry_their_alternatives_as_structure(conn):
    rows = store.rows(
        conn,
        "MATCH (r:OriginRule {agreement: 'EUKOR'}) RETURN r.alternatives_json AS alternatives",
    )
    assert rows and all(row["alternatives"] for row in rows)


# ---------------------------------------------------------------- MCP


def _mcp_call(store_file: str, messages: list[dict]) -> list[dict]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    payload = "".join(json.dumps(message) + "\n" for message in messages)
    process = subprocess.run(
        [sys.executable, "-m", "dutypath.mcp", "--store", store_file],
        input=payload,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    return [json.loads(line) for line in process.stdout.splitlines() if line.strip()]


def test_mcp_lists_its_tools(store_path):
    replies = _mcp_call(
        store_path,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ],
    )
    assert replies[0]["result"]["serverInfo"]["name"] == "dutypath"
    names = {tool["name"] for tool in replies[1]["result"]["tools"]}
    assert {"compare_markets", "assess_shipment", "resolve_rule", "rate_on_date",
            "snapshot_info", "verify_zero_leak", "read_cypher"} <= names


def test_an_agent_gets_the_three_market_verdict_over_mcp(store_path):
    payload = shipment("shipment-8504-converter.json")
    replies = _mcp_call(
        store_path,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "compare_markets", "arguments": {"shipment": payload, "on": "2026-12-01"}},
            },
        ],
    )
    content = replies[1]["result"]["content"][0]["text"]
    report = json.loads(content)
    assert report["best_claim"]["market"] == "EU"
    assert [block["market"] for block in report["markets"]] == ["US", "EU", "JP"]


def test_an_agent_can_ask_the_graph_a_question_over_mcp(store_path):
    replies = _mcp_call(
        store_path,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "read_cypher",
                    "arguments": {
                        "statement": "MATCH (r:RateLine {market: 'EU'}) RETURN count(r) AS n",
                        "parameters": {},
                    },
                },
            },
        ],
    )
    rows = json.loads(replies[1]["result"]["content"][0]["text"])["rows"]
    assert rows[0]["n"] >= 1700


def test_the_mcp_server_leaves_the_store_byte_identical(store_path):
    before = store.file_sha256(store_path)
    payload = shipment("shipment-3926-bracket.json")
    replies = _mcp_call(
        store_path,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "verify_zero_leak", "arguments": {"shipment": payload}},
            },
        ],
    )
    result = json.loads(replies[1]["result"]["content"][0]["text"])
    assert result["pass"] is True
    assert store.file_sha256(store_path) == before


# ---------------------------------------------------------------- relate parity


def test_relate_mcp_reads_the_same_rate_row(store_path):
    """The relate binary's own MCP surface, used as a second reader."""
    binary = os.environ.get("RELATE_BIN") or shutil_which("relate") or _local_relate()
    if not binary:
        pytest.skip("the relate command line is not on PATH")
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "read_cypher",
                "arguments": {
                    "statement": "MATCH (r:RateLine {code: '85044090', market: 'EU'}) "
                    "RETURN r.base_rate_percent AS base, r.staging AS staging",
                },
            },
        },
    ]
    payload = "".join(json.dumps(message) + "\n" for message in messages)
    process = subprocess.run(
        [binary, "serve", "--database", store_path, "--mcp", "stdio", "--read-only"],
        input=payload,
        capture_output=True,
        text=True,
        timeout=120,
    )
    replies = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
    text = replies[1]["result"]["content"][0]["text"]
    row = json.loads(text)["rows"][0]
    connection = store.connect(store_path, read_only=True)
    connection.autocommit = False
    try:
        ours = duty.line_rate(connection, "EU", "EUKOR", "85044090", date(2026, 12, 1))
    finally:
        connection.close()
    assert row["base"] == pytest.approx(ours["base_rate_percent"])
    assert row["staging"] == ours["staging"]


def _local_relate() -> str | None:
    for candidate in (Path("/workspace/.local/bin/relate"), Path.home() / ".local" / "bin" / "relate"):
        if candidate.exists():
            return str(candidate)
    return None


def shutil_which(name: str):
    from shutil import which

    return which(name)
