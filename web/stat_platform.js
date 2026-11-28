// © 2026 Andy217Ace
// Statistici — „Peroane schimbate după anunț” (secțiune publică în #statistici). Se înregistrează
// în App.statsExtra (apelat de statistici.js la fiecare randare) și citește
// /api/stats/platform-changes pentru aceeași perioadă / același panou. Doar DOM prin
// createElement + textContent (CSP, fără stiluri inline); clasele ss-* vin din statistici.css,
// deci urmează temele light/dark. Un serviciu e „schimbat” când panoul a arătat ≥ 2 peroane
// distincte valide; cifrele cu N; sub eșantion minim fără procent, cu mențiunea „date puține”.
"use strict";

(function () {
  var App = window.TabelaApp;
  if (!App || !App.stats) return;
  var S = App.stats;
  var el = App.el;
  var API = "/api/stats/platform-changes";
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

  function pairText(p) { return tt("stats.pc.pair", { a: p.from, b: p.to }); }

  function fill(sec, d) {
    sec.replaceChildren();
    var h = el("h2", "ss-fig-title", tt("stats.pc.title"));
    var head = el("div", "ss-fig-head");
    head.append(h);
    sec.append(head);
    var how = el("p", "ss-how");
    how.append(el("strong", null, tt("stats.how_label")), document.createTextNode(
      tt("stats.pc.how", { max: d.platform_max })));
    sec.append(how);
    if (!d.n_with_platform) {
      sec.append(el("p", "ss-n", tt("stats.pc.none")));
      return;
    }
    var line = tt("stats.pc.line", { a: num(d.n_changed), n: num(d.n_with_platform), pct: d.pct_changed != null ? " (" + pct(d.pct_changed) + ")." : "." });
    sec.append(el("p", "ss-n", line));
    Object.keys(BOARD_PL).forEach(function (b) {
      var x = d.boards && d.boards[b];
      if (x && x.n) sec.append(el("p", "ss-n", tt("stats.pc.board", { board: BOARD_PL[b], a: num(x.changed), n: num(x.n), pct: x.pct != null ? " (" + pct(x.pct) + ")" : tt("stats.pc.no_pct") })));
    });
    if (d.small_sample) {
      sec.append(el("p", "st-warn ss-warn", tt("stats.pc.few", { n: d.n_with_platform, c: d.n_changed })));
    }
    if (d.pairs.length) {
      sec.append(el("h3", "ss-sub-title", tt("stats.pc.common")));
      sec.append(table(tt("stats.pc.pairs_t"), tt("stats.pc.pairs_c").split("|"),
        d.pairs.map(function (p) { return [pairText(p), num(p.n)]; })));
    }
    if (d.trains.length) {
      sec.append(el("h3", "ss-sub-title", tt("stats.pc.trains_h")));
      sec.append(table(tt("stats.pc.trains_t"), tt("stats.pc.trains_c").split("|"),
        d.trains.map(function (t) {
          var a = el("a", null, (t.train_type ? t.train_type + " " : "") + t.train_no);
          a.href = window.TabelaApp.routeHref("#tren?nr=" + t.train_no);
          return [a, S.titleCase ? S.titleCase(t.station) : t.station,
                  tt("stats.fig.compare.of", { a: num(t.changed), n: num(t.seen) }) + " (" + (BOARD_PL[t.board] || "").toLowerCase() + ")",
                  pairText(t.pair)];
        })));
    }
    if (d.stations.length) {
      sec.append(el("h3", "ss-sub-title", tt("stats.pc.st_h")));
      sec.append(table(tt("stats.pc.st_t"), tt("stats.pc.st_c").split("|"),
        d.stations.map(function (s) {
          return [S.titleCase ? S.titleCase(s.station) : s.station,
                  tt("stats.fig.compare.of", { a: num(s.changed), n: num(s.seen) }), pct(s.pct)];
        })));
    }
    sec.append(el("p", "ss-n", tt("stats.pc.foot", { n: num(d.ignored_values) })));
  }

  function render(body, p) {
    var sec = el("section", "ss-fig ss-fig-wide");
    sec.setAttribute("data-key", "peroane-schimbate");
    sec.setAttribute("aria-busy", "true");
    sec.append(el("p", "ss-n", tt("stats.pc.loading")));
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
