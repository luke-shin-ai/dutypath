# DutyPath

Three markets, one bill of materials, and the answer to the question that
decides the invoice: under which agreement can this good claim a preference,
what does the answer cost if it cannot, and until when can the money be
recovered.

## 60 seconds

```
pip install -e ".[dev]"
dutypath compare --shipment fixtures/shipment-8504-converter.json
```

That is the whole setup: one install, one command, no account, no network call,
and the verdict prints in about a second. Two more commands show the rest of the
claim without reading any further:

```
dutypath verify-zero-leak --shipment fixtures/shipment-8504-converter.json
pytest -q
```

The first proves the rule file came back byte for byte after an assessment. The
second runs the suite on a bare install.

In a browser, with nothing to install:
**https://luke-shin-ai.github.io/dutypath/demo/**
The page root, **https://luke-shin-ai.github.io/dutypath/**, forwards there.

The five shipment files under `fixtures/` are synthetic. They were written to
exercise a rule and they name no company, no client and no real shipment; the
hackathon's rules on data and confidentiality are met by having nothing
confidential in the first place.

The tool stores no client data. The file it ships is the public rulebook:
tariff codes, origin rules, duty rates, and the schedules that say what the rate
is on a date.

It does not stop at what is missing. It prices the gap: which agreement wins,
how much it saves, who the parts exclude, and until when a refund can be
claimed.

The rulebook is one prebuilt `.rl` snapshot committed with the code, dated and
versioned, so an assessment needs no database and no network; `dutypath
freshness` says when that snapshot is too old to trust. Building the same rows
from a hub is a separate, optional step: `neo4j/pull_rules.cypher` is the
statement, and `dutypath pull-check` runs it against this snapshot so a reader
can see it complete and count what it returns. The default answer is the local
file, not a live hub query.

---

## Use case

A Korean exporter is about to ship a static converter to a customer in Europe,
and the same converter is also quoted to a buyer in the United States and one
in Japan. One bill of materials, three markets, three different questions.

```
$ dutypath compare --shipment fixtures/shipment-8504-converter.json
SHP-2026-1201-001  Static converter, industrial power supply unit
declared 480000.0 USD   assessed 2026-12-08   snapshot dutypath-rules-2026-11-22 (FRESH)

market  code        origin            pref    mfn    duty      route
US      85044095    NOT_ORIGINATING    0.0%   1.5%    7200.0  MFN: origin: NOT_ORIGINATING
EU      85044090    ORIGINATING        0.0%   3.3%       0.0  CLAIM
JP      850440090   ORIGINATING        0.0%   0.0%       0.0  MFN: document: the approved exporter approval expired before the claim date

best route   EU (EUKOR), duty 0.0 USD, saving 15840.0 USD
spread       7200.0 USD between EU and US
claim window 2027-12-08 (OPEN, 협정관세 사후적용 신청기간 1년)
note         United States applied MFN rate: the values are the WITS figures for 2023, as of 2023-12-31, 1057 days before the snapshot date 2026-11-22
note         The post import claim window: the period comes from a Ministry of Economy and Finance paper dated 2025-02-12, 648 days before the snapshot date 2026-11-22
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
| European Union | Korea-EU | Protocol Annex II (71 rules) | Annex 2-A, base rate and numbered category (1,726 lines) | required above EUR 6,000 |
| Japan | RCEP | Annex 3A (108 rules) | Annex I, the printed rate for each year (1,278 lines) | required |

The three schedules do not speak the same language. KORUS prints a letter and
Annex 2-B says what the letter does. The EU prints a number and Annex 2-A says
the number is the count of annual cuts. Japan prints the rate for every year, so
nothing is computed and nothing is interpolated: the cell for that year is the
answer, including the cells that read `U`, which is the schedule's own mark for
a line it excludes for Korean goods.

Japan's schedule also prints more than one row for some lines, under a Remarks
column that names the parties the row is written for. Each row is kept with its
treatment: `KR` when the remark names Korea, `ALL` when the row has no remark and
speaks for every party, and `OTHER-<parties>` when it names only other parties.
A Korean shipment is priced on the `KR` row when there is one, else on the `ALL`
row, and never on a row written for another party. On 3901.20.010 that is the
difference between a free rate and the compound duty Korea actually pays, so the
build refuses to put two rows under one treatment and the snapshot carries all
1,278 rows of the extract.

## How this maps to the judging criteria

The Devpost Overview weights five criteria: Relate and connected context 30,
Functionality and completeness 25, Usefulness 20, Documentation and
reproducibility 15, Creativity 10. The rules section of the same page lists the
same five with equal weight. This entry does not pick one list and ignore the
other; each row below names the section a judge can check, so the same work
scores under either reading.

| Criterion | Where it is answered | What to check |
| --- | --- | --- |
| Relate and connected context | `## How it uses Relate`, `cypher/`, `docs/MCP-SCENARIO.md` | one file store, 5,454 nodes and 13,559 relationships, the rule to interval to material join, the same graph rebuilt and walked in the browser, the same file over MCP |
| Functionality and completeness | `## 60 seconds`, `## The three markets`, `## What the snapshot covers` | five fixtures through `dutypath compare`, 182 tests, the three verdicts and the case that answers `UNDECIDABLE` |
| Usefulness | `## Use case`, `## Limits and honest statements` | duty, saving and claim window per market, priced on the entry date |
| Documentation and reproducibility | `## Setup and run`, `docs/SOURCES.md`, `docs/BENCHMARK-EVAL.md` | nine documents with URL and sha256, `python scripts/benchmark.py` |
| Creativity | `## The three markets`, `## What the snapshot covers` | three schedules read in their own format, the provisions a rule names kept as interval nodes |

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
| `HsInterval` | one provision a rule excludes, or the group it excludes, as an interval the join tests | 45 |
| `RateLine` | one tariff line and one partner treatment: base rate, staging, and for Japan the printed years | 3,851 |
| `Agreement` | the agreement a rule or a rate belongs to: MFN as the baseline, KORUS, RCEP, EUKOR, and TURKOR which the snapshot names but does not cover | 5 |
| `DeadlineRule` | a claim window, with its citation | 1 |
| `Hs6Rate` | applied MFN at six digits, with the number of lines behind it | 12 |
| `Source` | the document a row came from: title, URL, date | 9 |
| `Snapshot` | the snapshot's own date, version and age limit | 1 |

