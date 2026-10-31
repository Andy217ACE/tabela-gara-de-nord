// © 2026 Andy217Ace
// Tabela Gara de Nord — pagina „Sistem” (#sistem): panoul e viu? când a fost ultima citire
// reușită, rata de rânduri necitite din ultima oră, spațiu pe disc, mărimea bazei.
// Date: GET /api/system (public); pentru admin și GET /api/admin/system (detalii, dacă
// sesiunea e de admin). Valoarea lipsă se afișează „necunoscut”, nu 0.
// DOM built with createElement/textContent only (CSP: no inline styles/scripts).
"use strict";

(function () {
  var App = window.TabelaApp = window.TabelaApp || {};
  App.views = App.views || {};
  var $ = function (id) { return document.getElementById(id); };
  var MIN_FRAMES = 10;  // mirrors app.system_status.OCR_MIN_FRAMES

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

  // age in seconds -> „acum 3 min” / „acum 45 s”; missing -> „necunoscut”
  function ago(s) {
    if (s == null) return "necunoscut";
    if (s < 60) return "acum " + s + " s";
    if (s < 3600) return "acum " + Math.round(s / 60) + " min";
    return "acum " + Math.round(s / 3600) + " h";
  }

  function uptime(s) {
    if (s == null) return "necunoscut";
    var d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    return (d ? d + " z " : "") + (h ? h + " h " : "") + m + " min";
  }

  function num(v, unit) {
    return v == null ? "necunoscut" : v + (unit ? " " + unit : "");
  }

  var STATE = {
    live: { text: "LIVE", cls: "sys-live" },
    date_vechi: { text: "Date vechi", cls: "sys-old" },
    necunoscut: { text: "Necunoscut", cls: "sys-unknown" }
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
    if (o.unread_rate_1h == null) return { value: "necunoscut", sub: "nu sunt cadre citite" };
    var pct = Math.round(o.unread_rate_1h * 1000) / 10;  // one decimal
    var sub = "din ultima oră (" + o.n + " cadre)";
    if (o.insufficient) sub += " · date insuficiente";
    return { value: pct + " % necitite", sub: sub };
  }

  function render(d) {
    var box = $("sys-body");
    box.replaceChildren();
    var st = STATE[d.stare] || STATE.necunoscut;
    var hero = el("div", "sys-hero");
    hero.appendChild(el("span", "sys-badge " + st.cls, st.text));
    hero.appendChild(el("p", "sys-hero-text",
      d.poller && d.poller.last_ok_age_s != null
        ? "Ultima citire reușită: " + ago(d.poller.last_ok_age_s)
        : "Nu există nicio citire reușită."));
    box.appendChild(hero);

    var list = el("ul", "sys-list");
    var o = ocrValue(d.ocr || {});
    list.appendChild(row("Versiune", num(d.version)));
    list.appendChild(row("Ultima citire reușită", d.poller ? ago(d.poller.last_ok_age_s) : "necunoscut"));
    list.appendChild(row("Rânduri necitite", o.value, o.sub));
    list.appendChild(row("Spațiu liber pe disc", num(d.disk && d.disk.free_gb, "GB")));
    list.appendChild(row("Mărimea bazei", num(d.db && d.db.size_mb, "MB"),
      d.db && d.db.wal_mb != null ? "jurnal WAL: " + d.db.wal_mb + " MB" : null));
    list.appendChild(row("Pornit de", uptime(d.uptime_s)));
    box.appendChild(list);
  }

  function renderAdmin(d) {
    var box = $("sys-admin");
    box.replaceChildren();
    box.appendChild(el("h2", "sys-admin-title", "Detalii (administrare)"));
    var list = el("ul", "sys-list");
    var p = d.poller || {};
    var err = p.last_error ? "cod " + p.last_error + (p.last_error_age_s != null ? ", " + ago(p.last_error_age_s) : "") : "nicio eroare";
    list.appendChild(row("Ultima eroare", err));
    var w = d.ocr_window || {};
    list.appendChild(row("Cadre în fereastră", num(w.frames)));
    list.appendChild(row("Cadre complete", num(w.full_frames)));
    list.appendChild(row("Cadre reluate", num(w.frames_retried)));
    list.appendChild(row("Durata cadrului (mediană)", num(w.duration_ms_p50, "ms")));
    list.appendChild(row("Spațiu total pe disc", num(d.disk && d.disk.total_gb, "GB")));
    box.appendChild(list);
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
    var h = el("h1", "sys-heading", "Sistem");
    h.id = "sistem-heading";
    sec.appendChild(h);
    sec.appendChild(el("p", "sys-intro", "Starea panoului și a serverului. Datele se reîmprospătează automat."));
    var err = el("p", "sys-error", "Nu am putut încărca starea sistemului. Încearcă din nou mai târziu.");
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

  App.views.sistem = {
    show: function () {
      ensureSection();
      $("view-sistem").hidden = false;  // created after the router hid the views: show it now
      var err = $("sys-error");
      err.hidden = true;
      fetchJson("/api/system").then(function (d) {
        render(d);
        loadAdmin();
      }, function () {
        err.hidden = false;
      });
    }
  };
})();
