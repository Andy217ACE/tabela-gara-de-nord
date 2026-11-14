// © 2026 Andy217Ace
// Pagina offline: aplică limba salvată (i18n.js + dicționarul din cache), fără rețea.
(function () {
  "use strict";
  var I = window.I18N;
  if (!I) return;
  I.ready.then(function () {
    document.documentElement.lang = I.lang();
    document.title = I.t("offline.docTitle");
    I.applyDom(document);
  });
})();
