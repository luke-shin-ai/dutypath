// The rate row for a line, with the staging it is subject to.
// The date arithmetic lives in the engine because Annex 2-B paragraph 1 is a
// paragraph, not a table; this returns the row it applies to.
MATCH (r:RateLine {hts8: $hts8, market: $market, agreement: $agreement})
MATCH (r)-[:CITED_FROM]->(src:Source)
RETURN r.base_rate_percent AS base_rate, r.staging AS staging, r.base_rate_text AS rate_text,
       src.id AS source, toString(src.as_of) AS source_as_of;
