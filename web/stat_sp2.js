// © 2026 Andy217Ace
// Tabela Gara de Nord — Statistici v3, sub-proiectul 2: lista trenurilor din spatele unui punct de
// grafic. Strat lazy (fișier propriu, nu în precache): statistici.js îl încarcă la primul click pe un
// bar/punct. Cere /api/stats/overview?...&detail=train_list&by=&key=&board= (cel mult 200 de rânduri)
// și o arată într-un <dialog> modal. Textul vine din date doar prin textContent (CSP, fără innerHTML).
// App.statSp2.drill(d, opener, h): d = { by, key, label, board }, h = ajutoarele din statistici.js.
"use strict";

(function () {
  var App = window.TabelaApp;

  function drill(d, opener, h) {
    var el = h.el, tt = h.tt;
    var prev = document.querySelector("dialog.ss-drill");
    if (prev) prev.remove();
    var dlg = el("dialog", "c3-dlg ss-drill");
    var tid = "ss-drill-t";
    dlg.setAttribute("aria-labelledby", tid);
    var box = el("div", "c3-dlg-box");
    var head = el("div", "c3-dlg-head");
    var title = el("h2", "c3-dlg-title", tt("stats.sp2.drill.title", { what: d.label }));
    title.id = tid;
    var close = el("button", "btn btn-ghost c3-dlg-close", tt("charts.dlg.close"));
    close.type = "button";
    close.setAttribute("aria-label", tt("charts.dlg.close_aria"));
    head.append(title, close);
    var body = el("div", "c3-dlg-body");
    body.setAttribute("aria-live", "polite");
    body.append(el("p", "ss-empty", tt("stats.sp2.drill.loading")));
    box.append(head, body);
    dlg.append(box);
    document.body.append(dlg);

    var ctrl = new AbortController();
    dlg.addEventListener("close", function () {
      ctrl.abort();
      dlg.remove();
      if (opener && opener.focus) opener.focus();
    });
    close.addEventListener("click", function () { dlg.close(); });
    dlg.addEventListener("click", function (e) { if (e.target === dlg) dlg.close(); });
    if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
    close.focus();

    var extra = { detail: "train_list", by: d.by, key: d.key };
    if (d.board) extra.board = d.board;
    var q = new URLSearchParams(h.query());
    Object.keys(extra).forEach(function (k) { q.set(k, extra[k]); });
    h.getJSON(h.api + "?" + q.toString(), ctrl).then(function (data) {
      var tl = data && data.train_list;
      if (!tl) throw new Error("no train_list");
      body.replaceChildren(render(tl, h));
    }).catch(function (e) {
      if (e && e.aborted) return;
      var msg = el("p", "notice notice-error", tt("stats.sp2.drill.error", { why: e && e.status ? h.errorText(e) : tt("stats.sp2.drill.unavailable") }));
      msg.setAttribute("role", "alert");
      body.replaceChildren(msg);
    });
  }

  function render(tl, h) {
    var el = h.el, tt = h.tt;
    var box = el("div", "ss-drill-box");
    if (!tl.rows.length) {
      box.append(el("p", "ss-empty", tt("stats.sp2.drill.empty")));
      return box;
    }
    box.append(el("p", "ss-n", tt("stats.sp2.drill.count", { n: tl.total })));
    var wrap = el("div", "st-scroll");
    wrap.tabIndex = 0;
    wrap.setAttribute("role", "region");
    wrap.setAttribute("aria-label", tt("stats.sp2.drill.table"));
    var t = el("table", "st-table ss-table");
    var tr = el("tr");
    tt("stats.sp2.drill.cols").split("|").forEach(function (c, i) {
      var th = el("th", i === 5 ? "st-num" : null, c);
      th.scope = "col";
      tr.append(th);
    });
    var thead = el("thead");
    thead.append(tr);
    var tbody = el("tbody");
    tl.rows.forEach(function (r) {
      var row = el("tr");
      var first = el("th", null, r.train);
      first.scope = "row";
      var delay = r.delay == null ? tt("stats.state." + r.state) : h.minutes(r.delay);
      row.append(first, el("td", null, h.dayText(r.date)), el("td", null, r.time), el("td", null, r.route || "—"),
        el("td", null, r.operator || "—"), el("td", "st-num", delay));
      tbody.append(row);
    });
    t.append(thead, tbody);
    wrap.append(t);
    box.append(wrap);
    if (tl.truncated) box.append(el("p", "st-warn ss-warn ss-drill-trunc", tt("stats.sp2.drill.truncated", { limit: tl.limit, total: tl.total })));
    return box;
  }

  App.statSp2 = { drill: drill };
})();
