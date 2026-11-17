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
  var U = function () { return App.ui2; };   // Beta 1.26 visual helpers (ui2.js): donut, count-up, meter, spark
  var C3 = function () { return App.charts3; };   // Beta 1.28 interactive chart layer (charts3.js, lazy): tooltips, curves, calendar…
  var SVG_NS = "http://www.w3.org/2000/svg";
  var API = "/api/stats/overview";
  var BOARDS = ["arrival", "departure"];
  // THE color scale (Statistici v3 sp2): thresholds in one place, colors in statistici.css (--ss-good/mid/bad).
  // pct = % on time (>= good green, >= mid yellow, else red); minutes = typical delay (<= good green, <= mid yellow, else red).
  var SCALE = { pct: { good: 80, mid: 60 }, minutes: { good: 5, mid: 10 } };
  function tone(kind, val) {
    if (val == null || isNaN(val)) return "";
    var s = SCALE[kind];
    var good = kind === "pct" ? val >= s.good : val <= s.good;
    var mid = kind === "pct" ? val >= s.mid : val <= s.mid;
    return good ? "ss-t-good" : mid ? "ss-t-mid" : "ss-t-bad";
  }
  var tt = function (k, p) { return window.I18N.t(k, p); };
  var pl = function (n, base) { return S.pl(n, base); };   // "1 journey" / "3 journeys" from stats.w.*.one / .many
  function lazy(prefix, keys) {   // getters: the text follows the language chosen at the time it is read
    var o = {};
    keys.forEach(function (k) { Object.defineProperty(o, k, { enumerable: true, get: function () { return tt(prefix + k); } }); });
    return o;
  }
  var BOARD_PL = lazy("stats.board.", ["arrival", "departure"]);
  var BOARD_CLS = { arrival: "ss-arr", departure: "ss-dep" };
  function wd(i) { return tt("stats.wd." + i); }
  function wdShort(i) { return tt("stats.wds." + i); }
  function periods() { return ["all", "30", "7", "1"].map(function (k) { return [k, tt("stats.period." + k)]; }); }
  function boardOpts() { return [["", tt("stats.board.both")], ["arrival", tt("stats.board.arrival")], ["departure", tt("stats.board.departure")]]; }
  var FIELDS = ["perioada", "board", "operator", "tip", "doar_confirmate"];
  var STATE_TEXT = lazy("stats.state.", ["confirmed", "unconfirmed", "unknown", "in_progress"]);
  var OBS_TEXT = lazy("stats.obs.", ["ok", "uncertain", "rejected_low_conf", "incomplete"]);
  var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var $ = function (id) { return document.getElementById(id); };
  var nf = S.numFmt;
  var seq = 0;

  function num(v) { return v == null ? "—" : nf.format(v); }
  function minutes(v) { return v == null ? "—" : tt("stats.fmt.min", { v: nf.format(v) }); }
  function pct(v) { return v == null ? "—" : tt("stats.fmt.pct", { v: nf.format(v) }); }
  function hh(h) { return (h < 10 ? "0" : "") + h; }
  function hourRange(h) { return hh(h) + ":00–" + hh(h) + ":59"; }
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

  function slug(t) {
    return String(t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase()
      .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 34);
  }
  function chartUrl(key) {
    var q = query(v.p, { grafic: key });
    return location.origin + location.pathname + "#statistici?" + q;
  }

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

  // ?sect= names (not a filter: not in FIELDS)
  var SECTS = { sumar: ".ss-summary", probleme: ".ss-problems", bune: ".ss-good", glosar: ".ss-glossary",
    rute: '[data-key="ce-rute-intarzie-cel-mai-mult-si-c"]', operatori: '[data-key="care-operatori-sunt-cei-mai-punctu"]' };
  function cleanSect(raw) {
    var k = raw == null ? "" : String(raw).trim();
    return Object.prototype.hasOwnProperty.call(SECTS, k) ? k : "";
  }
  function sectQuery(sect) { return query(v.p, { sect: sect }); }

  function syncHash(p) {
    var q = v.sect ? sectQuery(v.sect) : query(p);
    var hash = "#statistici" + (q ? "?" + q : "");
    if (location.hash !== hash) history.replaceState(null, "", hash);
  }

  // ---- saved presets: list + menu in stat_presets.js (lazy) ----

  // only fields that still exist with a valid value (deleted operator, unknown key: dropped)
  function presetsApply(filters) {
    var opts = (v.data && v.data.options) || {};
    function known(list, val) { return (list || []).some(function (o) { return o.name === val; }); }
    var p = { perioada: "all", board: "", operator: "", tip: "", doar_confirmate: "" };
    FIELDS.forEach(function (f) {
      var val = clean(f, filters[f]);
      if (f === "operator" && v.data && !known(opts.operators, val)) val = "";  // before data: keep, validated on load
      if (f === "tip" && v.data && !known(opts.types, val)) val = "";
      p[f] = val;
    });
    v.p = p;
    setForm(p);
    syncHash(p);
    load();
  }

  var presetsP = null;
  function presetsLayer() {
    if (App.statPresets) return Promise.resolve();
    if (!presetsP) presetsP = new Promise(function (resolve) {
      var sc = document.createElement("script");
      sc.src = "stat_presets.js?v=2";
      sc.onload = resolve;
      sc.onerror = function () { presetsP = null; resolve(); };
      document.head.append(sc);
    });
    return presetsP;
  }

  function presetsMenu() {
    var box = el("div", "ss-presets");
    var tog = el("button", "btn btn-ghost btn-sm ss-presets-toggle", tt("stats.preset.button"));
    tog.type = "button";
    tog.setAttribute("aria-expanded", "false");
    var menu = el("div", "ss-presets-menu");
    menu.hidden = true;
    menu.addEventListener("change", function (e) { e.stopPropagation(); });   // the name field is not a filter
    box.append(tog, menu);
    var msg = el("p", "ss-preset-msg");
    msg.setAttribute("role", "status");
    function close() { menu.hidden = true; tog.setAttribute("aria-expanded", "false"); }
    tog.addEventListener("click", function () {
      if (!menu.hidden) { close(); return; }
      menu.hidden = false;
      tog.setAttribute("aria-expanded", "true");
      msg.textContent = "";
      presetsLayer().then(function () {
        if (App.statPresets) {
          App.statPresets.fill(menu, msg, { el: el, tt: tt, close: close, apply: presetsApply,
            current: function () { return Object.assign({}, v.p); } });
        } else {   // the layer could not be loaded: same message as a blocked localStorage
          msg.textContent = tt("stats.preset.unavailable");
          menu.replaceChildren(msg);
        }
      });
    });
    return box;
  }

  // ---- shell: filters + body ---------------------------------------------------------

  var v = { sect: "", sectPending: false, p: null, data: null, key: null, ctrl: null, ui: null, width: 0, at: 0 };

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
    form.setAttribute("aria-label", tt("stats.filters.aria"));
    form.noValidate = true;
    var per = segmented("perioada", tt("stats.filters.period"), periods());
    var brd = segmented("board", tt("stats.filters.board"), boardOpts());
    var op = selectField("operator", tt("stats.filters.operator"), tt("stats.filters.all_operators"));
    var tp = selectField("tip", tt("stats.filters.train_type"), tt("stats.filters.all_types"));
    var chk = el("label", "ss-check");
    var ci = el("input");
    ci.type = "checkbox";
    ci.id = "ss-confirmate";
    chk.append(ci, el("span", null, tt("stats.filters.confirmed_only")));
    var rs = el("button", "btn btn-ghost btn-sm ss-reset", tt("stats.reset"));
    rs.type = "button";
    rs.hidden = true;
    rs.addEventListener("click", function () { resetFilters(); });
    // < 600 px: fields collapse behind „Filtre (n)”
    var fields = el("div", "ss-fields");
    fields.append(per.node, brd.node, op.node, tp.node, chk);
    var ft = el("button", "btn btn-ghost btn-sm ss-filters-toggle", "");
    ft.type = "button";
    ft.setAttribute("aria-expanded", "false");
    ft.hidden = true;
    form.append(ft, fields, rs, presetsMenu());
    var mq = window.matchMedia ? window.matchMedia("(max-width: 599px)") : null;
    var panelOpen = false;
    function applyPanel() {
      var small = !!(mq && mq.matches);
      ft.hidden = !small;
      fields.hidden = small && !panelOpen;
      ft.setAttribute("aria-expanded", panelOpen ? "true" : "false");
      form.classList.toggle("ss-panel-open", small && panelOpen);
      syncFiltersH();
    }
    ft.addEventListener("click", function () { panelOpen = !panelOpen; applyPanel(); });
    if (mq) {
      if (mq.addEventListener) mq.addEventListener("change", applyPanel);
      else if (mq.addListener) mq.addListener(applyPanel);
    }
    function read() {
      return { perioada: per.get() || "all", board: brd.get(), operator: op.input.value,
               tip: tp.input.value, doar_confirmate: ci.checked ? "1" : "" };
    }
    form.addEventListener("change", function () {
      v.p = read();
      syncHash(v.p);
      syncReset();
      load();
    });
    form.addEventListener("submit", function (e) { e.preventDefault(); });
    var body = el("div", "ss-body");
    var quick = el("div", "ss-quick-host");
    root.replaceChildren(form, quick, body);
    v.ui = { form: form, quick: quick, body: body, reset: rs, toggle: ft, fields: fields, applyPanel: applyPanel, per: per, brd: brd, op: op, tp: tp, ci: ci };
    window.addEventListener("resize", debounce(function () {
      if (!v.data || $("view-statistici").hidden) return;
      syncFiltersH();
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
    syncReset();
  }

  // „Resetează filtrele” shows only while a filter differs from its default
  function isDefault(p) {
    return !p || (p.perioada === "all" && !p.board && !p.operator && !p.tip && !p.doar_confirmate);
  }
  function activeCount(p) {
    if (!p) return 0;
    return (p.perioada && p.perioada !== "all" ? 1 : 0) + (p.board ? 1 : 0) + (p.operator ? 1 : 0) + (p.tip ? 1 : 0) + (p.doar_confirmate ? 1 : 0);
  }
  function syncReset() {
    if (v.ui && v.ui.reset) v.ui.reset.hidden = isDefault(v.p);
    if (v.ui && v.ui.toggle) {
      v.ui.toggle.textContent = tt("stats.mobile.filters", { n: activeCount(v.p) });
      v.ui.applyPanel();
    }
    syncFiltersH();
  }
  // the charts3 chips stick under the filters
  function syncFiltersH() {
    if (!v.ui) return;
    var h = v.ui.form.offsetHeight;
    var cssom = document.documentElement.style;   // CSSOM property, CSP-safe (as charts3.js)
    cssom.setProperty("--ss-filters-h", (h ? h + 10 : 0) + "px");
  }

  // lazy "steps" layer (stat_steps.js): own file, not in the SW shell (precache budget); resolves even if it fails
  var stepsP = null;
  function stepsLayer() {
    if (App.statSteps) return Promise.resolve();
    if (!stepsP) stepsP = new Promise(function (resolve) {
      var sc = document.createElement("script");
      sc.src = "stat_steps.js?v=1";
      sc.onload = resolve;
      sc.onerror = function () { stepsP = null; resolve(); };
      document.head.append(sc);
    });
    return stepsP;
  }

  function load() {
    var q = query(v.p);
    var url = API + (q ? "?" + q : "");
    var ttl = ((v.data && v.data.cache_ttl_s) || 60) * 1000;
    if (url === v.key && v.data && Date.now() - v.at < ttl) return;
    v.key = url;
    if (v.ctrl) v.ctrl.abort();
    var ctrl = new AbortController();
    v.ctrl = ctrl;
    var root = $("st-statistici");
    root.classList.add("is-loading");
    root.setAttribute("aria-busy", "true");
    if (!v.data) {
      var wait = el("p", "sr-only", tt("stats.loading"));
      v.ui.body.replaceChildren(wait);
      if (U()) v.ui.body.append(U().skeleton("hero", 4), U().skeleton("chart", 2), U().skeleton("cards", 1));
    }
    var chartsReady = U() && U().charts ? U().charts() : Promise.resolve(null);
    chartsReady = chartsReady.then(function (c) { return stepsLayer().then(function () { return c; }); });
    S.getJSON(url, ctrl)
      .then(function (d) { return chartsReady.then(function () { return d; }); })
      .then(function (d) {
        if (v.ctrl !== ctrl) return;
        var snap = v.data && C3() ? C3().snapshot(v.ui.body) : null;   // old chart geometry, to ease into the new data
        v.data = d;
        v.at = Date.now();
        setForm(v.p);
        render(d);
        if (snap && C3()) C3().morph(v.ui.body, snap);
        focusChart();
        applySect();
      })
      .catch(function (e) {
        if (v.ctrl !== ctrl || e.aborted) return;
        v.data = null;
        v.key = null;
        v.ui.quick.replaceChildren();
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

  function focusChart() {
    if (v.focus && C3()) C3().focusKey(v.ui.body, v.focus);
    v.focus = null;
  }

  // ?sect=: scroll + highlight 2 s; unknown name ignored
  function applySect() {
    if (!v.sectPending || !v.data || !v.ui) return;
    v.sectPending = false;
    if (!v.sect) return;
    var node = v.ui.body.querySelector(SECTS[v.sect]);
    if (!node) return;
    node.classList.add("ss-target");
    node.scrollIntoView({ block: "start" });
    setTimeout(function () { node.classList.remove("ss-target"); }, 2000);
  }

  function show(params) {
    window.I18N.ready.then(function () {   // the dictionary must be loaded before the first labels are drawn
      ensure();
      v.focus = params && params.get ? (params.get("grafic") || "").slice(0, 40) : "";
      v.p = readParams(params);
      v.sect = cleanSect(params && params.get ? params.get("sect") : "");
      v.sectPending = !!v.sect;
      setForm(v.p);
      load();
      if (v.data && !v.ctrl) { focusChart(); applySect(); }
    });
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
    sec.setAttribute("data-key", o.key || slug(o.title));
    var head = el("div", "ss-fig-head");
    var h = el("h2", "ss-fig-title", o.title);
    h.id = hid;
    head.append(h);
    if (o.set) head.append(csvLink(o.set));
    sec.append(head);
    if (o.how) {
      var how = el("p", "ss-how");
      how.append(el("strong", null, tt("stats.how_label")), document.createTextNode(o.how));
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
    det.append(el("summary", null, tt("stats.view_data")));
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

  // chart builder that can draw itself again with other options (full-screen dialog: wider and taller)
  function again(fn, o) { return function (h2, x) { return fn(h2, Object.assign({}, o, x)); }; }

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
    return svg("path", { d: d, class: "ss-bar ss-vb " + cls });
  }

  function hbar(x, y, w, h, cls) {
    if (w <= 0) return null;
    var r = Math.min(4, h / 2, w);
    var d = "M" + x + "," + y + "H" + (x + w - r) + "Q" + (x + w) + "," + y + " " + (x + w) + "," + (y + r) +
      "V" + (y + h - r) + "Q" + (x + w) + "," + (y + h) + " " + (x + w - r) + "," + (y + h) + "H" + x + "Z";
    return svg("path", { d: d, class: "ss-bar ss-hb " + cls });
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
    var c3 = C3();
    var W = o.width || chartWidth(host);
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
    root.setAttribute("data-kind", "col");
    root.setAttribute("data-plot", [L, T, W - R, H - B].join(","));
    root.setAttribute("data-n", n);
    yGrid(root, L, R, W, y, ys, o.yFmt || function (t) { return nf.format(t); });
    if (o.unit) root.append(svg("text", { x: 4, y: 10, class: "ss-tick ss-unit" }, o.unit));
    if (c3 && o.refs) {
      o.refs.forEach(function (r) {
        if (r.value != null && r.value >= 0 && r.value <= ys.max) c3.refLine(root, { y: y(r.value), x1: L, x2: W - R, label: r.label, cls: r.cls, side: r.side });
      });
    }
    var every = Math.ceil(28 / band);
    var top = null;    // the highest bar: annotated when its own value label is not drawn
    o.cats.forEach(function (c, i) {
      var cx = L + band * i + band / 2;
      var group = k * bw + (k - 1) * 2;
      o.series.forEach(function (s, j) {
        var val = s.values[i];
        var x = cx - group / 2 + j * (bw + 2);
        var g = svg("g", { class: "ss-mark", "data-i": i, "data-s": j, "data-b": BOARD_CLS[s.board] });
        if (val != null && val > 0) {
          var b = vbar(x, y(val), bw, (H - B) - y(val), BOARD_CLS[s.board] + (s.low && s.low[i] ? " ss-low" : ""));
          if (b) { b.setAttribute("data-m", j + ":" + i); g.append(b); }
          var drawn = s.labels && s.labels[i] != null && band / k >= 22;
          if (drawn) {
            g.append(svg("text", { x: (x + bw / 2).toFixed(1), y: (y(val) - 4).toFixed(1), class: "ss-vlabel" }, s.labels[i]));
          } else if (!top || val > top.v) {
            top = { v: val, x: x + bw / 2, y: y(val), s: s, i: i };
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
    if (c3 && top && n > 3 && all.length > 2) c3.colMax(root, top, { L: L, W: W, R: R, label: top.s.labels && top.s.labels[top.i] != null ? top.s.labels[top.i] : nf.format(top.v), cls: BOARD_CLS[top.s.board] });
    root.__build = again(columns, o);
    host.append(root);
    return root;
  }

  // Lines over 24 hours / days: series = [{board, values:[n|null], low:[bool], tips:[...]}];
  // a line joins consecutive sufficient points only; small samples = hollow markers; with charts3.js: curves, area, extremes, o.refs
  function lines(host, o) {
    var c3 = C3();
    var W = o.width || chartWidth(host);
    var H = o.height || 220;
    var L = 40, R = 12, T = 24, B = 28;
    var refMargin = !!(c3 && o.refs && o.refs.length && W >= 520);
    if (refMargin) R = o.refR || 68;
    var all = [];
    o.series.forEach(function (s) { s.values.forEach(function (x) { if (x != null) all.push(x); }); });
    var ys = o.yMax ? { max: o.yMax, step: o.yStep || o.yMax / 4 } : niceMax(Math.max.apply(null, all.concat([1])));
    var n = o.cats.length;
    var band = (W - L - R) / Math.max(1, n);
    var x = function (i) { return L + band * i + band / 2; };
    var y = function (val) { return T + (1 - val / ys.max) * (H - T - B); };
    var root = svgRoot(W, H, o.title, o.desc);
    root.setAttribute("data-kind", "line");
    root.setAttribute("data-plot", [L, T, W - R, H - B].join(","));
    root.setAttribute("data-n", n);
    yGrid(root, L, R, W, y, ys, o.yFmt || function (t) { return nf.format(t); });
    if (o.unit) root.append(svg("text", { x: 4, y: 10, class: "ss-tick ss-unit" }, o.unit));
    var every = Math.ceil(30 / band);
    o.cats.forEach(function (c, i) {
      if (i % every === 0) root.append(svg("text", { x: x(i).toFixed(1), y: H - B + 16, class: "ss-tick ss-tick-x" }, c));
    });
    root.append(svg("line", { x1: L, x2: W - R, y1: H - B, y2: H - B, class: "ss-axis" }));
    if (c3 && o.refs) c3.lineRefs(root, o.refs, { y: y, x: x, L: L, T: T, W: W, R: R, margin: refMargin, series: o.series });
    var taken = [];
    o.series.forEach(function (s, si) {
      var runs = [], cur = null, pts = [];
      s.values.forEach(function (val, i) {
        var ok = val != null && !(s.low && s.low[i]);
        if (ok) {
          var pt = [x(i), y(val)];
          if (!cur) { cur = []; runs.push(cur); }
          cur.push(pt);
          pts.push({ x: pt[0], y: pt[1], v: val });
        } else cur = null;
      });
      var d = runs.map(function (r) {
        if (c3) return c3.smooth(r);
        return r.map(function (p, q) { return (q ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1); }).join("");
      }).join("");
      if (c3) {
        var ad = runs.filter(function (r) { return r.length > 2; }).map(function (r) { return c3.areaPath(c3.smooth(r), r, y(0).toFixed(1)); }).join("");
        if (ad) root.append(svg("path", { d: ad, class: "c3-area " + BOARD_CLS[s.board], "data-m": "a" + si }));
      }
      if (d) root.append(svg("path", { d: d, pathLength: 1, class: "ss-line " + BOARD_CLS[s.board], "data-m": "l" + si }));
      if (c3 && pts.length > 2 && o.extremes !== false) {
        c3.extremes(root, pts, o.extFmt || function (q) { return nf.format(q) + (o.unit === "%" ? "%" : ""); },
                    { taken: taken, top: T - 4, bottom: H - B - 6, right: W - R, cls: BOARD_CLS[s.board] });
      }
    });
    o.series.forEach(function (s, si) {
      s.values.forEach(function (val, i) {
        if (val == null) return;
        var g = svg("g", { class: "ss-mark", "data-i": i, "data-s": si, "data-b": BOARD_CLS[s.board] });
        g.append(svg("circle", { cx: x(i).toFixed(1), cy: y(val).toFixed(1), r: 4, "data-m": "d" + si + ":" + i,
                                 class: "ss-dot " + BOARD_CLS[s.board] + (s.low && s.low[i] ? " ss-dot-low" : "") }));
        g.append(svg("circle", { cx: x(i).toFixed(1), cy: y(val).toFixed(1), r: 12, class: "ss-hit" }));
        tip(g, s.tips[i]);
        root.append(g);
      });
    });
    root.__build = again(lines, o);
    host.append(root);
    return root;
  }

  // N per category, a slim strip under a chart (its own scale, never a second axis).
  function nStrip(host, o) {
    var W = o.width || chartWidth(host);
    var H = 64, L = 40, T = 6, B = 18;
    var R = typeof o.right === "function" ? o.right(W) : 12;   // same right margin as the line chart above it
    var all = [];
    o.series.forEach(function (s) { all = all.concat(s.values); });
    var mx = Math.max.apply(null, all.concat([1]));
    var n = o.cats.length;
    var band = (W - L - R) / Math.max(1, n);
    var k = o.series.length;
    var bw = Math.max(2, Math.min(12, (band * 0.7 - (k - 1)) / k));
    var root = svgRoot(W, H, o.title, o.desc);
    root.setAttribute("data-kind", "col");
    root.setAttribute("data-plot", [L, T, W - R, H - B].join(","));
    root.setAttribute("data-n", n);
    root.append(svg("text", { x: L - 6, y: T + 9, class: "ss-tick ss-tick-y" }, nf.format(mx)));
    root.append(svg("text", { x: 4, y: H - B + 4, class: "ss-tick ss-nhead" }, "N"));
    o.cats.forEach(function (c, i) {
      var cx = L + band * i + band / 2;
      var group = k * bw + (k - 1);
      o.series.forEach(function (s, j) {
        var val = s.values[i] || 0;
        var h = (val / mx) * (H - T - B);
        var g = svg("g", { class: "ss-mark", "data-i": i, "data-s": j, "data-b": BOARD_CLS[s.board] });
        var b = vbar(cx - group / 2 + j * (bw + 1), H - B - h, bw, h, BOARD_CLS[s.board] + " ss-nbar");
        if (b) { b.setAttribute("data-m", "n" + j + ":" + i); g.append(b); }
        g.append(svg("rect", { x: (cx - band / 2).toFixed(1), y: T, width: band.toFixed(1), height: H - T - B, class: "ss-hit" }));
        tip(g, BOARD_PL[s.board] + ", " + c + ": N = " + val);
        root.append(g);
      });
    });
    root.append(svg("line", { x1: L, x2: W - R, y1: H - B, y2: H - B, class: "ss-axis" }));
    root.__build = again(nStrip, o);
    host.append(root);
    return root;
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
        if (b) { b.setAttribute("data-m", String(i)); g.append(b); }
      }
      g.append(svg("text", { x: labW + plotW + 8, y: y0 + 16, class: "ss-hvalue" + (r.low ? " ss-muted" : "") }, r.valueText));
      g.append(svg("rect", { x: 0, y: y0, width: W, height: rowH, class: "ss-hit" }));
      tip(g, r.label + ": " + r.tip);
      root.append(g);
    });
    host.append(root);
    return root;
  }

  // ---- sections ------------------------------------------------------------------------

  function periodText(d) {
    var c = d.coverage || {};
    if (!c.first) return tt("stats.period_none");
    var span = c.first === c.last ? S.dayText(c.first) : S.dayText(c.first) + " – " + S.dayText(c.last);
    return span + " (" + pl(c.days || 0, "stats.w.day_data") + ")";
  }

  // Quick summary (Statistici v3): four cards from the same /api/stats/overview payload. A missing figure is „—”.
  function quickFigures(d) {
    var c = d.coverage || {};
    var p = d.params || {};
    var n = 0, ok = 0, wsum = 0;
    var worst = null;
    BOARDS.forEach(function (b) {
      var s = d.boards && d.boards[b];
      if (s && s.n) {
        n += s.n;
        ok += s.on_time || 0;
        if (s.mean != null) wsum += s.mean * s.n;
      }
      var r = d.routes && d.routes[b];
      var top = r && r.eligible && r.most_delayed && r.most_delayed[0];
      if (top && top.mean != null && (!worst || top.mean > worst.mean)) worst = top;
    });
    var enough = n > 0 && n >= (p.min_sample || 1);
    return { n: n, ok: ok, pct: enough ? Math.round(1000 * ok / n) / 10 : null, mean: n ? Math.round(10 * wsum / n) / 10 : null,
             trains: c.trains == null ? null : c.trains, journeys: c.journeys || 0, route: worst };
  }

  function renderSummary(d) {
    var f = quickFigures(d);
    var sec = el("section", "ss-quick");
    sec.setAttribute("aria-label", tt("stats.sum.aria"));
    function card(title, value, sub, sect, kind, num) {
      var c = el("div", "ss-card");
      var val = el("p", "ss-card-v " + tone(kind, num));
      if (sect) {   // link to the section behind the figure
        var a = el("a", "ss-card-link", value);
        a.href = "#statistici?" + sectQuery(sect);
        a.addEventListener("click", function () { v.sect = sect; v.sectPending = true; applySect(); });
        val.append(a);
      } else val.textContent = value;
      c.append(el("h3", "ss-card-t", title), val, el("p", "ss-card-s", sub));
      sec.append(c);
    }
    card(tt("stats.sum.on_time"), pct(f.pct), f.n ? tt("stats.sum.on_time_sub", { ok: f.ok, n: f.n }) : tt("stats.sum.none"), "probleme", "pct", f.pct);
    card(tt("stats.sum.mean"), minutes(f.mean), f.n ? tt("stats.sum.mean_sub", { n: f.n }) : tt("stats.sum.none"), null, "minutes", f.mean);
    card(tt("stats.sum.trains"), num(f.trains), tt("stats.sum.trains_sub", { n: f.journeys }));
    card(tt("stats.sum.route"), f.route ? S.titleCase(f.route.key) : "—",
      f.route ? tt("stats.sum.route_sub", { mean: minutes(f.route.mean), n: f.route.n }) : tt("stats.sum.none"), f.route ? "rute" : null);
    v.ui.quick.replaceChildren(sec);   // outside .ss-body: „Probleme” stays its first section
  }

  function summary(d) {
    var c = d.coverage || {};
    var h = d.history || {};
    var p = d.params || {};
    var sec = el("section", "ss-summary");
    sec.setAttribute("aria-labelledby", "ss-sum-h");
    var head = el("div", "ss-fig-head");
    var t = el("h2", "ss-fig-title", tt("stats.summary.title"));
    t.id = "ss-sum-h";
    head.append(t);
    var exp = el("div", "st-exports");
    var j = el("a", "btn btn-ghost btn-sm ss-csv", tt("stats.summary.json"));
    j.href = API + (query(v.p) ? "?" + query(v.p) : "");
    j.target = "_blank";
    j.rel = "noopener";
    exp.append(j);
    head.append(exp);
    sec.append(head);

    var cov = el("p", "ss-coverage");
    var ex = c.excluded || {};
    cov.textContent = tt("stats.summary.coverage", { period: periodText(d), journeys: pl(c.journeys || 0, "stats.w.journey"),
      trains: pl(c.trains || 0, "stats.w.train"), obs: pl(c.observations || 0, "stats.w.obs_ocr"),
      ghost: pl(ex.ghost || 0, "stats.w.ghost"), low: ex.low_quality || 0 }) +
      (p.operator ? tt("stats.summary.operator", { v: p.operator }) : "") + (p.tip ? tt("stats.summary.type", { v: p.tip }) : "") +
      (p.confirmed_only ? tt("stats.summary.confirmed_only") : "");
    sec.append(cov);

    if (!h.sufficient) {
      var w = el("p", "st-warn ss-history");
      w.setAttribute("role", "note");
      w.append(el("strong", null, tt("stats.summary.insufficient_h", { days: pl(h.days || 0, "stats.w.day") })),
        document.createTextNode(tt("stats.summary.insufficient_b", { n: h.needed_days || 7 })));
      sec.append(w);
    }
    var ul = el("ul", "ss-insights");
    (d.insights || []).forEach(function (s) { ul.append(el("li", null, s)); });
    sec.append(ul);
    var when = el("p", "ss-generated");
    var g = d.generated_at ? new Date(d.generated_at) : null;
    when.textContent = tt("stats.summary.generated", { time: g && !isNaN(g) ? new Intl.DateTimeFormat(window.I18N.lang(), { timeStyle: "medium", timeZone: "Europe/Bucharest" }).format(g) : "—",
      ttl: d.cache_ttl_s || 60, max: p.on_time_max_min, min: p.min_sample });
    sec.append(when);
    v.ui.body.append(sec);
  }

  // Hero strip (Beta 1.26): the numbers that matter first, counted up once on screen.
  function heroStrip(d, boards) {
    var c = d.coverage || {};
    var p = d.params || {};
    var sec = el("section", "ss-hero-strip");
    sec.setAttribute("aria-label", tt("stats.hero.aria"));
    var items = boards.map(function (b) {
      var s = d.boards[b];
      var ok = s.n && s.sufficient;
      return { label: tt("stats.hero.on_time", { board: BOARD_PL[b] }), tone: b === "arrival" ? "arr" : "dep", cls: "ss-hero-v " + (ok ? tone("pct", s.on_time_pct) : ""),
        value: ok ? s.on_time_pct : null, unit: ok ? " %" : "", fmt: function (x) { return nf.format(Math.round(x * 10) / 10); },
        sub: ok ? tt("stats.hero.on_time_sub", { ok: s.on_time, n: s.n, max: p.on_time_max_min })
          : (s.n ? tt("stats.hero.small_sub", { n: s.n, min: p.min_sample }) : tt("stats.hero.none_sub")),
        meter: ok ? s.on_time_pct : null, gauge: true };
    });
    items.push({ label: tt("stats.hero.analysed"), cls: "ss-hero-v", value: c.journeys || 0,
      sub: pl(c.trains || 0, "stats.w.train") + " · " + pl(c.observations || 0, "stats.w.obs_ocr") });
    items.push({ label: tt("stats.hero.days"), cls: "ss-hero-v", value: c.days || 0,
      sub: c.first ? (c.first === c.last ? S.dayText(c.first) : S.dayText(c.first) + " – " + S.dayText(c.last)) : tt("stats.hero.no_day") });
    sec.append(U().hero(items));
    v.ui.body.append(sec);
  }

  // Part-to-whole: on time / late / very late for one board (a donut, never a bar).
  function onTimeDonut(host, s, p, b) { U().delayDonut(host, s, p, BOARD_PL[b], "kpi-" + b); }

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
        hero.append(el("span", "ss-hero-l", tt("stats.kpi.on_time", { pct: pct(s.on_time_pct), max: p.on_time_max_min })));
      } else {
        hero.append(el("span", "ss-hero-v ss-muted", "—"),
                    el("span", "ss-hero-l", s.n ? tt("stats.kpi.small") : tt("stats.kpi.none")));
      }
      card.append(hero);
      if (s.n && U()) {
        var dn = el("div", "ss-kpi-donut");
        onTimeDonut(dn, s, p, b);
        card.append(dn);
      }
      card.append(nLine(s.n ? tt("stats.kpi.line", { ok: s.on_time, n: s.n, obs: pl(s.journeys || 0, "stats.w.journey_obs") })
        : tt("stats.kpi.line0", { obs: pl(s.journeys || 0, "stats.w.journey_obs") })));
      var dl = el("dl", "ss-kpi-grid");
      [[tt("stats.kpi.median"), minutes(s.median)], [tt("stats.kpi.mean"), minutes(s.mean)], ["p90", minutes(s.p90)],
       [tt("stats.kpi.over30"), s.n ? s.over_30 + (s.over_30_pct != null ? " (" + pct(s.over_30_pct) + ")" : "") : "—"],
       [tt("stats.kpi.max"), minutes(s.max)]].forEach(function (x) {
        var it = el("div", "ss-kpi-item");
        it.append(el("dt", null, x[0]), el("dd", null, x[1]));
        dl.append(it);
      });
      card.append(dl);
      if (s.n && !s.sufficient) card.append(warn(tt("stats.warn.small_raw", { n: s.n, min: p.min_sample })));
      box.append(card);
    });
    v.ui.body.append(box);
  }

  function smallNote(n, min) {
    return n > 0 && n < min ? tt("stats.warn.small_pct", { n: n, min: min }) : null;
  }

  function distributionSection(d, boards) {
    var p = d.params;
    var usePct = boards.every(function (b) { return d.boards[b].sufficient; });
    var f = figure({ title: tt("stats.fig.distribution"), key: "cat-de-mult-intarzie-trenurile", set: "distribution", legend: legend(boards),
      how: tt(usePct ? "stats.fig.distribution.how_pct" : "stats.fig.distribution.how_n") +
        (p.on_time_max_min === 5 ? tt("stats.fig.distribution.on_time5") : tt("stats.fig.distribution.on_timeN", { max: p.on_time_max_min })) });
    var cats = (d.distribution[boards[0]] || []).map(function (x) { return x.label; });
    columns(f.host, { cats: cats, unit: usePct ? "%" : tt("stats.unit.journeys"),
      title: tt("stats.fig.distribution.chart"), desc: tt("stats.fig.distribution.desc", { boards: boards.map(function (b) { return BOARD_PL[b].toLowerCase(); }).join(tt("stats.and")) }),
      series: boards.map(function (b) {
        var items = d.distribution[b];
        return { board: b,
          values: items.map(function (x) { return usePct ? x.pct : x.n; }),
          labels: items.map(function (x) { return usePct ? (x.pct == null ? null : nf.format(Math.round(x.pct)) + "%") : String(x.n); }),
          tips: items.map(function (x) { return tt("stats.tip.dist", { board: BOARD_PL[b], label: x.label, n: x.n, pct: x.pct != null ? " (" + pct(x.pct) + ")" : "", total: d.boards[b].n }); }) };
      }) });
    f.foot.append(nLine(boards.map(function (b) { return BOARD_PL[b] + ": N = " + d.boards[b].n; }).join(" · ")));
    boards.forEach(function (b) { var w = smallNote(d.boards[b].n, p.min_sample); if (w) f.foot.append(warn(BOARD_PL[b] + " — " + w)); });
    var rows = [];
    cats.forEach(function (c, i) {
      var r = [c + " min"];
      boards.forEach(function (b) { var x = d.distribution[b][i]; r.push(x.n, x.pct == null ? "—" : pct(x.pct)); });
      rows.push(r);
    });
    var cols = [tt("stats.col.delay")];
    boards.forEach(function (b) { cols.push(tt("stats.col.journeys_sfx", { board: BOARD_PL[b] }), tt("stats.col.pct_sfx", { board: BOARD_PL[b] })); });
    f.foot.append(dataTable(tt("stats.fig.distribution.chart"), cols, rows));
  }

  // ---- Beta 1.26: part-to-whole figure — donuts (few categories, shares of one total) ----

  var TYPE_SLOT = { IR: 1, IRN: 2, RE: 3, R: 4, RM: 5, IC: 6 };

  // list = [{key, journeys}] → segments: biggest first, at most `max` named slices + „Altele”
  function shareSegments(list, max, slotOf) {
    var rows = (list || []).filter(function (x) { return x.journeys > 0; })
      .sort(function (a, b) { return b.journeys - a.journeys; });
    var segs = [];
    var rest = 0;
    rows.forEach(function (x, i) {
      if (i < max) segs.push({ label: x.key, value: x.journeys, slot: slotOf(x, i) });
      else rest += x.journeys;
    });
    if (rest) segs.push({ label: tt("stats.share.other"), value: rest, slot: "other" });
    return segs;
  }

  function shareSection(d, boards) {
    var p = d.params;
    var f = figure({ title: tt("stats.fig.share"), key: "cum-se-impart-calatoriile", set: "types", wide: true,
      how: tt("stats.fig.share.how", { min: p.min_sample }) });
    var rows = [];
    var any = false;
    function addRows(group, segs, total) {
      segs.forEach(function (x) { rows.push([group + " — " + x.label, x.value, total >= p.min_sample ? pct(100 * x.value / total) : "—"]); });
    }
    function cellFor(host, board, head) {
      var cell = el("div", "ss-donut-cell");
      var h = el("h4", "ss-mult-h");
      if (board) h.append(boardKey(board));
      h.append(document.createTextNode(head));
      cell.append(h);
      host.append(cell);
      return cell;
    }
    if (boards.length > 1) {
      var segs = boards.map(function (b) { return { label: BOARD_PL[b], value: d.boards[b].journeys || 0, slot: b === "arrival" ? "arr" : "dep" }; });
      var tot = segs.reduce(function (a, x) { return a + x.value; }, 0);
      if (tot) {
        any = true;
        f.host.append(el("h3", "ss-rank-h", tt("stats.share.arr_dep")));
        U().donut(f.host, { title: tt("stats.share.arr_dep_title"), valueUnit: tt("stats.unit.journeys"), showPct: tot >= p.min_sample,
          desc: segs.map(function (x) { return x.label + " " + x.value; }).join(", ") + " " + tt("stats.share.n_total", { n: tot }),
          centerValue: nf.format(tot), centerLabel: tt("stats.unit.journeys"), segments: segs });
        addRows(tt("stats.share.board"), segs, tot);
      }
    }
    [[tt("stats.share.by_type"), "types", function (x) { return TYPE_SLOT[String(x.key).toUpperCase()] || "other"; }, 6, tt("stats.share.type")],
     [tt("stats.share.by_operator"), "operators", function (x, i) { return i + 1; }, 5, tt("stats.share.operator")]].forEach(function (g) {
      var pair = el("div", "ss-donut-pair");
      var made = 0;
      boards.forEach(function (b) {
        var segs = shareSegments(d[g[1]][b], g[3], g[2]);
        var tot = segs.reduce(function (a, x) { return a + x.value; }, 0);
        if (!tot) return;
        made += 1;
        any = true;
        var cell = cellFor(pair, b, BOARD_PL[b]);
        U().donut(cell, { title: g[0] + " — " + BOARD_PL[b], valueUnit: tt("stats.unit.journeys"), showPct: tot >= p.min_sample,
          desc: segs.map(function (x) { return x.label + " " + x.value; }).join(", ") + " " + tt("stats.share.n_total", { n: tot }),
          centerValue: nf.format(tot), centerLabel: tt("stats.share.total_n"), segments: segs });
        cell.append(nLine("N = " + tot));
        addRows(g[4] + " — " + BOARD_PL[b], segs, tot);
      });
      if (made) { f.host.append(el("h3", "ss-rank-h", g[0])); f.host.append(pair); }
    });
    if (!any) { f.foot.append(el("p", "ss-empty", tt("stats.empty.no_journeys_filters"))); return; }
    f.foot.append(csvLink("operators", tt("stats.share.csv_operators")));
    f.foot.append(dataTable(tt("stats.share.table"), tt("stats.share.cols").split("|"), rows));
  }

  function hourlySection(d, boards) {
    var p = d.params;
    var cats = [];
    for (var h = 0; h < 24; h++) cats.push(hh(h));
    var f = figure({ title: tt("stats.fig.hourly"), key: "la-ce-ora-intarzie-cel-mai-mult", set: "hourly", wide: true,
      legend: legend(boards, [["ss-key-hollow", tt("stats.legend.small", { min: p.min_sample })]]),
      how: tt("stats.fig.hourly.how") });
    lines(f.host, { cats: cats, unit: "min", extFmt: function (q) { return nf.format(q) + " min"; },
      refR: 78, refs: [{ value: p.on_time_max_min, label: tt("stats.ref.on_time", { max: p.on_time_max_min }), short: tt("stats.ref.on_time_short", { max: p.on_time_max_min }) }],
      title: tt("stats.fig.hourly.chart"), desc: tt("stats.fig.hourly.desc"),
      series: boards.map(function (b) {
        var hs = d.hourly[b];
        return { board: b, values: hs.map(function (x) { return x.median; }),
          low: hs.map(function (x) { return !x.sufficient; }),
          tips: hs.map(function (x) {
            return tt("stats.tip.hour", { board: BOARD_PL[b], hour: hourRange(x.key), median: minutes(x.median), mean: minutes(x.mean),
              n: x.n, small: x.n && !x.sufficient ? tt("stats.small_paren") : "" });
          }) };
      }) });
    nStrip(f.host, { right: function (w) { return w >= 520 ? 78 : 12; }, cats: cats, title: tt("stats.fig.hourly.nstrip"), desc: tt("stats.fig.hourly.nstrip_desc"),
      series: boards.map(function (b) { return { board: b, values: d.hourly[b].map(function (x) { return x.n; }) }; }) });
    var rows = [];
    for (var i = 0; i < 24; i++) {
      var r = [hourRange(i)];
      boards.forEach(function (b) { var x = d.hourly[b][i]; r.push(x.n, minutes(x.median), minutes(x.mean), pct(x.on_time_pct)); });
      rows.push(r);
    }
    var cols = [tt("stats.col.sched_hour")];
    boards.forEach(function (b) { var L = BOARD_PL[b]; cols.push(tt("stats.col.board_n", { board: L }), tt("stats.col.board_median", { board: L }), tt("stats.col.board_mean", { board: L }), tt("stats.col.board_ontime", { board: L })); });
    f.foot.append(dataTable(tt("stats.fig.hourly.table"), cols, rows));
  }

  var HEAT_BINS = [[2, "≤ 2 min"], [5, "2–5 min"], [10, "5–10 min"], [20, "10–20 min"], [Infinity, "> 20 min"]];

  function heatClass(c) {
    if (!c) return "ss-cell-none";
    if (!c.n) return "ss-cell-unread";
    if (!c.sufficient) return "ss-cell-low";
    for (var i = 0; i < HEAT_BINS.length; i++) if (c.mean <= HEAT_BINS[i][0]) return "ss-q" + i;
    return "ss-q4";
  }

  function heatLegend(p) {
    var lg = el("div", "ss-legend ss-legend-scale");
    HEAT_BINS.forEach(function (b, i) {
      var it = el("span", "ss-legend-item");
      it.append(el("span", "ss-key ss-key-sq ss-q" + i), document.createTextNode(b[1]));
      lg.append(it);
    });
    [["ss-cell-low", "N < " + p.min_sample], ["ss-cell-unread", tt("stats.heat.unread")],
     ["ss-cell-none", tt("stats.heat.none")]].forEach(function (x) {
      var it = el("span", "ss-legend-item");
      it.append(el("span", "ss-key ss-key-sq " + x[0]), document.createTextNode(x[1]));
      lg.append(it);
    });
    return lg;
  }

  // Calendar (Beta 1.28, drawn by charts3.js): one square per service day; nothing without the chart layer.
  function calendarSection(d, boards) {
    if (!C3()) return;
    C3().calendarFigure({ d: d, boards: boards, figure: figure, multiples: multiples, legend: heatLegend(d.params),
      heatClass: heatClass, width: chartWidth, dataTable: dataTable, nLine: nLine, dayText: S.dayText, pl: pl,
      minutes: minutes, pct: pct, BOARD_PL: BOARD_PL, el: el });
  }

  function heatmapSection(d, boards) {
    var p = d.params;
    var lg = heatLegend(p);
    var f = figure({ title: tt("stats.fig.heatmap"), key: "ce-zile-si-ore-sunt-cele-mai-probl", set: "heatmap", wide: true, legend: lg,
      how: tt("stats.fig.heatmap.how", { min: p.min_sample }) });
    if (d.history && !d.history.sufficient) {
      f.foot.append(warn(tt("stats.fig.heatmap.short_history", { days: pl(d.history.days || 0, "stats.w.day") })));
    }
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
      var root = svgRoot(W, H, tt("stats.fig.heatmap.title", { board: BOARD_PL[b] }), tt("stats.fig.heatmap.desc"));
      for (var dd = 0; dd < 7; dd++) {
        root.append(svg("text", { x: L - 4, y: (T + dd * ch + ch / 2 + 4).toFixed(1), class: "ss-tick ss-tick-y" }, wdShort(dd)));
        for (var hr = 0; hr < 24; hr++) {
          var c = map[dd + "-" + hr];
          var g = svg("g", { class: "ss-mark" });
          g.append(svg("rect", { x: (L + hr * cw + 1).toFixed(1), y: (T + dd * ch + 1).toFixed(1),
                                 width: Math.max(1, cw - 2).toFixed(1), height: Math.max(1, ch - 2).toFixed(1), rx: 2,
                                 class: "ss-cell " + heatClass(c), "data-m": dd + "-" + hr }));
          tip(g, wd(dd) + ", " + hourRange(hr) + ": " + (!c ? tt("stats.tip.heat_none") : !c.n ?
            tt("stats.tip.heat_unread", { journeys: pl(c.journeys, "stats.w.journey") }) :
            tt("stats.tip.heat_cell", { mean: minutes(c.mean), median: minutes(c.median), n: c.n }) +
            (c.sufficient ? tt("stats.tip.heat_ontime", { pct: pct(c.on_time_pct) }) : tt("stats.small_paren"))));
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
        rows.push([BOARD_PL[b] + ", " + wd(c.d) + " " + hourRange(c.h), c.journeys, c.n, minutes(c.mean), minutes(c.median), pct(c.on_time_pct)]);
      });
    });
    f.foot.append(nLine(tt("stats.fig.heatmap.only_cells", { n: rows.length })));
    f.foot.append(dataTable(tt("stats.fig.heatmap.table"), tt("stats.col.board_day_hour").split("|"), rows));
  }

  function dailySection(d, boards) {
    var p = d.params;
    var keys = {};
    boards.forEach(function (b) { (d.daily[b] || []).forEach(function (x) { keys[x.key] = true; }); });
    var days = Object.keys(keys).sort();
    var f = figure({ title: tt("stats.fig.daily"), key: "cum-a-evoluat-punctualitatea-de-la", set: "daily",
      legend: legend(boards),
      how: tt("stats.fig.daily.how", { max: p.on_time_max_min, min: p.min_sample }) });
    if (days.length < 2) {
      f.foot.append(el("p", "ss-empty", days.length ? tt("stats.fig.daily.one_day") :
        tt("stats.fig.daily.no_day")));
    }
    if (days.length) {
      var byKey = {};
      boards.forEach(function (b) { byKey[b] = {}; (d.daily[b] || []).forEach(function (x) { byKey[b][x.key] = x; }); });
      lines(f.host, { cats: days.map(shortDay), unit: "%", yMax: 100, yStep: 25,
        yFmt: function (t) { return t + "%"; },
        refs: boards.filter(function (b) { return d.boards[b].sufficient && d.boards[b].on_time_pct != null; }).map(function (b) {
          return { value: d.boards[b].on_time_pct, cls: BOARD_CLS[b], label: tt("stats.ref.mean", { board: BOARD_PL[b], pct: pct(d.boards[b].on_time_pct) }), short: BOARD_PL[b] + " " + Math.round(d.boards[b].on_time_pct) + "%" };
        }),
        title: tt("stats.fig.daily.chart"), desc: tt("stats.fig.daily.desc"),
        series: boards.map(function (b) {
          return { board: b, values: days.map(function (k) { var x = byKey[b][k]; return x ? x.on_time_pct : null; }),
            tips: days.map(function (k) { var x = byKey[b][k];
              return tt("stats.tip.daily", { board: BOARD_PL[b], day: S.dayText(k), rest: x ? tt("stats.tip.daily_ok", { pct: pct(x.on_time_pct), median: minutes(x.median), n: x.n }) : tt("stats.tip.heat_none") }); }) };
        }) });
      nStrip(f.host, { right: function (w) { return w >= 520 && C3() && boards.some(function (b) { return d.boards[b].sufficient && d.boards[b].on_time_pct != null; }) ? 68 : 12; }, cats: days.map(shortDay), title: tt("stats.fig.daily.nstrip"), desc: tt("stats.fig.daily.nstrip_desc"),
        series: boards.map(function (b) { return { board: b, values: days.map(function (k) { var x = byKey[b][k]; return x ? x.n : 0; }) }; }) });
      var rows = days.map(function (k) {
        var r = [S.dayText(k)];
        boards.forEach(function (b) { var x = byKey[b][k]; r.push(x ? x.journeys : 0, x ? x.n : 0, x ? pct(x.on_time_pct) : "—", x ? minutes(x.median) : "—"); });
        return r;
      });
      var cols = [tt("stats.col.day")];
      boards.forEach(function (b) { var L = BOARD_PL[b]; cols.push(tt("stats.col.board_journeys", { board: L }), tt("stats.col.board_n", { board: L }), tt("stats.col.board_ontime2", { board: L }), tt("stats.col.board_median2", { board: L })); });
      f.foot.append(dataTable(tt("stats.punctuality_by_day"), cols, rows));
    }
  }

  function rankedSection(d, boards, key, title, how, setName, firstCol, figKey) {
    var p = d.params;
    var f = figure({ title: title, key: figKey, set: setName, how: how });
    var cells = multiples(f.host, boards.length);
    var rows = [];
    boards.forEach(function (b, bi) {
      var list = (d[key][b] || []).filter(function (x) { return x.journeys > 0; });
      var cell = cells[bi];
      var h = el("h3", "ss-mult-h");
      h.append(el("span", "ss-key " + BOARD_CLS[b]), document.createTextNode(BOARD_PL[b]));
      cell.append(h);
      if (!list.length) { cell.append(el("p", "ss-empty", tt("stats.ranked.no_journey"))); return; }
      hbars(cell, { board: b, max: 100, title: title + " — " + BOARD_PL[b],
        desc: tt("stats.ranked.desc", { what: firstCol.toLowerCase() }),
        rows: list.map(function (x) {
          return { label: x.key, value: x.sufficient ? x.on_time_pct : null, low: !x.sufficient, cls: x.sufficient ? tone("pct", x.on_time_pct) : "",
            valueText: x.sufficient ? pct(x.on_time_pct) + " · N = " + x.n : (x.n ? "N = " + x.n + " < " + p.min_sample : "N = 0"),
            tip: x.sufficient ? tt("stats.ranked.tip_ok", { pct: pct(x.on_time_pct), median: minutes(x.median), n: x.n })
              : tt("stats.ranked.tip_small", { n: x.n, mean: minutes(x.mean) }) };
        }) });
      list.forEach(function (x) { rows.push([BOARD_PL[b] + " — " + x.key, x.journeys, x.n, pct(x.on_time_pct), minutes(x.median), minutes(x.mean)]); });
    });
    f.foot.append(nLine(tt("stats.ranked.foot", { max: p.on_time_max_min, min: p.min_sample })));
    f.foot.append(dataTable(title, [firstCol].concat(tt("stats.col.ranked").split("|")), rows));
  }

  function routesSection(d, boards) {
    var p = d.params;
    var f = figure({ title: tt("stats.fig.routes"), key: "ce-rute-intarzie-cel-mai-mult-si-c", set: "routes",
      how: tt("stats.fig.routes.how", { min: p.min_sample }) });
    var cells = multiples(f.host, boards.length);
    var rows = [];
    boards.forEach(function (b, bi) {
      var r = d.routes[b];
      var cell = cells[bi];
      var h = el("h3", "ss-mult-h");
      h.append(el("span", "ss-key " + BOARD_CLS[b]), document.createTextNode(BOARD_PL[b] + (b === "arrival" ? tt("stats.dir.from") : tt("stats.dir.to"))));
      cell.append(h);
      if (!r.eligible) {
        cell.append(el("p", "ss-empty", tt("stats.fig.routes.no_station", { min: p.min_sample, has: pl(r.below_min || 0, "stats.w.station_has") })));
        return;
      }
      [[tt("stats.fig.routes.most_delayed"), r.most_delayed, "mean"], [tt("stats.fig.routes.most_punctual"), r.most_punctual, "pct"]].forEach(function (L) {
        cell.append(el("h4", "ss-rank-h", L[0]));
        var ol = el("ol", "ss-rank");
        L[1].forEach(function (x) {
          var li = el("li");
          li.append(S.stationLink(x.key));
          li.append(el("span", "ss-rank-v " + (L[2] === "mean" ? tone("minutes", x.mean) : tone("pct", x.on_time_pct)), L[2] === "mean" ? tt("stats.fig.routes.mean_suffix", { v: minutes(x.mean) }) : tt("stats.fig.routes.ontime_suffix", { v: pct(x.on_time_pct) })));
          li.append(el("span", "ss-rank-n", "N = " + x.n));
          ol.append(li);
          rows.push([BOARD_PL[b] + " — " + S.titleCase(x.key), L[0], x.n, minutes(x.mean), minutes(x.median), pct(x.on_time_pct)]);
        });
        cell.append(ol);
      });
      if (r.below_min) cell.append(nLine(tt("stats.fig.routes.below", { n: pl(r.below_min, "stats.w.station") })));
    });
    var more = el("a", "st-back", tt("stats.fig.routes.full"));
    more.href = "#clasamente";
    f.foot.append(more);
    f.foot.append(dataTable(tt("stats.fig.routes.table"), tt("stats.col.routes").split("|"), rows));
  }

  function trafficSection(d, boards) {
    var t = d.traffic || {};
    var days = t.days || 0;
    var cats = [];
    for (var h = 0; h < 24; h++) cats.push(hh(h));
    var f = figure({ title: tt("stats.fig.traffic"), key: "cand-e-gara-cea-mai-aglomerata", set: "traffic", wide: true, legend: legend(boards),
      how: tt("stats.fig.traffic.how", { days: pl(days, "stats.w.day") }) });
    if (!days) { f.foot.append(el("p", "ss-empty", tt("stats.empty.no_journeys_filters"))); return; }
    columns(f.host, { cats: cats, unit: tt("stats.unit.per_day"), title: tt("stats.fig.traffic.chart"),
      desc: tt("stats.fig.traffic.desc"),
      series: boards.map(function (b) {
        return { board: b, values: t[b].map(function (x) { return x / days; }),
          tips: t[b].map(function (x, i) { return tt("stats.fig.traffic.tip", { board: BOARD_PL[b], hour: hourRange(i), x: x, days: pl(days, "stats.w.day"), avg: nf.format(x / days) }); }) };
      }) });
    var tot = boards.map(function (b) { return BOARD_PL[b] + ": " + t[b].reduce(function (a, x) { return a + x; }, 0); });
    f.foot.append(nLine(tt("stats.fig.traffic.total", { list: tot.join(" · "), days: pl(days, "stats.w.day") })));
    var rows = [];
    for (var i = 0; i < 24; i++) {
      var r = [hourRange(i)];
      boards.forEach(function (b) { r.push(t[b][i], nf.format(t[b][i] / days)); });
      rows.push(r);
    }
    var cols = [tt("stats.col.sched_hour")];
    boards.forEach(function (b) { cols.push(tt("stats.col.board_total", { board: BOARD_PL[b] }), tt("stats.col.board_perday", { board: BOARD_PL[b] })); });
    f.foot.append(dataTable(tt("stats.fig.traffic.table"), cols, rows));
  }

  function platformsSection(d, boards) {
    var platf = d.platforms || {};
    var seen = {};
    boards.forEach(function (b) { (platf[b].lines || []).forEach(function (x) { seen[x.line] = true; }); });
    var lineKeys = Object.keys(seen).map(Number).sort(function (a, b) { return a - b; });
    var f = figure({ title: tt("stats.fig.platforms"), key: "ce-linii-peroane-se-folosesc-cel-m", set: "platforms", wide: true, legend: legend(boards),
      how: tt("stats.fig.platforms.how") });
    if (!lineKeys.length) { f.foot.append(el("p", "ss-empty", tt("stats.fig.platforms.none"))); }
    else {
      var cats = lineKeys.map(String);
      var by = {};
      boards.forEach(function (b) { by[b] = {}; platf[b].lines.forEach(function (x) { by[b][x.line] = x.n; }); });
      columns(f.host, { cats: cats, unit: tt("stats.unit.journeys"), title: tt("stats.fig.platforms.chart"),
        desc: tt("stats.fig.platforms.desc"),
        series: boards.map(function (b) {
          return { board: b, values: cats.map(function (c) { return by[b][c] || 0; }),
            tips: cats.map(function (c) { return tt("stats.fig.platforms.tip", { board: BOARD_PL[b], c: c, n: by[b][c] || 0 }); }) };
        }) });
      var rows = cats.map(function (c) { var r = [tt("stats.fig.platforms.row", { c: c })]; boards.forEach(function (b) { r.push(by[b][c] || 0); }); return r; });
      var miss = [tt("stats.fig.platforms.missing")];
      boards.forEach(function (b) { miss.push(platf[b].missing); });
      rows.push(miss);
      f.foot.append(dataTable(tt("stats.fig.platforms.chart"), [tt("stats.fig.platforms.col")].concat(boards.map(function (b) { return BOARD_PL[b]; })), rows));
    }
    f.foot.append(nLine(boards.map(function (b) { return tt("stats.fig.platforms.missing_n", { board: BOARD_PL[b], n: platf[b].missing }); }).join(" · ")));
  }

  function weatherSection(d) {
    var w = d.weather || {};
    var p = d.params;
    var f = figure({ title: tt("stats.fig.weather"), key: "vremea-si-intarzierile", set: w.status === "ok" ? "weather" : null,
      how: tt("stats.fig.weather.how") });
    var note = warn(w.note || tt("stats.fig.weather.note"));
    note.classList.add("ss-weather-note");
    note.setAttribute("role", "note");
    f.foot.append(note);
    if (w.status !== "ok") {
      var box = el("div", "ss-collect");
      box.append(el("p", "ss-collect-h", tt("stats.fig.weather.collecting")));
      box.append(el("p", null, tt("stats.fig.weather.collecting_b", { matched: pl(w.matched || 0, "stats.w.journey_has"), days: pl(w.days || 0, "stats.w.day"),
        obs: pl(w.observations || 0, "stats.w.weather_obs"), needed: w.needed_days || 7, min: p.min_sample })));
      f.host.append(box);
      return;
    }
    var rows = [];
    var wb = w.boards || {};
    var shown = BOARDS.filter(function (b) { return wb[b]; });
    var cells = multiples(f.host, shown.length);
    shown.forEach(function (b, bi) {
      var cell = cells[bi];
      var h = el("h3", "ss-mult-h");
      h.append(el("span", "ss-key " + BOARD_CLS[b]), document.createTextNode(BOARD_PL[b]));
      cell.append(h);
      if (wb[b].status !== "ok") {
        cell.append(el("p", "ss-empty", tt("stats.fig.weather.board_collecting", { journeys: pl(wb[b].matched || 0, "stats.w.journey"), days: pl(wb[b].days || 0, "stats.w.day") })));
        return;
      }
      [["precip", tt("stats.weather.precip")], ["temp", tt("stats.weather.temp")]].forEach(function (dim) {
        var gs = (wb[b].groups && wb[b].groups[dim[0]]) || [];
        if (!gs.length) return;
        cell.append(el("h4", "ss-rank-h", dim[1]));
        var host = el("div", "ss-sub");
        cell.append(host);
        weatherBars(host, b, dim, gs, rows);
      });
    });
    f.foot.append(nLine(tt("stats.fig.weather.foot", { matched: pl(w.matched || 0, "stats.w.journey"), days: pl(w.days || 0, "stats.w.day") })));
    f.foot.append(dataTable(tt("stats.fig.weather.table"), tt("stats.col.weather").split("|"), rows));
  }

  function weatherBars(cell, b, dim, gs, rows) {
    var mx = Math.max.apply(null, gs.map(function (g) { return g.mean || 0; }).concat([1]));
    hbars(cell, { board: b, max: mx, title: tt("stats.fig.weather.bars", { dim: dim[1].toLowerCase(), board: BOARD_PL[b] }),
      desc: tt("stats.fig.weather.bars_desc"),
      rows: gs.map(function (g) {
        return { label: g.label, value: g.sufficient ? g.mean : null, low: !g.sufficient,
          valueText: (g.sufficient ? minutes(g.mean) + " · " : "") + "N = " + g.n,
          tip: tt("stats.fig.weather.bar_tip", { mean: minutes(g.mean), median: minutes(g.median), n: g.n }) };
      }) });
    gs.forEach(function (g) {
      rows.push([BOARD_PL[b] + ", " + dim[1].toLowerCase() + ": " + g.label, g.n, minutes(g.mean), minutes(g.median), pct(g.on_time_pct)]);
    });
  }

  function qualitySection(d) {
    var q = d.quality || {};
    var minS = (d.params && d.params.min_sample) || 5;
    var st = q.states || {};
    var obs = q.observations || {};
    var ex = q.excluded || {};
    var f = figure({ title: tt("stats.fig.quality"), key: "cat-de-bune-sunt-datele", wide: true,
      how: tt("stats.fig.quality.how") });
    var cells = multiples(f.host, 2);
    var nb = 0;
    function block(title, items, total, slots) {
      var cell = cells[nb++];
      cell.append(el("h3", "ss-mult-h", title));
      if (!total) { cell.append(el("p", "ss-empty", tt("stats.fig.quality.nothing"))); return; }
      if (U()) {
        U().donut(cell, { title: title, desc: tt("stats.fig.quality.block_desc", { title: title }), valueUnit: "", showPct: total >= minS,
          centerValue: nf.format(total), centerLabel: tt("stats.fig.quality.in_total"),
          segments: items.map(function (x, i) { return { label: x[0], value: x[1], slot: slots[i] }; }) });
      } else {
        hbars(cell, { board: "arrival", max: total, title: title, desc: tt("stats.fig.quality.block_desc2", { title: title }),
          rows: items.map(function (x) { return { label: x[0], value: x[1], cls: "ss-neutral", valueText: nf.format(x[1]), tip: x[1] + " din " + total }; }) });
      }
      cell.append(nLine(tt("stats.fig.quality.total", { n: nf.format(total) })));
    }
    var jt = (st.confirmed || 0) + (st.unconfirmed || 0) + (st.unknown || 0) + (st.in_progress || 0);
    block(tt("stats.fig.quality.journeys"), ["confirmed", "unconfirmed", "unknown", "in_progress"].map(function (k) {
      return [STATE_TEXT[k], st[k] || 0]; }), jt, [1, 5, "mute", 4]);
    var ot = 0;
    Object.keys(obs).forEach(function (k) { ot += obs[k] || 0; });
    block(tt("stats.fig.quality.ocr") + (q.counters_scope === "all" ? tt("stats.fig.quality.all_ops") : ""), ["ok", "uncertain", "rejected_low_conf", "incomplete"].map(function (k) {
      return [OBS_TEXT[k], obs[k] || 0]; }), ot, [1, 5, 2, "mute"]);
    f.foot.append(nLine(tt("stats.fig.quality.excluded", { scope: q.counters_scope === "all" ? tt("stats.fig.quality.scope") : "",
      ghost: pl(ex.ghost || 0, "stats.w.ghost"), low: ex.low_quality || 0, unc: q.uncertain_names || 0 })));
    f.foot.append(dataTable(tt("stats.fig.quality.table"), tt("stats.col.quality").split("|"),
      ["confirmed", "unconfirmed", "unknown", "in_progress"].map(function (k) { return [tt("stats.fig.quality.row_j", { s: STATE_TEXT[k] }), st[k] || 0]; })
        .concat(["ok", "uncertain", "rejected_low_conf", "incomplete"].map(function (k) { return [tt("stats.fig.quality.row_o", { s: OBS_TEXT[k] }), obs[k] || 0]; }))
        .concat([[tt("stats.fig.quality.row_ghost"), ex.ghost || 0], [tt("stats.fig.quality.row_low"), ex.low_quality || 0]])));
  }

  function glossary(d) {
    var p = d.params || {};
    var sec = el("section", "ss-glossary");
    sec.setAttribute("aria-labelledby", "ss-glos-h");
    var h = el("h2", "ss-fig-title", tt("stats.gl.title"));
    h.id = "ss-glos-h";
    sec.append(h);
    var dl = el("dl", "ss-gl");
    [["delay", {}], ["ontime", { max: p.on_time_max_min }], ["journey", {}], ["tjo", {}], ["confirmed", { gap: p.final_read_max_gap_min || 15 }],
     ["unconfirmed", {}], ["unknown", {}], ["n", {}], ["small", { min: p.min_sample }], ["median", {}], ["ghost", {}]].forEach(function (x) {
      dl.append(el("dt", null, tt("stats.gl." + x[0] + ".t")), el("dd", null, tt("stats.gl." + x[0] + ".d", x[1])));
    });
    sec.append(dl);
    v.ui.body.append(sec);
  }

  // ---- Probleme (Beta 1.19): deterministic findings computed on the server (app/stats_problems.py)

  var SEV_KEY = { "mare": "mare", "medie": "medie", "mică": "mica" };
  var LEVEL_KEY = { "insuficientă": "low", "parțială": "mid", "bună": "ok" };
  var CONF_KEY = { "ridicată": "ridicata", "medie": "medie", "scăzută": "scazuta" };
  function srv(map, prefix, val) { return map[val] ? tt(prefix + map[val]) : val; }   // known server words follow the language; anything else stays as sent

  function hashLink(l, cls) {
    var a = el("a", cls || "btn btn-ghost btn-sm ss-plink", l.label);
    // only in-app routes (#…): the server builds them, the page never follows anything else
    a.href = /^#[a-z]/.test(l.href || "") ? l.href : "#statistici";
    return a;
  }

  function badge(text, cls) { return el("span", "ss-badge " + cls, text); }

  function boardKey(b) { return el("span", "ss-key " + BOARD_CLS[b]); }

  function sectionHeading(text, sub) {
    var box = el("div", "ss-part");
    box.append(el("h2", "ss-part-h", text));
    if (sub) box.append(el("p", "ss-part-sub", sub));
    v.ui.body.append(box);
  }

  function coverageBox(c, d) {
    var box = el("div", "ss-cov ss-cov-" + (LEVEL_KEY[c.level] || "mid"));
    box.setAttribute("role", "note");
    var top = el("p", "ss-cov-h");
    var span = c.first ? (c.first === c.last ? shortDay(c.first) : shortDay(c.first) + "–" + shortDay(c.last)) : "";
    top.append(el("strong", null, tt("stats.cov.title", { level: srv(LEVEL_KEY, "stats.level.", c.level) })),
      document.createTextNode(tt("stats.cov.days", { days: pl(c.days || 0, "stats.w.day"), span: span ? " (" + span + ")" : "", n: c.needed_days })));
    box.append(top);
    var ul = el("ul", "ss-cov-list");
    if (c.partial && c.partial.length) {
      ul.append(el("li", null, tt("stats.cov.partial", { list: c.partial.map(function (x) { return shortDay(x.date) + " (" + x.why + ")"; }).join("; ") })));
    }
    if (c.gaps_count) {
      var longest = c.gaps.reduce(function (m, g) { return g.minutes > m.minutes ? g : m; }, c.gaps[0]);
      ul.append(el("li", null, tt("stats.cov.gaps", { thr: c.gap_threshold_min, count: c.gaps_count, total: c.gap_minutes, min: longest.minutes,
        when: shortDay(longest.start.slice(0, 10)) + " " + longest.start.slice(11, 16) + "–" + longest.end.slice(11, 16) })));
    } else {
      ul.append(el("li", null, tt("stats.cov.no_gaps", { thr: c.gap_threshold_min })));
    }
    ul.append(el("li", null, tt("stats.cov.results", { done: pl(c.finished || 0, "stats.w.journey_done"), unc: c.unconfirmed || 0, unk: c.unknown || 0, prog: c.in_progress || 0 })));
    ul.append(el("li", null, tt("stats.cov.cannot", { trend: (c.days || 0) < c.needed_days ? tt("stats.cov.trend") : "" })));
    box.append(ul);
    return box;
  }

  function problemItem(it) {
    var li = el("li", "ss-prob ss-sev-" + (SEV_KEY[it.severity] || "mica"));
    var head = el("div", "ss-prob-head");
    head.append(el("span", "ss-prob-rank", String(it.rank)));
    var t = el("h3", "ss-prob-title");
    if (it.board) t.append(boardKey(it.board));
    t.append(document.createTextNode(it.title));
    head.append(t);
    li.append(head);
    var b = el("p", "ss-badges");
    b.append(badge(tt("stats.prob.severity", { v: srv(SEV_KEY, "stats.sev.", it.severity) }), "ss-badge-sev"), badge(tt("stats.prob.confidence", { v: srv(CONF_KEY, "stats.conf.", it.confidence) }), "ss-badge-conf"),
      badge("N = " + it.n, "ss-badge-n"));
    li.append(b);
    li.append(el("p", "ss-prob-fig", it.figures));
    var why = el("p", "ss-prob-why");
    why.append(el("strong", null, tt("stats.prob.why")), document.createTextNode(it.why));
    li.append(why);
    if (it.links && it.links.length) {
      var links = el("div", "ss-prob-links");
      it.links.forEach(function (l) { links.append(hashLink(l)); });
      li.append(links);
    }
    return li;
  }

  function problemsSection(d) {
    var pr = d.problems;
    var p = d.params || {};
    var sec = el("section", "ss-problems");
    sec.setAttribute("aria-labelledby", "ss-prob-h");
    var head = el("div", "ss-fig-head");
    var h = el("h2", "ss-fig-title ss-prob-h1", tt("stats.fig.problems"));
    h.id = "ss-prob-h";
    head.append(h);
    sec.append(head);
    sec.append(el("p", "ss-how", tt("stats.fig.problems.how", { max: p.on_time_max_min, min: p.min_sample })));
    sec.append(coverageBox(pr.coverage, d));
    if (pr.status !== "ok") {
      sec.append(warn(pr.message));
    } else if (!pr.items.length) {
      sec.append(el("p", "ss-empty", tt("stats.fig.problems.none")));
    } else {
      var ol = el("ol", "ss-prob-list");
      pr.items.forEach(function (it) { ol.append(problemItem(it)); });
      sec.append(ol);
    }
    v.ui.body.append(sec);
  }

  function goodSection(d) {
    var good = d.problems.good || [];
    if (!good.length) return;
    var sec = el("section", "ss-good");
    sec.setAttribute("aria-labelledby", "ss-good-h");
    var h = el("h2", "ss-fig-title", tt("stats.fig.good"));
    h.id = "ss-good-h";
    sec.append(h);
    var ul = el("ul", "ss-good-list");
    good.forEach(function (s) { ul.append(el("li", null, s)); });
    sec.append(ul);
    v.ui.body.append(sec);
  }

  function recurrentSection(d) {
    var pr = d.problems, rec = pr.recurrent, p = d.params;
    var f = figure({ title: tt("stats.fig.recurrent"), key: "ce-trenuri-intarzie-zi-de-zi", wide: true,
      how: tt("stats.fig.recurrent.how", { days: rec.min_days, max: p.on_time_max_min }) });
    if (!rec.count) {
      f.host.append(el("p", "ss-empty", tt("stats.fig.recurrent.none", { seen: pl(rec.seen, "stats.w.train_seen"), days: rec.min_days })));
      return;
    }
    var ul = el("ul", "ss-ptrains");
    rec.trains.forEach(function (t) {
      var li = el("li", "ss-ptrain");
      var top = el("div", "ss-ptrain-top");
      top.append(hashLink({ label: t.train_type + " " + t.train_no, href: "#tren?nr=" + t.train_no }, "ss-ptrain-no"),
        el("span", "ss-ptrain-route", (t.board === "arrival" ? tt("stats.fig.recurrent.from") : tt("stats.fig.recurrent.to")) + S.titleCase(t.station) + " · " + t.sched_time),
        el("span", "ss-ptrain-board", BOARD_PL[t.board]));
      li.append(top);
      li.append(el("p", "ss-ptrain-stat", tt("stats.fig.recurrent.stat", { late: t.late_days, days: t.days, o15: t.over_15_days, median: minutes(t.median), max: minutes(t.max) })));
      if (U()) {
        var sp = el("div", "ss-ptrain-spark");
        sp.append(U().spark(t.delays.map(function (x) { return x.delay; }), { tone: "bad",
          label: tt("stats.fig.recurrent.spark", { train: t.train_type + " " + t.train_no, list: t.delays.map(function (x) { return minutes(x.delay); }).join(", ") }) }));
        li.append(sp);
      }
      li.append(el("p", "ss-ptrain-days", t.delays.map(function (x) { return shortDay(x.date) + ": " + x.delay + " min"; }).join(" · ")));
      ul.append(li);
    });
    f.host.append(ul);
    f.foot.append(nLine(tt("stats.fig.recurrent.foot", { shown: rec.trains.length, count: pl(rec.count, "stats.w.train"), o15: rec.over_15_every_day,
      seen: pl(rec.seen, "stats.w.train_seen"), days: rec.min_days })));
  }

  function windowsSection(d, boards) {
    var pr = d.problems, p = d.params;
    var f = figure({ title: tt("stats.fig.windows"), key: "la-ce-ore-si-in-ce-zile-se-aduna-i", wide: true,
      how: tt("stats.fig.windows.how") });
    var cells = multiples(f.host, boards.length);
    boards.forEach(function (b, bi) {
      var cell = cells[bi];
      var h = el("h3", "ss-mult-h");
      h.append(boardKey(b), document.createTextNode(BOARD_PL[b]));
      cell.append(h);
      var ws = pr.windows[b] || [];
      hbars(cell, { board: b, max: 100, title: tt("stats.fig.windows.bars", { board: BOARD_PL[b] }),
        desc: tt("stats.fig.windows.bars_desc"),
        rows: ws.map(function (w) {
          return { label: w.label, value: w.over_15_pct, low: !w.sufficient,
            valueText: (w.critical ? "! " : "") + (w.sufficient ? pct(w.over_15_pct) + " · " + w.over_15 + "/" + w.n : (w.n ? w.over_15 + "/" + w.n + " (N < " + p.min_sample + ")" : "N = 0")),
            tip: tt("stats.fig.windows.tip", { o15: w.over_15, n: w.n, crit: w.critical ? tt("stats.fig.windows.crit") : "", late: w.late_days, days: w.days }) };
        }) });
      var crit = ws.filter(function (w) { return w.critical; });
      cell.append(nLine(crit.length ? tt("stats.fig.windows.crit_list", { list: crit.map(function (w) { return w.label; }).join(", ") }) :
        tt("stats.fig.windows.no_crit")));
    });
    var eps = pr.episodes || [];
    var eh = el("h3", "ss-rank-h", tt("stats.fig.windows.episodes"));
    f.foot.append(eh);
    if (!eps.length) {
      f.foot.append(el("p", "ss-empty", tt("stats.fig.windows.no_episode")));
    } else {
      var ul = el("ul", "ss-episodes");
      eps.forEach(function (e) {
        var li = el("li");
        li.append(hashLink({ label: shortDay(e.date) + ", " + e.label, href: "#istoric?date=" + e.date + "&board=" + e.board }, "ss-ep-link"),
          document.createTextNode(tt("stats.fig.windows.ep", { board: BOARD_PL[e.board].toLowerCase(), o30: e.over_30, n: e.n, base: pct(e.base_pct),
            dirs: pl(e.stations, "stats.w.direction"), unc: e.unconfirmed })));
        ul.append(li);
      });
      f.foot.append(ul);
    }
  }

  function compareSection(d, boards) {
    var pr = d.problems, p = d.params;
    var f = figure({ title: tt("stats.fig.compare"), key: "sosiri-si-plecari-fata-in-fata",
      how: tt("stats.fig.compare.how") });
    var t = el("table", "ss-cmp");
    var cap = el("caption", "sr-only", tt("stats.share.arr_dep"));
    t.append(cap);
    var thead = el("thead");
    var hr = el("tr");
    hr.append(el("th", null, tt("stats.fig.compare.measure")));
    boards.forEach(function (b) { var th = el("th"); th.append(boardKey(b), document.createTextNode(BOARD_PL[b])); th.scope = "col"; hr.append(th); });
    thead.append(hr);
    t.append(thead);
    var tb = el("tbody");
    function row(label, fn) {
      var r = el("tr");
      var th = el("th", null, label);
      th.scope = "row";
      r.append(th);
      boards.forEach(function (b) { r.append(el("td", null, fn(pr.boards[b]))); });
      tb.append(r);
    }
    row(tt("stats.fig.compare.ontime"), function (s) { return s.n ? tt("stats.fig.compare.of", { a: s.on_time, n: s.n }) + (s.on_time_pct != null ? " (" + pct(s.on_time_pct) + ")" : "") : "—"; });
    row(tt("stats.kpi.median"), function (s) { return minutes(s.median); });
    row(tt("stats.fig.compare.over15"), function (s) { return s.n ? String(s.over_15) : "—"; });
    row(tt("stats.kpi.over30"), function (s) { return s.n ? String(s.over_30) : "—"; });
    row(tt("stats.fig.compare.over60"), function (s) { return s.n ? String(s.over_60) : "—"; });
    row(tt("stats.fig.compare.trains_days"), function (s) { return s.trains + " · " + s.days; });
    t.append(tb);
    var wrap = el("div", "ss-cmp-wrap");
    wrap.append(t);
    f.host.append(wrap);
    boards.forEach(function (b) {
      var m = pr.boards[b].mix;
      if (m) {
        f.foot.append(nLine(tt("stats.fig.compare.mix", { board: BOARD_PL[b], station: S.titleCase(m.station),
          dir: m.on_time_pct > m.rest_on_time_pct ? tt("stats.fig.compare.up") : tt("stats.fig.compare.down"), a: m.on_time, n: m.n, pct: pct(m.on_time_pct),
          ra: m.rest_on_time, rn: m.rest_n, rpct: pct(m.rest_on_time_pct) })));
      }
    });
    f.foot.append(nLine(tt("stats.fig.compare.foot", { max: p.on_time_max_min })));
  }

  function bigSection(d, boards) {
    var pr = d.problems;
    var f = figure({ title: tt("stats.fig.big"), key: "cat-de-des-apar-intarzieri-foarte-",
      how: tt("stats.fig.big.how") });
    boards.forEach(function (b) {
      var g = pr.big[b];
      var h = el("h3", "ss-mult-h");
      h.append(boardKey(b), document.createTextNode(tt("stats.fig.big.head", { board: BOARD_PL[b], o30: g.over_30, o60: g.over_60, n: g.n })));
      f.host.append(h);
      if (!g.top.length) { f.host.append(el("p", "ss-empty", tt("stats.fig.big.none"))); return; }
      var ol = el("ol", "ss-rank");
      g.top.forEach(function (x) {
        var li = el("li");
        li.append(hashLink({ label: x.train_type + " " + x.train_no, href: "#tren?nr=" + x.train_no }, "ss-rank-link"),
          el("span", null, S.titleCase(x.station) + ", " + shortDay(x.date) + " " + x.sched_time + (x.state === "unconfirmed" ? tt("stats.fig.big.unconfirmed") : "")),
          el("span", "ss-rank-v", minutes(x.delay)));
        ol.append(li);
      });
      f.host.append(ol);
    });
  }

  function problemRoutesSection(d, boards) {
    var pr = d.problems, p = d.params;
    var f = figure({ title: tt("stats.fig.proutes"), key: "ce-directii-au-cele-mai-multe-inta",
      how: tt("stats.fig.proutes.how", { min: p.min_sample }) });
    boards.forEach(function (b) {
      var r = pr.routes[b];
      var h = el("h3", "ss-mult-h");
      h.append(boardKey(b), document.createTextNode(BOARD_PL[b] + (b === "arrival" ? tt("stats.dir.from") : tt("stats.dir.to"))));
      f.host.append(h);
      var list = (r.worst || []).filter(function (x) { return x.median > p.on_time_max_min; });
      if (!list.length) {
        f.host.append(el("p", "ss-empty", r.eligible ? tt("stats.fig.proutes.none", { max: p.on_time_max_min }) :
          tt("stats.fig.proutes.insufficient")));
      } else {
        var ol = el("ol", "ss-rank");
        list.forEach(function (x) {
          var li = el("li");
          li.append(hashLink({ label: S.titleCase(x.key), href: "#statie?nume=" + encodeURIComponent(x.key) + "&board=" + b }, "ss-rank-link"),
            el("span", "ss-rank-n", tt("stats.fig.proutes.row", { a: x.on_time, n: x.n, trains: pl(x.trains, "stats.w.train") })),
            el("span", "ss-rank-v", tt("stats.fig.proutes.median", { v: minutes(x.median) })));
          ol.append(li);
        });
        f.host.append(ol);
      }
      f.host.append(nLine(tt("stats.fig.proutes.foot", { elig: r.eligible, single: r.single_train, below: r.below_min, min: p.min_sample })));
    });
  }

  function growthSection(d, boards) {
    var pr = d.problems, p = d.params;
    var f = figure({ title: tt("stats.fig.growth"), key: "creste-intarzierea-dupa-primul-anu",
      how: tt("stats.fig.growth.how") });
    var cells = multiples(f.host, boards.length);
    boards.forEach(function (b, bi) {
      var g = pr.growth[b], cell = cells[bi];
      var h = el("h3", "ss-mult-h");
      h.append(boardKey(b), document.createTextNode(BOARD_PL[b] + " (N = " + g.n + ")"));
      cell.append(h);
      if (!g.n) { cell.append(el("p", "ss-empty", tt("stats.fig.growth.none"))); return; }
      hbars(cell, { board: b, max: g.n, title: tt("stats.fig.growth.bars", { board: BOARD_PL[b] }),
        desc: tt("stats.fig.growth.bars_desc"),
        rows: [[tt("stats.fig.growth.grew"), g.grew, g.grew_median != null ? tt("stats.fig.growth.median_up", { v: nf.format(g.grew_median) }) : ""],
               [tt("stats.fig.growth.same"), g.same, ""], [tt("stats.fig.growth.fell"), g.recovered, g.recovered_median != null ? tt("stats.fig.growth.median_down", { v: nf.format(g.recovered_median) }) : ""]]
          .map(function (x) {
            return { label: x[0], value: x[1], low: !g.sufficient,
              valueText: x[1] + (g.sufficient ? " (" + nf.format(Math.round(1000 * x[1] / g.n) / 10) + " %)" : ""),
              tip: tt("stats.fig.growth.tip", { a: x[1], n: g.n, extra: x[2] ? ", " + x[2] : "" }) };
          }) });
      if (!g.sufficient) cell.append(warn(tt("stats.warn.small_raw2", { n: g.n, min: p.min_sample })));
    });
  }

  function trendSection(d, boards) {
    var tr = d.problems.trend, p = d.params;
    var f = figure({ title: tt("stats.fig.trend"), key: "se-imbunatateste-sau-se-inrautates",
      how: tt("stats.fig.trend.how", { n: tr.needed_days }) });
    if (tr.status !== "ok") {
      f.host.append(warn(tt("stats.fig.trend.insufficient", { days: tr.days, n: tr.needed_days })));
    } else {
      boards.forEach(function (b) {
        var dir = tr.direction[b];
        f.host.append(nLine(dir ? tt("stats.fig.trend.dir", { board: BOARD_PL[b], label: dir.label, sign: dir.diff_pp > 0 ? "+" : "", diff: nf.format(dir.diff_pp) })
          : tt("stats.fig.trend.few", { board: BOARD_PL[b] })));
      });
    }
    var byDate = {};
    boards.forEach(function (b) { (tr.boards[b] || []).forEach(function (r) { (byDate[r.date] = byDate[r.date] || {})[b] = r; }); });
    var dates = Object.keys(byDate).sort();
    var t = el("table", "ss-cmp ss-trend");
    t.append(el("caption", "sr-only", tt("stats.punctuality_by_day")));
    var hr = el("tr");
    hr.append(el("th", null, tt("stats.col.day")));
    boards.forEach(function (b) { var th = el("th"); th.scope = "col"; th.append(boardKey(b), document.createTextNode(tt("stats.fig.trend.board_ontime", { board: BOARD_PL[b] }))); hr.append(th); });
    var thead = el("thead");
    thead.append(hr);
    t.append(thead);
    var tb = el("tbody");
    dates.forEach(function (k) {
      var r = el("tr");
      var partial = boards.some(function (b) { return byDate[k][b] && byDate[k][b].partial; });
      var th = el("th", null, shortDay(k) + (partial ? tt("stats.fig.trend.partial") : ""));
      th.scope = "row";
      r.append(th);
      boards.forEach(function (b) {
        var x = byDate[k][b];
        r.append(el("td", null, x ? tt("stats.fig.compare.of", { a: x.on_time, n: x.n }) + (x.on_time_pct != null ? " (" + pct(x.on_time_pct) + ")" : "") : "—"));
      });
      tb.append(r);
    });
    t.append(tb);
    var wrap = el("div", "ss-cmp-wrap");
    wrap.append(t);
    f.foot.append(wrap);
    f.foot.append(nLine(tt("stats.fig.trend.foot", { min: p.min_sample })));
  }

  function resetFilters() {
    v.p = { perioada: "all", board: "", operator: "", tip: "", doar_confirmate: "" };
    v.sect = "";
    setForm(v.p);
    syncHash(v.p);
    load();
  }

  // chip click -> ?sect= in the address
  function tocSect() {
    var nav = v.ui.body.__c3nav;
    if (!nav) return;
    var map = {};
    map[tt("charts.toc.problems")] = "probleme";
    map[tt("charts.toc.good")] = "bune";
    nav.querySelectorAll(".c3-chip").forEach(function (b) {
      var k = map[b.textContent];
      if (k) b.addEventListener("click", function () { v.sect = k; syncHash(v.p); });
    });
  }

  function render(d) {
    seq = 0;
    v.ui.body.replaceChildren();
    v.ui.body.classList.toggle("ss-no-motion", !!reduceMotion);
    var boards = boardsOf(d);
    renderSummary(d);
    syncFiltersH();
    if (!d.coverage || !d.coverage.journeys) {
      summary(d);
      var msg = tt("stats.empty.none");
      var filtered = !!(v.p && (v.p.perioada !== "all" || v.p.board || v.p.operator || v.p.tip || v.p.doar_confirmate));
      if (U() && U().empty) {
        v.ui.body.append(U().empty({ art: "search", title: tt("stats.empty.title"), text: msg,
          action: filtered ? { label: tt("stats.empty.clear"), run: resetFilters } : null }));
      } else v.ui.body.append(el("p", "empty ss-empty", msg));
      glossary(d);
      return;
    }
    if (d.problems) {
      problemsSection(d);
      goodSection(d);
      if (d.problems.status === "ok") {
        sectionHeading(tt("stats.part.details"), tt("stats.part.details_sub"));
        recurrentSection(d);
        windowsSection(d, boards);
        compareSection(d, boards);
        bigSection(d, boards);
        problemRoutesSection(d, boards);
        growthSection(d, boards);
        if (App.statSteps) App.statSteps.render(d, boards, { el: el, nf: nf, figure: figure, multiples: multiples, hbars: hbars, nLine: nLine, warn: warn, boardKey: boardKey, hashLink: hashLink, dataTable: dataTable });
        trendSection(d, boards);
      }
      sectionHeading(tt("stats.part.charts"), tt("stats.part.charts_sub"));
    }
    if (d.coverage.journeys && U()) heroStrip(d, boards);
    summary(d);
    kpis(d, boards);
    distributionSection(d, boards);
    shareSection(d, boards);
    dailySection(d, boards);
    calendarSection(d, boards);
    hourlySection(d, boards);
    heatmapSection(d, boards);
    if (App.statWeekdays) App.statWeekdays.section(d, boards, { figure: figure, el: el, nLine: nLine });
    rankedSection(d, boards, "operators", tt("stats.fig.operators"), tt("stats.fig.operators.how"), "operators", tt("stats.share.operator"),
      "care-operatori-sunt-cei-mai-punctu");
    rankedSection(d, boards, "types", tt("stats.fig.types"), tt("stats.fig.types.how"), "types", tt("stats.filters.train_type"),
      "ce-tipuri-de-tren-sunt-mai-punctua");
    routesSection(d, boards);
    weatherSection(d);
    trafficSection(d, boards);
    platformsSection(d, boards);
    (App.statsExtra || []).forEach(function (x) { x(v.ui.body, v.p); });   // stat_platform.js, stat_dwell.js
    qualitySection(d);
    glossary(d);
    if (U()) {
      U().stagger(v.ui.body.querySelector(".ss-prob-list"));
      U().reveal(v.ui.body);
    }
    if (C3()) {
      C3().enhance(v.ui.body, { url: chartUrl });
      C3().toc(v.ui.body);
      tocSect();
    }
  }

  // RO/EN switch: the filter labels and every chart are drawn again in the new language
  document.addEventListener("i18n:change", function () {
    if (!v.ui) return;
    var p = v.p, wasShown = !!($("view-statistici") && !$("view-statistici").hidden);
    v.ui = null;
    v.data = null;
    v.key = null;
    if (v.ctrl) { v.ctrl.abort(); v.ctrl = null; }
    if (wasShown && p) show(new URLSearchParams(query(p)));
  });

  App.views.statistici = { show: show };
})();
