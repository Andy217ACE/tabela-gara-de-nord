// © 2026 Andy217Ace
// Tabela Gara de Nord — versiunea aplicației în footer + ecranul „Versiuni” (#versiuni).
// Data: GET /api/changelog -> {version, entries:[{version, date, groups:[{title, items}]}]}.
// DOM built with createElement/textContent only (CSP: no inline styles/scripts).
"use strict";

(function () {
  var App = window.TabelaApp = window.TabelaApp || {};
  App.views = App.views || {};
  var $ = function (id) { return document.getElementById(id); };
  var loaded = null;  // Promise of the changelog JSON (fetched once per page load)

  function load() {
    if (!loaded) {
      loaded = fetch("/api/changelog", { headers: { Accept: "application/json" } })
        .then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        })
        .catch(function (e) { loaded = null; throw e; });
    }
    return loaded;
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function plain(s) {  // markdown code spans shown as plain text
    return String(s).replace(/`/g, "");
  }

  function setFooter(data) {
    var a = $("app-version");
    if (a && data && typeof data.version === "string" && data.version) a.textContent = data.version;
  }

  function render(data) {
    var box = $("v-list");
    var entries = (data && Array.isArray(data.entries)) ? data.entries : [];
    box.replaceChildren();
    $("v-current").textContent = data && data.version ? "Versiunea curentă: " + data.version : "";
    if (!entries.length) {
      box.appendChild(el("p", "empty", "Istoricul versiunilor nu este disponibil."));
      return;
    }
    entries.forEach(function (e) {
      var art = el("article", "v-entry");
      var h = el("h2", "v-title", plain(e.version));
      var t = el("time", "v-date", e.date);
      t.dateTime = e.date;
      h.appendChild(document.createTextNode(" "));
      h.appendChild(t);
      art.appendChild(h);
      (e.groups || []).forEach(function (g) {
        if (g.title) art.appendChild(el("h3", "v-group", plain(g.title)));
        var ul = el("ul", "v-items");
        (g.items || []).forEach(function (it) { ul.appendChild(el("li", null, plain(it))); });
        art.appendChild(ul);
      });
      box.appendChild(art);
    });
  }

  App.views.versiuni = {
    show: function () {
      var err = $("v-error");
      err.hidden = true;
      load().then(function (d) { setFooter(d); render(d); }, function () {
        err.textContent = "Nu am putut încărca istoricul versiunilor. Încearcă din nou mai târziu.";
        err.hidden = false;
      });
    }
  };

  function init() { load().then(setFooter, function () { /* footer keeps its fallback text */ }); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
