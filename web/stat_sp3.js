// © 2026 Andy217Ace
// Statistici v3, sub-proiectul 3 (conținut nou) — strat lazy (stat_sp3.js + stat_sp3.css, nu în precache;
// statistici.js îl încarcă înaintea primei afișări): bannerul de alerte, „Ce s-a schimbat săptămâna asta” și
// comparația 7 zile în sumar (/api/stats/changes, /api/stats/overview?compare=prev7), apoi, la prima vizită
// (cutie proprie, ca stat_dwell dar fără App.statsExtra), „Cele mai fiabile trenuri” (/api/stats/reliable) și heatmap-ul zile × ore
// (/api/stats/heatmap). Textul vine din dicționar (stats.sp3.*) și intră în pagină doar prin textContent (CSP).
// Sub 7 zile de date serverul trimite o cheie de dicționar, iar aici apare „date insuficiente”, niciodată zero.
"use strict";

(function () {
  var App = window.TabelaApp;
  var S = App.stats;
  var el = App.el;
  var NS = "http://www.w3.org/2000/svg";
  var TTL = 60000;
  var cache = {};
  var seq = 0;

  var tt = function (k, p) { return window.I18N.t(k, p); };
  function nf() { return new Intl.NumberFormat(window.I18N.lang(), { maximumFractionDigits: 1 }); }
  function minutes(v) { return v == null ? "—" : tt("stats.fmt.min", { v: nf().format(v) }); }
  function pct(v) { return v == null ? "—" : tt("stats.fmt.pct", { v: nf().format(v) }); }
  function num(v) { return v == null ? "—" : nf().format(v); }
  function signed(v) { return v == null ? "—" : (v > 0 ? "+" : "") + nf().format(v); }
  function board(b) { return tt("stats.board." + b); }
  function hh(h) { return (h < 10 ? "0" : "") + h; }

  function get(url) {
    var c = cache[url];
    if (c && Date.now() - c.at < TTL) return Promise.resolve(c.data);
    return S.getJSON(url, new AbortController()).then(function (d) {
      cache[url] = { at: Date.now(), data: d };
      return d;
    });
  }

  // the page's filters as a query string; `period` false: the endpoint has its own 7-day window
  function qs(p, period) {
    var q = new URLSearchParams();
    ["perioada", "board", "operator", "tip", "doar_confirmate"].forEach(function (f) {
      if (!p || !p[f] || (f === "perioada" && (!period || p[f] === "all"))) return;
      q.set(f, p[f]);
    });
    return q;
  }

  function insufficient(d) {
    var h = d.history || {};
    var m = el("p", "st-warn ss-warn", tt(d.message_key || "stats.sp3.insufficient", { n: h.needed_days || 7, days: h.days || 0 }));
    m.setAttribute("role", "note");
    return m;
  }

  // ---- alert banner (above the summary cards) -------------------------------------------------

  function banner(host, d) {
    var a = d.alerts || [];
    if (!a.length) return;
    var b = el("section", "ss-sp3 ss-sp3-alert");
    b.setAttribute("role", "status");
    b.setAttribute("aria-label", tt("stats.sp3.alert.title"));
    b.append(el("h2", "ss-sp3-h", tt("stats.sp3.alert.title")));
    var ul = el("ul", "ss-sp3-list");
    a.slice(0, 5).forEach(function (x) {
      ul.append(el("li", null, tt("stats.sp3.alert.item", { kind: tt("stats.sp3.kind." + x.kind), name: S.titleCase(x.key),
        board: board(x.board), median: minutes(x.median), n: x.n })));
    });
    if (a.length > 5) ul.append(el("li", null, tt("stats.sp3.alert.more", { n: a.length - 5 })));
    b.append(ul, el("p", "ss-sp3-note", tt("stats.sp3.alert.note", { t: d.alert_threshold_min })));
    // after the summary cards, not above them: it arrives with a second request, and must not push them down (CLS)
    var cards = host.querySelector(".ss-quick");
    host.insertBefore(b, cards ? cards.nextSibling : host.firstChild);
  }

  // ---- „Ce s-a schimbat săptămâna asta” -------------------------------------------------------

  function changeList(title, items, cls) {
    var col = el("div", "ss-sp3-col " + cls);
    col.append(el("h3", "ss-sp3-h4", title));
    if (!items.length) {
      col.append(el("p", "ss-sp3-note", tt("stats.sp3.changes.none")));
      return col;
    }
    var ul = el("ul", "ss-sp3-list");
    items.forEach(function (x) {
      var li = el("li", null);
      li.append(el("strong", null, tt("stats.sp3.kind." + x.kind) + " "), document.createTextNode(
        tt("stats.sp3.changes.item", { name: S.titleCase(x.key), board: board(x.board), before: pct(x.before_pct), now: pct(x.now_pct),
          delta: tt("stats.sp3.fmt.pp", { v: signed(x.delta) }) })));
      li.append(el("span", "ss-sp3-n", " " + tt("stats.sp3.changes.n", { before: x.n_before, now: x.n_now })));
      ul.append(li);
    });
    col.append(ul);
    return col;
  }

  function changes(sec, d) {
    sec.replaceChildren(el("h2", "ss-sp3-h", tt("stats.sp3.changes.title")));
    if (d.status !== "ok") {
      sec.append(insufficient(d));
      return;
    }
    sec.append(el("p", "ss-sp3-note", tt("stats.sp3.changes.sub")));
    var cols = el("div", "ss-sp3-cols");
    cols.append(changeList(tt("stats.sp3.changes.better"), d.improved || [], "ss-sp3-up"),
      changeList(tt("stats.sp3.changes.worse"), d.worsened || [], "ss-sp3-down"));
    sec.append(cols);
  }

  // ---- 7 days against the 7 before ------------------------------------------------------------

  function compare(sec, d) {
    sec.replaceChildren(el("h2", "ss-sp3-h", tt("stats.sp3.compare.title")));
    if (d.status !== "ok") {
      sec.append(insufficient(d));
      return;
    }
    var cols = tt("stats.sp3.compare.cols").split("|");
    var a = d.before, b = d.now, dl = d.delta || {};
    var rows = [
      ["on_time", pct(a.on_time_pct), pct(b.on_time_pct), dl.on_time_pct == null ? "—" : tt("stats.sp3.fmt.pp", { v: signed(dl.on_time_pct) })],
      ["mean", minutes(a.mean), minutes(b.mean), dl.mean == null ? "—" : tt("stats.fmt.min", { v: signed(dl.mean) })],
      ["trains", num(a.trains), num(b.trains), signed(dl.trains)],
      ["journeys", num(a.journeys), num(b.journeys), signed(dl.journeys)]
    ];
    var wrap = el("div", "st-scroll ss-sp3-cmp-wrap");
    var t = el("table", "ss-sp3-cmp");
    var hr = el("tr");
    cols.forEach(function (c) { var th = el("th", null, c); th.scope = "col"; hr.append(th); });
    var thead = el("thead");
    thead.append(hr);
    t.append(thead);
    var tb = el("tbody");
    rows.forEach(function (r) {
      var tr = el("tr");
      var th = el("th", null, tt("stats.sp3.compare." + r[0]));
      th.scope = "row";
      tr.append(th);
      r.slice(1).forEach(function (c) { tr.append(el("td", null, c)); });
      tb.append(tr);
    });
    t.append(tb);
    wrap.append(t);
    sec.append(wrap, el("p", "ss-sp3-note", tt("stats.sp3.compare.note", { min: (d.params && d.params.min_sample) || 5 })));
  }

  // ---- mount (called by statistici.js after every render) -------------------------------------

  function enhance(ui, d, h) {
    var token = ++seq;
    var host = ui.quick;
    [].forEach.call(host.querySelectorAll(".ss-sp3"), function (n) { n.remove(); });
    if (!d.coverage || !d.coverage.journeys) return;
    var chg = el("section", "ss-sp3 ss-sp3-changes");
    var cmp = el("section", "ss-sp3 ss-sp3-compare");
    chg.hidden = cmp.hidden = true;
    host.append(chg, cmp);
    var p = fromQuery(h.query());
    lazy(ui.body, reliable, p);
    lazy(ui.body, heatmap, p);
    var q = qs(p, false).toString();
    function live() { return ui.quick === host && token === seq && host.isConnected; }
    get("/api/stats/changes" + (q ? "?" + q : "")).then(function (c) {
      if (!live()) return;
      banner(host, c);
      changes(chg, c);
      chg.hidden = false;
    }).catch(function () { /* the extras are optional: the page stays complete without them */ });
    var qc = new URLSearchParams(q);
    qc.set("compare", "prev7");
    get("/api/stats/overview?" + qc.toString()).then(function (c) {
      if (!live()) return;
      compare(cmp, c);
      cmp.hidden = false;
    }).catch(function () { });
  }

  // Sections with their own endpoint run at the first visit (IntersectionObserver or a scroll past the box), not at render.
  function lazy(body, fn, p) {
    var box = el("div", "ss-sp3-lazy"), done = false, io = null;
    body.append(box);
    function run() {
      if (done) return;
      done = true;
      if (io) io.disconnect();
      window.removeEventListener("scroll", near);
      fn(box, p);
    }
    function near() {
      if (!box.isConnected) window.removeEventListener("scroll", near);
      else if (box.getBoundingClientRect().top < window.innerHeight + 100) run();
    }
    if (!window.IntersectionObserver) { run(); return; }
    io = new IntersectionObserver(function (es) { if (es.some(function (e) { return e.isIntersecting; })) run(); }, { rootMargin: "100px" });
    io.observe(box);
    window.addEventListener("scroll", near, { passive: true });
  }

  function fromQuery(s) {
    var o = {};
    new URLSearchParams(s || "").forEach(function (v, k) { o[k] = v; });
    return o;
  }

  // ---- „Cele mai fiabile trenuri” (first visit) -----------------------------------------------

  function section(body, title, sub) {
    var sec = el("section", "ss-sp3-sec");
    sec.setAttribute("aria-busy", "true");
    sec.append(el("h2", "ss-fig-title", title), el("p", "ss-sp3-note", sub));
    body.append(sec);
    return sec;
  }

  function reliable(body, p) {
    var q = qs(p, true).toString();
    var sec = section(body, tt("stats.sp3.reliable.title"), "");
    get("/api/stats/reliable" + (q ? "?" + q : "")).then(function (d) {
      if (!sec.isConnected) return;
      sec.removeAttribute("aria-busy");
      var min = d.min_journeys || 10;
      sec.querySelector(".ss-sp3-note").textContent = tt("stats.sp3.reliable.sub", { min: min });
      if (!d.items || !d.items.length) {
        sec.append(el("p", "empty ss-empty", tt(d.message_key || "stats.sp3.reliable.empty", { min: min })));
        return;
      }
      var ol = el("ol", "ss-sp3-rel");
      d.items.forEach(function (x) {
        var li = el("li", "ss-sp3-rel-i");
        var a = el("a", "ss-sp3-train", x.train);
        a.href = "#tren?nr=" + encodeURIComponent(x.train_no);
        li.append(a, el("span", "ss-sp3-rel-r", S.titleCase(x.route || "") + (x.operator ? ", " + x.operator : "") + " · " + board(x.board)),
          el("span", "ss-sp3-rel-s ss-t-good", tt("stats.sp3.reliable.stat", { pct: pct(x.on_time_pct), n: x.n })));
        ol.append(li);
      });
      sec.append(ol);
    }).catch(function (e) {
      if (!sec.isConnected) return;
      sec.removeAttribute("aria-busy");
      if (e && e.status === 404) sec.remove();   // an older server without the endpoint: the page stays complete
      else sec.append(el("p", "st-warn ss-warn", S.errorText(e)));
    });
  }

  // ---- heatmap zile × ore (first visit): common scale for both boards -------------------------

  function svg(tag, attrs, text) {
    var n = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (text != null) n.textContent = text;
    return n;
  }

  function level(mean, max) {
    if (!(max > 0)) return 0;
    return Math.max(0, Math.min(4, Math.floor(5 * mean / max)));
  }

  function heatBoard(cell, b, d, min) {
    var map = {};
    (d.boards[b] || []).forEach(function (c) { map[c.d + "-" + c.h] = c; });
    var max = d.scale && d.scale.max;
    var W = Math.max(260, Math.floor(cell.clientWidth || 320));
    var L = 26, T = 4, B = 18;
    var cw = (W - L - 2) / 24;
    var ch = Math.max(14, Math.min(26, cw));
    var H = T + 7 * ch + B;
    var root = svg("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H, class: "ss-svg ss-sp3-heat-svg", role: "img", "aria-label": tt("stats.sp3.heat.aria", { board: board(b) }) });
    root.append(svg("title", {}, tt("stats.sp3.heat.aria", { board: board(b) })), svg("desc", {}, tt("stats.sp3.heat.desc")));
    d.days.forEach(function (dd) {
      root.append(svg("text", { x: L - 4, y: (T + dd * ch + ch / 2 + 4).toFixed(1), class: "ss-tick ss-tick-y" }, tt("stats.wds." + dd)));
      d.hours.forEach(function (hr) {
        var c = map[dd + "-" + hr] || {};
        var cls = !c.journeys ? "ss-cell-none" : !c.n ? "ss-cell-unread" : !c.sufficient ? "ss-cell-low" : "ss-q" + level(c.mean, max);
        var g = svg("g", { class: "ss-mark" });
        g.append(svg("rect", { x: (L + hr * cw + 1).toFixed(1), y: (T + dd * ch + 1).toFixed(1), width: Math.max(1, cw - 2).toFixed(1),
          height: Math.max(1, ch - 2).toFixed(1), rx: 2, class: "ss-cell " + cls, "data-m": dd + "-" + hr }));
        g.append(svg("title", {}, c.n ? tt("stats.sp3.heat.cell", { day: tt("stats.wd." + dd), hour: hh(hr) + ":00", mean: minutes(c.mean), n: c.n })
          : tt("stats.sp3.heat.cell_none", { day: tt("stats.wd." + dd), hour: hh(hr) + ":00" })));
        root.append(g);
      });
    });
    for (var x = 0; x < 24; x += cw < 16 ? 3 : 2) {
      root.append(svg("text", { x: (L + x * cw + cw / 2).toFixed(1), y: H - 4, class: "ss-tick ss-tick-x" }, hh(x)));
    }
    cell.append(root);
  }

  function heatLegend(d, min) {
    var lg = el("div", "ss-legend ss-legend-scale");
    var max = d.scale && d.scale.max;
    if (max == null) {
      lg.append(el("span", "ss-legend-item", tt("stats.sp3.heat.legend_none")));
      return lg;
    }
    for (var i = 0; i < 5; i++) {
      var it = el("span", "ss-legend-item");
      it.append(el("span", "ss-key ss-key-sq ss-q" + i));
      lg.append(it);
    }
    lg.append(el("span", "ss-legend-item", tt("stats.sp3.heat.legend", { max: nf().format(max) })));
    var low = el("span", "ss-legend-item");
    low.append(el("span", "ss-key ss-key-sq ss-cell-low"), document.createTextNode(tt("stats.sp3.heat.small", { min: min })));
    lg.append(low);
    return lg;
  }

  function heatmap(body, p) {
    var q = qs(p, true).toString();
    var sec = section(body, tt("stats.sp3.heat.title"), tt("stats.sp3.heat.sub"));
    sec.dataset.sp3 = "heatmap";
    get("/api/stats/heatmap" + (q ? "?" + q : "")).then(function (d) {
      if (!sec.isConnected) return;
      sec.removeAttribute("aria-busy");
      if (d.status !== "ok") {
        sec.append(insufficient(d));
        return;
      }
      var min = (d.params && d.params.min_sample) || 5;
      sec.append(heatLegend(d, min));
      var grid = el("div", "ss-multiples ss-sp3-heat");
      sec.append(grid);   // attached first: the cells are sized from their box
      Object.keys(d.boards).forEach(function (b) {
        var cell = el("div", "ss-multiple");
        cell.append(el("h3", "ss-mult-h", board(b)));
        grid.append(cell);
        heatBoard(cell, b, d, min);
      });
    }).catch(function (e) {
      if (!sec.isConnected) return;
      sec.removeAttribute("aria-busy");
      if (e && e.status === 404) sec.remove();   // an older server without the endpoint: the page stays complete
      else sec.append(el("p", "st-warn ss-warn", S.errorText(e)));
    });
  }

  App.statSp3 = { enhance: enhance, level: level };
})();
