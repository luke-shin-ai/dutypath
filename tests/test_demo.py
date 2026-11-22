"""The judgement screen's bundle and the arithmetic it does in the browser.

Two checks:

* the committed bundle is what the engine produces now, so the page cannot show
  an older answer than the snapshot holds,
* the page's own rate function agrees with ``duty.line_rate`` for every rate row
  in the bundle on a range of dates, year by year across each schedule.  That
  is the only logic the page duplicates, so it is the only logic tested here.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dutypath import duty, store  # noqa: E402

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


def _library_path() -> None:
    import ctypes.util

    if ctypes.util.find_library("nspr4"):
        return
    for candidate in (
        Path("/workspace/.sysroot/usr/lib/x86_64-linux-gnu"),
        Path("/workspace/.sysroot/lib/x86_64-linux-gnu"),
    ):
        if (candidate / "libnspr4.so").exists():
            current = os.environ.get("LD_LIBRARY_PATH", "")
            os.environ["LD_LIBRARY_PATH"] = str(candidate) + (":" + current if current else "")
            return


def test_the_page_rate_function_agrees_with_the_engine(bundle):
    pytest.importorskip("playwright.sync_api")
    _library_path()
    from playwright.sync_api import Error, sync_playwright

    try:
        with sync_playwright() as playwright:
            playwright.chromium.launch().close()
    except Error as error:  # no browser in this environment
        pytest.skip("chromium is not available: %s" % str(error).splitlines()[0])

    connection = store.connect(str(STORE), read_only=True)
    connection.autocommit = False
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.goto(DEMO.as_uri())
            page.wait_for_selector(".market")
            dates = ["2011-06-30", "2011-07-01", "2012-03-15", "2016-01-01", "2022-01-01",
                     "2026-12-01", "2031-01-01"]
            mismatches = []
            for key, row in bundle["rates"].items():
                market = row["market"]
                agreement = row["agreement"]
                for on in dates:
                    python_value = duty.line_rate(
                        connection, market, agreement, row["code"], date.fromisoformat(on)
                    )["percent"]
                    js_value = page.evaluate(
                        "([row, on]) => window.dutypathRate(row, on)", [row, on]
                    )
                    if python_value is None and js_value is None:
                        continue
                    if python_value is None or js_value is None or abs(python_value - js_value) > 1e-9:
                        mismatches.append({"code": key, "on": on, "python": python_value, "js": js_value})
            page.close()
            browser.close()
    finally:
        connection.close()
    assert mismatches == []
