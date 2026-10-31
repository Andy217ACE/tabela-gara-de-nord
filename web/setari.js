// © 2026 Andy217Ace
// „Setări" din admin: retenția capturilor și pragul de spațiu liber. Cheia de administrare
// NU apare aici (rămâne în /etc/tabela.env). Încărcat la cerere; DOM doar cu createElement/textContent (CSP).
(function () {
  "use strict";

  var FIELDS = [
    ["capture_retention_days", "Retenția imaginilor capturate (zile)",
      "Imaginile mai vechi se șterg; metadatele rămân."],
    ["capture_min_free_mb", "Spațiu liber minim pe disc (MB)",
      "Sub acest prag, capturile noi se salvează doar ca metadate."]
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
    return "Eroare (" + r.status + ").";
  }

  // mount(container): builds the settings form inside `container`
  function mount(container) {
    clear(container);
    container.appendChild(el("h2", "setari-title", "Setări"));
    var status = el("p", "setari-status", "");
    status.setAttribute("role", "status");
    container.appendChild(status);

    var form = el("form", "setari-form panel");
    var inputs = {};
    FIELDS.forEach(function (f) {
      var key = f[0];
      var wrap = el("div", "setari-field");
      var label = el("label", null, f[1]);
      var input = el("input");
      input.type = "number";
      input.step = "1";
      input.name = key;
      input.id = "setari-" + key;
      label.setAttribute("for", input.id);
      var hint = el("p", "setari-hint", f[2]);
      wrap.appendChild(label);
      wrap.appendChild(input);
      wrap.appendChild(hint);
      form.appendChild(wrap);
      inputs[key] = input;
    });
    var btn = el("button", "setari-save", "Salvează");
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
        ? "Autentificare necesară pentru setări." : message(r);
      btn.disabled = true;
    });

    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var body = {};
      FIELDS.forEach(function (f) {
        var raw = inputs[f[0]].value.trim();
        body[f[0]] = /^-?\d+$/.test(raw) ? parseInt(raw, 10) : raw;
      });
      status.textContent = "Se salvează…";
      save(body).then(function (r) {
        if (r.status === 200) { fill(r.data); status.textContent = "Setările au fost salvate."; return; }
        status.textContent = r.status === 422
          ? "Valoare în afara intervalului permis. Nu s-a modificat nimic."
          : message(r);
      });
    });
  }

  window.TabelaSetari = { mount: mount };
})();
