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

  function load(code) {
    return fetch("/i18n/" + code + ".json", { cache: "no-cache" })
      .then(function (r) { return r.ok ? r.json() : {}; })
      .catch(function () { return {}; })
      .then(function (d) { dicts[code] = d || {}; });
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

  var jobs = [load("ro")];
  if (active === "en") jobs.push(load("en"));

  function setLang(code) {
    var c = norm(code) || "ro";
    active = c;
    try { localStorage.setItem(KEY, c); } catch (e) { /* stocare indisponibilă: limba rămâne pe sesiune */ }
    var p = c === "ro" ? Promise.resolve() : load(c);
    window.I18N.ready = p.then(function () { /* void */ });
    return window.I18N.ready;
  }

  window.I18N = {
    t: t,
    setLang: setLang,
    lang: function () { return active; },
    ready: Promise.all(jobs).then(function () { /* void */ })
  };
})();
