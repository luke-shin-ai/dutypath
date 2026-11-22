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

SNAPSHOT_ID = "dutypath-rules-2026-11-22"
AS_OF = "2026-11-22"
RULE_VERSION = "1.0"
MAX_AGE_DAYS = 120

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
        "in_force": "2022-02-01",
        "approved_exporter_required": True,
        "coverage": "rules",
        "note": "product specific rules from Annex 3A; rate schedules are not in this snapshot",
    },
    {
        "code": "EUKOR",
        "name": "Korea-European Union Free Trade Agreement",
        "market": "EU",
        "in_force": "2011-07-01",
        "approved_exporter_required": True,
        "coverage": "none",
        "note": "rules and rates are not in this snapshot; listed so the gap is visible",
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


def build(conn, data_dir: str) -> dict:
    korus_rules = _read(os.path.join(data_dir, "korus_psr.json"))
    rcep_rules = _read(os.path.join(data_dir, "rcep_psr.json"))
    rate_rows = _read(os.path.join(data_dir, "korus_rates.json"))
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
            "id": SNAPSHOT_ID,
            "as_of": AS_OF,
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
            {"snapshot": SNAPSHOT_ID, "code": chapter_code, "title": title},
        )

    subheading_titles: dict[str, str] = {}
    for row in rate_rows:
        digits = row["hts8"]
        subheading_titles.setdefault(digits[:6], row["description"])
    for row in rcep_rules:
        code = re.sub(r"[^0-9]", "", row["code_from"])
        if len(code) == 6 and row.get("description"):
            subheading_titles.setdefault(code, row["description"])

    heading_titles: dict[str, str] = {}
    for row in rcep_rules:
        code = re.sub(r"[^0-9]", "", row["code_from"])
        if len(code) == 4 and row.get("description"):
            heading_titles.setdefault(code, row["description"])

    seen_headings = set()
    seen_subheadings = set()
    for digits in sorted({row["hts8"] for row in rate_rows} | set(subheading_titles)):
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
    for row in korus_rules + rcep_rules:
        counter += 1
        rule_id = f"OR-{counter:04d}"
        priority = {"subheading": 1, "range": 2, "heading": 3, "chapter": 4}.get(row["level"], 5)
        group = row.get("group_exclude") or []
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
                "excluded": row.get("excluded_from") or [],
                "group_from": group[0] if group else None,
                "group_to": group[1] if len(group) > 1 else None,
                "weight_min": row.get("originating_weight_min"),
                "structured": not row.get("unstructured", False),
                "priority": priority,
                "source": "SRC-KORUS-6A" if row["agreement"] == "KORUS" else "SRC-RCEP-3A",
            },
        )

    # Tariff lines and the staging that decides the rate on a date.
    for row in rate_rows:
        rule_id = f"RL-{row['hts8']}"
        conn.execute(
            """
            MATCH (s:Subheading {code: $subheading})
            MATCH (a:Agreement {code: $agreement})
            MATCH (src:Source {id: 'SRC-KORUS-2B'})
            CREATE (r:RateLine {id: $id, hts8: $hts8, hs6: $hs6, market: $market,
                                agreement: $agreement, description: $description,
                                base_rate_percent: $percent, base_rate_text: $text,
                                base_rate_kind: $kind, staging: $staging, currency: 'USD'})
            CREATE (r)-[:FOR]->(s)
            CREATE (r)-[:FOR]->(a)
            CREATE (r)-[:CITED_FROM]->(src)
            """,
            {
                "id": rule_id,
                "hts8": row["hts8"],
                "hs6": row["hts8"][:6],
                "market": row["market"],
                "agreement": row["agreement"],
                "description": row["description"],
                "percent": row["base_rate_percent"],
                "text": row["base_rate_text"],
                "kind": row["base_rate_kind"],
                "staging": row["staging"],
                "subheading": row["hts8"][:6],
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
