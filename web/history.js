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
  var BOARD_LABEL = { arrival: "Sosire", departure: "Plecare" };

  var $ = function (id) { return document.getElementById(id); };
  var form, inputs = {}, timer = null, inflight = null, detailCtrl = null, lastQuery = null;
  var lastFocus = null, allBtn = null;
  var PAGE = 200;                 // journeys per page (server max 200)
  var allState = null;            // {q, next, groups: {day: tbody}, shown, ctrl}

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
      if (!/^\d{4}-\d{2}-\d{2}$/.test(q.date)) return "Alege o zi validă.";
      if (q.date > todayBucharest()) {
        return "Ziua nu poate fi în viitor — istoricul începe cu ce s-a observat deja.";
      }
    }
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
    n.title = "citire nesigură";
    n.append(el("span", "sr-only", " (citire nesigură)"));
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

  var shortDayFmt = new Intl.DateTimeFormat("ro-RO", { timeZone: "UTC", day: "2-digit", month: "2-digit",
                                                       year: "numeric" });
  var numFmt = new Intl.NumberFormat("ro-RO", { maximumFractionDigits: 1 });

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
    p.append(el("strong", "h-sum-board", board === "arrival" ? "Sosiri" : "Plecări"), " — ");
    if (!s || !s.n) {
      p.append("nicio întârziere citită pentru călătoriile încheiate (necunoscut, nu 0).");
      return p;
    }
    var parts = ["N = " + s.n + " cu întârzierea citită", "medie " + minSigned(s.mean),
                 "mediană " + minSigned(s.median), "maxim " + minSigned(s.max)];
    if (s.sufficient && s.on_time_pct != null) {
      parts.push("la timp (≤ " + params.on_time_max_min + " min) " + numFmt.format(s.on_time_pct) + "%");
    } else {
      parts.push("fără procente sub N = " + params.min_sample);
    }
    p.append(parts.join(" · "));
    return p;
  }

  // Beta 1.26: the headline figures as a hero strip (count-up numbers), above the exact lines
  function summaryHero(data, sum, params) {
    var U = window.TabelaApp.ui2;
    if (!U) return null;
    var per = data.period || {};
    var items = [{ label: "Călătorii în listă", value: data.total,
                   sub: per.days ? plural(per.days, "zi cu date", "zile cu date") : "o zi" }];
    ["arrival", "departure"].forEach(function (b) {
      var s = sum[b];
      var ok = s && s.n && s.sufficient && s.on_time_pct != null;
      items.push({ label: (b === "arrival" ? "Sosiri" : "Plecări") + " · la timp", tone: b === "arrival" ? "arr" : "dep",
        value: ok ? s.on_time_pct : null, unit: ok ? " %" : "",
        fmt: function (x) { return numFmt.format(Math.round(x * 10) / 10); },
        sub: s && s.n ? (ok ? "N = " + s.n + " cu întârziere citită" : "N = " + s.n + " < " + params.min_sample + ": fără procent") : "N = 0",
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
      .map(function (k) { return STATE_SHORT[k] + ": " + st[k]; });
    if (states.length) box.append(el("p", "h-sum-states", "Rezultate (toată lista) — " + states.join(" · ")));
    if (data.low_quality_excluded) {
      box.append(el("p", "h-sum-note", plural(data.low_quality_excluded, "călătorie", "călătorii") +
        " din perioada de calitate redusă (versiunea beta inițială) apar în listă, dar nu intră în rezumat."));
    }
    box.append(el("p", "h-sum-note",
      "Întârzierea este cea CITITĂ pe tabela din București Nord. Media, mediana și maximul folosesc doar " +
      "călătoriile încheiate cu întârzierea citită (" + (params.confirmed_only ? "doar confirmate" :
      "confirmate și neconfirmate") + "); cele necunoscute nu intră și nu sunt 0."));
    box.hidden = false;
  }

  function allCount(q, data) {
    var count = $("h-count");
    var per = data.period || {};
    var text = (q.train ? "Trenul " + q.train + ": " : "") + plural(data.total, "călătorie", "călătorii");
    if (q.date) text += " · " + dayLabel(q.date);
    else if (per.first) {
      text += " în perioada " + shortDay(per.first) + " – " + shortDay(per.last) + " (" +
        plural(per.days, "zi", "zile") + ")";
    }
    count.textContent = text;
    if (allState && allState.shown < data.total) {
      count.append(" · ", el("strong", "h-truncated", "afișate " + allState.shown + " (cele mai noi)"));
    }
  }

  function journeyDelay(j) {
    var r = j.result || {};
    if (r.state === "confirmed") return delayBadge(r.final_delay, "Întârziere finală (rezultat confirmat)", true);
    if (r.delay_known) {
      return delayBadge(r.observed_delay, "Ultima întârziere citită — rezultat " +
                        (STATE_SHORT[r.state] || "necunoscut"), true);
    }
    return delayBadge(null, "", false);
  }

  function journeyRow(j) {
    var r = j.result || {};
    var tr = el("tr", "h-row");
    var known = j.max_read_delay != null;
    tr.dataset.delay = known ? delayLevel(j.max_read_delay) : "unread";
    cell(tr, "Ora programată", "h-time", j.sched_time || "--:--");
    cell(tr, "Panou", "h-board", BOARD_LABEL[j.board] || j.board);
    var hint = { train_type: j.train_type, train_no: j.train_no, board: j.board, sched_time: j.sched_time,
                 station: j.station, service_date: j.service_date };
    var train = el("button", "h-train");
    train.type = "button";
    train.append(el("span", App.typeClass(j.train_type), j.train_type || "?"),
                 el("span", "t-no", String(j.train_no)));
    train.setAttribute("aria-label", "Detaliu și grafic: tren " + (j.train_type || "") + " " + j.train_no +
      ", " + (BOARD_LABEL[j.board] || "") + " " + (j.sched_time || "") + ", " + dayLabel(j.service_date));
    train.addEventListener("click", function () { openJourney(j.id, train, hint); });
    cell(tr, "Tren", "h-trn", train);
    cell(tr, "Stație", "h-station", j.station ? stationLink(j.station, nameNode(titleCase(j.station), j)) : "—");
    var acts = el("span", "h-acts");
    var g = el("button", "h-act", "Grafic");
    g.type = "button";
    g.setAttribute("aria-label", "Detaliu și grafic, " + dayLabel(j.service_date) + " " + (j.sched_time || ""));
    g.addEventListener("click", function () { openJourney(j.id, g, hint); });
    var prof = el("a", "h-act", "Profil tren");
    prof.href = "#tren?nr=" + encodeURIComponent(j.train_no);
    acts.append(g, prof);
    cell(tr, "Detalii", "h-op", acts);
    cell(tr, "Întârziere max. citită", "h-max",
         known ? delayBadge(j.max_read_delay, "Cea mai mare întârziere citită pe tabelă", true)
               : delayBadge(null, "", false));
    cell(tr, "Întârziere finală / ultima citită", "h-last", journeyDelay(j));
    var hasPlat = j.platform != null && j.platform !== "";
    var plat = el("span", hasPlat ? "plat plat-sm" : "plat plat-sm plat-unknown", hasPlat ? String(j.platform) : "—");
    plat.setAttribute("aria-label", hasPlat ? "Linia " + j.platform : "Linie neanunțată");
    cell(tr, "Linia", "h-plat", plat);
    var res = resultBadge(r);
    if (r.reason) res.title = r.reason;
    var resCell = cell(tr, "Rezultat", "h-status", res);
    if (j.low_quality === true) {
      var lq = el("span", "lq-badge", "calitate redusă");
      lq.title = "Citită în perioada de calitate redusă (versiunea beta inițială) — nu intră în rezumat";
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
    ["Ora prog.", "Panou", "Tren", "Stație", "Detalii", "Întârziere max. citită",
     "Întârziere finală / ultima citită", "Linia", "Rezultat"].forEach(function (h) {
      var th = el("th", null, h);
      th.scope = "col";
      hr.append(th);
    });
    thead.append(hr);
    var tbody = el("tbody");
    table.append(el("caption", "sr-only", "Călătoriile din " + dayLabel(day)), thead, tbody);
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
      $("h-count").textContent = (q.train ? "Trenul " + q.train + ": " : "") +
        plural(0, "călătorie", "călătorii") + (q.date ? " · " + dayLabel(q.date) : "");
      var empty = $("h-empty");
      var narrowed = q.station || q.from || q.to || q.board || q.date;
      empty.textContent = q.train
        ? (narrowed ? "Nu există călătorii observate ale acestui tren pentru aceste filtre."
                    : "Trenul " + q.train + " nu a fost observat pe tabelă.")
        : (narrowed ? "Nu există trenuri observate pentru aceste filtre."
                    : "Nu există încă trenuri observate.");
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
    btn.textContent = "Se încarcă…";
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
        btn.textContent = "Încarcă mai multe";
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
    var sub = $("h-detail-sub");
    sub.replaceChildren((BOARD_LABEL[j.board] || "") + " " + (j.sched_time || ""));
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
    else syncScope();
    inputs.date.max = todayBucharest();
    search(false);
  }

  function init() {
    form = $("h-form");
    if (!form) return;
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
