// © 2026 Andy217Ace
// Statistici — „Erori de citire” (strat lazy, nu în precache; statistici.js îl încarcă la prima construire a
// secțiunii): tabelul 24 h / 48 h / 5 z / 7 z / 30 z din /api/stats/read-errors (ferestre glisante încheiate acum,
// independente de filtrele paginii) și explicația fiecărui rând. DOM doar prin createElement/textContent (CSP).
"use strict";

(function () {
  var App = window.TabelaApp;
  var el = App.el;
  var ROWS = ["frames", "frames_failed", "rows", "rows_unread", "rows_partial", "ghosts", "error_rate_pct"];
  var TTL = 60000;   // the server caches 5 min; a re-render (filters, language) reuses the last answer
  var cache = null;

  var tt = function (k, p) { return window.I18N.t(k, p); };

  function get() {
    if (cache && Date.now() - cache.at < TTL) return Promise.resolve(cache.data);
    return App.stats.getJSON("/api/stats/read-errors", new AbortController()).then(function (d) {
      cache = { at: Date.now(), data: d };
      return d;
    });
  }

  function table(d) {
    var nf = new Intl.NumberFormat(window.I18N.lang(), { maximumFractionDigits: 1 });
    var cap = tt("stats.fig.read_err.caption");
    var wrap = el("div", "st-scroll ss-re");
    wrap.tabIndex = 0;
    wrap.setAttribute("role", "region");
    wrap.setAttribute("aria-label", cap);
    var t = el("table", "st-table ss-table");
    t.append(el("caption", "sr-only", cap));
    var hr = el("tr");
    [tt("stats.fig.read_err.col")].concat(d.windows.map(function (w) { return tt("stats.fig.read_err.w." + w); }))
      .forEach(function (c, i) {
        var th = el("th", i ? "st-num" : null, c);
        th.scope = "col";
        hr.append(th);
      });
    var thead = el("thead");
    thead.append(hr);
    var tbody = el("tbody");
    ROWS.forEach(function (k) {
      var tr = el("tr");
      var th = el("th", null, tt("stats.fig.read_err." + k + ".t"));
      th.scope = "row";
      tr.append(th);
      d.windows.forEach(function (w) {
        var x = (d.data[w] || {})[k];
        tr.append(el("td", "st-num", x == null ? "—"
          : k === "error_rate_pct" ? tt("stats.fmt.pct", { v: nf.format(x) }) : nf.format(x)));
      });
      tbody.append(tr);
    });
    t.append(thead, tbody);
    wrap.append(t);
    return wrap;
  }

  function legend() {
    var dl = el("dl", "ss-gl");
    ROWS.forEach(function (k) {
      dl.append(el("dt", null, tt("stats.fig.read_err." + k + ".t")), el("dd", null, tt("stats.fig.read_err." + k + ".d")));
    });
    return dl;
  }

  function render(host) {
    get().then(function (d) {
      host.replaceChildren(table(d), legend());
    }).catch(function () {
      host.replaceChildren(el("p", "ss-empty", tt("stats.fig.read_err.error")));
    });
  }

  App.statReadErrors = { render: render };
})();
