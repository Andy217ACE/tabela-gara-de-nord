// © 2026 Andy217Ace
// Tabela Gara de Nord — Trenuri (#trenuri), profil tren (#tren?nr=), Statistici
// (#statistici), Clasamente (#clasamente). Data: /api/trains/stats, /api/trains/{no}/journeys,
// /api/stats, /api/stats/rankings. Every delay is the one READ on the București Nord board;
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
                            role: "img", "aria-labelledby": id + "-t " + id + "-d" });
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
      var g = svg("g", { class: "st-bar-g" });
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
    doar_confirmate: { label: "Doar rezultate confirmate", type: "checkbox" }
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
    var s = toSearch(p, fields);
    Object.keys(extra || {}).forEach(function (k) { s.set(k, extra[k]); });
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
      if (!v.data) v.body.replaceChildren(el("p", "detail-note", "Se încarcă…"));
      getJSON(url, ctrl)
        .then(function (data) {
          if (v.ctrl !== ctrl) return;
          v.data = data;
          v.body.replaceChildren();
          cfg.render(v, data);
        })
        .catch(function (e) {
          if (v.ctrl !== ctrl || e.aborted) return;
          v.data = null;
          v.key = null;
          v.body.replaceChildren(notice(cfg.errorText ? cfg.errorText(e) : errorText(e), "notice-error"));
        })
        .then(function () {
          if (v.ctrl === ctrl) { v.ctrl = null; $(cfg.root).classList.remove("is-loading"); }
        });
    }
    v.load = load;
    v.show = function (params) {
      ensure();
      v.p = readParams(params, cfg.fields);
      if (cfg.onParams) cfg.onParams(v, params);
      v.ui.set(v.p);
      if (cfg.title) cfg.title(v);
      load(false);
    };
    v.rerender = function () { if (v.data) { v.body.replaceChildren(); cfg.render(v, v.data); } };
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
      cell: function (e) { return pct(e.stats.on_time_pct); } },
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

    var t = scrollTable("Trenuri observate, cu statistici de întârziere");
    var thead = el("thead");
    var hr = el("tr");
    TR_COLS.forEach(function (c) {
      var th = el("th", c.num ? "st-num" : null);
      th.scope = "col";
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
    entries.forEach(function (e) {
      var card = el("section", "st-card");
      var h = el("h2", "st-card-h");
      h.append(el("span", "st-card-board", BOARD_PL[e.board] || e.board),
               document.createTextNode(" " + BOARD_DIR[e.board] + " "), stationLink(e.station));
      card.append(h);
      card.append(el("p", "st-card-sub", plural(e.journeys, "călătorie", "călătorii") + " · " +
        period(e.first_date, e.last_date)));
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
    root: "st-tren", route: "tren", fields: TN_FIELDS,
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

  // ---- #statistici -------------------------------------------------------------------

  var SS_FIELDS = ["board", "from", "to", "doar_confirmate", "prag", "min"];

  function tile(box, label, value, sub) {
    var t = el("div", "st-tile");
    t.append(el("span", "st-tile-label", label), el("span", "st-tile-value", value));
    if (sub) t.append(el("span", "st-tile-sub", sub));
    box.append(t);
  }

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

  function renderStatistici(v, d) {
    var params = d.params || {};
    var q = d.quality || {};
    var st = q.states || {};
    var boards = BOARDS.filter(function (b) { return d.boards && d.boards[b]; });

    v.body.append(el("p", "h-count", explainParams(params)));

    var tiles = el("div", "st-tiles");
    tile(tiles, "Perioada", d.period ? period(d.period.first, d.period.last) : "—",
         d.period ? plural(d.period.days || 0, "zi cu date", "zile cu date") : null);
    tile(tiles, "Călătorii", String(q.journeys || 0), (q.finished || 0) + " încheiate");
    tile(tiles, "Trenuri (numere)", String(d.trains == null ? "—" : d.trains));
    tile(tiles, "Observații (citiri OCR)", d.observations == null ? "necunoscut" : String(d.observations));
    tile(tiles, "Întârziere citită", String(q.delay_known || 0), pct(q.delay_known_pct) + " din cele încheiate");
    v.body.append(tiles);

    var qs = el("section", "st-section");
    qs.append(el("h2", "st-h2", "Calitatea datelor"));
    var ul = el("ul", "st-states");
    ["confirmed", "unconfirmed", "unknown", "in_progress"].forEach(function (k) {
      var li = el("li");
      li.append(el("span", "res-badge " + STATE_CLASS[k], STATE_TEXT[k]), el("strong", null, String(st[k] || 0)));
      ul.append(li);
    });
    qs.append(ul);
    qs.append(el("p", "st-note", (q.uncertain_names || 0) + " călătorii au numele stației/operatorului citit nesigur."));
    qs.append(el("p", "st-warn",
      "Înainte de Beta 1.04 citirea întârzierii nu era înregistrată pe fiecare călătorie: pentru majoritatea " +
      "călătoriilor de atunci întârzierea este „necunoscută” (nu 0) și nu intră în statistici. Doar cele cu " +
      "citiri păstrate în observațiile OCR (din Beta 1.01) sunt folosite."));
    v.body.append(qs);

    var cards = el("div", "st-cards");
    v.body.append(cards);
    boards.forEach(function (b) {
      var s = d.boards[b];
      var card = el("section", "st-card");
      card.append(el("h2", "st-card-h", BOARD_PL[b]));
      card.append(statsGrid(s, params));
      var w = sampleWarn(s, params);
      if (w) card.append(w);
      cards.append(card);
      var dist = d.distribution && d.distribution[b];
      if (dist) {
        card.append(el("h3", "detail-h", "Distribuția întârzierii citite (N = " + (s.n || 0) + ")"));
        card.append(distChart(card, dist, b));
      }
    });

    DIMS.forEach(function (dim) {
      var sec = el("section", "st-section");
      sec.append(el("h2", "st-h2", dim.title));
      sec.append(el("p", "st-note", "Bara = întârzierea medie citită (minute); sub fiecare bară: N călătorii. " +
        "Barele estompate au eșantion mic (N < " + params.min_sample + ")."));
      var grid = el("div", "st-cards");
      sec.append(grid);
      v.body.append(sec);
      boards.forEach(function (b) {
        var groups = d.by_time && d.by_time[b] && d.by_time[b][dim.key];
        var card = el("div", "st-card st-card-chart");
        card.append(el("h3", "detail-h", BOARD_PL[b]));
        grid.append(card);
        if (!groups || !groups.length) {
          card.append(el("p", "detail-note", "Nu există date."));
          return;
        }
        card.append(barChart({ host: card, items: groupItems(groups, dim.label), minWidth: dim.minWidth,
          showN: true, unit: "min",
          title: dim.title + " — " + BOARD_PL[b],
          desc: "Întârzierea medie citită pe tabela de la București Nord, cu N călătorii pentru fiecare bară." }));
      });
    });

    var note = el("section", "st-section st-explain");
    note.append(el("h2", "st-h2", "Cum citești aceste cifre"));
    [
      "Întârzierea este cea CITITĂ pe tabela de la București Nord (nu ora reală de sosire/plecare). " +
        "Intră în statistici doar călătoriile încheiate (dispărute de pe tabelă) cu întârzierea citită.",
      "Confirmat = dispariția de pe tabelă a fost observată după ora estimată (programat + întârziere), iar " +
        "întârzierea a fost citită cu cel mult " + (params.final_read_max_gap_min || 15) +
        " min înainte. Altfel rezultatul e neconfirmat (sau necunoscut, dacă întârzierea nu a fost citită niciodată).",
      "„La timp” = întârziere citită ≤ prag (acum " + params.on_time_max_min + " min). p90 = 90% dintre " +
        "călătorii au avut cel mult această întârziere.",
      "Eșantion minim (acum " + params.min_sample + "): sub el nu afișăm procente și p90, doar media, " +
        "mediana, maximul și N.",
      "Călătorie = o apariție pe un panou într-o zi de serviciu; tren = număr de tren; observație = o citire " +
        "OCR a tabelei. Sosirile și plecările sunt mereu separate."
    ].forEach(function (t) { note.append(el("p", "st-note", t)); });
    v.body.append(note);
  }

  var statistici = makeView({
    root: "st-statistici", route: "statistici", fields: SS_FIELDS,
    url: function (v) {
      var q = toSearch(v.p, SS_FIELDS).toString();
      return "/api/stats" + (q ? "?" + q : "");
    },
    render: renderStatistici
  });

  // ---- #clasamente -------------------------------------------------------------------

  var CL_FIELDS = ["board", "from", "to", "doar_confirmate", "prag", "min"];
  var RANK_LIMIT = 10;

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
    [["#", true], ["Tren", false], ["Panou", false], ["Stație", false], ["N", true], ["Medie", true],
     ["Mediană", true], ["% la timp", true]].forEach(function (h) {
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
      td(tr, pct(e.stats.on_time_pct), "st-num");
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
      return;
    }
    v.body.append(rankTable("Cele mai întârziate", d.most_delayed || []));
    v.body.append(rankTable("Cele mai punctuale", d.most_punctual || []));
    v.body.append(el("p", "st-note", "Ordine: „cele mai întârziate” după întârzierea medie citită (apoi " +
      "mediana); „cele mai punctuale” după % la timp (apoi media). N = călătorii încheiate cu " +
      "întârzierea citită pe tabela de la București Nord."));
  }

  var clasamente = makeView({
    root: "st-clasamente", route: "clasamente", fields: CL_FIELDS,
    url: function (v) {
      var q = toSearch(v.p, CL_FIELDS);
      q.set("limit", String(RANK_LIMIT));
      return "/api/stats/rankings?" + q.toString();
    },
    render: renderClasamente
  });

  App.views.trenuri = { show: trenuri.show };
  App.views.tren = { show: tren.show };
  App.views.statistici = { show: statistici.show };
  App.views.clasamente = { show: clasamente.show };
  App.stats = { stationLink: stationLink, barChart: barChart, statsGrid: statsGrid, sampleWarn: sampleWarn };
})();
