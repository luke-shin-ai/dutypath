// One good, three markets: the rule that applies and the line that prices it,
// for every agreement the snapshot covers, in one traversal.
//
// $codes is a map of market to the good's tariff line in that market's
// nomenclature, exactly as a shipment states it:
//   {US: '85044095', EU: '85044090', JP: '850440090'}
// $norms is the same code normalised to the eight digit space the rules use.
//
// A code can sit inside more than one rule interval (a heading and a chapter
// rule both cover 8504.40), so the rules are ordered the way the engine orders
// them, most specific first, and the first one is the rule that applies.
MATCH (a:Agreement)
WHERE a.coverage <> 'none' AND a.code <> 'MFN'
OPTIONAL MATCH (rule:OriginRule)-[:FOR]->(a)
  WHERE rule.from_norm <= $norms[a.market] AND rule.to_norm >= $norms[a.market]
WITH a, rule
ORDER BY a.code, rule.priority ASC, rule.to_norm ASC
WITH a, collect(rule)[0] AS rule
OPTIONAL MATCH (rule)-[:CITED_FROM]->(rule_source:Source)
OPTIONAL MATCH (rate:RateLine)-[:FOR]->(a)
  WHERE rate.code = $codes[a.market] AND rate.market = a.market
    AND coalesce(rate.partner, 'ALL') IN ['KR', 'ALL']
RETURN a.code AS agreement, a.market AS market, a.approved_exporter_required AS needs_approval,
       rule.code_from AS rule_from, rule.text AS rule_text, rule_source.id AS rule_source,
       rate.code AS line, rate.base_rate_percent AS base_rate, rate.staging AS staging,
       rate.years AS printed_years
ORDER BY a.code;
