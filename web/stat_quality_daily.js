// © 2026 Andy217Ace
// Tabela Gara de Nord — „Calitatea datelor pe zi” (doar admin, în pagina #sistem):
//   1. rata de confirmare a călătoriilor pe zi   GET /api/admin/quality-daily/confirmation
//   2. calitatea citirii pe zi                   GET /api/admin/quality-daily/reading
//   3. acoperirea panoului pe oră (capturi/60)   GET /api/admin/quality-daily/coverage
// DOM doar cu createElement/textContent (CSP: fără stiluri sau scripturi inline); barele și
// harta orară sunt SVG cu atribute, culorile vin din clase (stat_quality_daily.css).
"use strict";

(function () {
  var App = window.TabelaApp = window.TabelaApp || {};
  var SVG = "http://www.w3.org/2000/svg";
  var tt = function (k, p) { return window.I18N.t(k, p); };
  var nfCache = {};
  function nfmt(v) {   // Intl in the chosen language: English 12.5, Romanian 12,5
    var l = window.I18N.lang();
    nfCache[l] = nfCache[l] || new Intl.NumberFormat(l, { maximumFractionDigits: 2 });
    return nfCache[l].format(v);
  }
  var dfCache = {};

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function svg(tag, attrs, cls) {
    var n = document.createElementNS(SVG, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (cls) n.setAttribute("class", cls);
    return n;
  }

  function fetchJson(url) {
    return fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      });
  }

  function pct(v) { return v == null ? "—" : tt("stats.fmt.pct", { v: nfmt(v) }); }

  function dateRo(iso) {  // 2026-10-20 -> 20.10.2026 (ro) / 10/20/2026 (en): Intl in the chosen language
    var l = window.I18N.lang();
    dfCache[l] = dfCache[l] || new Intl.DateTimeFormat(l, { day: "2-digit", month: "2-digit", year: "numeric", timeZone: "UTC" });
    return dfCache[l].format(new Date(iso + "T00:00:00Z"));
  }

  function trendText(t) {
    if (!t || t.direction === "unknown") return tt("stats.qd.trend.unknown") + tt("stats.qd.trend.few");
    var d = t.delta_pp > 0 ? "+" + nfmt(t.delta_pp) : nfmt(t.delta_pp);
    return tt("stats.qd.trend." + t.direction) + tt("stats.qd.trend.pp", { d: d });
  }

  function card(title, intro) {
    var c = el("section", "sqd-card");
    c.appendChild(el("h3", "sqd-title", title));
    c.appendChild(el("p", "sqd-intro", intro));
    return c;
  }

  // one stacked bar: parts = [[value, cssClass], ...], rendered as <rect> with x/width attributes
  function stackBar(parts, label) {
    var total = parts.reduce(function (a, p) { return a + p[0]; }, 0);
    var s = svg("svg", { viewBox: "0 0 100 10", preserveAspectRatio: "none", role: "img",
                         "aria-label": label }, "sqd-bar");
    s.appendChild(svg("rect", { x: 0, y: 0, width: 100, height: 10 }, "sqd-bar-bg"));
    var x = 0;
    if (total > 0) parts.forEach(function (p) {
      var w = 100 * p[0] / total;
      if (w <= 0) return;
      s.appendChild(svg("rect", { x: x.toFixed(2), y: 0, width: w.toFixed(2), height: 10 }, p[1]));
      x += w;
    });
    return s;
  }

  function table(headers, rows, caption) {
    var wrap = el("div", "sqd-scroll");
    var t = el("table", "sqd-table");
    t.appendChild(el("caption", "sqd-sr", caption));
    var tr = el("tr");
    headers.forEach(function (h) {
      var th = el("th", null, h);
      th.scope = "col";
      tr.appendChild(th);
    });
    t.appendChild(el("thead")).appendChild(tr);
    var tb = el("tbody");
    rows.forEach(function (r) {
      var row = el("tr", r.cls || null);
      r.cells.forEach(function (c, i) {
        var td = el(i === 0 ? "th" : "td");
        if (i === 0) td.scope = "row";
        if (c instanceof Node) td.appendChild(c); else td.textContent = c;
        row.appendChild(td);
      });
      tb.appendChild(row);
    });
    t.appendChild(tb);
    wrap.appendChild(t);
    return wrap;
  }

  function dayLabel(d) {
    var s = dateRo(d.date);
    return d.partial ? s + tt("stats.qd.partial_day") : s;
  }

  function note(text, cls) { return el("p", cls || "sqd-note", text); }

  // -- 1 --------------------------------------------------------------------------
  function renderConfirmation(box, d) {
    box.replaceChildren();
    box.appendChild(note(tt("stats.qd.trend_h", { t: trendText(d.trend) }), "sqd-trend"));
    if (!d.days.length) { box.appendChild(note(tt("stats.qd.no_j"))); return; }
    var rows = d.days.slice().reverse().map(function (x) {
      var label = tt("stats.qd.conf_label", { c: x.confirmed, u: x.unconfirmed, p: x.in_progress, k: x.unknown });
      return {
        cls: x.partial ? "sqd-partial" : null,
        cells: [dayLabel(x), pct(x.pct_confirmed),
          stackBar([[x.confirmed, "sqd-c-ok"], [x.unconfirmed, "sqd-c-warn"],
                    [x.unknown, "sqd-c-bad"], [x.in_progress, "sqd-c-muted"]], label),
          String(x.confirmed), String(x.unconfirmed), String(x.in_progress), String(x.unknown)]
      };
    });
    box.appendChild(table(tt("stats.qd.conf_cols").split("|"),
      rows, tt("stats.qd.conf_cap")));
    box.appendChild(note(tt("stats.qd.conf_note")));
  }

  // -- 2 --------------------------------------------------------------------------
  function renderReading(box, d) {
    box.replaceChildren();
    box.appendChild(note(tt("stats.qd.read_trend", { t: trendText(d.trend) }), "sqd-trend"));
    if (!d.days.length) { box.appendChild(note(tt("stats.qd.no_obs"))); return; }
    var rows = d.days.slice().reverse().map(function (x) {
      var label = tt("stats.qd.read_label", { o: x.ok, u: x.uncertain, i: x.incomplete, r: x.rejected });
      return {
        cls: x.partial ? "sqd-partial" : null,
        cells: [dayLabel(x), pct(x.pct_ok),
          stackBar([[x.ok, "sqd-c-ok"], [x.uncertain, "sqd-c-warn"],
                    [x.incomplete, "sqd-c-bad"], [x.rejected, "sqd-c-muted"]], label),
          pct(x.pct_uncertain), pct(x.pct_incomplete), pct(x.pct_rejected), String(x.total)]
      };
    });
    box.appendChild(table(tt("stats.qd.read_cols").split("|"),
      rows, tt("stats.qd.read_cap")));
  }

  // -- 3 --------------------------------------------------------------------------
  function level(h) {
    if (h.partial && !h.gap) return "sqd-h-part";
    if (h.gap) return h.pct != null && h.pct >= 50 ? "sqd-h-warn" : "sqd-h-bad";
    return "sqd-h-ok";
  }

  var LBL = 30;  // left gutter of the heatmap for the day labels
  function heatmap(d) {
    var days = d.days.map(function (x) { return x.date; });
    var by = {};
    d.hours.forEach(function (h) { by[h.date + "|" + h.hour] = h; });
    var s = svg("svg", { viewBox: "0 0 " + (LBL + 24 * 12) + " " + (days.length * 12), role: "img",
                         "aria-label": tt("stats.qd.heat_aria", { n: days.length }) },
                "sqd-heat");
    days.forEach(function (day, r) {
      var lb = svg("text", { x: 0, y: r * 12 + 9 }, "sqd-heat-lbl");
      lb.textContent = dateRo(day).slice(0, 5);
      s.appendChild(lb);
      for (var hr = 0; hr < 24; hr++) {
        var h = by[day + "|" + hr];
        var rect = svg("rect", { x: LBL + hr * 12, y: r * 12, width: 11, height: 11, rx: 2 },
                       h ? level(h) : "sqd-h-none");
        var t = svg("title");
        t.textContent = tt("stats.qd.heat_tip", { day: dateRo(day), h: hr, rest: h ? tt("stats.qd.heat_cell", { a: h.ok, b: h.expected, pct: pct(h.pct) }) : tt("stats.qd.no_data") });
        rect.appendChild(t);
        s.appendChild(rect);
      }
    });
    return s;
  }

  function renderCoverage(box, d) {
    box.replaceChildren();
    box.appendChild(note(tt("stats.qd.cov_trend", { t: trendText(d.trend) }), "sqd-trend"));
    if (!d.days.length) { box.appendChild(note(tt("stats.qd.no_cap"))); return; }
    var thr = Math.round(d.threshold * 100);
    var legend = el("p", "sqd-legend");
    [["sqd-h-ok", "≥ " + thr + " %"], ["sqd-h-warn", tt("stats.qd.lg_gap", { a: 50, b: thr - 1 })],
     ["sqd-h-bad", tt("stats.qd.lg_bad")], ["sqd-h-part", tt("stats.qd.lg_part")], ["sqd-h-none", tt("stats.qd.no_data")]]
      .forEach(function (p) {
        var item = el("span", "sqd-legend-item");
        var sw = svg("svg", { viewBox: "0 0 10 10", width: 12, height: 12, "aria-hidden": "true" });
        sw.appendChild(svg("rect", { x: 0, y: 0, width: 10, height: 10, rx: 2 }, p[0]));
        item.appendChild(sw);
        item.appendChild(document.createTextNode(" " + p[1]));
        legend.appendChild(item);
      });
    box.appendChild(legend);
    var wrap = el("div", "sqd-heat-wrap");
    wrap.appendChild(heatmap(d));
    box.appendChild(wrap);
    box.appendChild(note(tt("stats.qd.cov_note", { n: d.expected_per_hour })));

    box.appendChild(table(tt("stats.qd.cov_cols").split("|"),
      d.days.slice().reverse().map(function (x) {
        return { cls: x.partial ? "sqd-partial" : null,
                 cells: [dayLabel(x), pct(x.pct), x.ok + " / " + x.expected, String(x.failed),
                         String(x.hours_with_gap)] };
      }), tt("stats.qd.cov_cap")));

    box.appendChild(el("h4", "sqd-sub", tt("stats.qd.gaps_h", { thr: thr })));
    if (!d.gaps.length) { box.appendChild(note(tt("stats.qd.no_gaps"))); return; }
    box.appendChild(table(tt("stats.qd.gap_cols").split("|"),
      d.gaps.slice(0, 15).map(function (g) {
        return { cells: [dateRo(g.date) + " " + (g.hour < 10 ? "0" : "") + g.hour + ":00",
                         pct(g.pct), g.ok + " / " + g.expected, String(g.failed)] };
      }), tt("stats.qd.gap_cap")));
  }

  // -- mount ----------------------------------------------------------------------
  function section(parent, title, intro, url, render) {
    var c = card(title, intro);
    var body = el("div", "sqd-body");
    body.appendChild(note(tt("stats.qd.loading")));
    c.appendChild(body);
    parent.appendChild(c);
    fetchJson(url).then(function (d) { render(body, d); }, function () {
      body.replaceChildren(note(tt("stats.qd.failed"), "sqd-error"));
    });
  }

  App.statQualityDaily = {
    mount: function (parent) {
      var root = el("div", "sqd");
      root.appendChild(el("h2", "sqd-heading", tt("stats.qd.h")));
      section(root, tt("stats.qd.s1"),
        tt("stats.qd.s1i"),
        "/api/admin/quality-daily/confirmation?days=14", renderConfirmation);
      section(root, tt("stats.qd.s2"),
        tt("stats.qd.s2i"),
        "/api/admin/quality-daily/reading?days=14", renderReading);
      section(root, tt("stats.qd.s3"),
        tt("stats.qd.s3i"),
        "/api/admin/quality-daily/coverage?days=7", renderCoverage);
      parent.appendChild(root);
    }
  };
})();
