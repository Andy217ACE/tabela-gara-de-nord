// © 2026 Andy217Ace
// Tabela Gara de Nord — Istoric: every journey the CFR board showed, from ALL days by
// default (newest first, grouped by day, 200 per page + „Încarcă mai multe”); a day, a
// train number, a station, a time range and the board narrow it, in any combination.
// No day picked = all days (the day field stays empty; „Toate zilele” clears it). State
// lives in the URL hash so a search can be shared: #istoric (all days),
// #istoric?date=… (one day), #istoric?train=…&station=… (all days of those filters).
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
  var I = window.I18N;
  function T(k, p) { return I ? I.t(k, p) : k; }
  // plural by Intl.PluralRules(lang): base.one | base.few (ro: 0, 2-19) | base.other
  function tp(base, n) {
    var cat = "other";
    try { cat = new Intl.PluralRules(I ? I.lang() : "ro").select(n); } catch (e) { /* ignore */ }
    return T(base + "." + (cat === "one" || cat === "few" ? cat : "other"), { n: n });
  }
  function boardLabel(b) { return b === "arrival" ? T("history.arrival") : b === "departure" ? T("history.departure") : ""; }

  var $ = function (id) { return document.getElementById(id); };
  var form, inputs = {}, timer = null, inflight = null, detailCtrl = null, lastQuery = null;
  var lastFocus = null, allBtn = null, lastJourney = null;
  var PAGE = 200;                 // journeys per page (server max 200)
  var allState = null;            // {q, next, groups: {day: tbody}, shown, ctrl}

  // ---- time helpers ------------------------------------------------------------

  function todayBucharest() {
    // en-CA formats as YYYY-MM-DD
    return new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit",
                                              day: "2-digit" }).format(new Date());
  }

  var timeFmt, shortTimeFmt, dayFmt, shortDayFmt, numFmt;
  function buildFmts() {
    var L = I && I.lang() === "en" ? "en-GB" : "ro-RO";
    timeFmt = new Intl.DateTimeFormat(L, { timeZone: TZ, hour: "2-digit", minute: "2-digit",
                                           second: "2-digit", hour12: false });
    shortTimeFmt = new Intl.DateTimeFormat(L, { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false });
    dayFmt = new Intl.DateTimeFormat(L, { timeZone: "UTC", weekday: "long", day: "numeric",
                                          month: "long", year: "numeric" });
    shortDayFmt = new Intl.DateTimeFormat(L, { timeZone: "UTC", day: "2-digit", month: "2-digit", year: "numeric" });
    numFmt = new Intl.NumberFormat(L, { maximumFractionDigits: 1 });
  }
  buildFmts();

  function localTime(ts, short) {
    var d = new Date(ts);
    if (isNaN(d.getTime())) return ts || "";
    return (short ? shortTimeFmt : timeFmt).format(d);
  }

  function dayLabel(iso) {
    var d = new Date(iso + "T12:00:00Z");
    return isNaN(d.getTime()) ? iso : dayFmt.format(d);
  }

  // Public helper kept for other views (the caller passes the words in).
  function plural(n, one, many) {
    // Romanian: 1 rezultat, 2–19 rezultate, 20+ „de rezultate” (except …01–…19)
    if (n === 1) return "1 " + one;
    var tail = n % 100;
    return n + (n === 0 || (tail >= 1 && tail <= 19) ? " " : " de ") + many;
  }

  function delayText(d) {
    if (d == null) return "—";
    d = d | 0;
    return d <= 0 ? T("history.delay.on_time") : "+" + d + " min";
  }

  function delayLevel(d) {
    if (!d || d <= 0) return "ok";
    return d <= 15 ? "minor" : "major";
  }

  // ---- URL state -----------------------------------------------------------------

  // q.date === "" means ALL days (the default — never pre-filled with today).
  function readForm() {
    var q = {};
    FIELDS.forEach(function (f) { q[f] = (inputs[f].value || "").trim(); });
    return q;
  }

  function writeForm(q) {
    FIELDS.forEach(function (f) { inputs[f].value = q[f] || ""; });
    syncScope();
  }

  // „Toate zilele” is pressed while no day is picked; pressing it clears the day.
  function syncScope() {
    allBtn.setAttribute("aria-pressed", inputs.date.value ? "false" : "true");
  }

  function queryFromParams(params) {
    var q = {};
    FIELDS.forEach(function (f) { q[f] = (params.get(f) || "").trim(); });
    if (q.board !== "arrival" && q.board !== "departure") q.board = "";
    return q;
  }

  function toSearch(q) {
    var p = new URLSearchParams();
    FIELDS.forEach(function (f) { if (q[f]) p.set(f, q[f]); });
    return p.toString();
  }

  function syncHash(q) {
    var s = toSearch(q);
    var hash = "#istoric" + (s ? "?" + s : "");
    if (location.hash !== hash) history.replaceState(null, "", hash);
  }

  // ---- validation (mirrors the API; the API stays the authority) ----------------------

  function validate(q) {
    if (q.date) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(q.date)) return T("history.err.bad_day");
      if (q.date > todayBucharest()) {
        return T("history.err.future");
      }
    }
    if (q.train && !/^\d{1,6}$/.test(q.train)) return T("history.err.train_digits");
    if (q.from && q.to && q.from > q.to) return T("history.err.time_order");
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
        ? T("history.err.offline")
        : T("history.err.no_response");
    }
    if (e.status === 422 || e.status === 404) return e.detail || T("history.err.invalid_filters");
    if (e.status === 429) return T("history.err.rate_limit");
    return T("history.err.server", { status: e.status || "?" });
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
      u.append(App.icon(App.ICONS.clock), document.createTextNode(T("history.delay.unread")));
      u.title = T("history.delay.unread_title");
      return u;
    }
    var lvl = delayLevel(d);
    var b = el("span", "delay delay-" + lvl);
    b.append(App.icon(lvl === "ok" ? App.ICONS.ok : lvl === "minor" ? App.ICONS.clock : App.ICONS.alert),
             document.createTextNode(delayText(d)));
    b.title = title;
    return b;
  }

  // station name → its page (#statie?nume=<canonical>, web/stats.js); `content` = text or node
  function stationLink(name, content) {
    var a = el("a", "station-link");
    a.href = "#statie?nume=" + encodeURIComponent(name);
    a.append(content == null ? titleCase(name) : content);
    return a;
  }

  // canonical name from an uncertain OCR match (API field `uncertain`): dotted underline
  function nameNode(text, s) {
    if (s.uncertain !== true) return text;
    var n = el("span", "is-uncertain", text);
    n.title = T("history.uncertain");
    n.append(el("span", "sr-only", " (" + T("history.uncertain") + ")"));
    return n;
  }

  function clearResults() {
    $("h-results").replaceChildren();
    $("h-count").textContent = "";
    $("h-empty").hidden = true;
    $("h-summary").replaceChildren();
    $("h-summary").hidden = true;
    $("h-more").hidden = true;
    if (allState && allState.ctrl) allState.ctrl.abort();
    allState = null;
  }

  // ---- journeys, all days or one (/api/history?all=1[&train=N][&date=…]) ----------------

  function shortDay(iso) {
    var d = new Date(iso + "T12:00:00Z");
    return isNaN(d.getTime()) ? iso : shortDayFmt.format(d);
  }

  function minSigned(v) {
    return v == null ? "—" : (v === 0 ? "0" : (v > 0 ? "+" : "") + numFmt.format(v)) + " min";
  }

  function allParams(q, cursor) {
    var p = new URLSearchParams();
    p.set("all", "1");
    ["train", "date", "station", "from", "to", "board"].forEach(function (f) { if (q[f]) p.set(f, q[f]); });
    p.set("limit", String(PAGE));
    if (cursor) p.set("cursor", cursor);
    return p.toString();
  }

  // One line per board: N (journeys with a READ delay), mean/median/max; % only from the
  // minimum sample on (the server withholds it below, `sufficient`).
  function summaryLine(board, s, params) {
    var p = el("p", "h-sum-line");
    p.append(el("strong", "h-sum-board", board === "arrival" ? T("history.board_arrivals") : T("history.board_departures")), " — ");
    if (!s || !s.n) {
      p.append(T("history.sum.none_read"));
      return p;
    }
    var parts = [T("history.sum.n_read", { n: s.n }), T("history.sum.mean", { v: minSigned(s.mean) }),
                 T("history.sum.median", { v: minSigned(s.median) }), T("history.sum.max", { v: minSigned(s.max) })];
    if (s.sufficient && s.on_time_pct != null) {
      parts.push(T("history.sum.on_time_pct", { max: params.on_time_max_min, pct: numFmt.format(s.on_time_pct) }));
    } else {
      parts.push(T("history.sum.no_pct", { min: params.min_sample }));
    }
    p.append(parts.join(" · "));
    return p;
  }

  // Beta 1.26: the headline figures as a hero strip (count-up numbers), above the exact lines
  function summaryHero(data, sum, params) {
    var U = window.TabelaApp.ui2;
    if (!U) return null;
    var per = data.period || {};
    var items = [{ label: T("history.sum.journeys_in_list"), value: data.total,
                   sub: per.days ? tp("history.sum.days", per.days) : T("history.sum.one_day") }];
    ["arrival", "departure"].forEach(function (b) {
      var s = sum[b];
      var ok = s && s.n && s.sufficient && s.on_time_pct != null;
      items.push({ label: (b === "arrival" ? T("history.board_arrivals") : T("history.board_departures")) + " · " + T("history.delay.on_time"), tone: b === "arrival" ? "arr" : "dep",
        value: ok ? s.on_time_pct : null, unit: ok ? " %" : "",
        fmt: function (x) { return numFmt.format(Math.round(x * 10) / 10); },
        sub: s && s.n ? (ok ? T("history.sum.n_read", { n: s.n }) : T("history.sum.n_below", { n: s.n, min: params.min_sample })) : "N = 0",
        meter: ok ? s.on_time_pct : null });
    });
    return U.hero(items);
  }

  function renderSummary(data) {
    var box = $("h-summary");
    box.replaceChildren();
    if (!data.total) { box.hidden = true; return; }
    var params = data.params || {};
    var sum = data.summary || {};
    var hero = summaryHero(data, sum, params);
    if (hero) box.append(hero);
    ["arrival", "departure"].forEach(function (b) {
      if (sum[b]) box.append(summaryLine(b, sum[b], params));
    });
    var st = (data.quality && data.quality.states) || {};
    var states = ["confirmed", "unconfirmed", "unknown", "in_progress"].filter(function (k) { return st[k]; })
      .map(function (k) { return stateShort(k) + ": " + st[k]; });
    if (states.length) box.append(el("p", "h-sum-states", T("history.sum.states", { states: states.join(" · ") })));
    if (data.low_quality_excluded) {
      box.append(el("p", "h-sum-note", T("history.sum.low_quality_note",
        { count: tp("history.journeys", data.low_quality_excluded) })));
    }
    box.append(el("p", "h-sum-note", T("history.sum.note",
      { mode: params.confirmed_only ? T("history.sum.confirmed_only") : T("history.sum.confirmed_and_not") })));
    box.hidden = false;
  }

  function allCount(q, data) {
    var count = $("h-count");
    var per = data.period || {};
    var text = (q.train ? T("history.count.train", { no: q.train }) + " " : "") + tp("history.journeys", data.total);
    if (q.date) text += " · " + dayLabel(q.date);
    else if (per.first) {
      text += " " + T("history.count.period", { first: shortDay(per.first), last: shortDay(per.last),
                                                days: tp("history.days", per.days) });
    }
    count.textContent = text;
    if (allState && allState.shown < data.total) {
      count.append(" · ", el("strong", "h-truncated", T("history.count.shown", { n: allState.shown })));
    }
  }

  function journeyDelay(j) {
    var r = j.result || {};
    if (r.state === "confirmed") return delayBadge(r.final_delay, T("history.delay.final_confirmed"), true);
    if (r.delay_known) {
      return delayBadge(r.observed_delay, T("history.delay.last_read_state", { state: stateShort(r.state) }), true);
    }
    return delayBadge(null, "", false);
  }

  function journeyRow(j) {
    var r = j.result || {};
    var tr = el("tr", "h-row");
    var known = j.max_read_delay != null;
    tr.dataset.delay = known ? delayLevel(j.max_read_delay) : "unread";
    cell(tr, T("history.cell.sched_time"), "h-time", j.sched_time || "--:--");
    cell(tr, T("history.field.board"), "h-board", boardLabel(j.board) || j.board);
    var hint = { train_type: j.train_type, train_no: j.train_no, board: j.board, sched_time: j.sched_time,
                 station: j.station, service_date: j.service_date };
    var train = el("button", "h-train");
    train.type = "button";
    train.append(el("span", App.typeClass(j.train_type), App.typeAbbr(j.train_type) || "?"),
                 el("span", "t-no", String(j.train_no)));
    train.setAttribute("aria-label", T("history.row.train_aria", { type: j.train_type || "", no: j.train_no,
      board: boardLabel(j.board), time: j.sched_time || "", day: dayLabel(j.service_date) }));
    train.addEventListener("click", function () { openJourney(j.id, train, hint); });
    cell(tr, T("history.col.train"), "h-trn", train);
    cell(tr, T("history.field.station"), "h-station", j.station ? stationLink(j.station, nameNode(titleCase(j.station), j)) : "—");
    var acts = el("span", "h-acts");
    var g = el("button", "h-act", T("history.row.chart"));
    g.type = "button";
    g.setAttribute("aria-label", T("history.row.chart_aria", { day: dayLabel(j.service_date), time: j.sched_time || "" }));
    g.addEventListener("click", function () { openJourney(j.id, g, hint); });
    var prof = el("a", "h-act", T("history.row.train_profile"));
    prof.href = "#tren?nr=" + encodeURIComponent(j.train_no);
    acts.append(g, prof);
    cell(tr, T("history.col.details"), "h-op", acts);
    cell(tr, T("history.col.max_delay"), "h-max",
         known ? delayBadge(j.max_read_delay, T("history.delay.max_title"), true)
               : delayBadge(null, "", false));
    cell(tr, T("history.col.last_delay"), "h-last", journeyDelay(j));
    var hasPlat = j.platform != null && j.platform !== "";
    var plat = el("span", hasPlat ? "plat plat-sm" : "plat plat-sm plat-unknown", hasPlat ? String(j.platform) : "—");
    plat.setAttribute("aria-label", hasPlat ? T("history.row.platform_aria", { platform: j.platform }) : T("history.row.platform_unannounced"));
    cell(tr, T("history.col.platform"), "h-plat", plat);
    var res = resultBadge(r);
    if (r.reason) res.title = r.reason;
    var resCell = cell(tr, T("history.col.result"), "h-status", res);
    if (j.low_quality === true) {
      var lq = el("span", "lq-badge", T("history.row.low_quality"));
      lq.title = T("history.row.low_quality_title");
      resCell.append(" ", lq);
    }
    tr.addEventListener("click", function (e) {
      if (e.target.closest("button, a")) return;
      openJourney(j.id, train, hint);
    });
    return tr;
  }

  function dayGroup(day) {
    var sec = el("section", "h-group");
    var label = dayLabel(day);
    sec.append(el("h2", "h-group-title", label.charAt(0).toUpperCase() + label.slice(1)));
    var table = el("table", "h-table");
    var thead = el("thead");
    var hr = el("tr");
    [T("history.col.sched_time"), T("history.field.board"), T("history.col.train"), T("history.field.station"),
     T("history.col.details"), T("history.col.max_delay"), T("history.col.last_delay"),
     T("history.col.platform"), T("history.col.result")].forEach(function (h) {
      var th = el("th", null, h);
      th.scope = "col";
      hr.append(th);
    });
    thead.append(hr);
    var tbody = el("tbody");
    table.append(el("caption", "sr-only", T("history.group.caption", { day: dayLabel(day) })), thead, tbody);
    sec.append(table);
    $("h-results").append(sec);
    return tbody;
  }

  function appendJourneys(list) {
    list.forEach(function (j) {
      var tb = allState.groups[j.service_date];
      if (!tb) tb = allState.groups[j.service_date] = dayGroup(j.service_date);
      tb.append(journeyRow(j));
    });
    allState.shown += list.length;
  }

  function renderAll(q, data) {
    clearResults();
    var list = Array.isArray(data.journeys) ? data.journeys : [];
    allState = { q: q, next: data.next || null, groups: {}, shown: 0, ctrl: null };
    if (!data.total) {
      $("h-count").textContent = (q.train ? T("history.count.train", { no: q.train }) + " " : "") +
        tp("history.journeys", 0) + (q.date ? " · " + dayLabel(q.date) : "");
      var empty = $("h-empty");
      var narrowed = q.station || q.from || q.to || q.board || q.date;
      empty.textContent = q.train
        ? (narrowed ? T("history.empty.train_filters") : T("history.empty.train_none", { no: q.train }))
        : (narrowed ? T("history.empty.filters") : T("history.empty.none"));
      empty.hidden = false;
      return;
    }
    renderSummary(data);
    appendJourneys(list);
    var U = window.TabelaApp.ui2;
    if (U) {
      var firstBody = $("h-results").querySelector("tbody");
      if (firstBody) U.stagger(firstBody);
      U.reveal($("h-results"));
    }
    allCount(q, data);
    $("h-more").hidden = !allState.next;
  }

  function loadMore() {
    if (!allState || !allState.next || allState.ctrl) return;
    var st = allState;
    var btn = $("h-more");
    var ctrl = new AbortController();
    st.ctrl = ctrl;
    btn.disabled = true;
    btn.textContent = T("history.loading_more");
    getJSON("/api/history?" + allParams(st.q, st.next), ctrl)
      .then(function (data) {
        if (allState !== st) return;
        appendJourneys(Array.isArray(data && data.journeys) ? data.journeys : []);
        st.next = (data && data.next) || null;
        allCount(st.q, data || {});
        $("h-error").hidden = true;
      })
      .catch(function (e) {
        if (allState !== st || e.aborted) return;
        $("h-error").textContent = errorText(e);
        $("h-error").hidden = false;
      })
      .then(function () {
        if (allState !== st) return;
        st.ctrl = null;
        btn.disabled = false;
        btn.textContent = T("history.more");
        var hadFocus = document.activeElement === btn;
        btn.hidden = !st.next;
        if (hadFocus && btn.hidden) { // last page: keep keyboard focus on the page, not <body>
          var cnt = $("h-count");
          cnt.tabIndex = -1;
          cnt.focus();
        }
      });
  }

  function setLoading(on) {
    var res = $("h-results");
    var U = window.TabelaApp.ui2;
    if (U) {
      var old = res.querySelector(".ui-skel");
      if (on && !res.firstChild) res.append(U.skeleton("table", 6));
      else if (!on && old) old.remove();
    }
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
    var key = toSearch(q);
    if (!force && key === lastQuery) return;
    lastQuery = key;
    if (inflight) inflight.abort();
    var ctrl = new AbortController();
    inflight = ctrl;
    setLoading(true);
    getJSON("/api/history?" + allParams(q), ctrl)
      .then(function (data) {
        if (inflight !== ctrl) return;
        errBox.hidden = true;
        renderAll(q, data || {});
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
    var H = W < 480 ? 200 : 230, L = 40, R = 16, TOP = 24, B = 30;
    var t0 = pts[0].t, t1 = pts[pts.length - 1].t;
    if (t1 - t0 < 60000) { t0 -= 300000; t1 += 300000; }
    var ys = yScale(Math.max.apply(null, pts.map(function (p) { return p.d; }).concat([0])));
    var maxD = ys.max;
    var x = function (t) { return L + (t - t0) / (t1 - t0) * (W - L - R); };
    var y = function (d) { return TOP + (1 - Math.max(0, d) / maxD) * (H - TOP - B); };

    var root = svg("svg", { viewBox: "0 0 " + W + " " + H, class: "chart", role: "img",
                            "aria-labelledby": "h-chart-title h-chart-desc", preserveAspectRatio: "xMidYMid meet" });
    root.append(svg("title", { id: "h-chart-title" }, T("history.chart.title")));
    var changes = pts.filter(function (p) { return p.change; }).length;
    root.append(svg("desc", { id: "h-chart-desc" },
      T("history.chart.desc", { what: readings != null ? tp("history.readings", readings)
        : tp("history.changes", changes) })));

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
    grid.append(svg("text", { x: L - 8, y: 12, class: "chart-ylabel chart-unit" }, T("history.chart.unit")));
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
      root.append(svg("line", { x1: gx, x2: gx, y1: TOP - 8, y2: H - B, class: "chart-gone" }));
      var nearEnd = x(p.t) > W - R - 30;
      var lbl = svg("text", { x: nearEnd ? x(p.t) - 4 : gx, y: TOP - 12,
                              class: "chart-gone-label" + (nearEnd ? " chart-xend" : "") }, T("history.chart.gone"));
      lbl.append(svg("title", {}, T("history.chart.gone_at", { time: localTime(p.t, true) })));
      root.append(lbl);
    });
    pts.forEach(function (p) {
      if (!p.change && !p.dot) return;
      var c = svg("circle", { cx: x(p.t).toFixed(1), cy: y(p.d).toFixed(1), r: p.dot ? 3 : 4,
                              class: "chart-dot" });
      c.append(svg("title", {}, localTime(p.t, true) + ": " + delayText(p.d) +
        (p.dot ? " " + T("history.chart.read") : "")));
      root.append(c);
    });
    return root;
  }

  function eventText(e) {
    var o = e.old, n = e.new;
    switch (e.kind) {
      case "delay": return T("history.event.delay", { from: delayText(toInt(o)), to: delayText(toInt(n)) });
      case "platform": return T("history.event.platform", { from: o || T("history.event.unannounced"),
                                                            to: n || T("history.event.unannounced") });
      case "appeared": return T("history.event.appeared");
      case "gone": return T("history.event.gone");
      default: return e.kind;
    }
  }

  // ---- journey (/api/journeys/{id}): final result + real delay readings ---------------

  var STATE_CLASS = { confirmed: "res-confirmed", unconfirmed: "res-unconfirmed",
                      unknown: "res-unknown", in_progress: "res-progress" };
  function stateShort(k) {
    return T("history.state." + (STATE_CLASS[k] ? k : "unknown"));
  }

  function minText(d) {
    if (d == null) return "—";
    return d <= 0 ? "0 min" : "+" + d + " min";
  }

  function resultBadge(r) {
    var st = r && STATE_CLASS[r.state] ? r.state : "unknown";
    var b = el("span", "res-badge " + STATE_CLASS[st], stateShort(st));
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
    box.append(el("h3", "detail-h", T("history.col.result")));
    var head = el("p", "res-head");
    head.append(resultBadge(r), el("span", "res-label", r.label || T("history.res.unknown")));
    box.append(head);
    if (r.reason) box.append(el("p", "res-reason", r.reason));

    var dl = el("dl", "res-facts");
    if (r.state === "confirmed") {
      factRow(dl, T("history.res.final_delay"), minText(r.final_delay), T("history.res.final_delay_note"));
    } else if (r.delay_known) {
      factRow(dl, T("history.res.last_read"), minText(r.observed_delay),
              r.delay_read_at ? T("history.res.at", { time: localTime(r.delay_read_at, true) }) : "");
    } else {
      factRow(dl, T("history.res.delay"), T("history.res.delay_unknown"), T("history.res.never_read"));
    }
    factRow(dl, T("history.cell.sched_time"), r.sched_at ? localTime(r.sched_at, true) : (j.sched_time || "—"));
    factRow(dl, T("history.res.est_time"), r.estimated_at ? localTime(r.estimated_at, true) : T("history.res.unknown_f"),
            r.estimated_at ? T("history.res.est_note") : "");
    factRow(dl, T("history.res.gone"), r.disappeared_at ? localTime(r.disappeared_at, true)
      : r.state === "in_progress" ? T("history.res.still_on_board") : T("history.res.not_observed"));
    factRow(dl, T("history.res.service_date"), j.service_date ? dayLabel(j.service_date) : T("history.res.unknown_f"));
    box.append(dl);
    box.append(el("p", "detail-note", T("history.res.note", { gap: j.final_read_max_gap_min || 15 })));
    var link = el("a", "res-train-link", T("history.res.train_profile", { train: (j.train_type ? j.train_type + " " : "") +
                  j.train_no }));
    link.href = "#tren?nr=" + encodeURIComponent(j.train_no);
    link.addEventListener("click", closeDetail);
    box.append(link);
    return box;
  }

  function journeyEventText(e) {
    if (e.kind === "delay") {
      var n = toInt(e.new);
      return n == null ? T("history.event.delay_unread") : T("history.event.delay_read", { v: minText(n) });
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
    chartBox.append(el("h3", "detail-h", T("history.chart.heading")));
    if (readings >= 1) {
      chartBox.append(buildChart(pts, readings));
      chartBox.append(el("p", "detail-note",
        tp("history.chart.readings", readings) + " " + T("history.chart.note") +
        (pts.some(function (p) { return p.gone; }) ? T("history.chart.note_gone") : "") +
        T("history.chart.note_axes")));
    } else {
      chartBox.append(el("p", "detail-note",
        T("history.chart.none")));
    }
    body.append(chartBox);

    var events = Array.isArray(j.events) ? j.events : [];
    var tl = el("section", "detail-block");
    tl.append(el("h3", "detail-h", T("history.events", { n: events.length })));
    if (!events.length) {
      tl.append(el("p", "detail-note", T("history.events_none")));
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
    $("h-detail-title").textContent = (j.train_type || T("history.train")) + " " + j.train_no;
    var sub = $("h-detail-sub");
    sub.replaceChildren(boardLabel(j.board) + " " + (j.sched_time || ""));
    if (j.station) {
      var sl = stationLink(j.station);
      sl.addEventListener("click", closeDetail);   // also when the hash does not change
      sub.append(" · ", sl);
    }
    if (j.service_date) sub.append(" · " + dayLabel(j.service_date));
  }

  function showDialog() {
    var dlg = $("h-detail");
    if (typeof dlg.showModal === "function") { if (!dlg.open) dlg.showModal(); } else dlg.setAttribute("open", "");
  }

  // Public: open one journey by id (also used by the train profile, stats.js).
  function openJourney(id, opener, hint) {
    lastFocus = opener || null;
    lastJourney = { id: id, hint: hint };
    if (hint) journeyHead(hint);
    else { $("h-detail-title").textContent = T("history.journey"); $("h-detail-sub").textContent = ""; }
    var body = $("h-detail-body");
    body.replaceChildren(el("p", "detail-note", T("history.loading_journey")));
    showDialog();
    if (detailCtrl) detailCtrl.abort();
    var ctrl = new AbortController();
    detailCtrl = ctrl;
    getJSON("/api/journeys/" + encodeURIComponent(id), ctrl)
      .then(function (data) {
        if (detailCtrl !== ctrl) return;
        if (!data || typeof data !== "object") throw new Error("invalid response");
        journeyHead(data);
        renderJourney(data);
      })
      .catch(function (e) {
        if (detailCtrl !== ctrl || e.aborted) return;
        body.replaceChildren(el("p", "notice notice-error",
          e.status === 404 ? T("history.journey_gone") : errorText(e)));
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
    (I ? I.ready : Promise.resolve()).then(function () { showNow(params); });
  }

  function showNow(params) {
    applyStatic();
    if (lastQuery !== null && !Array.from(params.keys()).length) {
      // bare #istoric (nav link): keep the current filters, restore them in the URL
      syncHash(readForm());
      return;
    }
    var q = queryFromParams(params);
    var cur = readForm();
    var changed = FIELDS.some(function (f) { return (cur[f] || "") !== (q[f] || ""); });
    if (changed) writeForm(q);
    else syncScope();
    inputs.date.max = todayBucharest();
    search(false);
  }

  // Static markup of the view (index.html carries the Romanian source text): set from the dictionary.
  function setText(sel, key) {
    var n = typeof sel === "string" ? document.querySelector(sel) : sel;
    if (n) n.textContent = T(key);
  }
  function fieldLabel(id, key) {
    var n = $(id);
    if (n && n.parentNode) setText(n.parentNode.querySelector(".field-label"), key);
  }
  function applyStatic() {
    if (!$("h-form")) return;
    setText("#istoric-heading", "history.title");
    setText("#view-istoric .page-sub", "history.sub");
    $("h-form").setAttribute("aria-label", T("history.filters"));
    setText("#h-day-label", "history.field.day");
    setText("#h-alldays", "history.all_days");
    setText("#h-day-hint", "history.day_hint");
    fieldLabel("h-train", "history.field.train");
    fieldLabel("h-station", "history.field.station");
    fieldLabel("h-from", "history.field.from");
    fieldLabel("h-to", "history.field.to");
    fieldLabel("h-board", "history.field.board");
    $("h-train").placeholder = T("history.placeholder.train");
    $("h-station").placeholder = T("history.placeholder.station");
    var opts = $("h-board").options;
    if (opts.length >= 3) {
      opts[0].textContent = T("history.board_all");
      opts[1].textContent = T("history.board_arrivals");
      opts[2].textContent = T("history.board_departures");
    }
    setText("#h-reset", "history.reset");
    if (!allState || !allState.ctrl) setText("#h-more", "history.more");
    $("h-detail-close").setAttribute("aria-label", T("history.close"));
    if (!$("h-detail").open) setText("#h-detail-title", "history.train");
  }

  function onLangChange() {
    buildFmts();
    applyStatic();
    if (lastQuery !== null) search(true);
    var dlg = $("h-detail");
    if (dlg && dlg.open && lastJourney) openJourney(lastJourney.id, lastFocus, lastJourney.hint);
  }

  function init() {
    form = $("h-form");
    if (!form) return;
    document.addEventListener("i18n:change", onLangChange);
    if (I) I.ready.then(applyStatic);
    FIELDS.forEach(function (f) { inputs[f] = $("h-" + f); });
    allBtn = $("h-alldays");
    inputs.date.value = "";            // all days by default — never pre-filled with today
    inputs.date.max = todayBucharest();
    syncScope();
    allBtn.addEventListener("click", function () {
      if (!inputs.date.value) return;
      inputs.date.value = "";
      syncScope();
      clearTimeout(timer);
      search(true);
    });
    form.addEventListener("submit", function (e) { e.preventDefault(); clearTimeout(timer); search(true); });
    form.addEventListener("input", function (e) {
      if (e.target === inputs.train) {
        var digits = inputs.train.value.replace(/\D+/g, "").slice(0, 6);
        if (digits !== inputs.train.value) inputs.train.value = digits;
      }
      syncScope();
      debounced();
    });
    form.addEventListener("change", function () { syncScope(); debounced(); });
    form.addEventListener("reset", function () {
      setTimeout(function () {
        inputs.date.value = "";
        syncScope();
        clearTimeout(timer);
        search(true);
      }, 0);
    });
    $("h-more").addEventListener("click", loadMore);
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
