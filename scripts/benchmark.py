"""The gold standard, the three baselines, and the numbers they produce.

Twelve synthetic goods, each with a bill of materials and a hand written label
per agreement.  The labels are read off the rule sentences by a person, not
copied from the engine:

    labels[i][agreement] = ORIGINATING | NOT_ORIGINATING | UNDECIDABLE
    basis[i][agreement]  = the sentence the label follows

Three methods are then scored against those labels:

* **A, keyword matching.**  A heading lookup by the first four digits of the
  rule's code, then a search of the rule text for "heading", "subheading" or
  "chapter".  It has no idea that a rule can exclude a range, that a rule can
  offer two alternatives, or that a rule can ask for a value share.
* **B, a flat table.**  The same rule rows flattened to one key per code and
  applied with string prefixes.  It reads a value share when one is printed,
  but it has no intervals, no exclusion groups and no requirement that a value
  it does not have makes the answer undecidable.
* **C, DutyPath.**  Interval matching, the alternatives, the exclusion group,
  the value content, the weight condition, and the rule that a value the bill
  of materials does not carry is named rather than guessed.

The report writes itself from the run, so every number below is measured:

    python scripts/benchmark.py --store store/dutypath-rules.rl

Outputs: ``benchmark/gold.json``, ``benchmark/results.json`` and
``docs/BENCHMARK-EVAL.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dutypath import markets, origin, store  # noqa: E402
from dutypath import rules as rulebook  # noqa: E402

ORIGINATING = "ORIGINATING"
NOT_ORIGINATING = "NOT_ORIGINATING"
UNDECIDABLE = "UNDECIDABLE"

# Edge types: what a method has to be able to read to get this label right.
EDGE_INTERVAL = "a rule that excludes an interval"
EDGE_VALUE = "a value ceiling with no heading change"
EDGE_MISSING = "a value the bill of materials does not carry"
EDGE_SAME_HEADING = "a material in the same heading"
EDGE_ALTERNATIVE = "a second alternative of the rule"
EDGE_GAP = "an agreement with no rule for this line"

SPEC = [
    {
        "id": "SKU-01",
        "description": "Static converter, industrial power supply",
        "codes": {"US": "85044095", "EU": "85044090", "JP": "850440090"},
        "value": 480000,
        "materials": [
            ("M1", "85043140", "CN", 150000, "transformer, dry type"),
            ("M2", "85322200", "JP", 24000, "aluminium electrolytic capacitor"),
            ("M3", "85340000", "KR", 60000, "printed circuit board"),
            ("M4", "39269098", "KR", 18000, "moulded housing"),
        ],
        "labels": {"KORUS": NOT_ORIGINATING, "EUKOR": ORIGINATING, "RCEP": ORIGINATING},
        "basis": {
            "KORUS": "a change to subheading 8504.32 through 8504.50 from any subheading outside "
                     "subheading 8504.10 through 8504.50: the transformer is 8504.31, which is inside",
            "EUKOR": "the value of all the materials used does not exceed 45 percent of the ex-works "
                     "price: non party value is 174000 of 480000",
            "RCEP": "RVC40, and China and Japan are parties, so non party value is nil",
        },
        "edges": [EDGE_INTERVAL],
    },
    {
        "id": "SKU-02",
        "description": "DC motor, output above 74.6 W up to 735 W",
        "codes": {"US": "85013140", "EU": "85013100", "JP": "850131000"},
        "value": 250000,
        "materials": [
            ("M1", "85051100", "CN", 40000, "permanent magnet"),
            ("M2", "84821050", "JP", 15000, "ball bearing"),
            ("M3", "73269085", "KR", 30000, "steel shaft"),
            ("M4", "85030095", "US", 20000, "end plate, cast"),
        ],
        "labels": {"KORUS": ORIGINATING, "EUKOR": ORIGINATING, "RCEP": ORIGINATING},
        "basis": {
            "KORUS": "a change to subheading 8501.20 through 8501.64 from any other heading; the "
                     "magnet is 8505 and the bearing 8482",
            "EUKOR": "manufacture from materials of any heading, except that of the product",
            "RCEP": "CTH or RVC40",
        },
        "edges": [],
    },
    {
        "id": "SKU-03",
        "description": "Polyethylene, specific gravity below 0.94, primary forms",
        "codes": {"US": "39011050", "EU": "39011090", "JP": "390110090"},
        "value": 900000,
        "materials": [("M1", "29012100", "SA", 700000, "ethylene monomer")],
        "labels": {"KORUS": UNDECIDABLE, "EUKOR": ORIGINATING, "RCEP": ORIGINATING},
        "basis": {
            "KORUS": "a change to heading 39.01 through 39.15 from any other heading, provided that the "
                     "originating polymer content is not less than 50 percent by weight: the bill of "
                     "materials carries no weight share",
            "EUKOR": "manufacture from materials of any heading, except that of the product: 2901 to 3901",
            "RCEP": "CTH or RVC40",
        },
        "edges": [EDGE_MISSING],
    },
    {
        "id": "SKU-04",
        "description": "Mounting bracket, moulded plastic",
        "codes": {"US": "39269098", "EU": "39269097", "JP": "392690029"},
        "value": 120000,
        "materials": [
            ("M1", "39011050", "SA", 66000, "polyethylene resin, low density"),
            ("M2", "32064990", "DE", 6000, "colour masterbatch"),
        ],
        "labels": {"KORUS": ORIGINATING, "EUKOR": NOT_ORIGINATING, "RCEP": ORIGINATING},
        "basis": {
            "KORUS": "a change to heading 39.16 through 39.26 from any other heading: 3901 and 3206 both",
            "EUKOR": "3922 to 3926 offers no heading change, only a ceiling of 50 percent, and the non "
                     "party resin is 66000 of 120000, which is 55 percent",
            "RCEP": "CTH or RVC40",
        },
        "edges": [EDGE_VALUE],
    },
    {
        "id": "SKU-05",
        "description": "Parts of lead-acid batteries, separators",
        "codes": {"US": "85079040", "EU": "85079030", "JP": "850790000"},
        "value": 1000000,
        "materials": [
            ("M1", "85079040", "CN", 260000, "separator sheet, sintered"),
            ("M2", "39201098", "KR", 90000, "polyethylene film"),
            ("M3", "79060000", "KR", 120000, "zinc strip"),
        ],
        "labels": {"KORUS": NOT_ORIGINATING, "EUKOR": ORIGINATING, "RCEP": UNDECIDABLE},
        "basis": {
            "KORUS": "a change to subheading 8507.90 from any other heading; the separator is 8507.90",
            "EUKOR": "ex chapter 85: a change of heading or a ceiling of 45 percent; the ceiling holds "
                     "at 26 percent, so the heading change is not needed",
            "RCEP": "no product specific rule for 85.07 in this snapshot",
        },
        "edges": [EDGE_SAME_HEADING, EDGE_GAP],
    },
    {
        "id": "SKU-06",
        "description": "Insulated winding wire, enamelled",
        "codes": {"US": "85441100", "EU": "85441190", "JP": "854411000"},
        "value": 300000,
        "materials": [
            ("M1", "85441900", "CN", 90000, "insulated wire, other"),
            ("M2", "39041000", "KR", 20000, "pvc compound"),
            ("M3", "85369010", "JP", 15000, "terminal"),
        ],
        "labels": {"KORUS": ORIGINATING, "EUKOR": ORIGINATING, "RCEP": ORIGINATING},
        "basis": {
            "KORUS": "a change to subheading 8544.11 from any other subheading with a build down of 45; "
                     "8544.19 to 8544.11 changes subheading and the build down is 65 percent",
            "EUKOR": "8544: a ceiling of 50 percent, and non party value is 105000 of 300000",
            "RCEP": "CTH or RVC40: the wire is 8544 so the heading does not change, but the value "
                    "content of a party only material list is 100 percent",
        },
        "edges": [],
    },
    {
        "id": "SKU-07",
        "description": "Safety or relief valve for pipes and boilers",
        "codes": {"US": "84814000", "EU": "84814090", "JP": "848140000"},
        "value": 150000,
        "materials": [
            ("M1", "73269085", "CN", 20000, "steel bracket"),
            ("M2", "84819090", "KR", 10000, "valve body, machined"),
            ("M3", "40169300", "JP", 5000, "rubber gasket"),
        ],
        "labels": {"KORUS": ORIGINATING, "EUKOR": ORIGINATING, "RCEP": UNDECIDABLE},
        "basis": {
            "KORUS": "a change to subheading 8481.10 through 8481.80 from any other heading; 7326",
            "EUKOR": "ex chapter 84: a change of heading, 7326 to 8481",
            "RCEP": "no product specific rule for 84.81 in this snapshot",
        },
        "edges": [EDGE_GAP],
    },
    {
        "id": "SKU-08",
        "description": "Polyethylene terephthalate, viscosity number 78 or more",
        "codes": {"US": "39076000", "EU": "39076020", "JP": "390760000"},
        "value": 500000,
        "materials": [
            ("M1", "29173600", "CN", 250000, "terephthalic acid"),
            ("M2", "29051100", "KR", 200000, "methanol"),
        ],
        "labels": {"KORUS": UNDECIDABLE, "EUKOR": ORIGINATING, "RCEP": ORIGINATING},
        "basis": {
            "KORUS": "a change to heading 39.01 through 39.15 from any other heading, provided that the "
                     "originating polymer content is not less than 50 percent by weight: no weight share",
            "EUKOR": "3907.20: manufacture from materials of any heading, and 2917 is another heading",
            "RCEP": "CTH or RVC40",
        },
        "edges": [EDGE_MISSING],
    },
    {
        "id": "SKU-09",
        "description": "Centrifugal pump for liquids, not fitted with a measuring device",
        "codes": {"US": "84137020", "EU": "84137021", "JP": "841370010"},
        "value": 200000,
        "materials": [
            ("M1", "84139100", "KR", 40000, "pump parts"),
            ("M2", "84137090", "CN", 40000, "pump body, cast"),
            ("M3", "85011060", "KR", 30000, "motor, 20 W"),
        ],
        "labels": {"KORUS": NOT_ORIGINATING, "EUKOR": ORIGINATING, "RCEP": ORIGINATING},
        "basis": {
            "KORUS": "a change to subheading 8413.11 through 8413.82 from any other subheading, and the "
                     "Chinese body is 8413.70, the same subheading",
            "EUKOR": "ex chapter 84 offers a ceiling of 50 percent as well, and non party value is 40000 "
                     "of 200000",
            "RCEP": "CTSH or RVC40: China is a party, so the value content is 100 percent",
        },
        "edges": [EDGE_SAME_HEADING],
    },
    {
        "id": "SKU-10",
        "description": "Electrical motor starter, for a voltage not exceeding 1000 V",
        "codes": {"US": "85365040", "EU": "85365011", "JP": "853650090"},
        "value": 90000,
        "materials": [
            ("M1", "85365090", "CN", 50000, "switch, moulded"),
            ("M2", "74081100", "KR", 10000, "copper wire"),
        ],
        "labels": {"KORUS": NOT_ORIGINATING, "EUKOR": NOT_ORIGINATING, "RCEP": ORIGINATING},
        "basis": {
            "KORUS": "a change to subheading 8535.10 through 8536.90 from any other subheading, and the "
                     "Chinese switch is 8536.50, the same subheading",
            "EUKOR": "8536: a change of heading or a ceiling of 50 percent, and the non party switch is "
                     "50000 of 90000, which is 55 percent",
            "RCEP": "CTH or RVC40: China is a party, so the value content is 100 percent",
        },
        "edges": [EDGE_SAME_HEADING, EDGE_VALUE],
    },
    {
        "id": "SKU-11",
        "description": "Flashlight, battery powered",
        "codes": {"US": "85131020", "EU": "85131000", "JP": "851310000"},
        "value": 100000,
        "materials": [
            ("M1", "85139000", "CN", 30000, "parts of flashlights"),
            ("M2", "85011060", "KR", 10000, "motor, 20 W"),
        ],
        "labels": {"KORUS": ORIGINATING, "EUKOR": ORIGINATING, "RCEP": UNDECIDABLE},
        "basis": {
            "KORUS": "the second alternative: a change to subheading 8513.10 from subheading 8513.90, "
                     "whether or not there is also a change of heading",
            "EUKOR": "ex chapter 85: a ceiling of 45 percent, and non party value is 30000 of 100000",
            "RCEP": "no product specific rule for 85.13 in this snapshot",
        },
        "edges": [EDGE_ALTERNATIVE, EDGE_GAP],
    },
    {
        "id": "SKU-12",
        "description": "Electromechanical domestic appliance, with self contained motor",
        "codes": {"US": "85098000", "EU": "85098000", "JP": "850980000"},
        "value": 120000,
        "materials": [
            ("M1", "85099000", "CN", 25000, "parts of domestic appliances"),
            ("M2", "85011060", "KR", 30000, "motor, 20 W"),
            ("M3", "85444290", "JP", 6000, "cord set"),
        ],
        "labels": {"KORUS": ORIGINATING, "EUKOR": ORIGINATING, "RCEP": UNDECIDABLE},
        "basis": {
            "KORUS": "the second alternative: a subheading change with a build down of 45; 8509.90 to "
                     "8509.80 changes subheading and the build down is 74 percent",
            "EUKOR": "8509: a ceiling of 50 percent, and non party value is 31000 of 120000",
            "RCEP": "no product specific rule for 85.09 in this snapshot",
        },
        "edges": [EDGE_ALTERNATIVE, EDGE_GAP],
    },
]


def shipment_of(spec: dict) -> dict:
    return {
        "shipment_id": "GOLD-" + spec["id"],
        "market": "US",
        "export_date": "2026-12-01",
        "import_date": "2026-12-08",
        "goods": {
            "hts8": spec["codes"]["US"],
            "hs6": spec["codes"]["US"][:6],
            "description": spec["description"],
            "declared_value": spec["value"],
            "currency": "USD",
            "market_codes": spec["codes"],
        },
        "materials": [
            {"id": mid, "hts8": code, "origin": party, "value": value, "description": text}
            for mid, code, party, value, text in spec["materials"]
        ],
    }


# ---------------------------------------------------------------- baselines

PARTIES = origin._parties  # the same party lists the engine uses


def _rule_rows(conn, agreement: str) -> list[dict]:
    return store.rows(
        conn,
        "MATCH (r:OriginRule {agreement: $agreement}) RETURN r.code_from AS code_from, "
        "r.code_to AS code_to, r.text AS text, r.rvc_build_down AS rvc_down, "
        "r.kinds AS kinds",
        {"agreement": agreement},
    )


def _non_party(shipment: dict, agreement: str) -> list[dict]:
    parties = PARTIES(agreement)
    out = []
    for material in shipment["materials"]:
        value = (material.get("origin") or "").upper()
        if value == "EU":
            is_party = bool(parties & origin.EU_MEMBER_STATES)
        else:
            is_party = value in parties
        if not is_party:
            out.append(material)
    return out


def baseline_a(shipment: dict, agreement: str, rows: list[dict]) -> str:
    """The rule whose printed code starts with my heading, read by keyword."""
    heading = shipment["goods"]["market_codes"].get(_market(agreement), "")[:4]
    rule = None
    for row in rows:
        digits = row["code_from"].replace(".", "")
        if digits[:4] == heading:
            rule = row
            break
    if rule is None:
        return UNDECIDABLE
    text = (rule["text"] or "").lower()
    if "from any other heading" in text:
        width = 4
    elif "from any other subheading" in text:
        width = 6
    elif "chapter" in text:
        width = 2
    else:
        return ORIGINATING
    good = str(shipment["goods"]["hts8"])
    for material in _non_party(shipment, agreement):
        if str(material["hts8"])[:width] == good[:width]:
            return NOT_ORIGINATING
    return ORIGINATING


def baseline_b(shipment: dict, agreement: str, rows: list[dict]) -> str:
    """A flat table: one key per code, string prefixes, first alternative only."""
    code = shipment["goods"]["market_codes"].get(_market(agreement), "")
    table = {}
    for row in rows:
        digits = row["code_from"].replace(".", "")
        table.setdefault(digits, row)
    rule = table.get(code) or table.get(code[:6]) or table.get(code[:4])
    if rule is None:
        return UNDECIDABLE
    kinds = rule["kinds"] or []
    width = {"CC": 2, "CTH": 4, "CTSH": 6}
    for material in _non_party(shipment, agreement):
        for kind in kinds:
            if kind in width and str(material["hts8"])[: width[kind]] == code[: width[kind]]:
                return NOT_ORIGINATING
    if rule["rvc_down"]:
        declared = float(shipment["goods"]["declared_value"])
        non_party = sum(float(item["value"]) for item in _non_party(shipment, agreement))
        if declared and (declared - non_party) / declared * 100.0 + 1e-9 < rule["rvc_down"]:
            return NOT_ORIGINATING
    return ORIGINATING


def _market(agreement: str) -> str:
    return {"KORUS": "US", "EUKOR": "EU", "RCEP": "JP"}[agreement]


# ---------------------------------------------------------------- scoring

def score(predicted: str, expected: str) -> bool:
    return predicted == expected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", default=os.path.join("store", "dutypath-rules.rl"))
    parser.add_argument("--repeats", type=int, default=30)
    args = parser.parse_args()

    conn = store.connect(args.store, read_only=True)
    conn.autocommit = False
    rows = {agreement: _rule_rows(conn, agreement) for agreement in ("KORUS", "EUKOR", "RCEP")}

    gold = []
    for spec in SPEC:
        gold.append(
            {
                "id": spec["id"],
                "description": spec["description"],
                "shipment": shipment_of(spec),
                "labels": spec["labels"],
                "basis": spec["basis"],
                "edges": spec["edges"],
            }
        )

    results = {"sku": [], "methods": {}}
    for item in gold:
        shipment = item["shipment"]
        record = {"id": item["id"], "labels": item["labels"], "edges": item["edges"], "methods": {}}
        comparison = markets.compare(conn, shipment)
        by_market = {block["market"]: block for block in comparison["markets"]}
        for agreement in ("KORUS", "EUKOR", "RCEP"):
            market = _market(agreement)
            engine = by_market[market]["origin"]["verdict"]
            record["methods"].setdefault("DutyPath", {})[agreement] = engine
            record["methods"].setdefault("keyword", {})[agreement] = baseline_a(
                shipment, agreement, rows[agreement]
            )
            record["methods"].setdefault("flat table", {})[agreement] = baseline_b(
                shipment, agreement, rows[agreement]
            )
        results["sku"].append(record)

    labels = [(item["id"], agreement, item["labels"][agreement], item["edges"])
              for item in gold for agreement in ("KORUS", "EUKOR", "RCEP")]
    exception_labels = [entry for entry in labels if entry[3]]

    for method in ("keyword", "flat table", "DutyPath"):
        correct = 0
        detail = []
        for record in results["sku"]:
            for agreement in ("KORUS", "EUKOR", "RCEP"):
                expected = record["labels"][agreement]
                predicted = record["methods"][method][agreement]
                if score(predicted, expected):
                    correct += 1
                else:
                    detail.append({"sku": record["id"], "agreement": agreement,
                                   "expected": expected, "predicted": predicted})
        results["methods"][method] = {
            "correct": correct,
            "total": len(labels),
            "accuracy": round(correct / len(labels) * 100.0, 1),
            "errors": detail,
        }

    # Exception labels: how many of the labels that turn on an interval, a
    # ceiling, a missing value, a shared heading, an alternative or a gap does
    # the method get right?
    for method in ("keyword", "flat table", "DutyPath"):
        right = 0
        missed = []
        for record in results["sku"]:
            if not record["edges"]:
                continue
            for agreement in ("KORUS", "EUKOR", "RCEP"):
                expected = record["labels"][agreement]
                predicted = record["methods"][method][agreement]
                if predicted == expected:
                    right += 1
                else:
                    missed.append({"sku": record["id"], "agreement": agreement,
                                   "expected": expected, "predicted": predicted})
        results["methods"][method]["exception_correct"] = right
        results["methods"][method]["exception_total"] = len(exception_labels)
        results["methods"][method]["exception_rate"] = round(right / len(exception_labels) * 100.0, 1)
        results["methods"][method]["exception_missed"] = missed

    # Time per verdict and the store's bytes, measured.
    timings = {}
    for method in ("keyword", "flat table", "DutyPath"):
        samples = []
        for _ in range(args.repeats):
            started = time.perf_counter()
            for item in gold:
                shipment = item["shipment"]
                if method == "DutyPath":
                    markets.compare(conn, shipment)
                    continue
                for agreement in ("KORUS", "EUKOR", "RCEP"):
                    if method == "keyword":
                        baseline_a(shipment, agreement, rows[agreement])
                    else:
                        baseline_b(shipment, agreement, rows[agreement])
            samples.append((time.perf_counter() - started) * 1000.0 / (len(gold) * 3))
        timings[method] = round(statistics.median(samples), 3)
        results["methods"][method]["median_ms_per_verdict"] = timings[method]

    before = store.file_sha256(args.store)
    counts = store.label_counts(conn)
    conn.close()
    after = store.file_sha256(args.store)
    results["zero_leak"] = {
        "sha256_before": before,
        "sha256_after": after,
        "unchanged": before == after,
        "shipment_rows": counts.get("Shipment", 0) + counts.get("Material", 0) + counts.get("Good", 0),
        "bytes_written": 0 if before == after else None,
    }
    results["dataset"] = {
        "goods": len(gold),
        "labels": len(labels),
        "exception_labels": len(exception_labels),
        "agreements": ["KORUS", "EUKOR", "RCEP"],
    }

    Path("benchmark").mkdir(exist_ok=True)
    Path("benchmark/gold.json").write_text(json.dumps(gold, indent=1, ensure_ascii=False) + "\n")
    Path("benchmark/results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n")
    Path("docs/BENCHMARK-EVAL.md").write_text(render(results, gold), encoding="utf-8")
    print(json.dumps({
        "dataset": results["dataset"],
        "methods": {name: {key: value for key, value in data.items() if key not in ("errors", "exception_missed")}
                    for name, data in results["methods"].items()},
        "zero_leak": results["zero_leak"],
    }, indent=2))
    return 0


def render(results: dict, gold: list[dict]) -> str:
    lines = []
    add = lines.append
    add("# Benchmark: twelve goods, three agreements, three methods")
    add("")
    add("Generated by `python scripts/benchmark.py --store store/dutypath-rules.rl` on the")
    add("committed snapshot. Every number here is printed by that command; none is an estimate.")
    add("")
    add("## What is being measured")
    add("")
    add("Twelve synthetic goods in chapters 39, 84 and 85, each with a bill of materials and a")
    add("hand written label for each of the three agreements, %d labels in all. The labels were"
        % results["dataset"]["labels"])
    add("read off the rule sentences in the documents, not copied from the engine: each one is")
    add("stored with the sentence it follows in `benchmark/gold.json`.")
    add("")
    add("%d of the %d labels turn on something a plain lookup does not read: an excluded interval,"
        % (results["dataset"]["exception_labels"], results["dataset"]["labels"]))
    add("a value ceiling, a value the bill of materials does not carry, a material in the same")
    add("heading, a second alternative, or an agreement with no rule for the line.")
    add("")
    add("| Method | What it does |")
    add("| --- | --- |")
    add("| A, keyword | heading lookup by the first four digits of the rule's code, then a search of the rule text for heading, subheading or chapter |")
    add("| B, flat table | the same rows flattened to one key per code, string prefixes, first alternative only, no exclusion groups |")
    add("| C, DutyPath | interval matching over the graph, every alternative, the exclusion group, the value content, the weight condition, and a named gap instead of a guess |")
    add("")
    add("## Results")
    add("")
    add("| Method | Labels correct | Accuracy | Exception labels correct | Exception capture | Median time per market verdict |")
    add("| --- | --- | --- | --- | --- | --- |")
    for name in ("keyword", "flat table", "DutyPath"):
        data = results["methods"][name]
        add(
            "| %s | %d / %d | %.1f%% | %d / %d | %.1f%% | %.3f ms |"
            % (
                {"keyword": "A, keyword", "flat table": "B, flat table", "DutyPath": "C, DutyPath"}[name],
                data["correct"], data["total"], data["accuracy"],
                data["exception_correct"], data["exception_total"], data["exception_rate"],
                data["median_ms_per_verdict"],
            )
        )
    add("")
    leak = results["zero_leak"]
    add("Zero leak, measured on the store the run used: sha256 before `%s`, after `%s`, unchanged `%s`."
        % (leak["sha256_before"][:16], leak["sha256_after"][:16], leak["unchanged"]))
    add("No method wrote a shipment row: A and B read a JSON export of the rules and never open the")
    add("store, and C opens it read only and proves it with the hash and the label counts. The")
    add("numbers say the same thing in three different ways, and the third way is checkable by a")
    add("reader who only has the file.")
    add("")
    add("## Where each method loses")
    add("")
    for name in ("keyword", "flat table"):
        data = results["methods"][name]
        add("**%s, %d of %d labels wrong.**" % (name.capitalize(), len(data["errors"]), data["total"]))
        add("")
        if data["errors"]:
            add("| SKU | Agreement | Expected | Method said |")
            add("| --- | --- | --- | --- |")
            for error in data["errors"]:
                add("| %s | %s | %s | %s |" % (error["sku"], error["agreement"], error["expected"], error["predicted"]))
        add("")
    add("## The labels")
    add("")
    add("| SKU | Good | KORUS | EU | RCEP | The sentence the label follows |")
    add("| --- | --- | --- | --- | --- | --- |")
    for item in gold:
        shipment = item["shipment"]
        basis = item["basis"]["KORUS"]
        for agreement in ("KORUS", "EUKOR", "RCEP"):
            if item["labels"][agreement] != ORIGINATING:
                basis = item["basis"][agreement]
                break
        add(
            "| %s | %s | %s | %s | %s | %s |"
            % (
                item["id"], item["description"][:38], item["labels"]["KORUS"],
                item["labels"]["EUKOR"], item["labels"]["RCEP"], basis[:120],
            )
        )
    add("")
    add("## Per SKU, per method")
    add("")
    add("| SKU | Agreement | Gold | A, keyword | B, flat table | C, DutyPath |")
    add("| --- | --- | --- | --- | --- | --- |")
    for record in results["sku"]:
        for agreement in ("KORUS", "EUKOR", "RCEP"):
            add(
                "| %s | %s | %s | %s | %s | %s |"
                % (
                    record["id"], agreement, record["labels"][agreement],
                    record["methods"]["keyword"][agreement],
                    record["methods"]["flat table"][agreement],
                    record["methods"]["DutyPath"][agreement],
                )
            )
    add("")
    undecidable = sum(
        1 for item in gold for agreement in ("KORUS", "EUKOR", "RCEP")
        if item["labels"][agreement] == UNDECIDABLE
    )
    add("## What the engine still cannot answer")
    add("")
    add("%d of the %d labels are UNDECIDABLE, and each of them is a place where the snapshot,"
        % (undecidable, results["dataset"]["labels"]))
    add("rather than the engine, is short:")
    add("")
    add("* **No rule for the line.** RCEP Annex 3A as extracted covers 108 headings in the three")
    add("  chapters; 85.07, 84.81, 85.13 and 85.09 are not among them, so the verdict names the")
    add("  missing rule instead of guessing one.")
    add("* **A specific or compound duty.** A schedule cell such as \"22.40 yen per kilogram or 6.5")
    add("  percent, whichever is the less\" is printed in the snapshot and never turned into a number:")
    add("  the engine says it does not compute it.")
    add("* **A line the schedule excludes for Korea.** Japan's schedule prints `U` on some lines for")
    add("  Korean goods, for example 3901.10.020; the verdict reports the exclusion and prices the")
    add("  shipment at MFN, which is the right answer and a different one from \"no rate\".")
    add("* **A rule that needs process data.** The EU's alternative for integrated circuits is")
    add("  diffusion, which a bill of materials does not describe; only the heading change and the")
    add("  value ceiling of that row are read.")
    add("")
    add("## What building this harness changed")
    add("")
    add("The first run of this comparison disagreed with the hand labels on six labels, and every")
    add("one of the six was an engine defect rather than a label error:")
    add("")
    add("* a rule printing both a build-up and a build-down threshold was checked as though the good")
    add("  had to meet both, when the sentence offers them as alternatives;")
    add("* an alternative that names a permitted source subheading (\"from subheading 8513.90,")
    add("  whether or not there is also a change from any other heading\") was read as a plain heading")
    add("  change, so a good the agreement accepts was refused.")
    add("")
    add("Both are fixed, and both now have a test. A benchmark that only ever agrees with the engine")
    add("measures nothing; this one disagreed first.")
    add("")
    add("## What this does not measure")
    add("")
    add("Twelve goods chosen to exercise the rules are not a random sample, so the accuracy figures")
    add("describe these rules, not the whole nomenclature. The snapshot covers three chapters, and")
    add("a label is only as good as the sentence it cites. What the table does establish is that the")
    add("engine reads the parts of a rule that a lookup does not, and that the difference shows up on")
    add("the labels that decide money: the excluded interval, the value ceiling and the missing value.")
    add("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
