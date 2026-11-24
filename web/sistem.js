// © 2026 Andy217Ace
// Tabela Gara de Nord — the "System" page (#sistem): is the board alive? when was the last
// successful read, the rate of unread rows in the last hour, disk space, database size,
// reading quality over 24 h / 7 d and in-memory timings (OCR cycle, p50/p95 per API route).
// Data: GET /api/system (public); for admins also GET /api/admin/system (details, if the
// session is an admin one). A missing value is shown as "unknown" (sistem.unknown), never 0.
// DOM built with createElement/textContent only (CSP: no inline styles/scripts).
"use strict";

(function () {
  var App = window.TabelaApp = window.TabelaApp || {};
  App.views = App.views || {};
  var $ = function (id) { return document.getElementById(id); };
  var MIN_FRAMES = 10;  // mirrors app.system_status.OCR_MIN_FRAMES
  function T(k, p) { return window.I18N.t(k, p); }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function fetchJson(url) {
    return fetch(url, { headers: { Accept: "application/json" } }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  // age in seconds -> "3 min ago" / "45 s ago" (ro: "acum 3 min"); missing -> "unknown"
  function ago(s) {
    if (s == null) return T("sistem.unknown");
    if (s < 60) return T("sistem.ago", { v: s + " s" });
    if (s < 3600) return T("sistem.ago", { v: Math.round(s / 60) + " min" });
    return T("sistem.ago", { v: Math.round(s / 3600) + " h" });
  }

  function uptime(s) {
    if (s == null) return T("sistem.unknown");
    var d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    return (d ? d + " " + T("sistem.unit.day") + " " : "") + (h ? h + " h " : "") + m + " min";
  }

  function num(v, unit) {
    return v == null ? T("sistem.unknown") : v + (unit ? " " + unit : "");
  }

  var STATE = {
    live: { text: "sistem.state.live", cls: "sys-live" },
    date_vechi: { text: "sistem.state.old", cls: "sys-old" },
    necunoscut: { text: "sistem.state.unknown", cls: "sys-unknown" }
  };

  // one labelled row of the status list
  function row(label, value, sub) {
    var li = el("li", "sys-row");
    li.appendChild(el("span", "sys-label", label));
    li.appendChild(el("span", "sys-value", value));
    if (sub) li.appendChild(el("span", "sys-sub", sub));
    return li;
  }

  function ocrValue(o) {
    if (o.unread_rate_1h == null) return { value: T("sistem.unknown"), sub: T("sistem.ocr.noFrames") };
    var pct = Math.round(o.unread_rate_1h * 1000) / 10;  // one decimal
    var sub = T("sistem.ocr.lastHour", { n: o.n });
    if (o.insufficient) sub += " · " + T("sistem.ocr.insufficient");
    return { value: T("sistem.ocr.unreadPct", { pct: pct }), sub: sub };
  }

  function render(d) {
    var box = $("sys-body");
    box.replaceChildren();
    var st = STATE[d.stare] || STATE.necunoscut;
    var hero = el("div", "sys-hero");
    hero.appendChild(el("span", "sys-badge " + st.cls, T(st.text)));
    hero.appendChild(el("p", "sys-hero-text",
      d.poller && d.poller.last_ok_age_s != null
        ? T("sistem.lastOkHero", { v: ago(d.poller.last_ok_age_s) })
        : T("sistem.noOk")));
    box.appendChild(hero);

    var list = el("ul", "sys-list");
    var o = ocrValue(d.ocr || {});
    list.appendChild(row(T("sistem.row.version"), num(d.version)));
    list.appendChild(row(T("sistem.row.lastOk"), d.poller ? ago(d.poller.last_ok_age_s) : T("sistem.unknown")));
    list.appendChild(row(T("sistem.row.unread"), o.value, o.sub));
    list.appendChild(row(T("sistem.row.diskFree"), num(d.disk && d.disk.free_gb, "GB")));
    list.appendChild(row(T("sistem.row.dbSize"), num(d.db && d.db.size_mb, "MB"),
      d.db && d.db.wal_mb != null ? T("sistem.row.wal", { v: d.db.wal_mb }) : null));
    list.appendChild(row(T("sistem.row.uptime"), uptime(d.uptime_s)));
    box.appendChild(list);
    if (d.ocr_quality) box.appendChild(qualityBlock(d.ocr_quality));
    if (d.perf) box.appendChild(perfBlock(d.perf));
  }

  // --- reading quality (24 h / 7 d) and timings (since restart) ---------------------------
  var MAX_ROUTES = 8;  // busiest routes shown; the API returns all of them

  function pct(v) { return v == null ? T("sistem.unknown") : v + " %"; }

  function qualityBlock(q) {
    var sec = el("div", "sys-block");
    sec.appendChild(el("h2", "sys-block-title", T("sistem.quality.title")));
    var list = el("ul", "sys-list");
    [["h24", "sistem.quality.h24"], ["d7", "sistem.quality.d7"]].forEach(function (p) {
      var w = q[p[0]] || {};
      list.appendChild(row(T(p[1]), pct(w.frames_ok_pct),
        T("sistem.quality.sub", { frames: num(w.frames), rows: num(w.rows), rowsPct: pct(w.rows_ok_pct) })));
    });
    sec.appendChild(list);
    return sec;
  }

  function ms(v) { return num(v, "ms"); }

  function perfBlock(p) {
    var sec = el("div", "sys-block");
    sec.appendChild(el("h2", "sys-block-title", T("sistem.perf.title")));
    sec.appendChild(el("p", "sys-note", T("sistem.perf.note")));
    var list = el("ul", "sys-list");
    var c = p.ocr_cycle || {};
    list.appendChild(row(T("sistem.perf.ocrCycle"), c.n ? ms(c.p50_ms) + " / " + ms(c.p95_ms) : T("sistem.unknown"),
      T("sistem.perf.ocrSub", { last: ms(c.last_ms), n: num(c.n) })));
    (p.routes || []).slice(0, MAX_ROUTES).forEach(function (r) {
      var li = row(r.route, ms(r.p50_ms) + " / " + ms(r.p95_ms), T("sistem.perf.requests", { n: r.n }));
      li.firstChild.classList.add("sys-route");
      list.appendChild(li);
    });
    if (!(p.routes || []).length) list.appendChild(row(T("sistem.perf.routes"), T("sistem.perf.noRoutes")));
    sec.appendChild(list);
    return sec;
  }

  // "Data quality per day" (stat_quality_daily.js/.css) is loaded on demand, for admins only
  function loadQualityDaily(cb) {
    if (App.statQualityDaily) return cb();
    var link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "stat_quality_daily.css";
    document.head.appendChild(link);
    var sc = document.createElement("script");
    sc.src = "stat_quality_daily.js";
    sc.addEventListener("load", cb);
    document.head.appendChild(sc);
  }

  function renderAdmin(d) {
    var box = $("sys-admin");
    box.replaceChildren();
    box.appendChild(el("h2", "sys-admin-title", T("sistem.admin.title")));
    var list = el("ul", "sys-list");
    var p = d.poller || {};
    var err = p.last_error ? T("sistem.admin.code") + " " + p.last_error + (p.last_error_age_s != null ? ", " + ago(p.last_error_age_s) : "") : T("sistem.admin.noError");
    list.appendChild(row(T("sistem.admin.lastError"), err));
    var w = d.ocr_window || {};
    list.appendChild(row(T("sistem.admin.frames"), num(w.frames)));
    list.appendChild(row(T("sistem.admin.fullFrames"), num(w.full_frames)));
    list.appendChild(row(T("sistem.admin.retried"), num(w.frames_retried)));
    list.appendChild(row(T("sistem.admin.duration"), num(w.duration_ms_p50, "ms")));
    list.appendChild(row(T("sistem.admin.diskTotal"), num(d.disk && d.disk.total_gb, "GB")));
    // version details stay on the admin endpoint (public, they would be a target list)
    if (d.tesseract) list.appendChild(row(T("sistem.admin.tesseract"), num(d.tesseract.version),
      (d.tesseract.langs || []).length ? T("sistem.admin.langs", { v: d.tesseract.langs.join(", ") }) : null));
    if ("security_updates" in d) list.appendChild(row(T("sistem.admin.secUpdates"), num(d.security_updates)));
    box.appendChild(list);
    loadQualityDaily(function () { App.statQualityDaily.mount(box); });  // data quality per day (admin)
    box.hidden = false;
  }

  // the admin block only for an admin session: 401/403 (or no access) keeps it hidden
  function loadAdmin() {
    var box = $("sys-admin");
    fetchJson("/api/admin/system").then(renderAdmin, function () { box.hidden = true; });
  }

  // section created on demand (like the OCR view), so the page needs no markup in index.html
  function ensureSection() {
    if ($("view-sistem")) return;
    var sec = el("section", "view view-sistem");
    sec.id = "view-sistem";
    sec.setAttribute("aria-labelledby", "sistem-heading");
    sec.hidden = true;
    var h = el("h1", "sys-heading", T("sistem.title"));
    h.id = "sistem-heading";
    sec.appendChild(h);
    sec.appendChild(el("p", "sys-intro", T("sistem.intro")));
    var err = el("p", "sys-error", T("sistem.error"));
    err.id = "sys-error";
    err.hidden = true;
    sec.appendChild(err);
    var body = el("div", "sys-body");
    body.id = "sys-body";
    sec.appendChild(body);
    var admin = el("div", "sys-admin");
    admin.id = "sys-admin";
    admin.hidden = true;
    sec.appendChild(admin);
    $("main").appendChild(sec);
  }

  // language switch: drop the built section so it is rebuilt in the new language
  document.addEventListener("i18n:change", function () {
    var sec = $("view-sistem");
    if (!sec) return;
    var wasShown = !sec.hidden;
    sec.remove();
    if (wasShown && location.hash === "#sistem") App.views.sistem.show();
  });

  App.views.sistem = {
    show: function () {
      ensureSection();
      $("view-sistem").hidden = false;  // created after the router hid the views: show it now
      var err = $("sys-error");
      err.hidden = true;
      fetchJson("/api/system").then(function (d) {
        render(d);
        if (d.admin) loadAdmin();  // anonymous visitors get no admin request (no 503 noise)
      }, function () {
        err.hidden = false;
      });
    }
  };
})();
