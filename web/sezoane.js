// © 2026 Andy217Ace
// Wave 5a: "Seasons and weather" — comparison of the read delay across seasons, with a data
// threshold. Correlation, not causation. Insufficient data: no numbers, no chart. Only
// textContent (CSP-safe). Payload: GET from the seasons route (see app/seasons.py, overview).
(function () {
  "use strict";

  var BOARD_PL = { arrival: "seasons.board.arrival", departure: "seasons.board.departure" };
  var lastRender = null;

  function T(k, p) { return window.I18N.t(k, p); }
  function dec(s) { return window.I18N.lang() === "en" ? s : s.replace(".", ","); }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function minutes(v) { return v == null ? "—" : dec(String(Math.round(v * 10) / 10)) + " min"; }
  function pct(v) { return v == null ? "—" : dec(String(Math.round(v * 10) / 10)) + " %"; }

  function groupTable(group) {
    var table = el("table", "sz-table");
    var head = el("tr");
    [T("seasons.col.group"), "N", T("seasons.col.median"), T("seasons.col.onTime")].forEach(function (t) { head.append(el("th", null, t)); });
    table.append(head);
    group.forEach(function (g) {
      var tr = el("tr");
      tr.append(el("td", null, g.label));
      tr.append(el("td", null, "N = " + g.n + (g.comparable ? "" : " " + T("seasons.notComparable", { min: GROUP_MIN }))));
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
      // below the threshold: no number and no chart, only the state and N
      box.append(el("p", "sz-insufficient", T("seasons.insufficient", { n: s.days })));
      return box;
    }
    box.append(el("p", null, T("seasons.eligibleDays", { n: s.days })));
    dims.forEach(function (dim) {
      var gs = (s.groups && s.groups[dim.key]) || [];
      if (!gs.length) return;
      box.append(el("h4", null, T(dim.title)));
      box.append(groupTable(gs));
    });
    return box;
  }

  function render(host, payload) {
    lastRender = { host: host, payload: payload };
    while (host.firstChild) host.removeChild(host.firstChild);
    host.append(el("p", "sz-note", payload.note));
    var dims = [{ key: "precip", title: "seasons.dim.precip" }, { key: "temp", title: "seasons.dim.temp" }];
    Object.keys(payload.boards || {}).forEach(function (b) {
      var bd = payload.boards[b];
      host.append(el("h2", null, BOARD_PL[b] ? T(BOARD_PL[b]) : b));
      (bd.seasons || []).forEach(function (s) { host.append(seasonBlock(s, dims)); });
      if (!bd.compare) {
        host.append(el("p", "sz-note", T("seasons.needTwo")));
      }
    });
    if (payload.timetable_excluded_days) {
      host.append(el("p", "sz-note", T("seasons.excluded", { n: payload.timetable_excluded_days })));
    }
  }

  // language switch: redraw the last rendered payload in the new language
  document.addEventListener("i18n:change", function () {
    if (lastRender && document.body.contains(lastRender.host)) render(lastRender.host, lastRender.payload);
  });

  window.Sezoane = { render: render };
})();
