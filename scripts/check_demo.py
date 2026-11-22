"""Open the judgement screen in Chromium and check it the way a reader would.

Three things are checked, at a desktop width and at a mobile width:

* the page renders the three markets and the money with no horizontal scroll
  (``scrollWidth`` equals the viewport width, so nothing is cut off or pushed
  sideways),
* the visible text carries none of the characters that give machine written
  text away (em and en dashes, middle dots, arrows, curly quotes, ellipsis),
* selecting the committed rule file makes the page hash it in the browser and
  report that it matches the hash the bundle was built from.

Screenshots land in ``docs/demo/screenshots``.  Usage:

    python scripts/check_demo.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "docs" / "demo" / "index.html"
STORE = ROOT / "store" / "dutypath-rules.rl"
SHOTS = ROOT / "docs" / "demo" / "screenshots"
FORBIDDEN = ["\u2014", "\u2013", "\u00b7", "\u2192", "\u2026", "\u201c", "\u201d", "\u2018", "\u2019"]

VIEWPORTS = [
    {"name": "desktop-1440", "width": 1440, "height": 940},
    {"name": "mobile-390", "width": 390, "height": 844},
]


def _ensure_chromium_libs() -> None:
    """Point the loader at a local copy of the browser's shared libraries.

    A stripped container can carry the Chromium build without libnspr4 and
    libnss3, and a copy of them lives under .sysroot when that happened.  This
    only prepends a path when the library cannot be found already.
    """
    import ctypes.util

    if ctypes.util.find_library("nspr4"):
        return
    for candidate in (
        Path("/workspace/.sysroot/usr/lib/x86_64-linux-gnu"),
        Path("/workspace/.sysroot/lib/x86_64-linux-gnu"),
        ROOT.parents[1] / ".sysroot" / "usr" / "lib" / "x86_64-linux-gnu",
    ):
        if (candidate / "libnspr4.so").exists():
            current = os.environ.get("LD_LIBRARY_PATH", "")
            os.environ["LD_LIBRARY_PATH"] = str(candidate) + (":" + current if current else "")
            return


def main() -> int:
    _ensure_chromium_libs()
    from playwright.sync_api import sync_playwright

    SHOTS.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for viewport in VIEWPORTS:
            page = browser.new_page(viewport={"width": viewport["width"], "height": viewport["height"]})
            page.goto(DEMO.as_uri())
            page.wait_for_selector(".market")
            page.wait_for_timeout(250)

            metrics = page.evaluate(
                """() => ({
                    scrollWidth: document.documentElement.scrollWidth,
                    clientWidth: document.documentElement.clientWidth,
                    bodyScroll: document.body.scrollWidth,
                    markets: document.querySelectorAll('.market').length,
                    text: document.body.innerText,
                    best: document.getElementById('best-route').textContent,
                    window: document.getElementById('window').textContent
                })"""
            )
            found = sorted({char for char in FORBIDDEN if char in metrics["text"]})
            overflow = metrics["scrollWidth"] - metrics["clientWidth"]
            shot = SHOTS / ("verdict-%s.png" % viewport["name"])
            page.screenshot(path=str(shot), full_page=True)
            results.append(
                {
                    "viewport": viewport["name"],
                    "width": viewport["width"],
                    "horizontal_scroll_px": overflow,
                    "markets_rendered": metrics["markets"],
                    "best_route": metrics["best"],
                    "claim_window": metrics["window"],
                    "forbidden_characters": found,
                    "screenshot": str(shot.relative_to(ROOT)),
                }
            )
            page.close()

        # The hash check, once, on the desktop viewport.
        page = browser.new_page(viewport={"width": 1440, "height": 940})
        page.goto(DEMO.as_uri())
        page.wait_for_selector(".market")
        page.set_input_files("#rules-file", str(STORE))
        page.wait_for_function("() => window.DUTYPATH_LAST_HASH", timeout=30000)
        page.wait_for_timeout(350)
        hashed = page.evaluate("() => window.DUTYPATH_LAST_HASH")
        badge = page.inner_text("#hash-badge")
        shot = SHOTS / "verdict-desktop-1440-hash-checked.png"
        page.screenshot(path=str(shot), full_page=True)
        results.append(
            {
                "viewport": "desktop-1440 (hash check)",
                "hash_in_browser": hashed,
                "badge": badge,
                "screenshot": str(shot.relative_to(ROOT)),
            }
        )
        page.close()
        browser.close()

    print(json.dumps({"demo": str(DEMO), "results": results}, indent=2))
    failed = [
        entry for entry in results
        if entry.get("horizontal_scroll_px", 0) != 0
        or entry.get("forbidden_characters")
        or entry.get("markets_rendered", 3) != 3
        or entry.get("badge") not in (None, "rule file matches")
    ]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
