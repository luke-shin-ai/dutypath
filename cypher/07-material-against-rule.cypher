// Which materials sit inside a provision the rule excludes?
//
// $materials is the bill of materials as codes, one entry per material:
//   [{id: 'M1', start_norm: '85041000', end_norm: '85049999'}, ...]
// $rule is the OriginRule id and $alternative is which alternative of its
// sentence the intervals belong to (the sentence can say "or").
//
// The provisions are HsInterval nodes hanging off the rule, one per excluded
// token, one per excluded range and one for the group the rule excludes, each
// with the eight digit bounds the comparison runs on.  The join returns one row
// per material and interval that are not disjoint, with the relation the engine
// uses:
//
//   inside   every line the material can name is in the interval
//   across   the material is written too coarsely, so the interval cuts it and
//            the exporter has not said enough (an honest "cannot tell")
//   outside  none of the lines is in the interval, and that pair is dropped
//
// A material is sent as the interval it can name, so heading 8504 goes in as
// 85040000 to 85049999 and comes back "across" 8504.10 to 8504.50 rather than
// passing as the top line of its own heading.  No material is written to the
// store: the list arrives as a parameter and leaves with the answer.
UNWIND $materials AS m
MATCH (r:OriginRule {id: $rule})-[:EXCLUDES]->(i:HsInterval)
WHERE i.alternative = $alternative
WITH m, i,
  CASE WHEN m.end_norm < i.from_norm OR m.start_norm > i.to_norm THEN 'outside'
       WHEN m.start_norm >= i.from_norm AND m.end_norm <= i.to_norm THEN 'inside'
       ELSE 'across' END AS relation
WHERE relation <> 'outside'
RETURN m.id AS material, i.kind AS kind, i.ord AS ord, i.label AS label,
       i.low AS low_code, i.high AS high_code, relation AS relation
ORDER BY m.id, i.kind, i.ord;
