// © 2026 Andy217Ace
// "Settings" from admin: capture retention and the free-space threshold. The admin key
// does NOT appear here (it stays in /etc/tabela.env). Loaded on demand; DOM only via createElement/textContent (CSP).
(function () {
  "use strict";

  function T(k, p) { return window.I18N.t(k, p); }

  var FIELDS = [
    ["capture_retention_days", "settings.retention.label", "settings.retention.hint"],
    ["capture_min_free_mb", "settings.minFree.label", "settings.minFree.hint"]
  ];

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }

  function api(path, opts) {
    opts = opts || {};
    opts.credentials = "same-origin";
    opts.cache = "no-store";
    return fetch(path, opts).then(function (r) {
      return r.json().catch(function () { return null; }).then(function (d) {
        return { status: r.status, data: d };
      });
    });
  }

  var csrf = null;
  function csrfToken(force) {
    if (csrf && !force) return Promise.resolve(csrf);
    return api("/api/admin/csrf").then(function (r) {
      csrf = (r.data && r.data.token) || "";
      return csrf;
    });
  }

  function save(body, retried) {
    return csrfToken(retried).then(function (tok) {
      return api("/api/admin/settings", {
        method: "POST",
        headers: { "X-CSRF-Token": tok, "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
    }).then(function (r) {
      if (r.status === 403 && !retried) return save(body, true);
      return r;
    });
  }

  function message(r) {
    var d = r.data && r.data.detail;
    if (typeof d === "string") return d;
    return T("settings.error", { status: r.status });
  }

  // mount(container): builds the settings form inside `container`
  var lastContainer = null;

  function mount(container) {
    lastContainer = container;
    clear(container);
    container.appendChild(el("h2", "setari-title", T("settings.title")));
    var status = el("p", "setari-status", "");
    status.setAttribute("role", "status");
    container.appendChild(status);

    var form = el("form", "setari-form panel");
    var inputs = {};
    FIELDS.forEach(function (f) {
      var key = f[0];
      var wrap = el("div", "setari-field");
      var label = el("label", null, T(f[1]));
      var input = el("input");
      input.type = "number";
      input.step = "1";
      input.name = key;
      input.id = "setari-" + key;
      label.setAttribute("for", input.id);
      var hint = el("p", "setari-hint", T(f[2]));
      wrap.appendChild(label);
      wrap.appendChild(input);
      wrap.appendChild(hint);
      form.appendChild(wrap);
      inputs[key] = input;
    });
    var btn = el("button", "setari-save", T("settings.save"));
    btn.type = "submit";
    form.appendChild(btn);
    container.appendChild(form);

    function fill(data) {
      FIELDS.forEach(function (f) {
        var s = data[f[0]];
        if (!s) return;
        inputs[f[0]].min = s.min;
        inputs[f[0]].max = s.max;
        inputs[f[0]].value = s.value;
      });
    }

    api("/api/admin/settings").then(function (r) {
      if (r.status === 200) { fill(r.data); return; }
      status.textContent = r.status === 401 || r.status === 503
        ? T("settings.authNeeded") : message(r);
      btn.disabled = true;
    });

    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var body = {};
      FIELDS.forEach(function (f) {
        var raw = inputs[f[0]].value.trim();
        body[f[0]] = /^-?\d+$/.test(raw) ? parseInt(raw, 10) : raw;
      });
      status.textContent = T("settings.saving");
      save(body).then(function (r) {
        if (r.status === 200) { fill(r.data); status.textContent = T("settings.saved"); return; }
        status.textContent = r.status === 422
          ? T("settings.outOfRange")
          : message(r);
      });
    });
  }

  // language switch: rebuild the form in the new language
  document.addEventListener("i18n:change", function () {
    if (lastContainer && document.body.contains(lastContainer)) mount(lastContainer);
  });

  window.TabelaSetari = { mount: mount };
})();
