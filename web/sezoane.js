// © 2026 Andy217Ace
// Val 5a: „Sezoane și vreme” — comparația întârzierii citite pe sezoane, cu prag de date.
// Corelație, nu cauzalitate. Date insuficiente: fără cifre, fără grafic. Doar textContent
// (CSP-safe). Payload: GET de la ruta de sezoane (vezi app/seasons.py, funcția overview).
(function () {
  "use strict";

  var BOARD_PL = { arrival: "Sosiri", departure: "Plecări" };

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function minutes(v) { return v == null ? "—" : String(Math.round(v * 10) / 10).replace(".", ",") + " min"; }
  function pct(v) { return v == null ? "—" : String(Math.round(v * 10) / 10).replace(".", ",") + " %"; }

  function groupTable(group) {
    var table = el("table", "sz-table");
    var head = el("tr");
    ["Grupa", "N", "Mediană", "% la timp"].forEach(function (t) { head.append(el("th", null, t)); });
    table.append(head);
    group.forEach(function (g) {
      var tr = el("tr");
      tr.append(el("td", null, g.label));
      tr.append(el("td", null, "N = " + g.n + (g.comparable ? "" : " (sub " + GROUP_MIN + ", nu se compară)")));
      tr.append(el("td", null, g.sufficient ? minutes(g.median) : "—"));
      tr.append(el("td", null, g.sufficient ? pct(g.on_time_pct) : "—"));
      table.append(tr);
    });
    return table;
  }

  var GROUP_MIN = 30;

  function seasonBlock(s, dims) {
    var box = el("section", "sz-season");
    box.append(el("h3", null, s.label));
    if (!s.enough) {
      // sub prag: nicio cifră și niciun grafic, doar starea și N
      box.append(el("p", "sz-insufficient", "date insuficiente (N=" + s.days + ")"));
      return box;
    }
    box.append(el("p", null, "N = " + s.days + " zile eligibile"));
    dims.forEach(function (dim) {
      var gs = (s.groups && s.groups[dim.key]) || [];
      if (!gs.length) return;
      box.append(el("h4", null, dim.title));
      box.append(groupTable(gs));
    });
    return box;
  }

  function render(host, payload) {
    while (host.firstChild) host.removeChild(host.firstChild);
    host.append(el("p", "sz-note", payload.note));
    var dims = [{ key: "precip", title: "Precipitații" }, { key: "temp", title: "Temperatură" }];
    Object.keys(payload.boards || {}).forEach(function (b) {
      var bd = payload.boards[b];
      host.append(el("h2", null, BOARD_PL[b] || b));
      (bd.seasons || []).forEach(function (s) { host.append(seasonBlock(s, dims)); });
      if (!bd.compare) {
        host.append(el("p", "sz-note",
          "Comparația dintre sezoane apare când există cel puțin două sezoane eligibile."));
      }
    });
    if (payload.timetable_excluded_days) {
      host.append(el("p", "sz-note", "Zile excluse din cauza schimbării de orar: " +
        payload.timetable_excluded_days + "."));
    }
  }

  window.Sezoane = { render: render };
})();
