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
  var TREND = {
    up: "↑ în creștere", down: "↓ în scădere", flat: "→ stabil", unknown: "tendință necunoscută"
  };

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

  function pct(v) { return v == null ? "—" : String(v).replace(".", ",") + " %"; }

  function dateRo(iso) {  // 2026-10-20 -> 20.10.2026
    var p = iso.split("-");
    return p[2] + "." + p[1] + "." + p[0];
  }

  function trendText(t) {
    if (!t || t.direction === "unknown") return TREND.unknown + " (sub 2 zile complete)";
    var d = t.delta_pp > 0 ? "+" + t.delta_pp : String(t.delta_pp);
    return TREND[t.direction] + " (" + d.replace(".", ",") + " puncte procentuale)";
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
    return d.partial ? s + " (zi parțială)" : s;
  }

  function note(text, cls) { return el("p", cls || "sqd-note", text); }

  // -- 1 --------------------------------------------------------------------------
  function renderConfirmation(box, d) {
    box.replaceChildren();
    box.appendChild(note("Tendință (zile complete): " + trendText(d.trend), "sqd-trend"));
    if (!d.days.length) { box.appendChild(note("Nu există călătorii în perioada aleasă.")); return; }
    var rows = d.days.slice().reverse().map(function (x) {
      var label = x.confirmed + " confirmate, " + x.unconfirmed + " neconfirmate, " +
        x.in_progress + " în curs, " + x.unknown + " necunoscute";
      return {
        cls: x.partial ? "sqd-partial" : null,
        cells: [dayLabel(x), pct(x.pct_confirmed),
          stackBar([[x.confirmed, "sqd-c-ok"], [x.unconfirmed, "sqd-c-warn"],
                    [x.unknown, "sqd-c-bad"], [x.in_progress, "sqd-c-muted"]], label),
          String(x.confirmed), String(x.unconfirmed), String(x.in_progress), String(x.unknown)]
      };
    });
    box.appendChild(table(["Ziua", "Confirmate", "Distribuție", "Conf.", "Neconf.", "În curs", "Necun."],
      rows, "Rata de confirmare pe zi"));
    box.appendChild(note("Procentul = confirmate din călătoriile încheiate (cele în curs nu au încă " +
      "rezultat). Ziua curentă și prima zi cu date sunt parțiale."));
  }

  // -- 2 --------------------------------------------------------------------------
  function renderReading(box, d) {
    box.replaceChildren();
    box.appendChild(note("Tendință % citite corect (zile complete): " + trendText(d.trend), "sqd-trend"));
    if (!d.days.length) { box.appendChild(note("Nu există observații în perioada aleasă.")); return; }
    var rows = d.days.slice().reverse().map(function (x) {
      var label = x.ok + " ok, " + x.uncertain + " incerte, " + x.incomplete + " incomplete, " +
        x.rejected + " respinse";
      return {
        cls: x.partial ? "sqd-partial" : null,
        cells: [dayLabel(x), pct(x.pct_ok),
          stackBar([[x.ok, "sqd-c-ok"], [x.uncertain, "sqd-c-warn"],
                    [x.incomplete, "sqd-c-bad"], [x.rejected, "sqd-c-muted"]], label),
          pct(x.pct_uncertain), pct(x.pct_incomplete), pct(x.pct_rejected), String(x.total)]
      };
    });
    box.appendChild(table(["Ziua", "Ok", "Distribuție", "Incerte", "Incomplete", "Respinse", "Rânduri"],
      rows, "Calitatea citirii pe zi"));
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
                         "aria-label": "Harta acoperirii pe oră: " + days.length + " zile, 24 ore" },
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
        t.textContent = dateRo(day) + " ora " + hr + ":00 — " +
          (h ? h.ok + " din " + h.expected + " capturi (" + pct(h.pct) + ")" : "fără date");
        rect.appendChild(t);
        s.appendChild(rect);
      }
    });
    return s;
  }

  function renderCoverage(box, d) {
    box.replaceChildren();
    box.appendChild(note("Tendință acoperire (zile complete): " + trendText(d.trend), "sqd-trend"));
    if (!d.days.length) { box.appendChild(note("Nu există capturi în perioada aleasă.")); return; }
    var thr = Math.round(d.threshold * 100);
    var legend = el("p", "sqd-legend");
    [["sqd-h-ok", "≥ " + thr + " %"], ["sqd-h-warn", "gol (50–" + (thr - 1) + " %)"],
     ["sqd-h-bad", "gol sever (< 50 %)"], ["sqd-h-part", "oră parțială"], ["sqd-h-none", "fără date"]]
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
    box.appendChild(note("Ore 0–23, de la stânga la dreapta; fiecare celulă = capturile reușite din " +
      "cele " + d.expected_per_hour + " așteptate."));

    box.appendChild(table(["Ziua", "Acoperire", "Reușite / așteptate", "Eșuate", "Ore cu gol"],
      d.days.slice().reverse().map(function (x) {
        return { cls: x.partial ? "sqd-partial" : null,
                 cells: [dayLabel(x), pct(x.pct), x.ok + " / " + x.expected, String(x.failed),
                         String(x.hours_with_gap)] };
      }), "Acoperirea panoului pe zi"));

    box.appendChild(el("h4", "sqd-sub", "Cele mai recente goluri (sub " + thr + " %)"));
    if (!d.gaps.length) { box.appendChild(note("Nu sunt goluri în perioada aleasă.")); return; }
    box.appendChild(table(["Ziua și ora", "Acoperire", "Reușite / așteptate", "Eșuate"],
      d.gaps.slice(0, 15).map(function (g) {
        return { cells: [dateRo(g.date) + " " + (g.hour < 10 ? "0" : "") + g.hour + ":00",
                         pct(g.pct), g.ok + " / " + g.expected, String(g.failed)] };
      }), "Orele cu acoperire sub prag"));
  }

  // -- mount ----------------------------------------------------------------------
  function section(parent, title, intro, url, render) {
    var c = card(title, intro);
    var body = el("div", "sqd-body");
    body.appendChild(note("Se încarcă…"));
    c.appendChild(body);
    parent.appendChild(c);
    fetchJson(url).then(function (d) { render(body, d); }, function () {
      body.replaceChildren(note("Nu am putut încărca aceste date.", "sqd-error"));
    });
  }

  App.statQualityDaily = {
    mount: function (parent) {
      var root = el("div", "sqd");
      root.appendChild(el("h2", "sqd-heading", "Calitatea datelor pe zi"));
      section(root, "Rata de confirmare a călătoriilor",
        "Câte călătorii au rezultat final confirmat, neconfirmat, în curs sau necunoscut, pe zi.",
        "/api/admin/quality-daily/confirmation?days=14", renderConfirmation);
      section(root, "Calitatea citirii",
        "Rândurile citite de pe tabelă, după validare: ok, incerte, incomplete, respinse.",
        "/api/admin/quality-daily/reading?days=14", renderReading);
      section(root, "Acoperirea panoului pe oră",
        "Capturi reușite față de cele așteptate (60 pe oră); golurile apar evidențiate.",
        "/api/admin/quality-daily/coverage?days=7", renderCoverage);
      parent.appendChild(root);
    }
  };
})();
