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
  var tt = function (k, p) { return window.I18N.t(k, p); };
  var BOARD_PL = {};   // getters: the text follows the language chosen at the time it is read
  ["arrival", "departure"].forEach(function (k) {
    Object.defineProperty(BOARD_PL, k, { enumerable: true, get: function () { return tt("stats.board." + k); } });
  });
  var cache = { key: null, at: 0, data: null };
  var TTL = 60000;

  function num(v) { return v == null ? "—" : S.numFmt.format(v); }
  function pct(v) { return v == null ? "—" : tt("stats.fmt.pct", { v: S.numFmt.format(v) }); }

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

  function mins(v) { return v == null ? "—" : tt("stats.fmt.min", { v: S.numFmt.format(v) }); }

  function statsRow(label, x) {
    return [label, num(x.n), mins(x.median), mins(x.mean), mins(x.p90)];
  }

  function cols() { return tt("stats.dw.cols").split("|"); }

  function fill(sec, d) {
    sec.replaceChildren();
    var h = el("h2", "ss-fig-title", tt("stats.dw.title"));
    var head = el("div", "ss-fig-head");
    head.append(h);
    sec.append(head);
    var how = el("p", "ss-how");
    how.append(el("strong", null, tt("stats.how_label")), document.createTextNode(
      tt("stats.dw.how")));
    sec.append(how);
    sec.append(el("p", "st-warn ss-warn", d.note));
    if (!d.n) {
      sec.append(el("p", "ss-n", tt("stats.dw.none")));
      return;
    }
    sec.append(el("p", "ss-n", tt("stats.dw.all", { median: mins(d.overall.median), mean: mins(d.overall.mean), n: num(d.n) })));
    var rows = [];
    Object.keys(BOARD_PL).forEach(function (b) {
      if (d.boards[b] && d.boards[b].n) rows.push(statsRow(BOARD_PL[b], d.boards[b]));
    });
    sec.append(table(tt("stats.dw.t_board"), [tt("stats.filters.board")].concat(cols().slice(1)), rows));
    if (d.types.length) {
      sec.append(el("h3", "ss-sub-title", tt("stats.dw.by_type")));
      sec.append(table(tt("stats.dw.t_type"), [tt("stats.dw.col_type")].concat(cols().slice(1)),
        d.types.map(function (g) { return statsRow((window.TabelaApp.typeAbbr(g.train_type)) || "—", g); })));
    }
    if (d.stations.length) {
      sec.append(el("h3", "ss-sub-title", tt("stats.dw.by_station")));
      sec.append(table(tt("stats.dw.t_station"), [tt("stats.c.station")].concat(cols().slice(1)),
        d.stations.map(function (g) { return statsRow(S.titleCase ? S.titleCase(g.station) : g.station, g); })));
    }
    sec.append(el("p", "ss-n", tt("stats.dw.foot", { min: d.min_group, omitted: d.small_groups_omitted ? tt("stats.dw.omitted", { n: d.small_groups_omitted }) : "" })));
  }

  function render(body, p) {
    var sec = el("section", "ss-fig ss-fig-wide");
    sec.setAttribute("data-key", "durata-pe-panou");
    sec.setAttribute("aria-busy", "true");
    sec.append(el("p", "ss-n", tt("stats.dw.loading")));
    body.append(sec);
    var q = "perioada=" + encodeURIComponent((p && p.perioada) || "all") +
      (p && p.board ? "&board=" + encodeURIComponent(p.board) : "") +
      (p && p.fara_aeroport === "0" ? "&fara_aeroport=0" : "");
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
