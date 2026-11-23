# Sources

Every row in `store/dutypath-rules.rl` came from one of these documents. The
files are not committed; the URL and the hash are, so the extraction can be
repeated and checked.

| Id | Document | URL | As of | sha256 of the copy used |
| --- | --- | --- | --- | --- |
| SRC-KORUS-6A | KORUS FTA Annex 6-A, Specific Rules of Origin | https://ustr.gov/sites/default/files/Annex_6-A_SPECIFIC_RULES_OF_ORIGIN.pdf | 2012-03-15 | `369019d640518ea4a4dab58f802808e93c18f8bd32f8bf54e4334df95a8b9974` |
| SRC-KORUS-2B | KORUS FTA Annex 2-B, Tariff Schedule of the United States | https://ustr.gov/sites/default/files/uploads/agreements/fta/korus/Annex_2-B-1_US_Tariff_Schedule.pdf | 2012-03-15 | `2312380eaf681ec407f6bc71085b30a5ce3663a5847512d1003314a43f6b4be1` |
| SRC-KORUS-CH2 | KORUS FTA Chapter 2, Annex 2-B Tariff Elimination | https://ustr.gov/sites/default/files/uploads/agreements/fta/korus/asset_upload_file904_12701.pdf | 2012-03-15 | `c170fb626eaa9a1e254ec598b15b5dd0b4c41d7e57bc31a626c1a4e72b844ffb` |
| SRC-RCEP-3A | RCEP Annex 3A, Product-Specific Rules (HS 2022) | https://www.abf.gov.au/free-trade-agreements/files/rcep-chapter-3-annex-3a-HS2022.pdf | 2023-01-01 | `0a244b142f36a19e08f6fdf6ec840490d672c3fa40edeeb0505186fa02f67d3f` |
| SRC-MOEF-2025-02 | FTA 활용지원을 위한 관세행정 추진전략, 기획재정부 | https://mofe.go.kr/com/cmm/fms/FileDown.do?atchFileId=ATCH_000000000028297&fileSn=6 | 2025-02-12 | 16 pages, quoted in `docs/ANCHORS.md` |
| SRC-WITS-2023 | WITS / TRAINS applied tariff, reporter 840, partner 000 | see `scripts/fetch_mfn.py` | 2023-12-31 | live query, response kept in `data/extract-2026-11-22/us_mfn_applied.json` |
| SRC-EUKOR-2A | Korea-EU FTA Annex 2-A, tariff schedule of the EU Party (Korean language copy of OJ L 127) | https://fta.motir.go.kr/webmodule/_PSD_FTA/eu/doc/kor/k_eu_2_eu_kor.pdf | 2011-07-01 | `ae9e1074afa05f3e44fab1545b7c42d5a3e94ef42b2478f8992f4e0de4693949` |
| SRC-EUKOR-ROO | Korea-EU FTA Protocol on rules of origin, Annex II (product specific rules) | https://fta.motir.go.kr/webmodule/_PSD_FTA/eu/doc/eng/k_eu_roo_eng.pdf | 2011-07-01 | `010261930adb0869239fabb14fb6236644c9bd22c13f2f5d3408167325cd4035` |
| SRC-RCEP-1-JP | RCEP Annex I, Schedule of Tariff Commitments of Japan (xlsx) | https://www.dfat.gov.au/sites/default/files/recp-schedule-of-japan.xlsx | 2022-01-01 | `b0f8da85296bf6b5f16028f15bd3b7c95c8fb3dd5680a163ddc73042da69856f` |

Downloaded 2026-11-22. Sizes: the EU schedule 1,057,373 bytes, 317 pages; the
protocol 896,363 bytes, 96 pages; the Japan schedule 2,236,772 bytes,
18,288 rows.

## What each document decided

**Annex 6-A** supplied every KORUS origin rule in chapters 39, 84 and 85, as
the sentence it prints. 222 blocks were read: 113 subheading rules, 93 ranges
and 16 heading rules. The Annex's own Section VII rules (chemical reaction,
mixture, purification, particle size, isomer separation) are not modelled; a
good that needs them falls back to the tariff shift rule in the same block or
comes back as undecidable.