Relationships are the ones a reader can say out loud: `(Subheading)-[:IN_HEADING]->(Heading)`,
`(Heading)-[:IN_CHAPTER]->(Chapter)`, `(OriginRule)-[:FOR]->(Agreement)`,
`(OriginRule)-[:EXCLUDES]->(HsInterval)`, `(RateLine)-[:FOR]->(Subheading)`, and every rule
and rate `-[:CITED_FROM]->(Source)`.
The file is 5.45 MB (5.20 MiB), 5,454 nodes and 13,559 relationships.

The graph answers four questions, and the engine answers the rest:

* **Which rule applies, and what prices it.** One traversal per market matches a
good's code against the rule intervals and joins the rate line for the same
Agreement node, so the rule, the line and both cited sources arrive together
(`rules.market_context`). Two separate lookups became one walk. The rule
interval match inside it takes 0.762 ms median over 401 rules on the committed
snapshot (`docs/BENCHMARK-FOOTPRINT.md`, Query time).
* **Which materials a rule excludes.** The provisions a rule bars are `HsInterval`
nodes hanging off the rule, one per alternative and in the order the sentence
names them. The material list goes into that join as codes, and the answer for
each material comes back inside, outside or across an interval
(`rules.material_intervals`, `cypher/07-material-against-rule.cypher`).
* **What the rate is on a date.** The staging category is a row, the base rate
  is a row, and the arithmetic is the annex read as a function of the entry
  date. For Japan the row carries the whole printed schedule, so the graph
  answers with the cell, not with a formula.
* **What the rule came from, and what sits above the line.** Every rule and rate
  is one hop from its source document, and a subheading is one hop from its
  heading and chapter.

