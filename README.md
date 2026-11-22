# DutyPath

Three markets, one bill of materials, and the answer to the question that
decides the invoice: under which agreement can this good claim a preference,
what does the answer cost if it cannot, and until when can the money be
recovered.

The tool stores no client data. The file it ships is the public rulebook:
tariff codes, origin rules, duty rates, and the schedules that say what the rate
is on a date.

It does not stop at what is missing. It prices the gap: which agreement wins,
how much it saves, who the parts exclude, and until when a refund can be
claimed.

The rules are pulled from a Neo4j hub as a versioned snapshot, and the verdict
says when that snapshot is too old to trust.

---

## Use case

A Korean exporter is about to ship a static converter to a customer in Europe,
and the same converter is also quoted to a buyer in the United States and one
in Japan. One bill of materials, three markets, three different questions.

```
$ dutypath compare --shipment fixtures/shipment-8504-converter.json
SHP-2026-1201-001  Static converter, industrial power supply unit
declared 480000.0 USD   assessed 2026-12-01   snapshot dutypath-rules-2026-11-22 (FRESH)

market  code        origin            pref    mfn    duty      route
US      85044095    NOT_ORIGINATING    0.0%   1.5%    7200.0  MFN: origin: NOT_ORIGINATING
EU      85044090    ORIGINATING        0.0%   3.3%       0.0  CLAIM
JP      850440090   ORIGINATING        0.0%   0.0%       0.0  MFN: document: the approved exporter approval expired before the claim date

best route   EU (EUKOR), duty 0.0 USD, saving 15840.0 USD
spread       7200.0 USD between EU and US
claim window 2027-12-08 (OPEN, 협정관세 사후적용 신청기간 1년)
```

The Chinese transformer inside the converter is in the group the KORUS rule
excludes, so the American entry pays 7,200 dollars. The EU rule for 8504 asks a
different question, a ceiling on the value of non originating material, and the
same transformer sits inside it, so the European entry pays nothing and saves
15,840. Japan is duty free on the line either way, and the RCEP approval on file
ran out three months before the entry date.

Three answers, and they are not the same kind of answer.

* **ORIGINATING.** The rule is met, the material that satisfied it is named, and
  the duty is computed at the preferential rate.
* **NOT ORIGINATING.** The rule is not met, and the part that breaks it is named
  with the reason: a transformer in the same heading the rule excludes, a
  separator from the same heading as the good.
* **UNDECIDABLE.** The snapshot cannot answer. Not "probably fine", not a
  default: the missing piece is named, for example the polymer weight share a
  KORUS rule asks for and the bill of materials does not carry, a material line
  with no tariff classification, a material whose code is written at heading
  level where the rule tests subheadings, or a rule sentence this parser could
  not read. The number of such sentences is printed by `dutypath info`.

The third answer is the one that matters in practice. A missing weight share is
a phone call or a re-test. A tool that guesses instead turns that into an
assessment years later. The same rule applies to the exporter's own file: a
material with no classification is a question back, not a pass, and a declared
value of zero or less is an input error with the field named, not a duty of
zero.

What it does not do: it is not legal advice, it is not a customs declaration,
and it does not decide for the exporter. It prices the decision.

## The three markets, and what each one asks

| Market | Agreement | Origin rule source | Rate source | Approved exporter |
| --- | --- | --- | --- | --- |
| United States | KORUS | Annex 6-A (222 rules) | Annex 2-B, base rate and category A to K (847 lines) | not required |
| European Union | Korea-EU | Protocol Annex II (71 rules) | Annex 2-A, base rate and numbered category (1,726 lines) | required |
| Japan | RCEP | Annex 3A (108 rules) | Annex I, the printed rate for each year (1,270 lines) | required |

The three schedules do not speak the same language. KORUS prints a letter and
Annex 2-B says what the letter does. The EU prints a number and Annex 2-A says
the number is the count of annual cuts. Japan prints the rate for every year, so
nothing is computed and nothing is interpolated: the cell for that year is the
answer, including the cells that read `U`, which is the schedule's own mark for
a line it excludes for Korean goods.

## How it uses Relate

**Mode: single file (`.rl`).** `store/dutypath-rules.rl` is opened read only,
and it is the only persistent thing in the project. Reasons:

* The rule book has to travel. A customs broker carries it to a client site, a
  laptop in an office with no network opens it, and a single file copies, diffs
  and versions like a document.
* A directory store would let the file set drift. One file is one snapshot, and
  a snapshot is what a rate table is; the hash of that file is a fact a reader
  can quote.
* The engine refuses to change it. The file is opened with `read_only=True`,
  and the MCP reader refuses any statement that contains a writing clause
  before the statement reaches the store, naming the clause it found. Both
  halves are tested: `tests/test_regressions.py` sends `CREATE`, `SET`,
  `DETACH DELETE` and a two statement string, and finds the store unchanged
  after each.

The shipment itself is loaded into a **separate in memory graph** for the run
and closed with it. The material list never has a file to leak from.

**What the graph models.**

