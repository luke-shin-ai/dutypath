"""The shipment's own graph, in memory.

A bill of materials is a small tree, and the question the engine asks of it is
a graph question: which tariff provisions do these parts sit in, and how far
are they from the good being classified.  So it is built as a graph, with the
nomenclature of each part hung above it, and it lives only as long as the run.

Nothing here touches the store.  That is the point: the rule book is a file
that ships with the tool, and the customer's material list never becomes part
of it.
"""

from __future__ import annotations

import relate

from . import codes

SCHEMA = [
    "CREATE (:Shipment {id: ''})",
]


def build(shipment: dict):
    """Load one shipment into a fresh in memory graph."""
    conn = relate.connect(":memory:")
    goods = shipment.get("goods") or {}
    good_code = str(goods.get("hts8") or goods.get("hs6") or goods.get("hs") or "")
    conn.execute(
        "CREATE (s:Shipment {id: $id, market: $market, value: $value})",
        {
            "id": str(shipment.get("shipment_id") or ""),
            "market": str(shipment.get("market") or ""),
            "value": float(goods.get("declared_value") or 0.0),
        },
    )
    conn.execute(
        "MATCH (s:Shipment) CREATE (g:Good {code: $code}) CREATE (s)-[:DECLARES]->(g)",
        {"code": good_code},
    )
    for entry in _codes_with_ancestors(good_code):
        _ensure_code(conn, entry)
    conn.execute(
        "MATCH (g:Good {code: $code}) MATCH (c:Code {code: $code}) CREATE (g)-[:CLASSIFIED_AS]->(c)",
        {"code": good_code},
    )

    for index, item in enumerate(shipment.get("materials") or [], start=1):
        material_id = str(item.get("id") or f"M{index}")
        code = str(item.get("hts8") or item.get("hs") or "")
        conn.execute(
            """
            MATCH (s:Shipment)
            CREATE (m:Material {id: $id, origin: $origin, value: $value, description: $description})
            CREATE (s)-[:CONTAINS]->(m)
            """,
            {
                "id": material_id,
                "origin": str(item.get("origin") or ""),
                "value": float(item.get("value") or 0.0),
                "description": str(item.get("description") or ""),
            },
        )
        for entry in _codes_with_ancestors(code):
            _ensure_code(conn, entry)
        conn.execute(
            """
            MATCH (m:Material {id: $id}) MATCH (c:Code {code: $code})
            CREATE (m)-[:CLASSIFIED_AS]->(c)
            """,
            {"id": material_id, "code": code},
        )
    return conn


def _codes_with_ancestors(code: str) -> list[str]:
    out = [code]
    out.extend(codes.ancestors(code))
    return [item for item in out if item]


def _ensure_code(conn, code: str) -> None:
    if conn.execute("MATCH (c:Code {code: $code}) RETURN c", {"code": code}).peek():
        return
    conn.execute("CREATE (:Code {code: $code, level: $level})", {"code": code, "level": codes.level_of(code)})
    chain = codes.ancestors(code)
    parent = chain[-1] if chain else None
    if parent is None:
        return
    _ensure_code(conn, parent)
    conn.execute(
        "MATCH (c:Code {code: $code}), (p:Code {code: $parent}) "
        "WHERE NOT (c)-[:IN]->(p) CREATE (c)-[:IN]->(p)",
        {"code": code, "parent": parent},
    )


MATERIALS_QUERY = """
MATCH (s:Shipment)-[:CONTAINS]->(m:Material)-[:CLASSIFIED_AS]->(c:Code)
RETURN m.id AS id, m.origin AS origin, m.value AS value, m.description AS description,
       c.code AS code
ORDER BY m.id
"""

GOOD_QUERY = """
MATCH (s:Shipment)-[:DECLARES]->(g:Good)-[:CLASSIFIED_AS]->(c:Code)
RETURN g.code AS code, s.value AS value, s.market AS market, s.id AS shipment
"""


def materials(conn) -> list[dict]:
    return [dict(row) for row in conn.execute(MATERIALS_QUERY)]


def good(conn) -> dict | None:
    row = conn.execute(GOOD_QUERY).single()
    return dict(row) if row is not None else None


def hierarchy_of(conn, code: str) -> list[str]:
    """The code and everything above it, nearest first, read from the graph."""
    rows = conn.execute(
        "MATCH p=(c:Code {code: $code})-[:IN*0..3]->(q:Code) "
        "RETURN DISTINCT q.code AS code, length(p) AS depth ORDER BY depth",
        {"code": code},
    )
    return [row["code"] for row in rows]
