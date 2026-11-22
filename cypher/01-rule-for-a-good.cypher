// Which origin rule applies to a good under an agreement.
// An exact subheading rule wins over a range, a range over a heading, a
// heading over a chapter; the normalised interval makes all four comparable.
MATCH (r:OriginRule {agreement: $agreement})
WHERE r.from_norm <= $norm AND r.to_norm >= $norm
RETURN r.id AS rule, r.level AS level, r.code_from AS from_code, r.code_to AS to_code,
       r.text AS text, r.priority AS priority
ORDER BY r.priority ASC, r.to_norm ASC
LIMIT 1;
