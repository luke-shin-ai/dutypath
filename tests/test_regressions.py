"""Regression tests for the defects a review reproduced by hand.

Each test here is a case where the engine used to give a confident answer it
could not support: a material with no code that passed a classification test, an
empty bill of materials that met every rule, a value that was missing and
counted as zero, a heading written where the rule asks for a subheading, another
agreement's approval read as this one's, an alternative the parser could not
read and passed anyway, a group exclusion read as a plain change, and a reader
that executed a write.

None of them is hypothetical: each input is one that was run against commit
b75322a and gave the wrong answer there, and the assertion is the answer the
engine now gives instead of the false positive.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dutypath import (  # noqa: E402
    assess, build, codes, deadline, duty, freshness, markets, origin, store, validate,
)
from dutypath import rules as rulebook  # noqa: E402
from dutypath import mcp as server  # noqa: E402

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


def case(materials, good="85044095", value=480000.0) -> dict:
    return {
        "shipment_id": "REG-1",
        "market": "US",
        "export_date": "2026-12-01",
        "import_date": "2026-12-08",
        "goods": {"hts8": good, "declared_value": value, "currency": "USD"},
        "materials": materials,
    }


# ------------------------------------------------------- D1, D2, D3, D4: input


def test_a_material_with_no_classification_does_not_pass_the_rule(conn):
    payload = shipment("shipment-8504-converter.json")
    del payload["materials"][0]["hts8"]
    report = origin.evaluate(conn, payload, "EUKOR", good_code="85044090")
    assert report["verdict"] == origin.UNDECIDABLE
    assert any("classification of material M1" in item for item in report["missing"])

    report = origin.evaluate(conn, payload, "KORUS", good_code="85044095")
    assert report["verdict"] == origin.UNDECIDABLE


def test_an_empty_bill_of_materials_meets_nothing(conn):
    payload = shipment("shipment-8504-converter.json")
    payload["materials"] = []
    report = origin.evaluate(conn, payload, "EUKOR", good_code="85044090")
    assert report["verdict"] == origin.UNDECIDABLE
    assert any("bill of materials" in item for item in report["missing"])


def test_a_missing_material_value_is_named_and_not_read_as_zero(conn):
    payload = shipment("shipment-8504-converter.json")
    payload["materials"][0].pop("value")
    report = origin.evaluate(conn, payload, "EUKOR", good_code="85044090")
    assert report["verdict"] == origin.UNDECIDABLE
    assert report["rvc_build_down"] is None
    assert any("declared value for material M1" in item for item in report["missing"])


def test_a_heading_written_where_the_rule_asks_for_a_subheading_is_undecidable(conn):
    payload = shipment("shipment-8504-converter.json")
    payload["materials"][0]["hts8"] = "8504"
    report = origin.evaluate(conn, payload, "KORUS", good_code="85044095")
    assert report["verdict"] == origin.UNDECIDABLE
    assert any("finer classification" in item for item in report["missing"])


def test_a_heading_outside_the_group_still_passes_the_group_test(conn):
    # 8505 is not in 8504.10 through 8504.50, so a heading is enough to say so.
    payload = case([{"id": "M1", "hts8": "8505", "origin": "CN", "value": 100000}])
    report = origin.evaluate(conn, payload, "KORUS", good_code="85044095")
    assert report["verdict"] == origin.ORIGINATING


def test_a_value_written_with_separators_is_read_as_the_number(conn):
    payload = shipment("shipment-8504-converter.json")
    payload["goods"]["declared_value"] = "480,000"
    payload["materials"][0]["value"] = "150,000"
    report = origin.evaluate(conn, payload, "EUKOR", good_code="85044090")
    assert report["verdict"] == origin.ORIGINATING
    assert report["rvc_build_down"] == pytest.approx(63.75)


def test_a_weight_written_with_a_percent_sign_is_read_as_the_number(conn):
    payload = shipment("shipment-3901-polymer.json")
    payload["attributes"] = {"originating_polymer_weight_percent": "62%"}
    report = origin.evaluate(conn, payload, "KORUS", good_code="39011050")
    assert report["verdict"] == origin.ORIGINATING


def test_a_negative_declared_value_is_an_input_error_not_a_negative_duty(conn):
    payload = shipment("shipment-8504-converter.json")
    payload["goods"]["declared_value"] = -10000
    with pytest.raises(validate.InputError) as error:
        markets.compare(conn, payload)
    assert "declared_value" in str(error.value)


def test_a_zero_declared_value_is_an_input_error(conn):
    payload = shipment("shipment-8504-converter.json")
    payload["goods"]["declared_value"] = 0
    with pytest.raises(validate.InputError):
        markets.compare(conn, payload)


def test_a_weight_share_above_a_hundred_is_an_input_error(conn):
    payload = shipment("shipment-3901-polymer.json")
    payload["attributes"] = {"originating_polymer_weight_percent": "162%"}
    with pytest.raises(validate.InputError):
        assess.assess(conn, payload)


# ------------------------------------------------------------- D9, D10: money


def test_another_agreements_approval_does_not_win_the_eu_claim(conn):
    payload = shipment("shipment-8504-converter.json")
    payload.pop("approved_exporter", None)
    payload["approved_exporters"] = [
        {"agreement": "RCEP", "valid_from": "2022-03-01", "valid_to": "2027-01-01"}
    ]
    report = markets.compare(conn, payload)
    eu = [block for block in report["markets"] if block["market"] == "EU"][0]
    assert eu["documents"]["status"] == "OTHER_AGREEMENT"
    assert eu["claim"]["allowed"] is False
    assert "another agreement" in eu["claim"]["blocked_by"]
    assert report["best_claim"]["market"] != "EU"


def test_an_expired_approval_where_none_is_required_does_not_block_the_claim(conn):
    payload = shipment("shipment-8501-motor.json")
    payload["approved_exporters"] = [
        {"agreement": "KORUS", "valid_from": "2020-01-01", "valid_to": "2024-01-01"}
    ]
    report = markets.compare(conn, payload)
    united_states = [block for block in report["markets"] if block["market"] == "US"][0]
    assert united_states["documents"]["status"] == "EXPIRED"
    assert united_states["documents"]["required"] is False
    assert united_states["claim"]["allowed"] is True
    assert united_states["duty"]["amount"] == 0.0
    assert report["best_claim"]["saving"] == pytest.approx(10000.0)


def test_the_document_gate_reads_the_requirement_from_the_agreement():
    required = deadline.approved_exporter({}, "RCEP", True, date(2026, 12, 1))
    not_required = deadline.approved_exporter({}, "KORUS", False, date(2026, 12, 1))
    assert deadline.blocks_claim(required)[0] is True
    assert deadline.blocks_claim(not_required)[0] is False
    assert deadline.blocks_claim(
        deadline.approved_exporter({"approved_exporter": {"agreement": "RCEP"}}, "EUKOR", True,
                                   date(2026, 12, 1))
    )[0] is True


# --------------------------------------------- D17, D19, D20: rule reading


def test_an_alternative_the_parser_could_not_read_does_not_hold(conn):
    # OR-0039 offers a heading change or a sentence about chassis and cabinets
    # that this parser cannot test.  The second one used to pass by default.
    payload = case([{"id": "M1", "hts8": "84159000", "origin": "CN", "value": 50000}],
                   good="84159000")
    report = origin.evaluate(conn, payload, "KORUS", good_code="84159000")
    assert report["verdict"] == origin.UNDECIDABLE
    assert any("testable reading" in item for item in report["missing"])


def test_recorded_media_from_unrecorded_media_is_undecidable(conn):
    # OR-0174's second alternative turns on whether the media is recorded, which
    # a bill of materials does not say.
    payload = case([{"id": "M1", "hts8": "85235100", "origin": "CN", "value": 50000}],
                   good="85235100")
    report = origin.evaluate(conn, payload, "KORUS", good_code="85235100")
    assert report["verdict"] == origin.UNDECIDABLE


def test_a_wholly_obtained_rule_is_undecidable_and_says_so(conn):
    payload = case([{"id": "M1", "hts8": "85491100", "origin": "CN", "value": 50000}],
                   good="85491100")
    report = origin.evaluate(conn, payload, "RCEP", good_code="85491100")
    assert report["verdict"] == origin.UNDECIDABLE
    assert "WO" in report["reason"] or any("WO" in item for item in report["missing"])


def test_outside_that_group_excludes_a_material_from_inside_the_group(conn):
    payload = case([{"id": "M1", "hts8": "84186990", "origin": "CN", "value": 50000}],
                   good="84181010")
    report = origin.evaluate(conn, payload, "KORUS", good_code="84181010")
    assert report["verdict"] == origin.NOT_ORIGINATING
    assert "the group the rule excludes" in report["reason"]


def test_outside_that_group_lets_a_material_from_outside_it_through(conn):
    payload = case([{"id": "M1", "hts8": "84189000", "origin": "CN", "value": 50000}],
                   good="84181010")
    report = origin.evaluate(conn, payload, "KORUS", good_code="84181010")
    assert report["verdict"] == origin.ORIGINATING


def test_the_group_named_by_that_group_is_the_rules_own_interval(conn):
    rule = rulebook.resolve(conn, "KORUS", "84181010")
    alternative = rulebook.alternatives(rule)[0]
    assert alternative["group"] == ("841810", "841869")


def test_an_except_clause_is_not_read_as_a_permitted_source(conn):
    # 8482.10 is barred by the first alternative of OR-0119; it must not also
    # appear in that alternative's list of permitted sources.
    rule = rulebook.resolve(conn, "KORUS", "84834000")
    first = rulebook.alternatives(rule)[0]
    assert "848210" in first["excluded"]
    assert "848210" not in first["allowed_from"]


def test_an_except_range_bars_every_subheading_inside_it(conn):
    rule = rulebook.resolve(conn, "KORUS", "84181010")
    first = rulebook.alternatives(rule)[0]
    assert ("841891", "841891") in first["excluded_ranges"] or "841891" in first["excluded"]
    # 8443.91 through 8443.99 is a range, so 8443.95 is barred too.
    printing = rulebook.resolve(conn, "KORUS", "84433110")
    ranges = [pair for pair in rulebook.alternatives(printing) if pair["excluded_ranges"]]
    assert ranges, "the exception range was not read as an interval"


def test_the_verdict_reason_names_the_test_that_ran(conn):
    # The EU rule for 8504 is a value ceiling with no heading test; the reason
    # used to claim a classification test that never happened.
    report = origin.evaluate(conn, shipment("shipment-8504-converter.json"), "EUKOR",
                             good_code="85044090")
    assert report["verdict"] == origin.ORIGINATING
    assert "value content" in report["reason"]
    assert "changes tariff classification" not in report["reason"]


# ------------------------------------------------------ D5, D6: hub and reader


def test_the_hub_query_completes_and_returns_one_row_per_thing(conn):
    statement = (ROOT / "neo4j" / "pull_rules.cypher").read_text(encoding="utf-8")
    body = "\n".join(line for line in statement.splitlines() if not line.strip().startswith("//"))
    rows = store.rows(conn, body, {"market": "US"})
    parts = {}
    for row in rows:
        parts[row["part"]] = parts.get(row["part"], 0) + 1
    assert parts["rule"] == 222
    assert parts["rate"] == 847
    assert rows[0]["node"] is not None
    # 222 rules plus 847 rates is 1,069 rows, not their product.
    assert len(rows) < 1200


def test_read_cypher_refuses_a_write_before_it_reaches_the_store(store_path):
    tool = server.Server(store_path)
    try:
        with pytest.raises(ValueError) as error:
            tool.read_cypher({"statement": "CREATE (:Material {id: 'LEAK-1', value: 999})"})
        assert "CREATE" in str(error.value)
        assert store.one(tool.conn, "MATCH (m:Material) RETURN count(m) AS n")["n"] == 0
        with pytest.raises(ValueError):
            tool.read_cypher({"statement": "MATCH (n) DETACH DELETE n"})
        with pytest.raises(ValueError):
            tool.read_cypher({"statement": "MATCH (r:OriginRule) SET r.text = ''"})
        with pytest.raises(ValueError):
            tool.read_cypher({"statement": "MATCH (n) RETURN n; CREATE (:M)"})
    finally:
        tool.close()


def test_a_url_in_a_literal_does_not_hide_the_write_after_it():
    # The review of de51478 sent this statement: removing comments before
    # literals read the "//" in 'http://x' as a comment, dropped the rest of
    # the line, and returned None, so the reader accepted a write.
    cases = {
        "MATCH (n) WHERE n.id = 'http://x' CREATE (m:Probe) RETURN m": "CREATE",
        "MATCH (n) WHERE n.id = 'https://a' DETACH DELETE n": "DETACH",
        "MATCH (n) WHERE n.id = 'http://x' SET n.leak = 1 RETURN n": "SET",
        "MATCH (n) WHERE n.id = 'http://x' MERGE (m:Probe) RETURN m": "MERGE",
    }
    for statement, clause in cases.items():
        assert store.write_keyword(statement) == clause, statement


def test_a_read_with_a_url_or_a_comment_is_still_a_read():
    reads = [
        "MATCH (n) WHERE n.url = 'http://x' RETURN n",
        "MATCH (r:OriginRule) RETURN r // the rule text follows",
        "MATCH (r:OriginRule) RETURN r // it's a note",
        "MATCH (r:OriginRule) /* a block, with an apostrophe: don't */ RETURN r",
        "RETURN 'CREATE' AS word",
    ]
    for statement in reads:
        assert store.write_keyword(statement) is None, statement


def test_a_comment_does_not_hide_the_write_on_the_next_line():
    statement = "MATCH (n) // don't\nCREATE (m:Probe) RETURN m"
    assert store.write_keyword(statement) == "CREATE"


def test_read_cypher_refuses_a_write_hidden_behind_a_url_literal(store_path):
    tool = server.Server(store_path)
    try:
        with pytest.raises(ValueError) as error:
            tool.read_cypher(
                {"statement": "MATCH (n) WHERE n.id = 'http://x' CREATE (m:Probe) RETURN m"}
            )
        assert "CREATE" in str(error.value)
        assert store.one(tool.conn, "MATCH (m:Probe) RETURN count(m) AS n")["n"] == 0
        with pytest.raises(ValueError):
            tool.read_cypher({"statement": "MATCH (n) WHERE n.id = 'https://a' DETACH DELETE n"})
    finally:
        tool.close()


def test_read_cypher_still_reads_and_a_literal_is_not_a_clause(store_path):
    tool = server.Server(store_path)
    try:
        rows = tool.read_cypher(
            {"statement": "MATCH (r:OriginRule) WHERE r.text CONTAINS 'created' RETURN count(r) AS n"}
        )
        assert rows["count"] == 1
    finally:
        tool.close()


# -------------------------------------------- D: a backtick identifier is not
# a string literal, and the guard has to know the difference


def test_a_backtick_identifier_does_not_hide_the_write_after_it():
    # The review of 400338a sent these statements: the scanner read the
    # apostrophe inside the backtick identifier as an opening string literal,
    # swallowed the code up to the next apostrophe, and returned a read.
    attacks = {
        "MATCH (n) RETURN 1 AS `a'` CREATE (:X) RETURN 2 AS `'`": "CREATE",
        "RETURN `a'//` CREATE (:X) RETURN `'`": "CREATE",
        "MATCH (n) RETURN `a'` CREATE (:X)": "CREATE",
        "MATCH (n) RETURN `a'` MERGE (x:X) RETURN `'`": "MERGE",
        "MATCH (n) SET n.x = 1 RETURN 1 AS `a'` DETACH DELETE n": "SET",
        "MATCH (n) RETURN 1 AS `a` CREATE (:X)": "CREATE",
        "MATCH (n) RETURN 1 AS `a``b` CREATE (:X)": "CREATE",
        "MATCH (n) RETURN 1 AS `a'` CREATE (:X) RETURN `b'c` // and a comment": "CREATE",
        "MATCH (n) RETURN 1 AS `a'`\nCREATE (:X)": "CREATE",
    }
    for statement, clause in attacks.items():
        assert store.write_keyword(statement) == clause, statement


def test_a_read_with_a_backtick_identifier_is_still_a_read():
    reads = [
        "MATCH (n) RETURN 1 AS `a'b`",
        "MATCH (n) RETURN 1 AS `CREATE`",
        "MATCH (n) RETURN 1 AS `a``b`",
        "MATCH (r:OriginRule) RETURN r.id AS `rule'id`",
        "RETURN 'it''s' AS x",
        "MATCH (n) WHERE n.id = 'a' RETURN count(n) AS n",
    ]
    for statement in reads:
        assert store.write_keyword(statement) is None, statement


def test_read_cypher_refuses_the_backtick_bypass_and_keeps_answering(store_path):
    tool = server.Server(store_path)
    try:
        for statement in (
            "MATCH (n) RETURN 1 AS `a'` CREATE (:Probe) RETURN 2 AS `'`",
            "RETURN `a'//` CREATE (:Probe) RETURN `'`",
        ):
            with pytest.raises(ValueError) as error:
                tool.read_cypher({"statement": statement})
            assert "CREATE" in str(error.value)
        # The refusal happens before the store sees the statement, so the
        # session is still usable: a statement that reached the engine and was
        # then refused at commit would have left this connection rolled back.
        assert store.one(tool.conn, "MATCH (m:Probe) RETURN count(m) AS n")["n"] == 0
        assert store.one(tool.conn, "MATCH (n) RETURN count(n) AS n")["n"] == 5454
    finally:
        tool.close()


def test_an_unclosed_literal_or_identifier_is_left_to_the_engine(store_path):
    # The scanner cannot tell where an unclosed literal ends, so it keeps the
    # rest as literal rather than inventing code.  The engine refuses the
    # statement, which is the answer that matters: no write is executed.
    unclosed = [
        "RETURN 'unclosed CREATE (:Probe)",
        "RETURN `unclosed CREATE (:Probe)",
        "RETURN 1 /* unterminated CREATE (:Probe)",
    ]
    for statement in unclosed:
        assert store.write_keyword(statement) is None, statement
        # One session per statement: a refused statement leaves the open
        # transaction rolled back in this engine, so the next one starts fresh.
        probe = store.connect(store_path, read_only=True)
        probe.autocommit = True
        try:
            with pytest.raises(Exception):
                store.rows(probe, statement)
            assert store.one(probe, "MATCH (m:Probe) RETURN count(m) AS n")["n"] == 0
        finally:
            probe.close()


def test_the_read_only_connection_refuses_the_write_itself(store_path):
    # The guard is the first line, not the only one.  With autocommit on, the
    # engine refuses the write at execution and names the reason; with it off it
    # accepts the statement, lets the session read its own write, and refuses it
    # at commit.  Either way the file is unchanged.
    before = store.file_sha256(store_path)
    write = "CREATE (:Probe {id: 'RO'})"
    guarded = store.connect(store_path, read_only=True)
    guarded.autocommit = True
    try:
        with pytest.raises(Exception) as error:
            store.rows(guarded, write)
        assert "read-only" in str(error.value).lower() or "read only" in str(error.value).lower()
        assert store.one(guarded, "MATCH (m:Probe) RETURN count(m) AS n")["n"] == 0
    finally:
        guarded.close()

    session = store.connect(store_path, read_only=True)
    session.autocommit = False
    try:
        store.rows(session, write)
        assert store.one(session, "MATCH (m:Probe) RETURN count(m) AS n")["n"] == 1
    finally:
        session.close()

    assert store.file_sha256(store_path) == before
    check = store.connect(store_path, read_only=True)
    check.autocommit = False
    try:
        assert store.one(check, "MATCH (m:Probe) RETURN count(m) AS n")["n"] == 0
    finally:
        check.close()


def test_a_keyword_that_is_not_a_keyword_is_refused_by_the_engine(store_path):
    # These are outside what a guard can decide: a Cyrillic letter in neither
    # case matches the clause list, a fullwidth word is a different word, and a
    # procedure call carries a string the guard does not read into.  Each one is
    # checked against the engine, so the README can say what happens rather than
    # what should happen.
    outside = [
        "\u041cATCH (n) RETURN 1 AS x",
        "\uff23\uff32\uff25\uff21\uff34\uff25 (:Probe)",
        "CALL apoc.do.when(true, 'CREATE (:Probe)', '', {}) YIELD value RETURN value",
    ]
    guarded = store.connect(store_path, read_only=True)
    guarded.autocommit = True
    try:
        for statement in outside:
            with pytest.raises(Exception):
                store.rows(guarded, statement)
        assert store.one(guarded, "MATCH (m:Probe) RETURN count(m) AS n")["n"] == 0
    finally:
        guarded.close()

    # The guard still names the procedure call, which is the clause it can see.
    assert store.write_keyword(
        "CALL apoc.do.when(true, 'CREATE (:Probe)', '', {}) YIELD value RETURN value"
    ) == "CALL"


# ------------------------------------------------------------- D13, D15: dates


def test_a_verdict_is_computed_on_the_code_of_the_agreements_own_market(conn):
    payload = shipment("shipment-8504-converter.json")
    payload["goods"].pop("market_codes", None)
    payload["market"] = "US"
    report = assess.assess(conn, payload)
    rcep = [item for item in report["agreements"] if item["agreement"] == "RCEP"][0]
    assert rcep["origin"]["verdict"] == origin.UNDECIDABLE
    assert any("code for Japan" in item for item in rcep["origin"]["missing"])


def test_the_snapshot_age_limit_comes_from_the_store():
    fresh = freshness.judge({"id": "x", "as_of": "2026-11-22", "max_age_days": 30}, date(2027, 1, 5))
    assert fresh["fresh"] is False
    assert fresh["max_age_days"] == 30


def test_a_date_before_the_snapshot_is_not_called_fresh():
    result = freshness.judge({"id": "x", "as_of": "2026-11-22", "max_age_days": 120}, date(2026, 11, 1))
    assert result["fresh"] is False
    assert result["status"] == "BEFORE_SNAPSHOT"
    assert result["age_days"] == 0


# ------------------------------------------------------------- D8, D12: the gap


def test_the_snapshot_names_the_alternatives_it_could_not_read(conn):
    from dutypath import cli

    unreadable = cli._unreadable_alternatives(conn)
    assert unreadable["alternatives"] >= 1
    ids = {item["rule"] for item in unreadable["named"]}
    assert {"OR-0039", "OR-0174", "OR-0329"} <= ids


def test_korus_leaves_thirty_six_subheadings_without_a_rule(conn):
    rows = store.rows(conn, "MATCH (s:Subheading) RETURN s.code AS code ORDER BY code")
    missing = []
    for row in rows:
        if rulebook.resolve(conn, "KORUS", row["code"]) is None:
            missing.append(row["code"])
    assert len(missing) == 36
    assert "844210" in missing


# ------------------------------------- D23: a schedule row for another partner
#
# Japan's schedule prints more than one row for some lines: a treatment for
# Korea, a treatment for other parties, and on most lines a general row.  The
# build used to name every row by the line alone, keep the first, and drop the
# rest, so 390120010 answered with the free ASEAN row (0.0 percent) instead of
# the compound duty Korea actually pays.  These three tests hold that open.


def test_a_row_written_for_another_party_is_not_the_korean_rate(conn):
    rows = store.rows(
        conn,
        "MATCH (r:RateLine {agreement: 'RCEP', code: '390120010'}) "
        "RETURN r.partner AS partner ORDER BY partner",
    )
    partners = [row["partner"] for row in rows]
    assert "KR" in partners
    assert "OTHER-AS+AU+NZ" in partners
    assert "OTHER-CN" in partners
    result = duty.line_rate(conn, "JP", "RCEP", "390120010", date(2026, 12, 1))
    assert result["partner"] == "KR"
    assert result["percent"] is None
    assert "does not compute" in result["reason"]


def test_every_japan_row_in_the_extract_reaches_the_store(store_path):
    japan = json.loads((DATA / "rcep_japan_rates.json").read_text(encoding="utf-8"))
    treatments = {(row["code"], row["partner"]) for row in japan}
    assert len(treatments) == len(japan), "two rows claim the same line and treatment"
    connection = store.connect(store_path)
    connection.autocommit = False
    try:
        counted = store.one(
            connection,
            "MATCH (r:RateLine {agreement: 'RCEP'}) RETURN count(r) AS n",
        )
    finally:
        connection.close()
    assert counted["n"] == len(japan)


def test_the_remarks_cell_names_the_parties_a_japan_row_is_written_for():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "extract_rcep_japan", ROOT / "scripts" / "extract_rcep_japan.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._partner("") == "ALL"
    assert module._partner("Treatment for Korea") == "KR"
    assert module._partner("Treatment for China and Korea") == "KR"
    assert module._partner("Treatment for China") == "OTHER-CN"
    assert module._partner("Treatment for ASEAN, Australia, and New Zealand") == "OTHER-AS+AU+NZ"


def test_the_build_refuses_two_rows_for_one_partner_treatment(tmp_path):
    import shutil

    data = tmp_path / "data"
    shutil.copytree(DATA, data)
    path = data / "rcep_japan_rates.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    duplicate = dict(rows[0])
    duplicate["base_rate_text"] = "something else"
    rows.append(duplicate)
    path.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    connection = store.connect(str(tmp_path / "dup.rl"))
    connection.autocommit = False
    try:
        with pytest.raises(ValueError) as error:
            build.build(connection, str(data))
        assert "partner treatment" in str(error.value)
    finally:
        connection.close()


# ------------------------------------- D24: the interval join is in the graph


def test_the_interval_join_finds_the_material_the_rule_excludes(conn):
    rule = rulebook.resolve(conn, "KORUS", "84181010")
    hits = rulebook.material_intervals(
        conn, rule["id"], 1,
        [("M1", "84186990"), ("M2", "84189000"), ("M3", "8418")],
    )
    # Inside the group the rule excludes.
    assert [hit["relation"] for hit in hits["M1"] if hit["kind"] == "group"] == ["inside"]
    # Outside it, so the join says nothing about this material.
    assert "M2" not in hits
    # Written at heading level, so it sits across the interval.
    assert [hit["relation"] for hit in hits["M3"] if hit["kind"] == "group"] == ["across"]


def test_the_interval_join_agrees_with_the_python_comparison(conn):
    # The graph and the Python comparison read the same interval nodes, and the
    # README says one cannot drift from the other. This reads every material
    # against every interval of the rule both ways and compares the answer.
    rule = rulebook.resolve(conn, "KORUS", "84181010")
    materials = [("M1", "84186990"), ("M2", "84189000"), ("M3", "8418"), ("M4", "3926")]
    hits = rulebook.material_intervals(conn, rule["id"], 1, materials)
    intervals = store.rows(
        conn,
        "MATCH (r:OriginRule {id: $id})-[:EXCLUDES]->(i:HsInterval) "
        "WHERE i.alternative = 1 RETURN i.low AS low, i.high AS high ORDER BY i.ord",
        {"id": rule["id"]},
    )
    for key, code in materials:
        for interval in intervals:
            expected = codes.interval_relation(code, interval["low"], interval["high"])
            answer = [hit["relation"] for hit in hits.get(key, [])
                      if hit["low_code"] == interval["low"]]
            if expected == "outside":
                assert answer == [], (key, code, interval)
            else:
                assert answer == [expected], (key, code, interval)


def test_the_rule_and_the_line_come_back_from_one_traversal(conn):
    context = rulebook.market_context(conn, "KORUS", "US", "85044095")
    direct = rulebook.resolve(conn, "KORUS", "85044095")
    assert context["rule"]["id"] == direct["id"]
    assert context["line"]["code"] == "85044095"
    assert context["line"]["source"] == "SRC-KORUS-2B"
    assert context["rule_source"] == "SRC-KORUS-6A"
    # A code the snapshot has no line for still brings back its rule.
    missing = rulebook.market_context(conn, "KORUS", "US", "99999999")
    assert missing["rule"] is None and missing["line"] is None


def test_the_interval_a_rule_names_is_a_node_it_points_at(conn):
    rows = store.rows(
        conn,
        "MATCH (r:OriginRule {id: 'OR-0043'})-[:EXCLUDES]->(i:HsInterval) "
        "RETURN i.kind AS kind, i.label AS label, i.from_norm AS low, i.to_norm AS high "
        "ORDER BY i.ord",
    )
    labels = {row["label"] for row in rows}
    assert "8418.91" in labels
    assert "8418.10 to 8418.69" in labels
    group = [row for row in rows if row["kind"] == "group"][0]
    assert group["low"] == "84181000"
    assert group["high"] == "84186999"