What the graph does not do is decide the verdict. A change of heading or
subheading, the value content and the weight share are compared on the material
codes, where the three answers (met, not met, cannot tell) are easier to give and
to test than in a traversal. The engine makes that comparison in Python
(`src/dutypath/origin.py`); the demo page makes the same one in JavaScript over
the rows the browser engine returns, and prints how many of its answers match
the engine's own. A relational schema could
express these two queries as well. What the graph changes is the number of keys
a reader has to trust: a rule names the provisions it excludes as edges on the
rule itself, with the alternative number on the edge, so
`cypher/07-material-against-rule.cypher` starts at one rule, walks to the
intervals it points at and returns one row per material and interval that are
not disjoint, and every rule and rate reaches its source document in one hop
instead of a join on a citation table.
`tests/test_regressions.py::test_the_interval_join_agrees_with_the_python_comparison`
reads the same intervals both ways and checks the graph's relation against
`codes.interval_relation` for every material, so the traversal and the Python
comparison cannot drift apart. The traversal that reads a
good's hierarchy is in `cypher/04-hierarchy-above-a-good.cypher`
and the same walk is done in the shipment's own graph; the interval files are
`cypher/02-exclusion-interval.cypher` and `cypher/07-material-against-rule.cypher`.
The demo's picture reads `cypher/08-rule-attachment.cypher` for the rule with its
intervals and source, and `cypher/09-classification-spine.cypher` for the
subheading, heading and chapter of every code on it, so the picture and the CLI
answer from the same statements.
`docs/MCP-SCENARIO.md` shows the rule lookup and the verdict side by side, so a
reader can see which part answers what.

The rows in this snapshot were first built from an extraction of the nine public
documents in `docs/SOURCES.md`, then written to one `.rl` file. Serving the same
rows from a hub that holds the whole corpus is an optional path, not the default:
`neo4j/pull_rules.cypher` is the statement, `dutypath pull-query --market US`
prints it and `dutypath pull-check --market US` runs it against this snapshot and
counts what came down. The statement is a union of one branch per part, so a
market returns 222 rules and 847 rate lines as 1,072 rows. This repository holds
no hub, no Aura instance and no server, and no verdict in it calls one. The pull
statement was run against the committed file, which shows that it completes and
returns the rows the label counts predict; it does not show that a remote hub
was queried. That is the mode the hackathon asks for, a persistent Relate store
that travels with the code, and a judge who clones this repository can run every
number here without an account.

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

`docs/demo/index.html` shows one shipment, the three markets, the rate on a date
the reader picks, the duty on a value the reader types, the material the rule
excludes, and the date until which a refund can be claimed. The rate arithmetic
runs in the browser from the schedule rows; the verdict cards are the engine's
build time answers, and the page says which is which. Selecting the
`store/dutypath-rules.rl` file makes the page hash it with WebCrypto and compare
it with the hash the bundle was built from.

The first screen states the two things a reader would otherwise have to work
out: a one line legend for `CLAIM`, `MFN`, `ORIGINATING`, `NOT ORIGINATING` and
`UNDECIDABLE`, and a notice that the verdict cards are a build time bundle.

### The file a reader can check

The committed rule book is one file, and its hash is the fact a reader can quote
back:

```
$ sha256sum store/dutypath-rules.rl
200d613c08a4c4c65cbff74d17ab46619e76f6032f9ffba9640999a90262aec8  store/dutypath-rules.rl
$ stat -c %s store/dutypath-rules.rl
5451776
```

That is 5,451,776 bytes (5.20 MiB), and the page prints the same two numbers
under Snapshot. Selecting the committed file in the Rule file check box hashes
it in the browser with WebCrypto and says `rule file matches`; the same hash is
written into `docs/demo/dutypath-demo.json` and `docs/demo/wasm/dutypath-graph.json`
as the identity of the snapshot each was built from. `tests/test_demo.py` fails
if the number written here stops matching the file, and the shipped build never
opens the file for writing: every read goes through a connection opened read
only, and the exporter and the bundle builder read a temporary copy.

### The graph, running in the tab

Below the verdict cards the page runs the engine itself. A worker loads
`@relate/relate-wasm` 1.3.0 (Apache-2.0, the package Neo4j publishes), rebuilds
the snapshot's 5,454 nodes and 13,559 relationships in memory, and answers the
committed `cypher/` files for the shipment on screen: the rule for the good, the
rate row and its source, the heading and chapter above it, the agreement
coverage, and the material against every interval the rule excludes. It reports
what it built, how long the build took, and which package version did it.

Each value the engine returns is compared with the bundle the page was built
from, and the panel states the score (15 of 15 on every fixture). The two cannot
disagree without the page saying so.

### The path, and the key material that moves it

