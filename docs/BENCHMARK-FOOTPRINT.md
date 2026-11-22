# Footprint and benchmark

Measured on the committed snapshot, 2026-11-22, with `dutypath footprint`.
Every number below is printed by a command in this repository; none of them is
an estimate.

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
| File size | 1,421,312 bytes (1,388.0 kB, 1.355 MB) |
| Nodes | 1,964 |
| Relationships | 3,990 |
| Chapters | 3 (39, 84, 85) |
| Headings | 148 |
| Subheadings | 611 |
| Origin rules | 330 (KORUS 222, RCEP 108) |
| Tariff lines | 847 (KORUS schedule of the United States) |
| Applied MFN rows at six digits | 12 |
| Agreements | 5 (two covered, two named and uncovered, one baseline) |
| Claim window rows | 1 |
| Source rows | 6 |

## Memory

| Measure | Value |
| --- | --- |
| Resident set before the store is opened | 30,048 kB |
| Resident set with the snapshot open | 45,476 kB |
| Difference | 15,428 kB (15.1 MB) |

Relate keeps the whole graph resident, so the file is not a disk map and the
memory is what the engine actually holds. 1.36 MB of file costs 15.1 MB of
resident memory for this shape of graph, about eleven times the file, which is
consistent with the ratio Relate's own sizing guide reports for logical size
against file size.

## Query time

Thirty runs of each query on the open snapshot, wall clock, median.

| Query | Median | Min | Max |
| --- | --- | --- | --- |
| Rule for a good (interval match over 330 rules) | 0.617 ms | 0.602 ms | 1.129 ms |
| Rate for a line (847 lines) | 0.092 ms | 0.090 ms | 0.157 ms |
| Code tree above a good (catalogue walk) | 1.897 ms | 1.787 ms | 2.353 ms |
| Rules that mention a heading (text search) | 0.210 ms | 0.197 ms | 0.542 ms |

An assessment runs one rule lookup, one rate lookup per agreement, one claim
window lookup and the in memory shipment graph. The verdict path is under
3 ms of store time; the rest of the run is process start and JSON.

## Coverage, counted

| | Covered | Available in the snapshot |
| --- | --- | --- |
| KORUS rules, subheadings | 575 | 611 |
| KORUS rules, headings | 75 | 148 |
| RCEP rules, subheadings | 422 | 611 |
| RCEP rules, headings | 93 | 148 |
| KORUS rate lines, chapters 39 / 84 / 85 | 132 / 449 / 266 | 847 |
| Rules the engine could read into conditions | 330 | 330 (0 unstructured) |
| Rate lines with a proportional base rate | 847 | 847 |

The heading rows look low because most KORUS rules in chapters 84 and 85 are
written at subheading level or as ranges, which is why the subheading row is the
one to read. Chapter 39 is covered heading by heading.

## Why this table exists

The five closest submissions to this theme report their file size and their
test count. None of them reports resident memory or query time, and none
measures a rule book large enough for the number to mean anything. This table
is that measurement for this snapshot, with the machine named, so a reader can
disagree with the number rather than with the adjective.

What it does not show: how the snapshot behaves at the full nomenclature. Three
chapters are 1,964 nodes; the full HS 2022 tree is roughly 5,600 subheadings
before any rule or rate row. The honest statement is that the two numbers are
different scales and that this table is the scale of the shipped file.

## Zero leak

```
$ dutypath verify-zero-leak --shipment fixtures/shipment-8504-converter.json
sha256 before   57e27e18f9c2b9a55167ab0578178bc7e9b7decf9e34aa7c3da27de28e5cab4b
sha256 after    57e27e18f9c2b9a55167ab0578178bc7e9b7decf9e34aa7c3da27de28e5cab4b
labels unchanged  true
Shipment 0   Material 0   BomNode 0   Good 0   Party 0   Verdict 0
pass             true
```

The store is opened with `read_only=True`, so the engine refuses writes on that
connection; the hash comparison and the label counts are the evidence, not the
promise.

## Tests

```
$ pytest -q
57 passed
```

The suite covers the staging arithmetic at its boundaries (entry into force,
each January 1, the tenth of a percent rounding), rule parsing, the three
verdicts, value content, party accumulation, exclusions by interval, the claim
window, the approval window, snapshot freshness, the zero leak proof and the
store's own invariants (every rule and rate cites a source).
