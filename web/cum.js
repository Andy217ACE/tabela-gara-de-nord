// © 2026 Andy217Ace
// Tabela Gara de Nord — „Cum funcționează?” (#cum): a static, plain-language explanation of
// where the data comes from and what it means. Text from i18n (cum.*); DOM via createElement/textContent (CSP).
"use strict";

(function () {
  var App = window.TabelaApp = window.TabelaApp || {};
  App.views = App.views || {};
  var $ = function (id) { return document.getElementById(id); };
  function T(k) { return window.I18N.t(k); }

  var REPO = "https://github.com/Andy217Ace/tabela-gara-de-nord";
  var STEPS = ["source", "ocr", "check", "store"];
  // [heading key suffix, paragraph count]; = CUM_SECTIONS in app/seo.py (server-rendered /cum)
  var SECTIONS = [["data", 3], ["delay", 3], ["history", 3], ["method", 6], ["limits", 3], ["privacy", 4], ["report", 2]];

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function link(href, text, external) {
    var a = el("a", null, text);
    a.href = href;
    if (external) { a.target = "_blank"; a.rel = "noopener noreferrer"; }
    return a;
  }

  // section created on demand (like #sistem), so the page needs no markup in index.html
  function build() {
    var sec = el("section", "view view-cum");
    sec.id = "view-cum";
    sec.setAttribute("aria-labelledby", "cum-heading");
    var head = el("div", "page-head");
    var h = el("h1", null, T("cum.title"));
    h.id = "cum-heading";
    head.appendChild(h);
    head.appendChild(el("p", "page-sub", T("cum.intro")));
    sec.appendChild(head);

    var flow = el("ol", "cum-flow");
    flow.setAttribute("aria-label", T("cum.flow.label"));
    STEPS.forEach(function (s) {
      var li = el("li", "cum-step");
      li.appendChild(el("strong", "cum-step-title", T("cum.flow." + s)));
      li.appendChild(el("span", "cum-step-text", T("cum.flow." + s + ".text")));
      flow.appendChild(li);
    });
    sec.appendChild(flow);

    SECTIONS.forEach(function (s) {
      var part = el("section", "cum-part");
      part.appendChild(el("h2", null, T("cum." + s[0] + ".title")));
      for (var i = 1; i <= s[1]; i++) part.appendChild(el("p", null, T("cum." + s[0] + ".p" + i)));
      if (s[0] === "method") {
        var mp = el("p");
        mp.appendChild(link(REPO + "/issues", T("cum.report.issues"), true));
        part.appendChild(mp);
      }
      if (s[0] === "limits") {
        var p = el("p");
        p.appendChild(link("#sistem", T("cum.limits.system")));
        p.appendChild(document.createTextNode(" · "));
        p.appendChild(link("https://cfr.ro", T("cum.limits.official"), true));
        part.appendChild(p);
      }
      if (s[0] === "report") {
        var ul = el("ul", "cum-links");
        var a = el("li");
        a.appendChild(link(REPO + "/issues", T("cum.report.issues"), true));
        var b = el("li");
        b.appendChild(link(REPO + "/security/advisories/new", T("cum.report.security"), true));
        ul.appendChild(a);
        ul.appendChild(b);
        part.appendChild(ul);
      }
      sec.appendChild(part);
    });
    $("main").appendChild(sec);
  }

  // language switch: drop the built section so it is rebuilt in the new language
  document.addEventListener("i18n:change", function () {
    var sec = $("view-cum");
    if (!sec) return;
    var wasShown = !sec.hidden;
    sec.remove();
    if (wasShown && document.body.getAttribute("data-route") === "cum") App.views.cum.show();
  });

  App.views.cum = {
    show: function () {
      if (!$("view-cum")) build();
      $("view-cum").hidden = false;  // created after the router hid the views: show it now
    }
  };
})();
