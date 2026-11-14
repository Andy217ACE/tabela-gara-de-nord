// © 2026 Andy217Ace
// Tabela Gara de Nord — #statistici: „Comparație pe zilele săptămânii” (luni–duminică), separat
// sosiri / plecări. Date: d.weekdays (app/stats_weekdays.py). Prag de încredere N=4 apariții
// distincte pe zi a săptămânii; sub prag, ziua apare ca „date insuficiente”, iar când nicio zi nu
// are N suficient se afișează doar mesajul + săptămânile acumulate (nicio vizualizare înșelătoare).
// CSP: fără cod dinamic, fără HTML din șiruri, fără stiluri inline; culorile vin din tokenii existenți (st-table).
"use strict";

(function () {
  var App = window.TabelaApp = window.TabelaApp || {};
  var tt = function (k, p) { return window.I18N.t(k, p); };
  var nfCache = {};
  var nf = { format: function (x) {   // Intl in the chosen language: English 12.5, Romanian 12,5
    var l = window.I18N.lang();
    nfCache[l] = nfCache[l] || new Intl.NumberFormat(l, { maximumFractionDigits: 1 });
    return nfCache[l].format(x);
  } };
  var BOARD_PL = {};
  ["arrival", "departure"].forEach(function (k) {
    Object.defineProperty(BOARD_PL, k, { enumerable: true, get: function () { return tt("stats.board." + k); } });
  });

  function num(v, suffix) { return v == null ? "—" : suffix === "%" ? tt("stats.fmt.pct", { v: nf.format(v) }) : suffix === "min" ? tt("stats.fmt.min", { v: nf.format(v) }) : nf.format(v); }
  function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

  function table(ctx, w, b) {
    var el = ctx.el;
    var wrap = el("div", "st-scroll");
    wrap.tabIndex = 0;
    wrap.setAttribute("role", "region");
    wrap.setAttribute("aria-label", tt("stats.wk.cmp", { board: BOARD_PL[b] }));
    var t = el("table", "st-table ss-table");
    t.append(el("caption", "sr-only", tt("stats.wk.cmp", { board: BOARD_PL[b] })));
    var head = el("tr");
    tt("stats.wk.cols").split("|").forEach(function (c, i) {
      var th = el("th", i ? "st-num" : null, c);
      th.scope = "col";
      head.append(th);
    });
    var thead = el("thead");
    thead.append(head);
    var body = el("tbody");
    w.boards[b].forEach(function (c) {
      var tr = el("tr");
      var th = el("th", null, cap(c.label));
      th.scope = "row";
      tr.append(th);
      tr.append(el("td", "st-num", String(c.appearances) + " / " + w.min_appearances));
      tr.append(el("td", "st-num", String(c.journeys)));
      if (c.reliable) {
        tr.append(el("td", "st-num", num(c.on_time_pct, "%")),
          el("td", "st-num", num(c.median, "min")),
          el("td", "st-num", num(c.over_30_pct, "%")));
      } else {
        var td = el("td", "st-num ss-empty", tt("stats.wk.insufficient"));
        td.colSpan = 3;
        tr.append(td);
      }
      body.append(tr);
    });
    t.append(thead, body);
    wrap.append(t);
    return wrap;
  }

  function section(d, boards, ctx) {
    var w = d && d.weekdays;
    if (!w || !ctx || !ctx.figure) return;
    var n = w.min_appearances;
    var f = ctx.figure({ title: tt("stats.wk.title"), key: "cum-se-compara-zilele-saptamanii", wide: true,
      how: tt("stats.wk.how", { n: n }) });
    if (w.status !== "ok") {
      var box = ctx.el("div", "ss-empty-box");
      box.append(ctx.el("p", "ss-empty", w.message || tt("stats.wk.pending")));
      box.append(ctx.nLine(tt("stats.wk.weeks", { w: w.weeks, n: n })));
      f.host.append(box);
      return;
    }
    boards.forEach(function (b) {
      if (!w.boards[b]) return;
      f.host.append(ctx.el("h3", "ss-mult-h", BOARD_PL[b]));
      f.host.append(table(ctx, w, b));
    });
    f.foot.append(ctx.nLine(tt("stats.wk.foot", { w: w.weeks, n: n })));
  }

  App.statWeekdays = { section: section };
})();
