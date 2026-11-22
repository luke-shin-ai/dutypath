// Serve one market's closure from the hub into an edge snapshot.
//
//   relate pull --from <creds> --query neo4j/pull_rules.cypher --param market=US \
//     --database store/dutypath-rules.rl
//
// What comes down is the public corpus only: the nomenclature the market's
// lines sit in, the origin rules of the agreements that cover it, the tariff
// lines with their staging, the claim deadlines, and the sources every row
// cites. A customer bill of materials is never part of this query, because it
// never enters the hub.
MATCH (a:Agreement)
WHERE a.market = '%(market)s'
OPTIONAL MATCH (a)<-[:FOR]-(rule:OriginRule)
OPTIONAL MATCH (a)<-[:FOR]-(rate:RateLine)-[:FOR]->(sub:Subheading)-[:IN_HEADING]->(head:Heading)
OPTIONAL MATCH (head)-[:IN_CHAPTER]->(chapter:Chapter)
OPTIONAL MATCH (rule)-[:CITED_FROM]->(rule_source:Source)
OPTIONAL MATCH (rate)-[:CITED_FROM]->(rate_source:Source)
RETURN a, rule, rate, sub, head, chapter, rule_source, rate_source;
