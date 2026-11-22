"""Fetch the applied MFN rate of the United States for a few six digit lines.

WITS carries the TRAINS applied tariff data.  Two things about it matter for
this snapshot:

* the value is a simple average over the tariff lines inside the six digit
  code, which is why the number of lines travels with the value, and
* when that count is one the average is the line's own rate, and only then is
  the number usable as a rate for a shipment.

Usage:
    python scripts/fetch_mfn.py --out data/extract-2026-11-22/us_mfn_applied.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess

CODES = [
    "850110", "850131", "850431", "850440", "850760", "850790",
    "853222", "853400", "854442", "392690", "847330", "847989",
]
URL = (
    "https://wits.worldbank.org/API/V1/SDMX/V21/datasource/TRN/reporter/{reporter}"
    "/partner/000/product/{code}/year/{year}/datatype/reported"
)
FIELDS = ("OBS_VALUE", "TOTALNOOFLINES", "MIN_RATE", "MAX_RATE", "TIME_PERIOD", "NOMENCODE")


def fetch(code: str, reporter: str = "840", year: int = 2023) -> dict | None:
    url = URL.format(reporter=reporter, code=code, year=year)
    completed = subprocess.run(
        ["curl", "-s", "-m", "40", "-A", "Mozilla/5.0", url], capture_output=True, text=True
    )
    match = re.search(r"<Obs ([^>]*)/>", completed.stdout)
    if not match:
        return None
    attributes = dict(re.findall(r'(\w+)="([^"]*)"', match.group(1)))
    return {key: attributes.get(key) for key in FIELDS}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    payload = {}
    for code in CODES:
        row = fetch(code)
        if row:
            payload[code] = row
            print(code, row["OBS_VALUE"], "lines", row["TOTALNOOFLINES"])
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
