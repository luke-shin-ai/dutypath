# Footprint and benchmark

Measured on the committed snapshot, 2026-11-22, with `dutypath footprint` and
`dutypath compare`. Every number below is printed by a command in this
repository; none of them is an estimate.

## The machine

| | |
| --- | --- |
| CPU | Intel(R) Xeon(R) Platinum 8488C |
| Memory | 1,522,124 kB total |
| Python | 3.12.16 |
| Relate | `relate-db` 1.2.0, single file store |

## The snapshot

| Measure | Value |
| --- | --- |
| Store file | `store/dutypath-rules.rl` |
| File size | 5,451,776 bytes (5,324.0 kB, 5.20 MB) |
| Nodes | 5,454 |
| Relationships | 13,559 |
| Chapters | 3 (39, 84, 85) |
| Headings | 161 |
| Subheadings | 965 |
| Origin rules | 401 (KORUS 222, RCEP 108, EU 71) |
| Exclusion intervals (nodes) | 45, each one hop from its rule |
| Tariff lines | 3,851 (US 847, EU 1,726, Japan 1,278) |
| Applied MFN rows at six digits | 12 |
| Agreements | 5 (three covered, one named and uncovered, one baseline) |
| Claim window rows | 1 |
| Source rows | 9 |

The Japan count is 1,278 because every row of the extract reaches the store: a
line can carry a general row and a treatment for Korea, or a treatment for Korea
and one for other parties, and each is kept under its own treatment. The build
refuses two rows that claim the same line and the same treatment, so a rate
never depends on which row came first.

## Memory

| Measure | Value |
| --- | --- |
| Resident set before the store is opened | 29,824 kB |
| Resident set with the snapshot open | 58,620 kB |
| Difference | 28,796 kB (28.1 MB) |

Relate keeps the whole graph resident, so the file is not a disk map and the
memory is what the engine actually holds. 5.20 MB of file costs 28.1 MB of
resident memory for this shape of graph, about five and a half times the file.

## Query time

Thirty runs of each query on the open snapshot, wall clock, median.

| Query | Median | Min | Max |
| --- | --- | --- | --- |
| Rule for a good (interval match over 401 rules) | 0.762 ms | 0.714 ms | 2.042 ms |
| Rate for a line (3,851 lines) | 0.106 ms | 0.102 ms | 0.468 ms |
| Code tree above a good (catalogue walk) | 2.704 ms | 2.642 ms | 3.472 ms |
| Rules that mention a heading (text search) | 0.274 ms | 0.266 ms | 0.713 ms |

An assessment runs one traversal per market that brings back the rule and the
rate line together, one interval join per rule alternative against the material
codes, one claim window lookup, and the in memory shipment graph.
`scripts/benchmark.py` times the whole verdict at 7.5 ms per market, three
markets for one shipment, which is the number to compare with the two baselines
in `docs/BENCHMARK-EVAL.md`.

## The hub query, run

`dutypath pull-check` runs `neo4j/pull_rules.cypher` against the committed
snapshot and counts the rows that come down. The statement is one branch per
part, joined with UNION, so a market's rules and its rates are separate rows
rather than their product.

| Market | Rows | Rules | Rate lines | Claim window | Seconds |
| --- | --- | --- | --- | --- | --- |
| United States | 1,072 | 222 | 847 | 1 | 0.05 |
| European Union | 1,800 | 71 | 1,726 | 1 | 0.08 |
| Japan | 1,389 | 108 | 1,278 | 1 | 0.07 |

The earlier form of that file matched the rules and the rates from the same
agreement in one row with two OPTIONAL MATCH clauses, which returns 188,034 rows
for the United States (222 times 847) and did not finish inside a 2 GB limit.
The row count here is the number of things pulled, so a reader can check it
against the label counts above.

## Coverage, counted

Rules, by the level the agreement prints them at:

| Agreement | Chapter | Heading | Subheading | Range |
| --- | --- | --- | --- | --- |
| KORUS | - | 16 | 113 | 93 |
| RCEP | - | 104 | 4 | - |
| EU | 2 | 64 | 2 | 3 |

