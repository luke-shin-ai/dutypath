"""What the snapshot weighs, measured rather than asserted.

Four numbers, each one taken from the running process: the file on disk, the
node and relationship counts the engine holds, the resident memory of the
process that has the store open, and the wall clock time of the queries a
verdict runs.  The report prints them together with the machine they came
from, because a memory number without the machine is not a measurement.
"""

from __future__ import annotations

import os
import statistics
import time

from . import store

QUERIES = {
    "rule for a good": (
        "MATCH (r:OriginRule {agreement: 'KORUS'}) "
        "WHERE r.from_norm <= $norm AND r.to_norm >= $norm RETURN r.id, r.text LIMIT 1",
        {"norm": "85044095"},
    ),
    "rate for a line": (
        "MATCH (r:RateLine {hts8: $hts8}) RETURN r.hts8, r.base_rate_percent, r.staging",
        {"hts8": "85044095"},
    ),
    "code tree above a good": (
        "MATCH (h:Heading)-[:IN_CHAPTER]->(c:Chapter) "
        "OPTIONAL MATCH (s:Subheading)-[:IN_HEADING]->(h) "
        "RETURN h.code, count(s) AS subs ORDER BY h.code",
        {},
    ),
    "rules that mention a heading": (
        "MATCH (r:OriginRule) WHERE r.text CONTAINS $needle RETURN count(r) AS n",
        {"needle": "8507"},
    ),
}


def rss_kb() -> int:
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return 0


def measure(store_path: str, repeats: int = 30) -> dict:
    size = os.path.getsize(store_path)
    base_rss = rss_kb()

    conn = store.connect(store_path, read_only=True)
    opened_rss = rss_kb()
    counts = store.label_counts(conn)
    nodes = sum(counts.values())
    relationships = store.relationship_count(conn)

    timings = {}
    for label, (statement, params) in QUERIES.items():
        samples = []
        for _ in range(repeats):
            started = time.perf_counter()
            list(conn.execute(statement, params))
            samples.append((time.perf_counter() - started) * 1000.0)
        timings[label] = {
            "median_ms": round(statistics.median(samples), 3),
            "min_ms": round(min(samples), 3),
            "max_ms": round(max(samples), 3),
        }
    conn.close()

    return {
        "store": store_path,
        "file_bytes": size,
        "file_kb": round(size / 1024.0, 1),
        "file_mb": round(size / (1024.0 * 1024.0), 3),
        "nodes": nodes,
        "relationships": relationships,
        "labels": counts,
        "rss_before_kb": base_rss,
        "rss_with_store_kb": opened_rss,
        "rss_delta_kb": max(opened_rss - base_rss, 0),
        "rss_delta_mb": round(max(opened_rss - base_rss, 0) / 1024.0, 1),
        "timings": timings,
        "repeats": repeats,
        "machine": _machine(),
    }


def _machine() -> dict:
    info = {}
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("model name"):
                    info["cpu"] = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    info["memory_total_kb"] = int(line.split()[1])
                    break
    except OSError:
        pass
    info["python"] = os.sys.version.split()[0]
    return info
