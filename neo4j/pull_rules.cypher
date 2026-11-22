// Serve one market's closure from the hub into an edge snapshot.
//
//   relate pull --from <creds> --query neo4j/pull_rules.cypher \
//     --param market=US --database store/dutypath-rules.rl
//
//   dutypath pull-query --market US   prints this statement
//   dutypath pull-check --market US   runs it here and counts the rows
//
// What comes down is the public corpus only: the agreement for the market, its
// origin rules, its tariff lines with the nomenclature those lines sit in, the
// claim window, and the sources every row cites. A customer bill of materials
// is never part of this query, because it never enters the hub.
//
// One row per thing, and no cartesian product. The earlier form of this file
// matched the rules and the rates from the same agreement with two OPTIONAL
// MATCH clauses in one row, which returns their product: 222 rules times 847
// rates is 188,034 rows for the United States, and the pull died out of memory
// before it finished. A UNION of one branch per part returns 1,072 rows for the
// same market and completes in well under a second.
MATCH (a:Agreement {market: $market})
RETURN 'market' AS part, a.code AS agreement, a AS node,
       null AS subheading, null AS heading, null AS chapter, null AS source
UNION
MATCH (a:Agreement {market: $market})<-[:FOR]-(rule:OriginRule)-[:CITED_FROM]->(source:Source)
RETURN 'rule' AS part, a.code AS agreement, rule AS node,
       null AS subheading, null AS heading, null AS chapter, source AS source
UNION
MATCH (a:Agreement {market: $market})<-[:FOR]-(rate:RateLine)
OPTIONAL MATCH (rate)-[:FOR]->(sub:Subheading)-[:IN_HEADING]->(heading:Heading)-[:IN_CHAPTER]->(chapter:Chapter)
MATCH (rate)-[:CITED_FROM]->(source:Source)
RETURN 'rate' AS part, a.code AS agreement, rate AS node,
       sub AS subheading, heading AS heading, chapter AS chapter, source AS source
UNION
MATCH (window:DeadlineRule)-[:CITED_FROM]->(source:Source)
WHERE window.agreement = 'ALL'
RETURN 'deadline' AS part, null AS agreement, window AS node,
       null AS subheading, null AS heading, null AS chapter, source AS source
UNION
MATCH (snap:Snapshot)
RETURN 'snapshot' AS part, null AS agreement, snap AS node,
       null AS subheading, null AS heading, null AS chapter, null AS source
