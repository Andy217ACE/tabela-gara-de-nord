// © 2026 Andy217Ace
// Statistici v3, sub-proiectul 2 (claritate vizuală) — strat lazy (stat_sp2.js + stat_sp2.css, nu în
// precache; statistici.js îl încarcă înaintea primei afișări): tooltips pe metrici (hover și focus),
// text scurt + „Citește mai mult”, modul simplu/expert, contrast ridicat și lista trenurilor din
// spatele unui punct de grafic (/api/stats/overview?...&detail=train_list, cel mult 200 de rânduri).
// Textul vine din date doar prin textContent (CSP, fără innerHTML). Fără acest strat pagina rămâne
// completă, doar fără aceste ajutoare.
"use strict";

(function () {
  var App = window.TabelaApp;
  var seq = 0;
  var MODE_KEY = "tabela.statsMode";

  // Metric explanation: hover and keyboard focus (CSS), Escape hides it.
  function help(node, key, tt) {
    tt = tt || window.I18N.t;
    var tip = document.createElement("span");
    tip.className = "ss-tip";
    tip.id = "ss-tip-" + (++seq);
    tip.textContent = tt(key);
    tip.setAttribute("role", "tooltip");
    node.classList.add("ss-help");
    node.tabIndex = 0;
    node.setAttribute("aria-describedby", tip.id);
    node.append(tip);
    node.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      node.classList.add("ss-help-off");
      node.addEventListener("blur", function () { node.classList.remove("ss-help-off"); }, { once: true });
    });
    node.addEventListener("mouseleave", function () { node.classList.remove("ss-help-off"); });
    return node;
  }

  // "De ce conteaza": the first sentence, the rest behind „Citește mai mult”.
  function why(p) {
    var text = p.lastChild.textContent;
    p.removeChild(p.lastChild);
    var m = /^([\s\S]*?[.!?])\s+(?=[A-Z\u0102\u00C2\u00CE\u0218\u021A\u201E"(])([\s\S]+)$/.exec(text);
    var tt = window.I18N.t;
    var short = document.createElement("span");
    short.className = "ss-why-short";
    short.textContent = m ? m[1] : text;
    p.append(short);
    if (!m) return;
    var rest = document.createElement("span");
    rest.className = "ss-more-rest";
    rest.id = "ss-more-" + (++seq);
    rest.hidden = true;
    rest.textContent = " " + m[2];
    var b = document.createElement("button");
    b.type = "button";
    b.className = "btn btn-ghost btn-sm ss-more";
    b.textContent = tt("stats.sp2.more");
    b.setAttribute("aria-expanded", "false");
    b.setAttribute("aria-controls", rest.id);
    b.addEventListener("click", function () {
      var open = rest.hidden;
      rest.hidden = !open;
      b.setAttribute("aria-expanded", open ? "true" : "false");
      b.textContent = tt(open ? "stats.sp2.less" : "stats.sp2.more");
    });
    p.append(rest, " ", b);
  }

  // Median vs mean (expert only): the "?" explanation and one line per board on the mean card.
  function median(card, boards, h) {
    var hi = h.el("button", "ss-help-i ss-exp", "?");
    hi.type = "button";
    hi.setAttribute("aria-label", h.tt("stats.gl.median.t"));
    card.prepend(help(hi, "stats.sp2.help.median", h.tt));
    var parts = Object.keys(boards || {}).filter(function (b) { return boards[b] && boards[b].n && boards[b].median != null; })
      .map(function (b) { return h.tt("stats.sp2.median", { board: h.board(b), median: h.minutes(boards[b].median), mean: h.minutes(boards[b].mean) }); });
    if (parts.length) card.append(h.el("p", "ss-card-s ss-exp", parts.join(" · ")));
  }

  // Display options in the filter bar (never filters: their change does not reload the data).
  function getMode() {
    try { return localStorage.getItem(MODE_KEY) === "expert" ? "expert" : "simple"; } catch (e) { return "simple"; }
  }
  function option(h, id, key, on, set) {
    var lab = h.el("label", "ss-check");
    var inp = h.el("input");
    inp.type = "checkbox";
    inp.id = id;
    inp.checked = on;
    inp.addEventListener("change", function (e) { e.stopPropagation(); set(inp.checked); });
    lab.append(inp, h.el("span", null, h.tt(key)));
    return lab;
  }
  function mount(fields, h) {
    var root = document.getElementById("st-statistici");
    root.dataset.mode = getMode();
    var T = window.TabelaTheme;
    fields.append(
      option(h, "ss-expert", "stats.sp2.expert", root.dataset.mode === "expert", function (on) {
        root.dataset.mode = on ? "expert" : "simple";
        try {
          if (on) localStorage.setItem(MODE_KEY, "expert"); else localStorage.removeItem(MODE_KEY);
        } catch (e) { /* fără stocare: ține până la reîncărcare */ }
      }),
      option(h, "ss-contrast", "stats.sp2.contrast", !!(T && T.getContrast()), function (on) { if (T) T.setContrast(on); }));
  }

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
    body.append(el("p", "ss-empty", tt("stats.loading")));
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
      body.replaceChildren(render(tl, h, d.label));
    }).catch(function (e) {
      if (e && e.aborted) return;
      var msg = el("p", "notice notice-error", tt("stats.sp2.drill.error"));
      msg.setAttribute("role", "alert");
      body.replaceChildren(msg);
    });
  }

  function render(tl, h, label) {
    var el = h.el, tt = h.tt;
    var box = el("div", "ss-drill-box");
    if (!tl.rows.length) {
      box.append(el("p", "ss-empty", tt("stats.ranked.no_journey")));
      return box;
    }
    var wrap = el("div", "st-scroll");
    wrap.tabIndex = 0;
    wrap.setAttribute("role", "region");
    wrap.setAttribute("aria-label", tt("stats.sp2.drill.title", { what: label }));
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

  var HELP = { "ss-badge-sev": "stats.sp2.help.sev", "ss-badge-conf": "stats.sp2.help.conf", "ss-badge-n": "stats.gl.n.d" };

  // Called after every render: additions to the freshly drawn page (idempotent per node).
  function enhance(ui, d, h) {
    var body = ui.body;
    if (!ui.sp2) {   // once per page build: display options + click handlers
      ui.sp2 = true;
      mount(ui.fields, h);
      body.addEventListener("click", function (e) {
        var g = e.target.closest ? e.target.closest("[data-drill]") : null;
        if (g) open(g, h);
      });
      body.addEventListener("keydown", function (e) {   // Enter on a chart: the mark the arrow keys are on
        if (e.key !== "Enter" || !e.target.matches || !e.target.matches("svg.ss-svg")) return;
        var g = e.target.querySelector(".c3-act[data-drill]");
        if (g) { e.preventDefault(); open(g, h); }
      });
    }
    Object.keys(HELP).forEach(function (c) {
      [].forEach.call(body.querySelectorAll("." + c), function (n) { help(n, HELP[c], h.tt); });
    });
    [].forEach.call(body.querySelectorAll(".ss-prob-why"), why);
    var mean = ui.quick.querySelectorAll(".ss-card")[1];
    if (mean) median(mean, d.boards, h);
  }

  function open(g, h) {
    var a = JSON.parse(g.getAttribute("data-drill"));
    drill({ by: a[0], key: a[1], label: a[2], board: a[3] }, g.closest("svg") || g, h);
  }

  App.statSp2 = { enhance: enhance };
})();
