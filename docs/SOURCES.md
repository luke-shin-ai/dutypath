# Sources

Every row in `store/dutypath-rules.rl` came from one of these documents. The
files are not committed; the hash is, so the extraction can be repeated and
checked.

| Id | Document | URL | As of | sha256 of the copy used |
| --- | --- | --- | --- | --- |
| SRC-KORUS-6A | KORUS FTA Annex 6-A, Specific Rules of Origin | https://ustr.gov/sites/default/files/Annex_6-A_SPECIFIC_RULES_OF_ORIGIN.pdf | 2012-03-15 | `369019d640518ea4a4dab58f802808e93c18f8bd32f8bf54e4334df95a8b9974` |
| SRC-KORUS-2B | KORUS FTA Annex 2-B, Tariff Schedule of the United States | https://ustr.gov/sites/default/files/uploads/agreements/fta/korus/Annex_2-B-1_US_Tariff_Schedule.pdf | 2012-03-15 | `2312380eaf681ec407f6bc71085b30a5ce3663a5847512d1003314a43f6b4be1` |
| SRC-KORUS-CH2 | KORUS FTA Chapter 2, Annex 2-B Tariff Elimination | https://ustr.gov/sites/default/files/uploads/agreements/fta/korus/asset_upload_file904_12701.pdf | 2012-03-15 | `c170fb626eaa9a1e254ec598b15b5dd0b4c41d7e57bc31a626c1a4e72b844ffb` |
| SRC-RCEP-3A | RCEP Annex 3A, Product-Specific Rules (HS 2022) | https://www.abf.gov.au/free-trade-agreements/files/rcep-chapter-3-annex-3a-HS2022.pdf | 2023-01-01 | `0a244b142f36a19e08f6fdf6ec840490d672c3fa40edeeb0505186fa02f67d3f` |
| SRC-MOEF-2025-02 | FTA 활용지원을 위한 관세행정 추진전략, 기획재정부 | https://mofe.go.kr/com/cmm/fms/FileDown.do?atchFileId=ATCH_000000000028297&fileSn=6 | 2025-02-12 | 16 pages, quoted in `docs/ANCHORS.md` |
| SRC-WITS-2023 | WITS / TRAINS applied tariff, reporter 840, partner 000 | see `scripts/fetch_mfn.py` | 2023-12-31 | live query, response kept in `data/extract-2026-11-22/us_mfn_applied.json` |

Downloaded 2026-11-22.

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
chapters, at heading level except four subheading rows. RCEP tariff schedules
are not in this snapshot, so RCEP origin is answered and RCEP duty is not.

**The MOEF strategy paper (2025-02-12)** is where the two deadlines and the
case anchors come from: the one year post import claim window, the approved
exporter requirement of the EU, UK, RCEP and Indonesia routes, the 2024
verification figures and the two named violation patterns.

**WITS** supplied the applied MFN rate at six digits for twelve lines, with the
count of tariff lines behind each value. When that count is one, the average is
the line's own rate and it is used; when it is more, it is an average of
several lines, which is not a rate for a shipment, so it is not used.

## What was deliberately left out

* The Korean tariff schedule, the EU schedule and the Turkiye schedule. Adding
  them without extracting them line by line would put numbers in the store that
  no document in it supports.
* Product specific rules outside chapters 39, 84 and 85.
* The Section VII operation rules and the RCEP "assembly of semiconductor
  products" alternative, which need process data a bill of materials does not
  carry.
* Any company name, bill of materials or shipment. The fixtures are synthetic.
