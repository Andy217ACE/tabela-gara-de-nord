// © 2026 Andy217Ace
// „Colectare Infofer (intern)" (#infofer): admin-only view of the 7-day Infofer spike, loaded on demand
// by app.js. Infofer terms: never public. DOM via createElement/textContent only (strict CSP).
(function () {
  "use strict";

  function T(k, p) { return window.I18N.t(k, p); }

  var REFRESH_MS = 60000;
  var root = null;
  var timer = null;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  function $(id) { return document.getElementById(id); }
  function dash(v) { return v == null ? "—" : String(v); }

  function api(path, opts) {
    opts = opts || {};
    opts.credentials = "same-origin";
    opts.cache = "no-store";
    return fetch(path, opts).then(function (r) {
      return r.json().catch(function () { return null; }).then(function (d) { return { status: r.status, data: d }; });
    });
  }

  function fmt(iso, opts) {
    var d = new Date(iso);
    if (!iso || isNaN(d)) return "—";
    opts.timeZone = "Europe/Bucharest";
    return new Intl.DateTimeFormat(window.I18N.lang() === "en" ? "en-GB" : "ro-RO", opts).format(d);
  }
  function when(iso) { return fmt(iso, { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); }
  function hour(iso) { return fmt(iso, { hour: "2-digit", minute: "2-digit" }); }
  function delay(v) { return v == null ? "—" : T("infofer.min", { n: v }); }

  function message(text) {
    var m = $("infofer-msg");
    m.textContent = text || "";
    m.hidden = !text;
  }

  function build() {
    root = $("view-infofer");
    if (!root) {   // created here, hidden/shown by app.js route() like the other views
      root = el("section", "view view-infofer");
      root.id = "view-infofer";
      $("main").appendChild(root);
    }
    clear(root);
    root.setAttribute("aria-labelledby", "infofer-heading");
    var head = el("div", "page-head");
    var h = el("h1", null, T("infofer.title"));
    h.id = "infofer-heading";
    head.appendChild(h);
    head.appendChild(el("p", "page-sub", T("infofer.subtitle")));
    var back = el("a", null, T("infofer.back"));
    back.href = "#admin";
    head.appendChild(back);
    root.appendChild(head);
    var msg = el("p", "notice notice-error", "");
    msg.id = "infofer-msg";
    msg.setAttribute("role", "status");
    msg.hidden = true;
    root.appendChild(msg);
    var body = el("div", "infofer-body");
    body.id = "infofer-body";
    root.appendChild(body);
  }

  // same login as #ocr/#ocr2/#admin (same session cookie), reusing its texts
  function showLogin() {
    stop();
    var body = $("infofer-body");
    clear(body);
    window.TabelaApp.adminLogin({ keys: "ocr", cls: "infofer-login", message: message,
      onOk: function () { load(); start(); } }).then(function (f) {
      clear(body);
      body.appendChild(f.form);
    }, function () { message(T("ocr.msg.noServer")); });
  }

  // ---- cards --------------------------------------------------------------------------

  function card(id, title) {
    var c = el("section", "infofer-card panel");
    c.id = id;
    c.setAttribute("aria-labelledby", id + "-h");
    var h = el("h2", "infofer-h2", title);
    h.id = id + "-h";
    c.appendChild(h);
    return c;
  }

  function stat(dl, k, v) {
    var d = el("div", "infofer-stat");
    d.appendChild(el("dt", null, k));
    d.appendChild(el("dd", null, v));
    dl.appendChild(d);
  }

  function table(cls, heads, rows) {
    var wrap = el("div", "infofer-scroll");
    var t = el("table", "infofer-table " + cls);
    var tr = el("tr");
    heads.forEach(function (h) { var th = el("th", null, h); th.scope = "col"; tr.appendChild(th); });
    var thead = el("thead");
    thead.appendChild(tr);
    t.appendChild(thead);
    var tb = el("tbody");
    rows.forEach(function (cells) {
      var r = el("tr");
      cells.forEach(function (c) { r.appendChild(c instanceof Node ? c : el("td", null, dash(c))); });
      tb.appendChild(r);
    });
    t.appendChild(tb);
    wrap.appendChild(t);
    return wrap;
  }

  function healthCard(h) {
    var c = card("infofer-health", T("infofer.health.h"));
    var badge = el("p", "infofer-badge " + (h.ok ? "is-ok" : "is-bad"),
      h.ok ? T("infofer.health.ok") : T("infofer.health.problem"));
    badge.id = "infofer-badge";
    c.appendChild(badge);
    (h.problems || []).forEach(function (p) { c.appendChild(el("p", "infofer-note", T("infofer.problem." + p))); });
    var dl = el("dl", "infofer-stats");
    var last = h.last_run || {};
    stat(dl, T("infofer.health.lastRun"), when(last.at) + (last.error ? " · " + last.error : ""));
    stat(dl, T("infofer.health.lastRunDetail"), T("infofer.health.lastRunValue",
      { status: dash(last.http_status), n: dash(last.n_markers), kb: last.bytes == null ? "—" : Math.round(last.bytes / 1024) }));
    stat(dl, T("infofer.health.lastOk"), when(h.last_ok_at));
    stat(dl, T("infofer.health.runs24"), T("infofer.health.runs24Value",
      { runs: h.runs_24h, failed: h.failed_24h, pct: dash(h.fail_pct_24h) }));
    stat(dl, T("infofer.health.avgMarkers"), dash(h.avg_markers_24h));
    stat(dl, T("infofer.health.total"), String(h.runs_total));
    stat(dl, T("infofer.health.started"), when(h.first_run_at));
    stat(dl, T("infofer.health.days"), T("infofer.health.daysValue", { n: dash(h.days_elapsed), of: h.days_target }));
    c.appendChild(dl);
    return c;
  }

  function hourlyCard(rows) {
    var c = card("infofer-hourly", T("infofer.hourly.h"));
    if (!rows.length) { c.appendChild(el("p", "infofer-note", T("infofer.empty"))); return c; }
    c.appendChild(table("infofer-hourly-t", [T("infofer.hourly.hour"), T("infofer.hourly.runs"),
      T("infofer.hourly.failed"), T("infofer.hourly.markers")], rows.map(function (r) {
      var td = el("td", "infofer-runs");
      var m = el("meter");
      m.min = 0;
      m.max = 20;   // one run every 3 minutes
      m.value = r.runs;
      m.setAttribute("aria-hidden", "true");
      td.appendChild(m);
      td.appendChild(el("span", null, " " + r.runs));
      var f = el("td", r.failed ? "infofer-bad" : null, String(r.failed));
      return [hour(r.hour), td, f, r.avg_markers];
    })));
    return c;
  }

  function liveCard(lv) {
    var c = card("infofer-live", T("infofer.live.h"));
    c.appendChild(el("p", "infofer-note", T("infofer.live.note", { at: when(lv.fetched_at) })));
    if (!lv.trains.length) { c.appendChild(el("p", "infofer-note", T("infofer.live.none"))); return c; }
    c.appendChild(table("infofer-live-t", [T("infofer.live.train"), T("infofer.live.from"), T("infofer.live.sched"),
      T("infofer.live.board"), T("infofer.live.infofer"), T("infofer.live.report")], lv.trains.map(function (t) {
      var rep = el("td", t.stale ? "infofer-stale" : null,
        dash(t.report_hhmm) + (t.stale ? " · " + T("infofer.live.stale", { n: t.passed_time }) : ""));
      return [(t.category || t.train_type) + " " + t.train_no, t.station, t.sched_time,
        delay(t.board_delay), delay(t.infofer_delay), rep];
    })));
    return c;
  }

  function accuracyCard(d) {
    var c = card("infofer-accuracy", T("infofer.acc.h"));
    c.appendChild(el("p", "infofer-note", T("infofer.acc.note")));
    if (d.accuracy_error) { c.appendChild(el("p", "notice notice-error", d.accuracy_error)); return c; }
    var hz = (d.accuracy || {}).horizons || {};
    var keys = ["60", "30", "15"].filter(function (k) { return hz[k]; });
    if (!keys.length) { c.appendChild(el("p", "infofer-note", T("infofer.empty"))); return c; }
    function mb(s) { return s.mae == null ? "—" : s.mae + " / " + (s.bias > 0 ? "+" : "") + s.bias; }
    c.appendChild(table("infofer-acc-t", [T("infofer.acc.horizon"), T("infofer.acc.coverage"),
      T("infofer.acc.infofer"), T("infofer.acc.board"), T("infofer.acc.model"), T("infofer.acc.better")],
    keys.map(function (k) {
      var s = hz[k];
      return ["T−" + k, s.covered + "/" + s.eligible + " (" + dash(s.coverage_pct) + "%)",
        mb(s.infofer), mb(s.tabela), mb(s.model), s.infofer_better_pct == null ? "—" : s.infofer_better_pct + "%"];
    })));
    c.appendChild(el("p", "infofer-note", T("infofer.acc.legend")));
    return c;
  }

  function render(d) {
    var body = $("infofer-body");
    clear(body);
    if (!d.enabled) { body.appendChild(el("p", "infofer-note", T("infofer.disabled"))); return; }
    if (d.error) { message(T("infofer.error", { error: d.error })); return; }
    message("");
    body.appendChild(healthCard(d.health));
    body.appendChild(liveCard(d.live));
    body.appendChild(accuracyCard(d));
    body.appendChild(hourlyCard(d.hourly || []));
    body.appendChild(el("p", "infofer-note", T("infofer.updated", { at: when(d.now) })));
  }

  function load() {
    return api("/api/admin/infofer").then(function (r) {
      if (r.status === 401 || r.status === 403) { showLogin(); return; }
      if (r.status === 503) { stop(); message(T("ocr.msg.disabled")); return; }
      if (r.status !== 200 || !r.data) { message(T("ocr.msg.loadError", { status: r.status })); return; }
      render(r.data);
    }).catch(function () { message(T("ocr.msg.noServer")); });
  }

  function stop() { if (timer) { clearInterval(timer); timer = null; } }
  function start() {
    stop();
    timer = setInterval(function () { if (!document.hidden && location.hash === "#infofer") load(); }, REFRESH_MS);
  }

  function show() {
    if (!root) build();
    load();
    start();
  }

  document.addEventListener("i18n:change", function () {
    if (!root) return;
    root = null;
    if (location.hash === "#infofer") show();
  });

  window.TabelaApp = window.TabelaApp || {};
  window.TabelaApp.views = window.TabelaApp.views || {};
  window.TabelaApp.views.infofer = { show: show, hide: stop };
})();