**Annex 2-B** supplied the 847 US tariff lines of the three chapters: HTS8,
description, base rate, staging category.

**Chapter 2, Annex 2-B paragraph 1** supplied what each staging category does.
It is the only place the arithmetic of `rates.py` comes from, including the
round-down to a tenth and the January 1 stages:

* A eliminated on entry into force, B two stages, C three, D five, E six, F
  seven, G ten, H fifteen,
* I reduces by named percentages of the base rate, duty free from year ten,
* J holds the base rate through year eight, then four equal cuts to year 12,
* K keeps duty free treatment.

**RCEP Annex 3A (HS 2022)** supplied 108 product specific rules for the three
chapters, at heading level except four subheading rows.

**RCEP Annex I, the schedule of Japan**, supplied 1,278 tariff lines in the
three chapters as the schedule prints them: a base rate and a cell for each of
the years 1 to 21. 162 of those rows carry a partner specific treatment marked
"Treatment for China and Korea", and both the general row and the Korea row are
stored, because they answer differently for the same good. A cell reading `U`
is the schedule's own mark for a line excluded from the commitment for that
partner.

**The EU schedule, Annex 2-A**, supplied 1,726 CN eight digit lines in the
three chapters with a base rate and a staging category. The schedule exists in
two downloads: the English copy (`a3d545173a4c6ca59dd33afaf4bf5bb13278cedbbe4d77148d55dcc0c814f9da`,
761,802 bytes) prints the same table with an embedded subset font that carries
no Unicode mapping, so every digit extracts as a control character. The Korean
copy prints the same table with a working text layer, and that is the copy
parsed. The two were checked against each other by hand on the pages sampled
during the extraction.

**The protocol's Annex II** supplied 71 EU product specific rules at the level
the annex prints them: four ranges in chapter 39, the default rule for chapters
84 and 85, and 63 headings. The table is transcribed rather than parsed, and
`scripts/build_eukor_psr.py` refuses to write the file unless the heading code
and every rule sentence it records appear on the same page of the document.

**The MOEF strategy paper (2025-02-12)** is where the two deadlines and the
case anchors come from: the one year post import claim window, the approved
exporter requirement of the EU, UK, RCEP and Indonesia routes, the 2024
verification figures and the two named violation patterns.

**WITS** supplied the applied MFN rate at six digits for twelve lines, with the
count of tariff lines behind each value. When that count is one, the average is
the line's own rate and it is used; when it is more, it is an average of
several lines, which is not a rate for a shipment, so it is not used.

## How old the numbers are

A row is dated by the document it came from, and those dates are not the
snapshot's date. The difference is printed, not rounded away:

| Block of numbers | Source | Date it speaks for | Age against the snapshot date 2026-11-22 |
| --- | --- | --- | --- |
| the rules, the schedules and their staging | SRC-KORUS-6A, SRC-KORUS-2B, SRC-KORUS-CH2, SRC-EUKOR-2A, SRC-EUKOR-ROO, SRC-RCEP-3A, SRC-RCEP-1-JP | 2011-07-01 to 2023-01-01, the date each document prints | the schedule row is what its document printed; a staging category carries the cut forward, and the year it lands on is computed from the document's own rules |
| the United States applied MFN rate, twelve lines at six digits | SRC-WITS-2023 | 2023-12-31 | 1,057 days |
| the one year post import claim window | SRC-MOEF-2025-02 | 2025-02-12 | 648 days |

The last two rows are why `dutypath freshness` and every comparison carry a
`data_vintage` block and a `caveats` line beside the snapshot's own age. The
snapshot's `as_of` says when the file was built; it does not say that the
applied MFN rate under it is the 2023 figure, and a reader pricing an entry on
that rate needs the second date, not the first.

## What was deliberately left out

* The Korean tariff schedule and the Turkiye schedule. Adding them without
  extracting them line by line would put numbers in the store that no document
  in it supports.
* Product specific rules outside chapters 39, 84 and 85.
* The Section VII operation rules and the RCEP "assembly of semiconductor
  products" alternative, which need process data a bill of materials does not
  carry.
* The EU alternative for integrated circuits (diffusion), for the same reason.
* Any company name, bill of materials or shipment. The fixtures and the
  benchmark goods are synthetic.
