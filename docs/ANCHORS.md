# Anchors

The reasons the three verdicts are the right shape come from one public
document, not from intuition. 기획재정부, 「FTA 활용지원을 위한 관세행정
추진전략」, 2025-02-12. Quoted with the section it appears in; the source's
arrows and list separators are written here in plain ASCII.

## What customs actually finds

> 수출검증 위반율(%): ('20)11.5 -> ('21)11.3 -> ('22)12.7 -> ('23)16.3 -> ('24)15.6

> 상대국 세관이 우리나라 수출기업 473개 검증(간접검증, 24년 기준)

> 검증요청 사유 | 원산지기준충족 여부 92.6, C/O 유효성(인증수출자 지위 포함) 6.1, C/O 위변조 0.3, 품목분류 오류 1.0

That last line is the whole design. 92.6 percent of verification requests are
about whether the origin rule was actually met, and 6.1 percent about whether
the document was valid. Two axes, and DutyPath has one verdict for each: the
origin verdict, and the approval window.

## The two patterns that cost money

> 1. 한-EU FTA 인증수출자 기간이 만료되어 인증수출자 지위 상실 -> 특혜 배제
> 2. 한-튀르키예 FTA에서 역외산 원사로 생산한 경우 원산지결정기준 불충족 -> 특혜 배제

Both are modelled. The first is `deadline.approved_exporter`, which returns
`EXPIRED` when the approval on file ended before the claim date, and
`deadline.blocks_claim` applies that status only where the agreement asks for the
approval: KORUS asks for none, so a stale KORUS approval on file is a note about
the file and not a reason to refuse a preference the agreement grants. The
second is a bill of materials whose material does not satisfy the tariff shift,
which is what the converter and battery parts fixtures show.

## The claim window

> 협정관세 사후적용 기간 : (기존) 1년 -> (개선) 최대 5년

The snapshot stores one year, in force as of the document, with the pending
extension carried in the same row's note so a reader sees that the number is
dated and may move.

## The requirement that a document can block a good origin

> 한-EU FTA, 한-영 FTA 활용을 위해서는 인증수출자만 혜택, RCEP, 한-인니 CEPA도 인증수출자를 규정

This is why `Agreement.approved_exporter_required` is a property of the
agreement row and not a constant in the code: it differs by agreement, and a
verdict that ignores it answers the wrong question.

## Utilisation, by product group (2024)

> 기계류 90.1, 화학공업제품 88.5, 전자전기제품 83.8, 생활용품 69.2, 섬유류 58.0

Electronics and machinery sit at the top of utilisation, which is where this
snapshot's three chapters are. The gap is not in the agreement's coverage but in
whether a company can answer the origin question before it ships.

## What is not in this document

No company, no shipment, no control list. The document is public, the numbers
are the government's, and nothing in DutyPath depends on the author's employer.
