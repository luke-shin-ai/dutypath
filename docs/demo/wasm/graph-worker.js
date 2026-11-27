// The rule graph, running in the tab.
//
// This worker loads @relate/relate-wasm 1.3.0, builds the snapshot's graph in
// the engine's in-memory database from the rows scripts/build_wasm_seed.py
// exported, and answers the committed Cypher files against it.  It runs in a
// worker so a slow statement cannot freeze the page and so a trapped instance
// can be replaced without a reload.
//
// The package opens :memory: or its own OPFS store.  It has no call that opens
// an existing .rl file, which is why the graph is rebuilt here from the
// exported rows instead of the store bytes.  See docs/demo/wasm/README.md.

import init, { RelateDb } from "./relate.js";

let db = null;
let queries = null;
let source = null;

function say(phase, text, extra) {
  self.postMessage(Object.assign({ type: "status", phase: phase, text: text }, extra || {}));
}

function exec(query, params) {
  const envelope = JSON.parse(db.execute(query, params == null ? null : JSON.stringify(params)));
  if (envelope.error) {
    throw new Error(envelope.error);
  }
  return envelope;
}

async function boot() {
  const started = performance.now();
  say("engine", "loading the Relate engine");
  await init();

  say("graph", "reading the exported rows");
  const graph = await (await fetch("./dutypath-graph.json", { cache: "no-cache" })).json();
  queries = await (await fetch("./dutypath-queries.json", { cache: "no-cache" })).json();
  source = graph.source;

  say("graph", "building " + graph.counts.nodes.toLocaleString("en-US") + " nodes and " +
      graph.counts.relationships.toLocaleString("en-US") + " relationships");
  const buildStart = performance.now();
  db = new RelateDb();

  for (const [label, item] of Object.entries(graph.labels)) {
    exec("CREATE CONSTRAINT " + label.toLowerCase() + "_" + item.key.toLowerCase() +
         " IF NOT EXISTS FOR (n:" + label + ") REQUIRE n." + item.key + " IS UNIQUE");
  }
  for (const [label, item] of Object.entries(graph.labels)) {
    exec("UNWIND $rows AS row CREATE (n:" + label + ") SET n = row", { rows: item.rows });
  }
  for (const group of graph.relationships) {
    exec("UNWIND $pairs AS p MATCH (a:" + group.from + " {" + group.from_key + ": p[0]}), " +
         "(b:" + group.to + " {" + group.to_key + ": p[1]}) CREATE (a)-[:" + group.type + "]->(b)",
         { pairs: group.pairs });
  }
  const buildMs = performance.now() - buildStart;

  const nodes = exec("MATCH (n) RETURN count(n) AS n", null);
  const rels = exec("MATCH ()-[r]->() RETURN count(r) AS r", null);
  self.postMessage({
    type: "ready",
    engine: "relate-wasm 1.3.0",
    buildMs: buildMs,
    totalMs: performance.now() - started,
    counts: {
      nodes: nodes.rows[0].n,
      relationships: rels.rows[0].r,
      labels: Object.keys(graph.labels).length,
      relationshipTypes: new Set(graph.relationships.map(function (g) { return g.type; })).size
    },
    source: source
  });
}

function collect(input) {
  const six = exec(queries["06-market-comparison.cypher"], { codes: input.codes, norms: input.norms });
  const markets = six.rows.map(function (row) {
    const market = row.market;
    const one = exec(queries["01-rule-for-a-good.cypher"], {
      agreement: row.agreement,
      norm: input.norms[market]
    });
    const rule = one.rows.length ? one.rows[0] : null;
    const rate = exec(queries["03-rate-on-a-date.cypher"], {
      code: input.codes[market],
      market: market,
      agreement: row.agreement
    });
    let materials = [];
    if (rule) {
      for (const alternative of [1, 2]) {
        const join = exec(queries["07-material-against-rule.cypher"], {
          rule: rule.rule,
          alternative: alternative,
          materials: input.materials
        });
        materials = materials.concat(join.rows);
      }
    }
    const hierarchy = exec(queries["04-hierarchy-above-a-good.cypher"], { subheading: input.codes[market] });
    return {
      market: market,
      agreement: row.agreement,
      rule: rule,
      comparison: row,
      rate: rate.rows.length ? rate.rows[0] : null,
      rateMs: rate.elapsed_ms,
      ruleMs: one.elapsed_ms,
      materials: materials,
      hierarchy: hierarchy.rows.length ? hierarchy.rows[0] : null,
      coverage: null
    };
  });
  const coverage = exec(queries["05-coverage-by-agreement.cypher"], null);
  for (const market of markets) {
    market.coverage = coverage.rows.filter(function (row) { return row.agreement === market.agreement; })[0] || null;
  }
  return { markets: markets, comparisonMs: six.elapsed_ms };
}

self.addEventListener("message", function (event) {
  const message = event.data || {};
  if (message.type === "run") {
    try {
      const started = performance.now();
      const result = collect(message);
      self.postMessage(Object.assign({ type: "result", id: message.id, totalMs: performance.now() - started }, result));
    } catch (error) {
      self.postMessage({ type: "error", id: message.id, message: String(error && error.message || error) });
    }
  }
});

boot().catch(function (error) {
  self.postMessage({ type: "failed", message: String(error && error.message || error) });
});
