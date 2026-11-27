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
//
// Two messages come in.  "run" answers the committed queries for the shipment
// on screen and is what the parity line compares with the bundle.  "analyze"
// answers the walk behind one picture: the rule that applies under each
// agreement, the intervals it excludes, the classification of each code, the
// way each material sits against those intervals (cypher/07) and the rate line
// that prices the good.  The verdict itself is computed on the page from those
// answers, so a picture of a path is a picture of what the engine returned.

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

// The walk behind one picture.  Everything a picture shows to the right of the
// bill of materials is a row of cypher/07, 08 or 09.
function analyze(input) {
  const started = performance.now();
  const spineRows = exec(queries["09-classification-spine.cypher"], { rows: input.spine }).rows;
  const markets = {};
  for (const market of input.markets) {
    const attachment = exec(queries["08-rule-attachment.cypher"], {
      agreement: market.agreement,
      norm: market.norm
    }).rows;
    const first = attachment.length ? attachment[0] : null;
    const rule = first && first.rule_id ? {
      id: first.rule_id,
      kinds: first.kinds || [],
      level: first.level,
      code_from: first.code_from,
      code_to: first.code_to,
      text: first.text,
      group_from: first.group_from,
      group_to: first.group_to,
      rvc_down: first.rvc_down,
      rvc_up: first.rvc_up,
      weight_min: first.weight_min,
      structured: first.structured,
      source: first.source_id ? { id: first.source_id, title: first.source_title } : null
    } : null;
    const intervals = attachment.filter(function (row) { return !!row.interval_id; }).map(function (row) {
      return {
        id: row.interval_id,
        alternative: row.interval_alternative,
        kind: row.interval_kind,
        ord: row.interval_ord,
        label: row.interval_label,
        low: row.interval_low,
        high: row.interval_high,
        from_norm: row.interval_from,
        to_norm: row.interval_to
      };
    });
    const hits = {};
    if (rule) {
      for (const alternative of market.alternatives || [1]) {
        const join = exec(queries["07-material-against-rule.cypher"], {
          rule: rule.id,
          alternative: alternative,
          materials: input.materials
        }).rows;
        const grouped = {};
        for (const row of join) {
          const key = String(row.material);
          grouped[key] = grouped[key] || [];
          grouped[key].push({
            kind: row.kind,
            ord: row.ord,
            label: row.label,
            low: row.low_code,
            high: row.high_code,
            relation: row.relation
          });
        }
        hits[String(alternative)] = grouped;
      }
    }
    markets[market.market] = { rule: rule, intervals: intervals, hits: hits };
  }
  return {
    markets: markets,
    spine: spineRows,
    analyzeMs: performance.now() - started
  };
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
  if (message.type === "analyze") {
    try {
      const result = analyze(message);
      self.postMessage(Object.assign({ type: "analysis", id: message.id }, result));
    } catch (error) {
      self.postMessage({ type: "analysis-failed", id: message.id, message: String(error && error.message || error) });
    }
  }
});

boot().catch(function (error) {
  self.postMessage({ type: "failed", message: String(error && error.message || error) });
});
