// © 2026 Andy217Ace
// i18n: limbi ro (implicit) și en. Ordine: ?lang= → localStorage "tabela-lang" → ro.
(function () {
  "use strict";
  var LANGS = ["ro", "en"], KEY = "tabela-lang";
  var dicts = { ro: {}, en: {} };

  function norm(v) { return LANGS.indexOf(v) >= 0 ? v : null; }

  function resolve() {
    var raw = null;
    try { raw = new URLSearchParams(location.search).get("lang"); } catch (e) { /* ignore */ }
    // Parametrul prezent dar invalid (inclusiv gol) merge direct pe ro, fără fallback la stocare.
    if (raw !== null) return norm(raw) || "ro";
    try { return norm(localStorage.getItem(KEY)) || "ro"; } catch (e) { return "ro"; }
  }

  var active = resolve();

  function fetchDict(path) {
    return fetch(path, { cache: "no-cache" })
      .then(function (r) { return r.ok ? r.json() : {}; })
      .catch(function () { return {}; })
      .then(function (d) { return d || {}; });
  }

  // Extra dictionaries (e.g. "admin" → /i18n/ro.admin.json): texts of the private pages, kept out of
  // ro.json (precached for everyone). Once asked for, load() fetches them with each language too.
  var extras = [];
  function load(code) {
    var files = ["/i18n/" + code + ".json"].concat(extras.map(function (n) { return "/i18n/" + code + "." + n + ".json"; }));
    return Promise.all(files.map(fetchDict)).then(function (ds) { dicts[code] = Object.assign.apply(null, [{}].concat(ds)); });
  }

  var extraP = {};
  function loadExtra(name) {
    if (!extraP[name]) {
      extraP[name] = window.I18N.ready.then(function () {
        var code = active;
        return fetchDict("/i18n/" + code + "." + name + ".json").then(function (d) {
          if (!Object.keys(d).length) { delete extraP[name]; return false; }   // failed (offline, never cached): retried next time
          if (extras.indexOf(name) < 0) extras.push(name);
          Object.assign(dicts[code], d);
          return true;
        });
      });
    }
    return extraP[name];
  }

  function fill(s, params) {
    if (!params) return s;
    return s.replace(/\{(\w+)\}/g, function (m, k) {
      return Object.prototype.hasOwnProperty.call(params, k) ? String(params[k]) : m;
    });
  }

  function t(key, params) {
    var s = dicts[active] && dicts[active][key];
    if (typeof s !== "string") s = dicts.ro[key];
    if (typeof s !== "string") s = key;
    return fill(s, params);
  }

  // Notă: "i18n:change" NU se emite la încărcarea inițială (limba activă e deja cunoscută; paginile
  // aplică I18N.ready + applyDom singure) — doar setLang() o emite.
  var jobs = [load("ro")];
  if (active === "en") jobs.push(load("en"));

  // Numele stațiilor: cheia stocată (BRASOV) → nume afișat (Brașov), același în ro și en.
  var stations = {};
  // at most ~2.5 s of waiting: a hung request must not keep the whole app from starting (names fall back to Title Case)
  jobs.push(Promise.race([
    fetch("/api/station-names").then(function (r) { return r.ok ? r.json() : {}; }),
    new Promise(function (resolve) { setTimeout(function () { resolve({}); }, 2500); })
  ]).catch(function () { return {}; }).then(function (d) { stations = d || {}; }));

  // Singurul helper de afișare a unei stații; cheie necunoscută (citire greșită) → Title Case.
  function station(name) {
    var s = String(name || "");
    if (Object.prototype.hasOwnProperty.call(stations, s)) return stations[s];
    return s.toLowerCase().replace(/(^|[\s\-.])(\S)/g, function (m, a, b) { return a + b.toUpperCase(); });
  }

  // Completează data-i18n="cheie" (textContent) și data-i18n-attr="atribut:cheie;atribut2:cheie2".
  function applyDom(root) {
    var scope = root || document, i, n, list, parts, p, c;
    if (scope.nodeType === 1 && scope.hasAttribute("data-i18n")) scope.textContent = t(scope.getAttribute("data-i18n"));
    list = scope.querySelectorAll("[data-i18n]");
    for (i = 0; i < list.length; i++) list[i].textContent = t(list[i].getAttribute("data-i18n"));
    list = scope.querySelectorAll("[data-i18n-attr]");
    for (i = 0; i < list.length; i++) {
      parts = list[i].getAttribute("data-i18n-attr").split(";");
      for (n = 0; n < parts.length; n++) {
        c = parts[n].indexOf(":");
        if (c > 0) list[i].setAttribute(parts[n].slice(0, c).trim(), t(parts[n].slice(c + 1).trim()));
      }
    }
  }

  function setLang(code) {
    var c = norm(code) || "ro";
    active = c;
    try { localStorage.setItem(KEY, c); } catch (e) { /* stocare indisponibilă: limba rămâne pe sesiune */ }
    var p = c === "ro" && !extras.length ? Promise.resolve() : load(c);
    window.I18N.ready = p.then(function () {
      try { document.dispatchEvent(new CustomEvent("i18n:change", { detail: { lang: c } })); } catch (e) { /* ignore */ }
    });
    return window.I18N.ready;
  }

  window.I18N = {
    t: t,
    station: station,
    applyDom: applyDom,
    setLang: setLang,
    loadExtra: loadExtra,   // Promise<boolean>: true once the extra dictionary is merged, false if it could not be fetched (retried on the next call)
    lang: function () { return active; },
    ready: Promise.all(jobs).then(function () { /* void */ })
  };
})();
