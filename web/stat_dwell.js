// © 2026 Andy217Ace
// Statistici — „Cât stă trenul pe panou” (secțiune publică în #statistici). Se înregistrează
// în App.statsExtra (apelat de statistici.js la fiecare randare) și citește
// /api/stats/dwell pentru aceeași perioadă / același panou. Doar DOM prin
// createElement + textContent (CSP, fără stiluri inline); clasele ss-* vin din statistici.css,
// deci urmează temele light/dark. Un serviciu e „schimbat” când panoul a arătat ≥ 2 peroane
// Durata = prima → ultima citire a serviciilor încheiate; mediană ȘI medie (media e trasă de extreme);
// sosiri și plecări separate. Este fereastra de consultare observată, nu orarul real.
"use strict";

(function () {
  var App = window.TabelaApp;
  if (!App || !App.stats) return;
  var S = App.stats;
  var el = App.el;
  var API = "/api/stats/dwell";
  var BOARD_PL = { arrival: "Sosiri", departure: "Plecări" };
  var cache = { key: null, at: 0, data: null };
  var TTL = 60000;

  function num(v) { return v == null ? "—" : S.numFmt.format(v); }
  function pct(v) { return v == null ? "—" : S.numFmt.format(v) + " %"; }

  function table(caption, cols, rows) {
    var wrap = el("div", "ss-cmp-wrap");
    var t = el("table", "ss-cmp");
    t.append(el("caption", "sr-only", caption));
    var hr = el("tr");
    cols.forEach(function (c) { var th = el("th", null, c); th.scope = "col"; hr.append(th); });
    var th = el("thead");
    th.append(hr);
    t.append(th);
    var tb = el("tbody");
    rows.forEach(function (r) {
      var tr = el("tr");
      r.forEach(function (c, i) {
        var td = el(i === 0 ? "th" : "td");
        if (i === 0) td.scope = "row";
        if (c instanceof Node) td.append(c); else td.textContent = c;
        tr.append(td);
      });
      tb.append(tr);
    });
    t.append(tb);
    wrap.append(t);
    return wrap;
  }

  function mins(v) { return v == null ? "—" : S.numFmt.format(v) + " min"; }

  function statsRow(label, x) {
    return [label, num(x.n), mins(x.median), mins(x.mean), mins(x.p90)];
  }

  var COLS = ["Grup", "Servicii (N)", "Mediană", "Medie", "90% sub"];

  function fill(sec, d) {
    sec.replaceChildren();
    var h = el("h2", "ss-fig-title", "Cât stă trenul pe panou");
    var head = el("div", "ss-fig-head");
    head.append(h);
    sec.append(head);
    var how = el("p", "ss-how");
    how.append(el("strong", null, "Cum se citește: "), document.createTextNode(
      "durata dintre prima și ultima dată când trenul a fost văzut pe panou, pentru trenurile care au dispărut deja. " +
      "Mediana este durata „de mijloc” (jumătate stau mai puțin); media este trasă în sus de cazurile foarte lungi, " +
      "de aceea le arătăm pe amândouă."));
    sec.append(how);
    sec.append(el("p", "st-warn ss-warn", d.note));
    if (!d.n) {
      sec.append(el("p", "ss-n", "Nu există încă trenuri încheiate pentru filtrele alese."));
      return;
    }
    sec.append(el("p", "ss-n", "Toate: mediană " + mins(d.overall.median) + ", medie " + mins(d.overall.mean) +
      " (N = " + num(d.n) + ")."));
    var rows = [];
    Object.keys(BOARD_PL).forEach(function (b) {
      if (d.boards[b] && d.boards[b].n) rows.push(statsRow(BOARD_PL[b], d.boards[b]));
    });
    sec.append(table("Durata pe panou, sosiri și plecări", ["Panou"].concat(COLS.slice(1)), rows));
    if (d.types.length) {
      sec.append(el("h3", "ss-sub-title", "Pe tip de tren"));
      sec.append(table("Durata pe panou după tipul trenului", ["Tip"].concat(COLS.slice(1)),
        d.types.map(function (g) { return statsRow(g.train_type || "—", g); })));
    }
    if (d.stations.length) {
      sec.append(el("h3", "ss-sub-title", "Pe stație"));
      sec.append(table("Durata pe panou după stație", ["Stația"].concat(COLS.slice(1)),
        d.stations.map(function (g) { return statsRow(S.titleCase ? S.titleCase(g.station) : g.station, g); })));
    }
    sec.append(el("p", "ss-n", "Se arată grupurile cu cel puțin " + d.min_group + " servicii" +
      (d.small_groups_omitted ? " (" + d.small_groups_omitted + " stații cu mai puține nu apar)" : "") +
      ". Duratele negative sau peste 24 de ore (pauze de citire) sunt excluse."));
  }

  function render(body, p) {
    var sec = el("section", "ss-fig ss-fig-wide");
    sec.setAttribute("data-key", "durata-pe-panou");
    sec.setAttribute("aria-busy", "true");
    sec.append(el("p", "ss-n", "Se încarcă durata pe panou…"));
    body.append(sec);
    var q = "perioada=" + encodeURIComponent((p && p.perioada) || "all") +
      (p && p.board ? "&board=" + encodeURIComponent(p.board) : "");
    if (cache.key === q && cache.data && Date.now() - cache.at < TTL) {
      sec.removeAttribute("aria-busy");
      fill(sec, cache.data);
      return;
    }
    S.getJSON(API + "?" + q, new AbortController()).then(function (d) {
      cache = { key: q, at: Date.now(), data: d };
      if (!sec.isConnected) return;
      sec.removeAttribute("aria-busy");
      fill(sec, d);
    }).catch(function (e) {
      if (!sec.isConnected) return;
      sec.removeAttribute("aria-busy");
      sec.replaceChildren(el("p", "st-warn ss-warn", S.errorText(e)));
    });
  }

  App.statsExtra = App.statsExtra || [];
  App.statsExtra.push(render);
})();
