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


def _code_only(statement: str) -> str:
    """The statement with string literals and comments cut out in one pass.

    The two have to be removed together, because either one alone hides the
    other.  Removing comments first reads the ``//`` in ``'http://x'`` as the
    start of a comment and drops the rest of the line, so a ``CREATE`` written
    after that literal is never named.  Removing literals first reads the
    apostrophe in ``// don't`` as an opening quote and swallows the code that
    follows.  A scanner that knows which of the two it is inside cannot make
    either mistake: it walks the statement once, skips a literal or a comment
    as a whole, and keeps everything else.
    """
    kept: list[str] = []
    index = 0
    length = len(statement)
    while index < length:
        char = statement[index]
        if char in ("'", '"'):
            index += 1
            while index < length:
                if statement[index] == "\\" and index + 1 < length:
                    index += 2
                    continue
                if statement[index] == char:
                    index += 1
                    break
                index += 1
            kept.append("''")
            continue
        if statement.startswith("//", index):
            while index < length and statement[index] != "\n":
                index += 1
            kept.append(" ")
            continue
        if statement.startswith("/*", index):
            end = statement.find("*/", index + 2)
            index = length if end == -1 else end + 2
            kept.append(" ")
            continue
        kept.append(char)
        index += 1
    return "".join(kept)


def write_keyword(statement: str) -> str | None:
    """The clause that would write in a statement, or None when it only reads.

    String literals and comments are skipped as each is met, so a property value
    that happens to read "created" is not mistaken for a clause and a URL in a
    literal does not hide the write that follows it.
    """
    if not statement or not statement.strip():
        return "an empty statement"
    body = _code_only(statement).strip().rstrip(";").strip()
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
