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


def test_the_bundle_carries_the_second_state_of_the_key_material(bundle):
    # The page lets a reader swap one material line and watch the three markets
    # answer again.  The second state is not invented in the browser: it is the
    # engine's own answer, built here, and the page compares what it computes
    # with this report.  So the two have to be the same shipment but for that
    # one line, and the three markets have to move.
    case = next(item for item in bundle["cases"] if item.get("toggle"))
    toggle = case["toggle"]
    filed = case["shipment"]["materials"]
    swapped = toggle["shipment"]["materials"]
    assert len(filed) == len(swapped)
    changed = []
    for before, after in zip(filed, swapped):
        if before != after:
            changed.append(after["id"])
            assert before["id"] == toggle["change"]["id"]
    assert changed == [toggle["material"]]
    assert toggle["shipment"]["goods"] == case["shipment"]["goods"]

    before = {block["market"]: block for block in case["report"]["markets"]}
    after = {block["market"]: block for block in toggle["report"]["markets"]}
    assert set(before) == {"US", "EU", "JP"}
    for market in before:
        assert after[market]["origin"]["verdict"] != before[market]["origin"]["verdict"], market
        assert after[market]["duty"]["amount"] != before[market]["duty"]["amount"], market


def test_the_reading_carries_what_the_engine_read_out_of_each_rule(bundle):
    # The page re-evaluates a rule in the browser.  The alternatives are this
    # repository's reading of the rule sentence, so they travel with the page
    # rather than being re-parsed by a second parser in JavaScript.
    for case in bundle["cases"]:
        reading = case.get("reading") or {}
        assert set(reading.get("parties", {})) == {"US", "EU", "JP"}, case["id"]
        for market in ("US", "EU", "JP"):
            assert reading["parties"][market], case["id"]
            assert "KR" in reading["parties"][market], case["id"]
        for market, alternatives in (reading.get("alternatives") or {}).items():
            if reading["rules"].get(market):
                assert alternatives, "%s has a rule but no alternative" % case["id"]
                for alternative in alternatives:
                    assert set(alternative) >= {"text", "kinds", "rvc_down", "rvc_up", "weight_min"}


def test_the_readme_quotes_the_hash_of_the_committed_store(bundle):
    # A judge can hash the rule file and compare it with the number the page and
    # the README print.  Keeping the number in one place and the file in another
    # is only useful if they are checked against each other.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    digest = store.file_sha256(str(STORE))
    assert digest == bundle["store"]["sha256"]
    assert digest in readme
    assert "%d bytes" % os.path.getsize(STORE) in readme.replace(",", "")
