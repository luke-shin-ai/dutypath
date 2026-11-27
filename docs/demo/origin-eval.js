// The origin verdict, computed in the tab.
//
// This is the same test the Python engine runs (src/dutypath/origin.py), written
// out in JavaScript so the page can answer a bill of materials it has changed
// without asking a server.  The division of work is the same as in Python:
//
//   * the graph answers which rule applies, which intervals that rule excludes,
//     where each material sits against those intervals, and which rate line
//     prices the good (cypher/07, 08 and 09, run by the engine in the worker);
//   * this file does the arithmetic and the level comparison, prints the path
//     it walked, and refuses to answer when a piece is missing.
//
// The rule sentence is read into its alternatives by the repository's parser at
// build time and travels with the page (case.reading.alternatives), because a
// sentence read is not something a browser should repeat with a second parser
// that could drift from the first.
//
// Nothing here writes: the material list is an argument and lives in the page.

(function (global) {
  var LEVEL_OF_KIND = { CC: 2, CTH: 4, CTSH: 6 };
  var LEVEL_WORDS = { 2: "chapter", 4: "heading", 6: "subheading" };

  function statedDigits(code) {
    return String(code === null || code === undefined ? "" : code).replace(/[^0-9]/g, "");
  }

  function span(code) {
    var digits = statedDigits(code);
    if (!digits) { return null; }
    if (digits.length > 8) { digits = digits.slice(0, 8); }
    return [digits + "0".repeat(8 - digits.length), digits + "9".repeat(8 - digits.length)];
  }

  function intervalRelation(code, low, high) {
    var bounds = span(code);
    var floor = span(low);
    var ceiling = span(high);
    if (!bounds || !floor || !ceiling) { return "across"; }
    if (bounds[1] < floor[0] || bounds[0] > ceiling[1]) { return "outside"; }
    if (bounds[0] >= floor[0] && bounds[1] <= ceiling[1]) { return "inside"; }
    return "across";
  }

  function pretty(code) {
    var digits = statedDigits(code);
    if (digits.length === 6) { return digits.slice(0, 4) + "." + digits.slice(4); }
    if (digits.length === 8) { return digits.slice(0, 4) + "." + digits.slice(4, 6) + "." + digits.slice(6); }
    return digits;
  }

  function levelName(code) {
    var digits = statedDigits(code);
    if (digits.length <= 2) { return "chapter"; }
    if (digits.length <= 4) { return "heading"; }
    if (digits.length <= 6) { return "subheading"; }
    return "tariff line";
  }

  function isUnder(child, parent) {
    var childDigits = statedDigits(child);
    var digits = statedDigits(parent);
    if (!childDigits || !digits) { return false; }
    if (childDigits.length < digits.length) { return false; }
    return childDigits.slice(0, digits.length) === digits;
  }

  function rounded(value) {
    if (value === null || value === undefined) { return null; }
    return Math.round(value * 100) / 100;
  }

  function partySet(parties) {
    var set = {};
    (parties || []).forEach(function (code) { set[String(code).toUpperCase()] = true; });
    return set;
  }

  function isParty(origin, parties) {
    return !!parties[String(origin || "").toUpperCase()];
  }

  function valueContent(materials, parties, fob) {
    var unknown = [];
    var nonParty = 0;
    var party = 0;
    materials.forEach(function (line) {
      if (line.value === null || line.value === undefined) { unknown.push(line.id); return; }
      if (isParty(line.origin, parties)) { party += line.value; } else { nonParty += line.value; }
    });
    if (unknown.length || !fob) {
      return {
        down: null, up: null, non_party: unknown.length ? null : nonParty,
        unknown_values: unknown, no_fob: !fob
      };
    }
    return {
      down: (fob - nonParty) / fob * 100.0,
      up: party / fob * 100.0,
      non_party: nonParty,
      unknown_values: [],
      no_fob: false
    };
  }

  function ctc(materialCode, goodCode, kind) {
    var level = LEVEL_OF_KIND[kind];
    var good = statedDigits(goodCode);
    var word = LEVEL_WORDS[level];
    if (good.length < level) {
      return {
        ok: null,
        why: "the good is stated at " + levelName(goodCode) + " level and a " + kind +
          " change needs the " + word
      };
    }
    var prefix = good.slice(0, level);
    var relation = intervalRelation(materialCode, prefix, prefix);
    if (relation === "across") {
      return {
        ok: null,
        why: "a finer classification than the " + levelName(materialCode) +
          " this material is stated at, to place it against " + word + " " + pretty(prefix)
      };
    }
    if (relation === "outside") {
      return { ok: true, why: word + " changes" };
    }
    if (kind === "CC") { return { ok: false, why: "same chapter " + prefix }; }
    if (kind === "CTH") { return { ok: false, why: "same heading " + prefix }; }
    return { ok: false, why: "same subheading " + prefix };
  }

  function conditionCount(alternative) {
    var count = (alternative.kinds || []).length;
    if (alternative.rvc_down !== null && alternative.rvc_down !== undefined) { count += 1; }
    if (alternative.rvc_up !== null && alternative.rvc_up !== undefined) { count += 1; }
    if (alternative.weight_min !== null && alternative.weight_min !== undefined) { count += 1; }
    return count;
  }

  // One alternative, one pass over the material list, in the order the engine
  // walks it.  Notes are kept per material so a picture can colour the line it
  // came from rather than the rule in general.
  function checkAlternative(alternative, index, goodCode, materials, parties, fob, hits, attributes) {
    var path = [];
    var reasons = [];
    var satisfied = [];
    var missing = [];
    var holds = true;
    var notes = {};
    var content = valueContent(materials, parties, fob);
    var down = content.down;
    var up = content.up;
    var nonParty = content.non_party;

    function note(position, status, detail) {
      notes[String(position)] = { status: status, detail: detail };
    }

    if (conditionCount(alternative) === 0) {
      return {
        index: index, holds: false,
        reason: "cannot decide this alternative: its sentence asks for a condition this parser did not read (" +
          String(alternative.text || "").slice(0, 120) + ")",
        path: [], rvc_down: rounded(down), rvc_up: rounded(up),
        missing: ["a testable reading of the alternative: " + String(alternative.text || "").slice(0, 100)],
        notes: notes, content: content
      };
    }

    (alternative.kinds || []).forEach(function (kind) {
      materials.forEach(function (line, position) {
        if (isParty(line.origin, parties)) {
          note(position, "party", "a party material, so no change is asked of it");
          return;
        }
        if (!statedDigits(line.code)) {
          missing.push("the tariff classification of material " + line.id);
          note(position, "unknown", "no tariff classification");
          return;
        }
        var lineHits = hits[String(position)] || [];
        var barred = null;
        for (var h = 0; h < lineHits.length; h += 1) {
          var hit = lineHits[h];
          if (hit.kind !== "excluded") { continue; }
          if (hit.relation === "across") {
            missing.push("a finer classification for material " + line.id + ", which is stated at " +
              levelName(line.code) + " level and sits across the exclusion " + hit.label);
            barred = "unknown";
            break;
          }
          barred = hit.label;
          break;
        }
        if (barred === "unknown") {
          note(position, "unknown", "stated too coarsely for the exclusion");
          return;
        }
        if (barred !== null) {
          holds = false;
          reasons.push(line.id + " " + line.code + " is in an excluded provision (" + barred + "): " + line.origin);
          path.push(line.id + " (" + line.code + ", " + line.origin + ") -[" + kind +
            "]-> excluded provision " + barred);
          note(position, "excluded", "excluded provision " + barred);
          return;
        }
        var permitted = (alternative.allowed_from || []).some(function (allowed) {
          return isUnder(line.code, allowed);
        });
        if (permitted) {
          path.push(line.id + " (" + line.code + ", " + line.origin + ") -[" + kind +
            "]-> permitted material from subheading " + (alternative.allowed_from || []).join(","));
          note(position, "pass", "a permitted source");
          return;
        }
        var groupHits = lineHits.filter(function (item) { return item.kind === "group"; });
        if (alternative.group && groupHits.length) {
          var relation = groupHits[0].relation;
          if (relation === "across") {
            missing.push("a finer classification for material " + line.id + ", which is stated at " +
              levelName(line.code) + " level and sits across the group " +
              pretty(alternative.group[0]) + " to " + pretty(alternative.group[1]) + " the rule excludes");
            note(position, "unknown", "stated too coarsely for the group");
            return;
          }
          if (relation === "inside") {
            holds = false;
            reasons.push(line.id + " " + line.code + " sits inside " + pretty(alternative.group[0]) +
              " to " + pretty(alternative.group[1]) + ", the group the rule excludes");
            path.push(line.id + " (" + line.code + ", " + line.origin + ") -[" + kind +
              "]-> inside group " + pretty(alternative.group[0]) + " to " + pretty(alternative.group[1]));
            note(position, "inside-group", "inside the excluded group " +
              pretty(alternative.group[0]) + " to " + pretty(alternative.group[1]));
            return;
          }
        }
        var verdict = ctc(line.code, goodCode, kind);
        if (verdict.ok === null) {
          missing.push("a finer classification for material " + line.id + ": " + verdict.why);
          note(position, "unknown", verdict.why);
          return;
        }
        if (verdict.ok) {
          path.push(line.id + " (" + line.code + ", " + line.origin + ") -[" + kind + "]-> " + verdict.why);
          note(position, "pass", verdict.why);
          return;
        }
        holds = false;
        reasons.push(line.id + " " + line.code + " from " + (line.origin || "unknown origin") + ": " +
          verdict.why + ", so the " + kind + " requirement fails");
        path.push(line.id + " (" + line.code + ", " + (line.origin || "?") + ") -[" + kind + "]-> " + verdict.why);
        note(position, "same-level", verdict.why);
      });
      var tested = materials.filter(function (line, position) {
        return !isParty(line.origin, parties) && statedDigits(line.code);
      });
      if (tested.length) {
        satisfied.push("every non party material (" + tested.length +
          " tested) changes classification as the " + kind + " requirement asks");
      } else {
        satisfied.push("no non party material is in the bill of materials, so the " + kind +
          " requirement is met without a material test");
      }
    });

    var floorDown = alternative.rvc_down === undefined ? null : alternative.rvc_down;
    var floorUp = alternative.rvc_up === undefined ? null : alternative.rvc_up;
    if (floorDown !== null || floorUp !== null) {
      if (down === null || up === null) {
        if (content.unknown_values.length) {
          missing.push("a declared value for material " + content.unknown_values.join(", ") +
            ", which the regional value content is computed from");
        }
        if (content.no_fob) {
          missing.push("declared value to compute regional value content");
        }
      } else {
        var downOk = floorDown !== null && down + 1e-9 >= floorDown;
        var upOk = floorUp !== null && up + 1e-9 >= floorUp;
        if (downOk || upOk) {
          if (downOk) {
            path.push("build down (declared value " + fob + " - non party materials " + nonParty +
              ") / " + fob + " = " + down.toFixed(2) + " percent, at or above " + floorDown + " percent");
            satisfied.push("regional value content " + down.toFixed(2) +
              " percent on the build down method meets the " + floorDown + " percent the rule asks for");
          }
          if (upOk) {
            path.push("build up " + up.toFixed(2) + " percent is at or above " + floorUp + " percent");
            satisfied.push("regional value content " + up.toFixed(2) +
              " percent on the build up method meets the " + floorUp + " percent the rule asks for");
          }
        } else {
          holds = false;
          reasons.push("regional value content " + down.toFixed(2) + " percent under the build down and " +
            up.toFixed(2) + " percent under the build up are both under the thresholds the rule asks for (" +
            (floorDown || 0) + " down, " + (floorUp || 0) + " up)");
          path.push("build down " + down.toFixed(2) + " percent, build up " + up.toFixed(2) +
            " percent, non party materials " + nonParty);
        }
      }
    }

    if (alternative.weight_min) {
      var supplied = attributes ? attributes.originating_polymer_weight_percent : null;
      if (supplied === null || supplied === undefined) {
        missing.push("originating polymer content as a share of total polymer weight (percent), " +
          "the rule asks for at least " + alternative.weight_min);
      } else if (Number(supplied) + 1e-9 < alternative.weight_min) {
        holds = false;
        reasons.push("originating polymer content " + Number(supplied).toFixed(1) +
          " percent is under " + alternative.weight_min + " percent by weight");
      } else {
        path.push("originating polymer content " + Number(supplied).toFixed(1) + " percent meets " +
          alternative.weight_min + " percent");
        satisfied.push("originating polymer content " + Number(supplied).toFixed(1) +
          " percent by weight meets the " + alternative.weight_min + " percent the rule asks for");
      }
    }

    var result = {
      index: index,
      holds: holds && missing.length === 0,
      reason: null,
      path: path,
      rvc_down: rounded(down),
      rvc_up: rounded(up),
      non_party: nonParty,
      missing: missing.slice(),
      notes: notes,
      content: content
    };
    if (missing.length) {
      result.reason = "cannot decide this alternative: " + missing.join("; ");
      result.holds = false;
    } else if (holds) {
      result.reason = satisfied.join("; ") || "alternative " + index + " holds";
    } else {
      result.reason = reasons.join("; ");
    }
    return result;
  }

  // The verdict for one market: the first alternative that holds wins, and an
  // alternative that cannot be decided is not a pass.
  function evaluateMarket(context) {
    var alternatives = context.alternatives || [];
    var materials = context.materials || [];
    var parties = partySet(context.parties);
    var fob = context.fob || null;
    var checks = [];
    var missing = [];
    if (!alternatives.length) {
      return {
        verdict: "UNDECIDABLE",
        reason: "no origin rule for " + (context.goodCode || "this good") + " under " +
          context.agreement + " in this snapshot",
        path: [],
        checks: [],
        rvc_down: null,
        rvc_up: null,
        non_party: null,
        missing: ["an origin rule for " + (context.goodCode || "this good")],
        notes: {}
      };
    }
    if (!materials.length) {
      return {
        verdict: "UNDECIDABLE",
        reason: "the bill of materials has no material lines, so no condition can be tested",
        path: [],
        checks: [],
        rvc_down: null,
        rvc_up: null,
        non_party: null,
        missing: ["the bill of materials: at least one material line"],
        notes: {}
      };
    }
    for (var index = 0; index < alternatives.length; index += 1) {
      var check = checkAlternative(
        alternatives[index], index + 1, context.goodCode, materials, parties, fob,
        (context.hits || {})[index + 1] || {}, context.attributes || null
      );
      checks.push(check);
      check.missing.forEach(function (item) {
        if (missing.indexOf(item) < 0) { missing.push(item); }
      });
      if (check.holds) {
        return {
          verdict: "ORIGINATING",
          reason: check.reason,
          path: check.path,
          checks: checks,
          rvc_down: check.rvc_down,
          rvc_up: check.rvc_up,
          non_party: check.non_party,
          missing: [],
          notes: check.notes,
          deciding: check.index
        };
      }
    }
    var first = checks[0];
    return {
      verdict: missing.length ? "UNDECIDABLE" : "NOT_ORIGINATING",
      reason: missing.length
        ? "cannot decide under this rule: " + missing.slice(0, 3).join("; ")
        : first.reason,
      path: missing.length ? first.path : first.path,
      checks: checks,
      rvc_down: first.rvc_down,
      rvc_up: first.rvc_up,
      non_party: first.non_party,
      missing: missing,
      notes: first.notes,
      deciding: first.index
    };
  }

  // Whether the documents on file let the preference be claimed, given that the
  // origin question is answered.  The requirement comes from the agreement; an
  // approval this agreement does not ask for cannot block a claim under it.
  function documentsAllow(approval) {
    if (!approval || !approval.required) { return true; }
    return approval.status === "VALID";
  }

  // The price of the route once the origin answer is known: the preferential
  // rate when the claim holds, the MFN rate when it does not, and nothing when
  // the snapshot cannot price either.
  function price(originVerdict, preferential, mfnPercent, value, approval) {
    var allowed = originVerdict === "ORIGINATING" && preferential !== null &&
      preferential !== undefined && documentsAllow(approval);
    var duty = null;
    if (allowed) {
      duty = value * preferential / 100;
    } else if (mfnPercent !== null && mfnPercent !== undefined) {
      duty = value * mfnPercent / 100;
    }
    return { allowed: allowed, duty: duty, preferential: preferential };
  }

  global.DUTYPATH_ORIGIN = {
    statedDigits: statedDigits,
    span: span,
    intervalRelation: intervalRelation,
    pretty: pretty,
    levelName: levelName,
    isUnder: isUnder,
    valueContent: valueContent,
    ctc: ctc,
    evaluateMarket: evaluateMarket,
    documentsAllow: documentsAllow,
    price: price
  };
})(window);
