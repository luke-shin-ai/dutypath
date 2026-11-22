"""Store access.

The snapshot is one Relate file.  Every read goes through here, so the mode
and the file stay visible in one place, and the hash of the file is easy to
compare before and after a run.
"""

from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from typing import Iterator

import relate

DEFAULT_STORE = os.path.join("store", "dutypath-rules.rl")


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
    conn = connect(path)
    conn.autocommit = not read_only
    try:
        yield conn
    finally:
        conn.close()


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
