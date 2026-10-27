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
  var BOARD_PL = { arrival: "Sosiri", departure: "Plecări" };
  var BOARD_ONE = { arrival: "Sosire", departure: "Plecare" };
  var BOARD_DIR = { arrival: "din", departure: "spre" };
  var STATE_TEXT = { confirmed: "confirmate", unconfirmed: "neconfirmate", unknown: "necunoscute",
                     in_progress: "în desfășurare" };
  var STATE_CLASS = { confirmed: "res-confirmed", unconfirmed: "res-unconfirmed",
                      unknown: "res-unknown", in_progress: "res-progress" };
  var MONTHS = ["ian.", "feb.", "mar.", "apr.", "mai", "iun.", "iul.", "aug.", "sept.", "oct.",
                "nov.", "dec."];

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
    return "Întârzierea medie pe zi, ultimele " + t.days + " zile (până la " + dayShort(t.last) + "): " +
      t.values.map(function (x) { return x == null ? "necitită" : numFmt.format(x) + " min"; }).join(", ");
  }
  function trendCell(trend, hi, o) {
    var c = el("span", "st-spark-cell");
    var read = trend && trend.values ? trend.values.filter(function (x) { return x != null; }).length : 0;
    if (!U() || read < 2) {
      c.textContent = "—";
      c.classList.add("ui-spark-none");
      c.title = "Sub 2 zile cu întârziere citită";
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
      sub: ok ? st.on_time + " din " + st.n + " (≤ " + params.on_time_max_min + " min)"
        : (st && st.n ? "N = " + st.n + " < " + params.min_sample + ": fără procent" : "N = 0"),
      meter: ok ? st.on_time_pct : null };
  }
  function heroBlock(v, items) {
    if (!U()) return;
    var sec = el("section", "st-hero");
    sec.setAttribute("aria-label", "Cifre principale");
    sec.append(U().hero(items));
    v.body.prepend(sec);
  }

  // ---- formatting --------------------------------------------------------------------

  var numFmt = new Intl.NumberFormat("ro-RO", { maximumFractionDigits: 1 });

  function num(v) { return v == null ? "—" : numFmt.format(v); }
  function minutes(v) { return v == null ? "—" : numFmt.format(v) + " min"; }
  function pct(v) { return v == null ? "—" : numFmt.format(v) + " %"; }

  function plural(n, one, many) {
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
    return m ? parseInt(m[3], 10) + " " + MONTHS[parseInt(m[2], 10) - 1] + " " + m[1] : iso;
  }

  function monthText(key) {
    var m = /^(\d{4})-(\d{2})$/.exec(String(key));
    return m ? MONTHS[parseInt(m[2], 10) - 1] + " " + m[1] : String(key);
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
      a.title = "citire nesigură";
    }
    return a;
  }

  function trainLink(e) {
    var a = el("a", "st-train");
    a.href = "#tren?nr=" + encodeURIComponent(e.train_no);
    a.append(el("span", App.typeClass(e.train_type), e.train_type || "?"),
             el("span", "t-no", String(e.train_no)));
    a.setAttribute("aria-label", "Tren " + (e.train_type || "") + " " + e.train_no);
    return a;
  }

  function resultBadge(r) {
    var f = H().resultBadge;
    if (typeof f === "function") return f(r);
    return el("span", "res-badge", (r && r.label) || "necunoscut");
  }

  function exportLink(text, url, csv) {
    var a = el("a", "btn btn-ghost btn-sm st-export", text);
    a.href = url;
    if (csv) a.setAttribute("download", "");
    else { a.target = "_blank"; a.rel = "noopener"; }
    return a;
  }

  function notice(text, cls) { return el("p", "notice" + (cls ? " " + cls : ""), text); }

  // Small sample: means are shown, percentages and p90 are not (API `sufficient=false`).
  function sampleWarn(s, params) {
    if (!s) return null;
    var min = params && params.min_sample != null ? params.min_sample : "?";
    if (!s.n) {
      return el("p", "st-warn", "Nicio călătorie încheiată cu întârziere citită (N = 0): " +
        "nu există statistici pentru acest grup.");
    }
    if (s.sufficient === false) {
      return el("p", "st-warn", "Eșantion mic (N = " + s.n + " < " + min +
        "): procentele nu sunt afișate.");
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
    statItem(dl, "N (călătorii cu întârziere citită)", s.n == null ? "—" : String(s.n));
    statItem(dl, "Medie", minutes(s.mean));
    statItem(dl, "Mediană", minutes(s.median));
    statItem(dl, "p90", minutes(s.p90));
    statItem(dl, "Maxim", minutes(s.max));
    statItem(dl, "La timp (≤ " + prag + " min)", pct(s.on_time_pct),
             s.n ? s.on_time + " din " + s.n : null);
    statItem(dl, "Peste 30 min", pct(s.over_30_pct), s.n ? s.over_30 + " din " + s.n : null);
    return dl;
  }

  function qualityLine(q) {
    if (!q) return el("p", "st-quality", "Calitatea datelor: necunoscută.");
    var st = q.states || {};
    return el("p", "st-quality",
      "Calitatea datelor: " + plural(q.journeys || 0, "călătorie", "călătorii") + ", " +
      (q.finished || 0) + " încheiate; întârziere citită la " + (q.delay_known || 0) +
      " (" + pct(q.delay_known_pct) + " din cele încheiate); rezultate: " +
      (st.confirmed || 0) + " confirmate, " + (st.unconfirmed || 0) + " neconfirmate, " +
      (st.unknown || 0) + " necunoscute, " + (st.in_progress || 0) + " în desfășurare.");
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
               tip: b.label + " min: " + plural(b.n, "călătorie", "călătorii") };
    });
    var total = items.reduce(function (a, b) { return a + (b.n || 0); }, 0);
    return barChart({ host: host, items: items, minWidth: 280,
      title: "Distribuția întârzierilor — " + BOARD_PL[board],
      desc: "Număr de călătorii pe intervale de întârziere citită (minute). Total N = " + total + "." });
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
      return navigator.onLine === false ? "Ești offline — statisticile au nevoie de conexiune."
        : "Serverul nu a răspuns. Încearcă din nou peste puțin timp.";
    }
    if (e.status === 422 || e.status === 404) return e.detail || "Parametri invalizi.";
    if (e.status === 429) return "Prea multe cereri — așteaptă câteva secunde.";
    return "Eroare la server (" + (e.status || "?") + "). Încearcă din nou mai târziu.";
  }

  // ---- parameters (persisted in the URL hash) ----------------------------------------

  var FIELD_DEFS = {
    query: { label: "Caută", type: "search", placeholder: "nr. tren, stație sau operator", max: 40 },
    board: { label: "Panou", type: "select" },
    from: { label: "De la (data)", type: "date" },
    to: { label: "Până la (data)", type: "date" },
    prag: { label: "„La timp” ≤ (min)", type: "number", lo: 0, hi: 60, placeholder: "5" },
    min: { label: "Eșantion minim", type: "number", lo: 1, hi: 1000, placeholder: "5" },
    doar_confirmate: { label: "Doar rezultate confirmate", type: "checkbox" },
    q: { label: "Caută stația", type: "search", placeholder: "ex. Galați, Brașov, Aeroport", max: 40 }
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
    form.setAttribute("aria-label", "Filtre");
    form.noValidate = true;
    var inputs = {};
    var timer = null;
    fields.forEach(function (f) {
      var d = FIELD_DEFS[f];
      var lab = el("label", "field st-field st-field-" + f.replace("_", "-"));
      var input;
      if (d.type === "select") {
        input = el("select");
        [["", "Ambele (separat)"], ["arrival", "Sosiri"], ["departure", "Plecări"]].forEach(function (o) {
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
    return "„La timp” = întârziere citită ≤ " + params.on_time_max_min + " min · eșantion minim " +
      params.min_sample + " călătorii" + (params.confirmed_only ? " · doar rezultate confirmate" : "") +
      (params.board ? " · doar " + BOARD_PL[params.board].toLowerCase() : "") +
      (params.from || params.to ? " · perioada " + (params.from ? dayText(params.from) : "început") +
        " – " + (params.to ? dayText(params.to) : "azi") : "");
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
      v.body.setAttribute("aria-live", "polite");
      root.replaceChildren(v.ui.form, v.body);
    }
    function load(force) {
      var url = cfg.url(v);
      if (!url) return;
      if (!force && url === v.key && v.data) return;
      v.key = url;
      if (v.ctrl) v.ctrl.abort();
      var ctrl = new AbortController();
      v.ctrl = ctrl;
      $(cfg.root).classList.add("is-loading");
      if (!v.data) {
        v.body.replaceChildren(el("p", "sr-only", "Se încarcă…"));
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
      ensure();
      v.p = readParams(params, cfg.fields);
      if (cfg.onParams) cfg.onParams(v, params);
      v.ui.set(v.p);
      if (cfg.title) cfg.title(v);
      load(false);
    };
    v.rerender = function () { if (v.data) { v.body.replaceChildren(); cfg.render(v, v.data); paint(); if (U()) U().reveal(v.body); } };
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

  var TR_COLS = [
    { key: "train_no", label: "Tren", get: function (e) { return e.train_no; },
      cell: function (e) { return trainLink(e); }, cls: "st-c-train" },
    { key: "board", label: "Panou", get: function (e) { return e.board; },
      cell: function (e) { return BOARD_ONE[e.board] || e.board; } },
    { key: "station", label: "Stație", get: function (e) { return e.station || ""; },
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
    { key: "journeys", label: "Călătorii", num: true, get: function (e) { return e.journeys; },
      cell: function (e) { return String(e.journeys); } },
    { key: "n", label: "N cu întârziere citită", num: true, get: function (e) { return e.stats.n; },
      cell: function (e) { return String(e.stats.n); } },
    { key: "on_time_pct", label: "% la timp", num: true, get: function (e) { return e.stats.on_time_pct; },
      cell: function (e) {
        var p = e.stats.on_time_pct;
        if (p == null || !U()) return pct(p);
        var c = el("span", "st-cell-meter", pct(p));
        var m = U().meter(p, { tone: p >= 90 ? "ok" : p >= 70 ? "mid" : "bad", label: pct(p) + " la timp" });
        m.classList.add("st-meter");
        c.append(m);
        return c;
      } },
    { key: "trend", label: "Ultimele 14 zile", nosort: true, get: function () { return null; },
      cell: function (e) { return trendCell(e.trend, trHi); } },
    { key: "mean", label: "Medie", num: true, get: function (e) { return e.stats.mean; },
      cell: function (e) { return minutes(e.stats.mean); } },
    { key: "median", label: "Mediană", num: true, get: function (e) { return e.stats.median; },
      cell: function (e) { return minutes(e.stats.median); } },
    { key: "p90", label: "p90", num: true, get: function (e) { return e.stats.p90; },
      cell: function (e) { return minutes(e.stats.p90); } },
    { key: "max", label: "Max", num: true, get: function (e) { return e.stats.max; },
      cell: function (e) { return minutes(e.stats.max); } },
    { key: "over_30", label: "> 30 min", num: true, get: function (e) { return e.stats.over_30; },
      cell: function (e) {
        return e.stats.n ? e.stats.over_30 + (e.stats.over_30_pct != null ? " (" + pct(e.stats.over_30_pct) + ")" : "") : "—";
      } },
    { key: "quality", label: "Calitate date", num: true,
      get: function (e) { return e.quality.delay_known_pct; },
      cell: function (e) {
        var q = e.quality;
        var s = el("span", "st-q", pct(q.delay_known_pct) + " citite");
        s.append(el("span", "st-q-sub", (q.states.confirmed || 0) + " confirmate"));
        s.title = "Întârziere citită la " + q.delay_known + " din " + q.finished +
          " călătorii încheiate; " + (q.states.confirmed || 0) + " cu rezultat confirmat.";
        return s;
      } }
  ];

  // a percentage with a thin bar under it (list rows); „—” stays „—”
  function pctMeter(p) {
    if (p == null || !U()) return pct(p);
    var c = el("span", "st-cell-meter", pct(p));
    var m = U().meter(p, { tone: p >= 90 ? "ok" : p >= 70 ? "mid" : "bad", label: pct(p) + " la timp" });
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

  function renderTrenuri(v, d) {
    var list = Array.isArray(d.trains) ? d.trains : [];
    var params = d.params || {};
    var totalJ = list.reduce(function (a, e) { return a + (e.journeys || 0); }, 0);
    var small = list.filter(function (e) { return e.stats && e.stats.sufficient === false; }).length;

    var head = el("div", "st-bar-head");
    head.append(el("p", "h-count", plural(list.length, "rând", "rânduri") + " (număr de tren × panou) · " +
      plural(totalJ, "călătorie", "călătorii") + " · " + explainParams(params)));
    var q = toSearch(v.p, TR_FIELDS);
    var exp = el("div", "st-exports");
    q.set("format", "csv");
    exp.append(exportLink("Export CSV", "/api/trains/stats?" + q.toString(), true));
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
        { label: "Rânduri tren × panou", value: list.length, sub: plural(totalJ, "călătorie", "călătorii") },
        onTimeTile("La timp · toate trenurile", "arr", pooled, params),
        { label: "Cu eșantion suficient", value: list.length - small, sub: "din " + list.length + " rânduri (N ≥ " + params.min_sample + ")" },
        { label: "Peste 30 min", value: pooled.n ? pooled.over_30 : null, tone: "bad",
          sub: pooled.n ? "din " + pooled.n + " cu întârziere citită" : "N = 0" }]);
    }
    v.body.append(el("p", "st-note",
      "Călătorie = o apariție a trenului pe un panou într-o zi de serviciu; un număr de tren poate avea " +
      "mai multe călătorii. N = călătoriile încheiate cu întârzierea citită (doar ele intră în statistici)."));
    if (small) {
      v.body.append(el("p", "st-warn", small + " din " + list.length + " rânduri au eșantion mic (N < " +
        params.min_sample + "): procentele nu sunt afișate acolo („—”)."));
    }
    if (!list.length) {
      v.body.append(el("p", "empty", v.p.query ? "Niciun tren nu se potrivește căutării." : "Încă nu există trenuri observate."));
      return;
    }

    trHi = trendMax(list);
    var t = scrollTable("Trenuri observate, cu statistici de întârziere");
    var thead = el("thead");
    var hr = el("tr");
    TR_COLS.forEach(function (c) {
      var th = el("th", c.num ? "st-num" : null);
      th.scope = "col";
      if (c.nosort) { th.textContent = c.label; th.title = "Aceeași scară pe tot tabelul"; hr.append(th); return; }
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
    sortEntries(list).forEach(function (e) {
      var tr = el("tr", "st-row");
      if (e.stats && e.stats.sufficient === false) tr.classList.add("st-row-small");
      TR_COLS.forEach(function (c) { td(tr, c.cell(e), (c.num ? "st-num " : "") + (c.cls || "")); });
      tr.addEventListener("click", function (ev) {
        if (ev.target.closest("a, button")) return;
        location.hash = "#tren?nr=" + encodeURIComponent(e.train_no);
      });
      tbody.append(tr);
    });
    t.table.append(thead, tbody);
    v.body.append(t.wrap);
  }

  var trenuri = makeView({
    root: "st-trenuri", route: "trenuri", fields: TR_FIELDS,
    url: function (v) {
      var q = toSearch(v.p, TR_FIELDS).toString();
      return "/api/trains/stats" + (q ? "?" + q : "");
    },
    render: renderTrenuri
  });

  // ---- #tren?nr= ---------------------------------------------------------------------

  var TN_FIELDS = ["prag", "min", "doar_confirmate"];

  function journeyDelay(r) {
    if (!r || !r.delay_known) return el("span", "delay delay-unread", "necitită");
    var d = r.state === "confirmed" ? r.final_delay : r.observed_delay;
    var text = d <= 0 ? "0 min" : "+" + d + " min";
    var s = el("span", "st-jdelay", text);
    if (r.state !== "confirmed") {
      s.append(el("span", "st-jdelay-note", " ultima citită"));
    }
    return s;
  }

  function renderTren(v, d) {
    var entries = Array.isArray(d.entries) ? d.entries : [];
    var params = d.params || {};
    var type = entries.length ? entries[0].train_type : null;
    var name = (type ? type + " " : "") + d.train_no;
    $("tren-heading").textContent = "Tren " + name;
    document.title = "Tren " + name + " · Tabela Gara de Nord";
    var first = null, last = null;
    entries.forEach(function (e) {
      if (!first || e.first_date < first) first = e.first_date;
      if (!last || e.last_date > last) last = e.last_date;
    });
    $("tren-sub").textContent = "Operator: " + ((d.operators || []).filter(Boolean).join(", ") || "necunoscut") +
      " · " + (d.observations == null ? "observații: necunoscut" : plural(d.observations, "observație (citire OCR)", "observații (citiri OCR)")) +
      " · perioada: " + period(first, last);

    var top = el("div", "st-bar-head");
    var back = el("a", "st-back", "← Toate trenurile");
    back.href = "#trenuri";
    top.append(back);
    var q = toSearch(v.p, TN_FIELDS);
    q.set("format", "csv");
    var exp = el("div", "st-exports");
    exp.append(exportLink("Export CSV (călătorii)", "/api/trains/" + encodeURIComponent(d.train_no) +
      "/journeys?" + q.toString(), true));
    top.append(exp);
    v.body.append(top);
    v.body.append(el("p", "h-count", explainParams(params)));

    var cards = el("div", "st-cards");
    v.body.append(cards);
    var jAll = Array.isArray(d.journeys) ? d.journeys : [];
    heroBlock(v, [{ label: "Călătorii observate", value: entries.reduce(function (a, e) { return a + (e.journeys || 0); }, 0),
                      sub: plural(entries.length, "panou", "panouri") + " · " + period(first, last) }]
      .concat(entries.map(function (e) {
        return onTimeTile((BOARD_PL[e.board] || e.board) + " · la timp", e.board === "arrival" ? "arr" : "dep", e.stats, params);
      })));
    entries.forEach(function (e) {
      var card = el("section", "st-card");
      var h = el("h2", "st-card-h");
      h.append(el("span", "st-card-board", BOARD_PL[e.board] || e.board),
               document.createTextNode(" " + BOARD_DIR[e.board] + " "), stationLink(e.station));
      card.append(h);
      card.append(el("p", "st-card-sub", plural(e.journeys, "călătorie", "călătorii") + " · " +
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
          sp.append(el("p", "detail-note", "Întârzierea pe călătorii, de la cele mai vechi la cele mai noi (min)"));
          sp.append(U().spark(series, { w: 240, h: 44, tone: "bad", label: "Întârzierea citită pe călătorii: " +
            series.map(function (x) { return x == null ? "necitită" : x + " min"; }).join(", ") }));
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
        card.append(el("h3", "detail-h", "Distribuția întârzierii citite (N = " + (e.stats.n || 0) + ")"));
        card.append(distChart(card, dist, e.board));
      }
    });

    var js = Array.isArray(d.journeys) ? d.journeys : [];
    var sec = el("section", "st-section");
    sec.append(el("h2", "st-h2", "Călătorii (" + js.length + ")"));
    sec.append(el("p", "st-note", "Cele mai noi primele. Data de serviciu = ziua orei programate. " +
      "Apasă pe o călătorie pentru rezultat, motiv și graficul citirilor."));
    var t = scrollTable("Călătoriile trenului " + name);
    var thead = el("thead");
    var hr = el("tr");
    ["Data de serviciu", "Ora prog.", "Panou", "Stație", "Rezultat", "Întârziere"].forEach(function (x) {
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
      b.setAttribute("aria-label", "Detalii călătorie " + dayText(j.service_date) + " " + (j.sched_time || ""));
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
      $("tren-heading").textContent = v.nr ? "Tren " + v.nr : "Tren";
      $("tren-sub").textContent = "";
    },
    url: function (v) {
      if (!/^\d{1,6}$/.test(v.nr || "") || parseInt(v.nr, 10) === 0) {
        v.data = null;
        v.key = null;
        v.body.replaceChildren(notice("Număr de tren invalid. Alege un tren din lista de trenuri.", "notice-error"));
        return null;
      }
      var q = toSearch(v.p, TN_FIELDS).toString();
      return "/api/trains/" + encodeURIComponent(parseInt(v.nr, 10)) + "/journeys" + (q ? "?" + q : "");
    },
    errorText: function (e) {
      return e.status === 404 ? "Trenul nu a fost observat pe tabelă (pentru filtrele alese)." : errorText(e);
    },
    render: renderTren
  });

  // ---- per-hour / weekday / month charts (shared by #statie) -----------------------

  function groupItems(groups, labelFn) {
    return (groups || []).map(function (g) {
      var label = labelFn(g);
      return { label: label, value: g.mean, n: g.n, low: g.n > 0 && g.sufficient === false,
               valueText: g.mean == null ? null : numFmt.format(Math.round(g.mean)),
               tip: label + ": medie " + minutes(g.mean) + ", N = " + g.n +
                    (g.n && g.sufficient === false ? " (eșantion mic)" : "") };
    });
  }

  var DIMS = [
    { key: "hour", title: "Pe oră (ora programată)", minWidth: 600,
      label: function (g) { return (g.key < 10 ? "0" : "") + g.key; } },
    { key: "weekday", title: "Pe zi a săptămânii (data de serviciu)", minWidth: 300,
      label: function (g) { return String(g.label || g.key).slice(0, 3); } },
    { key: "month", title: "Pe lună", minWidth: 240, label: function (g) { return monthText(g.key); } }
  ];

  // Charts per hour / weekday / month, one card per board (shared with #statie).
  function timeSections(host, byTime, boards, params, labels) {
    DIMS.forEach(function (dim) {
      var sec = el("section", "st-section");
      sec.append(el("h2", "st-h2", dim.title));
      sec.append(el("p", "st-note", "Bara = întârzierea medie citită (minute); sub fiecare bară: N călătorii. " +
        "Barele estompate au eșantion mic (N < " + params.min_sample + ")."));
      var grid = el("div", "st-cards");
      sec.append(grid);
      host.append(sec);
      boards.forEach(function (b) {
        var groups = byTime && byTime[b] && byTime[b][dim.key];
        var card = el("div", "st-card st-card-chart");
        card.append(el("h3", "detail-h", labels[b]));
        grid.append(card);
        if (!groups || !groups.length) {
          card.append(el("p", "detail-note", "Nu există date."));
          return;
        }
        card.append(barChart({ host: card, items: groupItems(groups, dim.label), minWidth: dim.minWidth,
          showN: true, unit: "min",
          title: dim.title + " — " + labels[b],
          desc: "Întârzierea medie citită pe tabela de la București Nord, cu N călătorii pentru fiecare bară." }));
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
    sec.append(el("h2", "st-h2", title + " — primele " + Math.min(3, list.length)));
    var row = el("ol", "st-podium");
    list.slice(0, 3).forEach(function (e, i) {
      var li = el("li", "st-podium-card st-pod-" + (i + 1));
      var rank = el("span", "st-pod-rank", String(i + 1));
      rank.setAttribute("aria-label", "Locul " + (i + 1));
      var link = trainLink(e);
      link.classList.add("st-pod-train");
      var fig = el("p", "st-pod-fig");
      if (by === "pct" && e.stats.on_time_pct != null) {
        U().countUp(fig, e.stats.on_time_pct, function (x) { return numFmt.format(Math.round(x * 10) / 10) + " %"; });
      } else if (e.stats.mean != null) {
        U().countUp(fig, e.stats.mean, function (x) { return numFmt.format(Math.round(x * 10) / 10) + " min"; });
      } else fig.textContent = "—";
      var top = el("div", "st-pod-top");
      top.append(rank, link);
      li.append(top, fig, el("p", "st-pod-lab", by === "pct" ? "la timp" : "întârziere medie"));
      var meta = el("p", "st-pod-meta");
      meta.append((BOARD_ONE[e.board] || e.board) + " · ", stationLink(e.station), " · N = " + e.stats.n);
      li.append(meta);
      if (by === "pct" && e.stats.on_time_pct != null) {
        li.append(U().meter(e.stats.on_time_pct, { tone: "ok", label: pct(e.stats.on_time_pct) + " la timp" }));
      }
      var sp = trendCell(e.trend, trendMax(list), { w: 120, h: 28, compact: false });
      if (!sp.classList.contains("ui-spark-none")) {
        sp.classList.add("st-pod-spark");
        li.append(el("p", "st-pod-lab st-pod-lab2", "ultimele 14 zile (min)"), sp);
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
      sec.append(el("p", "detail-note", "Niciun tren eligibil."));
      return sec;
    }
    var t = scrollTable(title);
    var thead = el("thead");
    var hr = el("tr");
    var hi = trendMax(list);
    [["#", true], ["Tren", false], ["Panou", false], ["Stație", false], ["N", true], ["Medie", true],
     ["Mediană", true], ["% la timp", true], ["Ultimele 14 zile", false]].forEach(function (h) {
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
    head.append(el("p", "h-count", plural(d.eligible || 0, "tren eligibil", "trenuri eligibile") +
      " (număr × panou, cu cel puțin " + params.min_sample + " călătorii cu întârziere citită) · " +
      (d.below_min || 0) + " sub prag · " + explainParams(params)));
    var q = toSearch(v.p, CL_FIELDS);
    q.set("limit", String(RANK_LIMIT));
    q.set("format", "csv");
    var exp = el("div", "st-exports");
    exp.append(exportLink("Export CSV", "/api/stats/rankings?" + q.toString(), true));
    head.append(exp);
    v.body.append(head);
    if (!d.eligible) {
      v.body.append(el("p", "st-warn", "Încă nu există trenuri cu cel puțin " + params.min_sample +
        " călătorii cu întârziere citită pentru filtrele alese. " +
        plural(d.below_min || 0, "tren are", "trenuri au") + " date, dar sub prag — nu le clasăm, " +
        "pentru că un eșantion atât de mic nu spune nimic sigur."));
    } else {
      heroBlock(v, [{ label: "Trenuri eligibile", value: d.eligible || 0, sub: "N ≥ " + params.min_sample + " călătorii cu întârziere citită" },
                    { label: "Sub prag", value: d.below_min || 0, sub: "nu sunt clasate" }]);
      podium(v.body, "Cele mai punctuale", d.most_punctual || [], "pct");
      podium(v.body, "Cele mai întârziate", d.most_delayed || [], "mean");
      v.body.append(rankTable("Cele mai întârziate", d.most_delayed || []));
      v.body.append(rankTable("Cele mai punctuale", d.most_punctual || []));
      v.body.append(el("p", "st-note", "Ordine: „cele mai întârziate” după întârzierea medie citită (apoi " +
        "mediana); „cele mai punctuale” după % la timp (apoi media). N = călătorii încheiate cu " +
        "întârzierea citită pe tabela de la București Nord."));
    }
    renderRankStations(d.stations, params);
  }

  function stationRankTable(title, list) {
    var sec = el("section", "st-subsection");
    sec.append(el("h3", "st-h3", title));
    if (!list.length) {
      sec.append(el("p", "detail-note", "Nicio stație eligibilă."));
      return sec;
    }
    var t = scrollTable("Stații — " + title.toLowerCase());
    var thead = el("thead");
    var hr = el("tr");
    var hi = trendMax(list);
    [["#", true], ["Stație", false], ["Panou", false], ["N", true], ["Călătorii", true], ["Trenuri", true],
     ["Medie", true], ["Mediană", true], ["% la timp", true], ["Ultimele 14 zile", false]].forEach(function (h) {
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
    sec.append(el("h2", "st-h2", "Clasamentul stațiilor"));
    sec.append(el("p", "h-count", plural(st.eligible || 0, "stație eligibilă", "stații eligibile") +
      " (stație × panou, cu cel puțin " + params.min_sample + " călătorii cu întârziere citită) · " +
      (st.below_min || 0) + " sub prag"));
    sec.append(el("p", "st-note", "Stația = originea (la sosiri) sau destinația (la plecări) afișată pe " +
      "tabelă. Întârzierea este cea citită pe tabela de la București Nord, nu cea de la stație. " +
      "Sosirile și plecările sunt clasate separat (coloana „Panou”)."));
    if (!st.eligible) {
      sec.append(el("p", "st-warn", "Încă nu există stații cu cel puțin " + params.min_sample +
        " călătorii cu întârziere citită pentru filtrele alese. " +
        plural(st.below_min || 0, "stație are", "stații au") + " date, dar sub prag — nu le clasăm."));
    } else {
      sec.append(stationRankTable("Cele mai întârziate", st.most_delayed || []));
      sec.append(stationRankTable("Cele mai punctuale", st.most_punctual || []));
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
    var head = el("div", "st-bar-head");
    var total = list.reduce(function (a, s) { return a + (s.journeys || 0); }, 0);
    head.append(el("p", "h-count", plural(list.length, "stație", "stații") +
      (v.p.q ? " pentru „" + v.p.q + "”" : "") + " · " + plural(total, "călătorie", "călătorii")));
    var q = new URLSearchParams();
    if (v.p.q) q.set("query", v.p.q);
    q.set("limit", String(SL_LIMIT));
    var exp = el("div", "st-exports");
    q.set("format", "csv");
    exp.append(exportLink("Export CSV", "/api/stations?" + q.toString(), true));
    q.delete("format");
    exp.append(exportLink("JSON", "/api/stations?" + q.toString(), false));
    head.append(exp);
    v.body.append(head);
    v.body.append(el("p", "st-note", "Stația = originea (la sosiri) sau destinația (la plecări) afișată pe " +
      "tabela din Gara de Nord. Întârzierile din paginile stațiilor sunt cele citite la București Nord, " +
      "nu la stație. „Nume nesigur” = numele a fost citit doar nesigur (OCR) pe tabelă."));
    if (!list.length) {
      v.body.append(el("p", "empty", v.p.q ? "Nicio stație nu se potrivește căutării." : "Încă nu există stații observate."));
      return;
    }
    var arr = list.reduce(function (a, x) { return a + (x.arrivals || 0); }, 0);
    var dep = list.reduce(function (a, x) { return a + (x.departures || 0); }, 0);
    var busiest = list.slice().sort(function (a, b) { return (b.journeys || 0) - (a.journeys || 0); })[0];
    heroBlock(v, [
      { label: "Stații observate", value: list.length, sub: v.p.q ? "pentru „" + v.p.q + "”" : "pe tabela din Gara de Nord" },
      { label: "Călătorii", value: total, sub: plural(arr, "sosire", "sosiri") + " · " + plural(dep, "plecare", "plecări") },
      { label: "Cea mai aglomerată", cls: "ui-stat-name", text: titleCase(busiest.name),
        sub: plural(busiest.journeys || 0, "călătorie", "călătorii") + " · " + plural(busiest.trains || 0, "tren", "trenuri") }]);
    if (U() && arr + dep > 0) {
      var card = el("section", "st-card st-share-card");
      card.append(el("h2", "st-card-h", "Sosiri și plecări"));
      card.append(el("p", "st-card-sub", "partea fiecărui panou din toate călătoriile din listă"));
      U().donut(card, { title: "Sosiri și plecări, toate stațiile", valueUnit: "călătorii", showPct: arr + dep >= 5,
        desc: "Sosiri " + arr + ", plecări " + dep + " (N = " + (arr + dep) + ").",
        centerValue: numFmt.format(arr + dep), centerLabel: "călătorii (N)",
        segments: [{ label: "Sosiri", value: arr, slot: "arr" }, { label: "Plecări", value: dep, slot: "dep" }] });
      v.body.append(card);
    }
    var t = scrollTable("Stații observate pe tabelă");
    var thead = el("thead");
    var hr = el("tr");
    [["Stație", false], ["Călătorii", true], ["Sosiri", true], ["Plecări", true], ["Trenuri", true],
     ["Cu întârziere citită", true], ["Perioada", false]].forEach(function (h) {
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
      if (s.uncertain_only) c.append(el("span", "st-tag", "nume nesigur"));
      td(tr, c);
      var jc = el("span", "st-cell-meter", String(s.journeys == null ? "—" : s.journeys));
      if (U() && s.arrivals != null && s.departures != null) {
        var sm = U().split(s.arrivals, s.departures, { label: plural(s.arrivals, "sosire", "sosiri") + ", " + plural(s.departures, "plecare", "plecări") });
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
      v.body.append(el("p", "st-note", "Se afișează primele " + SL_LIMIT + " stații — restrânge căutarea."));
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
    render: renderStatii
  });

  // ---- #statie?nume= -------------------------------------------------------------------

  var SN_FIELDS = ["board", "from", "to", "prag", "min", "doar_confirmate"];
  var JR_PAGE = 50;
  var BOARD_TOWARD = { arrival: "Sosiri dinspre stație", departure: "Plecări înspre stație" };
  var stampFmt = new Intl.DateTimeFormat("ro-RO", { timeZone: "Europe/Bucharest", day: "numeric",
    month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });

  function stamp(ts) {
    if (!ts) return "necunoscut";
    var d = new Date(ts);
    return isNaN(d.getTime()) ? String(ts) : stampFmt.format(d);
  }

  function stationApi(name) { return "/api/stations/" + encodeURIComponent(name); }

  function rankLine(rank, s, params, board) {
    if (rank && rank.position != null) {
      return el("p", "st-rankline", "Locul " + rank.position + " din " + rank.of + " stații (" +
        BOARD_PL[board].toLowerCase() + ") cu ≥ " + params.min_sample +
        " călătorii cu întârziere citită · locul 1 = cea mai întârziată.");
    }
    var n = s && s.n != null ? s.n : 0;
    return el("p", "st-rankline st-rankline-out", "Nu intră în clasamentul stațiilor: " +
      (n < params.min_sample ? "sub eșantionul minim (N = " + n + " < " + params.min_sample + ")."
        : "nu este eligibilă pentru filtrele alese."));
  }

  function stationTrainsTable(list, name, board) {
    var cap = "Trenuri — " + BOARD_PL[board].toLowerCase() + " " + BOARD_DIR[board] + " " + titleCase(name);
    var t = scrollTable(cap);
    var thead = el("thead");
    var hr = el("tr");
    var hi = trendMax(list);
    [["Tren", false], ["Operator", false], ["Călătorii", true], ["N", true], ["Medie", true],
     ["Mediană", true], ["p90", true], ["Max", true], ["% la timp", true], ["Ultimele 14 zile", false], ["Ultima zi", false]].forEach(function (h) {
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
      td(tr, e.operator || "necunoscut");
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
    b.setAttribute("aria-label", "Detalii călătorie " + (j.train_type || "") + " " + j.train_no + ", " +
      dayText(j.service_date) + " " + (j.sched_time || ""));
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
    td(tr, j.operator || "necunoscut");
    td(tr, resultBadge(j.result));
    td(tr, journeyDelay(j.result), "st-num");
    if (j.uncertain) tr.title = "Numele stației/operatorului citit nesigur";
    tr.addEventListener("click", function (ev) { if (!ev.target.closest("a, button")) open(); });
    return tr;
  }

  function jrPaint(v) {
    var jr = v.jr;
    var dom = jr && jr.dom;
    if (!dom) return;
    dom.tbody.replaceChildren.apply(dom.tbody, jr.items.map(jrRow));
    dom.wrap.hidden = !jr.items.length;
    dom.count.textContent = jr.items.length ? "Afișate: " + plural(jr.items.length, "călătorie", "călătorii") +
      (jr.next == null && jr.loaded ? " (toate)" : "") : "";
    dom.more.hidden = jr.next == null;
    dom.more.disabled = jr.loading;
    dom.status.textContent = jr.loading ? "Se încarcă…" : jr.error ? jr.error
      : jr.loaded && !jr.items.length ? "Nicio călătorie pentru această stație." : "";
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
    sec.append(el("h2", "st-h2", "Ultimele călătorii"));
    sec.append(el("p", "st-note", "Cele mai noi primele" + (board ? " · doar " + BOARD_PL[board].toLowerCase() : "") +
      " (fără filtrul de perioadă). Apasă pe o călătorie pentru rezultat, motiv și graficul citirilor."));
    var count = el("p", "h-count");
    var t = scrollTable("Ultimele călătorii — " + titleCase(name));
    var thead = el("thead");
    var hr = el("tr");
    ["Data de serviciu", "Ora prog.", "Panou", "Tren", "Operator", "Rezultat", "Întârziere"].forEach(function (x) {
      var th = el("th", null, x);
      th.scope = "col";
      hr.append(th);
    });
    thead.append(hr);
    var tbody = el("tbody");
    t.table.append(thead, tbody);
    var more = el("button", "btn btn-ghost btn-sm st-more-btn", "Mai multe călătorii");
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
    stationHeading("Stația " + nice,
      plural(d.journeys || 0, "călătorie", "călătorii") + " · " + plural(d.trains || 0, "tren", "trenuri") +
      " · perioada: " + (d.period ? period(d.period.first, d.period.last) : "—") +
      (d.period && d.period.days ? " (" + plural(d.period.days, "zi cu date", "zile cu date") + ")" : "") +
      " · prima observație: " + stamp(d.first_seen) + " · ultima: " + stamp(d.last_seen));
    document.title = "Stația " + nice + " · Tabela Gara de Nord";

    var bd = BOARDS.filter(function (b) { return d.boards && d.boards[b]; });
    heroBlock(v, [{ label: "Călătorii", value: d.journeys || 0, sub: plural(d.trains || 0, "tren", "trenuri") },
      { label: "Zile cu date", value: d.period && d.period.days ? d.period.days : 0, sub: d.period ? period(d.period.first, d.period.last) : "—" }]
      .concat(bd.map(function (b) {
        return onTimeTile((b === "arrival" ? "Sosiri" : "Plecări") + " · la timp", b === "arrival" ? "arr" : "dep", d.boards[b].stats, params);
      })));
    var warn = el("p", "st-warn st-station-note");
    warn.setAttribute("role", "note");
    warn.append(el("strong", null, "Atenție: "), document.createTextNode(d.note ||
      "Întârzierea este cea afișată pe tabela din București Nord, nu la stație."));
    v.body.append(warn);

    var top = el("div", "st-bar-head");
    var back = el("a", "st-back", "← Toate stațiile");
    back.href = "#statii";
    top.append(back);
    var q = toSearch(v.p, SN_FIELDS);
    var exp = el("div", "st-exports");
    q.set("format", "csv");
    exp.append(exportLink("Export CSV (trenuri)", stationApi(name) + "?" + q.toString(), true));
    var jq = new URLSearchParams();
    if (v.p.board) jq.set("board", v.p.board);
    jq.set("limit", "500");
    jq.set("format", "csv");
    exp.append(exportLink("Export CSV (călătorii)", stationApi(name) + "/journeys?" + jq.toString(), true));
    q.delete("format");
    exp.append(exportLink("JSON", stationApi(name) + (q.toString() ? "?" + q.toString() : ""), false));
    top.append(exp);
    v.body.append(top);
    v.body.append(el("p", "h-count", explainParams(params)));
    v.body.append(qualityLine(d.quality));
    if (d.uncertain_names) {
      v.body.append(el("p", "st-note", plural(d.uncertain_names, "călătorie are", "călătorii au") +
        " numele stației sau al operatorului citit nesigur (OCR)."));
    }

    var boards = BOARDS.filter(function (b) { return d.boards && d.boards[b]; });
    var cards = el("div", "st-cards");
    v.body.append(cards);
    boards.forEach(function (b) {
      var x = d.boards[b];
      var s = x.stats || {};
      var card = el("section", "st-card");
      card.append(el("h2", "st-card-h st-card-board", BOARD_TOWARD[b]));
      card.append(el("p", "st-card-sub", plural(x.journeys || 0, "călătorie", "călătorii") + " · " +
        (b === "arrival" ? "trenuri care vin din " : "trenuri care pleacă spre ") + nice));
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
        card.append(el("h3", "detail-h", "Distribuția întârzierii citite (N = " + (s.n || 0) + ")"));
        card.append(distChart(card, x.distribution, b));
      }
      cards.append(card);
    });

    boards.forEach(function (b) {
      var list = Array.isArray(d.boards[b].trains) ? d.boards[b].trains : [];
      var sec = el("section", "st-section");
      sec.append(el("h2", "st-h2", "Trenuri — " + BOARD_TOWARD[b].toLowerCase() + " (" + list.length + ")"));
      if (!list.length) sec.append(el("p", "detail-note", "Niciun tren."));
      else sec.append(stationTrainsTable(list, name, b));
      v.body.append(sec);
    });

    timeSections(v.body, d.by_time, boards, params, BOARD_TOWARD);
    v.body.append(journeysSection(v, name));
  }

  function stationMissing(text) {
    var box = el("div", "notice notice-error st-missing");
    box.append(el("p", null, text));
    var a = el("a", "st-back", "Vezi lista stațiilor →");
    a.href = "#statii";
    box.append(a);
    return box;
  }

  var statie = makeView({
    charts: true, root: "st-statie", route: "statie", fields: SN_FIELDS,
    onParams: function (v, params) { v.nume = (params.get("nume") || "").trim().slice(0, 40); },
    hashExtra: function (v) { return v.nume ? { nume: v.nume } : null; },
    title: function (v) {
      stationHeading(v.nume ? "Stația " + titleCase(v.nume) : "Stație", "");
      if (v.nume) document.title = "Stația " + titleCase(v.nume) + " · Tabela Gara de Nord";
    },
    url: function (v) {
      if (!v.nume) {
        v.data = null;
        v.key = null;
        v.body.replaceChildren(stationMissing("Nicio stație aleasă."));
        return null;
      }
      var q = toSearch(v.p, SN_FIELDS).toString();
      return stationApi(v.nume) + (q ? "?" + q : "");
    },
    errorNode: function (v, e) {
      if (e.status === 404) {
        stationHeading("Stație necunoscută", "");
        return stationMissing("Stația nu a fost observată pe tabelă" + (v.nume ? " („" + v.nume + "”)." : "."));
      }
      if (e.status === 422) return stationMissing("Nume de stație invalid.");
      return notice(errorText(e), "notice-error");
    },
    render: renderStatie
  });

  App.views.trenuri = { show: trenuri.show };
  App.views.tren = { show: tren.show };
  App.views.clasamente = { show: clasamente.show };
  App.views.statii = { show: statii.show };
  App.views.statie = { show: statie.show };
  // shared with statistici.js (#statistici, Statistici v2)
  App.stats = { stationLink: stationLink, barChart: barChart, statsGrid: statsGrid, sampleWarn: sampleWarn,
                getJSON: getJSON, errorText: errorText, plural: plural, titleCase: titleCase,
                dayText: dayText, numFmt: numFmt, svg: svg, notice: notice };
})();
