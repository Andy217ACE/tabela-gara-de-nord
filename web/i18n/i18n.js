// © 2026 Andy217Ace
// i18n: limbi ro (implicit) și en. Ordine: ?lang= → localStorage "tabela-lang" → ro.
(function () {
  "use strict";
  var LANGS = ["ro", "en"], KEY = "tabela-lang";
  var dicts = { ro: {}, en: {} };

  function norm(v) { return LANGS.indexOf(v) >= 0 ? v : null; }

  function resolve() {
    var fromUrl = null, fromStore = null;
    try { fromUrl = norm(new URLSearchParams(location.search).get("lang")); } catch (e) { /* ignore */ }
    if (fromUrl) {
      try { localStorage.setItem(KEY, fromUrl); } catch (e) { /* ignore */ }
      return fromUrl;
    }
    try { fromStore = norm(localStorage.getItem(KEY)); } catch (e) { /* ignore */ }
    return fromStore || "ro";
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

  window.I18N = {
    t: t,
    lang: function () { return active; },
    ready: Promise.all(jobs).then(function () { /* void */ })
  };
})();
