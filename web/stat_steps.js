// © 2026 Andy217Ace
// Statistici — „Întârzieri în trepte” și „Câte modificări are o cursă” (d.steps, computed by
// app/stats_steps.py). Loaded before statistici.js, which calls App.statSteps.render(d, boards, h)
// with its own helpers (figure, multiples, hbars, …). Only existing CSS classes; text via
// textContent (CSP). Delays are those READ on the board; a missing value is „—”.
"use strict";

(function () {
  var App = window.TabelaApp;
  var tt = function (k, p) { return window.I18N.t(k, p); };
  var BOARD_PL = {};   // getters: the text follows the language chosen at the time it is read
  ["arrival", "departure"].forEach(function (k) {
    Object.defineProperty(BOARD_PL, k, { enumerable: true, get: function () { return tt("stats.board." + k); } });
  });

  function pl(n, base) { return n + " " + tt(base + (n === 1 ? ".one" : ".many")); }

  function head(h, cell, b, n) {
    var t = h.el("h3", "ss-mult-h");
    t.append(h.boardKey(b), document.createTextNode(BOARD_PL[b] + " (N = " + n + ")"));
    cell.append(t);
  }

  function table(h, caption, cols, rows) {
    var t = h.el("table", "ss-cmp");
    t.append(h.el("caption", "sr-only", caption));
    var tr = h.el("tr");
    cols.forEach(function (c) { var th = h.el("th", null, c); th.scope = "col"; tr.append(th); });
    var thead = h.el("thead");
    thead.append(tr);
    var tb = h.el("tbody");
    rows.forEach(function (r) {
      var row = h.el("tr");
      r.forEach(function (c, i) {
        var cell = h.el(i === 0 ? "th" : "td");
        if (i === 0) cell.scope = "row";
        if (c && c.nodeType) cell.append(c); else cell.textContent = c == null ? "—" : String(c);
        row.append(cell);
      });
      tb.append(row);
    });
    t.append(thead, tb);
    var wrap = h.el("div", "ss-cmp-wrap");
    wrap.append(t);
    return wrap;
  }

  function stepsSection(d, boards, h) {
    var p = d.params;
    var f = h.figure({ title: tt("stats.stp.title"), key: "cum-creste-intarzierea-in-trepte",
      how: tt("stats.stp.how") });
    var cells = h.multiples(f.host, boards.length);
    boards.forEach(function (b, bi) {
      var s = (d.steps[b] || {}).steps, cell = cells[bi];
      head(h, cell, b, s ? s.n_journeys : 0);
      if (!s || !s.n_steps) { cell.append(h.el("p", "ss-empty", tt("stats.stp.none"))); return; }
      var fs = s.first_share, nf = h.nf;
      var gap = s.median_gap_min == null ? "—" : tt("stats.fmt.min", { v: nf.format(s.median_gap_min) });
      cell.append(h.nLine(tt("stats.stp.typical", { size: s.median_size == null ? "—" : tt("stats.fmt.min", { v: nf.format(s.median_size) }), gap: gap,
        pairs: s.gap_n ? tt("stats.stp.pairs", { n: s.gap_n }) : "", up: pl(s.n_steps, "stats.w.step_up"), down: pl(s.downs, "stats.w.step_down"),
        downmed: s.downs && s.down_median != null ? tt("stats.stp.down_median", { v: nf.format(s.down_median) }) : "" })));
      var max = s.matrix.length ? s.matrix[0].n : 1;
      h.hbars(cell, { board: b, max: max, title: tt("stats.stp.top", { board: BOARD_PL[b] }),
        desc: tt("stats.stp.top_desc"),
        rows: s.matrix.map(function (x) {
          return { label: x.from + " → " + x.to + " min", value: x.n, low: !s.sufficient,
            valueText: String(x.n) + (s.sufficient ? " (" + tt("stats.fmt.pct", { v: nf.format(Math.round(1000 * x.n / s.n_steps) / 10) }) + ")" : ""),
            tip: tt("stats.stp.tip", { n: x.n, total: s.n_steps }) };
        }) });
      cell.append(h.nLine(s.distinct_pairs > s.matrix.length ?
        tt("stats.stp.distinct_top", { a: s.matrix.length, b: s.distinct_pairs }) : tt("stats.stp.distinct", { b: s.distinct_pairs })));
      if (fs.n) {
        cell.append(h.nLine(tt("stats.stp.final", { n: fs.n,
          share: fs.announced_pct != null ? tt("stats.stp.share_pct", { v: nf.format(fs.announced_pct) }) : tt("stats.stp.share_min", { a: fs.announced_min, b: fs.final_min }),
          complete: fs.complete, later: fs.later,
          added: fs.added_median != null ? tt("stats.stp.added", { v: nf.format(fs.added_median) }) : "" })));
      }
      if (s.bounces) cell.append(h.nLine(tt("stats.stp.bounce_note", { b: pl(s.bounces, "stats.w.bounce") })));
      if (!s.sufficient) cell.append(h.warn(tt("stats.warn.small_raw2", { n: s.n_steps, min: p.min_sample })));
    });
    f.foot.append(h.dataTable(tt("stats.stp.table"), tt("stats.stp.table_cols").split("|"),
      boards.reduce(function (acc, b) {
        var s = (d.steps[b] || {}).steps;
        return acc.concat(s ? s.matrix.map(function (x) { return [BOARD_PL[b] + ": " + x.from + " → " + x.to + " min", x.n]; }) : []);
      }, [])));
  }

  function changesSection(d, boards, h) {
    var p = d.params;
    var f = h.figure({ title: tt("stats.ch.title"), key: "cate-modificari-are-o-cursa",
      how: tt("stats.ch.how") });
    var cells = h.multiples(f.host, boards.length);
    boards.forEach(function (b, bi) {
      var c = (d.steps[b] || {}).changes, cell = cells[bi];
      head(h, cell, b, c ? c.n : 0);
      if (!c || !c.n) { cell.append(h.el("p", "ss-empty", tt("stats.ch.none"))); return; }
      var nf = h.nf;
      h.hbars(cell, { board: b, max: c.n, title: tt("stats.ch.bars", { board: BOARD_PL[b] }),
        desc: tt("stats.ch.desc"),
        rows: c.hist.map(function (x) {
          return { label: tt(x.key === "1" ? "stats.ch.one" : "stats.ch.many", { k: x.key }), value: x.n, low: !c.sufficient,
            valueText: String(x.n) + (x.pct != null ? " (" + tt("stats.fmt.pct", { v: nf.format(x.pct) }) + ")" : ""),
            tip: tt("stats.ch.tip", { n: x.n, total: c.n }) };
        }) });
      cell.append(h.nLine(tt("stats.ch.mean", { mean: c.mean == null ? "—" : nf.format(c.mean), max: c.max })));
      if (!c.sufficient) cell.append(h.warn(tt("stats.warn.small_raw2", { n: c.n, min: p.min_sample })));
    });
    boards.forEach(function (b) {
      var c = (d.steps[b] || {}).changes;
      if (!c || !c.top.length) return;
      var box = h.el("div", "ss-recurrent");
      box.append(h.el("h3", "ss-mult-h", tt("stats.ch.top_h", { board: BOARD_PL[b] })));
      box.append(table(h, tt("stats.ch.top_t", { board: BOARD_PL[b].toLowerCase() }),
        tt("stats.ch.top_c").split("|"),
        c.top.map(function (t) {
          var a = h.hashLink({ label: t.train_type + " " + t.train_no, href: t.href }, "ss-plink");
          return [a, t.station ? t.station.charAt(0) + t.station.slice(1).toLowerCase() : "—", t.date, t.sched_time || "—",
            t.changes, t.values.join(" → ")];
        })));
      f.foot.append(box);
    });
  }

  App.statSteps = {
    render: function (d, boards, h) {
      if (!d.steps) return;
      stepsSection(d, boards, h);
      changesSection(d, boards, h);
    }
  };
})();
