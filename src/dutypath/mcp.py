"""An MCP server over the local rule snapshot.

An AI agent on a closed network holds the .rl file and no network. This module
lets that agent ask the same question a person asks the CLI, over the Model
Context Protocol's stdio transport: newline delimited JSON-RPC on stdin and
stdout, with the tools declared in `TOOLS`.

The server opens the snapshot read only, exactly as the CLI does, and it writes
nothing anywhere: an answer is a response, not a record.  A shipment sent to it
is read into memory and dropped with the call, so a tool call leaves the rule
book byte for byte as it was.

    python -m dutypath.mcp --stdio --store store/dutypath-rules.rl

Every tool returns one JSON object in the tool result's text content.  A tool
that cannot answer returns the same shape with the missing piece named, rather
than a default answer: an agent reading `UNDECIDABLE` is told what to ask the
exporter for.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from . import assess, duty, leak, markets, origin, store
from . import rules as rulebook

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "dutypath", "version": "0.2.0"}

TOOLS = [
    {
        "name": "compare_markets",
        "title": "Compare three markets",
        "description": (
            "Price one bill of materials in the United States (KORUS), the European Union "
            "(Korea-EU) and Japan (RCEP): the origin verdict under each agreement, the "
            "preferential and MFN rate, the duty each route pays, and the date until which a "
            "refund can be claimed. Reads the local .rl snapshot only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "shipment": {"type": "object", "description": "The shipment, as the JSON the CLI reads."},
                "shipment_path": {"type": "string", "description": "A path to the shipment JSON, used when shipment is absent."},
                "on": {"type": "string", "description": "Assessment date, ISO 8601. Defaults to the shipment's export date."},
            },
        },
        "annotations": {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "assess_shipment",
        "title": "Assess one market",
        "description": (
            "The same verdicts for the shipment's own market, one route per agreement, with the "
            "material that breaks a rule named and the reason quoted from the rule."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "shipment": {"type": "object"},
                "shipment_path": {"type": "string"},
                "on": {"type": "string"},
            },
        },
        "annotations": {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "resolve_rule",
        "title": "Resolve an origin rule",
        "description": (
            "The product specific origin rule that applies to a tariff code under one agreement, "
            "with the sentence it came from and the document that sentence is cited to."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agreement": {"type": "string", "enum": ["KORUS", "EUKOR", "RCEP"]},
                "code": {"type": "string", "description": "Tariff code at four, six or eight digits."},
            },
            "required": ["agreement", "code"],
        },
        "annotations": {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "rate_on_date",
        "title": "Rate for a line on a date",
        "description": (
            "The preferential rate one market gives one tariff line on one date, computed from the "
            "schedule row the snapshot holds, or the reason the snapshot cannot price it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "market": {"type": "string", "enum": ["US", "EU", "JP"]},
                "code": {"type": "string"},
                "on": {"type": "string", "description": "ISO 8601 date."},
            },
            "required": ["market", "code"],
        },
        "annotations": {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "snapshot_info",
        "title": "What the snapshot covers",
        "description": "Snapshot id, date, age limit, the agreements, the counts and the sources.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "verify_zero_leak",
        "title": "Prove the store is untouched",
        "description": (
            "Assess a shipment and report the sha256 of the store before and after, the label "
            "counts, and whether any shipment, material, good, party or verdict node exists."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"shipment": {"type": "object"}, "shipment_path": {"type": "string"}},
        },
        "annotations": {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "read_cypher",
        "title": "Read the graph",
        "description": "Run one read only Cypher statement against the rule snapshot and return its rows.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "statement": {"type": "string"},
                "parameters": {"type": "object"},
            },
            "required": ["statement"],
        },
        "annotations": {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
    },
]


class Server:
    def __init__(self, store_path: str):
        self.store_path = store_path
        self._conn = None

    @property
    def conn(self):
        if self._conn is None:
            self._conn = store.connect(self.store_path, read_only=True)
            self._conn.autocommit = False
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------ tools
    def compare_markets(self, args: dict) -> dict:
        shipment = _shipment(args)
        return markets.compare(self.conn, shipment, _on(args))

    def assess_shipment(self, args: dict) -> dict:
        shipment = _shipment(args)
        return assess.assess(self.conn, shipment, _on(args))

    def resolve_rule(self, args: dict) -> dict:
        agreement = str(args.get("agreement") or "")
        code = str(args.get("code") or "")
        rule = rulebook.resolve(self.conn, agreement, code)
        if rule is None:
            return {
                "agreement": agreement,
                "code": code,
                "found": False,
                "reason": "no origin rule for %s under %s in this snapshot" % (code, agreement),
            }
        source = store.one(
            self.conn,
            "MATCH (r:OriginRule {id: $id})-[:CITED_FROM]->(s:Source) "
            "RETURN s.id AS id, s.title AS title, s.url AS url, toString(s.as_of) AS as_of",
            {"id": rule["id"]},
        )
        return {
            "agreement": agreement,
            "code": code,
            "found": True,
            "rule": {
                "id": rule["id"],
                "level": rule["level"],
                "code_from": rule["code_from"],
                "code_to": rule["code_to"],
                "text": rule["text"],
                "alternatives": rulebook.alternatives(rule),
            },
            "source": source,
        }

    def rate_on_date(self, args: dict) -> dict:
        market = str(args.get("market") or "US")
        code = str(args.get("code") or "")
        on = date.fromisoformat(str(args.get("on") or date.today().isoformat())[:10])
        agreement = markets.MARKET_AGREEMENT.get(market, "KORUS")
        rate = duty.line_rate(self.conn, market, agreement, code, on)
        mfn = duty.mfn_rate(self.conn, market, code)
        return {"market": market, "agreement": agreement, "code": code, "on": on.isoformat(),
                "preferential": rate, "mfn": mfn}

    def snapshot_info(self, args: dict) -> dict:
        snapshot = store.one(
            self.conn,
            "MATCH (s:Snapshot) RETURN s.id AS id, toString(s.as_of) AS as_of, "
            "s.rule_version AS rule_version, s.max_age_days AS max_age_days, s.chapters AS chapters",
        )
        agreements = store.rows(
            self.conn,
            "MATCH (a:Agreement) RETURN a.code AS code, a.market AS market, a.coverage AS coverage "
            "ORDER BY a.code",
        )
        counts = store.label_counts(self.conn)
        rates = store.rows(
            self.conn,
            "MATCH (r:RateLine)-[:FOR]->(a:Agreement) RETURN a.code AS agreement, count(r) AS lines "
            "ORDER BY a.code",
        )
        rules = store.rows(
            self.conn,
            "MATCH (r:OriginRule)-[:FOR]->(a:Agreement) RETURN a.code AS agreement, count(r) AS rules "
            "ORDER BY a.code",
        )
        return {
            "snapshot": snapshot,
            "agreements": agreements,
            "counts": counts,
            "rate_lines": rates,
            "origin_rules": rules,
            "store": self.store_path,
        }

    def verify_zero_leak(self, args: dict) -> dict:
        shipment = _shipment(args)
        return leak.verify(self.store_path, shipment, _on(args))

    def read_cypher(self, args: dict) -> dict:
        statement = str(args.get("statement") or "")
        rows = store.rows(self.conn, statement, args.get("parameters") or {})
        return {"rows": rows, "count": len(rows)}

    # ------------------------------------------------------------ protocol
    def handle(self, request: dict) -> dict | None:
        method = request.get("method")
        request_id = request.get("id")
        if method == "initialize":
            return _result(request_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            })
        if method in ("notifications/initialized", "initialized"):
            return None
        if method == "ping":
            return _result(request_id, {})
        if method == "tools/list":
            return _result(request_id, {"tools": TOOLS})
        if method == "tools/call":
            params = request.get("params") or {}
            name = params.get("name")
            arguments = params.get("arguments") or {}
            handler = getattr(self, name, None) if name in {tool["name"] for tool in TOOLS} else None
            if handler is None:
                return _error(request_id, -32602, "unknown tool %r" % name)
            try:
                payload = handler(arguments)
            except Exception as error:  # the agent gets the reason, not a stack trace
                return _result(request_id, {
                    "content": [{"type": "text", "text": json.dumps({"error": str(error)}, ensure_ascii=False)}],
                    "isError": True,
                })
            return _result(request_id, {
                "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, default=str)}],
                "isError": False,
            })
        if method in ("shutdown", "exit"):
            return _result(request_id, {})
        return _error(request_id, -32601, "method not found: %r" % method)

    def serve(self) -> int:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except ValueError:
                _write(_error(None, -32700, "parse error"))
                continue
            response = self.handle(request)
            if response is not None:
                _write(response)
        self.close()
        return 0


def _result(request_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _write(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def _shipment(args: dict) -> dict:
    if isinstance(args.get("shipment"), dict):
        return args["shipment"]
    path = args.get("shipment_path")
    if not path:
        raise ValueError("pass a shipment object or a shipment_path")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _on(args: dict) -> date | None:
    value = args.get("on")
    return date.fromisoformat(str(value)[:10]) if value else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dutypath.mcp", description=__doc__)
    parser.add_argument("--store", default=store.DEFAULT_STORE)
    parser.add_argument("--stdio", action="store_true", default=True)
    args = parser.parse_args(argv)
    return Server(args.store).serve()


if __name__ == "__main__":
    raise SystemExit(main())
