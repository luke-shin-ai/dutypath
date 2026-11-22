// Claim windows travel with the rule book, because a verdict without its
// deadline is only half an answer.
MATCH (d:DeadlineRule)-[:CITED_FROM]->(src:Source)
RETURN d, src;
