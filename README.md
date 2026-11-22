# DutyPath

An origin and duty verdict for one shipment, computed off a rule snapshot that
carries no client data.

This tool stores no client data. The file it ships is the public rulebook:
tariff codes, origin rules, duty rates.

It does not stop at what is missing. It prices the gap: which agreement wins,
how much it saves, and until when a refund can be claimed.

The rules are pulled from a Neo4j hub as a versioned snapshot, and the verdict
says when that snapshot is too old to trust.

---

## Use case

A Korean exporter is about to ship. One question decides the invoice: under
which agreement can this good claim a preference, and what does the answer
cost if the answer is no.

Three answers come back, and they are not the same kind of answer.

* **ORIGINATING.** The rule is met, the material that satisfied it is named, and
  the duty is computed at the preferential rate.
* **NOT ORIGINATING.** The rule is not met, and the part that breaks it is named
  with the reason: a transformer in the same heading the rule excludes, a
  separator from the same heading as the good.
* **UNDECIDABLE.** The snapshot cannot answer. Not "probably fine", not a
  default: the missing piece is named, for example the polymer weight share a
  rule asks for and the bill of materials does not carry.

The third answer is the one that matters in practice. A missing weight share is
a phone call or a re-test. A tool that guesses instead turns that into an
assessment years later.

What it does not do: it is not legal advice, it is not a customs declaration,
and it does not decide for the exporter. It prices the decision.

```
$ dutypath assess --shipment fixtures/shipment-8504-converter.json
SHP-2026-1201-001  85044095  Static converter, industrial power supply unit  480000.0 USD
market United States  assessed 2026-12-01  snapshot dutypath-rules-2026-11-22 (2026-11-22, FRESH)

KORUS   origin NOT_ORIGINATING   rule 8504.32
        M1 (85043140, CN) -[CTSH]-> inside group 8504.10 to 8504.50
        rate   0.0% (staged, category A eliminated on entry into force)
        claim  blocked: origin: NOT_ORIGINATING

RCEP    origin ORIGINATING       rule 85.04
        rate   not in snapshot: this agreement covers JP, not US
        docs   EXPIRED approval expired on 2026-08-31, before the claim date 2026-12-01
        claim  blocked: market: this agreement covers JP

MFN     1.5% (agreement_base_rate, as of 2006-01-01)

decision  NO CLAIM
duty      7200.0 USD
exposure  7200.0 USD
claim window  2027-12-08 (OPEN, 협정관세 사후적용 신청기간 1년)
```

Same bill of materials, two agreements, two verdicts. The Chinese transformer
sits inside the group the KORUS rule excludes, so Korea to the United States
pays. Under RCEP the same transformer is a party material, so the value content
is 100 percent and the good originates; the RCEP rate for a shipment into the
United States does not exist because RCEP does not cover that market, and the
report says so instead of printing a number.

## How it uses Relate

**Mode: single file (`.rl`).** `store/dutypath-rules.rl` is opened read only,
and it is the only persistent thing in the project. Reasons:

* The rule book has to travel. A customs broker carries it to a client site, a
  laptop in an office with no network opens it, and a single file copies, diffs
  and versions like a document.
* A directory store would let the file set drift. One file is one snapshot, and
  a snapshot is what a rate table is; the hash of that file is a fact a reader
  can quote.
* The engine refuses writes on this connection, so the zero leak claim is a
  property of the open mode and not only of careful code.

The shipment itself is loaded into a **separate in memory graph** for the run
and closed with it. The material list never has a file to leak from.

**What the graph models.**

| Node | What it is | Count in this snapshot |
| --- | --- | --- |
| `Chapter`, `Heading`, `Subheading` | the nomenclature, as a tree | 3, 148, 611 |
| `OriginRule` | one product specific origin rule, with the sentence it came from | 330 |
| `RateLine` | one tariff line: base rate, staging category, source | 847 |
| `Agreement` | KORUS, RCEP, and the two agreements the snapshot does not cover | 5 |
| `DeadlineRule` | a claim window, with its citation | 1 |
| `Hs6Rate` | applied MFN at six digits, with the number of lines behind it | 12 |
| `Source` | the document a row came from: title, URL, date | 6 |
| `Snapshot` | the snapshot's own date, version and age limit | 1 |

Relationships are the ones a reader can say out loud: `(Subheading)-[:IN_HEADING]->(Heading)`,
`(Heading)-[:IN_CHAPTER]->(Chapter)`, `(OriginRule)-[:FOR]->(Agreement)`,
`(RateLine)-[:FOR]->(Subheading)`, and every rule and rate `-[:CITED_FROM]->(Source)`.

