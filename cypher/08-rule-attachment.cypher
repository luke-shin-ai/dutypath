// The rule that applies to a good, the intervals it excludes and the document
// it is cited to, in one walk of the graph.
//
// $agreement is the agreement code (KORUS, EUKOR, RCEP) and $norm is the good's
// code normalised to the eight digit space the rules use.  One row comes back
// per interval the rule names, with the rule and source columns repeated; a
// rule that names no interval comes back once with the interval columns null.
//
// This is the query the demo's own picture reads: every node it draws to the
// right of the bill of materials is a row of this statement or of
// cypher/09, so the picture cannot show a rule the snapshot does not hold.
MATCH (a:Agreement {code: $agreement})
OPTIONAL MATCH (rule:OriginRule)-[:FOR]->(a)
  WHERE rule.from_norm <= $norm AND rule.to_norm >= $norm
WITH a, rule
ORDER BY rule.priority ASC, rule.to_norm ASC
WITH a, collect(rule)[0] AS rule
OPTIONAL MATCH (rule)-[:EXCLUDES]->(i:HsInterval)
OPTIONAL MATCH (rule)-[:CITED_FROM]->(source:Source)
RETURN rule.id AS rule_id, rule.kinds AS kinds, rule.level AS level,
       rule.code_from AS code_from, rule.code_to AS code_to, rule.text AS text,
       rule.group_exclude_from AS group_from, rule.group_exclude_to AS group_to,
       rule.rvc_build_down AS rvc_down, rule.rvc_build_up AS rvc_up,
       rule.originating_weight_min AS weight_min, rule.structured AS structured,
       rule.priority AS priority,
       i.id AS interval_id, i.alternative AS interval_alternative,
       i.kind AS interval_kind, i.ord AS interval_ord, i.label AS interval_label,
       i.low AS interval_low, i.high AS interval_high,
       i.from_norm AS interval_from, i.to_norm AS interval_to,
       source.id AS source_id, source.title AS source_title
ORDER BY interval_alternative, interval_kind, interval_ord;
