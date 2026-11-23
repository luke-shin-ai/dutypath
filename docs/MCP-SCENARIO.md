# MCP scenario: an agent on a closed network

The setting is the one the tool was built for. A customs broker's laptop sits on
a client site with no network. On it there is one file, `dutypath-rules.rl`, and
an MCP host. The broker asks their assistant, in words, which agreement to
declare the shipment under. The assistant has no internet and no database: it
has a file and a stdio pipe.

DutyPath answers over the Model Context Protocol's stdio transport:

```
dutypath mcp --store store/dutypath-rules.rl
```

Seven tools are listed by `tools/list`:

| Tool | What it answers |
| --- | --- |
| `compare_markets` | the three market comparison for one bill of materials |
| `assess_shipment` | the same verdicts for the shipment's own market, one route per agreement |
| `resolve_rule` | the rule for a code under an agreement, its sentence, and the document it cites |
| `rate_on_date` | the preferential rate for one line on one date, or the reason there is none |
| `snapshot_info` | the snapshot's identity, coverage and counts |
| `verify_zero_leak` | the sha256 before and after an assessment, and the label counts |
| `read_cypher` | one read only Cypher statement against the snapshot; a statement that would write is refused before it reaches the store, and a call stops at 500 rows |

Two limits sit on the tools that take a path or a statement. `shipment_path`
has to resolve inside the directory the server was started in, so a path that
climbs out of it (`../../etc/passwd`, or a symlink pointing there) is refused
before anything is opened; a shipment passed as an object is unaffected.
`read_cypher` returns at most 500 rows per call and says whether it stopped
short, so a statement over the whole graph answers with a page instead of the
graph. A caller may ask for fewer rows with `limit`; asking for more gets 500.

## The exchange, as it ran

Seven messages on stdin, seven lines on stdout. The log below is the output of
`scripts/check_mcp.py`, trimmed to the fields that decide the answer.

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"broker-agent","version":"1.0"}}}
```

```json
{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"dutypath","version":"0.2.0"}}}
```

The agent asks what it is holding.

```json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"snapshot_info","arguments":{}}}
```

```json
{"snapshot":{"id":"dutypath-rules-2026-11-22","as_of":"2026-11-22","rule_version":"2.0","max_age_days":120,"chapters":["39","84","85"]},
 "agreements":[{"code":"EUKOR","market":"EU","coverage":"rules+rates"},
               {"code":"KORUS","market":"US","coverage":"rules+rates"},
               {"code":"MFN","market":"*","coverage":"rate"},
               {"code":"RCEP","market":"JP","coverage":"rules+rates"},
               {"code":"TURKOR","market":"TR","coverage":"none"}],
 "counts":{"Agreement":5,"Chapter":3,"DeadlineRule":1,"Heading":161,"Hs6Rate":12,"HsInterval":45,
           "OriginRule":401,"RateLine":3851,"Snapshot":1,"Source":9,"Subheading":965}}
```

It reads the rule before trusting the verdict.

```json
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"resolve_rule","arguments":{"agreement":"KORUS","code":"85044095"}}}
```

```json
{"agreement":"KORUS","code":"85044095","found":true,
 "rule":{"id":"OR-0131","level":"range","code_from":"8504.32","code_to":"8504.50",
         "text":"A change to subheading 8504.32 through 8504.50 from any subheading outside subheading 8504.10 through 8504.50.",
         "alternatives":[{"text":"A change to subheading 8504.32 through 8504.50 from any subheading outside subheading 8504.10 through 8504.50.",
                          "kinds":["CTSH"],"excluded":[],"excluded_ranges":[],"group":["8504.10","8504.50"],
                          "allowed_from":[],"rvc_down":null,"rvc_up":null,"weight_min":null}]},
 "source":{"id":"SRC-KORUS-6A","title":"KORUS FTA Annex 6-A, Specific Rules of Origin",
           "url":"https://ustr.gov/sites/default/files/Annex_6-A_SPECIFIC_RULES_OF_ORIGIN.pdf","as_of":"2012-03-15"}}
```

Then the question itself, with the material list the broker typed in.

```json
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"compare_markets",
 "arguments":{"shipment":{"shipment_id":"SHP-2026-1201-001","market":"US","export_date":"2026-12-01",
   "import_date":"2026-12-08",
   "goods":{"hts8":"85044095","hs6":"850440","description":"Static converter, industrial power supply unit",
            "declared_value":480000,"currency":"USD",
            "market_codes":{"US":"85044095","EU":"85044090","JP":"850440090"}},
   "materials":[{"id":"M1","hts8":"85043140","origin":"CN","value":150000,"description":"transformer, dry type"},
                {"id":"M2","hts8":"85322200","origin":"JP","value":24000,"description":"capacitor"},
                {"id":"M3","hts8":"85340000","origin":"KR","value":60000,"description":"printed circuit board"},
                {"id":"M4","hts8":"39269098","origin":"KR","value":18000,"description":"moulded housing"}],
   "approved_exporters":[{"agreement":"RCEP","valid_from":"2022-03-01","valid_to":"2026-08-31","ref":"RCEP-AE-2211-0093"},
                         {"agreement":"EUKOR","valid_from":"2024-01-01","valid_to":"2027-12-31","ref":"EU-AE-2024-0417"}]},
  "on":"2026-12-01"}}}
