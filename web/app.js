// © 2026 Andy217Ace
// Tabela Gara de Nord — live board. DOM is built with createElement/textContent only
// (no HTML strings: API data never reaches the parser). No inline styles (CSP).
"use strict";

(function () {
  var TIMEOUT_MS = 8000;
  // UI settings: GET /api/config is the single source of truth (refresh interval,
  // stale threshold, delay colour thresholds). These defaults mirror the server's and
  // apply only until the config arrives (or if it cannot be loaded).
  var CONFIG_DEFAULTS = { delay_thresholds: { low: 5, mid: 15, high: 30 }, stale_after_s: 180, refresh_s: 10 };
  var cfg = CONFIG_DEFAULTS;
  var configPromise = null;
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

  // ---- i18n (web/i18n/i18n.js): active language, plural and number helpers ----------

  function T(key, params) { return window.I18N ? window.I18N.t(key, params) : key; }
  function loc() { return window.I18N && window.I18N.lang() === "en" ? "en-GB" : "ro-RO"; }
  // Plural form by the active language's Intl.PluralRules; keys base.one / base.few / base.other
  function plural(base, n, params) {
    var cat = "other";
    try { cat = new Intl.PluralRules(loc()).select(Math.abs(n)); } catch (e) { /* ignore */ }
    var k = base + "." + cat, s = T(k, params);
    return s === k ? T(base + ".other", params) : s;
  }
  function unsureText() { return T("board.unsure"); }

  // ---- small DOM helpers (shared with history.js / follows.js) ----------------

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

  // duration without the "ago" wording: 12 s / 5 min / 3 h
  function dur(sec) {
    sec = Math.max(0, Math.round(sec));
    if (sec < 60) return T("time.s", { n: sec });
    var min = Math.floor(sec / 60);
    if (min < 60) return T("time.min", { n: min });
    return T("time.h", { n: Math.floor(min / 60) });
  }

  function ago(sec) { return T("time.ago", { age: dur(sec) }); }

  function delayLevel(d) {
    if (!d || d <= 0) return "ok";
    return d <= cfg.delay_thresholds.mid ? "minor" : "major";
  }

  // ---- config (/api/config) ------------------------------------------------------

  function validConfig(c) {
    var th = c && c.delay_thresholds;
    var num = function (v) { return typeof v === "number" && isFinite(v); };
    if (!th || !num(th.low) || !num(th.mid) || !num(th.high) ||
        !(th.low > 0 && th.low < th.mid && th.mid < th.high)) return CONFIG_DEFAULTS;
    return {
      delay_thresholds: { low: th.low, mid: th.mid, high: th.high },
      stale_after_s: num(c.stale_after_s) && c.stale_after_s > 0 ? c.stale_after_s : CONFIG_DEFAULTS.stale_after_s,
      // clamp: never hammer the server, never go silent for minutes
      refresh_s: num(c.refresh_s) ? Math.min(300, Math.max(5, c.refresh_s)) : CONFIG_DEFAULTS.refresh_s,
      weather: c.weather && typeof c.weather === "object" ? c.weather : null  // web/weather.js validates
    };
  }

  function loadConfig() {
    if (!configPromise) {
      configPromise = fetch("/api/config", { cache: "no-store", headers: { Accept: "application/json" } })
        .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
        .then(function (c) { cfg = validConfig(c); return cfg; })
        .catch(function () { return cfg; }); // keep the defaults
    }
    return configPromise;
  }

  function refreshMs() { return cfg.refresh_s * 1000; }

  function trainKey(t) {
    return (t.service_date || "") + "|" + t.train_no + "|" + t.sched_time;
  }

  function typeClass(type) {
    var k = String(type || "").toLowerCase();
    return ["ir", "irn", "re", "r", "rm"].indexOf(k) >= 0 ? "type type-" + k : "type";
  }

  // Official CFR display of a category code (codes in data/filters/URLs stay IC, IR, IRN, R, RE, RM).
  var TYPE_ABBR = { RE: "R-E", RM: "R-M" };
  function typeAbbr(type) { var k = String(type || ""); return TYPE_ABBR[k.toUpperCase()] || k; }
  function typeName(type) {
    var k = String(type || "").toUpperCase();
    return ["IC", "IR", "IRN", "R", "RE", "RM"].indexOf(k) >= 0 ? T("type.name." + k) : "";
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
    // the station name links to its page (#statie?nume=); an <a> without href (no station) is inert
    var stationLink = el("a", "station-link station-link-plain");
    station.append(stationLink);
    var meta = el("p", "t-meta");
    var type = el("span", "type");
    var no = el("span", "t-no");
    var flag = el("span", "t-flag");
    flag.title = T("board.flagTitle");
    flag.append(el("span", null, "*"), el("span", "sr-only", T("board.flagSr")));
    flag.firstChild.setAttribute("aria-hidden", "true");
    var op = el("span", "t-op");
    meta.append(type, no, flag, op);

    var row = el("div", "t-row");
    var delay = el("span", "delay");
    var follow = el("button", "follow");
    follow.type = "button";
    var followText = el("span", null, T("board.follow"));
    follow.append(icon(ICONS.bell), followText);
    row.append(delay, follow);
    main.append(station, meta);

    var platWrap = el("div", "t-plat");
    var plat = el("span", "plat");
    platWrap.append(plat, el("span", "plat-label", T("board.platformLabel")));

    li.append(time, main, platWrap, row);

    var card = { li: li, board: board, sched: sched, est: est, station: station,
                 stationLink: stationLink, type: type,
                 no: no, flag: flag, op: op, delay: delay, follow: follow, plat: plat,
                 followText: followText, followLabel: "", train: null, sig: null };
    follow.addEventListener("click", function () {
      if (card.train) window.TabelaApp.onFollow(card.train, follow);
    });
    li.addEventListener("animationend", function () { li.classList.remove("flash"); });
    return card;
  }

  function updateCard(c, t, prevSig) {
    var d = Math.max(0, t.delay_min | 0);
    // never "la timp" unless the delay cell was actually read (API `delay_read`)
    var read = t.delay_read === true;
    // unreadable now (glare): the train's last safe reading, labelled with its age
    var lastAge = !read && typeof t.delay_last_read_age_s === "number" ? t.delay_last_read_age_s : null;
    var lastRead = lastAge !== null;
    var level = read || lastRead ? delayLevel(d) : "unread";
    var fromBoard = c.board === "arrivals";
    var where = T(fromBoard ? "board.from" : "board.to");
    c.train = t;
    c.li.dataset.delay = level;

    c.sched.textContent = t.sched_time || "--:--";
    if (level === "ok" || level === "unread") {
      c.est.hidden = true;
      c.est.textContent = "";
      c.sched.removeAttribute("aria-label");
    } else {
      c.est.hidden = false;
      c.est.textContent = addMinutes(t.sched_time, d);
      c.sched.setAttribute("aria-label", T("board.scheduled", { time: t.sched_time }));
    }

    // A2 canonicalisation: `uncertain` = station/operator did not match a known name
    var unsure = t.uncertain === true;
    c.stationLink.textContent = t.station ? t.station.toLowerCase() : "—";
    if (t.station) {
      var href = "#statie?nume=" + encodeURIComponent(t.station);
      if (c.stationLink.getAttribute("href") !== href) c.stationLink.setAttribute("href", href);
      c.stationLink.setAttribute("aria-label", T(fromBoard ? "board.stationPageFrom" : "board.stationPageTo",
        { name: t.station + (unsure ? " (" + unsureText() + ")" : "") }));
      c.station.removeAttribute("aria-label");
    } else {
      c.stationLink.removeAttribute("href");
      c.stationLink.removeAttribute("aria-label");
      c.station.setAttribute("aria-label", where + " " + T("board.stationUnknown"));
    }
    c.station.classList.toggle("is-uncertain", unsure && !!t.station);
    // full name as tooltip: long names are clamped to 2 lines / ellipsis by CSS
    c.station.title = t.station ? t.station + (unsure ? " (" + unsureText() + ")" : "") : "";
    c.type.className = typeClass(t.train_type);
    c.type.textContent = typeAbbr(t.train_type) || "?";
    c.type.title = T("board.typeTitle", { type: typeName(t.train_type) || typeAbbr(t.train_type) || T("board.typeUnknown") });
    c.no.textContent = String(t.train_no);
    c.flag.hidden = !t.flagged;
    c.op.textContent = t.operator || "";
    c.op.hidden = !t.operator;
    c.op.classList.toggle("is-uncertain", unsure && !!t.operator);
    c.op.title = t.operator ? t.operator + (unsure ? " (" + unsureText() + ")" : "") : "";

    c.delay.className = "delay delay-" + level;
    var ageMin = lastRead ? Math.max(0, Math.round(lastAge / 60)) : 0;
    var ageTxt = ageMin < 1 ? T("time.agoUnder") : T("time.ago", { age: T("time.min", { n: ageMin }) });
    var valTxt = level === "unread" ? T("board.unread") : level === "ok" ? T("board.onTime") : "+" + d + " min";
    c.delay.replaceChildren(
      icon(level === "ok" ? ICONS.ok : level === "minor" || level === "unread" ? ICONS.clock : ICONS.alert),
      document.createTextNode(valTxt)
    );
    if (lastRead) {
      c.delay.append(document.createTextNode(" (" + T("board.lastRead", { age: ageTxt }) + ")"));
      c.delay.classList.add("delay-last");
    }
    c.delay.setAttribute("aria-label", level === "unread" ? T("board.delayAria.unread")
      : (level === "ok" ? T("board.delayAria.onTime") : plural("board.delayAria.late", d, { n: d })) +
        (lastRead ? ", " + T("board.lastRead", { age: ageTxt }) : ""));
    c.delay.title = level === "unread" ? T("board.delayTitle.unread")
      : lastRead ? T("board.delayTitle.glare", { age: ageTxt }) : "";

    var known = t.platform != null && t.platform !== "";
    c.plat.className = known ? "plat" : "plat plat-unknown";
    c.plat.textContent = known ? String(t.platform) : "—";
    c.plat.setAttribute("aria-label", known ? T("board.platAria", { p: t.platform }) : T("board.platNone"));
    c.plat.title = known ? T("board.platAria", { p: t.platform }) : T("board.platNoneTitle");

    c.followLabel = (t.train_type || "") + " " + t.train_no + " " + where + (t.station || "");
    applyFollow(c);

    var sig = (read ? d : "?") + "|" + (known ? t.platform : "-");
    if (prevSig != null && prevSig !== sig) {
      c.li.classList.remove("flash");
      void c.li.offsetWidth; // restart the animation
      c.li.classList.add("flash");
    }
    c.sig = sig;
    // coloana "Peron estimat" (peron_est.js) se agata aici; absenta = nicio schimbare
    var hook = window.TabelaApp.onCard;
    if (typeof hook === "function") hook(c.li, t, c.board);
  }

  // Follow button state comes from follows.js (TabelaApp.followState); absent = enabled.
  function applyFollow(c) {
    var fs = window.TabelaApp.followState;
    var st = typeof fs === "function" && c.train ? fs(c.train) : null;
    var on = !!(st && st.followed);
    var off = !!(st && st.unsupported);
    c.follow.setAttribute("aria-pressed", on ? "true" : "false");
    if (off) c.follow.setAttribute("aria-disabled", "true");
    else c.follow.removeAttribute("aria-disabled");
    c.follow.title = off ? st.reason : "";
    c.followText.textContent = T(on ? "board.followed" : "board.follow");
    c.follow.setAttribute("aria-label", T(on ? "board.unfollowTrain" : "board.followTrain", { label: c.followLabel }) +
      (off ? ". " + st.reason : ""));
  }

  function refreshFollowButtons() {
    BOARDS.forEach(function (b) { state.cards[b].forEach(applyFollow); });
    // the Panou view (panel.js) renders its own follow buttons
    document.dispatchEvent(new CustomEvent("tabela:follows"));
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

    empty.textContent = T("app.empty");
    empty.hidden = trains.length > 0;
    list.hidden = trains.length === 0;
    $("count-" + board).textContent = trains.length ? String(trains.length) : "";
  }

  // ---- live indicator / banner ---------------------------------------------------

  function currentAge() {
    if (!state.data || state.data.age_s == null) return null;
    var extra = 0;
    if (state.data.sw_offline && typeof state.data.sw_cached_at === "number") {
      extra = Math.max(0, (Date.now() - state.data.sw_cached_at) / 1000); // age of the cached copy
      return state.data.age_s + extra + (performance.now() - state.receivedAt) / 1000;
    }
    return state.data.age_s + (performance.now() - state.receivedAt) / 1000;
  }

  function announce(text) {
    if (text === state.lastAnnounce) return;
    state.lastAnnounce = text;
    $("sr-status").textContent = text;
  }

  // One panel can go stale alone (its frames rejected, e.g. a partial read) while the
  // other stays fresh; the global banner covers the case when everything is stale.
  function markPanelStale(b, data) {
    var p = data.boards && data.boards[b];
    var stale = !!(p && p.stale && !data.stale);
    [$("panel-" + b), $("tab-" + b)].forEach(function (node) {
      if (!node) return;
      node.dataset.stale = stale ? "true" : "false";
      node.title = stale ? (p.age_s == null ? T("app.panelStaleUnknown")
        : T("app.panelStale", { age: ago(p.age_s) })) : "";
    });
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
        text.textContent = T("app.live.noConn");
        bannerText.textContent = T("app.banner.lostLoad");
        banner.hidden = false;
        announce(T("app.announce.lost"));
      } else {
        text.textContent = T("app.loading");
      }
      return;
    }

    var stale = age == null || age > cfg.stale_after_s;
    if (state.failed) {
      live.dataset.state = "offline";
      text.textContent = age == null ? T("app.live.stale") : T("app.live.staleAge", { age: ago(age) });
      bannerText.textContent = T("app.banner.lostShowing");
      banner.hidden = false;
      announce(T("app.banner.lostShowing"));
    } else if (stale) {
      live.dataset.state = "stale";
      text.textContent = age == null ? T("app.live.noData") : T("app.live.staleAge", { age: ago(age) });
      bannerText.textContent = age == null
        ? T("app.banner.neverRead")
        : T("app.banner.outdated", { age: dur(age) });
      banner.hidden = false;
      announce(T("app.announce.stale"));
    } else {
      live.dataset.state = "live";
      text.textContent = T("app.live.updated", { age: ago(age) });
      banner.hidden = true;
      announce(T("app.announce.ok"));
    }
  }

  // ---- fetch loop --------------------------------------------------------------

  function schedule(ms) {
    clearTimeout(state.timer);
    state.timer = setTimeout(refresh, ms);
  }

  // First fetch failed: swap the skeleton cards for a message and drop aria-busy.
  function showLoadFailure() {
    BOARDS.forEach(function (b) {
      var list = $("list-" + b);
      list.querySelectorAll(".skeleton").forEach(function (n) { n.remove(); });
      list.removeAttribute("aria-busy");
      list.hidden = true;
      var empty = $("panel-" + b).querySelector(".empty");
      empty.textContent = T("app.loadFail");
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
          throw new Error("invalid response");
        }
        if (data.sw_offline && state.data && !state.data.sw_offline) {
          // offline: the in-memory copy is at least as new as the cached one
          state.failed = true;
          return;
        }
        state.data = data;
        state.receivedAt = performance.now();
        state.failed = !!data.sw_offline; // served from the service worker cache

        BOARDS.forEach(function (b) { renderBoard(b, data[b]); markPanelStale(b, data); });
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
        var boot = $("boot");
        if (boot) boot.hidden = true;
        renderLive();
        schedule(refreshMs());
        // mod „Panou" (panel.js) listens for every fetch outcome
        document.dispatchEvent(new CustomEvent("tabela:board",
          { detail: { data: state.data, failed: state.failed } }));
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

  // ---- routing: #istoric[?query] / #urmarite, views register in TabelaApp.views ---

  var ROUTES = { "": "tabela", "#": "tabela", "#istoric": "istoric", "#urmarite": "urmarite",
    "#ocr": "ocr", "#ocr2": "ocr2", "#admin": "admin", "#versiuni": "versiuni", "#trenuri": "trenuri", "#tren": "tren",
    "#statistici": "statistici", "#clasamente": "clasamente", "#statii": "statii", "#statie": "statie",
    "#sistem": "sistem", "#setari": "setari" };
  var VIEWS = ["tabela", "istoric", "urmarite", "ocr", "admin", "versiuni", "trenuri", "tren", "statistici",
    "clasamente", "statii", "statie", "sistem", "setari", "ocr2"];
  // routes with a page title: i18n key title.<route>
  var TITLES = ["istoric", "ocr", "admin", "versiuni", "urmarite", "trenuri", "tren", "statistici",
    "clasamente", "statii", "statie", "sistem", "setari", "ocr2"];
  // nav item highlighted for a route without its own entry (#tren → „Trenuri”, #statie → „Stații”)
  var NAV_PARENT = { tren: "trenuri", statie: "statii" };
  var currentRoute = null;   // route asked for by the address
  var shownRoute = null;     // route whose view is on screen (differs while its stylesheet loads)

  // „Capturi OCR" (#ocr, admin only): not in the nav; ocr.js/ocr.css are loaded on demand.
  function loadOcrView() {
    if ($("view-ocr")) return;
    var sec = el("section", "view view-ocr");
    sec.id = "view-ocr";
    sec.hidden = true;
    $("main").appendChild(sec);
    var css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = "ocr.css";
    document.head.appendChild(css);
    var s = document.createElement("script");
    s.src = "ocr.js";
    s.addEventListener("load", function () { if (currentRoute === "ocr") route(); });
    document.head.appendChild(s);
  }

  // „Administrare" (#admin, admin only, not in the nav): admin.js/admin.css loaded on demand.
  function loadAdminView() {
    if ($("view-admin")) return;
    var sec = el("section", "view view-admin");
    sec.id = "view-admin";
    sec.hidden = true;
    $("main").appendChild(sec);
    var css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = "admin.css";
    document.head.appendChild(css);
    var s = document.createElement("script");
    s.src = "admin.js";
    s.addEventListener("load", function () { if (currentRoute === "admin") route(); });
    document.head.appendChild(s);
  }

  // Paginile Sistem și Setări se încarcă la prima vizită (nu sunt în precache: bugetul SW).
  var lazyPages = {};
  function loadLazyPage(name, js, css) {
    if (lazyPages[js]) return;
    lazyPages[js] = true;
    if (css) {
      var link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = css;
      document.head.appendChild(link);
    }
    var s = document.createElement("script");
    s.src = js;
    s.addEventListener("load", function () { if (currentRoute === name) route(); });
    document.head.appendChild(s);
  }

  // Page stylesheets load on the first visit of a view, not with the board (render-blocking otherwise).
  // Inserted before ui2.css so the cascade stays as with static <link>s; the view is shown once they load (no FOUC).
  var STATS_CSS = ["stats.css"];
  var PAGE_CSS = { trenuri: STATS_CSS, tren: STATS_CSS, statii: STATS_CSS, statie: STATS_CSS, clasamente: STATS_CSS,
    statistici: ["stats.css", "statistici.css"] };
  var cssDone = {};
  function pageCssReady(name) {
    var ready = true;
    (PAGE_CSS[name] || []).forEach(function (href) {
      if (cssDone[href] === true) return;
      ready = false;
      if (cssDone[href]) return;   // already loading
      var link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = href;
      cssDone[href] = link;
      link.onload = link.onerror = function () {   // a failed sheet must not block the page
        cssDone[href] = true;
        if (currentRoute === name) route();
      };
      document.head.insertBefore(link, document.querySelector('link[href="ui2.css"]'));
    });
    return ready;
  }

  function parseHash() {
    var h = location.hash || "";
    var q = h.indexOf("?");
    var base = q >= 0 ? h.slice(0, q) : h;
    var params = new URLSearchParams(q >= 0 ? h.slice(q + 1) : "");
    return { name: ROUTES[base] || "tabela", params: params };
  }

  // The top menu scrolls sideways inside itself when it doesn't fit (phones): keep the
  // active item in view, without scrolling the page.
  function revealActiveNav() {
    var nav = document.querySelector(".mainnav");
    var a = nav && nav.querySelector('.nav-item[aria-current="page"]');
    if (!a || nav.scrollWidth <= nav.clientWidth + 1) return;
    var nr = nav.getBoundingClientRect();
    var ar = a.getBoundingClientRect();
    var pad = 24;
    if (ar.left < nr.left + pad) nav.scrollLeft -= (nr.left + pad) - ar.left;
    else if (ar.right > nr.right - pad) nav.scrollLeft += ar.right - (nr.right - pad);
  }

  // ---- phones (≤ 700 px, style.css): bottom bar = 4 sections + „Mai mult” ----------
  // The menu is filled from the .mainnav links that are not in the bar (one list of routes),
  // plus Versiuni/Setări; on phones the language switch moves into it as well.
  var NAV_BAR = ["tabela", "istoric", "trenuri", "statistici"];
  var PHONE_MQ = "(max-width: 700px)";
  function initMoreNav() {
    var btn = $("nav-more-btn"), menu = $("nav-more-menu");
    if (!btn || !menu) return;
    function item(a) { var li = el("li"); li.append(a); menu.append(li); }
    document.querySelectorAll(".mainnav .nav-item").forEach(function (a) {
      if (NAV_BAR.indexOf(a.dataset.route) >= 0) return;
      var c = a.cloneNode(true);
      c.className = "nav-more-link";
      c.removeAttribute("aria-current");
      item(c);
    });
    [["versiuni", "title.versiuni", ["M5 6h14", "M5 12h14", "M5 18h9"]],
     ["setari", "title.setari", ["M4 7h16", "M4 17h16", "M15 4.5v5", "M9 14.5v5"]]].forEach(function (r) {
      var a = el("a", "nav-more-link");
      a.href = "#" + r[0];
      a.dataset.route = r[0];
      var ic = icon(r[2]);
      ic.setAttribute("class", "nav-icon");
      var s = el("span", null, T(r[1]));
      s.setAttribute("data-i18n", r[1]);
      a.append(ic, s);
      item(a);
    });
    var langLi = el("li", "nav-more-lang");
    menu.append(langLi);
    var lang = document.querySelector(".navbar > [data-lang-toggle]"), home = lang && lang.parentNode;
    var mq = window.matchMedia ? window.matchMedia(PHONE_MQ) : null;
    function setOpen(on) {
      menu.hidden = !on;
      btn.setAttribute("aria-expanded", on ? "true" : "false");
    }
    function placeLang() {
      if (!lang) return;
      if (mq && mq.matches) langLi.append(lang); else home.append(lang);
      if (!(mq && mq.matches)) setOpen(false);
    }
    placeLang();
    if (mq) {
      if (mq.addEventListener) mq.addEventListener("change", placeLang);
      else if (mq.addListener) mq.addListener(placeLang);
    }
    btn.addEventListener("click", function () { setOpen(menu.hidden); });
    menu.addEventListener("click", function (e) { if (e.target.closest("a")) setOpen(false); });
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape" || menu.hidden) return;
      setOpen(false);
      btn.focus();
    });
    document.addEventListener("click", function (e) {
      if (!menu.hidden && !btn.parentNode.contains(e.target)) setOpen(false);
    });
    window.addEventListener("hashchange", function () { setOpen(false); });
  }

  // Phones: a filter form collapses behind „Filtre (n)” (n = fields with a value); on wider
  // screens the button is hidden and the form always open (style.css). Returns {button, sync}:
  // call sync() after setting the fields from code (no input event then).
  var filtSeq = 0;
  function filterToggle(form) {
    var btn = el("button", "btn btn-ghost filt-toggle");
    btn.type = "button";
    if (!form.id) form.id = "filt-form-" + (++filtSeq);
    btn.setAttribute("aria-controls", form.id);
    form.classList.add("filt-collapsible");
    function count() {
      return [].filter.call(form.elements, function (i) {
        if (i.tagName === "BUTTON" || i.tagName === "FIELDSET") return false;
        return i.type === "checkbox" || i.type === "radio" ? i.checked : String(i.value || "").trim() !== "";
      }).length;
    }
    function sync() {
      btn.textContent = T("stats.mobile.filters", { n: count() });
      btn.setAttribute("aria-expanded", form.classList.contains("filt-open") ? "true" : "false");
    }
    btn.addEventListener("click", function () { form.classList.toggle("filt-open"); sync(); });
    form.addEventListener("input", sync);
    form.addEventListener("change", sync);
    form.addEventListener("reset", function () { setTimeout(sync, 0); });
    document.addEventListener("i18n:change", sync);
    sync();
    return { button: btn, sync: sync };
  }

  function setTitle(name) {
    document.title = name === "tabela" ? "Tabela Gara de Nord"
      : (TITLES.indexOf(name) >= 0 ? T("title." + name) : "Tabela Gara de Nord") + " · Tabela Gara de Nord";
  }

  function route() {
    var r = parseHash();
    var name = r.name;
    currentRoute = name;
    if (!pageCssReady(name)) {   // route() runs again when the stylesheet is in
      if (!shownRoute) VIEWS.forEach(function (v) { var sec = $("view-" + v); if (sec) sec.hidden = true; });   // first load: not the board meanwhile
      return;
    }
    var changed = name !== shownRoute;
    // a heavy view drops its DOM (and timers) when left; it is drawn again from its cached data on return
    var prev = shownRoute && window.TabelaApp.views[shownRoute];
    if (changed && prev && typeof prev.hide === "function") prev.hide();
    shownRoute = name;
    document.documentElement.removeAttribute("data-deeplink");   // theme-init.js kept the board unpainted until now
    if (name === "ocr") loadOcrView();
    if (name === "ocr2") loadLazyPage("ocr2", "ocr2.js", "ocr2.css");
    if (name === "admin") loadAdminView();
    if (name === "sistem") loadLazyPage("sistem", "sistem.js", "sistem.css");
    if (name === "setari") loadLazyPage("setari", "setari.js");
    VIEWS.forEach(function (v) {
      var sec = $("view-" + v);
      if (sec) sec.hidden = v !== name;
    });
    document.querySelectorAll(".nav-item, .nav-more-link").forEach(function (a) {
      if (a.dataset.route === (NAV_PARENT[name] || name)) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    revealActiveNav();
    document.body.setAttribute("data-route", name);   // Beta 1.26: page canvas (ui2.css)
    // a view may refine the title later (stats.js: „Tren 1636 · …”)
    setTitle(name);
    var view = window.TabelaApp.views[name];
    if (view && typeof view.show === "function") view.show(r.params);
    if (changed) {
      window.scrollTo(0, 0);
      // page transition for every page except the live board (which is left exactly as it was)
      var ui2 = window.TabelaApp.ui2;
      if (ui2 && name !== "tabela" && name !== "ocr" && name !== "ocr2") ui2.enterView($("view-" + name));
    }
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
  window.TabelaApp.views = window.TabelaApp.views || {};
  window.TabelaApp.views.setari = {
    show: function () {
      if (window.TabelaSetari) window.TabelaSetari.mount($("view-setari"));
    }
  };
  if (typeof window.TabelaApp.onFollow !== "function") {
    window.TabelaApp.onFollow = function () {
      toast(T("app.followSoon"));
    };
  }
  window.TabelaApp.toast = toast;
  window.TabelaApp.config = loadConfig;   // Promise of the validated /api/config
  // the "uncertain reading" marker follows the active language
  Object.defineProperty(window.TabelaApp, "UNSURE", { get: unsureText, configurable: true, enumerable: true });
  window.TabelaApp.refresh = refresh;
  window.TabelaApp.el = el;
  window.TabelaApp.icon = icon;
  window.TabelaApp.filterToggle = filterToggle;
  window.TabelaApp.ICONS = ICONS;
  window.TabelaApp.typeClass = typeClass;
  window.TabelaApp.typeAbbr = typeAbbr;
  window.TabelaApp.typeName = typeName;
  window.TabelaApp.refreshFollowButtons = refreshFollowButtons;
  window.TabelaApp.boardTrains = function () {
    return state.data ? state.data.arrivals.concat(state.data.departures) : [];
  };

  // Offline support: register the service worker on secure origins (HTTPS / localhost).
  function registerSW() {
    if (!("serviceWorker" in navigator) || !window.isSecureContext) return null;
    if (!window.TabelaApp.swReady) {
      window.TabelaApp.swReady = navigator.serviceWorker.register("/sw.js", { scope: "/" })
        .catch(function (e) { window.TabelaApp.swReady = null; throw e; });
    }
    return window.TabelaApp.swReady;
  }
  window.TabelaApp.registerSW = registerSW;

  // ---- theme toggle (logic in theme-init.js, loaded first in <head>) ----------------

  var THEME_NEXT = { auto: "light", light: "dark", dark: "auto" };

  function renderThemeButtons() {
    var T = window.TabelaTheme, T_ = window.I18N ? window.I18N.t : function (k) { return k; };
    if (!T) return;
    var mode = T.get();
    document.querySelectorAll("[data-theme-toggle]").forEach(function (b) {
      var label = T_("theme.label", { mode: T_("theme.mode." + mode) });
      b.dataset.mode = mode;
      b.setAttribute("aria-label", label);
      var txt = b.querySelector(".pnl-btn-text"); // the Panou copy has visible text
      if (txt) txt.textContent = label;
      b.title = label + (mode === "auto" ? " (" + T_("theme.followsSystem") + ")" : "") +
        ". " + T_("theme.pressFor", { next: T_("theme.mode." + THEME_NEXT[mode]) });
    });
  }

  function initTheme() {
    var b = $("theme-btn");
    if (!b || !window.TabelaTheme) { if (b) b.hidden = true; return; }
    b.setAttribute("data-theme-toggle", "");
    b.addEventListener("click", function () { window.TabelaTheme.next(); });
    document.addEventListener("tabela:theme", renderThemeButtons);
    renderThemeButtons();
  }
  window.TabelaApp.renderThemeButtons = renderThemeButtons;

  // ---- "Peron estimat": lazy layer (peron_est.js/.css), not in the SW shell (precache budget) ----

  var peronLoad = null;
  function loadPeronEst() {
    if (peronLoad) return peronLoad;
    peronLoad = new Promise(function (resolve) {
      var css = document.createElement("link");
      css.rel = "stylesheet";
      css.href = "peron_est.css?v=1";
      document.head.appendChild(css);
      var js = document.createElement("script");
      js.src = "peron_est.js?v=1";
      js.onload = function () {
        if (state.data) BOARDS.forEach(function (b) { renderBoard(b, state.data[b] || []); });
        resolve(true);
      };
      js.onerror = function () { peronLoad = null; resolve(false); };
      document.head.appendChild(js);
    });
    return peronLoad;
  }
  window.TabelaApp.peronEstLoad = loadPeronEst;

  function initPeronEst() {
    var on = false;
    try { on = localStorage.getItem("tabela.peronEst") === "1"; } catch (e) { /* ignore */ }
    var box = $("pe-toggle");
    if (box) {
      box.checked = on;   // at once, before the lazy layer arrives
      // save the choice here, not in peron_est.js: that listener exists only after the lazy layer loaded,
      // so a quick tick + reload before that lost the setting (Beta 1.56)
      box.addEventListener("change", function () {
        try { localStorage.setItem("tabela.peronEst", box.checked ? "1" : "0"); } catch (e) { /* storage indisponibil */ }
        loadPeronEst();
      });
    }
    if (on) loadPeronEst();
  }

  // ---- boot ------------------------------------------------------------------------

  // Text next to a link (data-i18n would wipe the link): replace only the text node at one edge.
  function setEdge(node, last, text) {
    var n = node && (last ? node.lastChild : node.firstChild);
    if (n && n.nodeType === 3) n.nodeValue = text;
  }

  function applyShellText() {
    setEdge(document.querySelector(".live-src"), false, T("app.sourceLabel") + " ");
    setEdge(document.querySelector(".footer p"), false, "© 2026 Andy217Ace · " + T("footer.credit") + " ");
    var fm = document.querySelector(".footer-meteo");
    setEdge(fm, false, T("footer.meteo") + " ");
    setEdge(fm, true, " " + T("footer.meteoTail"));
  }

  // Every dynamic string is rebuilt from the data already in memory, in the active language.
  function relocalize() {
    if (window.I18N) window.I18N.applyDom(document);
    applyShellText();
    if (state.data) {
      BOARDS.forEach(function (b) { renderBoard(b, state.data[b]); markPanelStale(b, state.data); });
    } else if (state.failed) {
      showLoadFailure();
    }
    renderLive();
    renderThemeButtons();
    setTitle(currentRoute || "tabela");
  }
  document.addEventListener("i18n:change", relocalize);

  // Comutator RO/EN: butonul arată limba la care se trece; după setLang reaplicăm textele data-i18n.
  function initLang() {
    var I = window.I18N, btn = document.querySelector("[data-lang-toggle]");
    if (!I) return;
    function sync() {
      document.documentElement.lang = I.lang();
      relocalize();
      if (btn) btn.textContent = I.lang() === "en" ? "RO" : "EN";
    }
    I.ready.then(sync);
    if (!btn) return;
    btn.addEventListener("click", function () {
      var next = I.lang() === "en" ? "ro" : "en";
      I.setLang(next).then(function () {
        try {
          var u = new URL(location.href);
          u.searchParams.set("lang", next);
          history.replaceState(null, "", u.pathname + u.search + u.hash);
        } catch (e) { /* ignore */ }
        sync();
      });
    });
  }

  function init() {
    initMoreNav();   // before initLang: its links get the dictionary texts too
    initLang();
    initPeronEst();
    loadConfig();
    initTheme();
    initTabs();
    route();
    window.addEventListener("hashchange", function () {
      var u = window.TabelaApp.ui2;   // Beta 1.28: the page change runs inside a View Transition when the browser has them
      if (u && u.transition) u.transition(route); else route();
    });
    var navT = null;
    window.addEventListener("resize", function () {
      clearTimeout(navT);
      navT = setTimeout(revealActiveNav, 150);
    });
    setInterval(renderLive, 1000);
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "visible") refresh();
    });
    refresh();
    var sw = registerSW();
    if (sw) sw.catch(function () { /* offline mode unavailable; the page still works */ });
  }

  // Deferred scripts (history.js, follows.js) run before DOMContentLoaded and register
  // their views first, so the initial route can show them.
  // The dictionaries must be loaded before the first render (t() returns the key until then).
  function boot() { (window.I18N ? window.I18N.ready : Promise.resolve()).then(init); }
  if (document.readyState === "complete") boot();
  else document.addEventListener("DOMContentLoaded", boot);
})();