| Node | What it is | Count in this snapshot |
| --- | --- | --- |
| `Chapter`, `Heading`, `Subheading` | the nomenclature, as a tree | 3, 161, 965 |
| `OriginRule` | one product specific origin rule, with the sentence it came from | 401 |
| `RateLine` | one tariff line: base rate, staging, and for Japan the printed years | 3,843 |
| `Agreement` | the agreement a rule or a rate belongs to: MFN as the baseline, KORUS, RCEP, EUKOR, and TURKOR which the snapshot names but does not cover | 5 |
| `DeadlineRule` | a claim window, with its citation | 1 |
| `Hs6Rate` | applied MFN at six digits, with the number of lines behind it | 12 |
| `Source` | the document a row came from: title, URL, date | 9 |
| `Snapshot` | the snapshot's own date, version and age limit | 1 |

Relationships are the ones a reader can say out loud: `(Subheading)-[:IN_HEADING]->(Heading)`,
`(Heading)-[:IN_CHAPTER]->(Chapter)`, `(OriginRule)-[:FOR]->(Agreement)`,
`(RateLine)-[:FOR]->(Subheading)`, and every rule and rate `-[:CITED_FROM]->(Source)`.
The file is 5.16 MB, 5,401 nodes and 13,490 relationships.

The graph answers three questions, and the engine answers the rest:

* **Which rule applies.** One query matches a good's code against the rule
  intervals: an exact subheading, a range, a heading, a chapter. A range and a
  line live in the same comparison space because every code is normalised to
  eight digits at build time.
* **What the rate is on a date.** The staging category is a row, the base rate
  is a row, and the arithmetic is the annex read as a function of the entry
  date. For Japan the row carries the whole printed schedule, so the graph
  answers with the cell, not with a formula.
* **What the rule came from, and what sits above the line.** Every rule and rate
  is one hop from its source document, and a subheading is one hop from its
  heading and chapter.

What the graph does not do is decide the verdict. The exclusion interval, the
change of heading or subheading, the value content and the weight share are
compared in Python, on the material codes, where the three answers (met, not
met, cannot tell) are easier to give and to test than in a traversal. The
traversal that reads a good's hierarchy is in `cypher/04-hierarchy-above-a-good.cypher`
and the same walk is done in the shipment's own graph; the exclusion interval is
`cypher/02-exclusion-interval.cypher`. `docs/MCP-SCENARIO.md` shows the rule
lookup and the verdict side by side, so a reader can see which part answers what.

A hub holds the whole corpus and serves one market with one statement,
`neo4j/pull_rules.cypher`; `dutypath pull-query --market US` prints it and
`dutypath pull-check --market US` runs it against this snapshot and counts what
came down. The statement is a union of one branch per part, so a market returns
222 rules and 847 rate lines as 1,072 rows. The snapshot in this repository is
the result of that pull, with its date on it.

## Setup and run

Requires Python 3.10 or newer. Relate is Apache 2.0 and runs locally; there is
no account, no server and no network call at run time.

```
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# the committed snapshot is already in the repository
dutypath info
dutypath compare --shipment fixtures/shipment-8504-converter.json
dutypath assess --shipment fixtures/shipment-8501-motor.json
dutypath verify-zero-leak --shipment fixtures/shipment-8504-converter.json
dutypath footprint
dutypath pull-check --market US
dutypath mcp --store store/dutypath-rules.rl
pytest
```

To rebuild the snapshot from the documents:

```
pip install -e ".[extract]"
python scripts/extract_sources.py --pdf-dir <four KORUS and RCEP PDFs> --out data/extract-2026-11-22
python scripts/extract_eu_schedule.py --pdf <EU schedule, Korean copy> --out data/extract-2026-11-22/eukor_rates.json
python scripts/extract_rcep_japan.py --xlsx <schedule of Japan> --out data/extract-2026-11-22/rcep_japan_rates.json
python scripts/build_eukor_psr.py --pdf <rules of origin protocol> --out data/extract-2026-11-22/eukor_psr.json
python scripts/fetch_mfn.py --out data/extract-2026-11-22/us_mfn_applied.json
dutypath seed
```

`docs/SOURCES.md` lists the nine documents, their URLs, their download date and
their sha256, so the extraction can be repeated and checked.

## The screen

`docs/demo/index.html` opens from the file system and makes no network call. It
shows one shipment, the three markets, the rate on a date the reader picks, the
duty on a value the reader types, the material the rule excludes, and the date
until which a refund can be claimed. The rate arithmetic runs in the browser
from the schedule rows; the origin verdict comes from the engine, and the page
says which is which. Selecting the `store/dutypath-rules.rl` file makes the page
hash it with WebCrypto and compare it with the hash the bundle was built from.

`python scripts/check_demo.py` opens it in Chromium at 1440 and 390 pixels,
checks that neither width scrolls sideways, that the visible text carries none
of the characters machine written text gives itself away with, and that the
page's own rate arithmetic agrees with `duty.line_rate` for every rate row in
the bundle on seven dates. It needs Playwright, which the dev extras do not
install because a plain `pytest` run should not depend on a browser:
`pip install playwright && playwright install chromium`. The screenshots under
`docs/demo/screenshots/` are its output.

