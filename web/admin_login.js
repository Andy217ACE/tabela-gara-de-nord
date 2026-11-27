// © 2026 Andy217Ace
// Shared admin login form (#admin, #ocr, #ocr2, #infofer: one session cookie). Loaded on demand
// through window.TabelaApp.adminLogin (app.js), never precached. With ADMIN_TOTP_SECRET set on the
// server, a 6-digit code field appears (GET /api/admin/session -> totp, or a "totp_required" answer).
// DOM only via createElement/textContent (CSP).
(function () {
  "use strict";

  function T(key) { return window.I18N ? window.I18N.t(key) : key; }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function api(path, opts) {
    opts = opts || {};
    opts.credentials = "same-origin";
    opts.cache = "no-store";
    return fetch(path, opts).then(function (r) {
      return r.json().catch(function () { return null; }).then(function (d) { return { status: r.status, data: d }; });
    });
  }

  // o: { keys: "admin" | "ocr" (i18n prefix), cls, id, message(text, isError), onOk(), onDisabled() }
  window.TabelaAdminLogin = function (o) {
    var p = o.keys;
    var form = el("form", o.cls + " panel");
    form.setAttribute("aria-label", T(p + ".login.aria"));
    var label = el("label", "field");
    label.appendChild(el("span", "field-label", T(p + ".login.key")));
    var input = el("input");
    input.type = "password";
    if (o.id) input.id = o.id;
    input.name = "token";
    input.autocomplete = "current-password";
    input.required = true;
    input.maxLength = 200;
    label.appendChild(input);
    form.appendChild(label);
    var codeLabel = el("label", "field");
    codeLabel.appendChild(el("span", "field-label", T("admin.login.code")));
    var code = el("input");
    if (o.id) code.id = o.id + "-totp";
    code.name = "code";
    code.autocomplete = "one-time-code";
    code.inputMode = "numeric";
    code.pattern = "[0-9]{6}";
    code.maxLength = 6;
    codeLabel.appendChild(code);
    codeLabel.hidden = true;
    form.appendChild(codeLabel);
    var btn = el("button", "btn", T(p + ".login.submit"));
    btn.type = "submit";
    form.appendChild(btn);

    function needCode() { codeLabel.hidden = false; code.required = true; }
    api("/api/admin/session").then(function (r) { if (r.data && r.data.totp) needCode(); }, function () {});

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      btn.disabled = true;
      var body = code.required ? { token: input.value, code: code.value } : { token: input.value };
      api("/api/admin/login", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
      }).then(function (r) {
        btn.disabled = false;
        code.value = "";
        if (r.status === 401 && r.data && r.data.detail === "totp_required") {
          needCode();  // the key is kept: only the code is missing
          o.message(T("admin.msg.codeRequired"), false);
          code.focus();
          return;
        }
        input.value = "";
        if (r.status === 200) { o.message("", false); o.onOk(); return; }
        if (r.status === 503 && o.onDisabled) { o.onDisabled(); return; }
        o.message(T(r.status === 429 ? p + ".msg.tooMany"
          : code.required ? "admin.msg.wrongKeyOrCode" : p + ".msg.wrongKey"), true);
        input.focus();
      }).catch(function () {
        btn.disabled = false;
        o.message(T(p + ".msg.noServer"), true);
      });
    });
    return { form: form, input: input };
  };
})();