The same panel draws the walk each rule takes for the bill of materials on
screen: the shipment and its material lines on the left, then the classification
the code sits in, the origin rule with the intervals it excludes, the agreement
line and the rate, and the answer. Everything to the right of the bill of
materials is a row the engine returned: `cypher/08-rule-attachment.cypher`
brings back the rule, its exclusion interval nodes and its cited source,
`cypher/09-classification-spine.cypher` brings back the subheading, heading and
chapter of each code through the graph's own `IN_HEADING` and `IN_CHAPTER`
edges, and `cypher/07-material-against-rule.cypher` puts each material inside,
outside or across every interval the rule names. The bill of materials itself is
drawn dashed, because no material line is ever written to the store.
The verdict and the duty are computed on the page from those rows, by the same
comparison the Python engine makes (`docs/demo/origin-eval.js` against
`src/dutypath/origin.py`), and the line under the pictures states how many of
the three verdicts and three duties agree with the engine's own answer for the
same state.

One checkbox swaps the key material for its other sourcing option. The default
shipment is a moulded plastic bracket worth 120,000 USD; its M1 line is
polyethylene of heading 3901 at 45,000, and the swap makes it a moulded shell of
heading 3926, the good's own heading, at 75,000. One line changes, and all three
markets answer again because the three rules ask three different questions: the
KORUS rule wants every non party material to change heading (M1 now does not),
the EU rule wants the non party value under 50 percent (it is now 62.5), and the
RCEP rule asks for the heading change or 40 percent value content (neither holds
now). The verdicts go from `ORIGINATING` in all three to `NOT ORIGINATING` in
all three, and the duty moves from 0, 0 and 2,520 USD to 6,360, 7,800 and 4,680
USD. The path pictures light the condition that failed, in each market's own
terms, so the scene shows the graph deciding and the invoice following it rather
than a table changing.

Why the tab rebuilds the graph instead of opening the file: the wasm package
offers `new RelateDb()` for an in-memory database and `RelateDb.open("opfs://")`
for its own browser store, and no call that opens an existing `.rl` file. The
rows come from `scripts/build_wasm_seed.py`, which reads the snapshot and writes
`docs/demo/wasm/dutypath-graph.json` with the source path, byte count and
sha256. The `.rl` file remains the artifact the CLI, the MCP server and a native
`relate` run open, and `tests/test_wasm_seed.py` rebuilds the graph from the
export and holds its answers to the store's.

`python scripts/check_demo.py` opens the static page in Chromium at 1440 and 390
pixels, checks that neither width scrolls sideways, that the visible text
carries none of the characters machine written text gives itself away with, and
that the page's own rate arithmetic agrees with `duty.line_rate` for every rate
row in the bundle on seven dates. `python scripts/check_wasm_demo.py` serves the
repository over http, waits for the panel to finish, and fails if the engine and
the bundle disagree on any value, if any of the three path pictures is missing,
if the three verdicts it draws differ from the bundle's, if the key material
swap does not move all three markets, or if what the page computes after the
swap differs from the engine's own answer for that state. It runs both at 1440
and at 390 pixels, and on a second shipment that has no second state, where the
swap is refused instead of offered. Both need Playwright, which the dev extras
do not install because a plain `pytest` run should not depend on a browser:
`pip install playwright && playwright install chromium`. The screenshots under
`docs/demo/screenshots/` are their output, including the shipment as declared
and after the swap at both widths.

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

### The MCP boundary, stated

Over MCP the material list travels as a tool argument. The graph keeps none of
it: no `Shipment`, `Material`, `Good`, `Party` or `Verdict` node is written, and
`verify-zero-leak` compares the file's sha256 before and after to show it. What
the boundary does cover is the file and the graph, not the conversation: an
agent that sends a bill of materials to `compare_markets` has put that bill of
materials into its own context, and an MCP host may keep that transcript. So the
tool stores no client data and cannot leak what it never held; the agent holding
the bill of materials is the place to look for it. The server also refuses any
statement that would write before it reaches the store, so a session cannot
leave a node behind either. That reader walks a statement once and skips three
kinds of text as a whole: a string literal, a backtick quoted identifier, and a
comment. All three have to be kept apart, because any one of them can carry a
word that looks like a clause: an address inside a literal cannot hide the
clause written after it, an apostrophe inside `` `a'` `` is not the start of a
literal, and a clause inside a comment is not a clause. `tests/test_regressions.py`
holds the reader to that with the statements a review used to get past the
earlier version, and also checks the second line of defence directly: the order
in which the engine itself accepts and then refuses a write on a connection it
opened read only.

