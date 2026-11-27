// Where a stated code sits in the classification the snapshot holds: its
// subheading, the heading above it and the chapter above that.
//
// $rows is a list of {code, role, sub6, heading} objects, where code is the
// code as the exporter stated it, role is the caller's own label for the line
// (the good, or a material), and sub6 and heading are the two prefixes of that
// code.  The node is looked up by its key, so a code whose subheading or
// heading is not in the snapshot comes back with nulls rather than a guess.
//
// The edges the picture draws from the subheading up are the two the graph
// holds, IN_HEADING and IN_CHAPTER; nothing here invents a level the snapshot
// does not carry.
UNWIND $rows AS row
OPTIONAL MATCH (s:Subheading {code: row.sub6})
OPTIONAL MATCH (h:Heading {code: row.heading})
OPTIONAL MATCH (h)-[:IN_CHAPTER]->(c:Chapter)
RETURN row.code AS code, row.role AS role, row.label AS label,
       s.code AS subheading, h.code AS heading, c.code AS chapter
ORDER BY role, code;
