"""Build the public rule snapshot.

Only public material goes in: tariff codes, origin rules, duty rates, the
staging schedule, and the deadline the law gives a claim.  No shipment, no
material list, no customer name.  The input is the JSON written by
``scripts/extract_sources.py``, so a reader can check any row against the
document it came from.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date

from . import codes, store
from . import rules as rulebook

SNAPSHOT_ID = "dutypath-rules-2026-11-22"
AS_OF = "2026-11-22"
RULE_VERSION = "2.0"
MAX_AGE_DAYS = 120


def snapshot_identity(data_dir: str) -> tuple[str, str]:
    """The snapshot id and date, taken from the data set it is built from.

    ``meta.json`` is written by the extraction, so a rebuild from a new extract
    carries that extract's date instead of the date this file was first written.
    The constants above are the fallback for a directory without a meta file.
    """
    path = os.path.join(data_dir, "meta.json")
    if not os.path.exists(path):
        return SNAPSHOT_ID, AS_OF
    with open(path, encoding="utf-8") as handle:
        meta = json.load(handle)
    as_of = str(meta.get("extracted_on") or AS_OF)[:10]
    day = as_of.replace("-", "")
    return "dutypath-rules-%s-%s-%s" % (day[:4], day[4:6], day[6:8]), as_of

CHAPTER_TITLES = {
    "39": "Plastics and articles thereof",
    "84": "Nuclear reactors, boilers, machinery and mechanical appliances; parts thereof",
    "85": "Electrical machinery and equipment and parts thereof; sound recorders and reproducers",
}

SOURCES = [
    {
        "id": "SRC-KORUS-6A",
        "title": "KORUS FTA Annex 6-A, Specific Rules of Origin",
        "url": "https://ustr.gov/sites/default/files/Annex_6-A_SPECIFIC_RULES_OF_ORIGIN.pdf",
        "as_of": "2012-03-15",
    },
    {
        "id": "SRC-KORUS-2B",
        "title": "KORUS FTA Annex 2-B, Tariff Schedule of the United States",
        "url": "https://ustr.gov/sites/default/files/uploads/agreements/fta/korus/Annex_2-B-1_US_Tariff_Schedule.pdf",
        "as_of": "2012-03-15",
    },
    {
        "id": "SRC-KORUS-CH2",
        "title": "KORUS FTA Chapter 2, Annex 2-B Tariff Elimination (staging categories)",
        "url": "https://ustr.gov/sites/default/files/uploads/agreements/fta/korus/asset_upload_file904_12701.pdf",
        "as_of": "2012-03-15",
    },
    {
        "id": "SRC-RCEP-3A",
        "title": "RCEP Annex 3A, Product-Specific Rules (HS 2022)",
        "url": "https://www.abf.gov.au/free-trade-agreements/files/rcep-chapter-3-annex-3a-HS2022.pdf",
        "as_of": "2023-01-01",
    },
    {
        "id": "SRC-MOEF-2025-02",
        "title": "FTA 활용지원을 위한 관세행정 추진전략, 기획재정부, 2025-02-12",
        "url": "https://mofe.go.kr/com/cmm/fms/FileDown.do?atchFileId=ATCH_000000000028297&fileSn=6",
        "as_of": "2025-02-12",
    },
    {
        "id": "SRC-EUKOR-2A",
        "title": "Korea-EU FTA Annex 2-A, tariff schedule of the EU Party (Korean language copy of OJ L 127)",
        "url": "https://fta.motir.go.kr/webmodule/_PSD_FTA/eu/doc/kor/k_eu_2_eu_kor.pdf",
        "as_of": "2011-07-01",
    },
    {
        "id": "SRC-EUKOR-ROO",
        "title": "Korea-EU FTA Protocol on rules of origin, Annex II (product specific rules)",
        "url": "https://fta.motir.go.kr/webmodule/_PSD_FTA/eu/doc/eng/k_eu_roo_eng.pdf",
        "as_of": "2011-07-01",
    },
    {
        "id": "SRC-RCEP-1-JP",
        "title": "RCEP Annex I, Schedule of Tariff Commitments of Japan",
        "url": "https://www.dfat.gov.au/sites/default/files/recp-schedule-of-japan.xlsx",
        "as_of": "2022-01-01",
    },
    {
        "id": "SRC-WITS-2023",
        "title": "WITS / TRAINS applied tariff, reporter 840 (United States), partner 000, year 2023",
        "url": "https://wits.worldbank.org/API/V1/SDMX/V21/datasource/TRN/reporter/840/partner/000/product/850760/year/2023/datatype/reported",
        "as_of": "2023-12-31",
    },
]

AGREEMENTS = [
    {
        "code": "MFN",
        "name": "Most favoured nation, no agreement claimed",
        "market": "*",
        "approved_exporter_required": False,
        "coverage": "rate",
        "note": "baseline every agreement is compared against",
    },
    {
        "code": "KORUS",
        "name": "Korea-United States Free Trade Agreement",
        "market": "US",
        "in_force": "2012-03-15",
        "approved_exporter_required": False,
        "coverage": "rules+rates",
        "note": "rules from Annex 6-A, rates from Annex 2-B for chapters 39, 84, 85",
    },
    {
        "code": "RCEP",
        "name": "Regional Comprehensive Economic Partnership",
        "market": "JP",
        # The date this snapshot's RCEP rows speak for: the agreement entered
        # into force for Japan on 2022-01-01 and for Korea on 2022-02-01.  The
        # schedule in Annex I is Japan's, so Japan's date is the one on the row.
        "in_force": "2022-01-01",
        "approved_exporter_required": True,
        "coverage": "rules+rates",
        "note": "product specific rules from Annex 3A; rates from Japan's schedule in Annex I; "
                "in force for Japan on 2022-01-01",
    },
    {
        "code": "EUKOR",
        "name": "Korea-European Union Free Trade Agreement",
        "market": "EU",
        "in_force": "2011-07-01",
        "approved_exporter_required": True,
        "coverage": "rules+rates",
        "note": "product specific rules from the protocol's Annex II; rates from the EU schedule in Annex 2-A",
    },
    {
        "code": "TURKOR",
        "name": "Korea-Turkiye Free Trade Agreement",
        "market": "TR",
        "in_force": "2013-05-01",
        "approved_exporter_required": False,
        "coverage": "none",
        "note": "rules and rates are not in this snapshot; listed so the gap is visible",
    },
]

DEADLINES = [
    {
        "id": "DL-POST-IMPORT-CLAIM",
        "agreement": "ALL",
        "basis": "import_declaration_date",
        "months": 12,
        "label": "post import preference claim",
        "status": "in force",
        "legal_ref": "협정관세 사후적용 신청기간 1년",
        "source": "SRC-MOEF-2025-02",
        "note": "기획재정부 2025-02-12 자료는 이 기간을 최대 5년으로 넓히는 개정을 추진 과제로 적고 있다",
    },
]

LEAK_LABELS = ("Shipment", "Material", "BomNode", "Verdict", "Party", "Good")


def _title_for(code: str) -> str:
    return code


def _read(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _optional(path: str) -> list[dict]:
    return _read(path) if os.path.exists(path) else []


def _write_intervals(conn, rule_id: str, parsed: list[dict]) -> int:
    """Hang the intervals a rule names off the rule as nodes.

    A rule sentence bars materials by provision: a subheading, a list of them,
    or a range, and for some rules the range the rule itself covers.  Written
    as nodes rather than as an array property, each one is one hop from its
    rule, so a material list can meet them in a single traversal instead of a
    loop in Python.  ``alternative`` says which alternative of the sentence the
    interval belongs to, ``ord`` keeps the order the sentence names them in,
    and the eight digit bounds are what the comparison runs on.
    """
    written = 0
    for alt_index, alternative in enumerate(parsed, start=1):
        intervals = []
        for token in alternative.get("excluded") or []:
            intervals.append(("excluded", token, token))
        for pair in alternative.get("excluded_ranges") or []:
            intervals.append(("excluded", pair[0], pair[1]))
        group = alternative.get("group") or []
        if len(group) > 1:
            intervals.append(("group", group[0], group[1]))
        order = 0
        for kind, low, high in intervals:
            low_label = codes.pretty(low)
            high_label = codes.pretty(high)
            label = low_label if low_label == high_label else "%s to %s" % (low_label, high_label)
            conn.execute(
                """
                MATCH (r:OriginRule {id: $rule})
                CREATE (i:HsInterval {id: $id, kind: $kind, alternative: $alternative,
                                      ord: $ord, low: $low, high: $high,
                                      from_norm: $from_norm, to_norm: $to_norm, label: $label})
                CREATE (r)-[:EXCLUDES {alternative: $alternative}]->(i)
                """,
                {
                    "rule": rule_id,
                    "id": "%s-A%d-I%d-%s" % (rule_id, alt_index, order, kind),
                    "kind": kind,
                    "alternative": alt_index,
                    "ord": order,
                    "low": low,
                    "high": high,
                    "from_norm": codes.normalise_low(low),
                    "to_norm": codes.normalise(high),
                    "label": label,
                },
            )
            order += 1
            written += 1
    return written


def _rate_text(text: str, staging: str) -> str:
    value = _first_percent(text, staging)
    if value is not None:
        return "%g%%" % value
    return text or "not printed"


def _first_percent(text: str, staging: str) -> float | None:
    """The base rate of a schedule that prints the rate in words."""
    from . import rates

    if staging == "FREE":
        return 0.0
    value = rates.parse_percent(text)
    return value


def build(conn, data_dir: str) -> dict:
    snapshot_id, as_of = snapshot_identity(data_dir)
    korus_rules = _read(os.path.join(data_dir, "korus_psr.json"))
    rcep_rules = _read(os.path.join(data_dir, "rcep_psr.json"))
    rate_rows = _read(os.path.join(data_dir, "korus_rates.json"))
    eukor_rules = _optional(os.path.join(data_dir, "eukor_psr.json"))
    eukor_rows = _optional(os.path.join(data_dir, "eukor_rates.json"))
    japan_rows = _optional(os.path.join(data_dir, "rcep_japan_rates.json"))
    wits_path = os.path.join(data_dir, "us_mfn_applied.json")
    wits_rows = _read(wits_path) if os.path.exists(wits_path) else []

    conn.execute("CREATE CONSTRAINT chapter_code IF NOT EXISTS FOR (c:Chapter) REQUIRE c.code IS UNIQUE")
    conn.execute("CREATE CONSTRAINT heading_code IF NOT EXISTS FOR (h:Heading) REQUIRE h.code IS UNIQUE")
    conn.execute("CREATE CONSTRAINT subheading_code IF NOT EXISTS FOR (s:Subheading) REQUIRE s.code IS UNIQUE")
    conn.execute("CREATE CONSTRAINT agreement_code IF NOT EXISTS FOR (a:Agreement) REQUIRE a.code IS UNIQUE")
    conn.execute("CREATE CONSTRAINT source_id IF NOT EXISTS FOR (s:Source) REQUIRE s.id IS UNIQUE")
    conn.execute("CREATE CONSTRAINT rule_id IF NOT EXISTS FOR (r:OriginRule) REQUIRE r.id IS UNIQUE")
    conn.execute("CREATE CONSTRAINT rate_id IF NOT EXISTS FOR (r:RateLine) REQUIRE r.id IS UNIQUE")
    conn.execute("CREATE INDEX rate_hts8 IF NOT EXISTS FOR (r:RateLine) ON (r.hts8)")
    conn.execute("CREATE INDEX rule_norm IF NOT EXISTS FOR (r:OriginRule) ON (r.from_norm)")

    conn.execute(
        """
        CREATE (s:Snapshot {id: $id, as_of: date($as_of), rule_version: $version,
                            max_age_days: $max_age, chapters: $chapters,
                            generator: 'scripts/extract_sources.py'})
        """,
        {
            "id": snapshot_id,
            "as_of": as_of,
            "version": RULE_VERSION,
            "max_age": MAX_AGE_DAYS,
            "chapters": list(CHAPTER_TITLES),
        },
    )

    for source in SOURCES:
        conn.execute(
            """
            CREATE (s:Source {id: $id, title: $title, url: $url, as_of: date($as_of)})
            """,
            source,
        )

    for agreement in AGREEMENTS:
        conn.execute(
            """
            MATCH (snap:Snapshot {id: $snapshot})
            CREATE (a:Agreement {code: $code, name: $name, market: $market,
                                 approved_exporter_required: $approved_exporter_required,
                                 coverage: $coverage, note: $note, in_force: $in_force})
            CREATE (snap)-[:CONTAINS]->(a)
            """,
            {
                "snapshot": SNAPSHOT_ID,
                "code": agreement["code"],
                "name": agreement["name"],
                "market": agreement["market"],
                "approved_exporter_required": agreement["approved_exporter_required"],
                "coverage": agreement["coverage"],
                "note": agreement["note"],
                "in_force": agreement.get("in_force"),
            },
        )

    for deadline in DEADLINES:
        conn.execute(
            """
            MATCH (s:Source {id: $source})
            CREATE (d:DeadlineRule {id: $id, agreement: $agreement, basis: $basis,
                                    months: $months, label: $label, status: $status,
                                    legal_ref: $legal_ref, note: $note})
            CREATE (d)-[:CITED_FROM]->(s)
            """,
            {**deadline, "source": deadline["source"]},
        )

    # Chapters and the code tree.
    for chapter_code, title in CHAPTER_TITLES.items():
        conn.execute(
            "MATCH (snap:Snapshot {id: $snapshot}) "
            "CREATE (c:Chapter {code: $code, title: $title}) "
            "CREATE (snap)-[:COVERS]->(c)",
            {"snapshot": snapshot_id, "code": chapter_code, "title": title},
        )

    subheading_titles: dict[str, str] = {}
    for row in rate_rows:
        digits = row["hts8"]
        subheading_titles.setdefault(digits[:6], row["description"])
    for row in rcep_rules:
        code = re.sub(r"[^0-9]", "", row["code_from"])
        if len(code) == 6 and row.get("description"):
            subheading_titles.setdefault(code, row["description"])
    for row in eukor_rows:
        subheading_titles.setdefault(row["cn8"][:6], row["description"])
    for row in japan_rows:
        subheading_titles.setdefault(row["code"][:6], row["description"])

    heading_titles: dict[str, str] = {}
    for row in rcep_rules:
        code = re.sub(r"[^0-9]", "", row["code_from"])
        if len(code) == 4 and row.get("description"):
            heading_titles.setdefault(code, row["description"])

    seen_headings = set()
    seen_subheadings = set()
    line_codes = (
        {row["hts8"] for row in rate_rows}
        | {row["cn8"] for row in eukor_rows}
        | {row["code"] for row in japan_rows}
        | set(subheading_titles)
    )
    for digits in sorted(line_codes):
        heading = digits[:4]
        subheading = digits[:6]
        if heading not in seen_headings:
            conn.execute(
                "MATCH (c:Chapter {code: $chapter}) "
                "CREATE (h:Heading {code: $code, title: $title, chapter: $chapter}) "
                "CREATE (h)-[:IN_CHAPTER]->(c)",
                {
                    "chapter": digits[:2],
                    "code": heading,
                    "title": heading_titles.get(heading, ""),
                },
            )
            seen_headings.add(heading)
        if subheading not in seen_subheadings:
            conn.execute(
                "MATCH (h:Heading {code: $heading}) "
                "CREATE (s:Subheading {code: $code, title: $title, norm: $norm, heading: $heading}) "
                "CREATE (s)-[:IN_HEADING]->(h)",
                {
                    "heading": heading,
                    "code": subheading,
                    "title": subheading_titles.get(subheading, ""),
                    "norm": codes.normalise(subheading),
                },
            )
            seen_subheadings.add(subheading)

    # Origin rules.
    counter = 0
    rule_sets = [
        (korus_rules, "SRC-KORUS-6A"),
        (rcep_rules, "SRC-RCEP-3A"),
        (eukor_rules, "SRC-EUKOR-ROO"),
    ]
    for rows, source_id in rule_sets:
        for row in rows:
            counter += 1
            rule_id = f"OR-{counter:04d}"
            priority = {"subheading": 1, "range": 2, "heading": 3, "chapter": 4}.get(row["level"], 5)
            alternatives = row.get("alternatives")
            # A rule row also carries the exclusion and the group its first
            # alternative names, in normalised form, so a reader of the graph can
            # ask the interval question in Cypher (cypher/02) without re-reading
            # the sentence.  The verdict still comes from the parsed alternative.
            parsed = alternatives or rulebook.alternatives(
                {"text": row["text"], "code_from": row["code_from"], "code_to": row["code_to"]}
            )
            first = parsed[0] if parsed else {}
            excluded = row.get("excluded_from") or first.get("excluded") or []
            group = row.get("group_exclude") or list(first.get("group") or [])
            conn.execute(
                """
                MATCH (a:Agreement {code: $agreement})
                MATCH (src:Source {id: $source})
                CREATE (r:OriginRule {id: $id, agreement: $agreement, level: $level,
                                      code_from: $code_from, code_to: $code_to,
                                      from_norm: $from_norm, to_norm: $to_norm,
                                      text: $text, kinds: $kinds,
                                      rvc_build_down: $rvc_down, rvc_build_up: $rvc_up,
                                      excluded_from: $excluded, group_exclude_from: $group_from,
                                      group_exclude_to: $group_to,
                                      originating_weight_min: $weight_min,
                                      alternatives_json: $alternatives_json,
                                      structured: $structured, priority: $priority})
                CREATE (r)-[:FOR]->(a)
                CREATE (r)-[:CITED_FROM]->(src)
                """,
                {
                    "id": rule_id,
                    "agreement": row["agreement"],
                    "level": row["level"],
                    "code_from": row["code_from"],
                    "code_to": row["code_to"],
                    "from_norm": row["from_norm"],
                    "to_norm": row["to_norm"],
                    "text": row["text"],
                    "kinds": row["kinds"],
                    "rvc_down": row.get("rvc_build_down"),
                    "rvc_up": row.get("rvc_build_up"),
                    "excluded": excluded,
                    "group_from": codes.normalise_low(group[0]) if group else None,
                    "group_to": codes.normalise(group[1]) if len(group) > 1 else None,
                    "weight_min": row.get("originating_weight_min"),
                    "alternatives_json": json.dumps(alternatives, ensure_ascii=False)
                    if alternatives
                    else None,
                    "structured": not row.get("unstructured", False),
                    "priority": priority,
                    "source": source_id,
                },
            )
            _write_intervals(conn, rule_id, parsed)

    # Tariff lines and the staging that decides the rate on a date.
    line_sets = [
        (
            [
                {
                    "code": row["hts8"],
                    "market": row["market"],
                    "agreement": row["agreement"],
                    "description": row["description"],
                    "base_rate_text": row["base_rate_text"],
                    "base_rate_percent": row["base_rate_percent"],
                    "base_rate_kind": row["base_rate_kind"],
                    "staging": row["staging"],
                    "years": None,
                    "partner": None,
                    "currency": "USD",
                }
                for row in rate_rows
            ],
            "SRC-KORUS-2B",
        ),
        (
            [
                {
                    "code": row["cn8"],
                    "market": row["market"],
                    "agreement": row["agreement"],
                    "description": row["description"],
                    "base_rate_text": row["base_rate_text"],
                    "base_rate_percent": row["base_rate_percent"],
                    "base_rate_kind": row["base_rate_kind"],
                    "staging": row["staging"],
                    "years": None,
                    "partner": None,
                    "currency": "EUR",
                }
                for row in eukor_rows
            ],
            "SRC-EUKOR-2A",
        ),
        (
            [
                {
                    "code": row["code"],
                    "market": row["market"],
                    "agreement": row["agreement"],
                    "description": row["description"],
                    "base_rate_text": _rate_text(row["base_rate_text"], row["staging"]),
                    "base_rate_percent": _first_percent(row["base_rate_text"], row["staging"]),
                    "base_rate_kind": "percent"
                    if _first_percent(row["base_rate_text"], row["staging"]) is not None
                    else "specific",
                    "staging": row["staging"],
                    "years": row["years"],
                    "partner": row["partner"],
                    "currency": "JPY",
                }
                for row in japan_rows
            ],
            "SRC-RCEP-1-JP",
        ),
    ]
    seen_lines = set()
    for lines, source_id in line_sets:
        for row in lines:
            # The id names the agreement, the line and the partner treatment the
            # row belongs to.  Two rows that share all three are two different
            # rates for one question, and quietly keeping the first would make
            # the snapshot depend on row order; the build stops instead.
            line_id = f"RL-{row['agreement']}-{row['code']}-{row['partner'] or 'ALL'}"
            if line_id in seen_lines:
                raise ValueError(
                    "two schedule rows claim %s: a rate line must name one partner treatment"
                    % line_id
                )
            seen_lines.add(line_id)
            conn.execute(
                """
                MATCH (s:Subheading {code: $subheading})
                MATCH (a:Agreement {code: $agreement})
                MATCH (src:Source {id: $source})
                CREATE (r:RateLine {id: $id, code: $code, hts8: $code, hs6: $hs6,
                                    market: $market, agreement: $agreement,
                                    description: $description,
                                    base_rate_percent: $percent, base_rate_text: $text,
                                    base_rate_kind: $kind, staging: $staging,
                                    years: $years, partner: $partner,
                                    currency: $currency, nomenclature: $nomenclature})
                CREATE (r)-[:FOR]->(s)
                CREATE (r)-[:FOR]->(a)
                CREATE (r)-[:CITED_FROM]->(src)
                """,
                {
                    "id": line_id,
                    "code": row["code"],
                    "hs6": row["code"][:6],
                    "market": row["market"],
                    "agreement": row["agreement"],
                    "description": row["description"],
                    "percent": row["base_rate_percent"],
                    "text": row["base_rate_text"],
                    "kind": row["base_rate_kind"],
                    "staging": row["staging"],
                    "years": row["years"],
                    "partner": row["partner"] or "ALL",
                    "currency": row["currency"],
                    "nomenclature": {"US": "HTS", "EU": "CN", "JP": "JP"}.get(row["market"], ""),
                    "subheading": row["code"][:6],
                    "source": source_id,
                },
            )

    # Applied MFN at six digits, from WITS.  Kept apart from the line level
    # rates because an average of several lines is not a rate for a shipment.
    for code, payload in (wits_rows or {}).items() if isinstance(wits_rows, dict) else []:
        if not isinstance(payload, dict) or "OBS_VALUE" not in payload:
            continue
        lines = int(float(payload.get("TOTALNOOFLINES") or 0))
        conn.execute(
            """
            OPTIONAL MATCH (s:Subheading {code: $hs6})
            MATCH (src:Source {id: 'SRC-WITS-2023'})
            CREATE (r:Hs6Rate {id: $id, hs6: $hs6, market: 'US', year: 2023,
                               percent: $percent, lines: $lines, exact: $exact})
            CREATE (r)-[:CITED_FROM]->(src)
            FOREACH (target IN CASE WHEN s IS NULL THEN [] ELSE [s] END |
                CREATE (r)-[:FOR]->(target))
            """,
            {
                "id": f"HS6-{code}",
                "hs6": code,
                "percent": float(payload["OBS_VALUE"]),
                "lines": lines,
                "exact": lines == 1,
            },
        )

    counts = store.label_counts(conn)
    counts["relationships"] = store.relationship_count(conn)
    return counts
