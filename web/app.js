// © 2026 Andy217Ace
// Tabela Gara de Nord — live board. DOM is built with createElement/textContent only
// (no HTML strings: API data never reaches the parser). No inline styles (CSP).
"use strict";

(function () {
  var REFRESH_MS = 10000;
  var TIMEOUT_MS = 8000;
  var STALE_S = 180;
  var SVG_NS = "http://www.w3.org/2000/svg";
  var BOARDS = ["arrivals", "departures"];
  var TAB_KEY = "tabela.tab";

  var state = {
    data: null,          // last good /api/board payload
    receivedAt: 0,       // performance.now() when data arrived
    failed: false,       // last fetch failed
    lastAnnounce: "",
    cards: { arrivals: new Map(), departures: new Map() },
    timer: null,
    inflight: null
  };

  var $ = function (id) { return document.getElementById(id); };

  // ---- small DOM helpers ---------------------------------------------------

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function icon(paths) {
    var s = document.createElementNS(SVG_NS, "svg");
    s.setAttribute("viewBox", "0 0 24 24");
    s.setAttribute("aria-hidden", "true");
    s.setAttribute("focusable", "false");
    paths.forEach(function (d) {
      var p = document.createElementNS(SVG_NS, "path");
      p.setAttribute("d", d);
      s.appendChild(p);
    });
    return s;
  }

  var ICONS = {
    ok: ["M5 12.5l4.5 4.5L19 7.5"],
    clock: ["M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17z", "M12 7.5V12l3 2"],
    alert: ["M12 3.5 2.5 20h19z", "M12 10v4.5", "M12 17.2v.3"],
    bell: ["M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 1.5h-15z", "M10 20.5a2 2 0 0 0 4 0"]
  };

  // ---- formatting -----------------------------------------------------------

  function addMinutes(hhmm, min) {
    var m = /^(\d{2}):(\d{2})$/.exec(hhmm || "");
    if (!m) return hhmm || "";
    var t = (parseInt(m[1], 10) * 60 + parseInt(m[2], 10) + min) % 1440;
    var h = Math.floor(t / 60), mm = t % 60;
    return (h < 10 ? "0" : "") + h + ":" + (mm < 10 ? "0" : "") + mm;
  }

  function ago(sec) {
    sec = Math.max(0, Math.round(sec));
    if (sec < 60) return "acum " + sec + " s";
    var min = Math.floor(sec / 60);
    if (min < 60) return "acum " + min + " min";
    var h = Math.floor(min / 60);
    return "acum " + h + " h";
  }

  function delayLevel(d) {
    if (!d || d <= 0) return "ok";
    return d <= 15 ? "minor" : "major";
  }

  function trainKey(t) {
    return (t.service_date || "") + "|" + t.train_no + "|" + t.sched_time;
  }

  function typeClass(type) {
    var k = String(type || "").toLowerCase();
    return ["ir", "irn", "re", "r", "rm"].indexOf(k) >= 0 ? "type type-" + k : "type";
  }

  // ---- train card -------------------------------------------------------------

  function createCard(board) {
    var li = el("li", "train");
    var time = el("div", "t-time");
    var est = el("span", "t-est");
    var sched = el("span", "t-sched");
    time.append(sched, est);

    var main = el("div", "t-main");
    var station = el("p", "t-station");
    var meta = el("p", "t-meta");
    var type = el("span", "type");
    var no = el("span", "t-no");
    var flag = el("span", "t-flag");
    flag.title = "Marcat cu * pe tabela CFR";
    flag.append(el("span", null, "*"), el("span", "sr-only", "marcat cu asterisc pe tabela CFR"));
    flag.firstChild.setAttribute("aria-hidden", "true");
    var op = el("span", "t-op");
    meta.append(type, no, flag, op);

    var row = el("div", "t-row");
    var delay = el("span", "delay");
    var follow = el("button", "follow");
    follow.type = "button";
    follow.append(icon(ICONS.bell), el("span", null, "urmărește"));
    row.append(delay, follow);
    main.append(station, meta);

    var platWrap = el("div", "t-plat");
    var plat = el("span", "plat");
    platWrap.append(plat, el("span", "plat-label", "linia"));

    li.append(time, main, platWrap, row);

    var card = { li: li, board: board, sched: sched, est: est, station: station, type: type,
                 no: no, flag: flag, op: op, delay: delay, follow: follow, plat: plat,
                 train: null, sig: null };
    follow.addEventListener("click", function () {
      if (card.train) window.TabelaApp.onFollow(card.train, follow);
    });
    li.addEventListener("animationend", function () { li.classList.remove("flash"); });
    return card;
  }

  function updateCard(c, t, prevSig) {
    var d = Math.max(0, t.delay_min | 0);
    var level = delayLevel(d);
    var where = c.board === "arrivals" ? "din " : "spre ";
    c.train = t;
    c.li.dataset.delay = level;

    c.sched.textContent = t.sched_time || "--:--";
    if (level === "ok") {
      c.est.hidden = true;
      c.est.textContent = "";
      c.sched.removeAttribute("aria-label");
    } else {
      c.est.hidden = false;
      c.est.textContent = addMinutes(t.sched_time, d);
      c.sched.setAttribute("aria-label", "programat " + t.sched_time);
    }

    c.station.textContent = t.station ? t.station.toLowerCase() : "—";
    c.station.setAttribute("aria-label", where + (t.station || "stație necunoscută"));
    c.type.className = typeClass(t.train_type);
    c.type.textContent = t.train_type || "?";
    c.type.title = "Tip tren " + (t.train_type || "necunoscut");
    c.no.textContent = String(t.train_no);
    c.flag.hidden = !t.flagged;
    c.op.textContent = t.operator || "";
    c.op.hidden = !t.operator;

    c.delay.className = "delay delay-" + level;
    c.delay.replaceChildren(
      icon(level === "ok" ? ICONS.ok : level === "minor" ? ICONS.clock : ICONS.alert),
      document.createTextNode(level === "ok" ? "la timp" : "+" + d + " min")
    );
    c.delay.setAttribute("aria-label", level === "ok" ? "La timp" : "Întârziere " + d + " minute");

    var known = t.platform != null && t.platform !== "";
    c.plat.className = known ? "plat" : "plat plat-unknown";
    c.plat.textContent = known ? String(t.platform) : "—";
    c.plat.setAttribute("aria-label", known ? "Linia " + t.platform : "Linie neanunțată");
    c.plat.title = known ? "Linia " + t.platform : "Linia nu a fost anunțată";

    c.follow.setAttribute("aria-label", "Urmărește trenul " + (t.train_type || "") + " " +
      t.train_no + " " + where + (t.station || ""));

    var sig = d + "|" + (known ? t.platform : "-");
    if (prevSig != null && prevSig !== sig) {
      c.li.classList.remove("flash");
      void c.li.offsetWidth; // restart the animation
      c.li.classList.add("flash");
    }
    c.sig = sig;
  }

  function renderBoard(board, trains) {
    var list = $("list-" + board);
    var section = $("panel-" + board);
    var empty = section.querySelector(".empty");
    var cards = state.cards[board];
    var seen = new Set();

    list.querySelectorAll(".skeleton").forEach(function (n) { n.remove(); });
    list.removeAttribute("aria-busy");

    trains.forEach(function (t, i) {
      var key = trainKey(t);
      seen.add(key);
      var c = cards.get(key);
      var prevSig = c ? c.sig : null;
      if (!c) {
        c = createCard(board);
        cards.set(key, c);
      }
      updateCard(c, t, prevSig);
      // reorder only when needed so focus isn't lost on untouched cards
      if (list.children[i] !== c.li) list.insertBefore(c.li, list.children[i] || null);
    });

    cards.forEach(function (c, key) {
      if (!seen.has(key)) {
        c.li.remove();
        cards.delete(key);
      }
    });

    empty.textContent = EMPTY_TEXT;
    empty.hidden = trains.length > 0;
    list.hidden = trains.length === 0;
    $("count-" + board).textContent = trains.length ? String(trains.length) : "";
  }

  // ---- live indicator / banner ---------------------------------------------------

  function currentAge() {
    if (!state.data || state.data.age_s == null) return null;
    return state.data.age_s + (performance.now() - state.receivedAt) / 1000;
  }

  function announce(text) {
    if (text === state.lastAnnounce) return;
    state.lastAnnounce = text;
    $("sr-status").textContent = text;
  }

  function renderLive() {
    var live = $("live");
    var text = $("updated");
    var banner = $("banner");
    var bannerText = $("banner-text");
    var age = currentAge();

    if (!state.data) {
      if (state.failed) {
        live.dataset.state = "offline";
        text.textContent = "fără conexiune";
        bannerText.textContent = "Conexiune pierdută — nu am putut încărca tabela. Reîncerc automat.";
        banner.hidden = false;
        announce("Conexiune pierdută.");
      }
      return;
    }

    var stale = age == null || age > STALE_S;
    if (state.failed) {
      live.dataset.state = "offline";
      text.textContent = age == null ? "date vechi" : "date vechi · " + ago(age);
      bannerText.textContent = "Conexiune pierdută — afișez ultimele date.";
      banner.hidden = false;
      announce("Conexiune pierdută — afișez ultimele date.");
    } else if (stale) {
      live.dataset.state = "stale";
      text.textContent = age == null ? "fără date încă" : "date vechi · " + ago(age);
      bannerText.textContent = age == null
        ? "Tabela CFR nu a fost încă citită — datele pot lipsi."
        : "Datele nu s-au mai actualizat de " + ago(age).replace("acum ", "") +
          " — tabela poate fi depășită. Verifică și cfr.ro.";
      banner.hidden = false;
      announce("Date vechi.");
    } else {
      live.dataset.state = "live";
      text.textContent = "actualizat " + ago(age);
      banner.hidden = true;
      announce("Tabela este actualizată.");
    }
  }

  // ---- fetch loop --------------------------------------------------------------

  function schedule(ms) {
    clearTimeout(state.timer);
    state.timer = setTimeout(refresh, ms);
  }

  var EMPTY_TEXT = "Momentan nu sunt trenuri afișate.";

  // First fetch failed: swap the skeleton cards for a message and drop aria-busy.
  function showLoadFailure() {
    BOARDS.forEach(function (b) {
      var list = $("list-" + b);
      list.querySelectorAll(".skeleton").forEach(function (n) { n.remove(); });
      list.removeAttribute("aria-busy");
      list.hidden = true;
      var empty = $("panel-" + b).querySelector(".empty");
      empty.textContent = "Nu am putut încărca tabela. Reîncerc automat.";
      empty.hidden = false;
    });
  }

  function refresh() {
    if (state.inflight) state.inflight.abort();
    var ctrl = new AbortController();
    state.inflight = ctrl;
    var to = setTimeout(function () { ctrl.abort(); }, TIMEOUT_MS);

    fetch("/api/board", { signal: ctrl.signal, cache: "no-store", headers: { Accept: "application/json" } })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        if (!data || !Array.isArray(data.arrivals) || !Array.isArray(data.departures)) {
          throw new Error("răspuns invalid");
        }
        state.data = data;
        state.receivedAt = performance.now();
        state.failed = false;
        BOARDS.forEach(function (b) { renderBoard(b, data[b]); });
      })
      .catch(function () {
        if (state.inflight !== ctrl) return; // superseded (e.g. visibilitychange): not an outage
        state.failed = true;
        if (!state.data) showLoadFailure();
      })
      .then(function () {
        clearTimeout(to);
        if (state.inflight !== ctrl) return; // a newer refresh owns the UI and the timer
        state.inflight = null;
        renderLive();
        schedule(REFRESH_MS);
      });
  }

  // ---- tabs ------------------------------------------------------------------------

  function selectTab(board, focus) {
    $("boards").dataset.active = board;
    BOARDS.forEach(function (b) {
      var tab = $("tab-" + b);
      var on = b === board;
      tab.setAttribute("aria-selected", on ? "true" : "false");
      tab.tabIndex = on ? 0 : -1;
      if (on && focus) tab.focus();
    });
    try { localStorage.setItem(TAB_KEY, board); } catch (e) { /* storage unavailable */ }
  }

  function initTabs() {
    BOARDS.forEach(function (b) {
      var tab = $("tab-" + b);
      tab.addEventListener("click", function () { selectTab(b, false); });
      tab.addEventListener("keydown", function (e) {
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
          e.preventDefault();
          selectTab(b === "arrivals" ? "departures" : "arrivals", true);
        }
      });
    });
    var saved = null;
    try { saved = localStorage.getItem(TAB_KEY); } catch (e) { /* ignore */ }
    selectTab(BOARDS.indexOf(saved) >= 0 ? saved : "arrivals", false);
  }

  // ---- routing (#istoric / #urmarite are placeholders until Task 11) ---------------

  var ROUTES = { "": "tabela", "#istoric": "istoric", "#urmarite": "urmarite" };

  function route() {
    var name = ROUTES[location.hash] || "tabela";
    ["tabela", "istoric", "urmarite"].forEach(function (r) {
      $("view-" + r).hidden = r !== name;
    });
    document.querySelectorAll(".nav-item").forEach(function (a) {
      if (a.dataset.route === name) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    document.title = name === "tabela" ? "Tabela Gara de Nord"
      : (name === "istoric" ? "Istoric" : "Urmărite") + " · Tabela Gara de Nord";
  }

  // ---- toast -----------------------------------------------------------------------

  var toastTimer = null;
  function toast(msg) {
    var t = $("toast");
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.hidden = true; }, 3200);
  }

  // ---- public hooks (Task 11 replaces onFollow) ------------------------------------

  window.TabelaApp = window.TabelaApp || {};
  if (typeof window.TabelaApp.onFollow !== "function") {
    window.TabelaApp.onFollow = function () {
      toast("Urmărirea trenurilor vine în curând.");
    };
  }
  window.TabelaApp.toast = toast;
  window.TabelaApp.refresh = refresh;

  // ---- boot ------------------------------------------------------------------------

  function init() {
    initTabs();
    route();
    window.addEventListener("hashchange", route);
    setInterval(renderLive, 1000);
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "visible") refresh();
    });
    refresh();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
