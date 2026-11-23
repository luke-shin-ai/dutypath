"""An MCP server over the local rule snapshot.

An AI agent on a closed network holds the .rl file and no network. This module
lets that agent ask the same question a person asks the CLI, over the Model
Context Protocol's stdio transport: newline delimited JSON-RPC on stdin and
stdout, with the tools declared in `TOOLS`.

The server opens the snapshot read only, exactly as the CLI does, and it writes
nothing anywhere: an answer is a response, not a record.  A shipment sent to it
is read into memory and dropped with the call, so a tool call leaves the rule
book byte for byte as it was.

The boundary has a second side, and it is the one worth stating plainly: the
bill of materials reaches this server as a tool argument, so the agent that
calls it has that bill of materials in its own context, and an MCP host may keep
the transcript.  Nothing here stores it, and nothing here can leak what it never
held; what travels through the caller's context is the caller's to hold.

    python -m dutypath.mcp --stdio --store store/dutypath-rules.rl

Every tool returns one JSON object in the tool result's text content.  A tool
that cannot answer returns the same shape with the missing piece named, rather
than a default answer: an agent reading `UNDECIDABLE` is told what to ask the
exporter for.

The surface is kept small on purpose.  A `shipment_path` has to resolve inside
the directory the server was started in, so the tool cannot be talked into
opening a file elsewhere on the machine, and `read_cypher` returns at most 500
rows per call and says whether it stopped short.  Together they keep one call to
one question and one page.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from . import assess, duty, leak, markets, origin, store
from . import rules as rulebook

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "dutypath", "version": "0.2.0"}

# A tool result is a response to one question, not a dump of a file.  The reader
# returns at most this many rows and says when it stopped short, so a statement
# that matches the whole graph cannot turn one call into a megabyte of text.
MAX_ROWS = 500

TOOLS = [
    {
        "name": "compare_markets",
        "title": "Compare three markets",
        "description": (
            "Price one bill of materials in the United States (KORUS), the European Union "
            "(Korea-EU) and Japan (RCEP): the origin verdict under each agreement, the "
            "preferential and MFN rate, the duty each route pays, and the date until which a "
            "refund can be claimed. Reads the local .rl snapshot only. The bill of materials "
            "arrives as an argument and is never written to the graph, so it stays in the "
            "calling agent's context and not in the rule file."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "shipment": {"type": "object", "description": "The shipment, as the JSON the CLI reads."},
                "shipment_path": {"type": "string", "description": "A path to the shipment JSON, used when shipment is absent. It has to resolve inside the server's working directory."},
                "on": {"type": "string", "description": "Assessment date, ISO 8601. Defaults to the shipment's import date, then its export date."},
            },
        },
        "annotations": {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "assess_shipment",
        "title": "Assess one market",
        "description": (
            "The same verdicts for the shipment's own market, one route per agreement, with the "
            "material that breaks a rule named and the reason quoted from the rule. The bill of "
            "materials arrives as an argument and is not written to the graph."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "shipment": {"type": "object"},
                "shipment_path": {"type": "string", "description": "A path inside the server's working directory."},
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
            "counts, and whether any shipment, material, good, party or verdict node exists. "
            "This proves the rule file and the graph; the bill of materials still travelled "
            "through the caller's context to get here."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"shipment": {"type": "object"},
                           "shipment_path": {"type": "string", "description": "A path inside the server's working directory."}},
        },
        "annotations": {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "read_cypher",
        "title": "Read the graph",
        "description": (
            "Run one read only Cypher statement against the rule snapshot and return its rows. A "
            "statement that would write is refused before it reaches the store, and the refusal "
            "names the clause it found. A call returns at most %d rows; it says how many it "
            "stopped at, so a statement over the whole graph answers with a page and not with "
            "the graph." % MAX_ROWS
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "statement": {"type": "string"},
                "parameters": {"type": "object"},
                "limit": {"type": "integer", "description": "Rows to return, at most %d. Defaults to %d."
                           % (MAX_ROWS, MAX_ROWS)},
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
        clause = store.write_keyword(statement)
        if clause:
            raise ValueError(
                "read_cypher runs read only statements: this one contains %s, so it was not sent "
                "to the store. The snapshot is a rule book and an answer never edits it." % clause
            )
        limit = _row_limit(args.get("limit"))
        rows = []
        stopped = False
        for row in self.conn.execute(statement, args.get("parameters") or {}):
            if len(rows) >= limit:
                stopped = True
                break
            rows.append(dict(row))
        return {"rows": rows, "count": len(rows), "limit": limit, "truncated": stopped,
                "note": ("stopped at the %d row limit; ask a narrower question or raise limit" % limit)
                if stopped else None}

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
    with open(_workspace_file(str(path)), encoding="utf-8") as handle:
        return json.load(handle)


def _workspace_file(path: str) -> Path:
    """A shipment file inside the directory the server was started in.

    The server reads a file whose path arrives as a tool argument, so the path
    is the one place a caller could reach past the snapshot.  A path that
    resolves outside the working directory is refused before anything is
    opened, which keeps ``../../etc/shadow`` and a symlink pointing there in the
    same place: outside.
    """
    root = Path.cwd().resolve()
    target = (root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if target != root and root not in target.parents:
        raise ValueError(
            "shipment_path has to stay inside the server's working directory %s: %s resolves "
            "outside it, so it was not opened" % (root, target)
        )
    if not target.is_file():
        raise ValueError("shipment_path %s is not a file this server can read" % target)
    return target


def _row_limit(value) -> int:
    if value is None or value == "":
        return MAX_ROWS
    try:
        wanted = int(value)
    except (TypeError, ValueError):
        raise ValueError("limit has to be a whole number of rows, at most %d" % MAX_ROWS)
    return max(1, min(wanted, MAX_ROWS))


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
