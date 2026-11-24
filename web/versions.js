// © 2026 Andy217Ace
// Tabela Gara de Nord — the app version in the footer + the "Versions" screen (#versiuni).
// Data: GET /api/changelog -> {version, entries:[{version, date, groups:[{title, items}]}]}.
// DOM built with createElement/textContent only (CSP: no inline styles/scripts).
"use strict";

(function () {
  var App = window.TabelaApp = window.TabelaApp || {};
  App.views = App.views || {};
  var $ = function (id) { return document.getElementById(id); };
  var loaded = null;  // Promise of the changelog JSON (fetched once per page load)
  function T(k, p) { return window.I18N.t(k, p); }

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

  // "**text**" from the CHANGELOG -> <strong> (only textContent, no HTML from data)
  function item(s) {
    var li = el("li");
    plain(s).split("**").forEach(function (part, i) {
      if (!part) return;
      li.appendChild(i % 2 ? el("strong", null, part) : document.createTextNode(part));
    });
    return li;
  }

  function setFooter(data) {
    var a = $("app-version");
    if (a && data && typeof data.version === "string" && data.version) a.textContent = data.version;
  }

  var GROUP_KIND = { "nou": "new", "reparat": "fix", "tehnic": "tech", "modificat": "fix" };
  // group titles in the CHANGELOG are Romanian words; known ones get a translated badge, others stay as written
  function groupTitle(t) {
    var k = String(t).toLowerCase();
    return GROUP_KIND[k] ? T("versions.group." + k) : plain(t);
  }

  var OPEN_FIRST = 1;   // only the latest version starts open; older ones are one click away
  var dateFmts = {};

  function niceDate(iso) {
    var d = new Date(iso + "T12:00:00Z");
    if (isNaN(d.getTime())) return String(iso || "");
    var loc = window.I18N.lang() === "en" ? "en-GB" : "ro-RO";
    if (!dateFmts[loc]) dateFmts[loc] = new Intl.DateTimeFormat(loc, { timeZone: "UTC", day: "numeric", month: "long", year: "numeric" });
    return dateFmts[loc].format(d);
  }

  function entryBody(e) {
    var body = el("div", "v-body");
    (e.groups || []).forEach(function (g) {
      if (g.title) {
        var gh = el("h3", "v-group");
        var kind = GROUP_KIND[String(g.title).toLowerCase()] || "";
        gh.append(el("span", "v-badge" + (kind ? " v-badge-" + kind : ""), groupTitle(g.title)));
        gh.append(el("span", "v-count", (g.items || []).length + " " + T((g.items || []).length === 1 ? "versions.point" : "versions.points")));
        body.appendChild(gh);
      }
      var ul = el("ul", "v-items");
      (g.items || []).forEach(function (it) { ul.appendChild(item(it)); });
      body.appendChild(ul);
    });
    return body;
  }

  function render(data) {
    var box = $("v-list");
    var entries = (data && Array.isArray(data.entries)) ? data.entries : [];
    box.replaceChildren();
    $("v-current").textContent = data && data.version ? T("versions.current", { v: data.version }) : "";
    if (!entries.length) {
      box.appendChild(el("p", "empty", T("versions.unavailable")));
      return;
    }
    var U = App.ui2;
    if (U) {
      var hero = U.hero([
        { label: T("versions.heroCurrent"), text: plain(entries[0].version), cls: "ui-stat-name", sub: niceDate(entries[0].date) },
        { label: T("versions.heroCount"), value: entries.length, sub: T("versions.since", { v: plain(entries[entries.length - 1].version) }) },
        { label: T("versions.heroChanges"), value: (entries[0].groups || []).reduce(function (a, g) { return a + (g.items || []).length; }, 0),
          sub: (entries[0].groups || []).map(function (g) { return g.title ? groupTitle(g.title) : ""; }).filter(Boolean).join(" · ") }]);
      hero.classList.add("v-hero");
      box.appendChild(hero);
    }
    var tl = el("div", "v-timeline v-list-inner");
    entries.forEach(function (e, i) {
      var art = el("article", "v-entry" + (i === 0 ? " is-current" : ""));
      var h = el("h2", "v-title", plain(e.version));
      if (i === 0) h.appendChild(el("span", "v-tag", T("versions.tag")));
      var t = el("time", "v-date", e.date);
      t.dateTime = e.date;
      h.appendChild(document.createTextNode(" "));
      h.appendChild(t);
      art.appendChild(h);
      var body = entryBody(e);
      if (i < OPEN_FIRST) {
        art.appendChild(body);
      } else {
        body.id = "v-body-" + i;
        body.hidden = true;
        var n = (e.groups || []).reduce(function (a, g) { return a + (g.items || []).length; }, 0);
        var btn = el("button", "btn btn-ghost btn-sm v-more", T("versions.showAll", { n: n }));
        btn.type = "button";
        btn.setAttribute("aria-expanded", "false");
        btn.setAttribute("aria-controls", body.id);
        btn.addEventListener("click", function () {
          var open = body.hidden;
          body.hidden = !open;
          btn.setAttribute("aria-expanded", open ? "true" : "false");
          btn.textContent = open ? T("versions.hide") : T("versions.showAll", { n: n });
        });
        art.appendChild(btn);
        art.appendChild(body);
      }
      tl.appendChild(art);
    });
    box.appendChild(tl);
    if (U) U.reveal(box);
  }

  App.views.versiuni = {
    show: function () {
      var err = $("v-error");
      err.hidden = true;
      load().then(function (d) { setFooter(d); render(d); }, function () {
        err.textContent = T("versions.error");
        err.hidden = false;
      });
    }
  };

  // language switch: redraw the list (the changelog JSON is already loaded) if it is on screen
  document.addEventListener("i18n:change", function () {
    var box = $("v-list");
    if (box && box.childNodes.length && loaded) loaded.then(render, function () { /* keep what is shown */ });
  });

  function init() { load().then(setFooter, function () { /* footer keeps its fallback text */ }); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