```

The answer, trimmed to the numbers that decide it:

```json
{"best_claim":{"market":"EU","agreement":"EUKOR","duty":0.0,"saving":15840.0},
 "ranking":{"cheapest":"EU","dearest":"US","spread":7200.0,"currency":"USD"},
 "claim_window":{"status":"OPEN","deadline":"2027-12-08","legal_ref":"협정관세 사후적용 신청기간 1년",
                 "scope":"the Korean post import claim window, the same for every route; the importing country's own refund period is not in this snapshot"},
 "markets":[
   {"market":"US","code":"85044095","verdict":"NO CLAIM",
    "origin":{"verdict":"NOT_ORIGINATING","reason":"M1 85043140 sits inside 8504.10 to 8504.50, the group the rule excludes"},
    "rate":{"percent":0.0},"mfn":{"percent":1.5},"duty":{"amount":7200.0},
    "claim":{"allowed":false,"blocked_by":"origin: NOT_ORIGINATING"}},
   {"market":"EU","code":"85044090","verdict":"CLAIM",
    "origin":{"verdict":"ORIGINATING","reason":"regional value content 63.75 percent on the build down method meets the 55 percent the rule asks for"},
    "rate":{"percent":0.0},"mfn":{"percent":3.3},"duty":{"amount":0.0},
    "claim":{"allowed":true,"blocked_by":null}},
   {"market":"JP","code":"850440090","verdict":"NO CLAIM",
    "origin":{"verdict":"ORIGINATING","reason":"regional value content 100.00 percent on the build down method meets the 40 percent the rule asks for"},
    "rate":{"percent":0.0},"mfn":{"percent":0.0},"duty":{"amount":0.0},
    "claim":{"allowed":false,"blocked_by":"document: the approved exporter approval expired before the claim date"}}]}
```

Three markets, three answers, and the one the broker would have missed is the
one that pays: the same transformer that blocks the American claim is allowed by
the EU rule, whose ceiling is met at 36 percent, and the EU claim is worth
15,840 dollars. Japan is free either way, and the RCEP approval on file ran out
on 2026-08-31. The reasons read differently because the rules do: the American
answer is a classification test, the European and Japanese answers are value
content, and each says which test it ran.

Last, the agent proves it changed nothing.

```json
{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"verify_zero_leak","arguments":{"shipment":{...}}}}
```

```json
{"store":"store/dutypath-rules.rl",
 "sha256_before":"200d613c08a4c4c65cbff74d17ab46619e76f6032f9ffba9640999a90262aec8",
 "sha256_after":"200d613c08a4c4c65cbff74d17ab46619e76f6032f9ffba9640999a90262aec8",
 "hash_unchanged":true,"labels_unchanged":true,
 "forbidden_labels":{"Shipment":0,"Material":0,"BomNode":0,"Good":0,"Party":0,"Verdict":0},
 "pass":true}
```

Then it tries to write, and is told no.

```json
{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"read_cypher",
 "arguments":{"statement":"CREATE (:Material {id: 'LEAK-1', value: 999})"}}}
```

```json
{"error":"read_cypher runs read only statements: this one contains CREATE, so it was not sent to the store. The snapshot is a rule book and an answer never edits it."}
```

The refusal happens in the engine, before the statement reaches Relate: the
reader looks for a writing clause in the statement, so `CREATE`, `MERGE`, `SET`,
`DELETE`, `REMOVE`, `DROP`, `FOREACH`, `CALL` and a second statement after a
semicolon all come back with the clause named. A string literal that contains
one of those words is not a clause and still reads.

## What the zero leak proof covers, and what it does not

The proof is about the file and the graph: after a tool call the store's sha256
is the same, and no `Shipment`, `Material`, `Good`, `Party` or `Verdict` node
exists in it.  It is not a claim about the agent's own memory.  A bill of
materials reaches `compare_markets` as a tool argument, so the calling agent has
that bill of materials in its context before this server sees it, and an MCP host
may keep the transcript.  The boundary stated here is the one the tool can
enforce: it stores nothing, and it cannot leak what it never held.  An agent that
must not have the material list in its context should not be given the material
list.

## When the agent asks a question the snapshot cannot answer

An agent that is told "undecidable" can act on it, which is the point of having
the third verdict. Two shapes of that answer, both produced by the tools above:

* **No classification for a material.** A bill of materials with a line that
  carries no tariff code gets `"verdict": "UNDECIDABLE"` and `missing: ["the
  tariff classification of material M1"]`, whatever the rule asks, because the
  tool cannot say whether that line should have been tested. The agent asks the
  broker for the code.
* **No classification for a market.** A shipment written with no EU line gets
  `"blocked_by": "classification: the shipment states no line for this market's
  nomenclature"` and `missing: ["the good's CN eight digit code for European
  Union"]`. The agent asks the broker for the classification instead of pricing
  the good on an American code.
* **No rule for the line.** `resolve_rule` with agreement `RCEP` and code
  `85076000` returns `found: false` and the sentence "no origin rule for
  85076000 under RCEP in this snapshot". The comparison for that good reports
  `UNDECIDABLE` for Japan and still prices the United States and the EU.

## Running it yourself

```
PYTHONPATH=src python -m dutypath.mcp --store store/dutypath-rules.rl
```

Paste `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}` and then any
of the calls above on stdin. `scripts/check_mcp.py` runs the whole session above
and prints the replies, so the transcript in this file can be reproduced.

## The other MCP surface

Relate's own binary serves the same file over MCP:

```
relate serve --database store/dutypath-rules.rl --mcp stdio --read-only
```

That surface exposes `read_cypher` and `get_schema`, so an agent can read the
graph directly with the queries in `cypher/`. `tests/test_markets.py` reads the
same EU rate row two ways, through this package's Cypher and through
`duty.line_rate`, and compares them; when the binary is installed it compares
through that too, and says so in the test name rather than skipping.
