"""Build the EU product specific rules from the Korea-EU rules of origin annex.

The rules are read from Annex II of the Protocol concerning the definition of
'originating products' in the Korea-EU Free Trade Agreement.  The annex prints
three columns - heading, description, and the working or processing that
confers origin, with a second rule in a fourth column - so a line can offer two
alternatives and meets the rule when either holds.

The table is transcribed here rather than parsed: the PDF lays the columns out
as running text, and a parser that guesses which words belong to which column
would put a rule on the wrong heading without saying so.  Each transcription
is checked against the document instead: the script fails unless the heading
code and every rule sentence it claims are on the same page of the PDF.  That
check catches a mistyped sentence and a rule attributed to the wrong heading
whose neighbour prints different words.

The rule sentences are the annex's own words.  Two shapes cover the chapters in
this snapshot:

    CTH          manufacture from materials of any heading, except that of the
                 product
    MaxNOM n     the value of all the materials used does not exceed n percent
                 of the ex-works price

MaxNOM is stored as a build down floor, 100 - n, because the engine computes
the regional value content as (value - non originating materials) / value.

Usage:
    python scripts/build_eukor_psr.py --pdf <rules of origin protocol>.pdf \
        --out data/extract-2026-11-22/eukor_psr.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

CTH = "Manufacture from materials of any heading, except that of the product"
ANY = "Manufacture from materials of any heading"
MAXNOM = "Manufacture in which the value of all the materials used does not exceed %d%% of the ex-works price of the product"

# (code_from, code_to, level, page hint, alternatives)
# Alternatives are ("CTH",), ("ANY",), ("MAXNOM", n) or a tuple of them.
ROWS = [
    # Chapter 39
    ("3901", "3921", "range", 43, (("CTH",), ("MAXNOM", 25))),
    ("3907.30", "3907.40", "subheading", 43, (("ANY",),)),
    ("3907.20", "3907.91", "subheading", 43, (("ANY",),)),
    ("3922", "3926", "range", 43, (("MAXNOM", 50),)),
    # Chapter 84 default
    ("84", "84", "chapter", 71, (("CTH",), ("MAXNOM", 50))),
    ("8401", "8401", "heading", 71, (("CTH",), ("MAXNOM", 45))),
    ("8404", "8404", "heading", 71, (("CTH",), ("MAXNOM", 45))),
    ("8407", "8407", "heading", 71, (("MAXNOM", 50),)),
    ("8408", "8408", "heading", 71, (("MAXNOM", 50),)),
    ("8423", "8423", "heading", 72, (("CTH",), ("MAXNOM", 45))),
    ("8425", "8425", "heading", 72, (("CTH",), ("MAXNOM", 45))),
    ("8426", "8426", "heading", 72, (("CTH",), ("MAXNOM", 45))),
    ("8427", "8427", "heading", 72, (("MAXNOM", 50),)),
    ("8428", "8428", "heading", 72, (("CTH",), ("MAXNOM", 45))),
    ("8429", "8429", "heading", 72, (("CTH",), ("MAXNOM", 45))),
    ("8430", "8430", "heading", 72, (("CTH",), ("MAXNOM", 45))),
    ("8432", "8432", "heading", 72, (("CTH",), ("MAXNOM", 45))),
    ("8433", "8433", "heading", 72, (("CTH",), ("MAXNOM", 45))),
    ("8434", "8434", "heading", 72, (("CTH",), ("MAXNOM", 45))),
    ("8443", "8443", "heading", 73, (("MAXNOM", 45),)),
    ("8444", "8444", "heading", 73, (("CTH",), ("MAXNOM", 45))),
    ("8445", "8445", "heading", 73, (("CTH",), ("MAXNOM", 45))),
    ("8446", "8446", "heading", 73, (("CTH",), ("MAXNOM", 45))),
    ("8447", "8447", "heading", 73, (("CTH",), ("MAXNOM", 45))),
    ("8456", "8456", "heading", 73, (("CTH",), ("MAXNOM", 45))),
    ("8457", "8457", "heading", 73, (("CTH",), ("MAXNOM", 45))),
    ("8458", "8458", "heading", 73, (("CTH",), ("MAXNOM", 45))),
    ("8459", "8459", "heading", 73, (("CTH",), ("MAXNOM", 45))),
    ("8460", "8460", "heading", 74, (("CTH",), ("MAXNOM", 45))),
    ("8461", "8461", "heading", 74, (("CTH",), ("MAXNOM", 45))),
    ("8462", "8462", "heading", 74, (("CTH",), ("MAXNOM", 45))),
    ("8463", "8463", "heading", 74, (("CTH",), ("MAXNOM", 45))),
    ("8464", "8464", "heading", 74, (("CTH",), ("MAXNOM", 45))),
    ("8465", "8465", "heading", 74, (("CTH",), ("MAXNOM", 45))),
    ("8466", "8466", "heading", 74, (("CTH",), ("MAXNOM", 45))),
    ("8467", "8467", "heading", 74, (("CTH",), ("MAXNOM", 45))),
    ("8469", "8469", "heading", 75, (("CTH",), ("MAXNOM", 45))),
    ("8470", "8470", "heading", 75, (("CTH",), ("MAXNOM", 45))),
    ("8471", "8471", "heading", 75, (("CTH",), ("MAXNOM", 45))),
    ("8474", "8474", "heading", 75, (("CTH",), ("MAXNOM", 45))),
    ("8480", "8480", "heading", 75, (("CTH",), ("MAXNOM", 45))),
    # Chapter 85 default
    ("85", "85", "chapter", 75, (("CTH",), ("MAXNOM", 45))),
    ("8504", "8504", "heading", 75, (("MAXNOM", 45),)),
    ("8505", "8505", "heading", 76, (("CTH",), ("MAXNOM", 50))),
    ("8508", "8508", "heading", 76, (("CTH",), ("MAXNOM", 50))),
    ("8509", "8509", "heading", 76, (("CTH",), ("MAXNOM", 50))),
    ("8511", "8511", "heading", 76, (("CTH",), ("MAXNOM", 50))),
    ("8512", "8512", "heading", 76, (("CTH",), ("MAXNOM", 50))),
    ("8514", "8514", "heading", 76, (("CTH",), ("MAXNOM", 50))),
    ("8515", "8515", "heading", 76, (("CTH",), ("MAXNOM", 50))),
    ("8516", "8516", "heading", 77, (("CTH",), ("MAXNOM", 50))),
    ("8519", "8519", "heading", 77, (("MAXNOM", 50),)),
    ("8521", "8521", "heading", 77, (("MAXNOM", 45),)),
    ("8523", "8523", "heading", 77, (("MAXNOM", 50),)),
    ("8525", "8525", "heading", 77, (("MAXNOM", 50),)),
    ("8526", "8526", "heading", 77, (("MAXNOM", 50),)),
    ("8527", "8527", "heading", 77, (("MAXNOM", 45),)),
    ("8528", "8528", "heading", 77, (("MAXNOM", 45),)),
    ("8529", "8529", "heading", 78, (("MAXNOM", 50),)),
    ("8530", "8530", "heading", 78, (("CTH",), ("MAXNOM", 50))),
    ("8531", "8531", "heading", 78, (("CTH",), ("MAXNOM", 50))),
    ("8536", "8536", "heading", 78, (("CTH",), ("MAXNOM", 50))),
    ("8538", "8538", "heading", 78, (("CTH",), ("MAXNOM", 50))),
    ("8539", "8539", "heading", 78, (("CTH",), ("MAXNOM", 50))),
    ("8540", "8540", "heading", 78, (("MAXNOM", 45),)),
    ("8542.31", "8542.39", "range", 78, (("CTH",), ("MAXNOM", 45))),
    ("8544", "8544", "heading", 79, (("MAXNOM", 50),)),
    ("8545", "8545", "heading", 79, (("CTH",), ("MAXNOM", 50))),
    ("8546", "8546", "heading", 79, (("MAXNOM", 45),)),
    ("8547", "8547", "heading", 79, (("MAXNOM", 45),)),
    ("8548", "8548", "heading", 79, (("MAXNOM", 45),)),
]


def flatten(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalise(value: str, high: bool) -> str:
    """The bottom or top of the interval a code names, in one code space."""
    digits = re.sub(r"[^0-9]", "", value)
    if not digits:
        return ""
    return digits.ljust(8, "9" if high else "0")[:8]


def sentence(spec: tuple) -> str:
    if spec[0] == "CTH":
        return CTH
    if spec[0] == "ANY":
        return ANY
    return MAXNOM % spec[1]


def row_text(alternatives) -> str:
    return "; or ".join(sentence(spec) for spec in alternatives)


def structured(alternatives) -> list[dict]:
    out = []
    for spec in alternatives:
        if spec[0] == "CTH":
            out.append({"text": CTH, "kinds": ["CTH"], "rvc_down": None})
        elif spec[0] == "ANY":
            out.append({"text": ANY, "kinds": ["CTH"], "rvc_down": None})
        else:
            out.append({"text": MAXNOM % spec[1], "kinds": [], "rvc_down": 100.0 - spec[1]})
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    import pymupdf

    document = pymupdf.open(args.pdf)
    pages = [flatten(page.get_text()) for page in document]
    failures = []
    rows = []
    for code_from, code_to, level, page_hint, alternatives in ROWS:
        haystack = pages[page_hint] if page_hint < len(pages) else ""
        checks = [sentence(spec) for spec in alternatives]
        if level == "chapter":
            checks.append("Chapter %s" % code_from)
        else:
            token = code_from.replace(".", " ") if "." in code_from else code_from
            checks.append(token)
        for value in checks:
            if flatten(value) not in haystack:
                failures.append({"code": code_from, "page": page_hint, "missing": value[:70]})
        rows.append(
            {
                "agreement": "EUKOR",
                "level": level,
                "code_from": code_from,
                "code_to": code_to,
                "from_norm": normalise(code_from, False),
                "to_norm": normalise(code_to, True),
                "text": row_text(alternatives),
                "alternatives": structured(alternatives),
                "kinds": sorted({kind for spec in structured(alternatives) for kind in spec["kinds"]}),
                "rvc_build_down": max(
                    [spec["rvc_down"] or 0.0 for spec in structured(alternatives)] + [0.0]
                ),
                "rvc_build_up": None,
                "excluded_from": [],
                "group_exclude": [],
                "originating_weight_min": None,
                "structured": True,
                "source": "Korea-EU FTA, Protocol on rules of origin, Annex II",
                "source_page": page_hint,
            }
        )

    if failures:
        print(json.dumps({"failures": failures}, indent=2))
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=1, ensure_ascii=False)
    print(json.dumps({
        "file": args.pdf,
        "sha256": sha256(Path(args.pdf)),
        "rows": len(rows),
        "verified_against_pages": len({row["source_page"] for row in rows}),
        "out": str(out),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
