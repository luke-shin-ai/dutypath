// The supply chain of a good: every heading and chapter above it.
MATCH (s:Subheading {code: $subheading})-[:IN_HEADING]->(h:Heading)-[:IN_CHAPTER]->(c:Chapter)
RETURN s.code AS subheading, s.title AS subheading_title, h.code AS heading,
       h.title AS heading_title, c.code AS chapter, c.title AS chapter_title;
