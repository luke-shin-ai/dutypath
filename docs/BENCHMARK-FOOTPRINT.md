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
| File size | 5,410,816 bytes (5,284.0 kB, 5.16 MB) |
| Nodes | 5,401 |
| Relationships | 13,490 |
| Chapters | 3 (39, 84, 85) |
| Headings | 161 |
| Subheadings | 965 |
| Origin rules | 401 (KORUS 222, RCEP 108, EU 71) |
| Tariff lines | 3,843 (US 847, EU 1,726, Japan 1,270) |
| Applied MFN rows at six digits | 12 |
| Agreements | 5 (three covered, one named and uncovered, one baseline) |
| Claim window rows | 1 |
| Source rows | 9 |

The Japan count is 1,270 because eight of the 1,278 lines in the extract repeat
the same code with the same partner, and the store keeps the first of each.

## Memory

| Measure | Value |
| --- | --- |
| Resident set before the store is opened | 30,060 kB |
| Resident set with the snapshot open | 58,952 kB |
| Difference | 28,892 kB (28.2 MB) |

Relate keeps the whole graph resident, so the file is not a disk map and the
memory is what the engine actually holds. 5.16 MB of file costs 28.2 MB of
resident memory for this shape of graph, about five and a half times the file.

## Query time

Thirty runs of each query on the open snapshot, wall clock, median.

| Query | Median | Min | Max |
| --- | --- | --- | --- |
| Rule for a good (interval match over 401 rules) | 0.736 ms | 0.672 ms | 1.368 ms |
| Rate for a line (3,843 lines) | 0.117 ms | 0.114 ms | 0.224 ms |
| Code tree above a good (catalogue walk) | 2.522 ms | 2.380 ms | 2.737 ms |
| Rules that mention a heading (text search) | 0.284 ms | 0.264 ms | 0.584 ms |

An assessment runs one rule lookup, one rate lookup per agreement, one claim
window lookup, and the in memory shipment graph. `scripts/benchmark.py` times
the whole verdict at 7.7 ms per market, three markets for one shipment, which is
the number to compare with the two baselines in `docs/BENCHMARK-EVAL.md`.

## The hub query, run

`dutypath pull-check` runs `neo4j/pull_rules.cypher` against the committed
snapshot and counts the rows that come down. The statement is one branch per
part, joined with UNION, so a market's rules and its rates are separate rows
rather than their product.

| Market | Rows | Rules | Rate lines | Claim window | Seconds |
| --- | --- | --- | --- | --- | --- |
| United States | 1,072 | 222 | 847 | 1 | 0.08 |
| European Union | 1,800 | 71 | 1,726 | 1 | 0.11 |
| Japan | 1,381 | 108 | 1,270 | 1 | 0.11 |

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
| Japan | 1,270 | a printed cell for each year 1 to 21: 1,074 free on the general row, 162 Korea rows of which 15 print U |

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
129 passed
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
permission, an except range, the hub query, and the read only reader.
