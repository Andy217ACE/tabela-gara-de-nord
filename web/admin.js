// © 2026 Andy217Ace
// „Administrare" (#admin): pagină ascunsă (nu e în meniu), încărcată la cerere de app.js.
// Aceeași cheie de administrare și aceeași sesiune ca la „Capturi OCR" (cookie-ul e comun).
// Token-ul nu se păstrează nicăieri în browser. DOM doar cu createElement/textContent (CSP).
(function () {
  "use strict";

  var MIN_AGE_MIN = 60;          // aceeași valoare implicită ca scripts/merge_number_dups.py
  var REFRESH_MS = 10000;        // reîmprospătarea cardului „Server (live)"
  var RELATION_LABEL = { noise: "zgomot OCR", truncated_number: "număr trunchiat" };

  var APPLY = {
    word: "APLICA", title: "Aplică fuziunea", path: "/api/admin/tools/dupes/apply",
    body: { min_age_min: MIN_AGE_MIN },
    hint: "Se face o copie de siguranță a bazei înainte. Fuziunea se poate anula cu „Restaurează ultimul lot”.",
    submit: "Confirmă aplicarea"
  };
  var RESTORE = {
    word: "RESTAUREAZA", title: "Restaurează ultimul lot", path: "/api/admin/tools/dupes/restore",
    body: { batch: null },
    hint: "Se pun înapoi rândurile arhivate de ultimul lot de fuziune.",
    submit: "Confirmă restaurarea"
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

  var fmtTime = new Intl.DateTimeFormat("ro-RO", {
    timeZone: "Europe/Bucharest", day: "2-digit", month: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit"
  });

  function when(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    return isNaN(d) ? String(iso) : fmtTime.format(d);
  }

  function txt(v) { return v == null ? "—" : String(v); }

  function num(v, dec) { return v == null || isNaN(v) ? "—" : Number(v).toFixed(dec); }

  function mb(v) {
    if (v == null || isNaN(v)) return "—";
    return v >= 1024 ? (v / 1024).toFixed(1) + " GB" : Math.round(v) + " MB";
  }

  function gb(v) { return v == null || isNaN(v) ? "—" : Number(v).toFixed(1) + " GB"; }

  // 93784 s -> "1 zi, 2 h"; 5400 s -> "1 h 30 min"; 300 s -> "5 min"
  function uptime(s) {
    if (s == null || isNaN(s)) return "—";
    var d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    if (d) return d + (d === 1 ? " zi" : " zile") + ", " + h + " h";
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
    var h = el("h1", null, "Administrare");
    h.id = "admin-heading";
    head.appendChild(h);
    head.appendChild(el("p", "page-sub",
      "Unelte de întreținere pentru administratori. Aceeași cheie ca la Capturi OCR."));
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
    form.setAttribute("aria-label", "Autentificare administrare");
    var label = el("label", "field");
    label.appendChild(el("span", "field-label", "Cheie de administrare"));
    var input = el("input");
    input.type = "password";
    input.id = "admin-token";
    input.name = "token";
    input.autocomplete = "current-password";
    input.required = true;
    input.maxLength = 200;
    label.appendChild(input);
    form.appendChild(label);
    var btn = el("button", "btn", "Autentificare");
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
        if (r.status === 429) message("Prea multe încercări. Reîncearcă peste un minut.", true);
        else if (r.status === 503) disabled();
        else message("Cheie greșită.", true);
        input.focus();
      }).catch(function () {
        btn.disabled = false;
        message("Serverul nu răspunde.", true);
      });
    });
    input.focus();
  }

  function disabled() {
    loggedIn = false;
    stopTimer();
    clear($("admin-body"));
    message("Administrarea este dezactivată pe acest server (ADMIN_TOKEN nesetat).", true);
  }

  function logout() {
    api("/api/admin/logout", { method: "POST" }).finally(function () {
      showLogin();
      message("Ai ieșit din administrare.");
    });
  }

  function handleAuth(r) {
    if (r.status === 401) showLogin("Sesiunea a expirat. Autentifică-te din nou.");
    else if (r.status === 503) disabled();
    else if (r.status === 429) message("Prea multe încercări. Reîncearcă peste un minut.", true);
    else message("Eroare la încărcare (" + r.status + ").", true);
  }

  // ---- main view --------------------------------------------------------------------

  function loadAll() {
    loggedIn = true;
    var body = $("admin-body");
    clear(body);
    var bar = el("div", "admin-bar");
    var out = el("button", "btn btn-ghost btn-sm", "Ieșire");
    out.type = "button";
    out.addEventListener("click", logout);
    bar.appendChild(out);
    body.appendChild(bar);
    body.appendChild(dupesCard());
    body.appendChild(serverCard());
    body.appendChild(marksCard());
    loadReport();
    syncTimer();
  }

  // ---- duplicate train numbers ------------------------------------------------------

  function dupesCard() {
    var c = card("admin-dupes", "Duplicate de numere de tren");
    c.appendChild(el("p", "admin-text",
      "Unește două numere citite diferit pentru același rând de pe tablă. Fuziunea mută " +
      "observațiile pe numărul câștigător și arhivează rândurile pierdute; e reversibilă. " +
      "Înainte de fiecare aplicare se face o copie de siguranță a bazei."));
    var bar = el("div", "admin-actions");
    var refresh = el("button", "btn btn-ghost btn-sm", "Reîncarcă raportul");
    refresh.type = "button";
    refresh.addEventListener("click", function () { loadReport(); });
    var apply = el("button", "btn btn-ghost btn-sm", "Aplică fuziunea…");
    apply.type = "button";
    apply.addEventListener("click", function () { openConfirm(APPLY); });
    var restore = el("button", "btn btn-ghost btn-sm", "Restaurează ultimul lot…");
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
    }).catch(function () { message("Serverul nu răspunde.", true); });
  }

  function renderReport(rep, at) {
    var meta = $("admin-dupes-meta");
    var dl = $("admin-dupes-counts");
    var box = $("admin-dupes-pairs");
    if (!meta || !dl || !box) return;
    var merge = rep.merge || {};
    var list = Array.isArray(merge.list) ? merge.list : [];
    meta.textContent = "Raport generat la " + when(at) + ".";

    clear(dl);
    stat(dl, "Candidați la fuziune", txt(merge.services_affected));
    stat(dl, "Câștigător văzut < 2 zile", txt(merge.winner_seen_on_less_than_2_days));
    stat(dl, "Observații de mutat", txt(merge.observations_to_move));
    stat(dl, "Perechi de numere", txt(countOf(merge.by_number_pair)));
    stat(dl, "Doar listați (nemutați)", txt(countOf(rep.listed_not_merged)));
    stat(dl, "Aliasuri de stații", txt(countOf(rep.aliases)));
    stat(dl, "Program divergent (doar listat)", txt(countOf(rep.divergent_sched_listed_only)));

    clear(box);
    if (!list.length) {
      box.appendChild(el("p", "empty", "Nicio pereche propusă acum."));
      return;
    }
    var wrap = el("div", "admin-scroll");
    var t = el("table", "admin-table");
    var thead = el("thead");
    var tr = el("tr");
    ["Pierdut", "Câștigător", "Stație", "Ora programată", "Motiv"].forEach(function (x) {
      var th = el("th", null, x);
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
        RELATION_LABEL[m.relation] || m.relation
      ].forEach(function (v) { row.appendChild(el("td", null, txt(v))); });
      tb.appendChild(row);
    });
    t.appendChild(tb);
    wrap.appendChild(t);
    box.appendChild(wrap);
  }

  // Confirmarea se scrie într-un câmp (nu o fereastră a browserului); butonul se activează
  // doar când textul e exact cel cerut.
  function openConfirm(cfg) {
    var box = $("admin-confirm");
    if (!box) return;
    clear(box);
    box.hidden = false;
    var form = el("form", "admin-form");
    form.setAttribute("aria-label", cfg.title);
    form.appendChild(el("p", "admin-text", cfg.hint));
    var label = el("label", "field");
    label.appendChild(el("span", "field-label", "Scrie " + cfg.word + " pentru confirmare"));
    var input = el("input");
    input.type = "text";
    input.autocomplete = "off";
    input.maxLength = 20;
    input.required = true;
    label.appendChild(input);
    form.appendChild(label);
    var row = el("div", "admin-actions");
    var go = el("button", "btn", cfg.submit);
    go.type = "submit";
    go.disabled = true;
    var cancel = el("button", "btn btn-ghost btn-sm", "Renunță");
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
        showResult(cfg.title, r.data);
        loadReport();
        return;
      }
      if (r.status === 401) handleAuth(r);
      else if (r.status === 503) disabled();
      else if (r.status === 403) message("Protecția CSRF a respins cererea. Reîncearcă.", true);
      else if (r.status === 422) message(detailOf(r.data) || "Confirmarea lipsește sau e greșită.", true);
      else if (r.status === 429) message("Prea multe încercări. Reîncearcă peste un minut.", true);
      else message(detailOf(r.data) || "Eroare (" + r.status + ").", true);
    }).catch(function (e) {
      btn.disabled = false;
      if (e && e.status) handleAuth(e);
      else message("Serverul nu răspunde.", true);
    });
  }

  function showResult(title, data) {
    var box = $("admin-result");
    if (!box) return;
    clear(box);
    box.hidden = false;
    box.appendChild(el("h3", "admin-h3", title + " · rezultat"));
    var dl = el("dl", "admin-stats");
    kv(dl, data, "");
    box.appendChild(dl);
  }

  // afișează orice răspuns: cheile și valorile din API, fără să inventeze alte câmpuri
  function kv(dl, obj, prefix) {
    Object.keys(obj).forEach(function (k) {
      var v = obj[k];
      var label = prefix + k;
      if (v !== null && typeof v === "object" && !Array.isArray(v)) kv(dl, v, label + " · ");
      else if (Array.isArray(v)) stat(dl, label, v.length + " elemente");
      else stat(dl, label, txt(v));
    });
  }

  // ---- live server card -------------------------------------------------------------

  function serverCard() {
    var c = card("admin-server", "Server (live)");
    c.appendChild(el("p", "admin-text",
      "Se reîmprospătează la 10 secunde cât pagina e deschisă și ești autentificat. " +
      "Valorile care lipsesc apar ca „—”."));
    var bar = el("div", "admin-actions");
    var b = el("button", "btn btn-ghost btn-sm", "Reîmprospătează");
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
    c.appendChild(el("h3", "admin-h3", "Servicii"));
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
      if (m) m.textContent = "Eroare la citirea stării serverului (" + r.status + ").";
    }).catch(function () {
      serverBusy = false;
      var m = $("admin-server-meta");
      if (m) m.textContent = "Serverul nu răspunde.";
    });
  }

  function renderServer(s) {
    var dl = $("admin-server-stats");
    if (!dl) return;
    var load = s.load || {}, mem = s.memory || {}, disk = s.disk || {};
    var proc = s.process || {}, wd = s.watchdog || {};
    clear(dl);

    var l1 = load["1m"], cores = load.cores;
    stat(dl, "Încărcare 1 / 5 / 15 min",
      num(l1, 2) + " / " + num(load["5m"], 2) + " / " + num(load["15m"], 2) +
      " · nuclee: " + txt(cores),
      l1 != null && cores != null && l1 > cores ? "is-bad" : "");

    var used = mem.total_mb != null && mem.available_mb != null ? mem.total_mb - mem.available_mb : null;
    stat(dl, "RAM folosită",
      used == null ? "—" : mb(used) + " din " + mb(mem.total_mb),
      used != null && mem.total_mb ? (used / mem.total_mb > 0.9 ? "is-bad" : "") : "");
    stat(dl, "Swap folosit", mb(mem.swap_used_mb) + " din " + mb(mem.swap_total_mb));
    stat(dl, "Disc liber", gb(disk.free_gb) + " din " + gb(disk.total_gb));
    stat(dl, "Uptime", uptime(s.uptime_s));
    stat(dl, "Proces (RSS)", mb(proc.rss_mb));
    stat(dl, "Eșecuri watchdog", txt(wd.failures), wd.failures ? "is-bad" : "");
    stat(dl, "Ultimul restart watchdog", when(wd.last_restart));

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
    if (meta) meta.textContent = "Actualizat la " + when(s.generated_at) + ".";
  }

  // ---- proposed OCR13 marks (static text, no API) -----------------------------------

  function marksCard() {
    var c = card("admin-marks", "Marcaje propuse (OCR13)");
    c.appendChild(el("p", "admin-text",
      "60 de evenimente propuse în analiza pe istoricul vechi (mark_apply.sql, ID-uri de " +
      "evenimente din istoricul de pe Azure). Nu se aplică pe baza curentă, pentru că baza " +
      "de acasă are doar date de la 31.10. Nu există buton de aplicare."));
    return c;
  }

  // ---- timer: only while #admin is shown, the page is visible and the session is valid ---

  function stopTimer() {
    if (serverTimer) { clearInterval(serverTimer); serverTimer = null; }
  }

  function syncTimer() {
    var on = loggedIn && location.hash === "#admin" && !document.hidden && !!$("admin-server-stats");
    if (!on) { stopTimer(); return; }
    if (!serverTimer) {
      serverTimer = setInterval(loadServer, REFRESH_MS);
      loadServer();
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
    }).catch(function () { message("Serverul nu răspunde.", true); });
  }

  window.addEventListener("hashchange", syncTimer);
  document.addEventListener("visibilitychange", syncTimer);

  window.TabelaApp = window.TabelaApp || {};
  window.TabelaApp.views = window.TabelaApp.views || {};
  window.TabelaApp.views.admin = { show: show };
})();
