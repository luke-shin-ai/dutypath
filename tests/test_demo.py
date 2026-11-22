"""The judgement screen's bundle.

The committed bundle is what the engine produces now, so the page cannot show
an older answer than the snapshot holds.  The page's own rate arithmetic is
checked against ``duty.line_rate`` in ``scripts/check_demo.py``, which needs a
browser: keeping that comparison here would make a bare ``pytest`` run skip it,
and a check that sometimes does not run is not a check this suite can claim.

The two tests below need no browser and no network, so they run everywhere.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dutypath import store  # noqa: E402

BUNDLE = ROOT / "docs" / "demo" / "dutypath-demo.json"
DEMO = ROOT / "docs" / "demo" / "index.html"
STORE = ROOT / "store" / "dutypath-rules.rl"


@pytest.fixture(scope="module")
def bundle() -> dict:
    return json.loads(BUNDLE.read_text(encoding="utf-8"))


def test_the_committed_bundle_matches_the_engine(tmp_path):
    out = tmp_path / "bundle.json"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    subprocess.run(
        [sys.executable, "scripts/build_demo.py", "--store", str(STORE), "--out", str(out)],
        cwd=str(ROOT), check=True, capture_output=True, env=env,
    )
    fresh = json.loads(out.read_text(encoding="utf-8"))
    committed = json.loads(BUNDLE.read_text(encoding="utf-8"))
    assert fresh["snapshot"] == committed["snapshot"]
    assert fresh["store"]["sha256"] == committed["store"]["sha256"]
    assert fresh["rates"] == committed["rates"]
    assert [case["id"] for case in fresh["cases"]] == [case["id"] for case in committed["cases"]]
    assert fresh["cases"] == committed["cases"]


def test_the_bundle_names_the_store_it_was_built_from(bundle):
    assert bundle["store"]["sha256"] == store.file_sha256(str(STORE))
    assert bundle["store"]["bytes"] == os.path.getsize(STORE)


def test_the_bundle_carries_every_fixture_and_benchmark_good(bundle):
    ids = {case["id"] for case in bundle["cases"]}
    assert {"SHP-2026-1201-001", "SHP-2026-1201-005"} <= ids
    assert len([value for value in ids if value.startswith("GOLD-")]) == 12