Three things are answered by walking the graph, not by a lookup table:

* **Which rule applies.** One query matches a good's code against the rule
  intervals: an exact subheading, a range, a heading, a chapter. A range and a
  line live in the same comparison space because every code is normalised to
  eight digits at build time.
* **Which provisions an exclusion covers.** "Outside subheading 8504.10 through
  8504.50" is an interval test against the material's code. This is the step a
  string compare gets wrong, and it is the step that decides the converter case.
* **What the rate is on a date.** The staging category is a row, the base rate
  is a row, and the arithmetic is Annex 2-B paragraph 1 read as a function of
  the assessment date.

A hub holds the whole corpus and serves one market with a single query,
`neo4j/pull_rules.cypher`; `dutypath pull-query --market US` prints it. The
snapshot in this repository is the result of that pull, with its date on it.

## Setup and run

Requires Python 3.10 or newer. Relate is Apache 2.0 and runs locally; there is
no account, no server and no network call at run time.

```
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# the committed snapshot is already in the repository
dutypath info
dutypath assess --shipment fixtures/shipment-8501-motor.json
dutypath assess --shipment fixtures/shipment-3901-polymer.json
dutypath verify-zero-leak --shipment fixtures/shipment-8504-converter.json
dutypath footprint
pytest
```

To rebuild the snapshot from the documents:

```
pip install -e ".[extract]"
python scripts/extract_sources.py --pdf-dir <directory with the four PDFs> --out data/extract-2026-11-22
python scripts/fetch_mfn.py --out data/extract-2026-11-22/us_mfn_applied.json
dutypath seed
```

`docs/SOURCES.md` lists the four documents, their URLs, their download date and
their sha256, so the extraction can be repeated and checked.

## What the snapshot covers, and what it does not

Coverage is a number, not a claim.

| Scope | Covered | Not covered |
| --- | --- | --- |
| HS chapters | 39, 84, 85 | the other 94 chapters return `not covered in this snapshot` |
| KORUS | rules for the three chapters, tariff lines with base rate and staging | nothing in these chapters |
| RCEP | product specific rules for the three chapters | tariff schedules: no rate is priced |
| Korea-EU, Korea-Turkiye | listed as agreements so the gap is visible | rules and rates |
| Markets | United States | everything else |
| Duty types | ad valorem percentages | specific duties (cents per kilogram and the like) |

Two boundaries deserve their own line.

**The MFN baseline.** Where the applied MFN of a six digit line is a single
tariff line, the snapshot uses that applied rate and says so. Where an HTS8 line
exists in the KORUS schedule but the applied rate after 2006 does not, the
report falls back to the base rate recorded in that schedule, dated
2006-01-01, and says so. It never averages several tariff lines into a rate.

**Rule sentences.** 330 rules were extracted; the engine reads alternatives,
exclusions, value content thresholds and one weight condition. A rule it cannot
read produces `UNDECIDABLE` with that sentence quoted, not a default verdict.
`dutypath info` prints the structured and unstructured counts.

## Where the data lives

| What | Where | Leaves the machine |
| --- | --- | --- |
| the rule snapshot | `store/dutypath-rules.rl`, committed | no |
| the extracted source rows | `data/extract-2026-11-22/*.json`, committed | no |
| the source documents | not committed; URLs and sha256 in `docs/SOURCES.md` | no |
| a shipment | the file you pass to `assess`, read into memory | no |
| a verdict | standard output | no |

Nothing in this repository is client data. The fixtures are synthetic, written
to exercise a rule, and name no company.

## Limits and honest statements

* This is a pre-declaration check, not a legal opinion and not a customs
  declaration. A licensed customs broker signs the entry.
* Rates are only as fresh as the snapshot row they came from. Every rate row
  carries its source and date, and `dutypath freshness` says when the snapshot
  has aged past its own limit.
* The three chapter limit is deliberate. A snapshot that claims 97 chapters and
  gets one wrong is worse than a snapshot that covers three and says so.
* Origin rules are read from the agreement text by a parser. Where the parse is
  incomplete the verdict is `UNDECIDABLE`; the counts are printed by `info` and
  recorded in `docs/BENCHMARK-FOOTPRINT.md`.

## AI use

This project was built with an AI coding assistant (Claude based agent
environment) for code, tests and documentation, working from public documents.
No AI model runs inside DutyPath: every verdict is deterministic Cypher and
Python over the committed snapshot, so the same input gives the same output
offline. Every rate and rule in the snapshot cites the document it came from.

## Licence

Apache-2.0. See `LICENSE` and `NOTICE`. The rule texts and tariff schedules
belong to their publishers and are reproduced here as cited extracts for a
compliance check.
