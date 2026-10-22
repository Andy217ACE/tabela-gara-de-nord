// © 2026 Andy217Ace
// Tabela Gara de Nord — Statistici v2 (#statistici). One request per filter state:
// /api/stats/overview (cached on the server, read-only). The page explains itself: a
// summary in words, then one card per question — „Cum se citește”, the chart (SVG built
// with createElementNS + CSS classes: no inline styles, CSP), legend, N, the small-sample
// warning, „Vezi datele” (an accessible table) and a CSV export of the same data set.
// Rules: the delay is the one READ on the București Nord board; a missing value is „—”,
// never 0; N next to every figure; below the minimum sample no percentages; arrivals and
// departures never mixed; weather: correlation is not causation.
"use strict";

(function () {
  var App = window.TabelaApp;
  var S = App.stats;
  var el = App.el;
  var SVG_NS = "http://www.w3.org/2000/svg";
  var API = "/api/stats/overview";
  var BOARDS = ["arrival", "departure"];
  var BOARD_PL = { arrival: "Sosiri", departure: "Plecări" };
  var BOARD_CLS = { arrival: "ss-arr", departure: "ss-dep" };
  var WEEKDAYS = ["Luni", "Marți", "Miercuri", "Joi", "Vineri", "Sâmbătă", "Duminică"];
  var WD_SHORT = ["L", "Ma", "Mi", "J", "V", "S", "D"];
  var PERIODS = [["all", "Tot istoricul"], ["30", "30 de zile"], ["7", "7 zile"], ["1", "Azi"]];
  var BOARD_OPTS = [["", "Ambele"], ["arrival", "Sosiri"], ["departure", "Plecări"]];
  var FIELDS = ["perioada", "board", "operator", "tip", "doar_confirmate"];
  var STATE_TEXT = { confirmed: "Rezultat confirmat", unconfirmed: "Rezultat neconfirmat",
                     unknown: "Necunoscută", in_progress: "Încă pe tabelă" };
  var OBS_TEXT = { ok: "Citire completă", uncertain: "Citire nesigură",
                   rejected_low_conf: "Respinsă", incomplete: "Incompletă" };
  var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var $ = function (id) { return document.getElementById(id); };
  var nf = S.numFmt;
  var seq = 0;

  function num(v) { return v == null ? "—" : nf.format(v); }
  function minutes(v) { return v == null ? "—" : nf.format(v) + " min"; }
  function pct(v) { return v == null ? "—" : nf.format(v) + " %"; }
  function hh(h) { return (h < 10 ? "0" : "") + h; }
  function hourRange(h) { return hh(h) + ":00–" + hh(h) + ":59"; }
  function plural(n, one, many) { return S.plural(n, one, many); }
  function nid(prefix) { seq += 1; return "ss-" + prefix + "-" + seq; }

  function shortDay(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
    return m ? parseInt(m[3], 10) + "." + m[2] : String(iso || "");
  }

  function svg(tag, attrs, text) {
    var n = document.createElementNS(SVG_NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, String(attrs[k])); });
    if (text != null) n.textContent = text;
    return n;
  }

  function tip(node, text) { node.append(svg("title", {}, text)); return node; }

  // ---- params (URL hash) -----------------------------------------------------------------

  function clean(f, raw) {
    var v = raw == null ? "" : String(raw).trim();
    if (f === "perioada") return ["all", "30", "7", "1"].indexOf(v) >= 0 ? v : "all";
    if (f === "board") return v === "arrival" || v === "departure" ? v : "";
    if (f === "doar_confirmate") return v === "1" ? "1" : "";
    return v.slice(0, 40);
  }

  function readParams(params) {
    var p = {};
    FIELDS.forEach(function (f) { p[f] = clean(f, params.get(f)); });
    return p;
  }

  function query(p, extra) {
    var q = new URLSearchParams();
    FIELDS.forEach(function (f) {
      if (p[f] && !(f === "perioada" && p[f] === "all")) q.set(f, p[f]);
    });
    Object.keys(extra || {}).forEach(function (k) { q.set(k, extra[k]); });
    return q.toString();
  }

  function syncHash(p) {
    var q = query(p);
    var hash = "#statistici" + (q ? "?" + q : "");
    if (location.hash !== hash) history.replaceState(null, "", hash);
  }

  // ---- shell: filters + body ---------------------------------------------------------

  var v = { p: null, data: null, key: null, ctrl: null, ui: null, width: 0 };

  function segmented(name, label, opts) {
    var fs = el("fieldset", "ss-seg");
    fs.append(el("legend", "field-label", label));
    var row = el("div", "ss-seg-row");
    var inputs = {};
    opts.forEach(function (o) {
      var lab = el("label", "ss-seg-opt");
      var i = el("input");
      i.type = "radio";
      i.name = "ss-" + name;
      i.value = o[0];
      inputs[o[0]] = i;
      lab.append(i, el("span", null, o[1]));
      row.append(lab);
    });
    fs.append(row);
    return { node: fs, set: function (val) { Object.keys(inputs).forEach(function (k) { inputs[k].checked = k === val; }); },
             get: function () { var c = fs.querySelector("input:checked"); return c ? c.value : ""; } };
  }

  function selectField(name, label, allText) {
    var lab = el("label", "field ss-field ss-field-" + name);
    lab.append(el("span", "field-label", label));
    var s = el("select");
    s.id = "ss-" + name;
    s.name = name;
    lab.append(s);
    function fill(opts, cur) {
      var list = (opts || []).slice();
      if (cur && !list.some(function (o) { return o.name === cur; })) list.unshift({ name: cur, n: 0 });
      var all = el("option", null, allText);
      all.value = "";
      var nodes = [all];
      list.forEach(function (o) {
        var opt = el("option", null, o.name + (o.n ? " (" + o.n + ")" : ""));
        opt.value = o.name;
        nodes.push(opt);
      });
      s.replaceChildren.apply(s, nodes);
      s.value = cur || "";
    }
    fill([], "");
    return { node: lab, input: s, fill: fill };
  }

  function ensure() {
    if (v.ui) return;
    var root = $("st-statistici");
    var form = el("form", "ss-filters");
    form.setAttribute("role", "search");
    form.setAttribute("aria-label", "Filtre statistici");
    form.noValidate = true;
    var per = segmented("perioada", "Perioada", PERIODS);
    var brd = segmented("board", "Panou", BOARD_OPTS);
    var op = selectField("operator", "Operator", "Toți operatorii");
    var tp = selectField("tip", "Tip de tren", "Toate tipurile");
    var chk = el("label", "ss-check");
    var ci = el("input");
    ci.type = "checkbox";
    ci.id = "ss-confirmate";
    chk.append(ci, el("span", null, "Doar rezultate confirmate"));
    form.append(per.node, brd.node, op.node, tp.node, chk);
    function read() {
      return { perioada: per.get() || "all", board: brd.get(), operator: op.input.value,
               tip: tp.input.value, doar_confirmate: ci.checked ? "1" : "" };
    }
    form.addEventListener("change", function () {
      v.p = read();
      syncHash(v.p);
      load();
    });
    form.addEventListener("submit", function (e) { e.preventDefault(); });
    var body = el("div", "ss-body");
    root.replaceChildren(form, body);
    v.ui = { form: form, body: body, per: per, brd: brd, op: op, tp: tp, ci: ci };
    window.addEventListener("resize", debounce(function () {
      if (!v.data || $("view-statistici").hidden) return;
      var w = v.ui.body.clientWidth;
      if (Math.abs(w - v.width) > 24) render(v.data);
    }, 200));
  }

  function debounce(fn, ms) {
    var t = null;
    return function () { clearTimeout(t); t = setTimeout(fn, ms); };
  }

  function setForm(p) {
    v.ui.per.set(p.perioada || "all");
    v.ui.brd.set(p.board || "");
    v.ui.op.fill(v.data && v.data.options ? v.data.options.operators : [], p.operator);
    v.ui.tp.fill(v.data && v.data.options ? v.data.options.types : [], p.tip);
    v.ui.ci.checked = p.doar_confirmate === "1";
  }

  function load() {
    var q = query(v.p);
    var url = API + (q ? "?" + q : "");
    if (url === v.key && v.data) return;
    v.key = url;
    if (v.ctrl) v.ctrl.abort();
    var ctrl = new AbortController();
    v.ctrl = ctrl;
    var root = $("st-statistici");
    root.classList.add("is-loading");
    root.setAttribute("aria-busy", "true");
    if (!v.data) v.ui.body.replaceChildren(el("p", "detail-note", "Se încarcă statisticile…"));
    S.getJSON(url, ctrl)
      .then(function (d) {
        if (v.ctrl !== ctrl) return;
        v.data = d;
        setForm(v.p);
        render(d);
      })
      .catch(function (e) {
        if (v.ctrl !== ctrl || e.aborted) return;
        v.data = null;
        v.key = null;
        v.ui.body.replaceChildren(S.notice(S.errorText(e), "notice-error"));
      })
      .then(function () {
        if (v.ctrl === ctrl) {
          v.ctrl = null;
          root.classList.remove("is-loading");
          root.removeAttribute("aria-busy");
        }
      });
  }

  function show(params) {
    ensure();
    v.p = readParams(params);
    setForm(v.p);
    load();
  }

  // ---- building blocks ---------------------------------------------------------------

  function boardsOf(d) { return BOARDS.filter(function (b) { return d.boards && d.boards[b]; }); }

  function csvLink(set, label) {
    var a = el("a", "btn btn-ghost btn-sm ss-csv", label || "CSV");
    a.href = API + "?" + query(v.p, { format: "csv", set: set });
    a.setAttribute("download", "");
    return a;
  }

  function legend(boards, extra) {
    var box = el("div", "ss-legend");
    if (boards.length > 1) {
      boards.forEach(function (b) {
        var it = el("span", "ss-legend-item");
        it.append(el("span", "ss-key " + BOARD_CLS[b]), document.createTextNode(BOARD_PL[b]));
        box.append(it);
      });
    }
    (extra || []).forEach(function (x) {
      var it = el("span", "ss-legend-item");
      it.append(el("span", "ss-key " + x[0]), document.createTextNode(x[1]));
      box.append(it);
    });
    return box.childNodes.length ? box : null;
  }

  // A question card: title, how to read, chart host, notes, table, export.
  function figure(o) {
    var sec = el("section", "ss-fig" + (o.wide ? " ss-fig-wide" : ""));
    var hid = nid("h");
    sec.setAttribute("aria-labelledby", hid);
    var head = el("div", "ss-fig-head");
    var h = el("h2", "ss-fig-title", o.title);
    h.id = hid;
    head.append(h);
    if (o.set) head.append(csvLink(o.set));
    sec.append(head);
    if (o.how) {
      var how = el("p", "ss-how");
      how.append(el("strong", null, "Cum se citește: "), document.createTextNode(o.how));
      sec.append(how);
    }
    if (o.legend) sec.append(o.legend);
    var host = el("div", "ss-chart");
    sec.append(host);
    var foot = el("div", "ss-fig-foot");
    sec.append(foot);
    v.ui.body.append(sec);
    return { sec: sec, host: host, foot: foot, titleId: hid };
  }

  // Small multiples: every cell exists (and is laid out) before any chart measures its width.
  function multiples(host, n) {
    var grid = el("div", "ss-multiples");
    host.append(grid);
    var cells = [];
    for (var i = 0; i < n; i++) {
      cells.push(el("div", "ss-multiple"));
      grid.append(cells[i]);
    }
    return cells;
  }

  function nLine(text) { return el("p", "ss-n", text); }
  function warn(text) { return el("p", "st-warn ss-warn", text); }

  // „Vezi datele”: the chart as an accessible table.
  function dataTable(caption, cols, rows) {
    var det = el("details", "ss-data");
    det.append(el("summary", null, "Vezi datele (tabel)"));
    var wrap = el("div", "st-scroll");
    wrap.tabIndex = 0;
    wrap.setAttribute("role", "region");
    wrap.setAttribute("aria-label", caption);
    var t = el("table", "st-table ss-table");
    t.append(el("caption", "sr-only", caption));
    var thead = el("thead");
    var tr = el("tr");
    cols.forEach(function (c, i) {
      var th = el("th", i ? "st-num" : null, c);
      th.scope = "col";
      tr.append(th);
    });
    thead.append(tr);
    var tbody = el("tbody");
    rows.forEach(function (r) {
      var row = el("tr");
      r.forEach(function (c, i) {
        var cell;
        if (i === 0) { cell = el("th", null, c == null ? "—" : String(c)); cell.scope = "row"; }
        else cell = el("td", "st-num", c == null ? "—" : String(c));
        row.append(cell);
      });
      tbody.append(row);
    });
    t.append(thead, tbody);
    wrap.append(t);
    det.append(wrap);
    return det;
  }

  function niceMax(v, ticks) {
    var t = ticks || 4;
    if (!(v > 0)) return { max: 1, step: 1 };
    var raw = v / t;
    var mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
    var steps = [1, 2, 2.5, 5, 10];
    for (var i = 0; i < steps.length; i++) {
      var s = steps[i] * mag;
      if (raw <= s) return { max: Math.ceil(v / s) * s, step: s };
    }
    return { max: Math.ceil(v / (10 * mag)) * 10 * mag, step: 10 * mag };
  }

  function chartWidth(host) {
    var w = host.clientWidth || (v.ui.body.clientWidth - 32) || 320;
    v.width = v.ui.body.clientWidth;
    return Math.max(260, Math.min(1100, Math.floor(w)));
  }

  function svgRoot(W, H, title, desc) {
    var id = nid("c");
    var root = svg("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H, class: "ss-svg",
                            role: "img", "aria-labelledby": id + "-t " + id + "-d" });
    root.append(svg("title", { id: id + "-t" }, title));
    root.append(svg("desc", { id: id + "-d" }, desc));
    return root;
  }

  // vertical bar with a 4 px rounded data end, square on the baseline
  function vbar(x, y, w, h, cls) {
    if (h <= 0) return null;
    var r = Math.min(4, w / 2, h);
    var d = "M" + x + "," + (y + h) + "V" + (y + r) + "Q" + x + "," + y + " " + (x + r) + "," + y +
      "H" + (x + w - r) + "Q" + (x + w) + "," + y + " " + (x + w) + "," + (y + r) + "V" + (y + h) + "Z";
    return svg("path", { d: d, class: "ss-bar " + cls });
  }

  function hbar(x, y, w, h, cls) {
    if (w <= 0) return null;
    var r = Math.min(4, h / 2, w);
    var d = "M" + x + "," + y + "H" + (x + w - r) + "Q" + (x + w) + "," + y + " " + (x + w) + "," + (y + r) +
      "V" + (y + h - r) + "Q" + (x + w) + "," + (y + h) + " " + (x + w - r) + "," + (y + h) + "H" + x + "Z";
    return svg("path", { d: d, class: "ss-bar " + cls });
  }

  function yGrid(root, L, R, W, y, ys, fmt) {
    var g = svg("g", { class: "ss-grid", "aria-hidden": "true" });
    for (var t = 0; t <= ys.max + 1e-9; t += ys.step) {
      g.append(svg("line", { x1: L, x2: W - R, y1: y(t).toFixed(1), y2: y(t).toFixed(1) }));
      g.append(svg("text", { x: L - 6, y: (y(t) + 4).toFixed(1), class: "ss-tick ss-tick-y" }, fmt(t)));
    }
    root.append(g);
  }

  // Grouped columns: cats = labels, series = [{board, values:[n|null], tips:[text], labels:[text|null]}]
  function columns(host, o) {
    var W = chartWidth(host);
    var H = o.height || 220;
    var L = 40, R = 8, T = 24, B = 28;
    var all = [];
    o.series.forEach(function (s) { s.values.forEach(function (x) { if (x != null) all.push(x); }); });
    var ys = o.yMax ? { max: o.yMax, step: o.yStep || o.yMax / 4 } : niceMax(Math.max.apply(null, all.concat([0])));
    var y = function (val) { return T + (1 - val / ys.max) * (H - T - B); };
    var n = o.cats.length;
    var band = (W - L - R) / Math.max(1, n);
    var k = o.series.length;
    var bw = Math.max(2, Math.min(24, (band * 0.78 - 2 * (k - 1)) / k));
    var root = svgRoot(W, H, o.title, o.desc);
    yGrid(root, L, R, W, y, ys, o.yFmt || function (t) { return nf.format(t); });
    if (o.unit) root.append(svg("text", { x: 4, y: 10, class: "ss-tick ss-unit" }, o.unit));
    var every = Math.ceil(28 / band);
    o.cats.forEach(function (c, i) {
      var cx = L + band * i + band / 2;
      var group = k * bw + (k - 1) * 2;
      o.series.forEach(function (s, j) {
        var val = s.values[i];
        var x = cx - group / 2 + j * (bw + 2);
        var g = svg("g", { class: "ss-mark" });
        if (val != null && val > 0) {
          var b = vbar(x, y(val), bw, (H - B) - y(val), BOARD_CLS[s.board] + (s.low && s.low[i] ? " ss-low" : ""));
          if (b) g.append(b);
          if (s.labels && s.labels[i] != null && band / k >= 22) {
            g.append(svg("text", { x: (x + bw / 2).toFixed(1), y: (y(val) - 4).toFixed(1), class: "ss-vlabel" }, s.labels[i]));
          }
        }
        // hit area bigger than the mark
        var hit = svg("rect", { x: (x - 1).toFixed(1), y: T, width: (bw + 2).toFixed(1), height: H - T - B, class: "ss-hit" });
        g.append(hit);
        tip(g, s.tips[i]);
        root.append(g);
      });
      if (i % every === 0) {
        root.append(svg("text", { x: cx.toFixed(1), y: H - B + 16, class: "ss-tick ss-tick-x" }, c));
      }
    });
    root.append(svg("line", { x1: L, x2: W - R, y1: H - B, y2: H - B, class: "ss-axis" }));
    host.append(root);
  }

  // Lines over 24 hours / days: series = [{board, values:[n|null], low:[bool], tips:[...]}];
  // a line joins consecutive sufficient points only; small samples = hollow markers.
  function lines(host, o) {
    var W = chartWidth(host);
    var H = o.height || 220;
    var L = 40, R = 12, T = 24, B = 28;
    var all = [];
    o.series.forEach(function (s) { s.values.forEach(function (x) { if (x != null) all.push(x); }); });
    var ys = o.yMax ? { max: o.yMax, step: o.yStep || o.yMax / 4 } : niceMax(Math.max.apply(null, all.concat([1])));
    var n = o.cats.length;
    var band = (W - L - R) / Math.max(1, n);
    var x = function (i) { return L + band * i + band / 2; };
    var y = function (val) { return T + (1 - val / ys.max) * (H - T - B); };
    var root = svgRoot(W, H, o.title, o.desc);
    yGrid(root, L, R, W, y, ys, o.yFmt || function (t) { return nf.format(t); });
    if (o.unit) root.append(svg("text", { x: 4, y: 10, class: "ss-tick ss-unit" }, o.unit));
    var every = Math.ceil(30 / band);
    o.cats.forEach(function (c, i) {
      if (i % every === 0) root.append(svg("text", { x: x(i).toFixed(1), y: H - B + 16, class: "ss-tick ss-tick-x" }, c));
    });
    root.append(svg("line", { x1: L, x2: W - R, y1: H - B, y2: H - B, class: "ss-axis" }));
    o.series.forEach(function (s) {
      var d = "", pen = false;
      s.values.forEach(function (val, i) {
        var ok = val != null && !(s.low && s.low[i]);
        if (ok) { d += (pen ? "L" : "M") + x(i).toFixed(1) + "," + y(val).toFixed(1); pen = true; }
        else pen = false;
      });
      if (d) root.append(svg("path", { d: d, class: "ss-line " + BOARD_CLS[s.board] }));
    });
    o.series.forEach(function (s) {
      s.values.forEach(function (val, i) {
        if (val == null) return;
        var g = svg("g", { class: "ss-mark" });
        g.append(svg("circle", { cx: x(i).toFixed(1), cy: y(val).toFixed(1), r: 4,
                                 class: "ss-dot " + BOARD_CLS[s.board] + (s.low && s.low[i] ? " ss-dot-low" : "") }));
        g.append(svg("circle", { cx: x(i).toFixed(1), cy: y(val).toFixed(1), r: 12, class: "ss-hit" }));
        tip(g, s.tips[i]);
        root.append(g);
      });
    });
    host.append(root);
  }

  // N per category, a slim strip under a chart (its own scale, never a second axis).
  function nStrip(host, o) {
    var W = chartWidth(host);
    var H = 64, L = 40, R = o.right || 12, T = 6, B = 18;
    var all = [];
    o.series.forEach(function (s) { all = all.concat(s.values); });
    var mx = Math.max.apply(null, all.concat([1]));
    var n = o.cats.length;
    var band = (W - L - R) / Math.max(1, n);
    var k = o.series.length;
    var bw = Math.max(2, Math.min(12, (band * 0.7 - (k - 1)) / k));
    var root = svgRoot(W, H, o.title, o.desc);
    root.append(svg("text", { x: L - 6, y: T + 9, class: "ss-tick ss-tick-y" }, nf.format(mx)));
    root.append(svg("text", { x: 4, y: H - B + 4, class: "ss-tick ss-nhead" }, "N"));
    o.cats.forEach(function (c, i) {
      var cx = L + band * i + band / 2;
      var group = k * bw + (k - 1);
      o.series.forEach(function (s, j) {
        var val = s.values[i] || 0;
        var h = (val / mx) * (H - T - B);
        var g = svg("g", { class: "ss-mark" });
        var b = vbar(cx - group / 2 + j * (bw + 1), H - B - h, bw, h, BOARD_CLS[s.board] + " ss-nbar");
        if (b) g.append(b);
        g.append(svg("rect", { x: (cx - band / 2).toFixed(1), y: T, width: band.toFixed(1), height: H - T - B, class: "ss-hit" }));
        tip(g, c + " · " + BOARD_PL[s.board] + ": N = " + val);
        root.append(g);
      });
    });
    root.append(svg("line", { x1: L, x2: W - R, y1: H - B, y2: H - B, class: "ss-axis" }));
    host.append(root);
  }

  // Horizontal bars: rows = [{label, value|null, valueText, sub, low, href}], max
  function hbars(host, o) {
    var W = chartWidth(host);
    var rowH = 34;
    var labW = Math.min(160, Math.max(84, Math.round(W * 0.3)));
    var valW = Math.min(170, Math.max(112, Math.round(W * 0.36)));
    var maxChars = Math.max(6, Math.floor((labW - 10) / 6.8));
    var H = Math.max(rowH, o.rows.length * rowH) + 4;
    var plotW = W - labW - valW - 8;
    var root = svgRoot(W, H, o.title, o.desc);
    o.rows.forEach(function (r, i) {
      var y0 = i * rowH + 4;
      var g = svg("g", { class: "ss-mark" });
      var label = r.label.length > maxChars ? r.label.slice(0, maxChars - 1) + "…" : r.label;
      g.append(svg("text", { x: labW - 8, y: y0 + 16, class: "ss-hlabel" }, label));
      g.append(svg("rect", { x: labW, y: y0 + 4, width: plotW, height: 16, class: "ss-track" }));
      if (r.value != null && r.value > 0) {
        var b = hbar(labW, y0 + 4, Math.max(2, plotW * Math.min(1, r.value / o.max)), 16,
                     (r.cls || BOARD_CLS[o.board]) + (r.low ? " ss-low" : ""));
        if (b) g.append(b);
      }
      g.append(svg("text", { x: labW + plotW + 8, y: y0 + 16, class: "ss-hvalue" + (r.low ? " ss-muted" : "") }, r.valueText));
      g.append(svg("rect", { x: 0, y: y0, width: W, height: rowH, class: "ss-hit" }));
      tip(g, r.label + ": " + r.tip);
      root.append(g);
    });
    host.append(root);
  }

  // ---- sections ------------------------------------------------------------------------

  function periodText(d) {
    var c = d.coverage || {};
    if (!c.first) return "nicio zi cu date";
    var span = c.first === c.last ? S.dayText(c.first) : S.dayText(c.first) + " – " + S.dayText(c.last);
    return span + " (" + plural(c.days || 0, "zi cu date", "zile cu date") + ")";
  }

  function summary(d) {
    var c = d.coverage || {};
    var h = d.history || {};
    var p = d.params || {};
    var sec = el("section", "ss-summary");
    sec.setAttribute("aria-labelledby", "ss-sum-h");
    var head = el("div", "ss-fig-head");
    var t = el("h2", "ss-fig-title", "Pe scurt");
    t.id = "ss-sum-h";
    head.append(t);
    var exp = el("div", "st-exports");
    var j = el("a", "btn btn-ghost btn-sm ss-csv", "Toate datele (JSON)");
    j.href = API + (query(v.p) ? "?" + query(v.p) : "");
    j.target = "_blank";
    j.rel = "noopener";
    exp.append(j);
    head.append(exp);
    sec.append(head);

    var cov = el("p", "ss-coverage");
    var ex = c.excluded || {};
    cov.textContent = "Perioada: " + periodText(d) + " · " +
      plural(c.journeys || 0, "călătorie", "călătorii") + " (" + plural(c.trains || 0, "tren", "trenuri") + ") · " +
      plural(c.observations || 0, "observație OCR", "observații OCR") + " · excluse: " +
      plural(ex.ghost || 0, "fantomă", "fantome") + ", " + (ex.low_quality || 0) + " din perioada de calitate redusă" +
      (p.operator ? " · operator: " + p.operator : "") + (p.tip ? " · tip: " + p.tip : "") +
      (p.confirmed_only ? " · doar rezultate confirmate" : "");
    sec.append(cov);

    if (!h.sufficient) {
      var w = el("p", "st-warn ss-history");
      w.setAttribute("role", "note");
      w.append(el("strong", null, "Date insuficiente încă — " + plural(h.days || 0, "zi", "zile") + " de istoric. "),
        document.createTextNode("Cifrele de mai jos sunt reale (citite de pe tabelă), dar tendințele pe ore, zile " +
          "și operatori devin sigure abia după cel puțin " + (h.needed_days || 7) + " zile; se vor schimba pe " +
          "măsură ce se adună date."));
      sec.append(w);
    }
    var ul = el("ul", "ss-insights");
    (d.insights || []).forEach(function (s) { ul.append(el("li", null, s)); });
    sec.append(ul);
    var when = el("p", "ss-generated");
    var g = d.generated_at ? new Date(d.generated_at) : null;
    when.textContent = "Calculat la " + (g && !isNaN(g) ? g.toLocaleTimeString("ro-RO", { timeZone: "Europe/Bucharest" }) : "—") +
      " · se recalculează cel mult o dată la " + (d.cache_ttl_s || 60) + " s · „la timp” = întârziere citită ≤ " +
      p.on_time_max_min + " min · eșantion minim " + p.min_sample + " călătorii";
    sec.append(when);
    v.ui.body.append(sec);
  }

  function kpis(d, boards) {
    var p = d.params || {};
    var box = el("div", "ss-kpis");
    boards.forEach(function (b) {
      var s = d.boards[b];
      var card = el("section", "ss-kpi");
      var h = el("h2", "ss-kpi-h");
      h.append(el("span", "ss-key " + BOARD_CLS[b]), document.createTextNode(BOARD_PL[b]));
      card.append(h);
      var hero = el("p", "ss-hero");
      if (s.n && s.sufficient) {
        hero.append(el("span", "ss-hero-v", pct(s.on_time_pct)),
                    el("span", "ss-hero-l", " la timp (≤ " + p.on_time_max_min + " min)"));
      } else {
        hero.append(el("span", "ss-hero-v ss-muted", "—"),
                    el("span", "ss-hero-l", s.n ? " eșantion mic: procentul nu se afișează" : " nicio călătorie cu întârziere citită"));
      }
      card.append(hero);
      card.append(nLine(s.n ? s.on_time + " din " + s.n + " călătorii încheiate cu întârziere citită (N = " + s.n + ")" +
        " · " + plural(s.journeys || 0, "călătorie observată", "călătorii observate") : "N = 0 · " +
        plural(s.journeys || 0, "călătorie observată", "călătorii observate")));
      var dl = el("dl", "ss-kpi-grid");
      [["Mediană", minutes(s.median)], ["Medie", minutes(s.mean)], ["p90", minutes(s.p90)],
       ["Peste 30 min", s.n ? s.over_30 + (s.over_30_pct != null ? " (" + pct(s.over_30_pct) + ")" : "") : "—"],
       ["Maxim", minutes(s.max)]].forEach(function (x) {
        var it = el("div", "ss-kpi-item");
        it.append(el("dt", null, x[0]), el("dd", null, x[1]));
        dl.append(it);
      });
      card.append(dl);
      if (s.n && !s.sufficient) card.append(warn("Eșantion mic (N = " + s.n + " < " + p.min_sample + "): doar cifre brute, fără procente."));
      box.append(card);
    });
    v.ui.body.append(box);
  }

  function smallNote(n, min) {
    return n > 0 && n < min ? "Eșantion mic (N = " + n + " < " + min + "): procentele nu se afișează." : null;
  }

  function distributionSection(d, boards) {
    var p = d.params;
    var usePct = boards.every(function (b) { return d.boards[b].sufficient; });
    var f = figure({ title: "Cât de mult întârzie trenurile?", set: "distribution", legend: legend(boards),
      how: "fiecare coloană arată " + (usePct ? "ce procent din" : "câte dintre") + " călătoriile încheiate cu " +
        "întârziere citită au avut întârzierea în intervalul de minute de sub ea. Primele două intervale (0 și 1–5 min) " +
        "înseamnă „la timp”." });
    var cats = (d.distribution[boards[0]] || []).map(function (x) { return x.label; });
    columns(f.host, { cats: cats, unit: usePct ? "%" : "călătorii",
      title: "Distribuția întârzierilor citite", desc: "Coloane grupate pe intervale de întârziere, pentru " +
        boards.map(function (b) { return BOARD_PL[b].toLowerCase(); }).join(" și ") + ".",
      series: boards.map(function (b) {
        var items = d.distribution[b];
        return { board: b,
          values: items.map(function (x) { return usePct ? x.pct : x.n; }),
          labels: items.map(function (x) { return usePct ? (x.pct == null ? null : nf.format(Math.round(x.pct)) + "%") : String(x.n); }),
          tips: items.map(function (x) { return BOARD_PL[b] + ", " + x.label + " min: " + x.n + " călătorii" + (x.pct != null ? " (" + pct(x.pct) + ")" : "") + " din N = " + d.boards[b].n; }) };
      }) });
    f.foot.append(nLine(boards.map(function (b) { return BOARD_PL[b] + ": N = " + d.boards[b].n; }).join(" · ")));
    boards.forEach(function (b) { var w = smallNote(d.boards[b].n, p.min_sample); if (w) f.foot.append(warn(BOARD_PL[b] + " — " + w)); });
    var rows = [];
    cats.forEach(function (c, i) {
      var r = [c + " min"];
      boards.forEach(function (b) { var x = d.distribution[b][i]; r.push(x.n, x.pct == null ? "—" : pct(x.pct)); });
      rows.push(r);
    });
    var cols = ["Întârziere"];
    boards.forEach(function (b) { cols.push(BOARD_PL[b] + " (călătorii)", BOARD_PL[b] + " (%)"); });
    f.foot.append(dataTable("Distribuția întârzierilor citite", cols, rows));
  }

  function hourlySection(d, boards) {
    var p = d.params;
    var cats = [];
    for (var h = 0; h < 24; h++) cats.push(hh(h));
    var f = figure({ title: "La ce oră întârzie cel mai mult?", set: "hourly", wide: true,
      legend: legend(boards, [["ss-key-hollow", "eșantion mic (N < " + p.min_sample + ")"]]),
      how: "pe orizontală e ora programată (00–23); punctul arată mediana întârzierii citite pentru trenurile " +
        "din acea oră — jumătate dintre ele au întârziat mai puțin, jumătate mai mult. Cercurile goale au prea puține " +
        "călătorii: cifra e reală, dar nesigură, și nu e legată în linie. Banda de dedesubt arată câte călătorii (N) " +
        "stau în spatele fiecărei ore." });
    lines(f.host, { cats: cats, unit: "min",
      title: "Mediana întârzierii pe ora programată", desc: "Mediana întârzierii citite pe fiecare oră din zi, pe panou.",
      series: boards.map(function (b) {
        var hs = d.hourly[b];
        return { board: b, values: hs.map(function (x) { return x.median; }),
          low: hs.map(function (x) { return !x.sufficient; }),
          tips: hs.map(function (x) {
            return BOARD_PL[b] + ", " + hourRange(x.key) + ": mediana " + minutes(x.median) + ", medie " + minutes(x.mean) +
              ", N = " + x.n + (x.n && !x.sufficient ? " (eșantion mic)" : "");
          }) };
      }) });
    nStrip(f.host, { cats: cats, title: "N pe oră", desc: "Numărul de călătorii cu întârziere citită pe fiecare oră.",
      series: boards.map(function (b) { return { board: b, values: d.hourly[b].map(function (x) { return x.n; }) }; }) });
    var rows = [];
    for (var i = 0; i < 24; i++) {
      var r = [hourRange(i)];
      boards.forEach(function (b) { var x = d.hourly[b][i]; r.push(x.n, minutes(x.median), minutes(x.mean), pct(x.on_time_pct)); });
      rows.push(r);
    }
    var cols = ["Ora programată"];
    boards.forEach(function (b) { var L = BOARD_PL[b]; cols.push(L + " N", L + " mediană", L + " medie", L + " % la timp"); });
    f.foot.append(dataTable("Întârzierea pe ora programată", cols, rows));
  }

  var HEAT_BINS = [[2, "0–2 min"], [5, "3–5 min"], [10, "6–10 min"], [20, "11–20 min"], [Infinity, "peste 20 min"]];

  function heatClass(c) {
    if (!c) return "ss-cell-none";
    if (!c.sufficient) return "ss-cell-low";
    for (var i = 0; i < HEAT_BINS.length; i++) if (c.mean <= HEAT_BINS[i][0]) return "ss-q" + i;
    return "ss-q4";
  }

  function heatmapSection(d, boards) {
    var p = d.params;
    var lg = el("div", "ss-legend ss-legend-scale");
    HEAT_BINS.forEach(function (b, i) {
      var it = el("span", "ss-legend-item");
      it.append(el("span", "ss-key ss-key-sq ss-q" + i), document.createTextNode(b[1]));
      lg.append(it);
    });
    [["ss-cell-low", "N < " + p.min_sample], ["ss-cell-none", "fără date"]].forEach(function (x) {
      var it = el("span", "ss-legend-item");
      it.append(el("span", "ss-key ss-key-sq " + x[0]), document.createTextNode(x[1]));
      lg.append(it);
    });
    var f = figure({ title: "Ce zile și ore sunt cele mai problematice?", set: "heatmap", wide: true, legend: lg,
      how: "fiecare pătrat este o oră (pe orizontală) dintr-o zi a săptămânii (pe verticală); cu cât culoarea e mai " +
        "închisă, cu atât întârzierea medie citită e mai mare. Pătratele gri au sub " + p.min_sample +
        " călătorii (prea puține pentru o concluzie); cele goale n-au nicio călătorie. Treci cu mouse-ul peste un pătrat pentru cifre." });
    var cells = multiples(f.host, boards.length);
    boards.forEach(function (b, bi) {
      var cell = cells[bi];
      var h = el("h3", "ss-mult-h");
      h.append(el("span", "ss-key " + BOARD_CLS[b]), document.createTextNode(BOARD_PL[b]));
      cell.append(h);
      var map = {};
      (d.heatmap[b] || []).forEach(function (c) { map[c.d + "-" + c.h] = c; });
      var W = chartWidth(cell);
      var L = 26, T = 4, B = 18;
      var cw = (W - L - 2) / 24;
      var ch = Math.max(14, Math.min(26, cw));
      var H = T + 7 * ch + B;
      var root = svgRoot(W, H, "Întârzierea medie pe oră și zi — " + BOARD_PL[b],
                         "Hartă de căldură: 7 zile × 24 de ore; celulele cu eșantion mic sunt gri.");
      for (var dd = 0; dd < 7; dd++) {
        root.append(svg("text", { x: L - 4, y: (T + dd * ch + ch / 2 + 4).toFixed(1), class: "ss-tick ss-tick-y" }, WD_SHORT[dd]));
        for (var hr = 0; hr < 24; hr++) {
          var c = map[dd + "-" + hr];
          var g = svg("g", { class: "ss-mark" });
          g.append(svg("rect", { x: (L + hr * cw + 1).toFixed(1), y: (T + dd * ch + 1).toFixed(1),
                                 width: Math.max(1, cw - 2).toFixed(1), height: Math.max(1, ch - 2).toFixed(1), rx: 2,
                                 class: "ss-cell " + heatClass(c) }));
          tip(g, WEEKDAYS[dd] + ", " + hourRange(hr) + ": " + (c ? "medie " + minutes(c.mean) + ", mediana " +
            minutes(c.median) + ", N = " + c.n + (c.sufficient ? ", la timp " + pct(c.on_time_pct) : " (eșantion mic)") : "nicio călătorie"));
          root.append(g);
        }
      }
      var every = cw < 16 ? 3 : 2;
      for (var x = 0; x < 24; x += every) {
        root.append(svg("text", { x: (L + x * cw + cw / 2).toFixed(1), y: H - 4, class: "ss-tick ss-tick-x" }, hh(x)));
      }
      cell.append(root);
    });
    var rows = [];
    boards.forEach(function (b) {
      (d.heatmap[b] || []).forEach(function (c) {
        rows.push([BOARD_PL[b] + ", " + WEEKDAYS[c.d] + " " + hourRange(c.h), c.n, minutes(c.mean), minutes(c.median), pct(c.on_time_pct)]);
      });
    });
    f.foot.append(nLine("Doar celulele cu cel puțin o călătorie apar în tabel (" + rows.length + ")."));
    f.foot.append(dataTable("Întârzierea pe zi a săptămânii și oră", ["Panou, zi, oră", "N", "Medie", "Mediană", "% la timp"], rows));
  }

  function dailySection(d, boards) {
    var p = d.params;
    var keys = {};
    boards.forEach(function (b) { (d.daily[b] || []).forEach(function (x) { keys[x.key] = true; }); });
    var days = Object.keys(keys).sort();
    var f = figure({ title: "Cum a evoluat punctualitatea de la o zi la alta?", set: "daily",
      legend: legend(boards),
      how: "fiecare punct este procentul călătoriilor la timp (≤ " + p.on_time_max_min + " min) dintr-o zi de serviciu. " +
        "Zilele cu prea puține călătorii (N < " + p.min_sample + ") nu au procent și lipsesc din linie. Banda arată N pe zi." });
    if (days.length < 2) {
      f.foot.append(el("p", "ss-empty", days.length ? "O singură zi cu date — evoluția apare de la a doua zi." :
        "Nicio zi cu date pentru filtrele alese."));
    }
    if (days.length) {
      var byKey = {};
      boards.forEach(function (b) { byKey[b] = {}; (d.daily[b] || []).forEach(function (x) { byKey[b][x.key] = x; }); });
      lines(f.host, { cats: days.map(shortDay), unit: "%", yMax: 100, yStep: 25,
        yFmt: function (t) { return t + "%"; },
        title: "Procentul la timp pe zile", desc: "Procentul călătoriilor la timp pe fiecare zi de serviciu.",
        series: boards.map(function (b) {
          return { board: b, values: days.map(function (k) { var x = byKey[b][k]; return x ? x.on_time_pct : null; }),
            tips: days.map(function (k) { var x = byKey[b][k];
              return BOARD_PL[b] + ", " + S.dayText(k) + ": " + (x ? "la timp " + pct(x.on_time_pct) + ", mediana " + minutes(x.median) + ", N = " + x.n : "nicio călătorie"); }) };
        }) });
      nStrip(f.host, { cats: days.map(shortDay), title: "N pe zi", desc: "Călătorii cu întârziere citită pe zi.",
        series: boards.map(function (b) { return { board: b, values: days.map(function (k) { var x = byKey[b][k]; return x ? x.n : 0; }) }; }) });
      var rows = days.map(function (k) {
        var r = [S.dayText(k)];
        boards.forEach(function (b) { var x = byKey[b][k]; r.push(x ? x.journeys : 0, x ? x.n : 0, x ? pct(x.on_time_pct) : "—", x ? minutes(x.median) : "—"); });
        return r;
      });
      var cols = ["Ziua"];
      boards.forEach(function (b) { var L = BOARD_PL[b]; cols.push(L + " călătorii", L + " N", L + " % la timp", L + " mediană"); });
      f.foot.append(dataTable("Punctualitatea pe zile", cols, rows));
    }
  }

  function rankedSection(d, boards, key, title, how, setName, firstCol) {
    var p = d.params;
    var f = figure({ title: title, set: setName, how: how });
    var cells = multiples(f.host, boards.length);
    var rows = [];
    boards.forEach(function (b, bi) {
      var list = (d[key][b] || []).filter(function (x) { return x.journeys > 0; });
      var cell = cells[bi];
      var h = el("h3", "ss-mult-h");
      h.append(el("span", "ss-key " + BOARD_CLS[b]), document.createTextNode(BOARD_PL[b]));
      cell.append(h);
      if (!list.length) { cell.append(el("p", "ss-empty", "Nicio călătorie.")); return; }
      hbars(cell, { board: b, max: 100, title: title + " — " + BOARD_PL[b],
        desc: "Procentul la timp pe " + firstCol.toLowerCase() + "; rândurile fără bară au eșantion mic.",
        rows: list.map(function (x) {
          return { label: x.key, value: x.sufficient ? x.on_time_pct : null, low: !x.sufficient,
            valueText: x.sufficient ? pct(x.on_time_pct) + " · N = " + x.n : (x.n ? "N = " + x.n + " < " + p.min_sample : "N = 0"),
            tip: x.sufficient ? pct(x.on_time_pct) + " la timp, mediana " + minutes(x.median) + ", N = " + x.n
              : "N = " + x.n + " (prea puține pentru procent), medie " + minutes(x.mean) };
        }) });
      list.forEach(function (x) { rows.push([BOARD_PL[b] + " — " + x.key, x.journeys, x.n, pct(x.on_time_pct), minutes(x.median), minutes(x.mean)]); });
    });
    f.foot.append(nLine("Bară = % la timp (≤ " + p.on_time_max_min + " min), doar cu N ≥ " + p.min_sample +
      ". Fără bară = eșantion mic, cu cifrele brute în tabel."));
    f.foot.append(dataTable(title, [firstCol, "Călătorii", "N", "% la timp", "Mediană", "Medie"], rows));
  }

  function routesSection(d, boards) {
    var p = d.params;
    var f = figure({ title: "Ce rute întârzie cel mai mult — și care sunt cele mai punctuale?", set: "routes",
      how: "stația este originea trenului (la sosiri) sau destinația lui (la plecări), cum apare pe tabelă. " +
        "Întârzierea e tot cea citită la București Nord, nu la stație. Intră doar stațiile cu cel puțin " +
        p.min_sample + " călătorii cu întârziere citită. Apasă pe o stație pentru pagina ei." });
    var cells = multiples(f.host, boards.length);
    var rows = [];
    boards.forEach(function (b, bi) {
      var r = d.routes[b];
      var cell = cells[bi];
      var h = el("h3", "ss-mult-h");
      h.append(el("span", "ss-key " + BOARD_CLS[b]), document.createTextNode(BOARD_PL[b] + (b === "arrival" ? " — din" : " — spre")));
      cell.append(h);
      if (!r.eligible) {
        cell.append(el("p", "ss-empty", "Nicio stație cu N ≥ " + p.min_sample + " încă (" +
          plural(r.below_min || 0, "stație are", "stații au") + " date sub prag)."));
        return;
      }
      [["Cele mai întârziate (medie)", r.most_delayed, "mean"], ["Cele mai punctuale (% la timp)", r.most_punctual, "pct"]].forEach(function (L) {
        cell.append(el("h4", "ss-rank-h", L[0]));
        var ol = el("ol", "ss-rank");
        L[1].forEach(function (x) {
          var li = el("li");
          li.append(S.stationLink(x.key));
          li.append(el("span", "ss-rank-v", L[2] === "mean" ? minutes(x.mean) + " medie" : pct(x.on_time_pct) + " la timp"));
          li.append(el("span", "ss-rank-n", "N = " + x.n));
          ol.append(li);
          rows.push([BOARD_PL[b] + " — " + S.titleCase(x.key), L[0], x.n, minutes(x.mean), minutes(x.median), pct(x.on_time_pct)]);
        });
        cell.append(ol);
      });
      if (r.below_min) cell.append(nLine(plural(r.below_min, "stație", "stații") + " sub prag nu sunt clasate."));
    });
    var more = el("a", "st-back", "Clasamentul complet al trenurilor și stațiilor →");
    more.href = "#clasamente";
    f.foot.append(more);
    f.foot.append(dataTable("Rute: cele mai întârziate și cele mai punctuale", ["Stație", "Listă", "N", "Medie", "Mediană", "% la timp"], rows));
  }

  function trafficSection(d, boards) {
    var t = d.traffic || {};
    var days = t.days || 0;
    var cats = [];
    for (var h = 0; h < 24; h++) cats.push(hh(h));
    var f = figure({ title: "Când e gara cea mai aglomerată?", set: "traffic", wide: true, legend: legend(boards),
      how: "câte călătorii sunt programate în fiecare oră, în medie pe o zi cu date (" + plural(days, "zi", "zile") +
        "). Se numără toate călătoriile observate, cu sau fără întârziere citită." });
    if (!days) { f.foot.append(el("p", "ss-empty", "Nicio călătorie pentru filtrele alese.")); return; }
    columns(f.host, { cats: cats, unit: "pe zi", title: "Călătorii programate pe oră (medie pe zi)",
      desc: "Coloane grupate: sosiri și plecări programate pe fiecare oră, medie pe zi.",
      series: boards.map(function (b) {
        return { board: b, values: t[b].map(function (x) { return x / days; }),
          tips: t[b].map(function (x, i) { return BOARD_PL[b] + ", " + hourRange(i) + ": " + x + " călătorii în " +
            plural(days, "zi", "zile") + " (≈ " + nf.format(x / days) + " pe zi)"; }) };
      }) });
    var tot = boards.map(function (b) { return BOARD_PL[b] + ": " + t[b].reduce(function (a, x) { return a + x; }, 0); });
    f.foot.append(nLine("Total călătorii observate — " + tot.join(" · ") + " (în " + plural(days, "zi", "zile") + " cu date)."));
    var rows = [];
    for (var i = 0; i < 24; i++) {
      var r = [hourRange(i)];
      boards.forEach(function (b) { r.push(t[b][i], nf.format(t[b][i] / days)); });
      rows.push(r);
    }
    var cols = ["Ora programată"];
    boards.forEach(function (b) { cols.push(BOARD_PL[b] + " (total)", BOARD_PL[b] + " (pe zi)"); });
    f.foot.append(dataTable("Călătorii programate pe oră", cols, rows));
  }

  function platformsSection(d, boards) {
    var pl = d.platforms || {};
    var maxLine = 0;
    boards.forEach(function (b) { (pl[b].lines || []).forEach(function (x) { if (x.line > maxLine) maxLine = x.line; }); });
    var f = figure({ title: "Ce linii (peroane) se folosesc cel mai des?", set: "platforms", wide: true, legend: legend(boards),
      how: "câte călătorii au avut fiecare linie, după ultima linie citită pe tabelă. Călătoriile fără linie citită " +
        "sunt numărate separat („linie necitită”), nu ca linia 0." });
    if (!maxLine) { f.foot.append(el("p", "ss-empty", "Nicio linie citită pentru filtrele alese.")); }
    else {
      var cats = [];
      for (var i = 1; i <= maxLine; i++) cats.push(String(i));
      var by = {};
      boards.forEach(function (b) { by[b] = {}; pl[b].lines.forEach(function (x) { by[b][x.line] = x.n; }); });
      columns(f.host, { cats: cats, unit: "călătorii", title: "Călătorii pe linie",
        desc: "Coloane grupate: câte sosiri și plecări au folosit fiecare linie.",
        series: boards.map(function (b) {
          return { board: b, values: cats.map(function (c) { return by[b][c] || 0; }),
            tips: cats.map(function (c) { return BOARD_PL[b] + ", linia " + c + ": " + (by[b][c] || 0) + " călătorii"; }) };
        }) });
      var rows = cats.map(function (c) { var r = ["Linia " + c]; boards.forEach(function (b) { r.push(by[b][c] || 0); }); return r; });
      var miss = ["Linie necitită"];
      boards.forEach(function (b) { miss.push(pl[b].missing); });
      rows.push(miss);
      f.foot.append(dataTable("Călătorii pe linie", ["Linia"].concat(boards.map(function (b) { return BOARD_PL[b]; })), rows));
    }
    f.foot.append(nLine(boards.map(function (b) { return BOARD_PL[b] + ": " + pl[b].missing + " cu linie necitită"; }).join(" · ")));
  }

  function weatherSection(d) {
    var w = d.weather || {};
    var p = d.params;
    var f = figure({ title: "Vremea și întârzierile", set: w.status === "ok" ? "weather" : null,
      how: "compară întârzierea citită în grupe după vremea (model Open-Meteo, ±30 min față de ora programată). " +
        "Arată doar o asociere." });
    var note = warn(w.note || "Corelație, nu cauzalitate.");
    note.classList.add("ss-weather-note");
    note.setAttribute("role", "note");
    f.foot.append(note);
    if (w.status !== "ok") {
      var box = el("div", "ss-collect");
      box.append(el("p", "ss-collect-h", "Analiza meteo este în curs de adunare."));
      box.append(el("p", null, plural(w.matched || 0, "călătorie are", "călătorii au") + " deja vremea asociată, în " +
        plural(w.days || 0, "zi", "zile") + " (" + plural(w.observations || 0, "observație meteo", "observații meteo") +
        "). Graficele apar după cel puțin " + (w.needed_days || 7) + " zile și minimum două grupe cu N ≥ " + p.min_sample +
        " — altfel diferențele ar ține mai mult de ora din zi decât de vreme."));
      f.host.append(box);
      return;
    }
    var rows = [];
    var dims = [["precip", "Precipitații"], ["temp", "Temperatură"]].filter(function (dim) {
      return w.groups && w.groups[dim[0]] && w.groups[dim[0]].length;
    });
    var cells = multiples(f.host, dims.length);
    dims.forEach(function (dim, di) {
      var gs = w.groups[dim[0]];
      var cell = cells[di];
      cell.append(el("h3", "ss-mult-h", dim[1]));
      var mx = Math.max.apply(null, gs.map(function (g) { return g.mean || 0; }).concat([1]));
      hbars(cell, { board: "arrival", max: mx, title: "Întârzierea medie după " + dim[1].toLowerCase(),
        desc: "Întârzierea medie citită pe grupe meteo.",
        rows: gs.map(function (g) {
          return { label: g.label, value: g.sufficient ? g.mean : null, low: !g.sufficient, cls: "ss-neutral",
            valueText: (g.sufficient ? minutes(g.mean) + " · " : "") + "N = " + g.n,
            tip: "medie " + minutes(g.mean) + ", mediana " + minutes(g.median) + ", N = " + g.n };
        }) });
      gs.forEach(function (g) { rows.push([dim[1] + ": " + g.label, g.n, minutes(g.mean), minutes(g.median), pct(g.on_time_pct)]); });
    });
    f.foot.append(nLine("Ambele panouri împreună (vremea e aceeași la sosiri și plecări); " +
      plural(w.matched || 0, "călătorie", "călătorii") + " în " + plural(w.days || 0, "zi", "zile") + "."));
    f.foot.append(dataTable("Întârzierea după vreme", ["Grupa", "N", "Medie", "Mediană", "% la timp"], rows));
  }

  function qualitySection(d) {
    var q = d.quality || {};
    var st = q.states || {};
    var obs = q.observations || {};
    var ex = q.excluded || {};
    var f = figure({ title: "Cât de bune sunt datele?", wide: true,
      how: "câte călătorii au un rezultat sigur și cât de reușite au fost citirile automate (OCR) ale tabelei. " +
        "Doar călătoriile încheiate cu întârzierea citită intră în statistici; „necunoscut” nu înseamnă 0." });
    var cells = multiples(f.host, 2);
    var nb = 0;
    function block(title, items, total) {
      var cell = cells[nb++];
      cell.append(el("h3", "ss-mult-h", title));
      if (!total) { cell.append(el("p", "ss-empty", "Nimic de numărat.")); return; }
      hbars(cell, { board: "arrival", max: total, title: title, desc: title + ": numărători și procente din total.",
        rows: items.map(function (x) {
          return { label: x[0], value: x[1], cls: "ss-neutral",
            valueText: nf.format(x[1]) + " (" + nf.format(Math.round(1000 * x[1] / total) / 10) + " %)",
            tip: x[1] + " din " + total };
        }) });
      cell.append(nLine("Total: " + nf.format(total)));
    }
    var jt = (st.confirmed || 0) + (st.unconfirmed || 0) + (st.unknown || 0) + (st.in_progress || 0);
    block("Călătorii (rezultat)", ["confirmed", "unconfirmed", "unknown", "in_progress"].map(function (k) {
      return [STATE_TEXT[k], st[k] || 0]; }), jt);
    var ot = 0;
    Object.keys(obs).forEach(function (k) { ot += obs[k] || 0; });
    block("Citiri OCR (observații)", ["ok", "uncertain", "rejected_low_conf", "incomplete"].map(function (k) {
      return [OBS_TEXT[k], obs[k] || 0]; }), ot);
    f.foot.append(nLine("Excluse din toate statisticile: " + plural(ex.ghost || 0, "fantomă", "fantome") +
      " (rânduri citite greșit, fără tren real) și " + (ex.low_quality || 0) +
      " călătorii din perioada de calitate redusă (21.10, 00:00–11:31). " +
      (q.uncertain_names || 0) + " călătorii au numele stației sau al operatorului citit nesigur."));
    f.foot.append(dataTable("Calitatea datelor", ["Categoria", "Număr"],
      ["confirmed", "unconfirmed", "unknown", "in_progress"].map(function (k) { return ["Călătorii — " + STATE_TEXT[k], st[k] || 0]; })
        .concat(["ok", "uncertain", "rejected_low_conf", "incomplete"].map(function (k) { return ["Observații — " + OBS_TEXT[k], obs[k] || 0]; }))
        .concat([["Excluse — fantome", ex.ghost || 0], ["Excluse — calitate redusă", ex.low_quality || 0]])));
  }

  function glossary(d) {
    var p = d.params || {};
    var sec = el("section", "ss-glossary");
    sec.setAttribute("aria-labelledby", "ss-glos-h");
    var h = el("h2", "ss-fig-title", "Glosar");
    h.id = "ss-glos-h";
    sec.append(h);
    var dl = el("dl", "ss-gl");
    [["Întârziere citită", "Întârzierea afișată pe tabela CFR din București Nord, citită automat (OCR). Nu este ora reală de sosire sau plecare și nici întârzierea din alte stații."],
     ["La timp", "Întârziere citită de cel mult " + p.on_time_max_min + " minute."],
     ["Călătorie", "O apariție a unui tren pe un panou (sosiri sau plecări) într-o zi de serviciu. Un tren (număr) are de obicei câte o călătorie pe zi."],
     ["Tren · călătorie · observație", "Tren = numărul trenului; călătorie = trenul într-o anumită zi; observație = o citire a tabelei (la fiecare câteva zeci de secunde), deci o călătorie are multe observații."],
     ["Rezultat confirmat", "Trenul a dispărut de pe tabelă după ora estimată (programat + întârziere), iar întârzierea fusese citită cu cel mult " +
       (p.final_read_max_gap_min || 15) + " min înainte."],
     ["Rezultat neconfirmat", "Avem o întârziere citită, dar dispariția n-a fost observată la momentul potrivit (de ex. citirea tabelei a fost întreruptă). Intră în statistici, dacă nu bifezi „Doar rezultate confirmate”."],
     ["Necunoscut", "Întârzierea nu a fost citită niciodată. Nu este tratată ca 0 și nu intră în statistici."],
     ["N", "Numărul de călătorii încheiate cu întârziere citită din spatele unei cifre."],
     ["Eșantion mic", "Sub " + p.min_sample + " călătorii: arătăm doar cifrele brute (medie, mediană, maxim), fără procente."],
     ["Mediană · p90", "Mediana: jumătate dintre călătorii au întârziat mai puțin. p90: 90% au întârziat cel mult atât."],
     ["Fantomă", "Un rând citit greșit de OCR care n-a corespuns unui tren real; exclus din tot."]].forEach(function (x) {
      dl.append(el("dt", null, x[0]), el("dd", null, x[1]));
    });
    sec.append(dl);
    v.ui.body.append(sec);
  }

  function render(d) {
    seq = 0;
    v.ui.body.replaceChildren();
    v.ui.body.classList.toggle("ss-no-motion", !!reduceMotion);
    var boards = boardsOf(d);
    summary(d);
    if (!d.coverage || !d.coverage.journeys) {
      v.ui.body.append(el("p", "empty ss-empty", "Nu există încă date pentru filtrele alese. Încearcă „Tot istoricul” sau alt operator."));
      glossary(d);
      return;
    }
    kpis(d, boards);
    distributionSection(d, boards);
    dailySection(d, boards);
    hourlySection(d, boards);
    heatmapSection(d, boards);
    rankedSection(d, boards, "operators", "Care operatori sunt cei mai punctuali?",
      "fiecare rând este un operator, cum apare scris pe tabelă; bara arată ce procent din călătoriile lui au fost " +
      "la timp. Operatorii cu prea puține călătorii apar fără bară, doar cu N.", "operators", "Operator");
    rankedSection(d, boards, "types", "Ce tipuri de tren sunt mai punctuale?",
      "R = Regio, RM = Regio Metropolitan, RE = Regio Expres, IR = InterRegio, IRN = InterRegio de noapte, " +
      "IC = InterCity (tipul afișat pe " +
      "tabelă). Bara = procentul la timp; fără bară = eșantion mic.", "types", "Tip de tren");
    routesSection(d, boards);
    weatherSection(d);
    trafficSection(d, boards);
    platformsSection(d, boards);
    qualitySection(d);
    glossary(d);
  }

  App.views.statistici = { show: show };
})();
