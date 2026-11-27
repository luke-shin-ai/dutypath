// The "run it here" panel.
//
// The verdicts above are the build time bundle.  This panel proves the graph
// behind them is real: it starts the Relate WebAssembly engine in a worker,
// rebuilds the snapshot's 5,454 nodes and 13,559 relationships in the tab, and
// runs the committed Cypher files for the shipment on screen.  Every value the
// engine returns is compared with the bundle, so a reader can see the two
// agree instead of taking the sentence on trust.
//
// It is also where the origin question is asked again.  One material line of the
// shipment can be swapped for its other sourcing option; the panel asks the
// engine for the same walk with the new line, evaluates the three rules on the
// page from what comes back, and redraws the three paths.  The verdict and the
// duty are computed here, not read from the bundle; the bundle's own answer for
// the second state is shown next to it so the two can be compared.

(function () {
  var DATA = window.DUTYPATH_DEMO;
  var section = document.getElementById("engine");
  if (!DATA || !section) { return; }

  var ORIGIN = window.DUTYPATH_ORIGIN;
  var SUBGRAPH = window.DUTYPATH_SUBGRAPH;
  var AGREEMENT = { US: "KORUS", EU: "EUKOR", JP: "RCEP" };
  var MARKETS = ["US", "EU", "JP"];

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
  var analysis = null;
  var analysisCase = null;
  var toggled = false;
  var graphHost = document.getElementById("graph-host");
  var readoutEl = document.getElementById("graph-readout");
  var toggleInput = document.getElementById("material-toggle");
  var toggleNote = document.getElementById("material-swap");
  var mobileQuery = window.matchMedia ? window.matchMedia("(max-width: 760px)") : null;

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

  function caseMaterials(item, swapped) {
    var lines = (item.shipment.materials || []).map(function (line) {
      return {
        id: line.id,
        code: line.hts8 || line.code || "",
        origin: line.origin || "",
        value: line.value === null || line.value === undefined ? null : Number(line.value)
      };
    });
    if (swapped && item.toggle) {
      var change = item.toggle.change;
      lines = lines.map(function (line) {
        if (line.id !== change.id) { return line; }
        return {
          id: line.id,
          code: change.to.hts8,
          origin: change.to.origin,
          value: change.to.value === null ? null : Number(change.to.value)
        };
      });
    }
    return lines;
  }

  function blockFor(item, market) {
    var found = null;
    (item.report.markets || []).forEach(function (block) {
      if (block.market === market) { found = block; }
    });
    return found;
  }

  function entryDate(item) {
    var input = document.getElementById("on");
    if (input && input.value) { return input.value; }
    return (item.report.shipment || {}).assessed_on || "";
  }

  function declaredValue(item) {
    var input = document.getElementById("value");
    var value = input ? parseFloat(input.value) : NaN;
    if (!isNaN(value)) { return value; }
    return Number((item.report.shipment || {}).declared_value || 0);
  }

  function prefPercent(item, market, on) {
    var block = blockFor(item, market);
    if (!block) { return null; }
    var row = DATA.rates[market + ":" + block.code];
    if (!row || !window.dutypathRate) { return block.rate ? block.rate.percent : null; }
    return window.dutypathRate(row, on);
  }

  function mfnPercent(item, market) {
    var block = blockFor(item, market);
    if (!block) { return null; }
    if (block.mfn && block.mfn.percent !== null && block.mfn.percent !== undefined) {
      return block.mfn.percent;
    }
    var row = DATA.rates[market + ":" + block.code];
    return row ? row.base_rate_percent : null;
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

  // The walk the pictures are drawn from: one query per market for the rule and
  // its intervals, one for the classification of every code, and one join per
  // alternative between the material list and those intervals.
  function analysisPayload(item) {
    var codes = (item.shipment.goods || {}).market_codes || {};
    var reading = item.reading || {};
    var materials = caseMaterials(item, toggled);
    var markets = [];
    var spine = [];
    MARKETS.forEach(function (market) {
      var code = codes[market];
      if (!code) { return; }
      var alternatives = (reading.alternatives || {})[market] || [];
      markets.push({
        market: market,
        agreement: AGREEMENT[market],
        code: code,
        norm: normalise(code),
        alternatives: alternatives.map(function (item, index) { return index + 1; })
      });
      var digits = String(code).replace(/[^0-9]/g, "");
      spine.push({
        code: code,
        role: "good:" + market,
        label: "good " + market,
        sub6: digits.slice(0, 6),
        heading: digits.slice(0, 4)
      });
    });
    materials.forEach(function (line) {
      var digits = String(line.code || "").replace(/[^0-9]/g, "");
      if (!digits) { return; }
      spine.push({
        code: line.code,
        role: "material:" + line.id,
        label: line.id,
        sub6: digits.slice(0, 6),
        heading: digits.slice(0, 4)
      });
    });
    return {
      type: "analyze",
      id: ++requestId,
      markets: markets,
      spine: spine,
      materials: materials.map(function (line, position) {
        return { id: String(position), start_norm: normaliseLow(line.code), end_norm: normalise(line.code) };
      })
    };
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
      analyze();
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
      return;
    }
    if (message.type === "analysis") {
      analysis = message;
      analysisCase = currentCase().id + (toggled ? "|swapped" : "|filed");
      drawGraphs();
      return;
    }
    if (message.type === "analysis-failed") {
      if (readoutEl) {
        readoutEl.textContent = "the walk behind the picture could not be read from the engine: " + message.message;
      }
      return;
    }
  }

  function run() {
    if (!ready || !worker) { return; }
    var message = payload();
    pending = message;
    setStatus("running the committed Cypher for this shipment", "busy");
    worker.postMessage({ type: "run", id: message.id, codes: message.codes, norms: message.norms, materials: message.materials });
  }

  function analyze() {
    if (!ready || !worker) { return; }
    worker.postMessage(analysisPayload(currentCase()));
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

  // ---------------------------------------------------------------- pictures

  function spineFor(role) {
    var found = null;
    ((analysis && analysis.spine) || []).forEach(function (row) {
      if (row.role === role) { found = row; }
    });
    return found || {};
  }

  function ruleForItem(item, market) {
    var fromGraph = analysis && analysis.markets && analysis.markets[market] ? analysis.markets[market].rule : null;
    var fromReading = ((item.reading || {}).rules || {})[market] || null;
    if (fromGraph) {
      var group = fromGraph.group_from && fromGraph.group_to ? [fromGraph.group_from, fromGraph.group_to] : null;
      return {
        id: fromGraph.id,
        kinds: fromGraph.kinds || [],
        level: fromGraph.level,
        code_from: fromGraph.code_from,
        code_to: fromGraph.code_to,
        text: fromGraph.text,
        group: group,
        rvc_down: fromGraph.rvc_down,
        rvc_up: fromGraph.rvc_up,
        weight_min: fromGraph.weight_min,
        source: fromGraph.source
      };
    }
    if (fromReading) {
      return {
        id: fromReading.id, kinds: [], level: fromReading.level,
        code_from: fromReading.code_from, code_to: fromReading.code_to,
        text: fromReading.text, group: null, rvc_down: null, rvc_up: null, weight_min: null
      };
    }
    return null;
  }

  function evaluationFor(item, market) {
    var reading = item.reading || {};
    var hit = analysis && analysis.markets && analysis.markets[market];
    var block = blockFor(item, market);
    var context = {
      agreement: AGREEMENT[market],
      goodCode: block ? block.code : null,
      alternatives: ((reading.alternatives || {})[market]) || [],
      parties: ((reading.parties || {})[market]) || [],
      materials: caseMaterials(item, toggled),
      fob: declaredValue(item),
      hits: hit ? hit.hits : {},
      attributes: item.shipment.attributes || null
    };
    return ORIGIN.evaluateMarket(context);
  }

  function drawGraphs() {
    if (!graphHost || !analysis) { return; }
    var item = currentCase();
    if (analysisCase && analysisCase !== item.id + (toggled ? "|swapped" : "|filed")) { return; }
    var on = entryDate(item);
    var value = declaredValue(item);
    var currency = (item.report.shipment || {}).currency || "USD";
    var materials = caseMaterials(item, toggled);
    var mobile = mobileQuery ? mobileQuery.matches : false;
    var rows = [];
    var live = { toggled: toggled, markets: {} };

    graphHost.innerHTML = "";
    MARKETS.forEach(function (market) {
      var block = blockFor(item, market);
      if (!block) { return; }
      var evaluation = evaluationFor(item, market);
      var pref = prefPercent(item, market, on);
      var mfn = mfnPercent(item, market);
      var priced = ORIGIN.price(evaluation.verdict, pref, mfn, value, block.documents);
      var spine = spineFor("good:" + market);
      var byRole = {};
      ((analysis && analysis.spine) || []).forEach(function (row) { byRole[row.role] = row; });
      var model = {
        market: market,
        marketName: block.market_name || market,
        agreement: AGREEMENT[market],
        code: block.code,
        shipmentId: item.id,
        value: value,
        currency: currency,
        stateLabel: toggled ? "key material swapped" : "as declared",
        materials: materials,
        rule: ruleForItem(item, market),
        spine: { good: spine, byRole: byRole },
        evaluation: evaluation,
        ratePercent: pref,
        mfnPercent: mfn,
        duty: priced.duty,
        allowed: priced.allowed
      };
      live.markets[market] = {
        verdict: evaluation.verdict,
        duty: priced.duty,
        allowed: priced.allowed,
        reason: evaluation.reason,
        path: evaluation.path,
        rate: pref,
        rvc_down: evaluation.rvc_down,
        rvc_up: evaluation.rvc_up,
        blocked: priced.allowed ? null : (evaluation.verdict === "ORIGINATING"
          ? "document: the approval on file does not clear this claim"
          : "origin: " + evaluation.verdict)
      };

      var figure = document.createElement("figure");
      figure.className = "graph-figure";
      var caption = document.createElement("figcaption");
      caption.innerHTML = "<b>" + escapeText(model.marketName) + "</b> " +
        '<span class="mono">' + escapeText(model.agreement) + " " + escapeText(model.code || "") + "</span> " +
        '<span class="badge ' + (evaluation.verdict === "ORIGINATING" ? "b-claim" : (evaluation.verdict === "NOT_ORIGINATING" ? "b-refused" : "b-unknown")) +
        '">' + escapeText(evaluation.verdict.replace(/_/g, " ")) + "</span> " +
        '<span class="why">duty ' + escapeText(money(priced.duty)) + " " + escapeText(currency) + "</span>";
      var canvas = document.createElement("div");
      canvas.className = "graph-canvas";
      figure.appendChild(caption);
      figure.appendChild(canvas);
      graphHost.appendChild(figure);
      SUBGRAPH.render(canvas, model, { mobile: mobile });

      rows.push({
        market: market,
        verdict: evaluation.verdict,
        duty: priced.duty,
        reason: evaluation.reason
      });
    });

    if (readoutEl) {
      var agreement = [];
      var official = item.toggle ? (toggled ? item.toggle.report : item.report) : item.report;
      var officialMarkets = {};
      (official.markets || []).forEach(function (block) { officialMarkets[block.market] = block; });
      var verdictAgree = 0;
      var dutyAgree = 0;
      rows.forEach(function (row) {
        var stored = officialMarkets[row.market];
        if (!stored) { return; }
        if (stored.origin.verdict === row.verdict) { verdictAgree += 1; }
        var storedDuty = stored.duty.amount;
        if (storedDuty !== null && Math.abs(storedDuty - row.duty) < 0.005) { dutyAgree += 1; }
      });
      agreement.push("This tab against the engine's own answer for this state: " + verdictAgree +
        " of 3 verdicts and " + dutyAgree + " of 3 duties agree.");
      agreement.push(rows.map(function (row) {
        return row.market + " " + row.verdict.replace(/_/g, " ") + " " + money(row.duty) + " " + currency;
      }).join(", ") + ".");
      readoutEl.className = "graph-readout" + (verdictAgree === 3 ? " ok" : " fail");
      readoutEl.innerHTML = agreement.map(escapeText).join(" ");
    }

    if (window.DUTYPATH_SET_LIVE) {
      window.DUTYPATH_SET_LIVE(live);
    }
    syncToggle();
  }

  function describeSwap(item) {
    if (!toggleNote) { return; }
    if (!item.toggle) { toggleNote.textContent = ""; return; }
    var change = item.toggle.change;
    toggleNote.innerHTML = "M1 as declared: " + escapeText(change.from.hts8) + ", " +
      escapeText(change.from.origin) + ", " + escapeText(money(change.from.value)) +
      ". Swapped: " + escapeText(change.to.hts8) + ", " + escapeText(change.to.origin) + ", " +
      escapeText(money(change.to.value)) + " (" + escapeText(item.toggle.alternative_label) + ").";
  }

  function syncToggle() {
    var item = currentCase();
    // The swap is only offered once the walk behind it is in hand: before that
    // a click would ask for nothing and a reader would wait without a reason.
    var available = !!(item && item.toggle && analysis);
    if (toggleInput) {
      toggleInput.disabled = !available;
      toggleInput.checked = (item && item.toggle && toggled) ? true : false;
      if (!item || !item.toggle) { toggled = false; }
    }
    describeSwap(item);
  }

  function schedule() {
    var startOnce = function () { start(); run(); };
    ["case", "on", "value"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) {
        el.addEventListener("change", function () {
          if (id === "case") { analysis = null; syncToggle(); }
          startOnce();
          analyze();
        });
      }
    });
    if (toggleInput) {
      toggleInput.addEventListener("change", function () {
        toggled = !!toggleInput.checked;
        if (ready) { analyze(); } else { start(); }
      });
    }
    if (mobileQuery && mobileQuery.addEventListener) {
      mobileQuery.addEventListener("change", function () { drawGraphs(); });
    }
    if ("requestIdleCallback" in window) {
      window.requestIdleCallback(start, { timeout: 2500 });
    } else {
      window.setTimeout(start, 1200);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      // The page's own script fills the shipment list in its own DOMContentLoaded
      // handler, which may run after this one; a zero timeout puts the first
      // read of the selected shipment behind every handler.
      window.setTimeout(function () { syncToggle(); schedule(); }, 0);
    });
  } else {
    window.setTimeout(function () { syncToggle(); schedule(); }, 0);
  }
})();
