"""Open they demo over http and watch the engine build the graph in the tab.

The static page check (``scripts/check_demo.py``) opens the page from the file
system, where a worker and the wasm fetch are blocked.  This check serves the
repository over http, opens the published path ``docs/demo/``, and waits for
the panel's own report:

* the worker starts, builds the graph and names the counts it created,
* every value the engine returns for the shipment on screen equals the value
  the committed bundle was built from (the parity line says how many agree),
* a second shipment gives the same agreement,
* neither viewport scrolls sideways and the visible text stays free of the
  characters that give machine written text away.

    python scripts/check_wasm_demo.py
"""

from __future__ import annotations

import functools
import http.server
import json
import mimetypes
import os
import socket
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "docs" / "demo"
SHOTS = DEMO / "screenshots"
FORBIDDEN = ["\u2014", "\u2013", "\u00b7", "\u2192", "\u2026", "\u201c", "\u201d", "\u2018", "\u2019"]
VIEWPORTS = [
    {"name": "desktop-1440", "width": 1440, "height": 940},
    {"name": "mobile-390", "width": 390, "height": 844},
]


def _ensure_chromium_libs() -> None:
    import ctypes.util

    if ctypes.util.find_library("nspr4"):
        return
    for base in (ROOT, *ROOT.parents):
        for candidate in (
            base / ".sysroot" / "usr" / "lib" / "x86_64-linux-gnu",
            base / ".sysroot" / "lib" / "x86_64-linux-gnu",
        ):
            if (candidate / "libnspr4.so").exists():
                current = os.environ.get("LD_LIBRARY_PATH", "")
                os.environ["LD_LIBRARY_PATH"] = str(candidate) + (":" + current if current else "")
                return


def serve(directory: Path):
    mimetypes.add_type("application/wasm", ".wasm")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def main() -> int:
    _ensure_chromium_libs()
    from playwright.sync_api import sync_playwright

    SHOTS.mkdir(parents=True, exist_ok=True)
    server, port = serve(ROOT)
    url = "http://127.0.0.1:%d/docs/demo/" % port
    results = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            for viewport in VIEWPORTS:
                page = browser.new_page(viewport={"width": viewport["width"], "height": viewport["height"]})
                page.goto(url)
                page.wait_for_selector(".market")
                page.wait_for_function(
                    "() => document.getElementById('engine-parity').textContent.indexOf('agree') >= 0",
                    timeout=180000,
                )
                page.wait_for_timeout(200)
                state = page.evaluate(
                    """() => ({
                        status: document.getElementById('engine-status').textContent,
                        statusClass: document.getElementById('engine-status').className,
                        parity: document.getElementById('engine-parity').textContent,
                        parityClass: document.getElementById('engine-parity').className,
                        rows: document.querySelectorAll('#engine-body tbody tr').length,
                        text: document.body.innerText,
                        scrollWidth: document.documentElement.scrollWidth,
                        clientWidth: document.documentElement.clientWidth,
                    })"""
                )
                shot = SHOTS / ("wasm-%s.png" % viewport["name"])
                page.screenshot(path=str(shot), full_page=True)
                found = sorted({char for char in FORBIDDEN if char in state["text"]})
                results.append(
                    {
                        "viewport": viewport["name"],
                        "status": state["status"],
                        "parity": state["parity"],
                        "engine_rows": state["rows"],
                        "horizontal_scroll_px": state["scrollWidth"] - state["clientWidth"],
                        "forbidden_characters": found,
                        "screenshot": str(shot.relative_to(ROOT)),
                    }
                )
                page.close()

            # A second shipment, chosen the way a reader would choose it.
            page = browser.new_page(viewport={"width": 1440, "height": 940})
            page.goto(url)
            page.wait_for_function(
                "() => document.getElementById('engine-parity').textContent.indexOf('agree') >= 0",
                timeout=180000,
            )
            options = page.eval_on_selector_all("#case option", "els => els.map(e => e.value + ' ' + e.textContent)")
            target = None
            for option in options:
                if option.startswith("1 ") or " SHP-2026-1201-001" in option:
                    target = option.split(" ", 1)[0]
                    break
            if target is None:
                target = "1"
            before = page.inner_text("#engine-parity")
            page.select_option("#case", target)
            page.wait_for_function(
                "(before) => document.getElementById('engine-parity').textContent !== before && "
                "document.getElementById('engine-parity').textContent.indexOf('agree') >= 0",
                arg=before,
                timeout=180000,
            )
            page.wait_for_timeout(150)
            second = page.evaluate(
                """() => ({
                    case: document.getElementById('case').selectedOptions[0].textContent,
                    parity: document.getElementById('engine-parity').textContent,
                    status: document.getElementById('engine-status').textContent,
                })"""
            )
            shot = DEMO / "screenshots" / "wasm-second-shipment.png"
            page.screenshot(path=str(shot), full_page=True)
            results.append(
                {
                    "viewport": "second shipment",
                    "case": second["case"],
                    "parity": second["parity"],
                    "status": second["status"],
                    "screenshot": str(shot.relative_to(ROOT)),
                }
            )
            page.close()
            browser.close()
    finally:
        server.shutdown()

    print(json.dumps({"url": url, "results": results}, indent=2, ensure_ascii=False))
    failed = [
        entry
        for entry in results
        if entry.get("forbidden_characters")
        or entry.get("horizontal_scroll_px", 0) != 0
        or " values agree" not in entry.get("parity", "")
        or " 15 of 15 values agree" not in entry.get("parity", "")
        or "of 15 values agree" not in entry.get("parity", "")
        or entry.get("engine_rows", 3) != 3
    ]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
