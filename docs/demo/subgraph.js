// The picture of one verdict: the path the engine walked, drawn as a graph.
//
// The cells on the left are the input the page holds: the shipment and its bill
// of materials.  They are dashed, because the bill of materials is never
// written to the store.  Everything from the classification to the verdict is a
// node the worker read out of the engine (cypher/07, 08 and 09): the heading
// above the code, the origin rule, the intervals the rule excludes, the
// agreement, the rate line and the answer.
//
// One picture per market, because one bill of materials meets three different
// rules.  The path that is lit is the path the rule walked: a green cell and
// edge mean the condition held, a red one names the condition that failed.  Flip
// the key material in the panel and three pictures change together.

(function (global) {
  var PALETTE = {
    ink: "#10161f",
    muted: "#5a6672",
    line: "#c9d2dc",
    page: "#ffffff",
    input: "#f1f5f9",
    neutral: "#ffffff",
    ok: "#ecfdf5",
    okLine: "#0f766e",
    bad: "#fef2f2",
    badLine: "#b91c1c",
    unknown: "#eef2ff",
    unknownLine: "#1d4ed8"
  };

  function escapeText(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function money(amount, currency) {
    if (amount === null || amount === undefined) { return "not priced"; }
    var rounded = Math.round(amount * 100) / 100;
    return rounded.toLocaleString("en-US") + " " + currency;
  }

  function toneColours(tone) {
    if (tone === "ok") { return { fill: PALETTE.ok, stroke: PALETTE.okLine }; }
    if (tone === "bad") { return { fill: PALETTE.bad, stroke: PALETTE.badLine }; }
    if (tone === "unknown") { return { fill: PALETTE.unknown, stroke: PALETTE.unknownLine }; }
    if (tone === "input") { return { fill: PALETTE.input, stroke: PALETTE.line }; }
    return { fill: PALETTE.neutral, stroke: PALETTE.line };
  }

  // The condition a rule asks for, in one line a reader can check against the
  // sentence printed under the picture.
  function conditionText(rule) {
    if (!rule) { return "no rule"; }
    var parts = [];
    (rule.kinds || []).forEach(function (kind) {
      // RVC is a threshold, not a level change; it is printed from the numbers
      // below so a rule that says "CTH or RVC40" reads that way once.
      if (kind === "RVC") { return; }
      parts.push(kind);
    });
    if (rule.rvc_down !== null && rule.rvc_down !== undefined) { parts.push("RVC " + rule.rvc_down + "%"); }
    if (rule.rvc_up !== null && rule.rvc_up !== undefined) { parts.push("RVC up " + rule.rvc_up + "%"); }
    if (rule.weight_min !== null && rule.weight_min !== undefined) { parts.push("weight " + rule.weight_min + "%"); }
    return parts.length ? parts.join(" or ") : "not read into a test";
  }

  function intervalText(rule) {
    var pieces = [];
    if (rule && rule.group) {
      pieces.push("excludes " + global.DUTYPATH_ORIGIN.pretty(rule.group[0]) + " to " +
        global.DUTYPATH_ORIGIN.pretty(rule.group[1]));
    }
    return pieces;
  }

  function materialStatus(evaluation, position) {
    var note = (evaluation.notes || {})[String(position)];
    if (!note) { return { tone: "neutral", text: "" }; }
    if (note.status === "party") { return { tone: "ok", text: "a party material" }; }
    if (note.status === "pass") { return { tone: "ok", text: note.detail }; }
    if (note.status === "excluded" || note.status === "inside-group" || note.status === "same-level") {
      return { tone: "bad", text: note.detail };
    }
    return { tone: "unknown", text: note.detail };
  }

  function keyPosition(model) {
    var materials = model.materials || [];
    for (var index = 0; index < materials.length; index += 1) {
      var status = materialStatus(model.evaluation, index);
      if (status.tone === "bad" || status.tone === "unknown") { return index; }
    }
    return 0;
  }

  function cellsFor(model) {
    var materials = model.materials || [];
    var position = keyPosition(model);
    var key = materials[position] || { id: "M1", code: "", origin: "", value: null };
    var status = materialStatus(model.evaluation, position);
    var spine = model.spine || {};
    var good = spine.good || {};
    var keySpine = (spine.byRole || {})["material:" + key.id] || {};
    var count = materials.length;
    var verdict = model.evaluation.verdict;
    var verdictTone = verdict === "ORIGINATING" ? "ok" : (verdict === "NOT_ORIGINATING" ? "bad" : "unknown");
    var rateText = "pref " +
      (model.ratePercent === null || model.ratePercent === undefined ? "none" : model.ratePercent.toFixed(1) + "%") +
      " / MFN " + (model.mfnPercent === null || model.mfnPercent === undefined ? "none" : model.mfnPercent.toFixed(1) + "%");
    var ruleLines = [
      (model.rule || {}).id || "no rule",
      conditionText(model.rule),
      "covers " + ((model.rule || {}).code_from || "?") +
        ((model.rule || {}).code_to && model.rule.code_to !== model.rule.code_from
          ? " to " + model.rule.code_to : "")
    ].concat(intervalText(model.rule));
    var hasCtc = !!(model.rule && (model.rule.kinds || []).filter(function (kind) {
      return kind === "CC" || kind === "CTH" || kind === "CTSH";
    }).length);
    if (ruleLines.length < 4 && good.heading) { ruleLines.push("good heading " + good.heading); }
    var classification = keySpine.heading
      ? [
          "heading " + keySpine.heading,
          "subheading " + (keySpine.subheading || "not in snapshot"),
          "chapter " + (keySpine.chapter || "-")
        ]
      : [
          "no heading in snapshot",
          global.DUTYPATH_ORIGIN.levelName(key.code) + " level code",
          "no level read"
        ];

    return [
      {
        title: "Shipment",
        lines: [
          model.shipmentId || "",
          money(model.value, model.currency),
          model.stateLabel || ""
        ],
        tone: "input",
        dashed: true
      },
      {
        title: "Key material",
        lines: [
          key.id + "  " + (key.code || "no code"),
          (key.origin || "no origin") + ", " + money(key.value, model.currency),
          count === 1 ? "the only material line" : count + " material lines"
        ],
        tone: status.tone === "neutral" ? "input" : status.tone,
        dashed: true
      },
      {
        title: "Classification",
        lines: classification,
        // The classification is only part of the test when the rule asks for a
        // change of chapter, heading or subheading; an RVC rule never looks at
        // it, so the cell is not coloured against it there.
        tone: !hasCtc ? "neutral" : (keySpine.heading
          ? (status.tone === "ok" ? "ok" : (status.tone === "bad" ? "bad" : "neutral"))
          : "unknown")
      },
      {
        title: "Origin rule",
        lines: ruleLines.slice(0, 4),
        tone: "neutral"
      },
      {
        title: "Market and rate",
        lines: [
          model.agreement,
          "line " + (model.code || ""),
          rateText
        ],
        tone: verdictTone === "ok" ? "ok" : "neutral"
      },
      {
        title: "Verdict",
        lines: [
          verdict,
          "duty " + money(model.duty, model.currency),
          model.allowed ? "the claim holds" : "no claim"
        ],
        tone: verdictTone
      }
    ];
  }

  function truncate(text, limit) {
    var value = String(text === null || text === undefined ? "" : text);
    if (value.length <= limit) { return value; }
    return value.slice(0, limit - 1) + ".";
  }

  function drawHorizontal(cells, model) {
    var width = 1000;
    var padX = 6;
    var gap = 16;
    var cellW = (width - padX * 2 - gap * (cells.length - 1)) / cells.length;
    var cellH = 108;
    var titleH = 20;
    var height = titleH + cellH + 8;
    var parts = [];
    parts.push('<defs><marker id="arrow-' + model.market + '" viewBox="0 0 8 8" refX="7" refY="4" ' +
      'markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="' +
      PALETTE.line + '"></path></marker></defs>');

    var boxes = [];
    cells.forEach(function (cell, index) {
      var x = padX + index * (cellW + gap);
      var colours = toneColours(cell.tone);
      boxes.push({ x: x, y: titleH, w: cellW, h: cellH });
      parts.push('<rect x="' + x + '" y="' + titleH + '" width="' + cellW + '" height="' + cellH +
        '" rx="7" fill="' + colours.fill + '" stroke="' + colours.stroke + '" stroke-width="1.2"' +
        (cell.dashed ? ' stroke-dasharray="4 3"' : "") + '></rect>');
      parts.push('<text x="' + (x + 8) + '" y="' + (titleH + 15) + '" font-size="9.5" letter-spacing="0.4" ' +
        'fill="' + PALETTE.muted + '">' + escapeText(cell.title.toUpperCase()) + '</text>');
      cell.lines.slice(0, 4).forEach(function (line, lineIndex) {
        var weight = lineIndex === 0 ? ' font-weight="600"' : "";
        var size = lineIndex === 0 ? 11.5 : 10.5;
        var fill = lineIndex === 0 ? PALETTE.ink : PALETTE.muted;
        parts.push('<text x="' + (x + 8) + '" y="' + (titleH + 33 + lineIndex * 15) + '" font-size="' + size +
          '"' + weight + ' fill="' + fill + '">' + escapeText(truncate(line, 26)) + '</text>');
      });
    });

    for (var index = 0; index < boxes.length - 1; index += 1) {
      var from = boxes[index];
      var to = boxes[index + 1];
      var y = from.y + from.h / 2;
      var tone = "neutral";
      if (index < 2) { tone = "input"; }
      if (index === 2) { tone = cells[2].tone === "bad" ? "bad" : (cells[2].tone === "ok" ? "ok" : "neutral"); }
      if (index === 4) { tone = cells[5].tone === "bad" ? "bad" : "neutral"; }
      var stroke = tone === "bad" ? PALETTE.badLine : (tone === "ok" ? PALETTE.okLine : PALETTE.line);
      parts.push('<line x1="' + (from.x + from.w) + '" y1="' + y + '" x2="' + (to.x - 6) + '" y2="' + y +
        '" stroke="' + stroke + '" stroke-width="' + (tone === "neutral" ? 1.1 : 1.7) + '"' +
        (index < 2 ? ' stroke-dasharray="4 3"' : "") + ' marker-end="url(#arrow-' + model.market + ')"></line>');
    }
    return { body: parts.join(""), width: width, height: height };
  }

  function drawVertical(cells, model) {
    var width = 380;
    var padX = 4;
    var gap = 18;
    var cellW = width - padX * 2;
    var cellH = 78;
    var titleH = 18;
    var height = titleH + cells.length * (cellH + gap);
    var parts = [];
    parts.push('<defs><marker id="arrowv-' + model.market + '" viewBox="0 0 8 8" refX="7" refY="4" ' +
      'markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="' +
      PALETTE.line + '"></path></marker></defs>');
    var boxes = [];
    cells.forEach(function (cell, index) {
      var y = titleH + index * (cellH + gap);
      var colours = toneColours(cell.tone);
      boxes.push({ x: padX, y: y, w: cellW, h: cellH });
      parts.push('<rect x="' + padX + '" y="' + y + '" width="' + cellW + '" height="' + cellH +
        '" rx="7" fill="' + colours.fill + '" stroke="' + colours.stroke + '" stroke-width="1.2"' +
        (cell.dashed ? ' stroke-dasharray="4 3"' : "") + '></rect>');
      parts.push('<text x="' + (padX + 9) + '" y="' + (y + 14) + '" font-size="9" letter-spacing="0.4" ' +
        'fill="' + PALETTE.muted + '">' + escapeText(cell.title.toUpperCase()) + '</text>');
      cell.lines.slice(0, 4).forEach(function (line, lineIndex) {
        var weight = lineIndex === 0 ? ' font-weight="600"' : "";
        var size = lineIndex === 0 ? 11 : 10;
        var fill = lineIndex === 0 ? PALETTE.ink : PALETTE.muted;
        parts.push('<text x="' + (padX + 9) + '" y="' + (y + 30 + lineIndex * 13) + '" font-size="' + size +
          '"' + weight + ' fill="' + fill + '">' + escapeText(truncate(line, 46)) + '</text>');
      });
    });
    for (var index = 0; index < boxes.length - 1; index += 1) {
      var from = boxes[index];
      var to = boxes[index + 1];
      var x = padX + 26;
      var tone = "neutral";
      if (index < 2) { tone = "input"; }
      if (index === 2) { tone = cells[2].tone === "bad" ? "bad" : (cells[2].tone === "ok" ? "ok" : "neutral"); }
      if (index === 4) { tone = cells[5].tone === "bad" ? "bad" : "neutral"; }
      var stroke = tone === "bad" ? PALETTE.badLine : (tone === "ok" ? PALETTE.okLine : PALETTE.line);
      parts.push('<line x1="' + x + '" y1="' + (from.y + from.h) + '" x2="' + x + '" y2="' + (to.y - 5) +
        '" stroke="' + stroke + '" stroke-width="' + (tone === "neutral" ? 1.1 : 1.7) + '"' +
        (index < 2 ? ' stroke-dasharray="4 3"' : "") + ' marker-end="url(#arrowv-' + model.market + ')"></line>');
    }
    return { body: parts.join(""), width: width, height: height };
  }

  function render(host, model, options) {
    if (!host || !model || !model.evaluation) { return; }
    var cells = cellsFor(model);
    var drawn = (options && options.mobile) ? drawVertical(cells, model) : drawHorizontal(cells, model);
    var label = model.marketName + ": " + model.evaluation.verdict;
    var svg = '<svg viewBox="0 0 ' + drawn.width + " " + drawn.height + '" role="img" ' +
      'aria-label="' + escapeText(label) + '" preserveAspectRatio="xMidYMid meet" ' +
      'style="width:100%;height:auto;display:block">' +
      "<title>" + escapeText(label) + "</title>" + drawn.body + "</svg>";
    host.innerHTML = svg;
  }

  function legend() {
    return '<div class="graph-legend">' +
      '<span><i class="sw sw-input"></i>from the bill of materials (not stored)</span>' +
      '<span><i class="sw sw-ok"></i>condition held</span>' +
      '<span><i class="sw sw-bad"></i>condition failed</span>' +
      '<span><i class="sw sw-unknown"></i>cannot be decided</span>' +
      "</div>";
  }

  global.DUTYPATH_SUBGRAPH = { render: render, legend: legend, conditionText: conditionText };
})(window);
