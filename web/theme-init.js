// © 2026 Andy217Ace
// Tabela Gara de Nord — temă (Auto / Luminoasă / Întunecată).
// Încărcat SINCRON în <head>, înaintea foilor de stil: aplică tema salvată înainte de prima
// pictare (fără „flash"). Fișier extern, nu script inline (CSP: script-src 'self').
// Auto = fără atribut data-theme (urmează prefers-color-scheme); altfel
// <html data-theme="light|dark"> suprascrie media query-ul în style.css și panel.css.
"use strict";

(function () {
  var KEY = "tabela.theme";
  var ORDER = ["auto", "light", "dark"];
  var COLORS = { dark: "#0a0d12", light: "#f4f2ed" }; // = --bg din style.css
  var root = document.documentElement;

  function load() {
    try {
      var v = localStorage.getItem(KEY);
      return v === "light" || v === "dark" ? v : "auto";
    } catch (e) { return "auto"; }
  }

  function save(mode) {
    try {
      if (mode === "auto") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, mode);
    } catch (e) { /* fără stocare: tema ține până la reîncărcare */ }
  }

  // <meta name="theme-color">: două variante (media dark/light). La o temă forțată
  // ambele primesc culoarea temei; la Auto revin la valorile lor implicite.
  function syncMeta(mode) {
    var metas = document.querySelectorAll('meta[name="theme-color"]');
    for (var i = 0; i < metas.length; i++) {
      var m = metas[i];
      if (!m.dataset.auto) m.dataset.auto = m.getAttribute("content") || "";
      m.setAttribute("content", mode === "auto" ? m.dataset.auto : COLORS[mode]);
    }
  }

  function apply(mode) {
    if (mode === "light" || mode === "dark") root.dataset.theme = mode;
    else { mode = "auto"; delete root.dataset.theme; }
    syncMeta(mode);
    return mode;
  }

  var current = apply(load());

  window.TabelaTheme = {
    LABELS: { auto: "automată", light: "luminoasă", dark: "întunecată" },
    get: function () { return current; },
    set: function (mode) {
      current = apply(mode);
      save(current);
      try {
        document.dispatchEvent(new CustomEvent("tabela:theme", { detail: { mode: current } }));
      } catch (e) { /* browsere foarte vechi */ }
      return current;
    },
    next: function () {
      return this.set(ORDER[(ORDER.indexOf(current) + 1) % ORDER.length]);
    },
    // meta-urile sunt după acest script în <head>: resincronizăm când DOM-ul e gata
    syncMeta: function () { syncMeta(current); }
  };
  document.addEventListener("DOMContentLoaded", function () { syncMeta(current); });
})();

// „Site pentru desktop” pe telefon: pagina e așezată mult mai lată decât ecranul (~980 px pe
// un ecran de ~400 px) și afișată micșorată. Marcăm <html class="zoomed-out"> ca meniul de sus
// (style.css) să fie mai mare, lizibil și ușor de apăsat. Doar pe ecrane tactile (pointer
// coarse): pe desktop, zoom-ul browserului nu trebuie să schimbe meniul.
(function () {
  var root = document.documentElement;
  function check() {
    try {
      var coarse = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
      var sw = (window.screen && window.screen.width) || 0;
      var sh = (window.screen && window.screen.height) || 0;
      // iOS nu rotește screen.width: lățimea ecranului după orientare
      var land = window.matchMedia && window.matchMedia("(orientation: landscape)").matches;
      var dev = land ? Math.max(sw, sh) : Math.min(sw, sh);
      var on = !!coarse && dev > 0 && window.innerWidth >= dev * 1.6;
      root.classList.toggle("zoomed-out", on);
    } catch (e) { /* fără matchMedia/screen: meniul normal */ }
  }
  check();
  window.addEventListener("resize", check);
  window.addEventListener("orientationchange", check);
})();
