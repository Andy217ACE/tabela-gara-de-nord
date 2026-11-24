// © 2026 Andy217Ace
// Tabela Gara de Nord — Trenuri (#trenuri), profil tren (#tren?nr=), Clasamente (#clasamente), Stații (#statii) și pagina unei stații
// (#statie?nume=). Data: /api/trains/stats, /api/trains/{no}/journeys, /api/stats,
// /api/stats/rankings, /api/stations, /api/stations/{name}[/journeys]. Every delay is the one READ on the București Nord board;
// arrivals and departures are never mixed; a missing value is shown as „—”, never 0; N is
// shown next to every statistic. DOM via createElement/textContent, charts via
// createElementNS + classes from stats.css (no inline styles: CSP).
"use strict";

(function () {
  var App = window.TabelaApp;
  var el = App.el;
  var SVG_NS = "http://www.w3.org/2000/svg";
  var TIMEOUT_MS = 15000;
  var DEBOUNCE_MS = 400;
  var BOARDS = ["arrival", "departure"];
  var tt = function (k, p) { return window.I18N.t(k, p); };
  function lazy(prefix, keys) {   // getters: the text follows the language chosen at the time it is read
    var o = {};
    keys.forEach(function (k) { Object.defineProperty(o, k, { enumerable: true, get: function () { return tt(prefix + k); } }); });
    return o;
  }
  var BOARD_PL = lazy("stats.board.", ["arrival", "departure"]);
  var BOARD_ONE = lazy("stats.board_one.", ["arrival", "departure"]);
  var BOARD_DIR = lazy("stats.dirword.", ["arrival", "departure"]);
  var STATE_TEXT = lazy("stats.states.", ["confirmed", "unconfirmed", "unknown", "in_progress"]);
  var STATE_CLASS = { confirmed: "res-confirmed", unconfirmed: "res-unconfirmed",
                      unknown: "res-unknown", in_progress: "res-progress" };
  var monthFmt = {};
  function monthName(i) {   // short month name in the chosen language (Intl, not a Romanian list)
    var l = window.I18N.lang();
    monthFmt[l] = monthFmt[l] || new Intl.DateTimeFormat(l, { month: "short", timeZone: "UTC" });
    return monthFmt[l].format(new Date(Date.UTC(2000, i, 1)));
  }

  var $ = function (id) { return document.getElementById(id); };
  var H = function () { return App.history || {}; };
  var U = function () { return App.ui2; };   // Beta 1.26 visual helpers (ui2.js)
  var C3 = function () { return App.charts3; };   // Beta 1.28 interactive chart layer (charts3.js, lazy)

  // 14-day sparkline of a row (`trend`: mean read delay per day, null = not read); one scale per table; < 2 read days = „—”
  function trendMax(list) {
    var all = [];
    (list || []).forEach(function (e) {
      ((e.trend && e.trend.values) || []).forEach(function (x) { if (x != null) all.push(x); });
    });
    if (!all.length) return 5;
    all.sort(function (a, b) { return a - b; });
    // 90th percentile (min 5): one extreme day must not flatten the rows; higher values are clipped
    return Math.max(5, all[Math.min(all.length - 1, Math.floor(all.length * 0.9))]);
  }
  function dayShort(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
    return m ? parseInt(m[3], 10) + "." + m[2] : String(iso || "");
  }
  function trendText(t) {
    return tt("stats.trend.text", { days: t.days, last: dayShort(t.last), list: t.values.map(function (x) { return x == null ? tt("stats.unread") : minutes(x); }).join(", ") });
  }
  function trendCell(trend, hi, o) {
    var c = el("span", "st-spark-cell");
    var read = trend && trend.values ? trend.values.filter(function (x) { return x != null; }).length : 0;
    if (!U() || read < 2) {
      c.textContent = "—";
      c.classList.add("ui-spark-none");
      c.title = tt("stats.trend.few");
      return c;
    }
    c.append(U().spark(trend.values, Object.assign({ w: 84, h: 24, compact: true, tone: "bad", min: 0, max: hi, label: trendText(trend) }, o || {})));
    return c;
  }

  // pooled on-time figure → hero tile (honest: N next to it; „—” below the minimum sample)
  function onTimeTile(label, tone, st, params) {
    var ok = st && st.n && st.sufficient;
    return { label: label, tone: tone, gauge: true, value: ok ? st.on_time_pct : null, unit: ok ? " %" : "",
      fmt: function (x) { return numFmt.format(Math.round(x * 10) / 10); },
      sub: ok ? tt("stats.tile.sub", { a: st.on_time, n: st.n, max: params.on_time_max_min })
        : (st && st.n ? tt("stats.hero.small_sub", { n: st.n, min: params.min_sample }) : "N = 0"),
      meter: ok ? st.on_time_pct : null };
  }
  function heroBlock(v, items) {
    if (!U()) return;
    var sec = el("section", "st-hero");
    sec.setAttribute("aria-label", tt("stats.hero.aria"));
    sec.append(U().hero(items));
    v.body.prepend(sec);
  }

  // ---- formatting --------------------------------------------------------------------

  // Intl with the chosen language: English 12.5, Romanian 12,5 (one formatter per language, built on first use)
  var nfCache = {};
  var numFmt = { format: function (x) {
    var l = window.I18N.lang();
    nfCache[l] = nfCache[l] || new Intl.NumberFormat(l, { maximumFractionDigits: 1 });
    return nfCache[l].format(x);
  } };

  function num(v) { return v == null ? "—" : numFmt.format(v); }
  function minutes(v) { return v == null ? "—" : tt("stats.fmt.min", { v: numFmt.format(v) }); }
  function pct(v) { return v == null ? "—" : tt("stats.fmt.pct", { v: numFmt.format(v) }); }

  function pl(n, base) { return plural(n, tt(base + ".one"), tt(base + ".many")); }

  function plural(n, one, many) {
    if (window.I18N.lang() === "en") return n === 1 ? "1 " + one : numFmt.format(n) + " " + many;
    var p = H().plural;
    if (typeof p === "function") return p(n, one, many);
    return n === 1 ? "1 " + one : n + " " + many;
  }

  function titleCase(s) {
    var t = H().titleCase;
    return typeof t === "function" ? t(s) : String(s || "");
  }

  function dayText(iso) {
    if (!iso) return "—";
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
    return m ? parseInt(m[3], 10) + " " + monthName(parseInt(m[2], 10) - 1) + " " + m[1] : iso;
  }

  function monthText(key) {
    var m = /^(\d{4})-(\d{2})$/.exec(String(key));
    return m ? monthName(parseInt(m[2], 10) - 1) + " " + m[1] : String(key);
  }

  function period(first, last) {
    if (!first) return "—";
    return first === last ? dayText(first) : dayText(first) + " – " + dayText(last);
  }

  // ---- shared nodes ------------------------------------------------------------------

  function stationLink(name, uncertain) {
    if (!name) return el("span", null, "—");
    // the station page (#statie) ships separately: until its view exists, plain text
    if (!(window.TabelaApp.views && window.TabelaApp.views.statie)) {
      return el("span", uncertain ? "station-name is-uncertain" : "station-name", titleCase(name));
    }
    var a = el("a", "station-link", titleCase(name));
    a.href = "#statie?nume=" + encodeURIComponent(name);
    if (uncertain) {
      a.classList.add("is-uncertain");
      a.title = tt("stats.uncertain_reading");
    }
    return a;
  }

  function trainLink(e) {
    var a = el("a", "st-train");
    a.href = "#tren?nr=" + encodeURIComponent(e.train_no);
    a.append(el("span", App.typeClass(e.train_type), App.typeAbbr(e.train_type) || "?"),
             el("span", "t-no", String(e.train_no)));
    a.setAttribute("aria-label", tt("stats.train_aria", { t: (e.train_type || "") + " " + e.train_no }));
    return a;
  }

  function resultBadge(r) {
    var f = H().resultBadge;
    if (typeof f === "function") return f(r);
    return el("span", "res-badge", (r && r.label) || tt("stats.unknown_lc"));
  }

  function exportLink(text, url, csv) {
    var a = el("a", "btn btn-ghost btn-sm st-export", text);
    a.href = url;
    if (csv) a.setAttribute("download", "");
    else { a.target = "_blank"; a.rel = "noopener"; }
    return a;
  }

  function notice(text, cls) { return el("p", "notice" + (cls ? " " + cls : ""), text); }

  // list pages: „Nu am putut încărca …” + the reason + a retry button (a refetch of the same URL)
  function loadFailed(v, what, e) {
    var box = el("div", "st-error");
    box.append(notice(tt("stats.err.load", { what: what, why: errorText(e) }), "notice-error"));
    var b = el("button", "btn btn-ghost btn-sm st-retry", tt("stats.err.retry"));
    b.type = "button";
    b.addEventListener("click", function () { v.load(true); });
    box.append(b);
    return box;
  }

  // Small sample: means are shown, percentages and p90 are not (API `sufficient=false`).
  function sampleWarn(s, params) {
    if (!s) return null;
    var min = params && params.min_sample != null ? params.min_sample : "?";
    if (!s.n) {
      return el("p", "st-warn", tt("stats.sample.none"));
    }
    if (s.sufficient === false) {
      return el("p", "st-warn", tt("stats.sample.small", { n: s.n, min: min }));
    }
    return null;
  }

  function statItem(dl, label, value, sub) {
    var box = el("div", "st-stat");
    var dt = el("dt", null, label);
    var dd = el("dd", null, value);
    if (sub) dd.append(el("span", "st-stat-sub", sub));
    box.append(dt, dd);
    dl.append(box);
  }

  function statsGrid(s, params) {
    var dl = el("dl", "st-grid");
    var prag = params && params.on_time_max_min != null ? params.on_time_max_min : "?";
    s = s || {};
    statItem(dl, tt("stats.grid.n"), s.n == null ? "—" : String(s.n));
    statItem(dl, tt("stats.kpi.mean"), minutes(s.mean));
    statItem(dl, tt("stats.kpi.median"), minutes(s.median));
    statItem(dl, "p90", minutes(s.p90));
    statItem(dl, tt("stats.kpi.max"), minutes(s.max));
    statItem(dl, tt("stats.grid.ontime", { max: prag }), pct(s.on_time_pct),
             s.n ? tt("stats.fig.compare.of", { a: s.on_time, n: s.n }) : null);
    statItem(dl, tt("stats.kpi.over30"), pct(s.over_30_pct), s.n ? tt("stats.fig.compare.of", { a: s.over_30, n: s.n }) : null);
    return dl;
  }

  function qualityLine(q) {
    if (!q) return el("p", "st-quality", tt("stats.quality.unknown"));
    var st = q.states || {};
    return el("p", "st-quality",
      tt("stats.quality.line", { j: pl(q.journeys || 0, "stats.w.journey"), fin: q.finished || 0, dk: q.delay_known || 0, pct: pct(q.delay_known_pct),
        c: st.confirmed || 0, u: st.unconfirmed || 0, k: st.unknown || 0, p: st.in_progress || 0 }));
  }

  // ---- SVG bar chart -----------------------------------------------------------------

  function svg(tag, attrs, text) {
    var n = document.createElementNS(SVG_NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, String(attrs[k])); });
    if (text != null) n.textContent = text;
    return n;
  }

  function niceMax(v) {
    var steps = [1, 2, 5, 10, 15, 30, 60, 120, 240, 500, 1000, 2000, 5000, 10000];
    for (var i = 0; i < steps.length; i++) {
      if (Math.max(v, 1) / steps[i] <= 4) return { step: steps[i], max: Math.max(steps[i], Math.ceil(v / steps[i]) * steps[i]) };
    }
    var s = Math.pow(10, Math.ceil(Math.log10(v / 4)));
    return { step: s, max: Math.ceil(v / s) * s };
  }

  var chartSeq = 0;

  // o: {host, items:[{label, value|null, n, low, tip}], title, desc, unit, minWidth, showN}
  function barChart(o) {
    var hostW = o.host && o.host.clientWidth ? o.host.clientWidth - 30 : 600;
    var W = Math.round(Math.max(o.minWidth || 280, Math.min(960, hostW)));
    var Hh = 190, L = 38, R = 8, T = 20, B = o.showN ? 42 : 26;
    var items = o.items;
    var vals = items.map(function (it) { return it.value == null ? 0 : it.value; });
    var ys = niceMax(Math.max.apply(null, vals.concat([0])));
    var band = (W - L - R) / Math.max(1, items.length);
    var bw = Math.max(3, Math.min(48, band * 0.68));
    var x = function (i) { return L + band * i + band / 2; };
    var y = function (v) { return T + (1 - Math.max(0, v) / ys.max) * (Hh - T - B); };
    var id = "st-chart-" + (++chartSeq);

    var root = svg("svg", { viewBox: "0 0 " + W + " " + Hh, width: W, height: Hh, class: "st-chart",
                            role: "img", "aria-labelledby": id + "-t " + id + "-d", "data-kind": "col",
                            "data-plot": [L, T, W - R, Hh - B].join(","), "data-n": items.length });
    root.append(svg("title", { id: id + "-t" }, o.title));
    root.append(svg("desc", { id: id + "-d" }, o.desc));
    var grid = svg("g", { class: "st-grid-lines" });
    for (var v = 0; v <= ys.max; v += ys.step) {
      grid.append(svg("line", { x1: L, x2: W - R, y1: y(v), y2: y(v) }));
      grid.append(svg("text", { x: L - 6, y: y(v) + 4, class: "st-ylabel" }, String(v)));
    }
    if (o.unit) grid.append(svg("text", { x: L - 6, y: 11, class: "st-ylabel" }, o.unit));
    root.append(grid);

    var every = band < 22 ? Math.ceil(22 / band) : 1;
    items.forEach(function (it, i) {
      var g = svg("g", { class: "st-bar-g", "data-i": i, "data-s": 0 });
      var cx = x(i);
      if (it.value != null) {
        var top = y(it.value);
        var h = Math.max(it.value > 0 ? 1.5 : 0, (Hh - B) - top);
        g.append(svg("rect", { x: (cx - bw / 2).toFixed(1), y: ((Hh - B) - h).toFixed(1), width: bw.toFixed(1),
                               height: h.toFixed(1), rx: 2, class: "st-bar" + (it.low ? " st-bar-low" : "") }));
        if (band >= 18) {
          g.append(svg("text", { x: cx, y: ((Hh - B) - h - 4).toFixed(1), class: "st-vlabel" },
                       it.valueText != null ? it.valueText : num(it.value)));
        }
      } else if (band >= 14) {
        g.append(svg("text", { x: cx, y: Hh - B - 4, class: "st-vlabel st-vnone" }, "—"));
      }
      if (i % every === 0) {
        g.append(svg("text", { x: cx, y: Hh - B + 14, class: "st-xlabel" }, it.label));
      }
      if (o.showN) {
        g.append(svg("text", { x: cx, y: Hh - B + 30, class: "st-nlabel" }, String(it.n == null ? "—" : it.n)));
      }
      g.append(svg("title", {}, it.tip || (it.label + ": " + (it.value == null ? "—" : num(it.value)))));
      root.append(g);
    });
    root.append(svg("line", { x1: L, x2: W - R, y1: Hh - B, y2: Hh - B, class: "st-axis" }));
    if (o.showN) root.append(svg("text", { x: 4, y: Hh - B + 30, class: "st-nlabel st-nlabel-head" }, "N"));
    var wrap = el("div", "st-chart-scroll");
    wrap.append(root);
    return wrap;
  }

  function distChart(host, dist, board) {
    var items = (dist || []).map(function (b) {
      return { label: b.label, value: b.n, n: b.n, valueText: String(b.n),
               tip: tt("stats.chart.dist_tip", { label: b.label, j: pl(b.n, "stats.w.journey") }) };
    });
    var total = items.reduce(function (a, b) { return a + (b.n || 0); }, 0);
    return barChart({ host: host, items: items, minWidth: 280,
      title: tt("stats.chart.dist_title", { board: BOARD_PL[board] }),
      desc: tt("stats.chart.dist_desc", { n: total }) });
  }

  // ---- fetch -------------------------------------------------------------------------

  function getJSON(url, ctrl) {
    var to = setTimeout(function () { ctrl.timedOut = true; ctrl.abort(); }, TIMEOUT_MS);
    return fetch(url, { signal: ctrl.signal, cache: "no-store", headers: { Accept: "application/json" } })
      .then(function (r) {
        return r.json().catch(function () { return null; }).then(function (body) {
          if (!r.ok) {
            var err = new Error("http");
            err.status = r.status;
            err.detail = body && typeof body.detail === "string" ? body.detail : null;
            throw err;
          }
          return body;
        });
      }, function () {
        var err = new Error("network");
        err.aborted = ctrl.signal.aborted && !ctrl.timedOut;
        err.offline = true;
        throw err;
      })
      .finally(function () { clearTimeout(to); });
  }

  function errorText(e) {
    if (e.offline) {
      return navigator.onLine === false ? tt("stats.err.offline")
        : tt("stats.err.noreply");
    }
    if (e.status === 422 || e.status === 404) return e.detail || tt("stats.err.params");
    if (e.status === 429) return tt("stats.err.rate");
    return tt("stats.err.server", { s: e.status || "?" });
  }

  // ---- parameters (persisted in the URL hash) ----------------------------------------

  var FIELD_DEFS = {
    query: { get label() { return tt("stats.f.query"); }, type: "search", get placeholder() { return tt("stats.f.query_ph"); }, max: 40 },
    board: { get label() { return tt("stats.f.board"); }, type: "select" },
    from: { get label() { return tt("stats.f.from"); }, type: "date" },
    to: { get label() { return tt("stats.f.to"); }, type: "date" },
    prag: { get label() { return tt("stats.f.prag"); }, type: "number", lo: 0, hi: 60, placeholder: "5" },
    min: { get label() { return tt("stats.f.min"); }, type: "number", lo: 1, hi: 1000, placeholder: "5" },
    doar_confirmate: { get label() { return tt("stats.f.confirmed"); }, type: "checkbox" },
    q: { get label() { return tt("stats.f.q"); }, type: "search", get placeholder() { return tt("stats.f.q_ph"); }, max: 40 }
  };

  function clean(field, raw) {
    var v = (raw == null ? "" : String(raw)).trim();
    var d = FIELD_DEFS[field];
    if (!v) return "";
    if (d.type === "number") {
      if (!/^\d{1,4}$/.test(v)) return "";
      var n = parseInt(v, 10);
      return n >= d.lo && n <= d.hi ? String(n) : "";
    }
    if (d.type === "date") return /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : "";
    if (field === "board") return v === "arrival" || v === "departure" ? v : "";
    if (field === "doar_confirmate") return v === "1" ? "1" : "";
    return v.slice(0, d.max || 40);
  }

  function readParams(params, fields) {
    var p = {};
    fields.forEach(function (f) { p[f] = clean(f, params.get(f)); });
    return p;
  }

  function toSearch(p, fields) {
    var s = new URLSearchParams();
    fields.forEach(function (f) { if (p[f]) s.set(f, p[f]); });
    return s;
  }

  function syncHash(base, p, fields, extra) {
    // identity first (#statie?nume=…&board=…), then the filters
    var s = new URLSearchParams();
    Object.keys(extra || {}).forEach(function (k) { s.set(k, extra[k]); });
    toSearch(p, fields).forEach(function (val, k) { s.set(k, val); });
    var q = s.toString();
    var hash = "#" + base + (q ? "?" + q : "");
    if (location.hash !== hash) history.replaceState(null, "", hash);
  }

  // Filter form; `onChange(p)` after a debounced edit. Returns {form, set(p)}.
  function controls(id, fields, onChange) {
    var form = el("form", "st-filters");
    form.setAttribute("role", "search");
    form.setAttribute("aria-label", tt("stats.f.aria"));
    form.noValidate = true;
    var inputs = {};
    var timer = null;
    fields.forEach(function (f) {
      var d = FIELD_DEFS[f];
      var lab = el("label", "field st-field st-field-" + f.replace("_", "-"));
      var input;
      if (d.type === "select") {
        input = el("select");
        [["", tt("stats.f.both_sep")], ["arrival", tt("stats.board.arrival")], ["departure", tt("stats.board.departure")]].forEach(function (o) {
          var opt = el("option", null, o[1]);
          opt.value = o[0];
          input.append(opt);
        });
      } else {
        input = el("input");
        input.type = d.type === "number" ? "number" : d.type;
        if (d.type === "number") {
          input.min = String(d.lo);
          input.max = String(d.hi);
          input.inputMode = "numeric";
        }
        if (d.placeholder) input.placeholder = d.placeholder;
        if (d.max) input.maxLength = d.max;
        input.autocomplete = "off";
      }
      input.id = id + "-" + f;
      input.name = f;
      inputs[f] = input;
      if (d.type === "checkbox") {
        lab.classList.add("st-check");
        lab.append(input, el("span", null, d.label));
      } else {
        lab.append(el("span", "field-label", d.label), input);
      }
      form.append(lab);
    });
    function read() {
      var p = {};
      fields.forEach(function (f) {
        var i = inputs[f];
        p[f] = FIELD_DEFS[f].type === "checkbox" ? (i.checked ? "1" : "") : clean(f, i.value);
      });
      return p;
    }
    function fire() { clearTimeout(timer); timer = setTimeout(function () { onChange(read()); }, DEBOUNCE_MS); }
    form.addEventListener("input", fire);
    form.addEventListener("change", fire);
    form.addEventListener("submit", function (e) { e.preventDefault(); clearTimeout(timer); onChange(read()); });
    return {
      form: form,
      set: function (p) {
        fields.forEach(function (f) {
          var i = inputs[f];
          if (FIELD_DEFS[f].type === "checkbox") i.checked = p[f] === "1";
          else if (document.activeElement !== i && clean(f, i.value) !== (p[f] || "")) i.value = p[f] || "";
        });
      }
    };
  }

  function explainParams(params) {
    if (!params) return "";
    return tt("stats.explain", { max: params.on_time_max_min, min: params.min_sample,
      conf: params.confirmed_only ? tt("stats.explain.conf") : "",
      board: params.board ? tt("stats.explain.board", { b: BOARD_PL[params.board].toLowerCase() }) : "",
      period: params.from || params.to ? tt("stats.explain.period", { a: params.from ? dayText(params.from) : tt("stats.explain.start"),
        b: params.to ? dayText(params.to) : tt("stats.explain.today") }) : "" });
  }

  // Generic view: a persistent filter form + a body re-rendered from one API call.
  function makeView(cfg) {
    var v = { p: null, ctrl: null, ui: null, body: null, key: null, data: null };
    var paint = function () { if (cfg.charts && C3()) C3().enhance(v.body); };
    function ensure() {
      if (v.ui) return;
      var root = $(cfg.root);
      v.ui = controls(cfg.root, cfg.fields, function (p) {
        v.p = Object.assign({}, v.p, p);
        syncHash(cfg.route, v.p, cfg.fields, cfg.hashExtra ? cfg.hashExtra(v) : null);
        load();
      });
      v.body = el("div", "st-body");
      root.replaceChildren(v.ui.form, v.body);
    }
    function load(force) {
      var url = cfg.url(v);
      if (!url) return;
      if (!force && url === v.key && v.data) {
        if (!v.body.firstChild) v.rerender();   // back after hide(): the cached data, drawn again
        return;
      }
      v.key = url;
      if (v.ctrl) v.ctrl.abort();
      var ctrl = new AbortController();
      v.ctrl = ctrl;
      $(cfg.root).classList.add("is-loading");
      if (!v.data) {
        v.body.replaceChildren(el("p", "sr-only", tt("stats.loading_short")));
        if (U()) v.body.append(U().skeleton("hero", 3), U().skeleton("table", 6));
      }
      var ready = cfg.charts && U() && U().charts ? U().charts() : Promise.resolve(null);   // charts3.js only where there are charts
      getJSON(url, ctrl)
        .then(function (data) { return ready.then(function () { return data; }); })
        .then(function (data) {
          if (v.ctrl !== ctrl) return;
          v.data = data;
          v.body.replaceChildren();
          cfg.render(v, data);
          paint();
          if (U()) U().reveal(v.body);
        })
        .catch(function (e) {
          if (v.ctrl !== ctrl || e.aborted) return;
          v.data = null;
          v.key = null;
          v.body.replaceChildren(cfg.errorNode ? cfg.errorNode(v, e)
            : notice(cfg.errorText ? cfg.errorText(e) : errorText(e), "notice-error"));
          if (cfg.onError) cfg.onError(v, e);
        })
        .then(function () {
          if (v.ctrl === ctrl) { v.ctrl = null; $(cfg.root).classList.remove("is-loading"); }
        });
    }
    v.load = load;
    v.url = function () { return cfg.url(v); };
    v.show = function (params) {
      window.I18N.ready.then(function () {   // the dictionary must be loaded before the first labels are drawn
        ensure();
        v.p = readParams(params, cfg.fields);
        if (cfg.onParams) cfg.onParams(v, params);
        v.ui.set(v.p);
        if (cfg.title) cfg.title(v);
        load(false);
      });
    };
    v.relang = function () {   // RO/EN switch: new filter labels + the same data drawn again in the new language
      if (!v.ui) return;
      v.ui = null;
      ensure();
      v.ui.set(v.p);
      if (cfg.title) cfg.title(v);
      v.rerender();
    };
    v.rerender = function () { if (v.data) { v.body.replaceChildren(); cfg.render(v, v.data); paint(); if (U()) U().reveal(v.body); } };
    // leaving the page: drop its DOM (the data stays cached; show() draws it again)
    v.hide = function () {
      if (v.ctrl) { v.ctrl.abort(); v.ctrl = null; v.key = null; }
      $(cfg.root).classList.remove("is-loading");
      $(cfg.root).replaceChildren();
      v.ui = null;
      v.body = null;
    };
    return v;
  }

  // ---- table helpers -----------------------------------------------------------------

  function scrollTable(caption) {
    var wrap = el("div", "st-scroll");
    wrap.tabIndex = 0;
    wrap.setAttribute("role", "region");
    wrap.setAttribute("aria-label", caption);
    var table = el("table", "st-table");
    table.append(el("caption", "sr-only", caption));
    wrap.append(table);
    return { wrap: wrap, table: table };
  }

  function td(tr, content, cls) {
    var c = el("td", cls);
    if (content == null) c.textContent = "—";
    else if (typeof content === "string") c.textContent = content;
    else c.append(content);
    tr.append(c);
    return c;
  }

  // ---- #trenuri ----------------------------------------------------------------------

  var TR_FIELDS = ["query", "prag", "min", "doar_confirmate"];
  var trSort = { key: "journeys", dir: -1 };
  var trHi = 5;    // common scale of the 14-day sparklines of the table being drawn
  var TR_PAGE = 50;   // rows drawn at once (the whole list stays in memory: sorting and the counts use all of it)

  var TR_COLS = [
    { key: "train_no", get label() { return tt("stats.c.train"); }, get: function (e) { return e.train_no; },
      cell: function (e) { return trainLink(e); }, cls: "st-c-train" },
    { key: "board", get label() { return tt("stats.c.board"); }, get: function (e) { return e.board; },
      cell: function (e) { return BOARD_ONE[e.board] || e.board; } },
    { key: "station", get label() { return tt("stats.c.station"); }, get: function (e) { return e.station || ""; },
      cell: function (e) {
        var s = el("span", "st-station");
        s.append(stationLink(e.station));
        if (e.stations && e.stations.length > 1) {
          var more = el("span", "st-more", " +" + (e.stations.length - 1));
          more.title = e.stations.map(titleCase).join(", ");
          s.append(more);
        }
        return s;
      } },
    { key: "journeys", get label() { return tt("stats.c.journeys"); }, num: true, get: function (e) { return e.journeys; },
      cell: function (e) { return String(e.journeys); } },
    { key: "n", get label() { return tt("stats.c.n_read"); }, num: true, get: function (e) { return e.stats.n; },
      cell: function (e) { return String(e.stats.n); } },
    { key: "on_time_pct", get label() { return tt("stats.c.ontime"); }, num: true, get: function (e) { return e.stats.on_time_pct; },
      cell: function (e) {
        var p = e.stats.on_time_pct;
        if (p == null || !U()) return pct(p);
        var c = el("span", "st-cell-meter", pct(p));
        var m = U().meter(p, { tone: p >= 90 ? "ok" : p >= 70 ? "mid" : "bad", label: tt("stats.ontime_aria", { v: pct(p) }) });
        m.classList.add("st-meter");
        c.append(m);
        return c;
      } },
    { key: "trend", get label() { return tt("stats.c.last14"); }, nosort: true, get: function () { return null; },
      cell: function (e) { return trendCell(e.trend, trHi); } },
    { key: "mean", get label() { return tt("stats.c.mean"); }, num: true, get: function (e) { return e.stats.mean; },
      cell: function (e) { return minutes(e.stats.mean); } },
    { key: "median", get label() { return tt("stats.c.median"); }, num: true, get: function (e) { return e.stats.median; },
      cell: function (e) { return minutes(e.stats.median); } },
    { key: "p90", label: "p90", num: true, get: function (e) { return e.stats.p90; },
      cell: function (e) { return minutes(e.stats.p90); } },
    { key: "max", get label() { return tt("stats.c.max"); }, num: true, get: function (e) { return e.stats.max; },
      cell: function (e) { return minutes(e.stats.max); } },
    { key: "over_30", get label() { return tt("stats.c.over30"); }, num: true, get: function (e) { return e.stats.over_30; },
      cell: function (e) {
        return e.stats.n ? e.stats.over_30 + (e.stats.over_30_pct != null ? " (" + pct(e.stats.over_30_pct) + ")" : "") : "—";
      } },
    { key: "quality", get label() { return tt("stats.c.quality"); }, num: true,
      get: function (e) { return e.quality.delay_known_pct; },
      cell: function (e) {
        var q = e.quality;
        var s = el("span", "st-q", tt("stats.q.read", { v: pct(q.delay_known_pct) }));
        s.append(el("span", "st-q-sub", tt("stats.q.conf", { n: q.states.confirmed || 0 })));
        s.title = tt("stats.q.title", { dk: q.delay_known, fin: q.finished, c: q.states.confirmed || 0 });
        return s;
      } }
  ];

  // a percentage with a thin bar under it (list rows); „—” stays „—”
  function pctMeter(p) {
    if (p == null || !U()) return pct(p);
    var c = el("span", "st-cell-meter", pct(p));
    var m = U().meter(p, { tone: p >= 90 ? "ok" : p >= 70 ? "mid" : "bad", label: tt("stats.ontime_aria", { v: pct(p) }) });
    m.classList.add("st-meter");
    c.append(m);
    return c;
  }

  function sortEntries(list) {
    var col = TR_COLS.filter(function (c) { return c.key === trSort.key; })[0] || TR_COLS[3];
    return list.slice().sort(function (a, b) {
      var x = col.get(a), y = col.get(b);
      if (x == null && y == null) return a.train_no - b.train_no;
      if (x == null) return 1;   // missing values last, whatever the direction
      if (y == null) return -1;
      if (x < y) return -trSort.dir;
      if (x > y) return trSort.dir;
      return a.train_no - b.train_no || (a.board < b.board ? -1 : 1);
    });
  }

  function renderTrains(v, d) {
    var list = Array.isArray(d.trains) ? d.trains : [];
    var params = d.params || {};
    if (!list.length && !v.p.query) {
      v.body.append(el("p", "empty", tt("stats.tr.none")));
      return;
    }
    var totalJ = list.reduce(function (a, e) { return a + (e.journeys || 0); }, 0);
    var small = list.filter(function (e) { return e.stats && e.stats.sufficient === false; }).length;

    var head = el("div", "st-bar-head");
    head.append(el("p", "h-count", tt("stats.tr.count", { rows: pl(list.length, "stats.w.row"), j: pl(totalJ, "stats.w.journey"), explain: explainParams(params) })));
    var q = toSearch(v.p, TR_FIELDS);
    var exp = el("div", "st-exports");
    q.set("format", "csv");
    exp.append(exportLink(tt("stats.export.csv"), "/api/trains/stats?" + q.toString(), true));
    q.delete("format");
    exp.append(exportLink("JSON", "/api/trains/stats" + (q.toString() ? "?" + q.toString() : ""), false));
    head.append(exp);
    v.body.append(head);

    var pooled = list.reduce(function (a, e) {
      a.n += (e.stats && e.stats.n) || 0;
      a.on_time += (e.stats && e.stats.on_time) || 0;
      a.over_30 += (e.stats && e.stats.over_30) || 0;
      return a;
    }, { n: 0, on_time: 0, over_30: 0 });
    pooled.sufficient = pooled.n >= (params.min_sample || 5);
    pooled.on_time_pct = pooled.n ? Math.round(1000 * pooled.on_time / pooled.n) / 10 : null;
    if (list.length) {
      heroBlock(v, [
        { label: tt("stats.tr.hero.rows"), value: list.length, sub: pl(totalJ, "stats.w.journey") },
        onTimeTile(tt("stats.tr.hero.ontime"), "arr", pooled, params),
        { label: tt("stats.tr.hero.enough"), value: list.length - small, sub: tt("stats.tr.hero.of_rows", { n: list.length, min: params.min_sample }) },
        { label: tt("stats.kpi.over30"), value: pooled.n ? pooled.over_30 : null, tone: "bad",
          sub: pooled.n ? tt("stats.tr.hero.of_read", { n: pooled.n }) : "N = 0" }]);
    }
    v.body.append(el("p", "st-note",
      tt("stats.tr.note")));
    if (small) {
      v.body.append(el("p", "st-warn", tt("stats.tr.small", { a: small, n: list.length, min: params.min_sample })));
    }
    if (!list.length) {
      v.body.append(el("p", "empty", tt("stats.tr.nomatch")));
      return;
    }

    trHi = trendMax(list);
    var t = scrollTable(tt("stats.tr.table"));
    var thead = el("thead");
    var hr = el("tr");
    TR_COLS.forEach(function (c) {
      var th = el("th", c.num ? "st-num" : null);
      th.scope = "col";
      if (c.nosort) { th.textContent = c.label; th.title = tt("stats.tr.same_scale"); hr.append(th); return; }
      var b = el("button", "st-sort", c.label);
      b.type = "button";
      if (trSort.key === c.key) {
        th.setAttribute("aria-sort", trSort.dir > 0 ? "ascending" : "descending");
        b.append(el("span", "st-sort-ind", trSort.dir > 0 ? " ▲" : " ▼"));
      }
      b.addEventListener("click", function () {
        if (trSort.key === c.key) trSort.dir = -trSort.dir;
        else { trSort.key = c.key; trSort.dir = c.num ? -1 : 1; }
        v.rerender();
      });
      th.append(b);
      hr.append(th);
    });
    thead.append(hr);
    var tbody = el("tbody");
    var sorted = sortEntries(list);
    // the first TR_PAGE rows, then „Încarcă încă 50”; sorting keeps the count, new data starts again
    if (v.trShownKey !== v.key) { v.trShown = TR_PAGE; v.trShownKey = v.key; }
    var more = el("button", "btn btn-ghost btn-sm st-more-btn");
    more.type = "button";
    var status = el("p", "h-count st-tr-shown");
    status.setAttribute("role", "status");
    function fill(from) {
      sorted.slice(from, v.trShown).forEach(function (e) {
        var tr = el("tr", "st-row");
        if (e.stats && e.stats.sufficient === false) tr.classList.add("st-row-small");
        TR_COLS.forEach(function (c) { td(tr, c.cell(e), (c.num ? "st-num " : "") + (c.cls || "")); });
        tr.addEventListener("click", function (ev) {
          if (ev.target.closest("a, button")) return;
          location.hash = "#tren?nr=" + encodeURIComponent(e.train_no);
        });
        tbody.append(tr);
      });
      var shown = Math.min(v.trShown, sorted.length);
      var left = sorted.length - shown;
      more.hidden = !left;
      more.textContent = tt("stats.tr.more", { n: Math.min(TR_PAGE, left) });
      status.textContent = left ? tt("stats.tr.shown", { n: shown, total: sorted.length }) : "";
    }
    more.addEventListener("click", function () {
      var from = v.trShown;
      v.trShown += TR_PAGE;
      fill(from);
      if (more.hidden) t.wrap.focus();   // the button is gone: keep the focus on the table, not <body>
    });
    fill(0);
    // printing shows the whole list, not only the rows drawn so far
    if (v.trPrint) window.removeEventListener("beforeprint", v.trPrint);
    v.trPrint = function () {
      if (!more.isConnected || more.hidden) return;
      var from = v.trShown;
      v.trShown = sorted.length;
      fill(from);
    };
    window.addEventListener("beforeprint", v.trPrint);
    t.table.append(thead, tbody);
    v.body.append(t.wrap, more, status);
  }

  var trenuri = makeView({
    root: "st-trenuri", route: "trenuri", fields: TR_FIELDS,
    url: function (v) {
      var q = toSearch(v.p, TR_FIELDS).toString();
      return "/api/trains/stats" + (q ? "?" + q : "");
    },
    errorNode: function (v, e) { return loadFailed(v, tt("stats.err.what_trains"), e); },
    render: renderTrains
  });

  // ---- #tren?nr= ---------------------------------------------------------------------

  var TN_FIELDS = ["prag", "min", "doar_confirmate"];

  function journeyDelay(r) {
    if (!r || !r.delay_known) return el("span", "delay delay-unread", tt("stats.t.unread"));
    var d = r.state === "confirmed" ? r.final_delay : r.observed_delay;
    var text = d <= 0 ? minutes(0) : "+" + minutes(d);
    var s = el("span", "st-jdelay", text);
    if (r.state !== "confirmed") {
      s.append(el("span", "st-jdelay-note", tt("stats.t.last_read")));
    }
    return s;
  }

  function renderTren(v, d) {
    var entries = Array.isArray(d.entries) ? d.entries : [];
    var params = d.params || {};
    var type = entries.length ? entries[0].train_type : null;
    var name = (type ? type + " " : "") + d.train_no;
    $("tren-heading").textContent = tt("stats.t.heading", { name: name });
    document.title = tt("stats.t.title", { name: name });
    var first = null, last = null;
    entries.forEach(function (e) {
      if (!first || e.first_date < first) first = e.first_date;
      if (!last || e.last_date > last) last = e.last_date;
    });
    $("tren-sub").textContent = tt("stats.t.sub", { ops: (d.operators || []).filter(Boolean).join(", ") || tt("stats.unknown_lc"),
      obs: d.observations == null ? tt("stats.t.obs_unknown") : pl(d.observations, "stats.w.obs_reading"), period: period(first, last) });

    var top = el("div", "st-bar-head");
    var back = el("a", "st-back", tt("stats.t.back"));
    back.href = "#trenuri";
    top.append(back);
    var q = toSearch(v.p, TN_FIELDS);
    q.set("format", "csv");
    var exp = el("div", "st-exports");
    exp.append(exportLink(tt("stats.export.csv_j"), "/api/trains/" + encodeURIComponent(d.train_no) +
      "/journeys?" + q.toString(), true));
    top.append(exp);
    v.body.append(top);
    v.body.append(el("p", "h-count", explainParams(params)));

    var cards = el("div", "st-cards");
    v.body.append(cards);
    var jAll = Array.isArray(d.journeys) ? d.journeys : [];
    heroBlock(v, [{ label: tt("stats.t.observed"), value: entries.reduce(function (a, e) { return a + (e.journeys || 0); }, 0),
                      sub: pl(entries.length, "stats.w.board_n") + " · " + period(first, last) }]
      .concat(entries.map(function (e) {
        return onTimeTile(tt("stats.hero.on_time", { board: BOARD_PL[e.board] || e.board }), e.board === "arrival" ? "arr" : "dep", e.stats, params);
      })));
    entries.forEach(function (e) {
      var card = el("section", "st-card");
      var h = el("h2", "st-card-h");
      h.append(el("span", "st-card-board", BOARD_PL[e.board] || e.board),
               document.createTextNode(" " + BOARD_DIR[e.board] + " "), stationLink(e.station));
      card.append(h);
      card.append(el("p", "st-card-sub", pl(e.journeys, "stats.w.journey") + " · " +
        period(e.first_date, e.last_date)));
      if (U() && e.stats && e.stats.n) {
        var dn = el("div", "st-card-donut");
        U().delayDonut(dn, e.stats, params, BOARD_PL[e.board] || e.board, "tr-" + e.board);
        card.append(dn);
        // delay of each journey in time order (a gap = delay not read, never 0)
        var series = jAll.filter(function (j) { return j.board === e.board; }).slice().reverse().map(function (j) {
          var r = j.result;
          if (!r || !r.delay_known) return null;
          return r.state === "confirmed" ? r.final_delay : r.observed_delay;
        });
        if (series.filter(function (x) { return x != null; }).length > 1) {
          var sp = el("div", "st-card-spark");
          sp.append(el("p", "detail-note", tt("stats.t.spark_note")));
          sp.append(U().spark(series, { w: 240, h: 44, tone: "bad", label: tt("stats.t.spark_label", { list: series.map(function (x) { return x == null ? tt("stats.t.unread") : minutes(x); }).join(", ") }) }));
          card.append(sp);
        }
      }
      card.append(statsGrid(e.stats, params));
      var w = sampleWarn(e.stats, params);
      if (w) card.append(w);
      card.append(qualityLine(e.quality));
      cards.append(card);
      var dist = d.distribution && d.distribution[e.board];
      if (dist) {
        card.append(el("h3", "detail-h", tt("stats.t.dist_h", { n: e.stats.n || 0 })));
        card.append(distChart(card, dist, e.board));
      }
    });

    var js = Array.isArray(d.journeys) ? d.journeys : [];
    var sec = el("section", "st-section");
    sec.append(el("h2", "st-h2", tt("stats.t.journeys_h", { n: js.length })));
    sec.append(el("p", "st-note", tt("stats.t.journeys_note")));
    var t = scrollTable(tt("stats.t.journeys_table", { name: name }));
    var thead = el("thead");
    var hr = el("tr");
    ["service_date", "sched", "board", "station", "result", "delay"].map(function (k) { return tt("stats.c." + k); }).forEach(function (x) {
      var th = el("th", null, x);
      th.scope = "col";
      hr.append(th);
    });
    thead.append(hr);
    var tbody = el("tbody");
    js.forEach(function (j) {
      var tr = el("tr", "st-row");
      var b = el("button", "st-jbtn", dayText(j.service_date));
      b.type = "button";
      b.setAttribute("aria-label", tt("stats.t.detail_aria", { day: dayText(j.service_date), time: j.sched_time || "" }));
      var open = function () {
        var f = H().openJourney;
        if (typeof f === "function") {
          f(j.id, b, { train_type: j.train_type, train_no: j.train_no, board: j.board,
                       sched_time: j.sched_time, station: j.station, service_date: j.service_date });
        }
      };
      b.addEventListener("click", open);
      td(tr, b);
      td(tr, j.sched_time || "—", "st-mono");
      td(tr, BOARD_ONE[j.board] || j.board);
      td(tr, stationLink(j.station, j.uncertain));
      td(tr, resultBadge(j.result));
      td(tr, journeyDelay(j.result), "st-num");
      tr.addEventListener("click", function (ev) { if (!ev.target.closest("a, button")) open(); });
      tbody.append(tr);
    });
    t.table.append(thead, tbody);
    sec.append(t.wrap);
    v.body.append(sec);
  }

  var tren = makeView({
    charts: true, root: "st-tren", route: "tren", fields: TN_FIELDS,
    onParams: function (v, params) { v.nr = (params.get("nr") || "").trim(); },
    hashExtra: function (v) { return v.nr ? { nr: v.nr } : null; },
    title: function (v) {
      $("tren-heading").textContent = v.nr ? tt("stats.t.heading", { name: v.nr }) : tt("stats.c.train");
      $("tren-sub").textContent = "";
    },
    url: function (v) {
      if (!/^\d{1,6}$/.test(v.nr || "") || parseInt(v.nr, 10) === 0) {
        v.data = null;
        v.key = null;
        v.body.replaceChildren(notice(tt("stats.t.invalid"), "notice-error"));
        return null;
      }
      var q = toSearch(v.p, TN_FIELDS).toString();
      return "/api/trains/" + encodeURIComponent(parseInt(v.nr, 10)) + "/journeys" + (q ? "?" + q : "");
    },
    errorText: function (e) {
      return e.status === 404 ? tt("stats.t.notfound") : errorText(e);
    },
    render: renderTren
  });

  // ---- per-hour / weekday / month charts (shared by #statie) -----------------------

  function groupItems(groups, labelFn) {
    return (groups || []).map(function (g) {
      var label = labelFn(g);
      return { label: label, value: g.mean, n: g.n, low: g.n > 0 && g.sufficient === false,
               valueText: g.mean == null ? null : numFmt.format(Math.round(g.mean)),
               tip: tt("stats.g.tip", { label: label, mean: minutes(g.mean), n: g.n, small: g.n && g.sufficient === false ? tt("stats.small_paren") : "" }) };
    });
  }

  var DIMS = [
    { key: "hour", get title() { return tt("stats.dim.hour"); }, minWidth: 600,
      label: function (g) { return (g.key < 10 ? "0" : "") + g.key; } },
    { key: "weekday", get title() { return tt("stats.dim.weekday"); }, minWidth: 300,
      label: function (g) { return String(g.label || g.key).slice(0, 3); } },
    { key: "month", get title() { return tt("stats.dim.month"); }, minWidth: 240, label: function (g) { return monthText(g.key); } }
  ];

  // Charts per hour / weekday / month, one card per board (shared with #statie).
  function timeSections(host, byTime, boards, params, labels) {
    DIMS.forEach(function (dim) {
      var sec = el("section", "st-section");
      sec.append(el("h2", "st-h2", dim.title));
      sec.append(el("p", "st-note", tt("stats.dim.note", { min: params.min_sample })));
      var grid = el("div", "st-cards");
      sec.append(grid);
      host.append(sec);
      boards.forEach(function (b) {
        var groups = byTime && byTime[b] && byTime[b][dim.key];
        var card = el("div", "st-card st-card-chart");
        card.append(el("h3", "detail-h", labels[b]));
        grid.append(card);
        if (!groups || !groups.length) {
          card.append(el("p", "detail-note", tt("stats.dim.nodata")));
          return;
        }
        card.append(barChart({ host: card, items: groupItems(groups, dim.label), minWidth: dim.minWidth,
          showN: true, unit: "min",
          title: dim.title + " — " + labels[b],
          desc: tt("stats.dim.desc") }));
      });
    });
  }

  // ---- #clasamente -------------------------------------------------------------------

  var CL_FIELDS = ["board", "from", "to", "doar_confirmate", "prag", "min"];
  var RANK_LIMIT = 10;

  // top three as podium cards (rank, train, station, the figure the list is ordered by, N)
  function podium(host, title, list, by) {
    if (!U() || !list.length) return;
    var sec = el("section", "st-section st-podium-sec");
    sec.append(el("h2", "st-h2", tt("stats.pod.top", { title: title, n: Math.min(3, list.length) })));
    var row = el("ol", "st-podium");
    list.slice(0, 3).forEach(function (e, i) {
      var li = el("li", "st-podium-card st-pod-" + (i + 1));
      var rank = el("span", "st-pod-rank", String(i + 1));
      rank.setAttribute("aria-label", tt("stats.pod.rank", { n: i + 1 }));
      var link = trainLink(e);
      link.classList.add("st-pod-train");
      var fig = el("p", "st-pod-fig");
      if (by === "pct" && e.stats.on_time_pct != null) {
        U().countUp(fig, e.stats.on_time_pct, function (x) { return tt("stats.fmt.pct", { v: numFmt.format(Math.round(x * 10) / 10) }); });
      } else if (e.stats.mean != null) {
        U().countUp(fig, e.stats.mean, function (x) { return tt("stats.fmt.min", { v: numFmt.format(Math.round(x * 10) / 10) }); });
      } else fig.textContent = "—";
      var top = el("div", "st-pod-top");
      top.append(rank, link);
      li.append(top, fig, el("p", "st-pod-lab", by === "pct" ? tt("stats.pod.ontime") : tt("stats.pod.mean")));
      var meta = el("p", "st-pod-meta");
      meta.append((BOARD_ONE[e.board] || e.board) + " · ", stationLink(e.station), " · N = " + e.stats.n);
      li.append(meta);
      if (by === "pct" && e.stats.on_time_pct != null) {
        li.append(U().meter(e.stats.on_time_pct, { tone: "ok", label: tt("stats.ontime_aria", { v: pct(e.stats.on_time_pct) }) }));
      }
      var sp = trendCell(e.trend, trendMax(list), { w: 120, h: 28, compact: false });
      if (!sp.classList.contains("ui-spark-none")) {
        sp.classList.add("st-pod-spark");
        li.append(el("p", "st-pod-lab st-pod-lab2", tt("stats.pod.last14")), sp);
      }
      li.addEventListener("click", function (ev) {
        if (!ev.target.closest("a, button")) location.hash = "#tren?nr=" + encodeURIComponent(e.train_no);
      });
      row.append(li);
    });
    sec.append(row);
    host.append(sec);
  }

  function rankTable(title, list) {
    var sec = el("section", "st-section");
    sec.append(el("h2", "st-h2", title));
    if (!list.length) {
      sec.append(el("p", "detail-note", tt("stats.rank.none_train")));
      return sec;
    }
    var t = scrollTable(title);
    var thead = el("thead");
    var hr = el("tr");
    var hi = trendMax(list);
    [["#", true], ["train", false], ["board", false], ["station", false], ["N", true], ["mean", true],
     ["median", true], ["ontime", true], ["last14", false]].map(function (h) { return [h[0].length > 1 ? tt("stats.c." + h[0]) : h[0], h[1]]; }).forEach(function (h) {
      var th = el("th", h[1] ? "st-num" : null, h[0]);
      th.scope = "col";
      hr.append(th);
    });
    thead.append(hr);
    var tbody = el("tbody");
    list.forEach(function (e, i) {
      var tr = el("tr", "st-row");
      td(tr, String(i + 1), "st-num st-rank");
      td(tr, trainLink(e));
      td(tr, BOARD_ONE[e.board] || e.board);
      td(tr, stationLink(e.station));
      td(tr, String(e.stats.n), "st-num");
      td(tr, minutes(e.stats.mean), "st-num");
      td(tr, minutes(e.stats.median), "st-num");
      td(tr, pctMeter(e.stats.on_time_pct), "st-num");
      td(tr, trendCell(e.trend, hi));
      tr.addEventListener("click", function (ev) {
        if (!ev.target.closest("a, button")) location.hash = "#tren?nr=" + encodeURIComponent(e.train_no);
      });
      tbody.append(tr);
    });
    t.table.append(thead, tbody);
    sec.append(t.wrap);
    return sec;
  }

  function renderClasamente(v, d) {
    var params = d.params || {};
    var head = el("div", "st-bar-head");
    head.append(el("p", "h-count", tt("stats.cl.count", { elig: pl(d.eligible || 0, "stats.w.train_elig"), min: params.min_sample, below: d.below_min || 0, explain: explainParams(params) })));
    var q = toSearch(v.p, CL_FIELDS);
    q.set("limit", String(RANK_LIMIT));
    q.set("format", "csv");
    var exp = el("div", "st-exports");
    exp.append(exportLink(tt("stats.export.csv"), "/api/stats/rankings?" + q.toString(), true));
    head.append(exp);
    v.body.append(head);
    if (!d.eligible) {
      v.body.append(el("p", "st-warn", tt("stats.cl.warn", { min: params.min_sample, has: pl(d.below_min || 0, "stats.w.train_has") })));
    } else {
      heroBlock(v, [{ label: tt("stats.cl.hero_elig"), value: d.eligible || 0, sub: tt("stats.cl.hero_sub", { min: params.min_sample }) },
                    { label: tt("stats.cl.below"), value: d.below_min || 0, sub: tt("stats.cl.not_ranked") }]);
      podium(v.body, tt("stats.cl.most_punctual"), d.most_punctual || [], "pct");
      podium(v.body, tt("stats.cl.most_delayed"), d.most_delayed || [], "mean");
      v.body.append(rankTable(tt("stats.cl.most_delayed"), d.most_delayed || []));
      v.body.append(rankTable(tt("stats.cl.most_punctual"), d.most_punctual || []));
      v.body.append(el("p", "st-note", tt("stats.cl.order")));
    }
    renderRankStations(d.stations, params);
  }

  function stationRankTable(title, list) {
    var sec = el("section", "st-subsection");
    sec.append(el("h3", "st-h3", title));
    if (!list.length) {
      sec.append(el("p", "detail-note", tt("stats.st.none_elig")));
      return sec;
    }
    var t = scrollTable(tt("stats.st.table", { title: title.toLowerCase() }));
    var thead = el("thead");
    var hr = el("tr");
    var hi = trendMax(list);
    [["#", true], ["station", false], ["board", false], ["N", true], ["journeys", true], ["trains", true],
     ["mean", true], ["median", true], ["ontime", true], ["last14", false]].map(function (h) { return [h[0].length > 1 ? tt("stats.c." + h[0]) : h[0], h[1]]; }).forEach(function (h) {
      var th = el("th", h[1] ? "st-num" : null, h[0]);
      th.scope = "col";
      hr.append(th);
    });
    thead.append(hr);
    var tbody = el("tbody");
    list.forEach(function (e, i) {
      var s = e.stats || {};
      var tr = el("tr", "st-row");
      td(tr, String(i + 1), "st-num st-rank");
      td(tr, stationLink(e.station));
      td(tr, BOARD_ONE[e.board] || e.board);
      td(tr, s.n == null ? "—" : String(s.n), "st-num");
      td(tr, e.journeys == null ? "—" : String(e.journeys), "st-num");
      td(tr, e.trains == null ? "—" : String(e.trains), "st-num");
      td(tr, minutes(s.mean), "st-num");
      td(tr, minutes(s.median), "st-num");
      td(tr, pctMeter(s.on_time_pct), "st-num");
      td(tr, trendCell(e.trend, hi));
      tr.addEventListener("click", function (ev) {
        if (!ev.target.closest("a, button")) location.hash = "#statie?nume=" + encodeURIComponent(e.station);
      });
      tbody.append(tr);
    });
    t.table.append(thead, tbody);
    sec.append(t.wrap);
    return sec;
  }

  // Station ranking (`stations` of /api/stats/rankings) in #rank-stations.
  function renderRankStations(st, params) {
    var box = $("rank-stations");
    if (!box) return;
    box.replaceChildren();
    if (!st) return;
    var sec = el("section", "st-section st-explain");
    sec.append(el("h2", "st-h2", tt("stats.rs.title")));
    sec.append(el("p", "h-count", tt("stats.rs.count", { elig: pl(st.eligible || 0, "stats.w.station_elig"), min: params.min_sample, below: st.below_min || 0 })));
    sec.append(el("p", "st-note", tt("stats.rs.note")));
    if (!st.eligible) {
      sec.append(el("p", "st-warn", tt("stats.rs.warn", { min: params.min_sample, has: pl(st.below_min || 0, "stats.w.station_has") })));
    } else {
      sec.append(stationRankTable(tt("stats.cl.most_delayed"), st.most_delayed || []));
      sec.append(stationRankTable(tt("stats.cl.most_punctual"), st.most_punctual || []));
    }
    box.append(sec);
  }

  var clasamente = makeView({
    charts: true, root: "st-clasamente", route: "clasamente", fields: CL_FIELDS,
    url: function (v) {
      var q = toSearch(v.p, CL_FIELDS);
      q.set("limit", String(RANK_LIMIT));
      return "/api/stats/rankings?" + q.toString();
    },
    onError: function () { var b = $("rank-stations"); if (b) b.replaceChildren(); },
    render: renderClasamente
  });

  // ---- #statii (list + search) ---------------------------------------------------------

  var SL_FIELDS = ["q"];
  var SL_LIMIT = 500;

  function renderStatii(v, d) {
    var list = Array.isArray(d.stations) ? d.stations : [];
    if (!list.length && !v.p.q) {
      v.body.append(el("p", "empty", tt("stats.sl.none")));
      return;
    }
    var head = el("div", "st-bar-head");
    var total = list.reduce(function (a, s) { return a + (s.journeys || 0); }, 0);
    head.append(el("p", "h-count", tt("stats.sl.count", { st: pl(list.length, "stats.w.station"), q: v.p.q ? tt("stats.sl.for_q", { q: v.p.q }) : "", j: pl(total, "stats.w.journey") })));
    var q = new URLSearchParams();
    if (v.p.q) q.set("query", v.p.q);
    q.set("limit", String(SL_LIMIT));
    var exp = el("div", "st-exports");
    q.set("format", "csv");
    exp.append(exportLink(tt("stats.export.csv"), "/api/stations?" + q.toString(), true));
    q.delete("format");
    exp.append(exportLink("JSON", "/api/stations?" + q.toString(), false));
    head.append(exp);
    v.body.append(head);
    v.body.append(el("p", "st-note", tt("stats.sl.note")));
    if (!list.length) {
      v.body.append(el("p", "empty", tt("stats.sl.nomatch")));
      return;
    }
    var arr = list.reduce(function (a, x) { return a + (x.arrivals || 0); }, 0);
    var dep = list.reduce(function (a, x) { return a + (x.departures || 0); }, 0);
    var busiest = list.slice().sort(function (a, b) { return (b.journeys || 0) - (a.journeys || 0); })[0];
    heroBlock(v, [
      { label: tt("stats.sl.hero_obs"), value: list.length, sub: v.p.q ? tt("stats.sl.for_q", { q: v.p.q }).trim() : tt("stats.sl.hero_on_board") },
      { label: tt("stats.c.journeys"), value: total, sub: pl(arr, "stats.w.arrival") + " · " + pl(dep, "stats.w.departure") },
      { label: tt("stats.sl.busiest"), cls: "ui-stat-name", text: titleCase(busiest.name),
        sub: pl(busiest.journeys || 0, "stats.w.journey") + " · " + pl(busiest.trains || 0, "stats.w.train") }]);
    if (U() && arr + dep > 0) {
      var card = el("section", "st-card st-share-card");
      card.append(el("h2", "st-card-h", tt("stats.share.arr_dep")));
      card.append(el("p", "st-card-sub", tt("stats.sl.card_sub")));
      U().donut(card, { title: tt("stats.sl.donut"), valueUnit: tt("stats.unit.journeys"), showPct: arr + dep >= 5,
        desc: tt("stats.sl.donut_desc", { a: arr, d: dep, n: arr + dep }),
        centerValue: numFmt.format(arr + dep), centerLabel: tt("stats.share.total_n"),
        segments: [{ label: tt("stats.board.arrival"), value: arr, slot: "arr" }, { label: tt("stats.board.departure"), value: dep, slot: "dep" }] });
      v.body.append(card);
    }
    var t = scrollTable(tt("stats.sl.table"));
    var thead = el("thead");
    var hr = el("tr");
    [["station", false], ["journeys", true], ["arrivals", true], ["departures", true], ["trains", true],
     ["with_delay", true], ["period", false]].map(function (h) { return [tt("stats.c." + h[0]), h[1]]; }).forEach(function (h) {
      var th = el("th", h[1] ? "st-num" : null, h[0]);
      th.scope = "col";
      hr.append(th);
    });
    thead.append(hr);
    var tbody = el("tbody");
    list.forEach(function (s) {
      var tr = el("tr", "st-row");
      var c = el("span", "st-station");
      c.append(stationLink(s.name, s.uncertain_only));
      if (s.uncertain_only) c.append(el("span", "st-tag", tt("stats.sl.tag")));
      td(tr, c);
      var jc = el("span", "st-cell-meter", String(s.journeys == null ? "—" : s.journeys));
      if (U() && s.arrivals != null && s.departures != null) {
        var sm = U().split(s.arrivals, s.departures, { label: pl(s.arrivals, "stats.w.arrival") + ", " + pl(s.departures, "stats.w.departure") });
        sm.classList.add("st-meter");
        jc.append(sm);
      }
      td(tr, jc, "st-num");
      td(tr, s.arrivals == null ? "—" : String(s.arrivals), "st-num");
      td(tr, s.departures == null ? "—" : String(s.departures), "st-num");
      td(tr, s.trains == null ? "—" : String(s.trains), "st-num");
      td(tr, s.delay_known == null ? "—" : String(s.delay_known), "st-num");
      td(tr, period(s.first_date, s.last_date));
      tr.addEventListener("click", function (ev) {
        if (!ev.target.closest("a, button")) location.hash = "#statie?nume=" + encodeURIComponent(s.name);
      });
      tbody.append(tr);
    });
    t.table.append(thead, tbody);
    v.body.append(t.wrap);
    if (list.length >= SL_LIMIT) {
      v.body.append(el("p", "st-note", tt("stats.sl.limit", { n: SL_LIMIT })));
    }
  }

  var statii = makeView({
    root: "st-statii", route: "statii", fields: SL_FIELDS,
    url: function (v) {
      var q = new URLSearchParams();
      if (v.p.q) q.set("query", v.p.q);
      q.set("limit", String(SL_LIMIT));
      return "/api/stations?" + q.toString();
    },
    errorNode: function (v, e) { return loadFailed(v, tt("stats.err.what_stations"), e); },
    render: renderStatii
  });

  // ---- #statie?nume= -------------------------------------------------------------------

  var SN_FIELDS = ["board", "from", "to", "prag", "min", "doar_confirmate"];
  var JR_PAGE = 50;
  var BOARD_TOWARD = lazy("stats.toward.", ["arrival", "departure"]);
  var stampFmts = {};
  function stampFmt() {
    var l = window.I18N.lang();
    return stampFmts[l] = stampFmts[l] || new Intl.DateTimeFormat(l, { timeZone: "Europe/Bucharest", day: "numeric",
      month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
  }

  function stamp(ts) {
    if (!ts) return tt("stats.unknown_lc");
    var d = new Date(ts);
    return isNaN(d.getTime()) ? String(ts) : stampFmt().format(d);
  }

  function stationApi(name) { return "/api/stations/" + encodeURIComponent(name); }

  function rankLine(rank, s, params, board) {
    if (rank && rank.position != null) {
      return el("p", "st-rankline", tt("stats.rl.pos", { pos: rank.position, of: rank.of, board: BOARD_PL[board].toLowerCase(), min: params.min_sample }));
    }
    var n = s && s.n != null ? s.n : 0;
    return el("p", "st-rankline st-rankline-out", tt("stats.rl.out", { why: n < params.min_sample ? tt("stats.rl.below", { n: n, min: params.min_sample }) : tt("stats.rl.not_elig") }));
  }

  function stationTrainsTable(list, name, board) {
    var cap = tt("stats.stt.cap", { board: BOARD_PL[board].toLowerCase(), dir: BOARD_DIR[board], name: titleCase(name) });
    var t = scrollTable(cap);
    var thead = el("thead");
    var hr = el("tr");
    var hi = trendMax(list);
    [["train", false], ["operator", false], ["journeys", true], ["N", true], ["mean", true],
     ["median", true], ["p90", true], ["max", true], ["ontime", true], ["last14", false], ["last_day", false]].map(function (h) { return [h[0].length > 3 || h[0] === "max" ? tt("stats.c." + h[0]) : h[0], h[1]]; }).forEach(function (h) {
      var th = el("th", h[1] ? "st-num" : null, h[0]);
      th.scope = "col";
      hr.append(th);
    });
    thead.append(hr);
    var tbody = el("tbody");
    list.forEach(function (e) {
      var s = e.stats || {};
      var tr = el("tr", "st-row");
      if (s.sufficient === false) tr.classList.add("st-row-small");
      td(tr, trainLink(e), "st-c-train");
      td(tr, e.operator || tt("stats.unknown_lc"));
      td(tr, e.journeys == null ? "—" : String(e.journeys), "st-num");
      td(tr, s.n == null ? "—" : String(s.n), "st-num");
      td(tr, minutes(s.mean), "st-num");
      td(tr, minutes(s.median), "st-num");
      td(tr, minutes(s.p90), "st-num");
      td(tr, minutes(s.max), "st-num");
      td(tr, pct(s.on_time_pct), "st-num");
      td(tr, trendCell(e.trend, hi));
      td(tr, dayText(e.last_date));
      tr.addEventListener("click", function (ev) {
        if (!ev.target.closest("a, button")) location.hash = "#tren?nr=" + encodeURIComponent(e.train_no);
      });
      tbody.append(tr);
    });
    t.table.append(thead, tbody);
    return t.wrap;
  }

  // „Ultimele călătorii”: /api/stations/{name}/journeys, paginated with before=next_before.
  function jrRow(j) {
    var tr = el("tr", "st-row");
    var b = el("button", "st-jbtn", dayText(j.service_date));
    b.type = "button";
    b.setAttribute("aria-label", tt("stats.jr.aria", { t: (j.train_type || "") + " " + j.train_no, day: dayText(j.service_date), time: j.sched_time || "" }));
    var open = function () {
      var f = H().openJourney;
      if (typeof f === "function") {
        f(j.id, b, { train_type: j.train_type, train_no: j.train_no, board: j.board,
                     sched_time: j.sched_time, station: j.station, service_date: j.service_date });
      }
    };
    b.addEventListener("click", open);
    td(tr, b);
    td(tr, j.sched_time || "—", "st-mono");
    td(tr, BOARD_ONE[j.board] || j.board);
    td(tr, trainLink(j));
    td(tr, j.operator || tt("stats.unknown_lc"));
    td(tr, resultBadge(j.result));
    td(tr, journeyDelay(j.result), "st-num");
    if (j.uncertain) tr.title = tt("stats.jr.uncertain");
    tr.addEventListener("click", function (ev) { if (!ev.target.closest("a, button")) open(); });
    return tr;
  }

  function jrPaint(v) {
    var jr = v.jr;
    var dom = jr && jr.dom;
    if (!dom) return;
    dom.tbody.replaceChildren.apply(dom.tbody, jr.items.map(jrRow));
    dom.wrap.hidden = !jr.items.length;
    dom.count.textContent = jr.items.length ? tt("stats.jr.shown", { n: pl(jr.items.length, "stats.w.journey"), all: jr.next == null && jr.loaded ? tt("stats.jr.all") : "" }) : "";
    dom.more.hidden = jr.next == null;
    dom.more.disabled = jr.loading;
    dom.status.textContent = jr.loading ? tt("stats.loading_short") : jr.error ? jr.error
      : jr.loaded && !jr.items.length ? tt("stats.jr.empty") : "";
  }

  function jrFetch(v) {
    var jr = v.jr;
    if (jr.loading) return;
    jr.loading = true;
    jr.error = null;
    jrPaint(v);
    var q = new URLSearchParams();
    q.set("limit", String(JR_PAGE));
    if (jr.board) q.set("board", jr.board);
    if (jr.next != null) q.set("before", String(jr.next));
    var ctrl = new AbortController();
    jr.ctrl = ctrl;
    getJSON(stationApi(jr.name) + "/journeys?" + q.toString(), ctrl)
      .then(function (data) {
        if (v.jr !== jr) return;
        var items = Array.isArray(data && data.journeys) ? data.journeys : [];
        jr.items = jr.items.concat(items);
        jr.next = data && data.next_before != null ? data.next_before : null;
        jr.loaded = true;
      })
      .catch(function (e) {
        if (v.jr !== jr || e.aborted) return;
        jr.error = errorText(e);
      })
      .then(function () {
        if (v.jr !== jr) return;
        jr.loading = false;
        jrPaint(v);
      });
  }

  function journeysSection(v, name) {
    var board = v.p.board || "";
    var sec = el("section", "st-section");
    sec.append(el("h2", "st-h2", tt("stats.jr.title")));
    sec.append(el("p", "st-note", tt("stats.jr.note", { only: board ? tt("stats.jr.only", { b: BOARD_PL[board].toLowerCase() }) : "" })));
    var count = el("p", "h-count");
    var t = scrollTable(tt("stats.jr.table", { name: titleCase(name) }));
    var thead = el("thead");
    var hr = el("tr");
    ["service_date", "sched", "board", "train", "operator", "result", "delay"].map(function (k) { return tt("stats.c." + k); }).forEach(function (x) {
      var th = el("th", null, x);
      th.scope = "col";
      hr.append(th);
    });
    thead.append(hr);
    var tbody = el("tbody");
    t.table.append(thead, tbody);
    var more = el("button", "btn btn-ghost btn-sm st-more-btn", tt("stats.jr.more"));
    more.type = "button";
    var status = el("p", "detail-note");
    status.setAttribute("role", "status");
    sec.append(count, t.wrap, more, status);
    var key = name + "|" + board;
    if (!v.jr || v.jr.key !== key) {
      if (v.jr && v.jr.ctrl) v.jr.ctrl.abort();
      v.jr = { key: key, name: name, board: board, items: [], next: null, loaded: false, loading: false };
    }
    v.jr.dom = { tbody: tbody, wrap: t.wrap, count: count, more: more, status: status };
    more.addEventListener("click", function () { jrFetch(v); });
    if (!v.jr.loaded && !v.jr.loading) jrFetch(v);
    else jrPaint(v);
    return sec;
  }

  function stationHeading(text, sub) {
    $("statie-heading").textContent = text;
    $("statie-sub").textContent = sub || "";
  }

  function renderStatie(v, d) {
    var params = d.params || {};
    var name = d.name || v.nume;
    var nice = titleCase(name);
    if (name !== v.nume) {   // show the canonical name in the URL (GALATI, not galați)
      v.nume = name;
      v.key = v.url();
      syncHash("statie", v.p, SN_FIELDS, { nume: name });
    }
    stationHeading(tt("stats.sn.heading", { name: nice }),
      tt("stats.sn.sub", { j: pl(d.journeys || 0, "stats.w.journey"), t: pl(d.trains || 0, "stats.w.train"),
        period: d.period ? period(d.period.first, d.period.last) : "—",
        days: d.period && d.period.days ? tt("stats.sn.days", { d: pl(d.period.days, "stats.w.day_data") }) : "",
        first: stamp(d.first_seen), last: stamp(d.last_seen) }));
    document.title = tt("stats.sn.title", { name: nice });

    var bd = BOARDS.filter(function (b) { return d.boards && d.boards[b]; });
    heroBlock(v, [{ label: tt("stats.c.journeys"), value: d.journeys || 0, sub: pl(d.trains || 0, "stats.w.train") },
      { label: tt("stats.hero.days"), value: d.period && d.period.days ? d.period.days : 0, sub: d.period ? period(d.period.first, d.period.last) : "—" }]
      .concat(bd.map(function (b) {
        return onTimeTile(tt("stats.hero.on_time", { board: BOARD_PL[b] }), b === "arrival" ? "arr" : "dep", d.boards[b].stats, params);
      })));
    var warn = el("p", "st-warn st-station-note");
    warn.setAttribute("role", "note");
    warn.append(el("strong", null, tt("stats.sn.warn_h")), document.createTextNode(d.note ||
      tt("stats.sn.warn_b")));
    v.body.append(warn);

    var top = el("div", "st-bar-head");
    var back = el("a", "st-back", tt("stats.sn.back"));
    back.href = "#statii";
    top.append(back);
    var q = toSearch(v.p, SN_FIELDS);
    var exp = el("div", "st-exports");
    q.set("format", "csv");
    exp.append(exportLink(tt("stats.export.csv_t"), stationApi(name) + "?" + q.toString(), true));
    var jq = new URLSearchParams();
    if (v.p.board) jq.set("board", v.p.board);
    jq.set("limit", "500");
    jq.set("format", "csv");
    exp.append(exportLink(tt("stats.export.csv_j"), stationApi(name) + "/journeys?" + jq.toString(), true));
    q.delete("format");
    exp.append(exportLink("JSON", stationApi(name) + (q.toString() ? "?" + q.toString() : ""), false));
    top.append(exp);
    v.body.append(top);
    v.body.append(el("p", "h-count", explainParams(params)));
    v.body.append(qualityLine(d.quality));
    if (d.uncertain_names) {
      v.body.append(el("p", "st-note", tt("stats.sn.uncertain", { n: pl(d.uncertain_names, "stats.w.journey_has") })));
    }

    var boards = BOARDS.filter(function (b) { return d.boards && d.boards[b]; });
    var cards = el("div", "st-cards");
    v.body.append(cards);
    boards.forEach(function (b) {
      var x = d.boards[b];
      var s = x.stats || {};
      var card = el("section", "st-card");
      card.append(el("h2", "st-card-h st-card-board", BOARD_TOWARD[b]));
      card.append(el("p", "st-card-sub", tt("stats.sn.card_sub", { j: pl(x.journeys || 0, "stats.w.journey"), dir: b === "arrival" ? tt("stats.sn.dir_arr") : tt("stats.sn.dir_dep"), name: nice })));
      if (U() && s.n) {
        var dn = el("div", "st-card-donut");
        U().delayDonut(dn, s, params, BOARD_TOWARD[b], "st-" + b);
        card.append(dn);
      }
      card.append(statsGrid(s, params));
      var w = sampleWarn(s, params);
      if (w) card.append(w);
      card.append(rankLine(x.rank, s, params, b));
      card.append(qualityLine(x.quality));
      if (x.distribution) {
        card.append(el("h3", "detail-h", tt("stats.t.dist_h", { n: s.n || 0 })));
        card.append(distChart(card, x.distribution, b));
      }
      cards.append(card);
    });

    boards.forEach(function (b) {
      var list = Array.isArray(d.boards[b].trains) ? d.boards[b].trains : [];
      var sec = el("section", "st-section");
      sec.append(el("h2", "st-h2", tt("stats.sn.trains_h", { toward: BOARD_TOWARD[b].toLowerCase(), n: list.length })));
      if (!list.length) sec.append(el("p", "detail-note", tt("stats.sn.no_train")));
      else sec.append(stationTrainsTable(list, name, b));
      v.body.append(sec);
    });

    timeSections(v.body, d.by_time, boards, params, BOARD_TOWARD);
    v.body.append(journeysSection(v, name));
  }

  function stationMissing(text) {
    var box = el("div", "notice notice-error st-missing");
    box.append(el("p", null, text));
    var a = el("a", "st-back", tt("stats.sn.list"));
    a.href = "#statii";
    box.append(a);
    return box;
  }

  var statie = makeView({
    charts: true, root: "st-statie", route: "statie", fields: SN_FIELDS,
    onParams: function (v, params) { v.nume = (params.get("nume") || "").trim().slice(0, 40); },
    hashExtra: function (v) { return v.nume ? { nume: v.nume } : null; },
    title: function (v) {
      stationHeading(v.nume ? tt("stats.sn.heading", { name: titleCase(v.nume) }) : tt("stats.sn.generic"), "");
      if (v.nume) document.title = tt("stats.sn.title", { name: titleCase(v.nume) });
    },
    url: function (v) {
      if (!v.nume) {
        v.data = null;
        v.key = null;
        v.body.replaceChildren(stationMissing(tt("stats.sn.none_picked")));
        return null;
      }
      var q = toSearch(v.p, SN_FIELDS).toString();
      return stationApi(v.nume) + (q ? "?" + q : "");
    },
    errorNode: function (v, e) {
      if (e.status === 404) {
        stationHeading(tt("stats.sn.unknown"), "");
        return stationMissing(tt("stats.sn.not_seen", { name: v.nume ? " (“" + v.nume + "”)" : "" }));
      }
      if (e.status === 422) return stationMissing(tt("stats.sn.invalid"));
      return notice(errorText(e), "notice-error");
    },
    render: renderStatie
  });

  // RO/EN switch: labels and charts of the visible view are rebuilt in the new language
  document.addEventListener("i18n:change", function () {
    [trenuri, tren, clasamente, statii, statie].forEach(function (view) { if (view.relang) view.relang(); });
  });

  App.views.trenuri = { show: trenuri.show, hide: trenuri.hide };
  App.views.tren = { show: tren.show, hide: tren.hide };
  App.views.clasamente = { show: clasamente.show, hide: clasamente.hide };
  App.views.statii = { show: statii.show, hide: statii.hide };
  App.views.statie = { show: statie.show, hide: statie.hide };
  // shared with statistici.js (#statistici, Statistici v2)
  App.stats = { stationLink: stationLink, barChart: barChart, statsGrid: statsGrid, sampleWarn: sampleWarn,
                getJSON: getJSON, errorText: errorText, plural: plural, pl: pl, titleCase: titleCase,
                dayText: dayText, numFmt: numFmt, svg: svg, notice: notice };
})();
