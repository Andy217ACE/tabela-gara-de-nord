// © 2026 Andy217Ace
// Tabela Gara de Nord — ceasul din antet + widgetul meteo de lângă ceas.
// - Ceas digital HH:MM (Europe/Bucharest) în antet, cu data pe ecrane late; bifează la 1 s.
// - Widget meteo în fiecare element [data-weather-slot] (antet + bara de titlu a Panoului):
//   pictogramă, temperatură, „se simte", vânt; la apăsare/hover un popover cu detalii.
// - Datele vin DOAR de la serverul nostru (GET /api/weather; CSP connect-src 'self');
//   serverul le ia de la Open-Meteo. Sunt valori de MODEL („Condiții curente (model
//   Open-Meteo)"), nu o stație meteo. Lipsă ≠ 0: o valoare null se afișează „—".
// - Date vechi (> stale_after_s) sau reîmprospătare eșuată: starea gri „date vechi (acum X
//   min)", păstrând ultima valoare; niciodată prezentate drept curente.
// DOM doar cu createElement/createElementNS/textContent; rotirea săgeții de vânt prin
// atributul SVG transform (fără stiluri inline — CSP).
"use strict";

(function () {
  var TZ = "Europe/Bucharest";
  var SVG_NS = "http://www.w3.org/2000/svg";
  var DEFAULTS = { enabled: true, stale_after_s: 2700, refresh_s: 300 };
  var ATTR = { source: "Open-Meteo.com", url: "https://open-meteo.com/", license: "CC BY 4.0" };
  var LABEL = "Condiții curente (model Open-Meteo)";
  var DIR_NAMES = { N: "nord", NE: "nord-est", E: "est", SE: "sud-est", S: "sud",
                    SV: "sud-vest", V: "vest", NV: "nord-vest" };

  // pictograme 24×24, linie (culoarea vine din CSS); norul de sus lasă loc precipitațiilor
  var CLOUD = "M7 18h10a4 4 0 0 0 .5-7.97A6 6 0 0 0 6.1 11.1 3.5 3.5 0 0 0 7 18z";
  var CLOUD_UP = "M7.5 14h9a3.3 3.3 0 0 0 .4-6.57A5 5 0 0 0 7 8.3 2.9 2.9 0 0 0 7.5 14z";
  var ICONS = {
    sun: { c: [[12, 12, 4]], p: ["M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6"] },
    moon: { p: ["M19.5 14.5A7.5 7.5 0 1 1 9.5 4.5a6 6 0 0 0 10 10z"] },
    partly: { c: [[8, 8, 3]], p: ["M8 2.2v1.3M2.2 8h1.3M3.9 3.9l.9.9M12.1 3.9l-.9.9", "M9 20h8.5a3.5 3.5 0 0 0 .4-6.97A5 5 0 0 0 8.3 13.4 3.3 3.3 0 0 0 9 20z"] },
    "partly-night": { p: ["M11.5 7.6A4.6 4.6 0 1 1 5.4 2.6a3.7 3.7 0 0 0 6.1 5z", "M9 20h8.5a3.5 3.5 0 0 0 .4-6.97A5 5 0 0 0 8.3 13.4 3.3 3.3 0 0 0 9 20z"] },
    cloud: { p: [CLOUD] },
    fog: { p: ["M7 11h10a3.5 3.5 0 0 0 .3-6.98A5 5 0 0 0 6.9 5.2 3 3 0 0 0 7 11z", "M4 14.5h16M6 18h12M8 21.5h8"] },
    drizzle: { p: [CLOUD_UP, "M9 17.5v.1M12 19.5v.1M15 17.5v.1M10.5 21.5v.1M13.5 21.5v.1"] },
    rain: { p: [CLOUD_UP, "M9 16.5l-1 3.5M12.5 16.5l-1 3.5M16 16.5l-1 3.5"] },
    freezing: { p: [CLOUD_UP, "M9 16.5l-1 3.5M16 16.5l-1 3.5", "M12.3 17v4.5M10.4 18.1l3.8 2.3M14.2 18.1l-3.8 2.3"] },
    snow: { p: [CLOUD_UP, "M8.5 16.5v4M6.8 17.5l3.4 2M10.2 17.5l-3.4 2", "M15.5 16.5v4M13.8 17.5l3.4 2M17.2 17.5l-3.4 2"] },
    showers: { c: [[17.5, 6, 2.2]], p: ["M17.5 1.8v.9M21.7 6h-.9M20.5 3l-.6.6", "M5.5 14h8.5a3.2 3.2 0 0 0 .3-6.39A4.6 4.6 0 0 0 5.2 8.5 2.8 2.8 0 0 0 5.5 14z", "M7 16.5l-1 3.5M10.5 16.5l-1 3.5M14 16.5l-1 3.5"] },
    thunder: { p: [CLOUD_UP, "M12.5 14.5l-2.5 4h3.5l-2 4"] },
    unknown: { p: [CLOUD, "M10.6 11.4a1.6 1.6 0 1 1 2.2 1.5c-.5.2-.8.6-.8 1.1M12 16.3v.1"] }
  };

  var S = { cfg: DEFAULTS, data: null, receivedAt: 0, failed: false, loading: true,
            widgets: [], timer: null, inflight: null, seq: 0 };

  var fmtClock = new Intl.DateTimeFormat("ro-RO", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false });
  var fmtDate = new Intl.DateTimeFormat("ro-RO", { timeZone: TZ, weekday: "short", day: "numeric", month: "short" });

  // ---- helpers ---------------------------------------------------------------------

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function svg(kind, cls) {
    var def = ICONS[kind] || ICONS.unknown;
    var s = document.createElementNS(SVG_NS, "svg");
    s.setAttribute("viewBox", "0 0 24 24");
    s.setAttribute("aria-hidden", "true");
    s.setAttribute("focusable", "false");
    s.setAttribute("class", cls + " wx-i-" + (ICONS[kind] ? kind : "unknown"));
    (def.c || []).forEach(function (c) {
      var ci = document.createElementNS(SVG_NS, "circle");
      ci.setAttribute("cx", c[0]); ci.setAttribute("cy", c[1]); ci.setAttribute("r", c[2]);
      s.appendChild(ci);
    });
    (def.p || []).forEach(function (d) {
      var p = document.createElementNS(SVG_NS, "path");
      p.setAttribute("d", d);
      s.appendChild(p);
    });
    return s;
  }

  // săgeata arată încotro bate vântul (dinspre direcția citită + 180°)
  function arrow(deg) {
    var s = document.createElementNS(SVG_NS, "svg");
    s.setAttribute("viewBox", "0 0 24 24");
    s.setAttribute("aria-hidden", "true");
    s.setAttribute("focusable", "false");
    s.setAttribute("class", "wx-arrow");
    var g = document.createElementNS(SVG_NS, "g");
    g.setAttribute("transform", "rotate(" + ((Number(deg) + 180) % 360) + " 12 12)");
    var p = document.createElementNS(SVG_NS, "path");
    p.setAttribute("d", "M12 20V4M6.5 9.5 12 4l5.5 5.5");
    g.appendChild(p);
    s.appendChild(g);
    return s;
  }

  function isNum(v) { return typeof v === "number" && isFinite(v); }

  function round(v) {
    var r = Math.round(v);
    return r === 0 ? 0 : r; // fără „-0"
  }

  function deg(v) { return isNum(v) ? round(v) + "°" : "—"; }

  function dec1(v) { return isNum(v) ? v.toFixed(1).replace(".", ",") : null; }

  // 1 grad, 2–19 grade, 20+ „de grade" (0 grade)
  function grade(n) {
    var a = Math.abs(n) % 100;
    if (Math.abs(n) === 1) return n + " grad";
    if (a === 0 && n !== 0) return n + " de grade";
    return a < 20 ? n + " grade" : n + " de grade";
  }

  function windText(d) {
    if (!isNum(d.wind_speed_kmh)) return "—";
    return round(d.wind_speed_kmh) + " km/h" + (d.wind_direction_ro ? " " + d.wind_direction_ro : "");
  }

  function ageS() {
    if (!S.data || !isNum(S.data.age_s)) return null;
    return S.data.age_s + (Date.now() - S.receivedAt) / 1000;
  }

  function agoText(s) {
    var m = Math.max(0, Math.round(s / 60));
    if (m < 1) return "acum mai puțin de 1 min";
    if (m < 60) return "acum " + m + " min";
    var h = Math.floor(m / 60);
    return "acum " + h + " h" + (m % 60 ? " " + (m % 60) + " min" : "");
  }

  function state() {
    if (!S.data) return S.loading ? "loading" : "unavailable";
    if (!S.data.available) return "unavailable";
    var a = ageS();
    if (S.failed || S.data.stale || a == null || a > S.cfg.stale_after_s) return "stale";
    return "ok";
  }

  function summary(d, st) {
    if (st === "loading") return "Vremea în București: se încarcă";
    if (st === "unavailable") return "Vremea în București: meteo indisponibilă";
    var parts = ["Vremea în București: " + (isNum(d.temperature_c) ? grade(round(d.temperature_c)) : "temperatură necunoscută")];
    if (d.condition_ro) parts.push(d.condition_ro.toLowerCase());
    if (isNum(d.wind_speed_kmh)) {
      parts.push("vânt " + round(d.wind_speed_kmh) + " km/h" +
                 (DIR_NAMES[d.wind_direction_ro] ? " dinspre " + DIR_NAMES[d.wind_direction_ro] : ""));
    }
    var s = parts.join(", ");
    if (st === "stale") s += ". Date vechi, " + agoText(ageS() || 0);
    return s + ". Apasă pentru detalii.";
  }

  // ---- widget ----------------------------------------------------------------------

  var uid = 0;

  function makeWidget(slot) {
    var w = { slot: slot };
    var id = "wx-pop-" + (++uid);
    w.root = el("div", "wx");
    w.root.dataset.state = "loading";
    w.root.dataset.place = slot.getAttribute("data-weather-slot") || "";
    w.btn = el("button", "wx-btn");
    w.btn.type = "button";
    w.btn.setAttribute("aria-expanded", "false");
    w.btn.setAttribute("aria-controls", id);
    w.pop = el("div", "wx-pop");
    w.pop.id = id;
    w.pop.setAttribute("role", "region");
    w.pop.setAttribute("aria-label", "Detalii meteo");
    w.root.append(w.btn, w.pop);
    slot.textContent = "";
    slot.appendChild(w.root);

    w.btn.addEventListener("click", function (e) {
      e.stopPropagation();
      setOpen(w, !w.open);
    });
    w.root.addEventListener("mouseenter", function () { place(w); });
    w.root.addEventListener("focusout", function (e) {
      if (w.open && e.relatedTarget && !w.root.contains(e.relatedTarget)) setOpen(w, false);
    });
    return w;
  }

  function place(w) {
    var r = w.root.getBoundingClientRect();
    var vw = window.innerWidth || document.documentElement.clientWidth;
    w.root.classList.toggle("wx-left", r.left + r.width / 2 < vw / 2);
  }

  function setOpen(w, open) {
    if (open) {
      S.widgets.forEach(function (o) { if (o !== w) setOpen(o, false); });
      place(w);
    }
    w.open = open;
    w.root.classList.toggle("is-open", open);
    w.btn.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function row(dl, label, value) {
    dl.append(el("dt", null, label), el("dd", null, value));
  }

  function credit() {
    var p = el("p", "wx-pop-src");
    var a = el("a", null, ATTR.source);
    a.href = ATTR.url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    p.append("Meteo: ", a, " · " + ATTR.license);
    return p;
  }

  function renderWidget(w) {
    var st = state();
    var d = S.data || {};
    w.root.dataset.state = st;
    w.btn.setAttribute("aria-label", summary(d, st));
    w.btn.textContent = "";
    w.pop.textContent = "";

    if (st === "loading") {
      w.btn.append(el("span", "wx-sk"), el("span", "sr-only", "Se încarcă vremea"));
      w.btn.disabled = true;
      w.pop.appendChild(credit());
      return;
    }
    w.btn.disabled = false;
    if (st === "unavailable") {
      w.btn.appendChild(el("span", "wx-na", "meteo indisponibilă"));
      w.pop.append(el("p", "wx-pop-title", LABEL),
                   el("p", "wx-pop-note", S.failed && !S.data
                     ? "Nu am putut încărca datele meteo. Reîncercăm automat."
                     : "Încă nu există date meteo. Serverul le actualizează la 15 minute."),
                   credit());
      return;
    }

    var ico = el("span", "wx-ico");
    ico.appendChild(svg(d.icon, "wx-svg"));
    var temp = el("span", "wx-temp", deg(d.temperature_c));
    var sub = el("span", "wx-sub");
    if (isNum(d.apparent_temperature_c)) sub.appendChild(el("span", "wx-feels", "se simte " + deg(d.apparent_temperature_c)));
    var wind = el("span", "wx-wind");
    if (isNum(d.wind_speed_kmh) && isNum(d.wind_direction_deg)) wind.appendChild(arrow(d.wind_direction_deg));
    wind.appendChild(el("span", "wx-wind-t", windText(d)));
    sub.appendChild(wind);
    w.btn.append(ico, temp, sub);
    if (st === "stale") w.btn.appendChild(el("span", "wx-old", "date vechi (" + agoText(ageS() || 0) + ")"));

    // popover
    var head = el("p", "wx-pop-title", LABEL);
    var cond = el("p", "wx-pop-cond", (d.condition_ro || "Condiții necunoscute") + " · București");
    var dl = el("dl", "wx-dl");
    row(dl, "Temperatura", deg(d.temperature_c) + (isNum(d.temperature_c) ? "C" : ""));
    row(dl, "Se simte ca", deg(d.apparent_temperature_c) + (isNum(d.apparent_temperature_c) ? "C" : ""));
    row(dl, "Vânt", isNum(d.wind_speed_kmh)
      ? round(d.wind_speed_kmh) + " km/h" + (DIR_NAMES[d.wind_direction_ro]
        ? " dinspre " + DIR_NAMES[d.wind_direction_ro] + " (" + d.wind_direction_ro + ")" : "")
      : "—");
    var pr = dec1(d.precipitation_mm);
    row(dl, "Precipitații", pr == null ? "—" : pr + " mm");
    row(dl, "Ora observației", (d.observed_local || "—") + " (ora României)");
    var a = ageS();
    row(dl, "Vechime", a == null ? "—" : agoText(a));
    w.pop.append(head, cond, dl);
    if (st === "stale") {
      w.pop.appendChild(el("p", "wx-pop-warn", S.failed
        ? "Nu am putut reîmprospăta datele — afișăm ultima valoare primită, nu condițiile actuale."
        : "Datele sunt vechi — nu reprezintă condițiile actuale."));
    }
    w.pop.append(el("p", "wx-pop-note", "Valoare de model pentru zona Bucureștiului, nu măsurătoarea unei stații meteo."),
                 credit());
  }

  function renderAll() { S.widgets.forEach(renderWidget); }

  // ---- data ------------------------------------------------------------------------

  function load() {
    if (S.inflight) S.inflight.abort();
    var ctrl = typeof AbortController === "function" ? new AbortController() : null;
    S.inflight = ctrl;
    var to = ctrl ? setTimeout(function () { ctrl.abort(); }, 10000) : null;
    return fetch("/api/weather", { cache: "no-store", headers: { Accept: "application/json" },
                                   signal: ctrl ? ctrl.signal : undefined })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (j) {
        if (!j || typeof j !== "object") throw new Error("bad body");
        S.data = j;
        S.receivedAt = Date.now();
        S.failed = false;
      })
      .catch(function () {
        if (S.inflight !== ctrl && ctrl) return; // înlocuită de o cerere nouă
        S.failed = true;
      })
      .then(function () {
        if (to) clearTimeout(to);
        if (S.inflight === ctrl) S.inflight = null;
        S.loading = false;
        renderAll();
      });
  }

  function schedule() {
    clearInterval(S.timer);
    S.timer = setInterval(load, S.cfg.refresh_s * 1000);
  }

  function setEnabled(on) {
    document.querySelectorAll("[data-weather-slot], .wx-credit, .footer-meteo").forEach(function (n) {
      n.hidden = !on;
    });
  }

  // ---- header clock ----------------------------------------------------------------

  function tickClock() {
    var c = document.getElementById("hdr-clock");
    if (!c) return;
    var now = new Date();
    var t = c.querySelector(".hdr-clock-time");
    var d = c.querySelector(".hdr-clock-date");
    var tv = fmtClock.format(now);
    if (t && t.textContent !== tv) t.textContent = tv;
    var dv = fmtDate.format(now);
    if (d && d.textContent !== dv) d.textContent = dv;
    c.setAttribute("datetime", now.toISOString());
  }

  // ---- boot ------------------------------------------------------------------------

  function init() {
    tickClock();
    setInterval(tickClock, 1000);

    var slots = document.querySelectorAll("[data-weather-slot]");
    S.widgets = Array.prototype.map.call(slots, makeWidget);
    renderAll();
    document.addEventListener("click", function (e) {
      S.widgets.forEach(function (w) { if (w.open && !w.root.contains(e.target)) setOpen(w, false); });
    });
    // Esc închide popover-ul și când focusul nu e în widget (ex. deschis prin hover/atingere);
    // în faza de captură, ca Esc să nu iasă în același timp din ecranul complet al Panoului
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      var open = S.widgets.filter(function (w) { return w.open; });
      if (!open.length) return;
      e.stopPropagation();
      open.forEach(function (w) {
        var had = w.root.contains(document.activeElement);
        setOpen(w, false);
        if (had) w.btn.focus();
      });
    }, true);

    var cfgP = window.TabelaApp && typeof window.TabelaApp.config === "function"
      ? window.TabelaApp.config() : Promise.resolve(null);
    cfgP.then(function (c) {
      var x = c && c.weather;
      if (x && typeof x === "object") {
        S.cfg = {
          enabled: x.enabled !== false,
          stale_after_s: isNum(x.stale_after_s) && x.stale_after_s > 0 ? x.stale_after_s : DEFAULTS.stale_after_s,
          refresh_s: isNum(x.refresh_s) ? Math.min(3600, Math.max(60, x.refresh_s)) : DEFAULTS.refresh_s
        };
      }
    }).catch(function () { /* valorile implicite */ }).then(function () {
      setEnabled(S.cfg.enabled);
      if (!S.cfg.enabled) return;
      load();
      schedule();
      setInterval(function () { if (S.data) renderAll(); }, 30000); // „acum X min"
      document.addEventListener("visibilitychange", function () {
        if (document.visibilityState === "visible") load();
      });
    });
  }

  window.TabelaWeather = { refresh: load };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
