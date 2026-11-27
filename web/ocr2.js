// © 2026 Andy217Ace
// „Alternativa OCR" (#ocr2): admin-only evidence page for the alt reader, loaded on demand by app.js.
// DOM is built with createElement/textContent only (CSP: no inline styles or HTML strings).
(function () {
  "use strict";

  function T(k, p) { return window.I18N.t(k, p); }

  var VERDICTS = ["correct", "wrong", "unclear"];
  var FIELD_KEY = { type: "ocr.field.type", no: "ocr.field.no", station: "ocr.field.station",
    operator: "ocr.field.operator", time: "ocr.field.time", delay: "ocr.field.delay", platform: "ocr.field.platform" };
  var root = null;
  var st = { events: [], next: null, only: "all", totals: null, state: null, loaded: false };

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  function $(id) { return document.getElementById(id); }

  function api(path, opts) {
    opts = opts || {};
    opts.credentials = "same-origin";
    opts.cache = "no-store";
    return fetch(path, opts).then(function (r) {
      return r.json().catch(function () { return null; }).then(function (d) { return { status: r.status, data: d }; });
    });
  }

  var csrf = null;
  // mutating admin call: JSON body + X-CSRF-Token (one retry with a fresh token on 403)
  function post(path, body, retried) {
    return (csrf && !retried ? Promise.resolve(csrf) : api("/api/admin/csrf").then(function (r) {
      csrf = (r.data && r.data.token) || "";
      return csrf;
    })).then(function (tok) {
      return api(path, { method: "POST", headers: { "X-CSRF-Token": tok, "Content-Type": "application/json" },
        body: JSON.stringify(body) });
    }).then(function (r) { return r.status === 403 && !retried ? post(path, body, true) : r; });
  }

  function when(iso) {
    var d = new Date(iso);
    return isNaN(d) ? (iso || "—") : new Intl.DateTimeFormat(window.I18N.lang() === "en" ? "en-GB" : "ro-RO", {
      timeZone: "Europe/Bucharest", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit"
    }).format(d);
  }
  function label(col) { return FIELD_KEY[col] ? T(FIELD_KEY[col]) : col; }

  function message(text) {
    var m = $("ocr2-msg");
    m.textContent = text || "";
    m.hidden = !text;
  }

  function build() {
    root = $("view-ocr2");
    if (!root) {   // created here, hidden/shown by app.js route() like the other views
      root = el("section", "view view-ocr2");
      root.id = "view-ocr2";
      $("main").appendChild(root);
    }
    clear(root);
    root.setAttribute("aria-labelledby", "ocr2-heading");
    var head = el("div", "page-head");
    var h = el("h1", null, T("ocr2.title"));
    h.id = "ocr2-heading";
    head.appendChild(h);
    head.appendChild(el("p", "page-sub", T("ocr2.subtitle")));
    root.appendChild(head);
    var msg = el("p", "notice notice-error", "");
    msg.id = "ocr2-msg";
    msg.setAttribute("role", "status");
    msg.hidden = true;
    root.appendChild(msg);
    var body = el("div", "ocr2-body");
    body.id = "ocr2-body";
    root.appendChild(body);
  }

  // same login as #ocr (same session cookie), reusing its texts
  function showLogin() {
    var body = $("ocr2-body");
    clear(body);
    window.TabelaApp.adminLogin({ keys: "ocr", cls: "ocr2-login", message: message,
      onOk: function () { load(true); } }).then(function (f) {
      clear(body);
      body.appendChild(f.form);
    }, function () { message(T("ocr.msg.noServer")); });
  }

  // ---- state + totals ---------------------------------------------------------------

  function stat(dl, k, v) {
    var d = el("div", "ocr2-stat");
    d.appendChild(el("dt", null, k));
    d.appendChild(el("dd", null, v));
    dl.appendChild(d);
  }

  function renderSummary() {
    var box = $("ocr2-summary");
    clear(box);
    var s = st.state, t = st.totals;
    var yn = function (b) { return T(b ? "ocr2.yes" : "ocr2.no"); };
    box.appendChild(el("h2", "ocr2-h2", T("ocr2.state.h")));
    var dl = el("dl", "ocr2-stats");
    stat(dl, T("ocr2.state.enabled"), yn(s.enabled));
    stat(dl, T("ocr2.state.shadow"), yn(s.shadow));
    stat(dl, T("ocr2.state.model"), (s.model_path || "—") + " · " + T(s.model_loaded ? "ocr2.state.loaded" : "ocr2.state.notLoaded"));
    var c = s.since_start || {};
    stat(dl, T("ocr2.state.sinceStart"), T("ocr2.state.counters", { frames: c.frames || 0, tried: c.tried || 0, recovered: c.recovered || 0 }));
    box.appendChild(dl);
    box.appendChild(el("h2", "ocr2-h2", T("ocr2.totals.h")));
    var tl = el("dl", "ocr2-stats");
    stat(tl, T("ocr2.totals.events"), String(t.events));
    stat(tl, T("ocr2.totals.verified"), String(t.verified));
    stat(tl, T("ocr2.totals.correct"), String(t.correct));
    stat(tl, T("ocr2.totals.wrong"), String(t.wrong));
    stat(tl, T("ocr2.totals.unclear"), String(t.unclear));
    var p = el("div", "ocr2-stat ocr2-precision");
    p.appendChild(el("dt", null, T("ocr2.totals.precision")));
    p.appendChild(el("dd", null, t.precision == null ? "—" : (t.precision * 100).toFixed(1) + "%"));
    p.appendChild(el("dd", "ocr2-n", t.precision == null ? T("ocr2.totals.none") : T("ocr2.totals.n", { n: t.n_precision })));
    tl.appendChild(p);
    box.appendChild(tl);
  }

  // totals are recomputed locally after each verdict (no refetch: this page is the only writer of verdicts)
  function bump(old, nu) {
    var t = st.totals;
    if (old) { t[old]--; t.verified--; }
    if (nu) { t[nu]++; t.verified++; }
    t.n_precision = t.correct + t.wrong;
    t.precision = t.n_precision ? t.correct / t.n_precision : null;
    renderSummary();
  }

  // ---- events -----------------------------------------------------------------------

  function paintButtons(ev, li) {
    li.querySelectorAll(".ocr2-v").forEach(function (b) {
      b.setAttribute("aria-pressed", String(ev.verdict === b.dataset.v));
    });
  }

  function setVerdict(ev, v, li) {
    var old = ev.verdict;
    var nu = old === v ? null : v;
    var err = li.querySelector(".ocr2-err");
    ev.verdict = nu;
    bump(old, nu);
    paintButtons(ev, li);
    err.hidden = true;
    post("/api/admin/ocr-alt/" + encodeURIComponent(ev.id) + "/verdict", { verdict: nu }).then(function (r) {
      if (r.status < 200 || r.status >= 300) throw new Error(String(r.status));
    }).catch(function () {
      ev.verdict = old;
      bump(nu, old);
      paintButtons(ev, li);
      err.textContent = T("ocr2.verdict.error");
      err.hidden = false;
    });
  }

  function card(ev) {
    var li = el("li", "ocr2-ev panel");
    var head = el("div", "ocr2-ev-head");
    head.appendChild(el("strong", null, when(ev.ts)));
    head.appendChild(el("span", "ocr2-tag", T(ev.board === "arrival" ? "ocr.board.arrival" : "ocr.board.departure")));
    head.appendChild(el("span", null, T("ocr2.row", { n: ev.row_index })));
    if (ev.shadow) head.appendChild(el("span", "ocr2-tag", T("ocr2.shadow")));
    li.appendChild(head);
    var cx = ev.context || {};
    var ctx = ["type", "station", "operator"].map(function (k) {
      return label(k) + ": " + (cx[k] == null ? "—" : cx[k]);
    }).join(" · ");
    li.appendChild(el("p", "ocr2-ctx", T("ocr2.context") + " " + ctx));
    var cols = el("ul", "ocr2-cols");
    (ev.cols || []).forEach(function (col) {
      var c = el("li", "ocr2-col");
      var val = (ev.values || {})[col];
      var url = (ev.crops || {})[col];
      if (url) {
        var img = el("img", "ocr2-crop");
        img.src = url;
        img.alt = T("ocr2.cropAlt", { col: label(col), value: val == null ? "" : val });
        img.loading = "lazy";
        c.appendChild(img);
      }
      var txt = el("span", null, label(col) + ": ");
      txt.appendChild(el("strong", "mono", val == null ? "—" : String(val)));
      txt.appendChild(document.createTextNode(" · " + (ev.prob == null ? "—" : Math.round(ev.prob * 100) + "%")));
      c.appendChild(txt);
      cols.appendChild(c);
    });
    li.appendChild(cols);
    var bar = el("div", "ocr2-verdicts");
    bar.setAttribute("role", "group");
    bar.setAttribute("aria-label", T("ocr2.verdict.aria"));
    VERDICTS.forEach(function (v) {
      var b = el("button", "btn btn-ghost btn-sm ocr2-v ocr2-v-" + v, T("ocr2.verdict." + v));
      b.type = "button";
      b.dataset.v = v;
      b.addEventListener("click", function () { setVerdict(ev, v, li); });
      bar.appendChild(b);
    });
    li.appendChild(bar);
    var err = el("p", "notice notice-error ocr2-err", "");
    err.setAttribute("role", "alert");
    err.hidden = true;
    li.appendChild(err);
    paintButtons(ev, li);
    return li;
  }

  function renderEvents() {
    var box = $("ocr2-events");
    clear(box);
    if (!st.events.length) {
      box.appendChild(el("p", "ocr2-empty", T(st.only === "unverified" ? "ocr2.emptyFiltered" : "ocr2.empty")));
    } else {
      var ul = el("ul", "ocr2-list");
      st.events.forEach(function (ev) { ul.appendChild(card(ev)); });
      box.appendChild(ul);
    }
    $("ocr2-more").hidden = !st.next;
  }

  function fetchEvents(append) {
    var q = "?limit=50&only=" + st.only + (append && st.next ? "&before=" + encodeURIComponent(st.next) : "");
    return api("/api/admin/ocr-alt" + q).then(function (r) {
      if (r.status === 401 || r.status === 403) { showLogin(); return false; }
      if (r.status === 503) { message(T("ocr.msg.disabled")); return false; }
      if (r.status !== 200 || !r.data) { message(T("ocr.msg.loadError", { status: r.status })); return false; }
      message("");
      st.state = r.data.state;
      st.totals = r.data.totals;
      st.events = append ? st.events.concat(r.data.events) : r.data.events;
      st.next = r.data.next;
      return true;
    });
  }

  function skeleton() {
    var body = $("ocr2-body");
    clear(body);
    var sum = el("section", "ocr2-summary");
    sum.id = "ocr2-summary";
    body.appendChild(sum);
    var bar = el("div", "ocr2-bar");
    bar.appendChild(el("h2", "ocr2-h2", T("ocr2.events.h")));
    var lab = el("label", "ocr2-filter");
    var cb = el("input");
    cb.type = "checkbox";
    cb.id = "ocr2-only";
    cb.checked = st.only === "unverified";
    cb.addEventListener("change", function () {
      st.only = cb.checked ? "unverified" : "all";
      fetchEvents(false).then(function (ok) { if (ok) { renderSummary(); renderEvents(); } })
        .catch(function () { message(T("ocr.msg.noServer")); });
    });
    lab.appendChild(cb);
    lab.appendChild(el("span", null, T("ocr2.filter")));
    bar.appendChild(lab);
    body.appendChild(bar);
    var ev = el("div", "ocr2-events");
    ev.id = "ocr2-events";
    body.appendChild(ev);
    var more = el("button", "btn btn-ghost", T("ocr2.more"));
    more.type = "button";
    more.id = "ocr2-more";
    more.hidden = true;
    more.addEventListener("click", function () {
      more.disabled = true;
      fetchEvents(true).then(function (ok) { if (ok) renderEvents(); })
        .catch(function () { message(T("ocr.msg.noServer")); })
        .then(function () { more.disabled = false; });
    });
    body.appendChild(more);
  }

  function load(force) {
    if (st.loaded && !force) return;
    fetchEvents(false).then(function (ok) {
      if (!ok) return;
      st.loaded = true;
      skeleton();
      renderSummary();
      renderEvents();
    }).catch(function () { message(T("ocr.msg.noServer")); });
  }

  function show() {
    if (!root) build();
    load(false);
  }


  // language switch: rebuild in the new language
  document.addEventListener("i18n:change", function () {
    if (!root) return;
    root = null;
    st.loaded = false;
    if (location.hash === "#ocr2") show();
  });

  window.TabelaApp = window.TabelaApp || {};
  window.TabelaApp.views = window.TabelaApp.views || {};
  window.TabelaApp.views.ocr2 = { show: show };
})();
