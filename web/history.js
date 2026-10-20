// © 2026 Andy217Ace
// Tabela Gara de Nord — Istoric: what the CFR board showed on a given day.
// State lives in the URL hash (#istoric?date=…&train=…) so a search can be shared.
// DOM built with createElement/textContent only; the chart is SVG via createElementNS,
// styled from style.css (no inline styles: CSP). All values are *observed* on the board,
// never confirmed arrival/departure results.
"use strict";

(function () {
  var App = window.TabelaApp;
  var el = App.el;
  var SVG_NS = "http://www.w3.org/2000/svg";
  var TZ = "Europe/Bucharest";
  var DEBOUNCE_MS = 350;
  var TIMEOUT_MS = 10000;
  var FIELDS = ["date", "train", "station", "from", "to", "board"];
  var BOARD_LABEL = { arrival: "Sosire", departure: "Plecare" };
  var STATUS_LABEL = { listed: "pe tabelă", gone: "dispărut de pe tabelă" };

  var $ = function (id) { return document.getElementById(id); };
  var form, inputs = {}, timer = null, inflight = null, detailCtrl = null, lastQuery = null;
  var lastFocus = null;

  // ---- time helpers ------------------------------------------------------------

  function todayBucharest() {
    // en-CA formats as YYYY-MM-DD
    return new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit",
                                              day: "2-digit" }).format(new Date());
  }

  var timeFmt = new Intl.DateTimeFormat("ro-RO", { timeZone: TZ, hour: "2-digit", minute: "2-digit",
                                                   second: "2-digit", hour12: false });
  var shortTimeFmt = new Intl.DateTimeFormat("ro-RO", { timeZone: TZ, hour: "2-digit",
                                                        minute: "2-digit", hour12: false });
  var dayFmt = new Intl.DateTimeFormat("ro-RO", { timeZone: "UTC", weekday: "long", day: "numeric",
                                                  month: "long", year: "numeric" });

  function localTime(ts, short) {
    var d = new Date(ts);
    if (isNaN(d.getTime())) return ts || "";
    return (short ? shortTimeFmt : timeFmt).format(d);
  }

  function dayLabel(iso) {
    var d = new Date(iso + "T12:00:00Z");
    return isNaN(d.getTime()) ? iso : dayFmt.format(d);
  }

  function plural(n, one, many) {
    // Romanian: 1 rezultat, 2–19 rezultate, 20+ „de rezultate” (except …01–…19)
    if (n === 1) return "1 " + one;
    var tail = n % 100;
    return n + (n === 0 || (tail >= 1 && tail <= 19) ? " " : " de ") + many;
  }

  function delayText(d) {
    if (d == null) return "—";
    d = d | 0;
    return d <= 0 ? "la timp" : "+" + d + " min";
  }

  function delayLevel(d) {
    if (!d || d <= 0) return "ok";
    return d <= 15 ? "minor" : "major";
  }

  // ---- URL state -----------------------------------------------------------------

  function readForm() {
    var q = {};
    FIELDS.forEach(function (f) { q[f] = (inputs[f].value || "").trim(); });
    return q;
  }

  function writeForm(q) {
    FIELDS.forEach(function (f) { inputs[f].value = q[f] || ""; });
  }

  function queryFromParams(params) {
    var q = {};
    FIELDS.forEach(function (f) { q[f] = (params.get(f) || "").trim(); });
    if (!q.date) q.date = todayBucharest();
    if (q.board !== "arrival" && q.board !== "departure") q.board = "";
    return q;
  }

  function toSearch(q, includeDefaultDate) {
    var p = new URLSearchParams();
    FIELDS.forEach(function (f) {
      if (!q[f]) return;
      if (f === "date" && !includeDefaultDate && q.date === todayBucharest()) return;
      p.set(f, q[f]);
    });
    return p.toString();
  }

  function syncHash(q) {
    var s = toSearch(q, true);
    var hash = "#istoric" + (s ? "?" + s : "");
    if (location.hash !== hash) history.replaceState(null, "", hash);
  }

  // ---- validation (mirrors the API; the API stays the authority) ----------------------

  function validate(q) {
    var today = todayBucharest();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(q.date)) return "Alege o zi validă.";
    if (q.date > today) return "Ziua nu poate fi în viitor — istoricul începe cu ce s-a observat deja.";
    if (q.train && !/^\d{1,6}$/.test(q.train)) return "Numărul trenului are doar cifre (maxim 6).";
    if (q.from && q.to && q.from > q.to) return "Ora „de la” este după ora „până la”.";
    return null;
  }

  // ---- fetch helper -----------------------------------------------------------------

  function getJSON(url, ctrl) {
    var to = setTimeout(function () { ctrl.timedOut = true; ctrl.abort(); }, TIMEOUT_MS);
    return fetch(url, { signal: ctrl.signal, cache: "no-store", headers: { Accept: "application/json" } })
      .then(function (r) {
        return r.json().catch(function () { return null; }).then(function (body) {
          if (!r.ok) {
            var err = new Error("http");
            err.status = r.status;
            err.detail = body && typeof body.detail === "string" ? body.detail : null;
            throw err;
          }
          return body;
        });
      }, function (e) {
        var err = new Error("network");
        err.aborted = ctrl.signal.aborted && !ctrl.timedOut;
        err.offline = true;
        throw err;
      })
      .finally(function () { clearTimeout(to); });
  }

  function errorText(e) {
    if (e.offline) {
      return navigator.onLine === false
        ? "Ești offline — istoricul are nevoie de conexiune."
        : "Serverul nu a răspuns. Încearcă din nou peste puțin timp.";
    }
    if (e.status === 422 || e.status === 404) return e.detail || "Filtre invalide.";
    if (e.status === 429) return "Prea multe cereri — așteaptă câteva secunde.";
    return "Eroare la server (" + (e.status || "?") + "). Încearcă din nou mai târziu.";
  }

  // ---- results ----------------------------------------------------------------------

  function cell(row, label, cls, content) {
    var td = el("td", cls);
    td.dataset.label = label;
    if (typeof content === "string") td.textContent = content;
    else if (content) td.append(content);
    row.append(td);
    return td;
  }

  function delayBadge(d, title) {
    var lvl = delayLevel(d);
    var b = el("span", "delay delay-" + lvl);
    b.append(App.icon(lvl === "ok" ? App.ICONS.ok : lvl === "minor" ? App.ICONS.clock : App.ICONS.alert),
             document.createTextNode(delayText(d)));
    b.title = title;
    return b;
  }

  function renderResults(q, services) {
    var box = $("h-results");
    box.replaceChildren();
    var n = services.length;
    $("h-count").textContent = plural(n, "rezultat", "rezultate") + " · " + dayLabel(q.date) +
      (n ? " · valori observate pe tabela CFR, nu ore reale confirmate" : "");
    var empty = $("h-empty");
    if (!n) {
      empty.textContent = q.date === todayBucharest() && !q.train && !q.station && !q.from && !q.to
        ? "Nu există încă trenuri observate azi."
        : "Nu există trenuri observate pentru aceste filtre.";
      empty.hidden = false;
      return;
    }
    empty.hidden = true;

    var table = el("table", "h-table");
    var cap = el("caption", "sr-only", "Trenuri observate pe " + dayLabel(q.date));
    var thead = el("thead");
    var hr = el("tr");
    ["Ora prog.", "Panou", "Tren", "Stație", "Operator", "Întârziere max. observată",
     "Ultima întârziere observată", "Linia", "Stare"].forEach(function (h) {
      var th = el("th", null, h);
      th.scope = "col";
      hr.append(th);
    });
    thead.append(hr);
    var tbody = el("tbody");
    services.forEach(function (s) {
      var tr = el("tr", "h-row");
      tr.dataset.delay = delayLevel(s.max_delay);
      cell(tr, "Ora programată", "h-time", s.sched_time || "--:--");
      cell(tr, "Panou", "h-board", BOARD_LABEL[s.board] || s.board);
      var train = el("button", "h-train");
      train.type = "button";
      var type = el("span", App.typeClass(s.train_type), s.train_type || "?");
      train.append(type, el("span", "t-no", String(s.train_no)));
      train.setAttribute("aria-label", "Detalii tren " + (s.train_type || "") + " " + s.train_no +
        " (" + (BOARD_LABEL[s.board] || "") + " " + (s.sched_time || "") + ")");
      train.addEventListener("click", function () { openDetail(s, q.date, train); });
      cell(tr, "Tren", "h-trn", train);
      cell(tr, "Stație", "h-station", s.station ? titleCase(s.station) : "—");
      cell(tr, "Operator", "h-op", s.operator || "—");
      cell(tr, "Întârziere max. observată", "h-max",
           delayBadge(s.max_delay, "Cea mai mare întârziere văzută pe tabelă"));
      cell(tr, "Ultima întârziere observată", "h-last",
           delayBadge(s.final_delay, "Ultima întârziere văzută pe tabelă (nu ora reală de sosire/plecare)"));
      var known = s.platform != null && s.platform !== "";
      var plat = el("span", known ? "plat plat-sm" : "plat plat-sm plat-unknown", known ? String(s.platform) : "—");
      plat.setAttribute("aria-label", known ? "Linia " + s.platform : "Linie neanunțată");
      cell(tr, "Linia", "h-plat", plat);
      cell(tr, "Stare", "h-status", STATUS_LABEL[s.status] || s.status || "—");
      tr.addEventListener("click", function (e) {
        if (e.target.closest("button")) return;
        openDetail(s, q.date, train);
      });
      tbody.append(tr);
    });
    table.append(cap, thead, tbody);
    box.append(table);
  }

  function clearResults() {
    $("h-results").replaceChildren();
    $("h-count").textContent = "";
    $("h-empty").hidden = true;
  }

  function setLoading(on) {
    $("h-results").setAttribute("aria-busy", on ? "true" : "false");
    $("view-istoric").classList.toggle("is-loading", on);
  }

  function search(force) {
    var q = readForm();
    syncHash(q);
    var err = validate(q);
    var errBox = $("h-error");
    if (err) {
      errBox.textContent = err;
      errBox.hidden = false;
      clearResults();
      lastQuery = null;
      return;
    }
    var key = toSearch(q, true);
    if (!force && key === lastQuery) return;
    lastQuery = key;
    if (inflight) inflight.abort();
    var ctrl = new AbortController();
    inflight = ctrl;
    var params = new URLSearchParams();
    FIELDS.forEach(function (f) { if (q[f]) params.set(f, q[f]); });
    setLoading(true);
    getJSON("/api/history?" + params.toString(), ctrl)
      .then(function (data) {
        if (inflight !== ctrl) return;
        errBox.hidden = true;
        renderResults(q, Array.isArray(data && data.services) ? data.services : []);
      })
      .catch(function (e) {
        if (inflight !== ctrl || e.aborted) return;
        lastQuery = null; // allow retry with the same filters
        clearResults();
        errBox.textContent = errorText(e);
        errBox.hidden = false;
      })
      .then(function () {
        if (inflight === ctrl) {
          inflight = null;
          setLoading(false);
        }
      });
  }

  function debounced() {
    clearTimeout(timer);
    timer = setTimeout(function () { search(false); }, DEBOUNCE_MS);
  }

  // ---- detail: timeline + chart -------------------------------------------------------

  function svg(tag, attrs, text) {
    var n = document.createElementNS(SVG_NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, String(attrs[k])); });
    if (text != null) n.textContent = text;
    return n;
  }

  function toInt(v) {
    if (v == null || v === "") return null;
    var n = parseInt(v, 10);
    return isNaN(n) ? null : n;
  }

  // Step series of observed delays for one service: [{t: ms, d: minutes}]
  function delaySeries(events, service) {
    var pts = [];
    var mine = events.filter(function (e) {
      return e.board === service.board && e.sched_time === service.sched_time;
    });
    var firstDelay = null;
    mine.forEach(function (e) { if (e.kind === "delay" && firstDelay == null) firstDelay = e; });
    var start = firstDelay ? toInt(firstDelay.old) : service.final_delay;
    var current = start;
    mine.forEach(function (e) {
      var t = new Date(e.ts).getTime();
      if (isNaN(t)) return;
      if (e.kind === "appeared" && current != null) pts.push({ t: t, d: current });
      else if (e.kind === "delay") {
        var nv = toInt(e.new);
        if (nv == null) return;
        if (current != null && !pts.length) pts.push({ t: t, d: current });
        pts.push({ t: t, d: nv, change: true });
        current = nv;
      } else if (e.kind === "gone" && current != null) pts.push({ t: t, d: current, end: true });
    });
    if (pts.length && service.last_seen) {
      var ls = new Date(service.last_seen).getTime();
      if (!isNaN(ls) && ls > pts[pts.length - 1].t) pts.push({ t: ls, d: current, end: true });
    }
    return pts;
  }

  // Y axis: integer tick step (1, 2, 5, 10, 15, 30, 60…) with at most 5 intervals.
  function yScale(v) {
    var steps = [1, 2, 5, 10, 15, 30, 60, 120, 240];
    var step = steps[steps.length - 1];
    for (var i = 0; i < steps.length; i++) {
      if (Math.max(v, 1) / steps[i] <= 5) { step = steps[i]; break; }
    }
    return { step: step, max: Math.max(step, Math.ceil(v / step) * step) };
  }

  function titleCase(s) {
    return String(s || "").toLowerCase().replace(/(^|[\s\-.])(\S)/g, function (m, a, b) {
      return a + b.toUpperCase();
    });
  }

  function buildChart(pts) {
    // viewBox in CSS pixels of the dialog so labels keep a readable size on phones
    var box = $("h-detail-body");
    var W = Math.max(300, Math.min(680, (box && box.clientWidth) || 640));
    var H = W < 480 ? 200 : 230, L = 40, R = 16, T = 24, B = 30;
    var t0 = pts[0].t, t1 = pts[pts.length - 1].t;
    if (t1 - t0 < 60000) { t0 -= 300000; t1 += 300000; }
    var ys = yScale(Math.max.apply(null, pts.map(function (p) { return p.d; }).concat([0])));
    var maxD = ys.max;
    var x = function (t) { return L + (t - t0) / (t1 - t0) * (W - L - R); };
    var y = function (d) { return T + (1 - Math.max(0, d) / maxD) * (H - T - B); };

    var root = svg("svg", { viewBox: "0 0 " + W + " " + H, class: "chart", role: "img",
                            "aria-labelledby": "h-chart-title h-chart-desc", preserveAspectRatio: "xMidYMid meet" });
    root.append(svg("title", { id: "h-chart-title" }, "Întârzierea observată în timp"));
    var changes = pts.filter(function (p) { return p.change; }).length;
    root.append(svg("desc", { id: "h-chart-desc" },
      "Axa orizontală: ora citirii tabelei. Axa verticală: întârzierea afișată, în minute. " +
      plural(changes, "schimbare observată", "schimbări observate") + "."));

    var grid = svg("g", { class: "chart-grid" });
    for (var dv = 0; dv <= maxD; dv += ys.step) {
      var yy = y(dv);
      grid.append(svg("line", { x1: L, x2: W - R, y1: yy, y2: yy }));
      grid.append(svg("text", { x: L - 8, y: yy + 4, class: "chart-ylabel" }, String(dv)));
    }
    var ticks = W < 480 ? 3 : 4;
    for (var j = 0; j <= ticks; j++) {
      var tt = t0 + (t1 - t0) * j / ticks;
      var cls = "chart-xlabel" + (j === 0 ? " chart-xstart" : j === ticks ? " chart-xend" : "");
      grid.append(svg("text", { x: x(tt), y: H - 10, class: cls }, localTime(tt, true)));
    }
    grid.append(svg("text", { x: L - 8, y: 12, class: "chart-ylabel chart-unit" }, "min"));
    root.append(grid);

    var d = "";
    pts.forEach(function (p, k) {
      if (k === 0) d = "M" + x(p.t).toFixed(1) + " " + y(p.d).toFixed(1);
      else {
        d += " H" + x(p.t).toFixed(1) + " V" + y(p.d).toFixed(1); // step: value holds until changed
      }
    });
    root.append(svg("path", { d: d, class: "chart-line" }));
    pts.forEach(function (p) {
      if (!p.change) return;
      var c = svg("circle", { cx: x(p.t).toFixed(1), cy: y(p.d).toFixed(1), r: 4, class: "chart-dot" });
      c.append(svg("title", {}, localTime(p.t, true) + ": " + delayText(p.d)));
      root.append(c);
    });
    return root;
  }

  function eventText(e) {
    var o = e.old, n = e.new;
    switch (e.kind) {
      case "delay": return "Întârziere: " + delayText(toInt(o)) + " → " + delayText(toInt(n));
      case "platform": return "Linie: " + (o || "neanunțată") + " → " + (n || "neanunțată");
      case "appeared": return "Apare pe tabelă";
      case "gone": return "Dispare de pe tabelă";
      default: return e.kind;
    }
  }

  function renderDetail(service, day, events) {
    var body = $("h-detail-body");
    body.replaceChildren();
    var pts = delaySeries(events, service);
    var chartBox = el("section", "detail-block");
    chartBox.append(el("h3", "detail-h", "Întârzierea observată în timp"));
    if (pts.length >= 2) {
      chartBox.append(buildChart(pts));
      var nChanges = pts.filter(function (p) { return p.change; }).length;
      chartBox.append(el("p", "detail-note",
        plural(nChanges, "schimbare de întârziere observată", "schimbări de întârziere observate") +
        ". Axa X: ora citirii tabelei (ora României). Axa Y: întârzierea afișată, în minute. " +
        "Valori observate, nu ora reală de sosire/plecare."));
    } else {
      chartBox.append(el("p", "detail-note", "Prea puține observații pentru grafic."));
    }
    body.append(chartBox);

    var tl = el("section", "detail-block");
    tl.append(el("h3", "detail-h", "Evenimente (" + events.length + ")"));
    if (!events.length) {
      tl.append(el("p", "detail-note", "Nu există evenimente înregistrate pentru acest tren în ziua aleasă."));
    } else {
      var ol = el("ol", "timeline");
      events.forEach(function (e) {
        var li = el("li", "tl-item tl-" + e.kind);
        var time = el("time", "tl-time", localTime(e.ts));
        time.dateTime = e.ts;
        var txt = el("span", "tl-text", eventText(e));
        var meta = el("span", "tl-meta", (BOARD_LABEL[e.board] || e.board || "") +
          (e.sched_time ? " " + e.sched_time : "") + (e.station ? " · " + titleCase(e.station) : ""));
        li.append(time, txt, meta);
        ol.append(li);
      });
      tl.append(ol);
    }
    body.append(tl);
  }

  function openDetail(service, day, opener) {
    var dlg = $("h-detail");
    lastFocus = opener || null;
    $("h-detail-title").textContent = (service.train_type || "Tren") + " " + service.train_no;
    $("h-detail-sub").textContent = (BOARD_LABEL[service.board] || "") + " " + (service.sched_time || "") +
      (service.station ? " · " + titleCase(service.station) : "") + " · " + dayLabel(day);
    var body = $("h-detail-body");
    body.replaceChildren(el("p", "detail-note", "Se încarcă evenimentele…"));
    if (typeof dlg.showModal === "function") { if (!dlg.open) dlg.showModal(); } else dlg.setAttribute("open", "");
    if (detailCtrl) detailCtrl.abort();
    var ctrl = new AbortController();
    detailCtrl = ctrl;
    getJSON("/api/train/" + encodeURIComponent(service.train_no) + "?date=" + encodeURIComponent(day), ctrl)
      .then(function (data) {
        if (detailCtrl !== ctrl) return;
        renderDetail(service, day, Array.isArray(data && data.events) ? data.events : []);
      })
      .catch(function (e) {
        if (detailCtrl !== ctrl || e.aborted) return;
        body.replaceChildren(el("p", "notice notice-error", errorText(e)));
      });
  }

  function closeDetail() {
    var dlg = $("h-detail");
    if (detailCtrl) { detailCtrl.abort(); detailCtrl = null; }
    if (typeof dlg.close === "function" && dlg.open) dlg.close();
    else dlg.removeAttribute("open");
  }

  // ---- view lifecycle ----------------------------------------------------------------

  function show(params) {
    if (lastQuery !== null && !Array.from(params.keys()).length) {
      // bare #istoric (nav link): keep the current filters, restore them in the URL
      syncHash(readForm());
      return;
    }
    var q = queryFromParams(params);
    var cur = readForm();
    var changed = FIELDS.some(function (f) { return (cur[f] || "") !== (q[f] || ""); });
    if (changed) writeForm(q);
    inputs.date.max = todayBucharest();
    search(false);
  }

  function init() {
    form = $("h-form");
    if (!form) return;
    FIELDS.forEach(function (f) { inputs[f] = $("h-" + f); });
    inputs.date.value = todayBucharest();
    inputs.date.max = todayBucharest();
    form.addEventListener("submit", function (e) { e.preventDefault(); clearTimeout(timer); search(true); });
    form.addEventListener("input", function (e) {
      if (e.target === inputs.train) {
        var digits = inputs.train.value.replace(/\D+/g, "").slice(0, 6);
        if (digits !== inputs.train.value) inputs.train.value = digits;
      }
      debounced();
    });
    form.addEventListener("change", debounced);
    form.addEventListener("reset", function () {
      setTimeout(function () {
        inputs.date.value = todayBucharest();
        clearTimeout(timer);
        search(true);
      }, 0);
    });
    var dlg = $("h-detail");
    $("h-detail-close").addEventListener("click", closeDetail);
    dlg.addEventListener("click", function (e) { if (e.target === dlg) closeDetail(); }); // backdrop
    dlg.addEventListener("close", function () {
      if (detailCtrl) { detailCtrl.abort(); detailCtrl = null; }
      if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
    });
  }

  App.views.istoric = { show: show };
  App.history = { delaySeries: delaySeries, todayBucharest: todayBucharest, plural: plural };
  init();
})();
