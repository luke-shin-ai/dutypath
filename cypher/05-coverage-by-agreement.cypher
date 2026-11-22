// What the snapshot can answer, per agreement, before anyone asks it.
MATCH (a:Agreement)
OPTIONAL MATCH (r:OriginRule)-[:FOR]->(a)
OPTIONAL MATCH (t:RateLine)-[:FOR]->(a)
RETURN a.code AS agreement, a.market AS market, a.coverage AS coverage,
       count(DISTINCT r) AS rules, count(DISTINCT t) AS rate_lines;
