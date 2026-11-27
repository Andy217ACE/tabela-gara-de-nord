// © 2026 Andy217Ace
// "Administration" (#admin): hidden page (not in the menu), loaded on demand by app.js.
// Same admin key and same session as "OCR captures" (the cookie is shared).
// The token is not kept anywhere in the browser. DOM only via createElement/textContent (CSP).
// UI text comes from I18N (admin.*); error details returned by the API stay as the server sent them (Romanian).
(function () {
  "use strict";

  var MIN_AGE_MIN = 60;          // same default as scripts/merge_number_dups.py
  var REFRESH_MS = 10000;        // refresh interval of the "Server (live)" card
  var RELATION_KEY = { noise: "admin.relation.noise", truncated_number: "admin.relation.truncated" };

  function T(k, p) { return window.I18N.t(k, p); }

  var APPLY = {
    word: "APLICA", title: "admin.dupes.applyTitle", path: "/api/admin/tools/dupes/apply",
    body: { min_age_min: MIN_AGE_MIN },
    hint: "admin.dupes.applyHint",
    submit: "admin.dupes.applySubmit"
  };
  var RESTORE = {
    word: "RESTAUREAZA", title: "admin.dupes.restoreTitle", path: "/api/admin/tools/dupes/restore",
    body: { batch: null },
    hint: "admin.dupes.restoreHint",
    submit: "admin.dupes.restoreSubmit"
  };

  var root = null;
  var built = false;
  var loggedIn = false;
  var serverTimer = null;
  var serverBusy = false;

  // ---- helpers ----------------------------------------------------------------------

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }

  function $(id) { return document.getElementById(id); }

  function api(path, opts) {
    opts = opts || {};
    opts.credentials = "same-origin";
    opts.cache = "no-store";
    return fetch(path, opts).then(function (r) {
      if (r.status === 204) return { status: r.status, data: null };
      return r.json().catch(function () { return null; }).then(function (d) {
        return { status: r.status, data: d };
      });
    });
  }

  var fmtCache = {};
  function fmtTime() {
    var loc = window.I18N.lang() === "en" ? "en-GB" : "ro-RO";
    if (!fmtCache[loc]) {
      fmtCache[loc] = new Intl.DateTimeFormat(loc, {
        timeZone: "Europe/Bucharest", day: "2-digit", month: "2-digit",
        hour: "2-digit", minute: "2-digit", second: "2-digit"
      });
    }
    return fmtCache[loc];
  }

  function when(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    return isNaN(d) ? String(iso) : fmtTime().format(d);
  }

  function txt(v) { return v == null ? "—" : String(v); }

  function num(v, dec) { return v == null || isNaN(v) ? "—" : Number(v).toFixed(dec); }

  function mb(v) {
    if (v == null || isNaN(v)) return "—";
    return v >= 1024 ? (v / 1024).toFixed(1) + " GB" : Math.round(v) + " MB";
  }

  function gb(v) { return v == null || isNaN(v) ? "—" : Number(v).toFixed(1) + " GB"; }

  // 93784 s -> "1 day, 2 h" (ro: "1 zi, 2 h"); 5400 s -> "1 h 30 min"; 300 s -> "5 min"
  function uptime(s) {
    if (s == null || isNaN(s)) return "—";
    var d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    if (d) return d + " " + T(d === 1 ? "admin.uptime.day" : "admin.uptime.days") + ", " + h + " h";
    if (h) return h + " h " + m + " min";
    return m + " min";
  }

  function countOf(v) {
    if (Array.isArray(v)) return v.length;
    if (v && typeof v === "object") return Object.keys(v).length;
    return null;
  }

  // text of the `detail` field of an error response (string, or FastAPI's list of {msg})
  function detailOf(d) {
    if (!d || d.detail == null) return null;
    if (typeof d.detail === "string") return d.detail;
    if (Array.isArray(d.detail)) {
      var t = d.detail.map(function (x) { return x && x.msg ? x.msg : ""; }).filter(Boolean).join("; ");
      return t || null;
    }
    return null;
  }

  function message(text, isError) {
    var m = $("admin-msg");
    if (!m) return;
    m.textContent = text || "";
    m.className = "notice" + (isError ? " notice-error" : "");
    m.hidden = !text;
  }

  function stat(dl, label, value, cls) {
    var d = el("div", "admin-stat" + (cls ? " " + cls : ""));
    d.appendChild(el("dt", null, label));
    d.appendChild(el("dd", null, value));
    dl.appendChild(d);
  }

  function card(id, title) {
    var c = el("section", "admin-card panel");
    c.id = id;
    c.setAttribute("aria-label", title);
    c.appendChild(el("h2", "admin-h2", title));
    return c;
  }

  // ---- skeleton and login -----------------------------------------------------------

  function build() {
    root = $("view-admin");
    clear(root);
    root.setAttribute("aria-labelledby", "admin-heading");
    var head = el("div", "page-head admin-head");
    var h = el("h1", null, T("admin.title"));
    h.id = "admin-heading";
    head.appendChild(h);
    head.appendChild(el("p", "page-sub", T("admin.subtitle")));
    root.appendChild(head);
    var msg = el("p", "notice", "");
    msg.id = "admin-msg";
    msg.setAttribute("role", "status");
    msg.hidden = true;
    root.appendChild(msg);
    var body = el("div", "admin-body");
    body.id = "admin-body";
    root.appendChild(body);
    built = true;
  }

  function showLogin(note) {
    loggedIn = false;
    stopTimer();
    var body = $("admin-body");
    clear(body);
    var form = el("form", "admin-login panel");
    form.setAttribute("aria-label", T("admin.login.aria"));
    var label = el("label", "field");
    label.appendChild(el("span", "field-label", T("admin.login.key")));
    var input = el("input");
    input.type = "password";
    input.id = "admin-token";
    input.name = "token";
    input.autocomplete = "current-password";
    input.required = true;
    input.maxLength = 200;
    label.appendChild(input);
    form.appendChild(label);
    var btn = el("button", "btn", T("admin.login.submit"));
    btn.type = "submit";
    form.appendChild(btn);
    body.appendChild(form);
    message(note || "", !!note);
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      btn.disabled = true;
      api("/api/admin/login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: input.value })
      }).then(function (r) {
        btn.disabled = false;
        input.value = "";
        if (r.status === 200) { message(""); loadAll(); return; }
        if (r.status === 429) message(T("admin.msg.tooMany"), true);
        else if (r.status === 503) disabled();
        else message(T("admin.msg.wrongKey"), true);
        input.focus();
      }).catch(function () {
        btn.disabled = false;
        message(T("admin.msg.noServer"), true);
      });
    });
    input.focus();
  }

  function disabled() {
    loggedIn = false;
    stopTimer();
    clear($("admin-body"));
    message(T("admin.msg.disabled"), true);
  }

  function logout() {
    api("/api/admin/logout", { method: "POST" }).finally(function () {
      showLogin();
      message(T("admin.msg.loggedOut"));
    });
  }

  function handleAuth(r) {
    if (r.status === 401) showLogin(T("admin.msg.expired"));
    else if (r.status === 503) disabled();
    else if (r.status === 429) message(T("admin.msg.tooMany"), true);
    else message(T("admin.msg.loadError", { status: r.status }), true);
  }

  // ---- main view --------------------------------------------------------------------

  function loadAll() {
    loggedIn = true;
    var body = $("admin-body");
    clear(body);
    var bar = el("div", "admin-bar");
    var out = el("button", "btn btn-ghost btn-sm", T("admin.logout"));
    out.type = "button";
    out.addEventListener("click", logout);
    bar.appendChild(out);
    body.appendChild(bar);
    body.appendChild(dupesCard());
    body.appendChild(serverCard());
    body.appendChild(nvmeCard());
    body.appendChild(visitorsCard());
    body.appendChild(pushTestCard());
    body.appendChild(securityCard());
    body.appendChild(marksCard());
    loadReport();
    loadSecurity();
    loadVisitors();
    syncTimer();
  }

  // ---- duplicate train numbers ------------------------------------------------------

  function dupesCard() {
    var c = card("admin-dupes", T("admin.dupes.title"));
    c.appendChild(el("p", "admin-text", T("admin.dupes.intro")));
    var bar = el("div", "admin-actions");
    var refresh = el("button", "btn btn-ghost btn-sm", T("admin.dupes.reload"));
    refresh.type = "button";
    refresh.addEventListener("click", function () { loadReport(); });
    var apply = el("button", "btn btn-ghost btn-sm", T("admin.dupes.apply"));
    apply.type = "button";
    apply.addEventListener("click", function () { openConfirm(APPLY); });
    var restore = el("button", "btn btn-ghost btn-sm", T("admin.dupes.restore"));
    restore.type = "button";
    restore.addEventListener("click", function () { openConfirm(RESTORE); });
    bar.appendChild(refresh);
    bar.appendChild(apply);
    bar.appendChild(restore);
    c.appendChild(bar);
    var meta = el("p", "admin-meta", "");
    meta.id = "admin-dupes-meta";
    c.appendChild(meta);
    var counts = el("dl", "admin-stats");
    counts.id = "admin-dupes-counts";
    c.appendChild(counts);
    var pairs = el("div");
    pairs.id = "admin-dupes-pairs";
    c.appendChild(pairs);
    var confirm = el("div", "admin-confirm");
    confirm.id = "admin-confirm";
    confirm.hidden = true;
    c.appendChild(confirm);
    var result = el("div", "admin-result");
    result.id = "admin-result";
    result.setAttribute("role", "status");
    result.hidden = true;
    c.appendChild(result);
    return c;
  }

  function loadReport() {
    api("/api/admin/tools/dupes").then(function (r) {
      if (r.status !== 200 || !r.data) { handleAuth(r); return; }
      renderReport(r.data.report || {}, r.data.generated_at);
    }).catch(function () { message(T("admin.msg.noServer"), true); });
  }

  function renderReport(rep, at) {
    var meta = $("admin-dupes-meta");
    var dl = $("admin-dupes-counts");
    var box = $("admin-dupes-pairs");
    if (!meta || !dl || !box) return;
    var merge = rep.merge || {};
    var list = Array.isArray(merge.list) ? merge.list : [];
    meta.textContent = T("admin.dupes.reportAt", { time: when(at) });

    clear(dl);
    stat(dl, T("admin.dupes.stat.candidates"), txt(merge.services_affected));
    stat(dl, T("admin.dupes.stat.winnerRecent"), txt(merge.winner_seen_on_less_than_2_days));
    stat(dl, T("admin.dupes.stat.toMove"), txt(merge.observations_to_move));
    stat(dl, T("admin.dupes.stat.pairs"), txt(countOf(merge.by_number_pair)));
    stat(dl, T("admin.dupes.stat.listedOnly"), txt(countOf(rep.listed_not_merged)));
    stat(dl, T("admin.dupes.stat.aliases"), txt(countOf(rep.aliases)));
    stat(dl, T("admin.dupes.stat.divergent"), txt(countOf(rep.divergent_sched_listed_only)));

    clear(box);
    if (!list.length) {
      box.appendChild(el("p", "empty", T("admin.dupes.empty")));
      return;
    }
    var wrap = el("div", "admin-scroll");
    var t = el("table", "admin-table");
    var thead = el("thead");
    var tr = el("tr");
    ["lost", "winner", "station", "sched", "reason"].forEach(function (x) {
      var th = el("th", null, T("admin.dupes.col." + x));
      th.scope = "col";
      tr.appendChild(th);
    });
    thead.appendChild(tr);
    t.appendChild(thead);
    var tb = el("tbody");
    list.forEach(function (m) {
      var slot = m.slot || {};
      var row = el("tr");
      [
        (m.loser || {}).train, (m.winner || {}).train, slot.station, slot.sched,
        RELATION_KEY[m.relation] ? T(RELATION_KEY[m.relation]) : m.relation
      ].forEach(function (v) { row.appendChild(el("td", null, txt(v))); });
      tb.appendChild(row);
    });
    t.appendChild(tb);
    wrap.appendChild(t);
    box.appendChild(wrap);
  }

  // The confirmation is typed into a field (not a browser dialog); the button is enabled
  // only when the text is exactly the requested one.
  function openConfirm(cfg) {
    var box = $("admin-confirm");
    if (!box) return;
    clear(box);
    box.hidden = false;
    var form = el("form", "admin-form");
    form.setAttribute("aria-label", T(cfg.title));
    form.appendChild(el("p", "admin-text", T(cfg.hint)));
    var label = el("label", "field");
    label.appendChild(el("span", "field-label", T("admin.dupes.typeWord", { word: cfg.word })));
    var input = el("input");
    input.type = "text";
    input.autocomplete = "off";
    input.maxLength = 20;
    input.required = true;
    label.appendChild(input);
    form.appendChild(label);
    var row = el("div", "admin-actions");
    var go = el("button", "btn", T(cfg.submit));
    go.type = "submit";
    go.disabled = true;
    var cancel = el("button", "btn btn-ghost btn-sm", T("admin.dupes.cancel"));
    cancel.type = "button";
    cancel.addEventListener("click", function () { clear(box); box.hidden = true; });
    row.appendChild(go);
    row.appendChild(cancel);
    form.appendChild(row);
    input.addEventListener("input", function () { go.disabled = input.value !== cfg.word; });
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      if (input.value !== cfg.word) return;
      go.disabled = true;
      runAction(cfg, go, box);
    });
    box.appendChild(form);
    input.focus();
  }

  function getCsrf() {
    return api("/api/admin/csrf").then(function (r) {
      if (r.status !== 200 || !r.data || !r.data.token) return Promise.reject(r);
      return r.data.token;
    });
  }

  function runAction(cfg, btn, box) {
    message("");
    getCsrf().then(function (tok) {
      var payload = {};
      Object.keys(cfg.body).forEach(function (k) { payload[k] = cfg.body[k]; });
      payload.confirm = cfg.word;
      return api(cfg.path, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": tok },
        body: JSON.stringify(payload)
      });
    }).then(function (r) {
      btn.disabled = false;
      if (r.status === 200 && r.data) {
        clear(box);
        box.hidden = true;
        showResult(T(cfg.title), r.data);
        loadReport();
        return;
      }
      if (r.status === 401) handleAuth(r);
      else if (r.status === 503) disabled();
      else if (r.status === 403) message(T("admin.msg.csrf"), true);
      else if (r.status === 422) message(detailOf(r.data) || T("admin.msg.confirmWrong"), true);
      else if (r.status === 429) message(T("admin.msg.tooMany"), true);
      else message(detailOf(r.data) || T("admin.msg.error", { status: r.status }), true);
    }).catch(function (e) {
      btn.disabled = false;
      if (e && e.status) handleAuth(e);
      else message(T("admin.msg.noServer"), true);
    });
  }

  function showResult(title, data) {
    var box = $("admin-result");
    if (!box) return;
    clear(box);
    box.hidden = false;
    box.appendChild(el("h3", "admin-h3", T("admin.result.title", { title: title })));
    var dl = el("dl", "admin-stats");
    kv(dl, data, "");
    box.appendChild(dl);
  }

  // shows any response: the keys and values from the API, without inventing other fields
  function kv(dl, obj, prefix) {
    Object.keys(obj).forEach(function (k) {
      var v = obj[k];
      var label = prefix + k;
      if (v !== null && typeof v === "object" && !Array.isArray(v)) kv(dl, v, label + " · ");
      else if (Array.isArray(v)) stat(dl, label, T("admin.result.items", { n: v.length }));
      else stat(dl, label, txt(v));
    });
  }

  // ---- live server card -------------------------------------------------------------

  function serverCard() {
    var c = card("admin-server", T("admin.server.title"));
    c.appendChild(el("p", "admin-text", T("admin.server.intro")));
    var bar = el("div", "admin-actions");
    var b = el("button", "btn btn-ghost btn-sm", T("admin.refresh"));
    b.type = "button";
    b.addEventListener("click", function () { loadServer(); });
    bar.appendChild(b);
    c.appendChild(bar);
    var meta = el("p", "admin-meta", "");
    meta.id = "admin-server-meta";
    c.appendChild(meta);
    var dl = el("dl", "admin-stats");
    dl.id = "admin-server-stats";
    c.appendChild(dl);
    c.appendChild(el("h3", "admin-h3", T("admin.server.services")));
    var ul = el("ul", "admin-list");
    ul.id = "admin-server-services";
    c.appendChild(ul);
    return c;
  }

  function loadServer() {
    if (serverBusy || !$("admin-server-stats")) return;
    serverBusy = true;
    api("/api/admin/tools/server").then(function (r) {
      serverBusy = false;
      if (r.status === 200 && r.data) { renderServer(r.data); return; }
      if (r.status === 401 || r.status === 503 || r.status === 429) { handleAuth(r); return; }
      var m = $("admin-server-meta");
      if (m) m.textContent = T("admin.server.readError", { status: r.status });
    }).catch(function () {
      serverBusy = false;
      var m = $("admin-server-meta");
      if (m) m.textContent = T("admin.msg.noServer");
    });
  }

  function renderServer(s) {
    var dl = $("admin-server-stats");
    if (!dl) return;
    var load = s.load || {}, mem = s.memory || {}, disk = s.disk || {};
    var proc = s.process || {}, wd = s.watchdog || {};
    clear(dl);

    var l1 = load["1m"], cores = load.cores;
    stat(dl, T("admin.server.load"),
      num(l1, 2) + " / " + num(load["5m"], 2) + " / " + num(load["15m"], 2) +
      " · " + T("admin.server.cores") + ": " + txt(cores),
      l1 != null && cores != null && l1 > cores ? "is-bad" : "");

    var used = mem.total_mb != null && mem.available_mb != null ? mem.total_mb - mem.available_mb : null;
    stat(dl, T("admin.server.ram"),
      used == null ? "—" : T("admin.of", { a: mb(used), b: mb(mem.total_mb) }),
      used != null && mem.total_mb ? (used / mem.total_mb > 0.9 ? "is-bad" : "") : "");
    stat(dl, T("admin.server.swap"), T("admin.of", { a: mb(mem.swap_used_mb), b: mb(mem.swap_total_mb) }));
    stat(dl, T("admin.server.disk"), T("admin.of", { a: gb(disk.free_gb), b: gb(disk.total_gb) }));
    stat(dl, T("admin.server.uptime"), uptime(s.uptime_s));
    stat(dl, T("admin.server.process"), mb(proc.rss_mb));
    stat(dl, T("admin.server.wdFailures"), txt(wd.failures), wd.failures ? "is-bad" : "");
    stat(dl, T("admin.server.wdRestart"), when(wd.last_restart));

    var ul = $("admin-server-services");
    clear(ul);
    var svc = s.services;
    if (!svc || !Object.keys(svc).length) {
      ul.appendChild(el("li", "admin-muted", "—"));
    } else {
      Object.keys(svc).forEach(function (name) {
        var li = el("li", "admin-svc");
        li.appendChild(el("span", "admin-svc-name", name));
        li.appendChild(el("span", "admin-svc-state", txt(svc[name])));
        ul.appendChild(li);
      });
    }
    var meta = $("admin-server-meta");
    if (meta) meta.textContent = T("admin.server.updated", { time: when(s.generated_at) });
  }

  // ---- proposed OCR13 marks (static text, no API) -----------------------------------

  function marksCard() {
    var c = card("admin-marks", T("admin.marks.title"));
    c.appendChild(el("p", "admin-text", T("admin.marks.text")));
    return c;
  }

  // ---- live NVMe card (GET /api/admin/tools/nvme; colectorul root scrie nvme.json) ---------

  var NVME_TEMP_WARN_C = 70;  // temperature from which it is shown in red
  var nvmeBusy = false;

  function nvmeCard() {
    var c = card("admin-nvme", T("admin.nvme.title"));
    c.appendChild(el("p", "admin-text", T("admin.nvme.intro")));
    var bar = el("div", "admin-actions");
    var b = el("button", "btn btn-ghost btn-sm", T("admin.refresh"));
    b.type = "button";
    b.addEventListener("click", function () { loadNvme(); });
    bar.appendChild(b);
    c.appendChild(bar);
    var meta = el("p", "admin-meta", "");
    meta.id = "admin-nvme-meta";
    c.appendChild(meta);
    var dl = el("dl", "admin-stats");
    dl.id = "admin-nvme-stats";
    c.appendChild(dl);
    c.appendChild(el("h3", "admin-h3", T("admin.nvme.smartlog")));
    var sl = el("dl", "admin-stats");
    sl.id = "admin-nvme-smartlog";
    c.appendChild(sl);
    c.appendChild(el("h3", "admin-h3", T("admin.nvme.smartctl")));
    var sc = el("dl", "admin-stats");
    sc.id = "admin-nvme-smartctl";
    c.appendChild(sc);
    c.appendChild(el("h3", "admin-h3", T("admin.nvme.errorLog")));
    var ul = el("ul", "admin-list");
    ul.id = "admin-nvme-errors";
    c.appendChild(ul);
    return c;
  }

  function loadNvme() {
    if (nvmeBusy || !$("admin-nvme-stats")) return;
    nvmeBusy = true;
    api("/api/admin/tools/nvme").then(function (r) {
      nvmeBusy = false;
      if (r.status === 200 && r.data) { renderNvme(r.data); return; }
      if (r.status === 401 || r.status === 503 || r.status === 429) { handleAuth(r); return; }
      var m = $("admin-nvme-meta");
      if (m) m.textContent = T("admin.nvme.readError", { status: r.status });
    }).catch(function () {
      nvmeBusy = false;
      var m = $("admin-nvme-meta");
      if (m) m.textContent = T("admin.msg.noServer");
    });
  }

  function nvmeLabel(key) {
    var s = key.replace(/_/g, " ");
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  function pct(v) { return v == null ? "—" : v + " %"; }

  function units(v) {
    // one NVMe data unit = 1000 x 512 bytes
    return v == null ? "—" : T("admin.nvme.units", { n: txt(v), tb: (v * 512000 / 1e12).toFixed(2) });
  }

  function ageText(sec) {
    return sec < 120 ? sec + " s" : Math.round(sec / 60) + " min";
  }

  function renderNvme(s) {
    var dl = $("admin-nvme-stats");
    if (!dl) return;
    clear(dl);
    clear($("admin-nvme-smartlog"));
    clear($("admin-nvme-smartctl"));
    clear($("admin-nvme-errors"));
    var meta = $("admin-nvme-meta");
    if (!s.available) {
      if (meta) meta.textContent = T("admin.nvme.noData");
      return;
    }
    var sl = s.smart_log || {}, sc = s.smartctl || {}, h = sc.health || {};
    var dev = s.device || {};

    stat(dl, T("admin.nvme.smartState"), txt(sc.overall_health),
      sc.overall_health && sc.overall_health !== "PASSED" ? "is-bad" : "");
    stat(dl, "Model", txt(dev.model));
    stat(dl, T("admin.nvme.temp"), sl.temperature_c == null ? "—" : sl.temperature_c + " °C",
      sl.temperature_c >= NVME_TEMP_WARN_C ? "is-bad" : "");
    stat(dl, "Critical warning", txt(sl.critical_warning), sl.critical_warning ? "is-bad" : "");
    stat(dl, T("admin.nvme.spare"), pct(sl.available_spare),
      sl.available_spare != null && sl.available_spare_threshold != null &&
      sl.available_spare < sl.available_spare_threshold ? "is-bad" : "");
    stat(dl, T("admin.nvme.wear"), pct(sl.percentage_used));
    stat(dl, T("admin.nvme.mediaErrors"), txt(sl.media_errors), sl.media_errors ? "is-bad" : "");
    stat(dl, T("admin.nvme.unsafe"), txt(sl.unsafe_shutdowns));
    stat(dl, T("admin.nvme.poh"), txt(sl.power_on_hours));
    stat(dl, T("admin.nvme.dataRead"), units(sl.data_units_read));
    stat(dl, T("admin.nvme.dataWritten"), units(sl.data_units_written));
    stat(dl, T("admin.nvme.errEntries"), txt(sl.num_err_log_entries));
    stat(dl, T("admin.nvme.readAt"), when(s.collected_at) +
      (s.age_s != null ? " (" + T("admin.ago", { age: ageText(s.age_s) }) + ")" : ""), s.stale ? "is-bad" : "");

    var slDl = $("admin-nvme-smartlog");
    Object.keys(sl).forEach(function (k) { stat(slDl, nvmeLabel(k), txt(sl[k])); });
    var scDl = $("admin-nvme-smartctl");
    Object.keys(h).forEach(function (k) { stat(scDl, nvmeLabel(k), txt(h[k])); });

    var ul = $("admin-nvme-errors");
    var errs = s.error_log || [];
    if (!errs.length) {
      ul.appendChild(el("li", "admin-muted", T("admin.nvme.noEntries")));
    } else {
      errs.forEach(function (e) {
        ul.appendChild(el("li", "admin-svc", T("admin.nvme.errors") + " " + txt(e.error_count) + " · sqid " +
          txt(e.sqid) + " · cmdid " + txt(e.cmdid) + " · " + txt(e.status_field) +
          " · LBA " + txt(e.lba)));
      });
    }

    var notes = [];
    if (s.stale) notes.push(T("admin.nvme.stale"));
    if (!s.ok) notes.push(T("admin.nvme.partial", { err: txt(s.error) }));
    if (meta) meta.textContent = notes.length ? notes.join(" ") :
      T("admin.nvme.readAtMeta", { time: when(s.collected_at) });
  }

  // ---- Vizitatori online (GET /api/admin/visitors) + test push (POST /api/admin/push-test) ----
  // Paths/UA come from visitors: shown only via textContent.

  var visBusy = false;

  function visitorsCard() {
    var c = card("admin-visitors", T("admin.vis.title"));
    c.appendChild(el("p", "admin-text", T("admin.vis.intro")));
    var meta = el("p", "admin-meta", "");
    meta.id = "admin-vis-meta";
    meta.setAttribute("role", "status");
    c.appendChild(meta);
    var box = el("div", "admin-sec-box");
    box.id = "admin-vis-box";
    c.appendChild(box);
    return c;
  }

  function loadVisitors() {
    if (visBusy || !$("admin-vis-box")) return;
    visBusy = true;
    api("/api/admin/visitors").then(function (r) {
      visBusy = false;
      var meta = $("admin-vis-meta"), box = $("admin-vis-box");
      if (!meta || !box) return;
      if (r.status === 401 || r.status === 503 || r.status === 429) { handleAuth(r); return; }
      clear(box);
      if (r.status !== 200 || !r.data) { meta.textContent = T("admin.vis.error", { status: r.status }); return; }
      var v = r.data.visitors || [];
      meta.textContent = v.length ? T("admin.vis.count", { n: v.length }) : T("admin.vis.none");
      if (!v.length) return;
      var t = el("table", "admin-table"), tr = el("tr");
      ["ip", "client", "page", "reqs", "first", "last"].forEach(function (k) {
        tr.appendChild(el("th", null, T("admin.vis.col." + k)));
      });
      t.appendChild(tr);
      v.forEach(function (x) {
        var row = el("tr");
        [x.ip, x.client, x.path, String(x.requests), when(new Date(x.first_seen * 1000).toISOString()),
         when(new Date(x.last_seen * 1000).toISOString())].forEach(function (s) {
          row.appendChild(el("td", null, s));
        });
        t.appendChild(row);
      });
      box.appendChild(t);
    }).catch(function () { visBusy = false; });
  }

  function pushTestCard() {
    var c = card("admin-push-test", T("admin.push.title"));
    c.appendChild(el("p", "admin-text", T("admin.push.intro")));
    var bar = el("div", "admin-actions");
    var b = el("button", "btn btn-ghost btn-sm", T("admin.push.send"));
    b.type = "button";
    var out = el("p", "admin-meta", "");
    out.setAttribute("role", "status");
    function say(k, p) { out.textContent = T(k, p); b.disabled = false; }
    b.addEventListener("click", function () {
      b.disabled = true;
      out.textContent = "";
      var reg = "serviceWorker" in navigator ? navigator.serviceWorker.ready : Promise.resolve(null);
      reg.then(function (r) { return r && r.pushManager ? r.pushManager.getSubscription() : null; })
        .then(function (sub) {
          if (!sub) { say("admin.push.noSub"); return null; }
          return getCsrf().then(function (tok) {
            return api("/api/admin/push-test", {
              method: "POST",
              headers: { "Content-Type": "application/json", "X-CSRF-Token": tok },
              body: JSON.stringify({ endpoint: sub.endpoint })
            });
          }).then(function (r) {
            if (r.status === 401 || r.status === 503) { handleAuth(r); return; }
            var res = r.data && r.data.result;
            if (r.status === 429) say("admin.push.rate");
            else if (res === "sent") say("admin.push.sent");
            else if (res === "not_subscribed") say("admin.push.notSubscribed");
            else if (res === "gone") say("admin.push.gone");
            else if (res === "key_mismatch") {
              // 403: subscription made with an old VAPID key; re-subscribe (follows move along)
              var F = window.TabelaApp && window.TabelaApp.follows;
              return (F ? F.heal(true) : Promise.resolve(null)).then(function (ep) {
                say(ep ? "admin.push.keyMismatchFixed" : "admin.push.keyMismatch");
              }, function () { say("admin.push.keyMismatch"); });
            }
            else if (res === "not_configured") say("admin.push.notConfigured");
            else say("admin.push.error", { status: r.data && r.data.status != null ? r.data.status : r.status });
          });
        }).catch(function () { say("admin.msg.noServer"); });
    });
    bar.appendChild(b);
    c.appendChild(bar);
    c.appendChild(out);
    return c;
  }

  // ---- Securitate (GET /api/admin/security; exportatorul root scrie snapshot.json) --------
  // The probed IPs and paths come from hostile traffic: everything is shown only via textContent.

  var SEC_REFRESH_TICKS = 6;       // 6 x 10 s: the snapshot changes every 2 minutes
  function secTz() { return T("admin.sec.tz"); }
  var SEC_EVENT = { ban: "admin.sec.event.ban", unban: "admin.sec.event.unban", restore: "admin.sec.event.restore" };
  var SEC_WINDOWS = { "24h": "admin.sec.win.24h", "7d": "admin.sec.win.7d" };
  var secBusy = false;
  var secTick = 0;
  var secData = null;
  var secWindow = "24h";
  var secSort = {};                // id container -> { col, dir }

  function securityCard() {
    var c = card("admin-security", T("admin.sec.title"));
    c.appendChild(el("p", "admin-text", T("admin.sec.intro", { tz: secTz() })));
    var bar = el("div", "admin-actions");
    var b = el("button", "btn btn-ghost btn-sm", T("admin.refresh"));
    b.type = "button";
    b.addEventListener("click", function () { loadSecurity(); });
    bar.appendChild(b);
    var lab = el("label", "admin-sec-window");
    lab.appendChild(el("span", null, T("admin.sec.requestsOver")));
    var sel = el("select");
    sel.id = "admin-sec-window";
    Object.keys(SEC_WINDOWS).forEach(function (k) {
      var o = el("option", null, T(SEC_WINDOWS[k]));
      o.value = k;
      sel.appendChild(o);
    });
    sel.value = secWindow;
    sel.addEventListener("change", function () {
      secWindow = sel.value;
      if (secData) renderSecurity(secData);
    });
    lab.appendChild(sel);
    bar.appendChild(lab);
    c.appendChild(bar);
    var meta = el("p", "admin-meta", "");
    meta.id = "admin-sec-meta";
    meta.setAttribute("role", "status");
    c.appendChild(meta);
    var notes = el("ul", "admin-list admin-sec-notes");
    notes.id = "admin-sec-notes";
    c.appendChild(notes);
    var dl = el("dl", "admin-stats");
    dl.id = "admin-sec-summary";
    c.appendChild(dl);
    [["banned", "admin.sec.h.banned"], ["history", "admin.sec.h.history"],
     ["top", "admin.sec.h.top"]].forEach(function (x) {
      var h = el("h3", "admin-h3", T(x[1]));
      h.id = "admin-sec-" + x[0] + "-h";
      c.appendChild(h);
      var box = el("div", "admin-sec-box");
      box.id = "admin-sec-" + x[0];
      c.appendChild(box);
    });
    return c;
  }

  function loadSecurity() {
    if (secBusy || !$("admin-sec-summary")) return;
    secBusy = true;
    api("/api/admin/security").then(function (r) {
      secBusy = false;
      if (r.status === 200 && r.data) { renderSecurity(r.data); return; }
      if (r.status === 401 || r.status === 503 || r.status === 429) { handleAuth(r); return; }
      var m = $("admin-sec-meta");
      if (m) m.textContent = T("admin.sec.readError", { status: r.status });
    }).catch(function () {
      secBusy = false;
      var m = $("admin-sec-meta");
      if (m) m.textContent = T("admin.msg.noServer");
    });
  }

  function setHeading(key, title, n) {
    var h = $("admin-sec-" + key + "-h");
    if (h) h.textContent = n == null ? title : title + " (N = " + n + ")";
  }

  function secClear() {
    ["admin-sec-summary", "admin-sec-notes", "admin-sec-banned", "admin-sec-history",
     "admin-sec-top"].forEach(function (id) { var n = $(id); if (n) clear(n); });
    setHeading("banned", T("admin.sec.h.banned"), null);
    setHeading("history", T("admin.sec.h.history"), null);
    setHeading("top", T("admin.sec.h.top"), null);
  }

  function secNote(text) {
    var ul = $("admin-sec-notes");
    if (ul) ul.appendChild(el("li", "admin-sec-note", text));
  }

  function renderSecurity(s) {
    var meta = $("admin-sec-meta");
    if (!meta) return;
    secData = s.available ? s : null;
    secClear();
    if (!s.available) {
      if (s.reason === "stale") {
        meta.textContent = T("admin.sec.stale", { age: s.age_s != null ? ageText(s.age_s) : "—",
          time: when(s.generated_at), tz: secTz() });
      } else if (s.reason === "invalid") {
        meta.textContent = T("admin.sec.invalid");
      } else {
        meta.textContent = T("admin.sec.noData");
      }
      return;
    }
    meta.textContent = T("admin.sec.updated", { age: s.age_s != null ? ageText(s.age_s) : "—",
      time: when(s.generated_at), tz: secTz() });

    var f2 = s.fail2ban || {}, acc = s.access_log || {}, t = s.totals || {};
    if (!f2.available) secNote(T("admin.sec.note.f2Unavailable"));
    if (f2.available && f2.log_available === false) secNote(T("admin.sec.note.f2NoLog"));
    if (!acc.available) secNote(T("admin.sec.note.noAccess"));
    if (acc.truncated) secNote(T("admin.sec.note.truncated"));
    if (s.ips_truncated) secNote(T("admin.sec.note.ipsTruncated"));
    if (acc.ips_capped) secNote(T("admin.sec.note.ipsCapped"));
    if (s.banned_truncated) secNote(T("admin.sec.note.bannedTruncated"));
    if (s.probe_rule === "builtin") secNote(T("admin.sec.note.builtin"));

    var dl = $("admin-sec-summary");
    stat(dl, T("admin.sec.stat.bannedNow"), txt(t.banned_now), t.banned_now ? "is-bad" : "");
    stat(dl, T("admin.sec.stat.bans24"), txt(t.bans_24h));
    stat(dl, T("admin.sec.stat.bans7"), txt(t.bans_7d));
    stat(dl, T("admin.sec.stat.probes24"), txt(t.probes_24h));
    stat(dl, T("admin.sec.stat.probeIps24"), txt(t.probe_ips_24h));
    stat(dl, T("admin.sec.stat.requests24"), txt(t.requests_24h));
    stat(dl, T("admin.sec.stat.probes7"), txt(t.probes_7d));
    stat(dl, T("admin.sec.stat.requests7"), txt(t.requests_7d));
    var jails = Array.isArray(f2.jails) ? f2.jails : [];
    stat(dl, T("admin.sec.stat.jails"), jails.length ? jails.map(function (j) {
      return txt(j.name) + ": " + txt(j.banned_now);
    }).join(" · ") : "—");
    if (acc.lines != null) stat(dl, T("admin.sec.stat.lines"), txt(acc.lines) +
      (acc.parse_errors ? " (" + T("admin.sec.unrecognized") + ": " + acc.parse_errors + ")" : ""));

    var ips = s.ips || {};
    var winLabel = T(SEC_WINDOWS[secWindow]);
    function win(ip) { var x = ips[ip]; return x ? x[secWindow] || null : null; }
    function field(ip, k) { var w = win(ip); return w ? w[k] : null; }
    function pathsOf(ip) { var w = win(ip); return w && Array.isArray(w.paths) ? w.paths : null; }

    var banned = Array.isArray(s.banned) ? s.banned : [];
    setHeading("banned", T("admin.sec.h.banned"), banned.length);
    secTable("admin-sec-banned", [
      { label: "IP", val: function (b) { return b.ip; }, mono: true },
      { label: "Jail", val: function (b) { return b.jail; } },
      { label: T("admin.sec.col.bannedAt", { tz: secTz() }), val: function (b) { return b.banned_at; },
        text: function (b) { return when(b.banned_at); } },
      { label: T("admin.sec.col.expires", { tz: secTz() }),
        val: function (b) { return b.permanent ? "9999" : b.expires_at; },
        text: function (b) { return b.permanent ? T("admin.sec.permanent") : when(b.expires_at); } },
      { label: T("admin.sec.col.banCount"), num: true, val: function (b) { return b.bancount; } },
      { label: T("admin.sec.col.requests") + " " + winLabel, num: true, val: function (b) { return field(b.ip, "requests"); } },
      { label: T("admin.sec.col.probes") + " " + winLabel, num: true, val: function (b) { return field(b.ip, "probes"); } },
      { label: T("admin.sec.col.paths") + " " + winLabel, paths: function (b) { return pathsOf(b.ip); } }
    ], banned, { col: 2, dir: "desc" }, T("admin.sec.emptyBanned"));

    var hist = Array.isArray(s.history) ? s.history : [];
    setHeading("history", T("admin.sec.h.history"), hist.length);
    secTable("admin-sec-history", [
      { label: T("admin.sec.col.moment", { tz: secTz() }), val: function (h) { return h.at; },
        text: function (h) { return when(h.at); } },
      { label: T("admin.sec.col.event"), val: function (h) { return SEC_EVENT[h.event] ? T(SEC_EVENT[h.event]) : null; } },
      { label: "Jail", val: function (h) { return h.jail; } },
      { label: "IP", val: function (h) { return h.ip; }, mono: true }
    ], hist, { col: 0, dir: "desc" }, T("admin.sec.emptyHistory"));

    // the top comes ordered by 7 days; in the 24 h window only those with probes in 24 h remain
    var top = (Array.isArray(s.top) ? s.top : []).filter(function (x) {
      return secWindow !== "24h" || x.probes_24h == null || x.probes_24h > 0;
    });
    setHeading("top", T("admin.sec.h.top"), top.length);
    secTable("admin-sec-top", [
      { label: "IP", val: function (x) { return x.ip; }, mono: true },
      { label: T("admin.sec.col.probes") + " " + winLabel, num: true,
        val: function (x) { return secWindow === "24h" ? x.probes_24h : x.probes_7d; } },
      { label: T("admin.sec.col.requests") + " " + winLabel, num: true, val: function (x) {
        var v = field(x.ip, "requests");
        return v == null && secWindow === "7d" ? x.requests_7d : v;
      } },
      { label: T("admin.sec.col.lastRequest", { tz: secTz() }), val: function (x) { return x.last_seen; },
        text: function (x) { return when(x.last_seen); } },
      { label: T("admin.sec.col.bannedNow"), val: function (x) { return x.banned == null ? null : (x.banned ? T("admin.sec.yes") : T("admin.sec.no")); } },
      { label: T("admin.sec.col.paths") + " " + winLabel, paths: function (x) { return pathsOf(x.ip); } }
    ], top, { col: 1, dir: "desc" }, T("admin.sec.emptyTop", { win: winLabel }));
  }

  // comparator: missing values always last, numbers numerically, the rest as text
  function secCompare(a, b, dir) {
    if (a == null && b == null) return 0;
    if (a == null) return 1;
    if (b == null) return -1;
    var r = typeof a === "number" && typeof b === "number" ? a - b :
      String(a).localeCompare(String(b), "ro");
    return dir === "asc" ? r : -r;
  }

  function secTable(boxId, cols, rows, defSort, emptyText) {
    var box = $(boxId);
    if (!box) return;
    clear(box);
    if (!rows.length) { box.appendChild(el("p", "empty", emptyText)); return; }
    var st = secSort[boxId] || defSort;
    var sorted = rows.map(function (r, i) { return { r: r, i: i }; });
    var sortCol = cols[st.col];
    if (sortCol && sortCol.val) {
      sorted.sort(function (x, y) {
        return secCompare(sortCol.val(x.r), sortCol.val(y.r), st.dir) || x.i - y.i;
      });
    }
    var wrap = el("div", "admin-scroll");
    var t = el("table", "admin-table admin-sec-table");
    var tr = el("tr");
    cols.forEach(function (c, i) {
      var th = el("th", c.num ? "is-num" : null);
      th.scope = "col";
      if (c.val) {
        var on = i === st.col;
        if (on) th.setAttribute("aria-sort", st.dir === "asc" ? "ascending" : "descending");
        var btn = el("button", "admin-sort",
          c.label + (on ? (st.dir === "asc" ? " ↑" : " ↓") : ""));
        btn.type = "button";
        btn.addEventListener("click", function () {
          var dir = on ? (st.dir === "asc" ? "desc" : "asc") : (c.num ? "desc" : "asc");
          secSort[boxId] = { col: i, dir: dir };
          secTable(boxId, cols, rows, defSort, emptyText);
        });
        th.appendChild(btn);
      } else {
        th.textContent = c.label;
      }
      tr.appendChild(th);
    });
    var thead = el("thead");
    thead.appendChild(tr);
    t.appendChild(thead);
    var tb = el("tbody");
    sorted.forEach(function (x) {
      var row = el("tr");
      cols.forEach(function (c) {
        var td = el("td", ((c.num ? "is-num" : "") + (c.mono ? " admin-mono" : "")).trim() || null);
        if (c.paths) {
          var ps = c.paths(x.r);
          if (!ps) td.textContent = "—";
          else if (!ps.length) td.textContent = T("admin.sec.none");
          else ps.forEach(function (p) {
            td.appendChild(el("span", "admin-sec-path", txt(p.path) + " ×" + txt(p.count)));
          });
        } else {
          td.textContent = c.text ? c.text(x.r) : txt(c.val(x.r));
        }
        row.appendChild(td);
      });
      tb.appendChild(row);
    });
    t.appendChild(tb);
    wrap.appendChild(t);
    box.appendChild(wrap);
  }

  // ---- timer: only while #admin is shown, the page is visible and the session is valid ---

  function stopTimer() {
    if (serverTimer) { clearInterval(serverTimer); serverTimer = null; }
  }

  function syncTimer() {
    var on = loggedIn && location.hash === "#admin" && !document.hidden && !!$("admin-server-stats");
    if (!on) { stopTimer(); return; }
    if (!serverTimer) {
      serverTimer = setInterval(function () {
        loadServer();
        loadNvme();
        secTick += 1;
        if (secTick % SEC_REFRESH_TICKS === 0) loadSecurity();
        if (secTick % 3 === 0) loadVisitors();  // 3 x 10 s = 30 s
      }, REFRESH_MS);
      loadServer();
      loadNvme();
    }
  }

  // ---- view registration ------------------------------------------------------------

  function show() {
    if (!built) build();
    api("/api/admin/session").then(function (r) {
      if (r.status !== 200 || !r.data) { handleAuth(r); return; }
      if (!r.data.enabled) { disabled(); return; }
      if (r.data.authenticated) {
        message("");
        if (!loggedIn || !$("admin-dupes")) loadAll();
        else syncTimer();
      } else showLogin();
    }).catch(function () { message(T("admin.msg.noServer"), true); });
  }

  // language switch: rebuild the page in the new language (it is re-shown if it is the current page)
  document.addEventListener("i18n:change", function () {
    if (!built) return;
    stopTimer();
    built = false;
    loggedIn = false;
    secData = null;
    if (location.hash === "#admin") show();
  });

  window.addEventListener("hashchange", syncTimer);
  document.addEventListener("visibilitychange", syncTimer);

  window.TabelaApp = window.TabelaApp || {};
  window.TabelaApp.views = window.TabelaApp.views || {};
  window.TabelaApp.views.admin = { show: show };
})();
