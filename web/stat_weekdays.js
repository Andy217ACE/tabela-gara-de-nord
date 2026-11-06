// © 2026 Andy217Ace
// Tabela Gara de Nord — #statistici: „Comparație pe zilele săptămânii” (luni–duminică), separat
// sosiri / plecări. Date: d.weekdays (app/stats_weekdays.py). Prag de încredere N=4 apariții
// distincte pe zi a săptămânii; sub prag, ziua apare ca „date insuficiente”, iar când nicio zi nu
// are N suficient se afișează doar mesajul + săptămânile acumulate (nicio vizualizare înșelătoare).
// CSP: fără cod dinamic, fără HTML din șiruri, fără stiluri inline; culorile vin din tokenii existenți (st-table).
"use strict";

(function () {
  var App = window.TabelaApp = window.TabelaApp || {};
  var nf = new Intl.NumberFormat("ro-RO", { maximumFractionDigits: 1 });
  var BOARD_PL = { arrival: "Sosiri", departure: "Plecări" };

  function num(v, suffix) { return v == null ? "—" : nf.format(v) + (suffix || ""); }
  function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

  function table(ctx, w, b) {
    var el = ctx.el;
    var wrap = el("div", "st-scroll");
    wrap.tabIndex = 0;
    wrap.setAttribute("role", "region");
    wrap.setAttribute("aria-label", "Comparație pe zilele săptămânii — " + BOARD_PL[b]);
    var t = el("table", "st-table ss-table");
    t.append(el("caption", "sr-only", "Comparație pe zilele săptămânii — " + BOARD_PL[b]));
    var head = el("tr");
    ["Ziua", "Apariții", "Servicii", "La timp (≤5 min)", "Întârziere mediană", "Peste 30 min"].forEach(function (c, i) {
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
        tr.append(el("td", "st-num", num(c.on_time_pct, " %")),
          el("td", "st-num", num(c.median, " min")),
          el("td", "st-num", num(c.over_30_pct, " %")));
      } else {
        var td = el("td", "st-num ss-empty", "date insuficiente");
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
    var f = ctx.figure({ title: "Cum se compară zilele săptămânii?", wide: true,
      how: "fiecare rând este o zi a săptămânii; serviciile sunt toate trenurile programate în acea zi, iar procentul la timp, " +
        "întârzierea mediană și ponderea peste 30 de minute se calculează doar din întârzierile citite. O zi se compară abia " +
        "după " + n + " apariții distincte (zile calendaristice încheiate); până atunci apare „date insuficiente”. " +
        "Ziua de azi nu se numără, fiindcă nu s-a încheiat." });
    if (w.status !== "ok") {
      var box = ctx.el("div", "ss-empty-box");
      box.append(ctx.el("p", "ss-empty", w.message || "Comparația va deveni valabilă după ~4 săptămâni de date"));
      box.append(ctx.nLine("Săptămâni acumulate: " + w.weeks + " din " + n + " necesare (cea mai bine acoperită zi a săptămânii)."));
      f.host.append(box);
      return;
    }
    boards.forEach(function (b) {
      if (!w.boards[b]) return;
      f.host.append(ctx.el("h3", "ss-mult-h", BOARD_PL[b]));
      f.host.append(table(ctx, w, b));
    });
    f.foot.append(ctx.nLine("Săptămâni acumulate: " + w.weeks + ". Zilele cu mai puțin de " + n +
      " apariții rămân marcate „date insuficiente”; sosirile și plecările nu se amestecă."));
  }

  App.statWeekdays = { section: section };
})();