Two limits keep that surface small. `shipment_path` has to resolve inside the
directory the server was started in, so a path that climbs out of it, or a
symlink pointing there, is refused before a file is opened; a shipment passed
as an object is unaffected. `read_cypher` returns at most 500 rows per call and
reports whether it stopped short, so a statement over the whole graph answers
with a page and not with the graph.

## Limits and honest statements

* This is a pre-declaration check, not a legal opinion and not a customs
  declaration. A licensed customs broker signs the entry.
* Rates are only as fresh as the snapshot row they came from. Every rate row
  carries its source and date, and `dutypath freshness` says when the snapshot
  has aged past its own limit.
* The rate and the documents are read on the import date, or on a date you
  pass to `compare`, and not on the export date. A shipment that leaves in
  December and is entered in January is priced in January's year of the
  schedule.
* The EU party list is the list of the day being assessed: Croatia from
  2013-07-01, the United Kingdom until 2020-01-31. The transition period after
the withdrawal is not modelled, and a shipment dated inside it is read at the
end of membership; that is the one place these dates can differ from an origin
decision.
* At or under EUR 6,000 the EU agreement lets any exporter sign the origin
declaration, so no approved exporter is demanded there. A value stated in
another currency is not measured against the ceiling: the snapshot carries no
exchange rate, says so, and treats the consignment as needing the approval.
* The applied MFN rate for the United States is the 2023 WITS figure, 1,057
  days older than the snapshot date, and the claim window is a paper of
  2025-02-12. `freshness`, `compare` and `assess` print each of those ages
  beside the snapshot's own, because the snapshot date is the day the file was
  built and not the day of every figure in it.
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

## What it uses, and what was used to build it

**Relate features in the product.** Two engines, one of them in the tab.
`relate-db` 1.2.0 is what the CLI, the MCP server and the scripts open: single
file mode, no server, `store/dutypath-rules.rl` read only, every read through one
module (`src/dutypath/store.py`). `@relate/relate-wasm` 1.3.0 is the same engine
compiled for the browser, and the demo page runs it in a worker to rebuild the
graph from the exported rows and answer the same Cypher. Cypher does the
interval match for a rule, the join that brings a market's rule and rate line
back together, the interval join between a rule's exclusion nodes and the
material codes, the catalogue walk above a good, the citation hops to the source
documents, and the hub pull statement. The MCP server (`dutypath mcp`) speaks
the Model Context Protocol over stdio with seven tools, and the shipment's own
graph is a separate in memory Relate graph that closes with the run.

**Third party code and data.** The only runtime dependency is `relate-db` from
PyPI. The extraction scripts use `pypdf` (optional, `[extract]`) and `openpyxl`
for the published spreadsheet; neither is needed to run a verdict. The nine
source documents are public: the KORUS annexes, RCEP Annex 3A and Annex I
(Japan), the Korea-EU schedule and rules of origin protocol, a Ministry of
Economy and Finance strategy paper, and a World Bank WITS applied tariff query.
`docs/SOURCES.md` lists each URL, date and sha256, and `NOTICE` names the
publishers. The demo page uses no library, no font download and no analytics.

The browser check uses Playwright, which is not in the dev extras, because a
plain `pytest` run should not need a browser.

**AI use.** This project was built with an AI coding assistant (a Claude based
agent environment) for code, tests and documentation, working from public
documents, as the hackathon's rules require disclosing. No AI model runs inside
DutyPath: every verdict is deterministic Cypher, Python and, in the demo page,
the same comparison written out in JavaScript over the rows the browser engine
returns, so the same input gives the same output offline. Every rate and rule
in the snapshot cites the document it came from. The review of this code that
produced the fixes in `tests/test_regressions.py` and `tests/test_redteam_round2.py`
also used language models as critics, and each finding was reproduced by hand
before it was fixed.

**Synthetic data.** Every shipment in `fixtures/`, in `benchmark/gold.json` and
in the demo is written by hand for this project. None of them is a client file,
a real company's material list or a real entry. The demo's three market example
is one of those synthetic shipments, and so is the second state of its key
material.

## Licence

Apache-2.0. See `LICENSE` and `NOTICE`. The rule texts and tariff schedules
belong to their publishers and are reproduced here as cited extracts for a
compliance check.