## The benchmark

`docs/BENCHMARK-EVAL.md` scores three methods on twelve goods and thirty six
hand written labels: keyword matching gets 63.9 percent, a flat rule table 47.2,
and this engine 100, with the exception labels (an excluded interval, a value
ceiling, a missing value, a shared heading, a second alternative, an agreement
with no rule) captured 30 out of 30. The first run of that harness disagreed
with the hand labels on six labels, and all six were engine defects that are now
fixed and tested. `python scripts/benchmark.py` regenerates the table.

## What the snapshot covers, and what it does not

Coverage is a number, not a claim.

| Scope | Covered | Not covered |
| --- | --- | --- |
| HS chapters | 39, 84, 85 | the other 94 chapters return `not covered in this snapshot` |
| KORUS | rules for 929 of the 965 subheadings, rates for the three chapters | 36 subheadings the annex leaves without a rule, listed in `docs/BENCHMARK-FOOTPRINT.md` |
| Korea-EU | rules and the EU schedule for the three chapters | the Korean side of the schedule |
| RCEP | rules for 682 of the 965 subheadings, Japan's schedule | 283 subheadings the annex leaves without a rule; the schedules of the other fourteen parties |
| Markets | United States, European Union, Japan | everything else |
| Duty types | ad valorem percentages | specific and compound duties (yen per kilogram, and the like) |

Four boundaries deserve their own line.

**The MFN baseline.** On the American side, where the applied MFN of a six digit
line is a single tariff line, the snapshot uses that applied rate and says so;
otherwise it falls back to the base rate recorded in the agreement schedule,
dated 2006-01-01, and says so. On the EU and Japan side the baseline is the base
rate printed in that schedule, and the row says which date that rate speaks for.
It never averages several tariff lines into a rate.

**Rule sentences.** 401 rules were extracted or transcribed. The engine reads
alternatives, exclusions, exclusion intervals (including "outside that group"
and "except from subheading X through Y"), value content thresholds, a
permitted source subheading and one weight condition. A rule sentence it cannot
read, or a condition that needs a classification or a value the shipment does
not carry, produces `UNDECIDABLE` with the sentence or the material named.
`dutypath info` prints the structured and unstructured counts and names every
alternative that could not be read: in this snapshot three rules have one each
(OR-0039, OR-0174, OR-0329), covering ten subheadings, and those subheadings now
answer `UNDECIDABLE` where an earlier build answered `ORIGINATING`.

**Two nomenclatures, one comparison.** A good's line differs by market, so the
shipment states its code in each market's nomenclature. When it states none for
a market, that market is undecidable and names the missing code; the tool does
not price a German entry on an American tariff line.

**RCEP's gap.** Annex 3A as extracted lists 108 rules for the three chapters, so
682 of the 965 subheadings resolve. A good outside that set is undecidable under
RCEP and priced everywhere else.

## Where the data lives

| What | Where | Leaves the machine |
| --- | --- | --- |
| the rule snapshot | `store/dutypath-rules.rl`, committed | no |
| the extracted source rows | `data/extract-2026-11-22/*.json`, committed | no |
| the source documents | not committed; URLs and sha256 in `docs/SOURCES.md` | no |
| a shipment | the file you pass to `assess`, `compare` or the MCP server, read into memory | no |
| a verdict | standard output | no |

Nothing in this repository is client data. The fixtures and the twelve benchmark
goods are synthetic, written to exercise a rule, and name no company.

## Limits and honest statements

* This is a pre-declaration check, not a legal opinion and not a customs
  declaration. A licensed customs broker signs the entry.
* Rates are only as fresh as the snapshot row they came from. Every rate row
  carries its source and date, and `dutypath freshness` says when the snapshot
  has aged past its own limit.
* The three chapter limit is deliberate. A snapshot that claims 97 chapters and
  gets one wrong is worse than a snapshot that covers three and says so.
* Origin rules are read from agreement text by a parser, or transcribed from a
  table and checked against it. Where the read is incomplete the verdict is
  `UNDECIDABLE`; the counts are printed by `info` and recorded in
  `docs/BENCHMARK-FOOTPRINT.md`.
* The EU schedule is parsed from the Korean language copy of the same table,
  because the English copy prints its digits through a font with no Unicode
  mapping. Both hashes are in `docs/SOURCES.md`.
* The value content on the build-up method counts a material whose origin is a
  party as a party material. Whether that material itself meets an origin rule
  is not in the bill of materials this snapshot reads, so the figure is the
  agreement's own party content and not the accumulated content of a supply
  chain.
* Where a rule both limits the sources and asks for a value content ("from
  subheading 8483.90, provided that there is a regional value content of not
  less than 40 percent"), the alternative is read as the value content alone.
  Every source that clause would bar is already barred by the other
  alternative's exclusions, which is why the simpler reading does not change a
  verdict in this snapshot.

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
