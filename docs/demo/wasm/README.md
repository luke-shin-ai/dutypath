# The engine the page runs

The demo's verdict cards are a build time bundle. This directory is what lets
the same page query the graph in the reader's own tab.

    dutypath-graph.json    the snapshot's nodes and relationships as rows
    dutypath-queries.json  cypher/*.cypher copied verbatim
    relate.js              @relate/relate-wasm 1.3.0, as published
    relate_bg.wasm         the same package's engine, 6.9 MB
    opfs.js, trap.js       the package's side modules, as published
    snippets/              the package's glue the build imports
    graph-worker.js        our worker: build the graph, run the queries

The package is Apache-2.0 and published by Neo4j. `NOTICE` records it.

## Why the tab rebuilds the graph

`@relate/relate-wasm` 1.3.0 opens one of two things: `new RelateDb()` for an
in-memory database, or `RelateDb.open("opfs://<name>")` for a store it creates
in the browser's origin private file system. It has no call that opens an
existing `.rl` file, and the engine's own `Database::open` rejects `opfs://`
outside this package. So a page cannot hand the engine the committed
`store/dutypath-rules.rl`.

What it can do is rebuild the same graph from rows exported out of that file and
then answer the same Cypher. That is what this directory does. The `.rl` file
stays the artifact the CLI, the MCP server and a native `relate` run open, and
the panel says so on the page.

## Regenerating the export

    python scripts/build_wasm_seed.py --store store/dutypath-rules.rl

The script copies the store to a temporary file before opening it, because
closing a store runs `final_checkpoint` and rewrites the file, which changes its
sha256. The committed `.rl` is never opened in place.

The export carries the source path, byte count and sha256. The worker reports
that sha256 on the page, so a reader can check the rows against the file in the
repository.

`tests/test_wasm_seed.py` holds the export to the store: counts, labels, key
uniqueness, the copied query text, and the answers of `cypher/01`, `03`, `06`
and `07` against a rebuilt graph and against the store for every fixture.

## The package

    npm pack @relate/relate-wasm@1.3.0

unpacks to `relate.js`, `relate.d.ts`, `relate_bg.wasm`, `relate_bg.wasm.d.ts`,
`opfs.js`, `opfs.d.ts`, `trap.js`, `trap.d.ts`, `snippets/`, `README.md` and
`package.json`. The runtime files above were copied from that tarball unmodified.
To move to a later release, replace them, rerun the export, and run
`python scripts/check_wasm_demo.py`.
