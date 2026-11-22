"""Extract the public rule material this snapshot is built from.

Everything the store contains comes out of documents a reader can open:

  KORUS Annex 6-A      product specific rules of origin (chapters 39, 84, 85)
  KORUS Annex 2-B      tariff schedule of the United States: HTS8, base rate,
                       staging category (chapters 39, 84, 85)
  KORUS Chapter 2      Annex 2-B: what each staging category means
  RCEP Annex 3A HS2022 product specific rules (chapters 39, 84, 85)

The script writes one JSON file per source plus meta.json under data/.  The
PDFs are not committed; SOURCES.md records the URL, the download date and the
sha256 of each file so the extraction can be repeated and checked.

Usage:
    python scripts/extract_sources.py --pdf-dir /path/to/pdfs --out data/extract-2026-11-22
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

CHAPTERS = ("39", "84", "85")

# Staging categories as written in Annex 2-B paragraph 1 of chapter 2.
STAGING_TEXT = {
    "A": "eliminated entirely on the date this Agreement enters into force",
    "B": "removed in two equal annual stages, duty-free January 1 of year two",
    "C": "removed in three equal annual stages, duty-free January 1 of year three",
    "D": "removed in five equal annual stages, duty-free January 1 of year five",
    "E": "removed in six equal annual stages, duty-free January 1 of year six",
    "F": "removed in seven equal annual stages, duty-free January 1 of year seven",
    "G": "removed in ten equal annual stages, duty-free January 1 of year ten",
    "H": "removed in 15 equal annual stages, duty-free January 1 of year 15",
    "I": "reduced by percentages of the base rate, duty-free January 1 of year ten",
    "J": "base rate through year eight, then four equal stages, duty-free January 1 of year 12",
    "K": "continues to receive duty-free treatment",
}

# Equal stage counts, from Annex 2-B paragraph 1 (a) to (k).
EQUAL_STAGES = {"A": 1, "B": 2, "C": 3, "D": 5, "E": 6, "F": 7, "G": 10, "H": 15}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pdf_text(path: Path) -> str:
    import pypdf

    reader = pypdf.PdfReader(str(path))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return "\n".join(pages)


def normalise(text: str) -> str:
    """Unify the dash characters the PDFs use and drop page headers."""
    for dash in ("\u2013", "\u2014", "\u2212"):
        text = text.replace(dash, "-")
    return re.sub(r"(?m)^\s*\d+-\d+\s*$", "", text)


# ---------------------------------------------------------------- KORUS 6-A

CODE_LINE = re.compile(
    r"^\s*("
    r"\d{4}\.\d{2}\s*-\s*\d{4}\.\d{2}"      # 8401.10 - 8401.30
    r"|\d{4}\.\d{2}\s*-\s*\d{4}"             # 8401.10 - 8401
    r"|\d{2}\.\d{2}\s*-\s*\d{2}\.\d{2}"      # 84.01 - 84.02
    r"|\d{4}\.\d{2}"                          # 8401.10
    r"|\d{2}\.\d{2}"                          # 84.01
    r"|\d{4}"                                 # 8401
    r")\s*$"
)


def parse_korus_psr(text: str) -> list[dict]:
    """Split Annex 6-A into (code block, rule text) rows for our chapters."""
    text = normalise(text.replace("\f", "\n"))
    lines = [line.rstrip() for line in text.split("\n")]
    starts = []
    for index, line in enumerate(lines):
        match = CODE_LINE.match(line)
        if not match:
            continue
        code = re.sub(r"\s+", "", match.group(1))
        starts.append((index, code))
    rows = []
    for position, (index, code) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        body = [line.strip() for line in lines[index + 1 : end] if line.strip()]
        rule = re.sub(r"\s+", " ", " ".join(body)).strip()
        if not rule:
            continue
        first = re.sub(r"[^0-9]", "", code)[:2]
        if first not in CHAPTERS:
            continue
        if "-" in code:
            code_from, code_to = [part.strip() for part in code.split("-")]
            level = "range"
        else:
            code_from = code_to = code
            if "." not in code:
                level = "heading"
            elif len(code) == 5:
                level = "heading"
            else:
                level = "subheading"
        rows.append(
            {
                "agreement": "KORUS",
                "level": level,
                "code_from": code_from,
                "code_to": code_to,
                "text": rule,
                "source": "KORUS Annex 6-A",
            }
        )
    return rows


# ---------------------------------------------------------------- KORUS 2-B

RATE_LINE = re.compile(r"^(\d{8})\s+(.+)$")
RATE_TAIL = re.compile(
    r"\s+((?:Free)|(?:[\d.]+%)|(?:\$[\d.,]+/?\w*)|(?:[\d.]+ ?cents?[^%]*?))\s+([A-Z]{1,2})$"
)


def parse_rate(value: str):
    value = value.strip()
    if value.lower() == "free":
        return 0.0, "percent"
    match = re.fullmatch(r"([\d.]+)%", value)
    if match:
        return float(match.group(1)), "percent"
    return None, "specific"


def parse_korus_schedule(text: str) -> list[dict]:
    """HTS8, description, base rate, staging category for our chapters."""
    text = normalise(text.replace("\f", "\n"))
    rows = []
    for line in text.split("\n"):
        line = line.strip()
        match = RATE_LINE.match(line)
        if not match:
            continue
        hts8, rest = match.groups()
        if hts8[:2] not in CHAPTERS:
            continue
        tail = RATE_TAIL.search(rest)
        if not tail:
            continue
        rate_text = tail.group(1).strip()
        staging = tail.group(2).strip()
        description = rest[: tail.start()].strip()
        if not description:
            continue
        percent, kind = parse_rate(rate_text)
        rows.append(
            {
                "market": "US",
                "agreement": "KORUS",
                "hts8": hts8,
                "description": description,
                "base_rate_text": rate_text,
                "base_rate_percent": percent,
                "base_rate_kind": kind,
                "staging": staging,
                "source": "KORUS Annex 2-B, tariff schedule of the United States",
            }
        )
    return rows


# ---------------------------------------------------------------- RCEP 3A

RCEP_RULE = re.compile(
    r"((?:CTH|CTSH|CC|WO|CR|RVC\d{2}(?:/\d{2})?|"
    r"Assembly of semi ?conductor products|Chemical reaction|PE|SP|As specified for split headings)"
    r"(?:\s*(?:,|or|and)\s*(?:CTH|CTSH|CC|WO|CR|RVC\d{2}(?:/\d{2})?|"
    r"Assembly of semi ?conductor products|Chemical reaction|PE|SP|As specified for split headings))*)"
)
RCEP_STANDALONE = re.compile(r"^(?:%s)$" % RCEP_RULE.pattern)
RCEP_HEADING = re.compile(r"^(\d{2}\.\d{2})\s*(?:(\d{4}\.\d{2})\s*)?(.*)$")


def parse_rcep_psr(text: str) -> list[dict]:
    """Heading level rules from Annex 3A for our chapters.

    Annex 3A is a table: chapter | heading | subheading | description | rule.
    Text extraction interleaves the columns.  A rule therefore ends the line
    that starts with a heading number, or sits alone on the line after it.
    """
    text = normalise(text.replace("\f", "\n"))
    rows = []
    pending = None
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        match = RCEP_HEADING.match(line)
        if match and match.group(1)[:2] not in CHAPTERS:
            pending = None
            continue
        if re.match(r"^\d{2}\s+CHAPTER", line) or line.upper().startswith("SECTION"):
            pending = None
            continue
        if match:
            heading, subheading, rest = match.groups()
            rest = rest.strip()
            trailing = None
            for candidate in RCEP_RULE.finditer(rest):
                if candidate.end() == len(rest):
                    trailing = candidate.group(1).strip()
            if trailing:
                description = rest[: rest.rfind(trailing)].strip(" ,")
                rows.append(
                    {
                        "agreement": "RCEP",
                        "level": "subheading" if subheading else "heading",
                        "code_from": subheading or heading,
                        "code_to": subheading or heading,
                        "text": trailing,
                        "description": description,
                        "source": "RCEP Annex 3A (HS 2022)",
                    }
                )
                pending = None
            else:
                pending = {
                    "agreement": "RCEP",
                    "level": "heading",
                    "code_from": heading,
                    "code_to": heading,
                    "description": rest,
                    "source": "RCEP Annex 3A (HS 2022)",
                }
            continue
        if pending is not None:
            match_rule = RCEP_STANDALONE.match(line)
            if match_rule:
                pending["text"] = match_rule.group(1).strip()
                rows.append(pending)
                pending = None

    # A wrapped row can be picked up twice; keep the longest rule text per code.
    best = {}
    for row in rows:
        key = (row["agreement"], row["code_from"], row["code_to"])
        if key not in best or len(row["text"]) > len(best[key]["text"]):
            best[key] = row
    return list(best.values())


# ---------------------------------------------------------------- rules -> fields

def normalise_code_low(code: str) -> str:
    digits = re.sub(r"[^0-9]", "", code)
    if len(digits) <= 6:
        return digits.ljust(8, "0")
    return digits[:8]


def normalise_code(code: str) -> str:
    """One comparison space for every level of the nomenclature.

    Digits only, padded to eight characters, so a heading range, a subheading
    range and a tariff line can be compared with plain string ordering:
    39.16 becomes 39169999, 8501.20 becomes 85012099, 85012040 stays itself.
    """
    digits = re.sub(r"[^0-9]", "", code)
    if len(digits) <= 4:
        return digits.ljust(8, "9")
    if len(digits) <= 6:
        return digits.ljust(8, "9")
    return digits[:8]


def describe_rule(text: str, code_from: str = "", code_to: str = "") -> dict:
    """Pull the machine readable pieces out of a rule sentence.

    Nothing is inferred beyond what the sentence says.  A sentence the parser
    cannot structure is kept with kind ``UNSTRUCTURED`` so the engine can say
    so instead of guessing.
    """
    result = {
        "kinds": [],
        "excluded_from": [],
        "group_exclude": [],
        "rvc_build_down": None,
        "rvc_build_up": None,
        "originating_weight_min": None,
        "unstructured": False,
    }
    lowered = text.lower()

    tokens = {token.upper().replace(" ", "") for token in re.findall(r"[A-Z]{2,4}\d{0,2}", text)}
    if "CTH" in tokens:
        result["kinds"].append("CTH")
    if "CTSH" in tokens:
        result["kinds"].append("CTSH")
    if "CC" in tokens:
        result["kinds"].append("CC")
    if "WO" in tokens or "wholly obtained" in lowered:
        result["kinds"].append("WO")
    if "CR" in tokens or "chemical reaction" in lowered:
        result["kinds"].append("CR")
    if "assemblyofsemiconductorproducts" in tokens or "assembly of semi conductor products" in lowered:
        result["kinds"].append("ASSEMBLY")

    if "change to subheading" in lowered and "from any other chapter" in lowered:
        result["kinds"].append("CC")
    if "from any other heading" in lowered:
        result["kinds"].append("CTH")
    if "from any other subheading" in lowered:
        result["kinds"].append("CTSH")
    if "outside subheading" in lowered or "outside that group" in lowered:
        result["kinds"].append("CTSH")
        match = re.search(r"outside (?:subheadings? )?(\d{4}\.\d{2})(?: through | - |-)(\d{4}\.\d{2})", lowered)
        if match:
            result["group_exclude"] = [match.group(1), match.group(2)]
        elif code_from and code_to:
            result["group_exclude"] = [code_from, code_to]

    for value in re.findall(r"rvc\s?(\d{2})(?:/(\d{2}))?", lowered):
        result["rvc_build_down"] = float(value[0])
        if value[1]:
            result["rvc_build_up"] = float(value[1])
    if "regional value content" in lowered or "value added" in lowered:
        down = re.search(r"(\d{2}) percent under the build-down", lowered)
        up = re.search(r"(\d{2}) percent under the build-up", lowered)
        single = re.search(r"regional value content of not less than (\d{2}) percent", lowered)
        if down:
            result["rvc_build_down"] = float(down.group(1))
        if up:
            result["rvc_build_up"] = float(up.group(1))
        if single and not (down or up):
            result["rvc_build_down"] = float(single.group(1))
        added = re.search(r"(\d{2})\s?% value added", lowered)
        if added:
            result["rvc_build_down"] = result["rvc_build_down"] or float(added.group(1))
        result["kinds"].append("RVC")
    if result.get("rvc_build_down") or result.get("rvc_build_up"):
        result["kinds"].append("RVC")

    for match in re.finditer(r"except from (?:headings?|subheadings?|chapters?) ([\d., andor-]+)", lowered):
        for token in re.findall(r"\d{4}(?:\.\d{2})?", match.group(1)):
            result["excluded_from"].append(token.replace(".", ""))
    for match in re.finditer(r"outside that group", lowered):
        pass

    result["kinds"] = sorted(set(result["kinds"]))
    weight = re.search(
        r"originating polymer content.{0,140}?not less than (\d{2}) percent by weight", lowered
    )
    if weight:
        result["originating_weight_min"] = float(weight.group(1))
    if not result["kinds"]:
        result["unstructured"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    pdf_dir = Path(args.pdf_dir)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    files = {
        "korus_annex_6a": "korus_annex6a.pdf",
        "korus_annex_2b": "korus_annex2b_us.pdf",
        "korus_chapter2": "korus_ch2.pdf",
        "rcep_annex_3a": "rcep_annex3a.pdf",
    }
    texts = {}
    digests = {}
    for key, name in files.items():
        path = pdf_dir / name
        texts[key] = pdf_text(path)
        digests[key] = {"file": name, "sha256": sha256(path), "bytes": os.path.getsize(path)}

    korus_rules = parse_korus_psr(texts["korus_annex_6a"])
    rate_rows = parse_korus_schedule(texts["korus_annex_2b"])
    rcep_rules = parse_rcep_psr(texts["rcep_annex_3a"])

    for row in korus_rules + rcep_rules:
        row.update(describe_rule(row["text"], row["code_from"], row["code_to"]))
        row["from_norm"] = normalise_code_low(row["code_from"])
        row["to_norm"] = normalise_code(row["code_to"])

    (out / "korus_psr.json").write_text(json.dumps(korus_rules, indent=1, ensure_ascii=False))
    (out / "korus_rates.json").write_text(json.dumps(rate_rows, indent=1, ensure_ascii=False))
    (out / "rcep_psr.json").write_text(json.dumps(rcep_rules, indent=1, ensure_ascii=False))
    (out / "staging.json").write_text(json.dumps(STAGING_TEXT, indent=1, ensure_ascii=False))
    (out / "meta.json").write_text(
        json.dumps(
            {
                "extracted_on": "2026-11-22",
                "chapters": list(CHAPTERS),
                "files": digests,
                "counts": {
                    "korus_psr": len(korus_rules),
                    "korus_rates": len(rate_rows),
                    "rcep_psr": len(rcep_rules),
                },
            },
            indent=1,
            ensure_ascii=False,
        )
    )
    print(json.dumps(json.loads((out / "meta.json").read_text())["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
