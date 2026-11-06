// © 2026 Andy217Ace
// Statistici — „Întârzieri în trepte” și „Câte modificări are o cursă” (d.steps, computed by
// app/stats_steps.py). Loaded before statistici.js, which calls App.statSteps.render(d, boards, h)
// with its own helpers (figure, multiples, hbars, …). Only existing CSS classes; text via
// textContent (CSP). Delays are those READ on the board; a missing value is „—”.
"use strict";

(function () {
  var App = window.TabelaApp;
  var BOARD_PL = { arrival: "Sosiri", departure: "Plecări" };

  function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }

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
    var f = h.figure({ title: "Cum crește întârzierea, în trepte",
      how: "tabela urcă întârzierea treptat (de ex. 0 → 5 → 10 min). Numărăm salturile dintre două valori citite " +
        "una după alta, de la valoarea anterioară (la început 0) la cea nouă. Scăderile apar separat; o valoare care " +
        "apare o singură citire și revine exact la cea de dinainte (A → B → A) e zgomot de citire și nu se numără." });
    var cells = h.multiples(f.host, boards.length);
    boards.forEach(function (b, bi) {
      var s = (d.steps[b] || {}).steps, cell = cells[bi];
      head(h, cell, b, s ? s.n_journeys : 0);
      if (!s || !s.n_steps) { cell.append(h.el("p", "ss-empty", "Nicio modificare de întârziere citită.")); return; }
      var fs = s.first_share, nf = h.nf;
      var gap = s.median_gap_min == null ? "—" : nf.format(s.median_gap_min) + " min";
      cell.append(h.nLine("Treapta tipică: " + (s.median_size == null ? "—" : nf.format(s.median_size) + " min") +
        " · timp median între două modificări: " + gap + (s.gap_n ? " (din " + s.gap_n + " perechi)" : "") +
        " · " + plural(s.n_steps, "creștere", "creșteri") + ", " + plural(s.downs, "scădere", "scăderi") +
        (s.downs && s.down_median != null ? " (mediana −" + nf.format(s.down_median) + " min)" : "") + "."));
      var max = s.matrix.length ? s.matrix[0].n : 1;
      h.hbars(cell, { board: b, max: max, title: "Cele mai frecvente trepte — " + BOARD_PL[b],
        desc: "Numărul de treceri de la o valoare de întârziere la alta.",
        rows: s.matrix.map(function (x) {
          return { label: x.from + " → " + x.to + " min", value: x.n, low: !s.sufficient,
            valueText: String(x.n) + (s.sufficient ? " (" + nf.format(Math.round(1000 * x.n / s.n_steps) / 10) + " %)" : ""),
            tip: x.n + " din " + s.n_steps + " creșteri" };
        }) });
      cell.append(h.nLine(s.distinct_pairs > s.matrix.length ?
        "Primele " + s.matrix.length + " din " + s.distinct_pairs + " perechi diferite." : s.distinct_pairs + " perechi diferite."));
      if (fs.n) {
        cell.append(h.nLine("Din întârzierea finală (curse cu întârziere la final, N = " + fs.n + "): " +
          (fs.announced_pct != null ? nf.format(fs.announced_pct) + " % era deja anunțată la prima apariție" :
            fs.announced_min + " din " + fs.final_min + " min anunțate la prima apariție") +
          "; " + fs.complete + " curse au avut valoarea finală încă de la început, " + fs.later + " au primit minute ulterior" +
          (fs.added_median != null ? " (mediana +" + nf.format(fs.added_median) + " min)" : "") + "."));
      }
      if (s.bounces) cell.append(h.nLine(plural(s.bounces, "citire izolată ignorată", "citiri izolate ignorate") + " (zgomot A → B → A)."));
      if (!s.sufficient) cell.append(h.warn("Eșantion mic (N = " + s.n_steps + " < " + p.min_sample + "): doar cifre brute."));
    });
    f.foot.append(h.dataTable("Treptele de întârziere", ["Panou, de la → la", "Număr"],
      boards.reduce(function (acc, b) {
        var s = (d.steps[b] || {}).steps;
        return acc.concat(s ? s.matrix.map(function (x) { return [BOARD_PL[b] + ": " + x.from + " → " + x.to + " min", x.n]; }) : []);
      }, [])));
  }

  function changesSection(d, boards, h) {
    var p = d.params;
    var f = h.figure({ title: "Câte modificări are o cursă",
      how: "numărul de ori în care tabela a schimbat întârzierea unei curse (0 = nicio modificare citită). Sosirile și " +
        "plecările sunt separate. Citirile izolate care revin la valoarea de dinainte nu se numără." });
    var cells = h.multiples(f.host, boards.length);
    boards.forEach(function (b, bi) {
      var c = (d.steps[b] || {}).changes, cell = cells[bi];
      head(h, cell, b, c ? c.n : 0);
      if (!c || !c.n) { cell.append(h.el("p", "ss-empty", "Nicio cursă de arătat.")); return; }
      var nf = h.nf;
      h.hbars(cell, { board: b, max: c.n, title: "Modificări pe cursă — " + BOARD_PL[b],
        desc: "Câte curse au avut 0, 1, 2, 3 sau 4 și peste modificări de întârziere.",
        rows: c.hist.map(function (x) {
          return { label: x.key + (x.key === "1" ? " modificare" : " modificări"), value: x.n, low: !c.sufficient,
            valueText: String(x.n) + (x.pct != null ? " (" + nf.format(x.pct) + " %)" : ""),
            tip: x.n + " din " + c.n + " curse" };
        }) });
      cell.append(h.nLine("Medie: " + (c.mean == null ? "—" : nf.format(c.mean)) + " modificări/cursă · maximum: " + c.max + "."));
      if (!c.sufficient) cell.append(h.warn("Eșantion mic (N = " + c.n + " < " + p.min_sample + "): doar cifre brute."));
    });
    boards.forEach(function (b) {
      var c = (d.steps[b] || {}).changes;
      if (!c || !c.top.length) return;
      var box = h.el("div", "ss-recurrent");
      box.append(h.el("h3", "ss-mult-h", "Cursele cu cele mai multe modificări — " + BOARD_PL[b]));
      box.append(table(h, "Cursele cu cele mai multe modificări, " + BOARD_PL[b].toLowerCase(),
        ["Tren", "Stație", "Ziua", "Ora", "Modificări", "Valori citite (min)"],
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
