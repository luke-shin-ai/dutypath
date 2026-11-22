// The rate row for a line, with the staging it is subject to.
// The date arithmetic lives in the engine because each annex says it in a
// sentence, not a column; this returns the row that sentence applies to.
// Japan's row carries the printed schedule in `years`, so the cell for the
// year in question is read straight out of the row.
// A schedule can carry more than one row for one line: Japan prints a general
// rate and, on some lines, a treatment for Korea or for other parties.  A Korean
// shipment is priced on the Korea row when there is one, else on the general
// row, and never on a row written for another party.
MATCH (r:RateLine {code: $code, market: $market, agreement: $agreement})
WHERE coalesce(r.partner, 'ALL') IN ['KR', 'ALL']
MATCH (r)-[:CITED_FROM]->(src:Source)
RETURN r.base_rate_percent AS base_rate, r.base_rate_text AS rate_text,
       r.staging AS staging, r.years AS printed_years, r.partner AS partner,
       src.id AS source, toString(src.as_of) AS source_as_of
ORDER BY CASE WHEN r.partner = 'KR' THEN 0 ELSE 1 END
LIMIT 1;
