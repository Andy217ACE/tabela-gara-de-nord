// © 2026 Andy217Ace
// „Capturi OCR" (#ocr): admin-only diagnostic view, loaded on demand by app.js.
// Raw CFR captures are private: every call goes to /api/admin/* (token cookie or 503/401).
// DOM is built with createElement/textContent only (CSP: no inline styles or HTML strings).
(function () {
  "use strict";

  var FIELDS = [
    ["type", "Tip"], ["no", "Nr."], ["station", "Stație"], ["operator", "Operator"],
    ["time", "Ora"], ["delay", "Întârziere"], ["platform", "Linie"]
  ];
  var STATE_LABEL = {
    ok: "valid", uncertain: "nesigur", rejected_low_conf: "respins (încredere mică)",
    incomplete: "incomplet"
  };
  var BOARD_LABEL = { arrival: "Sosiri", departure: "Plecări" };
  var PAGE = 50;

  var root = null;
  var state = { before: null, selected: null, detail: null, overlay: true };

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
      if (r.status === 204) return { status: r.status, data: null };
      return r.json().catch(function () { return null; }).then(function (d) {
        return { status: r.status, data: d };
      });
    });
  }

  var fmtTime = new Intl.DateTimeFormat("ro-RO", {
    timeZone: "Europe/Bucharest", day: "2-digit", month: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit"
  });

  function when(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    return isNaN(d) ? iso : fmtTime.format(d);
  }

  function bytes(n) {
    if (n == null) return "—";
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
    return (n / 1048576).toFixed(1) + " MB";
  }

  function ms(n) { return n == null ? "—" : (n >= 1000 ? (n / 1000).toFixed(2) + " s" : Math.round(n) + " ms"); }

  function age(s) {
    if (s == null) return "—";
    if (s < 90) return Math.round(s) + " s";
    if (s < 5400) return Math.round(s / 60) + " min";
    return (s / 3600).toFixed(1) + " h";
  }

  function confClass(c) {
    if (c == null) return "ocr-conf ocr-conf-none";
    return "ocr-conf " + (c >= 80 ? "ocr-conf-hi" : c >= 50 ? "ocr-conf-mid" : "ocr-conf-lo");
  }

  // ---- skeleton ---------------------------------------------------------------------

  function build() {
    root = document.getElementById("view-ocr");
    clear(root);
    root.setAttribute("aria-labelledby", "ocr-heading");
    var head = el("div", "page-head ocr-head");
    var h = el("h1", null, "Capturi OCR");
    h.id = "ocr-heading";
    head.appendChild(h);
    head.appendChild(el("p", "page-sub",
      "Diagnostic intern: imaginea tabelei, dreptunghiurile citite și încrederea pe câmp. " +
      "Capturile CFR sunt private și nu se redistribuie."));
    root.appendChild(head);
    var msg = el("p", "notice", "");
    msg.id = "ocr-msg";
    msg.setAttribute("role", "status");
    msg.hidden = true;
    root.appendChild(msg);
    var body = el("div", "ocr-body");
    body.id = "ocr-body";
    root.appendChild(body);
  }

  function message(text, isError) {
    var m = document.getElementById("ocr-msg");
    m.textContent = text || "";
    m.className = "notice" + (isError ? " notice-error" : "");
    m.hidden = !text;
  }

  // ---- login ------------------------------------------------------------------------

  function showLogin(note) {
    var body = document.getElementById("ocr-body");
    clear(body);
    var form = el("form", "ocr-login panel");
    form.setAttribute("aria-label", "Autentificare administrare");
    var label = el("label", "field");
    label.appendChild(el("span", "field-label", "Cheie de administrare"));
    var input = el("input");
    input.type = "password";
    input.id = "ocr-token";
    input.name = "token";
    input.autocomplete = "current-password";
    input.required = true;
    input.maxLength = 200;
    label.appendChild(input);
    form.appendChild(label);
    var btn = el("button", "btn", "Autentificare");
    btn.type = "submit";
    form.appendChild(btn);
    body.appendChild(form);
    if (note) message(note, true);
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      btn.disabled = true;
      api("/api/admin/login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: input.value })
      }).then(function (r) {
        btn.disabled = false;
        input.value = "";
        if (r.status === 200) { message(""); loadAll(); return; }
        if (r.status === 429) message("Prea multe încercări. Reîncearcă peste un minut.", true);
        else if (r.status === 503) disabled();
        else message("Cheie greșită.", true);
        input.focus();
      }).catch(function () {
        btn.disabled = false;
        message("Serverul nu răspunde.", true);
      });
    });
    input.focus();
  }

  function disabled() {
    clear(document.getElementById("ocr-body"));
    message("Administrarea este dezactivată pe acest server (ADMIN_TOKEN nesetat).", true);
  }

  function logout() {
    api("/api/admin/logout", { method: "POST" }).finally(function () {
      state.detail = null;
      showLogin();
      message("Ai ieșit din administrare.");
    });
  }

  // ---- main view ----------------------------------------------------------------------

  function loadAll() {
    var body = document.getElementById("ocr-body");
    clear(body);
    var bar = el("div", "ocr-bar");
    var refresh = el("button", "btn btn-ghost btn-sm", "Reîncarcă");
    refresh.type = "button";
    refresh.addEventListener("click", loadAll);
    var out = el("button", "btn btn-ghost btn-sm", "Ieșire");
    out.type = "button";
    out.addEventListener("click", logout);
    bar.appendChild(refresh);
    bar.appendChild(out);
    body.appendChild(bar);
    var stats = el("dl", "ocr-stats");
    stats.id = "ocr-stats";
    body.appendChild(stats);
    var layout = el("div", "ocr-layout");
    var listBox = el("section", "ocr-list");
    listBox.setAttribute("aria-label", "Capturi recente");
    listBox.appendChild(el("h2", "ocr-h2", "Capturi recente"));
    var wrap = el("div", "ocr-scroll");
    var table = el("table", "ocr-table");
    var thead = el("thead");
    var tr = el("tr");
    ["Ora", "Stare", "Rânduri", "Durată", "Mărime", "Hash", "Versiune", "Eroare"].forEach(function (t) {
      var th = el("th", null, t);
      th.scope = "col";
      tr.appendChild(th);
    });
    thead.appendChild(tr);
    table.appendChild(thead);
    var tbody = el("tbody");
    tbody.id = "ocr-rows";
    table.appendChild(tbody);
    wrap.appendChild(table);
    listBox.appendChild(wrap);
    var more = el("button", "btn btn-ghost btn-sm", "Mai vechi");
    more.type = "button";
    more.id = "ocr-more";
    more.hidden = true;
    more.addEventListener("click", function () { loadList(false); });
    listBox.appendChild(more);
    var detail = el("section", "ocr-detail");
    detail.id = "ocr-detail";
    detail.setAttribute("aria-live", "polite");
    detail.appendChild(el("p", "empty", "Alege o captură din listă."));
    layout.appendChild(listBox);
    layout.appendChild(detail);
    body.appendChild(layout);
    state.before = null;
    loadStats();
    loadList(true);
  }

  function stat(dl, label, value, cls) {
    var d = el("div", "ocr-stat" + (cls ? " " + cls : ""));
    d.appendChild(el("dt", null, label));
    d.appendChild(el("dd", null, value));
    dl.appendChild(d);
  }

  function loadStats() {
    api("/api/admin/stats").then(function (r) {
      var dl = document.getElementById("ocr-stats");
      if (!dl) return;
      if (r.status !== 200 || !r.data) { handleAuth(r); return; }
      var s = r.data;
      clear(dl);
      stat(dl, "Ultima captură", when(s.last_capture_attempt));
      stat(dl, "Ultima reușită", when(s.last_capture_ok));
      stat(dl, "Durată OCR medie / p95",
        ms(s.duration_ms.avg) + " / " + ms(s.duration_ms.p95) + " (N=" + s.duration_ms.n + ")");
      stat(dl, "Erori 24 h", String(s.errors_24h), s.errors_24h ? "is-bad" : "");
      stat(dl, "Rânduri 24 h (cu probleme)", s.rows_24h + " (" + s.rows_with_errors_24h + ")");
      stat(dl, "Vechime LIVE", age(s.live_age_s), s.live_age_s == null || s.live_age_s > 180 ? "is-bad" : "");
      stat(dl, "Imagini păstrate", s.images.count + " · " + bytes(s.images.bytes) +
        " · " + s.capture.retention_days + " zile");
      stat(dl, "Baza de date", bytes(s.db_bytes));
      stat(dl, "Tesseract", s.tesseract.available ? (s.tesseract.version || "disponibil") : "indisponibil",
        s.tesseract.available ? "" : "is-bad");
      stat(dl, "Sursa CFR", s.source.available ? "disponibilă" : "fără imagini noi",
        s.source.available ? "" : "is-bad");
    });
  }

  function handleAuth(r) {
    if (r.status === 401) showLogin("Sesiunea a expirat. Autentifică-te din nou.");
    else if (r.status === 503) disabled();
    else if (r.status === 429) message("Prea multe încercări. Reîncearcă peste un minut.", true);
    else message("Eroare la încărcare (" + r.status + ").", true);
  }

  function loadList(reset) {
    var url = "/api/admin/captures?limit=" + PAGE + (reset || !state.before ? "" : "&before=" + state.before);
    api(url).then(function (r) {
      if (r.status !== 200) { handleAuth(r); return; }
      var tbody = document.getElementById("ocr-rows");
      if (!tbody) return;
      if (reset) clear(tbody);
      r.data.captures.forEach(function (c) { tbody.appendChild(captureRow(c)); });
      if (reset && !r.data.captures.length) {
        var tr = el("tr");
        var td = el("td", "empty", "Nicio captură încă.");
        td.colSpan = 8;
        tr.appendChild(td);
        tbody.appendChild(tr);
      }
      state.before = r.data.next_before;
      document.getElementById("ocr-more").hidden = !state.before;
    });
  }

  function captureRow(c) {
    var tr = el("tr", c.ok ? "" : "is-error");
    tr.dataset.id = c.id;
    var td = el("td");
    var b = el("button", "ocr-open", when(c.captured_at));
    b.type = "button";
    b.setAttribute("aria-label", "Deschide captura din " + when(c.captured_at));
    b.addEventListener("click", function () { openDetail(c.id); });
    td.appendChild(b);
    tr.appendChild(td);
    tr.appendChild(el("td", null, c.ok ? "ok" : "eroare"));
    tr.appendChild(el("td", "num", String(c.n_rows)));
    tr.appendChild(el("td", "num", ms(c.duration_ms)));
    tr.appendChild(el("td", "num", bytes(c.bytes)));
    tr.appendChild(el("td", "mono", c.hash8));
    tr.appendChild(el("td", "mono", c.processing_version || "—"));
    tr.appendChild(el("td", "ocr-err", c.error || ""));
    return tr;
  }

  // ---- detail -------------------------------------------------------------------------

  function openDetail(id) {
    state.selected = id;
    document.querySelectorAll("#ocr-rows tr").forEach(function (tr) {
      if (String(tr.dataset.id) === String(id)) tr.setAttribute("aria-current", "true");
      else tr.removeAttribute("aria-current");
    });
    api("/api/admin/captures/" + id).then(function (r) {
      if (r.status !== 200) { handleAuth(r); return; }
      state.detail = r.data;
      renderDetail(r.data);
    });
  }

  function imageSrc(d) {
    return "/api/admin/captures/" + d.id + (state.overlay ? "/overlay.png" : "/image");
  }

  function renderDetail(d) {
    var box = document.getElementById("ocr-detail");
    clear(box);
    var h = el("h2", "ocr-h2", "Captura #" + d.id + " · " + when(d.captured_at));
    h.tabIndex = -1;
    box.appendChild(h);
    var meta = el("p", "ocr-meta",
      (d.ok ? "OCR reușit" : "OCR eșuat") + " · " + d.n_rows + " rânduri valide · " +
      d.observations.length + " linii citite · " + ms(d.duration_ms) + " · " +
      (d.width ? d.width + "×" + d.height + " px · " : "") + bytes(d.bytes) + " · hash " + d.hash8);
    box.appendChild(meta);
    if (d.error) box.appendChild(el("p", "notice notice-error", d.error));

    var tools = el("div", "ocr-tools");
    var lab = el("label", "ocr-toggle");
    var cb = el("input");
    cb.type = "checkbox";
    cb.checked = state.overlay;
    var viewable = d.has_image && !!d.width;  // width is null when the bytes did not decode
    cb.disabled = !viewable;
    lab.appendChild(cb);
    lab.appendChild(el("span", null, "Dreptunghiuri OCR"));
    tools.appendChild(lab);
    var copy = el("button", "btn btn-ghost btn-sm", "Copiază JSON");
    copy.type = "button";
    copy.addEventListener("click", function () {
      var text = JSON.stringify(d, null, 2);
      var done = function () { copy.textContent = "Copiat"; setTimeout(function () { copy.textContent = "Copiază JSON"; }, 1500); };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { message("Copierea a eșuat.", true); });
      } else {
        message("Clipboard indisponibil în acest browser.", true);
      }
    });
    tools.appendChild(copy);
    box.appendChild(tools);

    if (viewable) {
      var fig = el("figure", "ocr-figure");
      var img = el("img", "ocr-img");
      img.alt = "Imaginea tabelei CFR din captura #" + d.id + (state.overlay ? ", cu dreptunghiurile OCR" : "");
      img.decoding = "async";
      img.src = imageSrc(d);
      img.addEventListener("error", function () { message("Imaginea nu a putut fi încărcată.", true); });
      fig.appendChild(img);
      var legend = el("figcaption", "ocr-legend");
      [["ocr-conf ocr-conf-hi", "≥ 80"], ["ocr-conf ocr-conf-mid", "50–79"], ["ocr-conf ocr-conf-lo", "< 50"]].forEach(function (p) {
        legend.appendChild(el("span", p[0], p[1]));
      });
      legend.appendChild(el("span", "ocr-legend-text", "încredere Tesseract pe celulă; numărul = indexul liniei"));
      fig.appendChild(legend);
      box.appendChild(fig);
      cb.addEventListener("change", function () {
        state.overlay = cb.checked;
        img.src = imageSrc(d);
        img.alt = "Imaginea tabelei CFR din captura #" + d.id + (state.overlay ? ", cu dreptunghiurile OCR" : "");
      });
    } else if (d.has_image) {
      box.appendChild(el("p", "notice", "Fișierul salvat nu este o imagine validă (de aceea OCR a eșuat)."));
    } else {
      box.appendChild(el("p", "notice", "Imaginea a expirat (retenție); datele structurate rămân."));
    }

    ["arrival", "departure"].forEach(function (board) {
      var obs = d.observations.filter(function (o) { return o.board === board; });
      if (!obs.length) return;
      box.appendChild(el("h3", "ocr-h3", BOARD_LABEL[board] + " (" + obs.length + ")"));
      box.appendChild(obsTable(obs));
    });
    h.focus();
  }

  function obsTable(list) {
    var wrap = el("div", "ocr-scroll");
    var t = el("table", "ocr-table ocr-obs");
    var thead = el("thead");
    var tr = el("tr");
    ["#", "Stare", "Text brut"].concat(FIELDS.map(function (f) { return f[1]; })).forEach(function (x) {
      var th = el("th", null, x);
      th.scope = "col";
      tr.appendChild(th);
    });
    thead.appendChild(tr);
    t.appendChild(thead);
    var tb = el("tbody");
    list.forEach(function (o) {
      var r = el("tr", "ocr-state-" + o.validation_state);
      r.appendChild(el("td", "num", String(o.row_index)));
      var st = el("td", "ocr-state");
      st.appendChild(el("span", "ocr-badge ocr-badge-" + o.validation_state, STATE_LABEL[o.validation_state] || o.validation_state));
      if (o.row_conf != null) st.appendChild(el("span", "ocr-rowconf", Math.round(o.row_conf * 100) + "%"));
      r.appendChild(st);
      r.appendChild(el("td", "mono ocr-raw", o.raw_text || "—"));
      FIELDS.forEach(function (f) {
        var cell = (o.fields || {})[f[0]] || {};
        var td = el("td", "ocr-field");
        var raw = cell.raw == null ? "" : String(cell.raw);
        var norm = cell.norm == null ? "" : String(cell.norm);
        td.appendChild(el("span", "ocr-raw-val mono", raw || "∅"));
        if (norm !== raw) {
          var n = el("span", "ocr-norm", "→ " + (norm || "∅"));
          td.appendChild(n);
        }
        var c = el("span", confClass(cell.conf), cell.conf == null ? "?" : String(Math.round(cell.conf)));
        c.title = "Încredere OCR";
        td.appendChild(c);
        if ((f[0] === "station" || f[0] === "operator") && o.uncertain) {
          var u = el("span", "ocr-unsure", "?");
          u.title = "Nume nepotrivit cu lista cunoscută (nesigur)";
          u.setAttribute("aria-label", "nesigur");
          td.appendChild(u);
        }
        if (f[0] === "delay" && !o.delay_read && o.validation_state !== "incomplete") {
          var x = el("span", "ocr-unsure", "necitit");
          td.appendChild(x);
        }
        r.appendChild(td);
      });
      tb.appendChild(r);
    });
    t.appendChild(tb);
    wrap.appendChild(t);
    return wrap;
  }

  // ---- view registration ----------------------------------------------------------------

  function show() {
    if (!root) build();
    api("/api/admin/session").then(function (r) {
      if (r.status !== 200 || !r.data) { handleAuth(r); return; }
      if (!r.data.enabled) { disabled(); return; }
      if (r.data.authenticated) {
        message("");
        if (!document.getElementById("ocr-rows")) loadAll();
      } else showLogin();
    }).catch(function () { message("Serverul nu răspunde.", true); });
  }

  window.TabelaApp = window.TabelaApp || {};
  window.TabelaApp.views = window.TabelaApp.views || {};
  window.TabelaApp.views.ocr = { show: show };
})();
