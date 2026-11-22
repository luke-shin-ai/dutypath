"""Run the MCP session in docs/MCP-SCENARIO.md and print what comes back.

The session is the one a broker's assistant on a closed network would run:
what do I have, what is the rule, price the shipment in three markets, prove
nothing was written, try to write, and find the write refused.  The script
fails if a call that should answer comes back as an error, if the write is not
refused, or if the zero leak proof does not pass, so it works as a smoke test
against a snapshot as well as a way to regenerate the transcript.

    python scripts/check_mcp.py --store store/dutypath-rules.rl
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", default=os.path.join("store", "dutypath-rules.rl"))
    parser.add_argument("--shipment", default=os.path.join("fixtures", "shipment-8504-converter.json"))
    args = parser.parse_args()

    with open(args.shipment, encoding="utf-8") as handle:
        shipment = json.load(handle)

    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "broker-agent", "version": "1.0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "snapshot_info", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "resolve_rule", "arguments": {"agreement": "KORUS", "code": "85044095"}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "compare_markets",
                    "arguments": {"shipment": shipment, "on": "2026-12-01"}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
         "params": {"name": "verify_zero_leak", "arguments": {"shipment": shipment}}},
        {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
         "params": {"name": "read_cypher",
                    "arguments": {"statement": "CREATE (:Material {id: 'LEAK-1', value: 999})"}}},
        {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
         "params": {"name": "read_cypher",
                    "arguments": {"statement": "MATCH (m:Material) RETURN count(m) AS n"}}},
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    process = subprocess.run(
        [sys.executable, "-m", "dutypath.mcp", "--store", args.store],
        input="".join(json.dumps(message) + "\n" for message in messages),
        capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=120,
    )
    replies = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
    ok = True
    summary = []
    for reply in replies:
        result = reply.get("result", {})
        if reply.get("error"):
            ok = False
            summary.append({"id": reply["id"], "error": reply["error"]})
            continue
        if "content" in result:
            refused = bool(result.get("isError"))
            text = result["content"][0]["text"]
            # The write is the one call that has to come back refused; every
            # other call has to come back with an answer.
            if refused != (reply["id"] == 6):
                ok = False
            summary.append({"id": reply["id"], "refused": refused, "content": json.loads(text)})
        else:
            summary.append({"id": reply["id"], "result": result})
    leak = [entry for entry in summary if entry.get("id") == 5]
    if leak and not leak[0]["content"].get("pass"):
        ok = False
    after = [entry for entry in summary if entry.get("id") == 7]
    if after and after[0]["content"]["rows"][0].get("n"):
        ok = False
    print(json.dumps({"replies": len(replies), "ok": ok, "log": summary}, indent=2, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
