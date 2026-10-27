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
  var LINE_LABEL = { empty: "rând gol", unread: "rând necitit" };

  // "S 12 · P 11" (+ re-reads) from the per-panel counts of a capture
  function boardsText(b) {
    if (!b || !b.arrivals) return "—";
    var t = "S " + b.arrivals.rows + " · P " + b.departures.rows;
    var re = b.arrivals.retried + b.departures.retried;
    if (re) t += " · recitite " + re + " (+" + (b.arrivals.recovered + b.departures.recovered) + ")";
    return t;
  }

  var EXPECTED = 12;  // lines per panel (4 groups x 3); /api/admin/stats ocr.expected_rows

  function boardsShort(b) {
    return b && b.arrivals && (b.arrivals.rows !== EXPECTED || b.departures.rows !== EXPECTED);
  }
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
    var rulesBox = el("section", "ocr-rules panel");
    rulesBox.id = "ocr-rules";
    rulesBox.setAttribute("aria-label", "Corecții manuale");
    body.appendChild(rulesBox);
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
    loadRules();
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
      if (s.ocr && s.ocr.window) {
        var w = s.ocr.window, last = s.ocr.last;
        if (s.ocr.expected_rows) EXPECTED = s.ocr.expected_rows;
        stat(dl, "Cadre cu " + EXPECTED + "/" + EXPECTED + " rânduri", w.frames ? w.full_frames + " din " + w.frames + " (de la pornire, max. 60)" : "—",
          w.frames && w.full_frames < w.frames ? "is-bad" : "");
        stat(dl, "Recitiri OCR (rânduri recuperate)", w.lines_retried + " (" + w.lines_recovered + ") · max " + ms(w.retry_ms_max));
        if (last && last.boards) {
          stat(dl, "Ultimul cadru", "S " + (last.boards.arrival || {}).rows + " · P " + (last.boards.departure || {}).rows +
            " · " + ms(last.duration_ms));
        }
      }
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
    tr.appendChild(el("td", "num" + (boardsShort(c.boards) ? " is-bad" : ""),
      c.boards ? boardsText(c.boards) : String(c.n_rows)));
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
      (d.ok ? "OCR reușit" : "OCR eșuat") + " · " + d.n_rows + " rânduri valide (" +
      boardsText(d.boards) + " din " + EXPECTED + "/" + EXPECTED + ") · " +
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

    var corrBox = el("section", "ocr-corr-form panel");
    corrBox.id = "ocr-corr-form";
    corrBox.hidden = true;
    corrBox.setAttribute("aria-label", "Corecție manuală");
    box.appendChild(corrBox);

    ["arrival", "departure"].forEach(function (board) {
      var obs = d.observations.filter(function (o) { return o.board === board; });
      if (!obs.length) return;
      box.appendChild(el("h3", "ocr-h3", BOARD_LABEL[board] + " (" + obs.length + ")"));
      box.appendChild(obsTable(obs, d));
    });
    h.focus();
  }

  function obsTable(list, cap) {
    var wrap = el("div", "ocr-scroll");
    var t = el("table", "ocr-table ocr-obs");
    var thead = el("thead");
    var tr = el("tr");
    ["#", "Stare", "Text brut"].concat(FIELDS.map(function (f) { return f[1]; }), ["Corecție"]).forEach(function (x) {
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
      var line = o.line || {};
      var lbl = (line.state && LINE_LABEL[line.state]) || STATE_LABEL[o.validation_state] || o.validation_state;
      st.appendChild(el("span", "ocr-badge ocr-badge-" + o.validation_state, lbl));
      if (line.retry) {
        st.appendChild(el("span", "ocr-rowconf", line.retry.variant
          ? "recitit (" + line.retry.variant + ", " + line.retry.attempts + ")"
          : "recitit fără succes (" + line.retry.attempts + ")"));
      }
      if (o.row_conf != null) st.appendChild(el("span", "ocr-rowconf", Math.round(o.row_conf * 100) + "%"));
      (line.corr || []).forEach(function (id) {
        var b = el("span", "ocr-badge ocr-badge-corr", "corectat #" + id);
        b.title = "Rândul a fost modificat de regula manuală #" + id + " (valoarea citită de OCR rămâne în text brut)";
        st.appendChild(b);
      });
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
      var act = el("td", "ocr-act");
      var cbtn = el("button", "btn btn-ghost btn-sm", "Corectează");
      cbtn.type = "button";
      cbtn.setAttribute("aria-label", "Corectează rândul " + o.row_index + " (" + BOARD_LABEL[o.board] + ")");
      cbtn.addEventListener("click", function () { openCorrectionForm(cap, o); });
      act.appendChild(cbtn);
      r.appendChild(act);
      tb.appendChild(r);
    });
    t.appendChild(tb);
    wrap.appendChild(t);
    return wrap;
  }


  // ---- corecții manuale (schema v9) -----------------------------------------------------
  // Regulă îngustă (panou, câmp, valoare citită greșit, + stație / oră / interval de zile
  // opționale) -> valoare corectă. Se aplică pe cadre noi (marcaj +corr:<id>) și, doar după
  // o previzualizare (dry-run) și confirmare, retroactiv, într-un lot restaurabil.

  var CORR_FIELDS = [["no", "Nr. tren"], ["type", "Tip"], ["station", "Stație"],
    ["operator", "Operator"], ["time", "Ora"], ["platform", "Linie"], ["delay", "Întârziere"]];
  var csrf = null;

  function csrfToken(force) {
    if (csrf && !force) return Promise.resolve(csrf);
    return api("/api/admin/csrf").then(function (r) {
      csrf = (r.data && r.data.token) || "";
      return csrf;
    });
  }

  // mutating admin call: JSON body + X-CSRF-Token (one retry with a fresh token on 403)
  function post(path, body, method, retried) {
    return csrfToken(retried).then(function (tok) {
      var headers = { "X-CSRF-Token": tok };
      var opts = { method: method || "POST", headers: headers };
      if (body !== undefined) { headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
      return api(path, opts);
    }).then(function (r) {
      if (r.status === 403 && !retried) return post(path, body, method, true);
      return r;
    });
  }

  function detailText(r) {
    var d = r.data && r.data.detail;
    if (typeof d === "string") return d;
    if (d && d.message) return d.message;
    return "Eroare (" + r.status + ").";
  }

  function rowValue(o, field) {
    var f = (o.fields || {})[field] || {};
    if (field === "type") return f.norm == null ? "" : String(f.norm);
    if (field === "no") return o.train_no == null ? "" : String(o.train_no);
    if (field === "station") return o.station || "";
    if (field === "operator") return o.operator || "";
    if (field === "time") return o.sched_time || "";
    if (field === "platform") return o.platform == null ? "" : String(o.platform);
    return o.delay_read && o.delay_min != null ? String(o.delay_min) : "";  // delay: unread stays empty, never 0
  }

  function labeled(text, inp, hint) {
    var l = el("label", "field");
    l.appendChild(el("span", "field-label", text));
    l.appendChild(inp);
    if (hint) l.appendChild(el("span", "field-hint", hint));
    return l;
  }

  function input(type, id, max) {
    var i = el("input");
    i.type = type;
    i.id = id;
    i.autocomplete = "off";
    if (max) i.maxLength = max;
    return i;
  }

  function openCorrectionForm(cap, o) {
    var box = document.getElementById("ocr-corr-form");
    clear(box);
    box.hidden = false;
    var h = el("h3", "ocr-h3", "Corecție manuală · captura #" + cap.id + " · " + BOARD_LABEL[o.board] + " · rândul " + o.row_index);
    h.tabIndex = -1;
    box.appendChild(h);
    box.appendChild(el("p", "ocr-meta", "Text brut: " + (o.raw_text || "—") +
      ". Regula se aplică numai rândurilor care au exact valoarea citită greșit, pe acest panou, " +
      "și nu modifică imaginea sau textul brut OCR."));
    var msg = el("p", "notice", "");
    msg.setAttribute("role", "status");
    msg.hidden = true;
    var form = el("form", "ocr-corr-grid");

    var sel = el("select");
    sel.id = "corr-field";
    CORR_FIELDS.forEach(function (f) { var op = el("option", null, f[1]); op.value = f[0]; sel.appendChild(op); });
    form.appendChild(labeled("Câmp", sel));
    var wrong = input("text", "corr-wrong", 60);
    form.appendChild(labeled("Valoarea citită (greșită)", wrong));
    var wrongHint = el("span", "field-hint", "");
    wrong.parentNode.appendChild(wrongHint);
    var right = input("text", "corr-right", 60);
    right.required = true;
    form.appendChild(labeled("Valoarea corectă", right));

    var lim = el("fieldset", "ocr-corr-limits");
    lim.appendChild(el("legend", null, "Limitări (opțional; cu cât mai înguste, cu atât mai sigur)"));
    var st = input("text", "corr-station", 60);
    lim.appendChild(labeled("Doar stația", st));
    var tm = input("text", "corr-time", 5);
    tm.placeholder = "OO:MM";
    lim.appendChild(labeled("Doar ora programată", tm));
    var d1 = input("date", "corr-from");
    lim.appendChild(labeled("Zile de la", d1));
    var d2 = input("date", "corr-to");
    lim.appendChild(labeled("Zile până la", d2));
    var quick = el("button", "btn btn-ghost btn-sm", "Limitează la stația și ora acestui rând");
    quick.type = "button";
    quick.addEventListener("click", function () { st.value = o.station || ""; tm.value = o.sched_time || ""; invalidate(); });
    lim.appendChild(quick);
    form.appendChild(lim);

    var note = el("textarea");
    note.id = "corr-note";
    note.rows = 2;
    note.maxLength = 500;
    note.required = true;
    form.appendChild(labeled("Notă (obligatorie, 3–500 caractere)", note));

    function prefill() {
      var f = sel.value;
      wrong.value = rowValue(o, f);
      right.value = "";
      var unreadOk = f === "platform" || f === "delay";
      wrong.required = !unreadOk;
      wrongHint.textContent = unreadOk ? "Gol = „necitit” (nu 0)." : "";
    }
    sel.addEventListener("change", function () { prefill(); invalidate(); });
    prefill();

    var out = el("div", "ocr-corr-result");
    out.setAttribute("aria-live", "polite");
    var bar = el("div", "ocr-corr-actions");
    var prev = el("button", "btn", "Previzualizează");
    prev.type = "submit";
    var save = el("button", "btn", "Salvează regula");
    save.type = "button";
    save.disabled = true;
    var cancel = el("button", "btn btn-ghost", "Închide");
    cancel.type = "button";
    cancel.addEventListener("click", function () { box.hidden = true; clear(box); });
    bar.appendChild(prev); bar.appendChild(save); bar.appendChild(cancel);
    form.appendChild(bar);
    box.appendChild(msg);
    box.appendChild(form);
    box.appendChild(out);

    function payload() {
      return {
        board: o.board, field: sel.value, wrong_value: wrong.value.trim(),
        correct_value: right.value.trim(), station: st.value.trim() || null,
        sched_time: tm.value.trim() || null, date_from: d1.value || null, date_to: d2.value || null,
        note: note.value.trim(), source_capture_id: cap.id, source_row_index: o.row_index
      };
    }
    function say(text, bad) { msg.textContent = text || ""; msg.className = "notice" + (bad ? " notice-error" : ""); msg.hidden = !text; }
    function invalidate() { save.disabled = true; clear(out); }
    [wrong, right, st, tm, d1, d2, note].forEach(function (i) { i.addEventListener("input", invalidate); });

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      say("");
      prev.disabled = true;
      post("/api/admin/corrections/preview", payload()).then(function (r) {
        prev.disabled = false;
        if (r.status !== 200) { save.disabled = true; say(detailText(r), true); return; }
        renderPreview(out, r.data.preview, "Previzualizare (nu s-a modificat nimic)");
        save.disabled = false;
      }).catch(function () { prev.disabled = false; say("Serverul nu răspunde.", true); });
    });
    save.addEventListener("click", function () {
      say("");
      save.disabled = true;
      post("/api/admin/corrections", payload()).then(function (r) {
        if (r.status !== 201) { save.disabled = false; say(detailText(r), true); return; }
        box.hidden = true;
        clear(box);
        message("Regula #" + r.data.correction.id + " este activă pe cadrele noi. Previzualizează și aplică retroactiv din „Corecții manuale”.");
        loadRules();
      }).catch(function () { save.disabled = false; say("Serverul nu răspunde.", true); });
    });
    h.focus();
    if (box.scrollIntoView) box.scrollIntoView({ block: "nearest" });
  }

  function cnt(label, n) {
    var d = el("div", "ocr-stat");
    d.appendChild(el("dt", null, label));
    d.appendChild(el("dd", null, String(n)));
    return d;
  }

  function previewTable(out, list, extra) {
    if (!list.length) return;
    var w = el("div", "ocr-scroll");
    var t = el("table", "ocr-table");
    var tr = el("tr");
    ["Serviciu", "Ziua", "Tren", "Ora", "Stația", "Din → în"].concat(extra ? ["Motiv"] : []).forEach(function (x) {
      var th = el("th", null, x); th.scope = "col"; tr.appendChild(th);
    });
    var hd = el("thead"); hd.appendChild(tr); t.appendChild(hd);
    var tb = el("tbody");
    list.forEach(function (s) {
      var r = el("tr");
      [s.id, s.date, s.train, s.sched_time, s.station, (s.from || "necitit") + " → " + s.to].forEach(function (v) { r.appendChild(el("td", null, String(v))); });
      if (extra) r.appendChild(el("td", "ocr-raw", s.conflict || ""));
      tb.appendChild(r);
    });
    t.appendChild(tb); w.appendChild(t); out.appendChild(w);
  }

  function renderPreview(out, pv, title) {
    clear(out);
    out.appendChild(el("h4", "ocr-h3", title));
    var dl = el("dl", "ocr-stats");
    dl.appendChild(cnt("Servicii", pv.services.count));
    dl.appendChild(cnt("Observații (capturi)", pv.observations.count + " (" + pv.observations.captures + ")"));
    dl.appendChild(cnt("Evenimente", pv.events.count));
    dl.appendChild(cnt("Conflicte (sărite)", pv.conflicts.count));
    out.appendChild(dl);
    if (pv.empty) out.appendChild(el("p", "notice", "Nicio înregistrare existentă nu se potrivește: regula va acționa doar pe cadrele noi."));
    if (pv.services.sample.length) {
      out.appendChild(el("p", "ocr-meta", "Servicii care s-ar modifica (primele " + pv.services.sample.length + " din " + pv.services.count + "):"));
      previewTable(out, pv.services.sample, false);
    }
    if (pv.conflicts.sample.length) {
      out.appendChild(el("p", "ocr-meta", "Conflicte (nu se modifică):"));
      previewTable(out, pv.conflicts.sample, true);
    }
  }

  // ---- lista regulilor ------------------------------------------------------------------

  function scopeText(r) {
    var p = [];
    if (r.station) p.push("stația " + r.station);
    if (r.sched_time) p.push("ora " + r.sched_time);
    if (r.date_from || r.date_to) p.push("zilele " + (r.date_from || "…") + " – " + (r.date_to || "…"));
    return p.length ? p.join(", ") : "fără limitări";
  }

  function fieldLabel(f) {
    for (var i = 0; i < CORR_FIELDS.length; i++) if (CORR_FIELDS[i][0] === f) return CORR_FIELDS[i][1];
    return f;
  }

  function loadRules() {
    var box = document.getElementById("ocr-rules");
    if (!box) return;
    api("/api/admin/corrections?status=all").then(function (r) {
      if (r.status !== 200) { handleAuth(r); return; }
      clear(box);
      var head = el("div", "ocr-rules-head");
      head.appendChild(el("h2", "ocr-h2", "Corecții manuale"));
      var aud = el("button", "btn btn-ghost btn-sm", "Jurnal de audit");
      aud.type = "button";
      aud.addEventListener("click", showAudit);
      head.appendChild(aud);
      box.appendChild(head);
      box.appendChild(el("p", "ocr-meta",
        "Se creează din detaliul unei capturi (butonul „Corectează” de pe fiecare rând). O regulă corectează cadrele noi imediat; " +
        "datele vechi se schimbă numai după previzualizare și confirmare, într-un lot care se poate restaura. Nimic de aici nu apare în API-ul public."));
      var list = r.data.corrections;
      if (!list.length) {
        box.appendChild(el("p", "empty", "Nicio regulă încă."));
      } else {
        var w = el("div", "ocr-scroll");
        var t = el("table", "ocr-table ocr-rule-table");
        var tr = el("tr");
        ["#", "Panou", "Câmp", "Citit → corect", "Limitări", "Notă", "Stare", "Acțiuni"].forEach(function (x) {
          var th = el("th", null, x); th.scope = "col"; tr.appendChild(th);
        });
        var hd = el("thead"); hd.appendChild(tr); t.appendChild(hd);
        var tb = el("tbody");
        list.forEach(function (c) { tb.appendChild(ruleRow(c)); });
        t.appendChild(tb); w.appendChild(t); box.appendChild(w);
      }
      var res = el("div", "ocr-corr-result");
      res.id = "ocr-rule-result";
      res.setAttribute("aria-live", "polite");
      box.appendChild(res);
    });
  }

  function liveBatches(c) { return (c.batches || []).filter(function (b) { return !b.restored_at; }); }

  function ruleRow(c) {
    var tr = el("tr", c.status === "deleted" ? "is-deleted" : "");
    tr.appendChild(el("td", "num", String(c.id)));
    tr.appendChild(el("td", null, BOARD_LABEL[c.board]));
    tr.appendChild(el("td", null, fieldLabel(c.field)));
    tr.appendChild(el("td", "mono", (c.wrong_value || "necitit") + " → " + c.correct_value));
    tr.appendChild(el("td", "ocr-raw", scopeText(c)));
    tr.appendChild(el("td", "ocr-raw", c.note));
    var live = liveBatches(c);
    tr.appendChild(el("td", null, c.status === "deleted" ? "ștearsă" :
      "activă" + (live.length ? " · aplicată retroactiv (" + live.length + " lot)" : "")));
    var td = el("td", "ocr-act");
    if (c.status === "active") {
      var pv = el("button", "btn btn-ghost btn-sm", "Previzualizează retroactiv");
      pv.type = "button";
      pv.addEventListener("click", function () { previewRule(c); });
      td.appendChild(pv);
      live.forEach(function (b) {
        var rs = el("button", "btn btn-ghost btn-sm", "Restaurează lotul " + b.id);
        rs.type = "button";
        rs.addEventListener("click", function () { restoreBatch(b.id); });
        td.appendChild(rs);
      });
      var del = el("button", "btn btn-ghost btn-sm", "Șterge");
      del.type = "button";
      del.setAttribute("aria-label", "Șterge regula " + c.id);
      del.addEventListener("click", function () { deleteRule(c, live.length > 0); });
      td.appendChild(del);
    }
    tr.appendChild(td);
    return tr;
  }

  function ruleResult() { return document.getElementById("ocr-rule-result"); }

  function previewRule(c) {
    var out = ruleResult();
    post("/api/admin/corrections/" + c.id + "/preview").then(function (r) {
      if (r.status !== 200) { message(detailText(r), true); return; }
      message("");
      renderPreview(out, r.data.preview, "Regula #" + c.id + " · previzualizare retroactivă (nu s-a modificat nimic)");
      var pv = r.data.preview;
      var bar = el("div", "ocr-corr-actions");
      var go = el("button", "btn", "Aplică retroactiv (" + pv.services.count + " servicii, " + pv.observations.count + " observații)");
      go.type = "button";
      go.disabled = !!pv.empty;
      go.addEventListener("click", function () {
        go.disabled = true;
        post("/api/admin/corrections/" + c.id + "/apply", { plan_hash: pv.plan_hash }).then(function (a) {
          if (a.status !== 200) { go.disabled = false; message(detailText(a), true); return; }
          message("Aplicat: lotul " + a.data.batch + " (" + a.data.services + " servicii, " + a.data.observations + " observații). Poate fi restaurat.");
          loadRules();
        });
      });
      bar.appendChild(go);
      out.appendChild(bar);
      if (out.scrollIntoView) out.scrollIntoView({ block: "nearest" });
    });
  }

  function restoreBatch(id) {
    if (!window.confirm("Restaurezi lotul " + id + "? Valorile vechi revin acolo unde nu s-au schimbat între timp.")) return;
    post("/api/admin/corrections/batches/" + encodeURIComponent(id) + "/restore").then(function (r) {
      if (r.status !== 200) { message(detailText(r), true); return; }
      message("Lot restaurat: " + r.data.services + " servicii, " + r.data.observations + " observații (sărite: " + r.data.skipped + ").");
      loadRules();
    });
  }

  function deleteRule(c, hasBatches) {
    var q = hasBatches
      ? "Ștergi regula #" + c.id + " ȘI restaurezi lotul aplicat retroactiv?"
      : "Ștergi regula #" + c.id + "? Nu va mai acționa pe cadrele noi (rămâne în jurnal).";
    if (!window.confirm(q)) return;
    post("/api/admin/corrections/" + c.id + (hasBatches ? "?restore=1" : ""), undefined, "DELETE").then(function (r) {
      if (r.status !== 200) { message(detailText(r), true); return; }
      message("Regula #" + c.id + " a fost ștearsă.");
      loadRules();
    });
  }

  var ACTION_LABEL = { create: "creată", apply: "aplicată retroactiv", restore: "restaurat lot", delete: "ștearsă" };

  function showAudit() {
    var out = ruleResult();
    api("/api/admin/corrections/audit?limit=100").then(function (r) {
      if (r.status !== 200) { handleAuth(r); return; }
      clear(out);
      out.appendChild(el("h4", "ocr-h3", "Jurnal de audit (ultimele " + r.data.audit.length + ")"));
      var w = el("div", "ocr-scroll");
      var t = el("table", "ocr-table");
      var tr = el("tr");
      ["Ora", "Acțiune", "Regula", "Lot", "IP"].forEach(function (x) { var th = el("th", null, x); th.scope = "col"; tr.appendChild(th); });
      var hd = el("thead"); hd.appendChild(tr); t.appendChild(hd);
      var tb = el("tbody");
      r.data.audit.forEach(function (a) {
        var row = el("tr");
        [when(a.ts), ACTION_LABEL[a.action] || a.action, a.correction_id == null ? "—" : "#" + a.correction_id, a.batch || "—", a.ip || "—"]
          .forEach(function (v) { row.appendChild(el("td", null, v)); });
        tb.appendChild(row);
      });
      t.appendChild(tb); w.appendChild(t); out.appendChild(w);
    });
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
