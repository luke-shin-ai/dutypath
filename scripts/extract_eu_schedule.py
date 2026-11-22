"""Extract the European Union's tariff schedule from the Korea-EU FTA annex.

The source is the EU Party's tariff schedule in Annex 2-A of the Korea-EU Free
Trade Agreement, as published by the Korean government's FTA portal together
with the Korean-language version of the same schedule.  The Korean PDF carries
a real text layer and a fixed five-column table, so the rows are read by column
position rather than by guessing from running text:

    CN2007 code | description | base rate | staging category | entry price

The English PDF of the same schedule uses an embedded subset font with no
Unicode mapping, which is why the Korean copy is the one parsed here.  The two
files are the same table; the sha256 of both is recorded in docs/SOURCES.md.

What is written out:

    market, agreement, cn8, description, base_rate_text, base_rate_percent,
    base_rate_kind, staging, source

Rows whose base rate or staging category cannot be read from the table are not
written at all: the store says "not in snapshot" for those lines rather than
carrying a number nothing supports.

Usage:
    python scripts/extract_eu_schedule.py --pdf <eu schedule, Korean>.pdf \
        --out data/extract-2026-11-22/eukor_rates.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

# Column x positions in the Korean schedule, read off the table rule lines.
CODE_RIGHT = 125.0        # code column ends here
DESCRIPTION_LEFT = 126.0  # description column starts here
RATE_LEFT = 320.0         # base rate column
RATE_RIGHT = 405.0
CATEGORY_LEFT = 405.0     # staging category column
CATEGORY_RIGHT = 462.0

CHAPTERS = ("39", "84", "85")

CODE_LINE = re.compile(r"^(\d{4}) (\d{2}) (\d{2})$")
HEADING_LINE = re.compile(r"^(\d{4})$")
SUBHEADING_LINE = re.compile(r"^(\d{4}) (\d{2})$")
RATE_TEXT = re.compile(r"^(Free|\d+(?:,\d+)?(?:\s*\+\s*\d+(?:,\d+)?)?)$")
CATEGORY_TEXT = re.compile(r"^(\d{1,2}(?:-[A-Z])?|[A-Z](?:-[A-Z])?)$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _column(word) -> str | None:
    x0, x1 = word[0], word[2]
    if x1 <= CODE_RIGHT:
        return "code"
    if RATE_LEFT <= x0 < RATE_RIGHT:
        return "rate"
    if CATEGORY_LEFT <= x0 < CATEGORY_RIGHT:
        return "category"
    if x0 >= DESCRIPTION_LEFT:
        return "description"
    return None


def _rows(page) -> list[dict]:
    """Group the words of one page into text rows by their vertical position."""
    buckets: dict[float, list] = {}
    for word in page.get_text("words"):
        y = round(word[1], 1)
        key = None
        for existing in buckets:
            if abs(existing - y) < 2.5:
                key = existing
                break
        buckets.setdefault(key if key is not None else y, []).append(word)
    rows = []
    for y in sorted(buckets):
        words = sorted(buckets[y], key=lambda item: item[0])
        cells: dict[str, list[str]] = {"code": [], "rate": [], "category": [], "description": []}
        for word in words:
            column = _column(word)
            if column:
                cells[column].append(word[4])
        rows.append({name: " ".join(value).strip() for name, value in cells.items()})
    return rows


def parse(pdf_path: Path) -> tuple[list[dict], dict]:
    """Read every line of the EU schedule in chapters 39, 84 and 85."""
    import pymupdf

    document = pymupdf.open(str(pdf_path))
    out: list[dict] = []
    stats = {"pages": document.page_count, "code_rows": 0, "skipped": 0}
    pending: dict | None = None

    def close(row: dict | None) -> None:
        nonlocal pending
        if row is None:
            return
        if not row.get("rate") or not row.get("category"):
            stats["skipped"] += 1
            pending = None
            return
        code = row["code"].replace(" ", "")
        if not code.startswith(CHAPTERS):
            pending = None
            return
        stats["code_rows"] += 1
        out.append(
            {
                "market": "EU",
                "agreement": "EUKOR",
                "cn8": code,
                "description": row.get("description", ""),
                "base_rate_text": row["rate"],
                "base_rate_percent": _percent(row["rate"]),
                "base_rate_kind": "percent" if _percent(row["rate"]) is not None else "specific",
                "staging": row["category"],
                "source": "EU tariff schedule, Annex 2-A (EU Party)",
            }
        )
        pending = None

    for page_index in range(document.page_count):
        for row in _rows(document[page_index]):
            code_cell = row["code"]
            if CODE_LINE.match(code_cell):
                close(pending)
                pending = row
                continue
            if not code_cell:
                if pending is not None:
                    # A continuation line of the row above: fill a column the
                    # first line did not carry.
                    if not pending["rate"] and row["rate"]:
                        pending["rate"] = row["rate"]
                    if not pending["category"] and row["category"]:
                        pending["category"] = row["category"]
                continue
            # A heading or subheading line with no tariff line of its own.
            close(pending)
    close(pending)
    return out, stats


def _percent(text: str) -> float | None:
    value = text.replace(" ", "")
    if value.lower() == "free":
        return 0.0
    if "+" in value:
        return None
    match = re.match(r"^\d+(?:,\d+)?$", value)
    if not match:
        return None
    return float(value.replace(",", "."))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    path = Path(args.pdf)
    rows, stats = parse(path)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=1, ensure_ascii=False)
    print(json.dumps({
        "file": str(path),
        "sha256": sha256(path),
        "rows": len(rows),
        **stats,
        "categories": sorted({row["staging"] for row in rows}),
        "out": str(out),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
