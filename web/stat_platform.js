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

  function pairText(p) { return "peron " + p.from + " → " + p.to; }

  function fill(sec, d) {
    sec.replaceChildren();
    var h = el("h2", "ss-fig-title", "Peroane schimbate după anunț");
    var head = el("div", "ss-fig-head");
    head.append(h);
    sec.append(head);
    var how = el("p", "ss-how");
    how.append(el("strong", null, "Cum se citește: "), document.createTextNode(
      "un tren e „schimbat” când panoul i-a afișat cel puțin două peroane diferite (de exemplu 6 apoi 4). " +
      "Se numără doar serviciile cu un peron citit; valorile care nu sunt un peron real (1–" + d.platform_max +
      ") sunt citiri greșite și se ignoră."));
    sec.append(how);
    if (!d.n_with_platform) {
      sec.append(el("p", "ss-n", "Nu există încă servicii cu peron citit pentru filtrele alese."));
      return;
    }
    var line = num(d.n_changed) + " din " + num(d.n_with_platform) + " servicii cu peron și-au schimbat peronul" +
      (d.pct_changed != null ? " (" + pct(d.pct_changed) + ")." : ".");
    sec.append(el("p", "ss-n", line));
    Object.keys(BOARD_PL).forEach(function (b) {
      var x = d.boards && d.boards[b];
      if (x && x.n) sec.append(el("p", "ss-n", BOARD_PL[b] + ": " + num(x.changed) + " din " + num(x.n) +
        (x.pct != null ? " (" + pct(x.pct) + ")" : " — fără procent, eșantion mic")));
    });
    if (d.small_sample) {
      sec.append(el("p", "st-warn ss-warn", "Date puține (N = " + d.n_with_platform + ", schimbări = " +
        d.n_changed + "): cifrele sunt orientative și se pot schimba mult pe măsură ce se adună istoric."));
    }
    if (d.pairs.length) {
      sec.append(el("h3", "ss-sub-title", "Cele mai frecvente schimbări"));
      sec.append(table("Perechi de peroane din → în", ["Schimbare", "Cazuri"],
        d.pairs.map(function (p) { return [pairText(p), num(p.n)]; })));
    }
    if (d.trains.length) {
      sec.append(el("h3", "ss-sub-title", "Trenuri care își schimbă peronul"));
      sec.append(table("Trenuri cu peron schimbat", ["Tren", "Stația", "Schimbat / văzut", "Cea mai frecventă"],
        d.trains.map(function (t) {
          var a = el("a", null, (t.train_type ? t.train_type + " " : "") + t.train_no);
          a.href = "#tren?nr=" + t.train_no;
          return [a, S.titleCase ? S.titleCase(t.station) : t.station,
                  num(t.changed) + " din " + num(t.seen) + " (" + (BOARD_PL[t.board] || "").toLowerCase() + ")",
                  pairText(t.pair)];
        })));
    }
    if (d.stations.length) {
      sec.append(el("h3", "ss-sub-title", "Stații cu cele mai multe schimbări"));
      sec.append(table("Stații cu peron schimbat", ["Stația", "Schimbate / văzute", "Procent"],
        d.stations.map(function (s) {
          return [S.titleCase ? S.titleCase(s.station) : s.station,
                  num(s.changed) + " din " + num(s.seen), pct(s.pct)];
        })));
    }
    sec.append(el("p", "ss-n", "Peronul se citește de pe panoul București Nord; o schimbare poate fi și o " +
      "corectare a unei citiri nesigure (" + num(d.ignored_values) + " valori ignorate)."));
  }

  function render(body, p) {
    var sec = el("section", "ss-fig ss-fig-wide");
    sec.setAttribute("data-key", "peroane-schimbate");
    sec.setAttribute("aria-busy", "true");
    sec.append(el("p", "ss-n", "Se încarcă peroanele schimbate…"));
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
