"""Extract Japan's tariff schedule for the RCEP annex.

The source is the machine readable copy of Annex I, Schedule of Tariff
Commitments of Japan (RCEP), published by the Australian Department of Foreign
Affairs and Trade next to the signed text.  Its columns are the printed
schedule itself:

    Tariff Line | Description | Base Rate | Year 1 .. Year 21 and subsequent

A cell holds either a rate ("Free", "3.9", 0.039, "22.40 yen/kg or 6.5%,
whichever is the less"), or "U", which the schedule uses for a line the Party
has excluded from reduction or elimination for that partner.  The cells are
copied as printed: this extractor does no arithmetic, so the number a verdict
prints is the number in the schedule for the year it asks about.

Japan's schedule carries partner specific rows for the same tariff line, marked
in the Remarks column ("Treatment for China and Korea", "Treatment for China").
Every row is kept with the treatment it belongs to: `KR` when the remark names
Korea, `ALL` when it has no remark and so speaks for every party, and
`OTHER-<parties>` when it names only other parties (for example
`OTHER-AS+AU+NZ`). A Korean shipment reads the Korea row, or the general row
when there is one, and a row written for China alone is never mistaken for
the general rate.

Usage:
    python scripts/extract_rcep_japan.py --xlsx <schedule of japan>.xlsx \
        --out data/extract-2026-11-22/rcep_japan_rates.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

CHAPTERS = ("39", "84", "85")
FIRST_DATA_ROW = 6  # 1-based row where the header ends in the published sheet


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return ("%.4f" % value).rstrip("0").rstrip(".")
    return str(value).strip()


def _partner(remarks: str) -> str:
    """Whether the row is the Korea rate, the general rate, or another party's.

    The Remarks column names the parties a row is written for: "Treatment for
    Korea", "Treatment for China and Korea", "Treatment for ASEAN, Australia,
    and New Zealand".  A row that names Korea is the rate a Korean exporter
    gets; an empty remark is the rate every party gets; a remark that names
    only other parties is neither, and must not be handed to a Korean shipment
    as if it were the general rate.  The remark itself travels with the row, so
    a reader sees which parties the number was written for.
    """
    lowered = remarks.lower()
    if not lowered.strip():
        return "ALL"
    if "korea" in lowered:
        return "KR"
    named = [code for word, code in PARTIES.items() if word in lowered]
    return "OTHER-" + "+".join(sorted(named)) if named else "OTHER"


# The parties a Remarks cell can name, as the ISO code the rest of the project
# uses.  The label says which parties a row was written for, so two rows for one
# line never read as the same treatment.
PARTIES = {
    "asean": "AS",
    "australia": "AU",
    "new zealand": "NZ",
    "china": "CN",
    "japan": "JP",
    "india": "IN",
}


def parse(xlsx: Path) -> list[dict]:
    import openpyxl

    book = openpyxl.load_workbook(str(xlsx), read_only=True, data_only=True)
    sheet = book["Annex I"]
    rows = list(sheet.iter_rows(min_row=FIRST_DATA_ROW, values_only=True))
    book.close()

    out = []
    for row in rows:
        code = _text(row[0]).replace(" ", "")
        digits = re.sub(r"[^0-9]", "", code)
        if len(digits) < 9 or digits[:2] not in CHAPTERS:
            continue
        years = [_text(value) for value in row[3:24]]
        base = _text(row[2])
        remarks = _text(row[24])
        # A line with no base rate and no year cells is a heading banner.
        if not base and not any(years):
            continue
        out.append(
            {
                "market": "JP",
                "agreement": "RCEP",
                "code": digits,
                "hs6": digits[:6],
                "description": _text(row[1]),
                "base_rate_text": base,
                "staging": _staging(base, years),
                "years": years,
                "partner": _partner(remarks),
                "remarks": remarks,
                "source": "RCEP Annex I, Schedule of Tariff Commitments of Japan",
            }
        )
    return out


def _staging(base: str, years: list[str]) -> str:
    """One word for the shape of the schedule on this line."""
    filled = [value for value in years if value]
    if filled and all(value.upper() == "U" for value in filled):
        return "U"
    if filled and all(value.lower() == "free" for value in filled):
        return "FREE"
    return "SCHEDULE"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--xlsx", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    path = Path(args.xlsx)
    rows = parse(path)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=1, ensure_ascii=False)
    partners = {}
    for row in rows:
        partners[row["partner"]] = partners.get(row["partner"], 0) + 1
    print(json.dumps({
        "file": str(path),
        "sha256": sha256(path),
        "rows": len(rows),
        "partners": partners,
        "chapters": sorted({row["code"][:2] for row in rows}),
        "out": str(out),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
