"""Store access.

The snapshot is one Relate file.  Every read goes through here, so the mode
and the file stay visible in one place, and the hash of the file is easy to
compare before and after a run.

Relate accepts a write on a connection opened read only and refuses it at
commit, which leaves the file intact but lets a session see its own write.  So
the engine also refuses the statement itself: ``write_keyword`` names the
writing clause in a statement before anything is sent to the store, and the
MCP reader refuses on that answer.  The promise is then a property of the code
and the mode together, which is what the README says.
"""

from __future__ import annotations

import hashlib
import os
import re
from contextlib import contextmanager
from typing import Iterator

import relate

DEFAULT_STORE = os.path.join("store", "dutypath-rules.rl")

# Clauses that change the graph.  CALL is on the list because a subquery is the
# one place a write could hide behind a read: a procedure call is not something
# this snapshot needs and a reader can point that out.
WRITE_CLAUSE = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|FOREACH|LOAD\s+CSV|CALL|GRANT|REVOKE|"
    r"TRUNCATE|ALTER|INSERT|UPDATE)\b",
    re.IGNORECASE,
)
STRING_LITERAL = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)



def connect(path: str, read_only: bool = False):
    """Open a store, in memory when ``path`` is ``:memory:``.

    ``read_only`` loads the file once and refuses writes and checkpoints, so a
    verdict cannot change the rule book even by accident.
    """
    if path != ":memory:":
        return relate.connect(os.fspath(path), read_only=read_only)
    return relate.connect(":memory:", read_only=read_only)


@contextmanager
def open_store(path: str, read_only: bool = False) -> Iterator:
    conn = connect(path, read_only=read_only)
    conn.autocommit = not read_only
    try:
        yield conn
    finally:
        conn.close()


def write_keyword(statement: str) -> str | None:
    """The clause that would write in a statement, or None when it only reads.

    String literals and comments are removed first, so a property value that
    happens to read "created" is not mistaken for a clause.
    """
    if not statement or not statement.strip():
        return "an empty statement"
    cleaned = COMMENT.sub(" ", statement)
    cleaned = STRING_LITERAL.sub("''", cleaned)
    body = cleaned.strip().rstrip(";").strip()
    if ";" in body:
        return "more than one statement"
    match = WRITE_CLAUSE.search(body)
    return match.group(0).upper() if match else None


def rows(conn, statement: str, params: dict | None = None) -> list[dict]:
    return [dict(row) for row in conn.execute(statement, params or {})]


def one(conn, statement: str, params: dict | None = None):
    row = conn.execute(statement, params or {}).peek()
    return dict(row) if row is not None else None


def file_sha256(path: str) -> str:
    if not os.path.exists(path):
        return ""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def label_counts(conn) -> dict:
    result = rows(
        conn,
        "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS n ORDER BY label",
    )
    return {row["label"]: row["n"] for row in result}


def relationship_count(conn) -> int:
    row = one(conn, "MATCH ()-[r]->() RETURN count(r) AS n")
    return int(row["n"]) if row else 0