How many of the 965 subheadings in the three chapters resolve to a rule:

| Agreement | Subheadings with a rule | Of |
| --- | --- | --- |
| KORUS | 929 | 965 |
| EU | 965 | 965 |
| RCEP | 682 | 965 |

KORUS leaves 36 subheadings of the three chapters without a rule of their own
(`844210`, `844340`, `844351`, `844359`, `844360`, `844390`, `845240`, `848510`,
`850530`, `851780` and 26 more). A good on one of those lines comes back
undecidable under KORUS and priced under the other two agreements.

RCEP is the low number because Annex 3A as extracted lists 108 rules for the
three chapters, and a good whose line is not listed comes back undecidable. The
gap is visible on purpose: the tool says "no product specific rule for this
line in this snapshot" rather than inventing one.

Three rule sentences in the snapshot have an alternative this parser cannot
read: OR-0039 (KORUS 8415.90, a sentence about chassis and cabinets), OR-0174
(KORUS 8523.21 to 8523.80, media recorded or unrecorded) and OR-0329 (RCEP
85.49, `WO`). Those alternatives return `UNDECIDABLE` with the sentence quoted,
so the ten subheadings they cover answer honestly instead of passing. The count
is printed by `dutypath info` under `unreadable_alternatives`.

Rate lines, by the shape of the schedule:

| Market | Lines | Shape |
| --- | --- | --- |
| United States | 847 | base rate and a staging category A to K; 847 with an ad valorem base rate |
| European Union | 1,726 | base rate and a numbered category: 1,677 at 0, 26 at 3, 23 at 5 |
| Japan | 1,278 | a printed cell for each year 1 to 21: the general row where there is one, 162 Korea rows, and 170 rows written for other parties only |

## Zero leak

```
$ dutypath verify-zero-leak --shipment fixtures/shipment-8504-converter.json
sha256 before   <the store's sha256, printed by the command>
sha256 after    <the same>
labels unchanged  true
Shipment 0   Material 0   BomNode 0   Good 0   Party 0   Verdict 0
pass             true
```

The store is opened with `read_only=True`, so the engine refuses writes on that
connection; the hash comparison and the label counts are the evidence, not the
promise. Two more readings of the same claim: `tests/test_markets.py::test_the_mcp_server_leaves_the_store_byte_identical`
runs the proof through the MCP server, the path an agent uses, and
`tests/test_regressions.py::test_read_cypher_refuses_a_write_before_it_reaches_the_store`
sends `CREATE`, `MATCH ... SET` and `DETACH DELETE` through `read_cypher`, gets a
refusal for each, and finds no `Material` node afterwards.

## Tests

```
$ pytest -q
136 passed
```

No test is skipped, on a bare `pip install -e ".[dev]"` as well as here. The
browser comparison of the page's rate arithmetic needs Playwright, so it lives
in `scripts/check_demo.py` rather than in a test that would skip when the
browser is absent.

The suite covers the staging arithmetic of all three schedules at their
boundaries (each entry into force, each January 1, the rounding to a tenth, a
`U` cell, a compound duty), rule parsing and the alternatives of a rule, the
three verdicts, value content under either method, party accumulation including
the EU member states, exclusions by interval, by group and by heading, the claim
window, the approval window, snapshot freshness, the zero leak proof through the
CLI and through MCP, the store's invariants (every rule and rate cites a source;
every Japan row carries 21 cells), and one regression per defect in
`tests/test_regressions.py`: an unclassified material, an empty bill of
materials, a missing material value, a heading written where a subheading is
asked for, separators and percent signs in typed numbers, a negative amount,
another agreement's approval, an expired approval where none is required, an
unreadable alternative, a group exclusion, an except clause read as a
permission, an except range, the hub query, and the read only reader, plus a
Japan row written for another party, a duplicate partner treatment, and the
interval join that now does the exclusion test in the graph.
