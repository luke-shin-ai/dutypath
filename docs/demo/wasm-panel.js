// The "run it here" panel.
//
// The verdicts above are the build time bundle.  This panel proves the graph
// behind them is real: it starts the Relate WebAssembly engine in a worker,
// rebuilds the snapshot's 5,454 nodes and 13,559 relationships in the tab, and
// runs the committed Cypher files for the shipment on screen.  Every value the
// engine returns is compared with the bundle, so a reader can see the two
// agree instead of taking the sentence on trust.

(function () {
  var DATA = window.DUTYPATH_DEMO;
  var section = document.getElementById("engine");
  if (!DATA || !section) { return; }

  var statusEl = document.getElementById("engine-status");
  var buildEl = document.getElementById("engine-build");
  var liveEl = document.getElementById("engine-live");
  var builtCounts = null;
  var bodyEl = document.getElementById("engine-body");
  var parityEl = document.getElementById("engine-parity");
  var worker = null;
  var ready = false;
  var pending = null;
  var requestId = 0;

  function money(amount) {
    if (amount === null || amount === undefined) { return "-"; }
    return (Math.round(amount * 100) / 100).toLocaleString("en-US");
  }
  function normaliseLow(code) {
    var digits = String(code || "").replace(/[^0-9]/g, "");
    if (!digits) { return ""; }
    return digits.length < 8 ? digits + "0".repeat(8 - digits.length) : digits.slice(0, 8);
  }
  function normalise(code) {
    var digits = String(code || "").replace(/[^0-9]/g, "");
    if (!digits) { return ""; }
    return digits.length < 8 ? digits + "9".repeat(8 - digits.length) : digits.slice(0, 8);
  }
  function setStatus(text, kind) {
    statusEl.textContent = text;
    statusEl.className = "engine-status" + (kind ? " " + kind : "");
  }
  function escapeText(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function currentCase() {
    var select = document.getElementById("case");
    var index = select ? parseInt(select.value, 10) : 0;
    if (isNaN(index) || !DATA.cases[index]) { index = 0; }
    return DATA.cases[index];
  }

  function payload() {
    var item = currentCase();
    var shipment = item.shipment || {};
    var codes = (shipment.goods || {}).market_codes || {};
    var norms = {};
    Object.keys(codes).forEach(function (market) { norms[market] = normalise(codes[market]); });
    var materials = ((shipment.materials) || []).map(function (line) {
      var code = line.hts8 || line.code || "";
      return { id: line.id, start_norm: normaliseLow(code), end_norm: normalise(code) };
    });
    return { type: "run", id: ++requestId, codes: codes, norms: norms, materials: materials, item: item };
  }

  function start() {
    if (worker) { return; }
    if (location.protocol === "file:") {
      setStatus("the browser engine needs the page served over http. Open the published page to run it.", "warn");
      return;
    }
    setStatus("starting the engine", "busy");
    try {
      worker = new Worker("wasm/graph-worker.js", { type: "module" });
    } catch (error) {
      setStatus("this browser did not start the worker: " + (error && error.message ? error.message : error), "fail");
      return;
    }
    worker.addEventListener("message", onMessage);
    worker.addEventListener("error", function (event) {
      setStatus("the engine worker stopped: " + (event.message || "unknown error"), "fail");
    });
  }

  function onMessage(event) {
    var message = event.data || {};
    if (message.type === "status") {
      setStatus(message.text, "busy");
      return;
    }
    if (message.type === "ready") {
      ready = true;
      builtCounts = message.counts;
      buildEl.innerHTML = "<b>" + escapeText(message.engine) + "</b> built " +
        message.counts.nodes.toLocaleString("en-US") + " nodes and " +
        message.counts.relationships.toLocaleString("en-US") + " relationships in this tab in " +
        (message.buildMs / 1000).toFixed(1) + " s, from " + message.counts.labels + " labels and " +
        message.counts.relationshipTypes + " relationship types. Snapshot " + message.source.sha256.slice(0, 12) +
        ". The bytes came from this page's own files and nothing is sent anywhere.";
      setStatus("the engine is up, running the committed Cypher for this shipment", "busy");
      run();
      return;
    }
    if (message.type === "failed") {
      setStatus("the engine did not start: " + message.message + ". The static numbers above are unaffected.", "fail");
      return;
    }
    if (message.type === "error") {
      setStatus("the query failed: " + message.message, "fail");
      return;
    }
    if (message.type === "result") {
      render(message);
    }
  }

  function run() {
    if (!ready || !worker) { return; }
    var message = payload();
    pending = message;
    setStatus("running the committed Cypher for this shipment", "busy");
    worker.postMessage({ type: "run", id: message.id, codes: message.codes, norms: message.norms, materials: message.materials });
  }

  function render(result) {
    var item = pending ? pending.item : currentCase();
    var report = (item.report || {});
    var byMarket = {};
    (report.markets || []).forEach(function (block) { byMarket[block.market] = block; });

    var compared = 0;
    var matched = 0;
    var differences = [];
    function check(label, live, stored) {
      compared += 1;
      if (String(live) === String(stored)) { matched += 1; }
      else { differences.push(label + ": engine " + live + ", bundle " + stored); }
    }

    var html = '<div class="engine-table"><table><thead><tr>' +
      "<th>Market</th><th>Agreement</th><th>Rule from graph</th><th>Rate line</th>" +
      "<th>Base rate</th><th>Staging</th><th>Source</th><th>Materials against the rule</th>" +
      "</tr></thead><tbody>";

    (result.markets || []).forEach(function (row) {
      var block = byMarket[row.market] || {};
      var rule = row.rule || {};
      var rate = row.rate || {};
      var stored = block.rate || {};
      var storedOrigin = block.origin || {};
      check(row.market + " rule", rule.from_code, (storedOrigin.rule || {}).code_from);
      check(row.market + " line", (row.comparison || {}).line, block.code);
      check(row.market + " base rate", (row.comparison || {}).base_rate, stored.base_rate_percent);
      check(row.market + " staging", (row.comparison || {}).staging, stored.staging);
      check(row.market + " source", rate.source, stored.source);

      var materialText = "none in a barred provision";
      if ((row.materials || []).length) {
        materialText = row.materials.map(function (line) {
          return line.material + " " + line.relation + " " + line.label;
        }).join("; ");
      }
      html += "<tr><td>" + escapeText(row.market) + "</td><td>" + escapeText(row.agreement) + "</td>" +
        '<td class="mono">' + escapeText(rule.from_code) + "</td>" +
        '<td class="mono">' + escapeText((row.comparison || {}).line) + "</td>" +
        "<td>" + escapeText((row.comparison || {}).base_rate) + "%</td>" +
        "<td>" + escapeText((row.comparison || {}).staging) + "</td>" +
        '<td class="mono">' + escapeText(rate.source) + "</td>" +
        "<td>" + escapeText(materialText) + "</td></tr>";
    });
    html += "</tbody></table></div>";
    bodyEl.innerHTML = html;

    var timing = "The three market comparison took " + (result.comparisonMs || 0).toFixed(2) +
      " ms in the engine here, and the whole run " + ((result.totalMs || 0) / 1000).toFixed(2) + " s including the queries per market.";
    var parityText = "Engine against bundle: " + matched + " of " + compared + " values agree.";
    if (differences.length) {
      parityEl.className = "engine-parity fail";
      parityEl.innerHTML = escapeText(parityText) + "<br>" + escapeText(differences.join(" | "));
      setStatus(timing, "fail");
    } else {
      parityEl.className = "engine-parity ok";
      parityEl.innerHTML = escapeText(parityText) + " " + escapeText(timing);
      setStatus("the graph in this tab answers the same as the committed bundle", "ok");
      if (liveEl && builtCounts) {
        liveEl.hidden = false;
        liveEl.textContent = "graph engine live in this tab: " + builtCounts.nodes.toLocaleString("en-US") +
          " nodes and " + builtCounts.relationships.toLocaleString("en-US") +
          " relationships built here, " + matched + " of " + compared + " values agree with the bundle";
      }
    }
  }

  function schedule() {
    var startOnce = function () { start(); run(); };
    ["case", "on", "value"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) { el.addEventListener("change", startOnce); }
    });
    if ("requestIdleCallback" in window) {
      window.requestIdleCallback(start, { timeout: 2500 });
    } else {
      window.setTimeout(start, 1200);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", schedule);
  } else {
    schedule();
  }
})();
