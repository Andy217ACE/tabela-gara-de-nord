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
        // /api/history returns at most 500 rows and flags the cut with X-Truncated: 1
        ctrl.truncated = r.headers.get("X-Truncated") === "1";
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

  // `known === false`: the delay cell was never read for this journey → „necitit”,
  // never „la timp” (a missing value is not 0).
  function delayBadge(d, title, known) {
    if (known === false) {
      var u = el("span", "delay delay-unread");
      u.append(App.icon(App.ICONS.clock), document.createTextNode("necitit"));
      u.title = "Întârzierea nu a fost citită de pe tabela CFR pentru această călătorie";
      return u;
    }
    var lvl = delayLevel(d);
    var b = el("span", "delay delay-" + lvl);
    b.append(App.icon(lvl === "ok" ? App.ICONS.ok : lvl === "minor" ? App.ICONS.clock : App.ICONS.alert),
             document.createTextNode(delayText(d)));
    b.title = title;
    return b;
  }

  var TRUNCATED_TEXT = "primele 500 — restrânge filtrele (oră/stație/tren)";

  function renderResults(q, services, truncated) {
    var box = $("h-results");
    box.replaceChildren();
    var n = services.length;
    var count = $("h-count");
    count.textContent = plural(n, "rezultat", "rezultate") + " · " + dayLabel(q.date) +
      (n ? " · valori observate pe tabela CFR, nu ore reale confirmate" : "");
    if (truncated) {
      count.append(" · ", el("strong", "h-truncated", TRUNCATED_TEXT));
    }
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
      var known = s.delay_known !== false;
      tr.dataset.delay = known ? delayLevel(s.max_delay) : "unread";
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
      cell(tr, "Stație", "h-station", s.station ? nameNode(titleCase(s.station), s) : "—");
      cell(tr, "Operator", "h-op", s.operator ? nameNode(s.operator, s) : "—");
      cell(tr, "Întârziere max. observată", "h-max",
           delayBadge(s.max_delay, "Cea mai mare întârziere văzută pe tabelă", known));
      cell(tr, "Ultima întârziere observată", "h-last",
           delayBadge(s.final_delay, "Ultima întârziere văzută pe tabelă (nu ora reală de sosire/plecare)",
                      known));
      var hasPlat = s.platform != null && s.platform !== "";
      var plat = el("span", hasPlat ? "plat plat-sm" : "plat plat-sm plat-unknown",
                    hasPlat ? String(s.platform) : "—");
      plat.setAttribute("aria-label", hasPlat ? "Linia " + s.platform : "Linie neanunțată");
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

  // canonical name from an uncertain OCR match (API field `uncertain`): dotted underline
  function nameNode(text, s) {
    if (s.uncertain !== true) return text;
    var n = el("span", "is-uncertain", text);
    n.title = "citire nesigură";
    n.append(el("span", "sr-only", " (citire nesigură)"));
    return n;
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
        renderResults(q, Array.isArray(data && data.services) ? data.services : [], !!ctrl.truncated);
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

  // Points of /api/journeys/{id} `delay_series` (real readings only, never an unread
  // frame) + a final marker at the observed disappearance. A reading repeated by two
  // sources a few seconds apart (observation + event) is drawn once.
  function readingSeries(series, result) {
    var pts = [];
    (series || []).forEach(function (r) {
      var t = new Date(r.t).getTime();
      var d = typeof r.delay === "number" ? r.delay : null;
      if (isNaN(t) || d == null) return;
      var prev = pts[pts.length - 1];
      if (prev && prev.d === d && Math.abs(t - prev.t) < 5000) return;
      pts.push({ t: t, d: d, dot: true });
    });
    pts.sort(function (a, b) { return a.t - b.t; });
    var gone = result && result.disappeared_at ? new Date(result.disappeared_at).getTime() : NaN;
    if (pts.length && !isNaN(gone)) {
      pts.push({ t: Math.max(gone, pts[pts.length - 1].t), d: pts[pts.length - 1].d, gone: true });
    }
    return pts;
  }

  function buildChart(pts, readings) {
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
      (readings != null ? plural(readings, "citire reală", "citiri reale")
        : plural(changes, "schimbare observată", "schimbări observate")) + "."));

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
      if (!p.gone) return;
      // observed disappearance from the board: vertical marker
      var gx = x(p.t).toFixed(1);
      root.append(svg("line", { x1: gx, x2: gx, y1: T - 8, y2: H - B, class: "chart-gone" }));
      var nearEnd = x(p.t) > W - R - 30;
      var lbl = svg("text", { x: nearEnd ? x(p.t) - 4 : gx, y: T - 12,
                              class: "chart-gone-label" + (nearEnd ? " chart-xend" : "") }, "dispărut");
      lbl.append(svg("title", {}, "Dispărut de pe tabelă la " + localTime(p.t, true)));
      root.append(lbl);
    });
    pts.forEach(function (p) {
      if (!p.change && !p.dot) return;
      var c = svg("circle", { cx: x(p.t).toFixed(1), cy: y(p.d).toFixed(1), r: p.dot ? 3 : 4,
                              class: "chart-dot" });
      c.append(svg("title", {}, localTime(p.t, true) + ": " + delayText(p.d) +
        (p.dot ? " (citit)" : "")));
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

  // ---- journey (/api/journeys/{id}): final result + real delay readings ---------------

  var STATE_CLASS = { confirmed: "res-confirmed", unconfirmed: "res-unconfirmed",
                      unknown: "res-unknown", in_progress: "res-progress" };
  var STATE_SHORT = { confirmed: "confirmat", unconfirmed: "neconfirmat", unknown: "necunoscut",
                      in_progress: "în desfășurare" };

  function minText(d) {
    if (d == null) return "—";
    return d <= 0 ? "0 min" : "+" + d + " min";
  }

  function resultBadge(r) {
    var st = r && STATE_CLASS[r.state] ? r.state : "unknown";
    var b = el("span", "res-badge " + STATE_CLASS[st], STATE_SHORT[st]);
    b.title = (r && r.label) || "";
    return b;
  }

  function factRow(dl, label, value, note) {
    var dt = el("dt", null, label);
    var dd = el("dd");
    if (typeof value === "string") dd.textContent = value;
    else dd.append(value);
    if (note) dd.append(el("span", "res-fact-note", " " + note));
    dl.append(dt, dd);
  }

  function renderResult(j) {
    var r = j.result || {};
    var box = el("section", "detail-block res");
    box.dataset.state = r.state || "unknown";
    box.append(el("h3", "detail-h", "Rezultat"));
    var head = el("p", "res-head");
    head.append(resultBadge(r), el("span", "res-label", r.label || "Rezultat necunoscut"));
    box.append(head);
    if (r.reason) box.append(el("p", "res-reason", r.reason));

    var dl = el("dl", "res-facts");
    if (r.state === "confirmed") {
      factRow(dl, "Întârziere finală", minText(r.final_delay), "(citită pe tabela de la București Nord)");
    } else if (r.delay_known) {
      factRow(dl, "Ultima întârziere citită", minText(r.observed_delay),
              r.delay_read_at ? "(la " + localTime(r.delay_read_at, true) + ")" : "");
    } else {
      factRow(dl, "Întârziere", "necunoscută", "(nu a fost citită niciodată pentru această călătorie)");
    }
    factRow(dl, "Ora programată", r.sched_at ? localTime(r.sched_at, true) : (j.sched_time || "—"));
    factRow(dl, "Ora estimată", r.estimated_at ? localTime(r.estimated_at, true) : "necunoscută",
            r.estimated_at ? "(programat + întârzierea citită)" : "");
    factRow(dl, "Dispărut de pe tabelă", r.disappeared_at ? localTime(r.disappeared_at, true)
      : r.state === "in_progress" ? "încă pe tabelă" : "neobservat");
    factRow(dl, "Data de serviciu", j.service_date ? dayLabel(j.service_date) : "necunoscută");
    box.append(dl);
    box.append(el("p", "detail-note",
      "Data de serviciu = ziua orei programate (un tren de 00:05 citit pe tabelă la 23:58 aparține " +
      "zilei următoare). Întârzierea este cea CITITĂ pe tabela de la București Nord, nu ora reală " +
      "de sosire/plecare. „Confirmat” = dispariția de pe tabelă a fost observată după ora estimată, " +
      "iar întârzierea a fost citită cu cel mult " + (j.final_read_max_gap_min || 15) +
      " min înainte."));
    var link = el("a", "res-train-link", "Profilul trenului " + (j.train_type ? j.train_type + " " : "") +
                  j.train_no + " →");
    link.href = "#tren?nr=" + encodeURIComponent(j.train_no);
    link.addEventListener("click", closeDetail);
    box.append(link);
    return box;
  }

  function journeyEventText(e) {
    if (e.kind === "delay") {
      var n = toInt(e.new);
      return n == null ? "Întârziere: necitită" : "Întârziere citită: " + minText(n);
    }
    return eventText(e);
  }

  function renderJourney(j) {
    var body = $("h-detail-body");
    body.replaceChildren();
    body.append(renderResult(j));

    var pts = readingSeries(j.delay_series, j.result);
    var readings = pts.filter(function (p) { return p.dot; }).length;
    var chartBox = el("section", "detail-block");
    chartBox.append(el("h3", "detail-h", "Întârzierea citită în timp"));
    if (readings >= 1) {
      chartBox.append(buildChart(pts, readings));
      chartBox.append(el("p", "detail-note",
        plural(readings, "citire reală a întârzierii", "citiri reale ale întârzierii") +
        " (puncte); între citiri linia păstrează ultima valoare citită" +
        (pts.some(function (p) { return p.gone; }) ? "; marcajul vertical = dispariția de pe tabelă" : "") +
        ". Axa X: ora citirii (ora României). Axa Y: întârzierea, în minute."));
    } else {
      chartBox.append(el("p", "detail-note",
        "Nicio citire a întârzierii pentru această călătorie — nu desenăm un grafic din valori necitite."));
    }
    body.append(chartBox);

    var events = Array.isArray(j.events) ? j.events : [];
    var tl = el("section", "detail-block");
    tl.append(el("h3", "detail-h", "Evenimente (" + events.length + ")"));
    if (!events.length) {
      tl.append(el("p", "detail-note", "Nu există evenimente înregistrate pentru această călătorie."));
    } else {
      var ol = el("ol", "timeline");
      events.forEach(function (e) {
        var li = el("li", "tl-item tl-" + e.kind);
        var time = el("time", "tl-time", localTime(e.ts));
        time.dateTime = e.ts;
        li.append(time, el("span", "tl-text", journeyEventText(e)));
        ol.append(li);
      });
      tl.append(ol);
    }
    body.append(tl);
  }

  function journeyHead(j) {
    $("h-detail-title").textContent = (j.train_type || "Tren") + " " + j.train_no;
    $("h-detail-sub").textContent = (BOARD_LABEL[j.board] || "") + " " + (j.sched_time || "") +
      (j.station ? " · " + titleCase(j.station) : "") +
      (j.service_date ? " · " + dayLabel(j.service_date) : "");
  }

  function showDialog() {
    var dlg = $("h-detail");
    if (typeof dlg.showModal === "function") { if (!dlg.open) dlg.showModal(); } else dlg.setAttribute("open", "");
  }

  // Public: open one journey by id (also used by the train profile, stats.js).
  function openJourney(id, opener, hint) {
    lastFocus = opener || null;
    if (hint) journeyHead(hint);
    else { $("h-detail-title").textContent = "Călătorie"; $("h-detail-sub").textContent = ""; }
    var body = $("h-detail-body");
    body.replaceChildren(el("p", "detail-note", "Se încarcă rezultatul călătoriei…"));
    showDialog();
    if (detailCtrl) detailCtrl.abort();
    var ctrl = new AbortController();
    detailCtrl = ctrl;
    getJSON("/api/journeys/" + encodeURIComponent(id), ctrl)
      .then(function (data) {
        if (detailCtrl !== ctrl) return;
        if (!data || typeof data !== "object") throw new Error("răspuns invalid");
        journeyHead(data);
        renderJourney(data);
      })
      .catch(function (e) {
        if (detailCtrl !== ctrl || e.aborted) return;
        body.replaceChildren(el("p", "notice notice-error",
          e.status === 404 ? "Călătoria nu mai există." : errorText(e)));
      });
  }

  function openDetail(service, day, opener) {
    if (service.id != null) {
      openJourney(service.id, opener, { train_type: service.train_type, train_no: service.train_no,
        board: service.board, sched_time: service.sched_time, station: service.station,
        service_date: day });
      return;
    }
    // older API without `id`: the day's events for this train number
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
    // the dialog is shared with other views (#tren): keep it outside the hidden #view-istoric
    document.body.appendChild(dlg);
    // navigating (link, back button) must not leave the modal over another view
    window.addEventListener("hashchange", function () { if (dlg.open) closeDetail(); });
    $("h-detail-close").addEventListener("click", closeDetail);
    dlg.addEventListener("click", function (e) { if (e.target === dlg) closeDetail(); }); // backdrop
    dlg.addEventListener("close", function () {
      if (detailCtrl) { detailCtrl.abort(); detailCtrl = null; }
      if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
    });
  }

  App.views.istoric = { show: show };
  App.history = { delaySeries: delaySeries, readingSeries: readingSeries, todayBucharest: todayBucharest,
                  plural: plural, openJourney: openJourney, resultBadge: resultBadge,
                  titleCase: titleCase, dayLabel: dayLabel, localTime: localTime };
  init();
})();
