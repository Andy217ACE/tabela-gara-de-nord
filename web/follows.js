// © 2026 Andy217Ace
// Tabela Gara de Nord — Urmărite: follow trains and get Web Push notifications.
// Anonymous: the only thing kept on the device is the push subscription endpoint
// (localStorage). DOM built with createElement/textContent only (CSP).
"use strict";

(function () {
  var App = window.TabelaApp;
  var el = App.el;
  var TZ = "Europe/Bucharest";
  var EP_KEY = "tabela.push.endpoint";
  var TIMEOUT_MS = 10000;
  var MSG_UNSUPPORTED = "Notificările necesită conexiune sigură (HTTPS) și un browser compatibil.";
  var MSG_IOS = "Pe iPhone, adaugă mai întâi aplicația pe ecranul principal.";

  var $ = function (id) { return document.getElementById(id); };
  var state = {
    endpoint: null,     // current subscription endpoint (or null)
    follows: [],        // [{train_no, date}]
    loaded: false,
    busy: false
  };

  // ---- environment ---------------------------------------------------------------

  function todayBucharest() {
    return new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit",
                                              day: "2-digit" }).format(new Date());
  }

  function isIOS() {
    var ua = navigator.userAgent || "";
    return /iPad|iPhone|iPod/.test(ua) ||
      (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  }

  function isStandalone() {
    return (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) ||
      navigator.standalone === true;
  }

  function supported() {
    return !!(window.isSecureContext && "serviceWorker" in navigator &&
              "PushManager" in window && "Notification" in window);
  }

  // iOS exposes push only to home-screen apps; the generic message covers the rest.
  function unsupportedReason() {
    if (isIOS() && !isStandalone()) return MSG_IOS;
    return supported() ? null : MSG_UNSUPPORTED;
  }

  // ---- storage (best effort) ----------------------------------------------------------

  function loadEndpoint() {
    try { return localStorage.getItem(EP_KEY); } catch (e) { return null; }
  }

  function saveEndpoint(ep) {
    try {
      if (ep) localStorage.setItem(EP_KEY, ep);
      else localStorage.removeItem(EP_KEY);
    } catch (e) { /* storage unavailable: the browser subscription is still the source */ }
  }

  // ---- HTTP -----------------------------------------------------------------------------

  function api(method, url, body) {
    var ctrl = new AbortController();
    var to = setTimeout(function () { ctrl.abort(); }, TIMEOUT_MS);
    var opts = { method: method, signal: ctrl.signal, cache: "no-store",
                 headers: { Accept: "application/json" } };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    return fetch(url, opts).then(function (r) {
      return r.json().catch(function () { return null; }).then(function (data) {
        if (!r.ok) {
          var err = new Error((data && typeof data.detail === "string" && data.detail) ||
                              "Eroare la server (" + r.status + ").");
          err.status = r.status;
          throw err;
        }
        return data;
      });
    }, function () {
      throw new Error(navigator.onLine === false ? "Ești offline." : "Serverul nu a răspuns. Încearcă din nou.");
    }).finally(function () { clearTimeout(to); });
  }

  // VAPID public key (base64url) -> Uint8Array for applicationServerKey
  function urlBase64ToUint8Array(b64) {
    var padding = "=".repeat((4 - (b64.length % 4)) % 4);
    var base64 = (b64 + padding).replace(/-/g, "+").replace(/_/g, "/");
    var raw = atob(base64);
    var out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  // ---- subscription ----------------------------------------------------------------------

  function registration() {
    var p = App.registerSW && App.registerSW();
    if (!p) return Promise.reject(new Error(MSG_UNSUPPORTED));
    return p.then(function () { return navigator.serviceWorker.ready; });
  }

  function currentSubscription() {
    if (!supported()) return Promise.resolve(null);
    return navigator.serviceWorker.getRegistration("/").then(function (reg) {
      return reg && reg.pushManager ? reg.pushManager.getSubscription() : null;
    }).catch(function () { return null; });
  }

  // Ask permission (first use), subscribe the browser and register it with the server.
  function ensureSubscription() {
    var reason = unsupportedReason();
    if (reason) return Promise.reject(new Error(reason));
    if (Notification.permission === "denied") {
      return Promise.reject(new Error("Notificările sunt blocate pentru acest site. Activează-le din setările browserului."));
    }
    var perm = Notification.permission === "granted"
      ? Promise.resolve("granted") : Promise.resolve(Notification.requestPermission());
    return perm.then(function (p) {
      if (p !== "granted") throw new Error("Fără permisiunea pentru notificări nu pot urmări trenuri.");
      return registration();
    }).then(function (reg) {
      return reg.pushManager.getSubscription().then(function (sub) {
        if (sub) return sub;
        return api("GET", "/api/push/key").catch(function (e) {
          if (e.status === 404) throw new Error("Notificările nu sunt încă activate pe server.");
          throw e;
        }).then(function (data) {
          return reg.pushManager.subscribe({ userVisibleOnly: true,
                                             applicationServerKey: urlBase64ToUint8Array(data.key) });
        });
      });
    }).then(function (sub) {
      var json = sub.toJSON ? sub.toJSON() : sub;
      return api("POST", "/api/push/subscribe", { endpoint: json.endpoint, keys: json.keys })
        .then(function () {
          state.endpoint = json.endpoint;
          saveEndpoint(json.endpoint);
          return json.endpoint;
        });
    });
  }

  function disableNotifications() {
    var ep = state.endpoint;
    return currentSubscription().then(function (sub) {
      var tasks = [];
      if (ep) tasks.push(api("POST", "/api/push/unsubscribe", { endpoint: ep }).catch(function () { return null; }));
      if (sub) tasks.push(sub.unsubscribe().catch(function () { return false; }));
      return Promise.all(tasks);
    }).then(function () {
      state.endpoint = null;
      state.follows = [];
      saveEndpoint(null);
    });
  }

  // ---- follows -----------------------------------------------------------------------------

  function key(no, date) { return no + "|" + date; }

  function isFollowed(no, date) {
    return state.follows.some(function (f) { return key(f.train_no, f.date) === key(no, date); });
  }

  var MSG_PAST = "Trenul aparține unei zile trecute; se pot urmări doar trenurile de azi sau de mai târziu.";

  function trainDate(train) {
    return train.service_date || todayBucharest();
  }

  // The API only accepts follows dated today or later (Europe/Bucharest).
  function pastTrain(train) {
    return trainDate(train) < todayBucharest();
  }

  function loadFollows() {
    if (!state.endpoint) {
      state.follows = [];
      return Promise.resolve();
    }
    return api("GET", "/api/follows?endpoint=" + encodeURIComponent(state.endpoint))
      .then(function (data) {
        state.follows = Array.isArray(data && data.follows) ? data.follows : [];
      });
  }

  function follow(no, date) {
    return ensureSubscription().then(function (ep) {
      return api("POST", "/api/follow", { endpoint: ep, train: no, date: date });
    }).then(function () {
      if (!isFollowed(no, date)) state.follows.push({ train_no: no, date: date });
    });
  }

  function unfollow(no, date) {
    if (!state.endpoint) return Promise.resolve();
    return api("DELETE", "/api/follow", { endpoint: state.endpoint, train: no, date: date })
      .then(function () {
        state.follows = state.follows.filter(function (f) { return key(f.train_no, f.date) !== key(no, date); });
      });
  }

  // ---- UI -------------------------------------------------------------------------------------

  var dayFmt = new Intl.DateTimeFormat("ro-RO", { timeZone: "UTC", weekday: "short", day: "numeric", month: "short" });
  function dayLabel(iso) {
    var t = todayBucharest();
    if (iso === t) return "azi";
    var d = new Date(iso + "T12:00:00Z");
    return isNaN(d.getTime()) ? iso : dayFmt.format(d);
  }

  function titleCase(x) {
    return String(x || "").toLowerCase().replace(/(^|[\s\-.])(\S)/g, function (m, a, b) {
      return a + b.toUpperCase();
    });
  }

  function onBoard(no, date) {
    return App.boardTrains().filter(function (t) { return t.train_no === no && trainDate(t) === date; });
  }

  function renderList() {
    var list = $("f-list");
    if (!list) return;
    list.replaceChildren();
    var today = todayBucharest();
    var items = state.follows.slice().sort(function (a, b) {
      return a.date < b.date ? -1 : a.date > b.date ? 1 : a.train_no - b.train_no;
    });
    $("f-count").textContent = state.endpoint
      ? (items.length === 1 ? "1 tren urmărit" : items.length + " trenuri urmărite") : "";
    $("f-empty").hidden = items.length > 0 || !state.loaded;
    $("f-empty").textContent = state.endpoint
      ? "Nu urmărești niciun tren. Apasă „urmărește” pe un tren din tabelă."
      : "Nicio urmărire pe acest dispozitiv. Apasă „urmărește” pe un tren din tabelă pentru a activa notificările.";
    items.forEach(function (f) {
      var li = el("li", "f-item");
      var info = el("div", "f-info");
      var title = el("p", "f-title");
      var seen = onBoard(f.train_no, f.date);
      if (seen.length) {
        title.append(el("span", App.typeClass(seen[0].train_type), seen[0].train_type || "?"), document.createTextNode(" "));
      }
      title.append(el("span", "t-no", String(f.train_no)));
      var sub = el("p", "f-sub");
      var parts = [dayLabel(f.date)];
      if (f.date < today) parts.push("zi trecută");
      seen.forEach(function (t) {
        var d = Math.max(0, t.delay_min | 0);
        parts.push((t.sched_time || "") + " " + titleCase(t.station));
        // never "la timp" unless the delay cell was actually read (API delay_read)
        if (t.delay_read !== true) {
          var nr = el("span", "delay-unread", "necitit");
          nr.title = "Celula de întârziere nu a putut fi citită de pe tabela CFR";
          parts.push(nr);
        } else {
          parts.push(d ? "+" + d + " min" : "la timp");
        }
        if (t.platform != null && t.platform !== "") parts.push("linia " + t.platform);
      });
      if (f.date <= today && !seen.length) parts.push("nu e pe tabelă acum");
      sub.replaceChildren();
      parts.forEach(function (p, i) {
        if (i) sub.append(" · ");
        sub.append(p);
      });
      info.append(title, sub);
      var hist = el("a", "f-link", "Istoric");
      hist.href = "#istoric?date=" + encodeURIComponent(f.date <= today ? f.date : today) +
        "&train=" + encodeURIComponent(f.train_no);
      var btn = el("button", "btn btn-ghost btn-sm", "Nu mai urmări");
      btn.type = "button";
      btn.setAttribute("aria-label", "Nu mai urmări trenul " + f.train_no + " (" + dayLabel(f.date) + ")");
      btn.addEventListener("click", function () {
        btn.disabled = true;
        unfollow(f.train_no, f.date).then(function () {
          App.toast("Nu mai urmărești trenul " + f.train_no + ".");
          renderAll();
        }, function (e) {
          btn.disabled = false;
          App.toast(e.message);
        });
      });
      var actions = el("div", "f-actions");
      actions.append(hist, btn);
      li.append(info, actions);
      list.append(li);
    });
  }

  function renderSwitch() {
    var sw = $("f-switch");
    if (!sw) return;
    var reason = unsupportedReason();
    var support = $("f-support"), ios = $("f-ios");
    support.hidden = !reason || reason === MSG_IOS;
    support.textContent = reason && reason !== MSG_IOS ? reason : "";
    ios.hidden = reason !== MSG_IOS;
    ios.textContent = reason === MSG_IOS ? MSG_IOS : "";
    sw.disabled = !!reason || state.busy;
    sw.checked = !!state.endpoint;
    var status = $("f-status");
    if (reason) status.textContent = "Notificări indisponibile pe acest dispozitiv.";
    else if (state.busy) status.textContent = "Se actualizează…";
    else if ("Notification" in window && Notification.permission === "denied") {
      status.textContent = "Notificările sunt blocate pentru acest site din setările browserului.";
    } else status.textContent = state.endpoint
      ? "Activate. Primești notificări pentru trenurile urmărite."
      : "Dezactivate. Se activează automat când urmărești primul tren.";
  }

  function renderAll() {
    renderSwitch();
    renderList();
    App.refreshFollowButtons();
  }

  // Board button handler (called by app.js)
  function onFollow(train, button) {
    var reason = unsupportedReason() || (pastTrain(train) ? MSG_PAST : null);
    if (reason) {
      App.toast(reason);
      return;
    }
    if (state.busy) return;
    var no = train.train_no;
    var date = trainDate(train);
    var was = isFollowed(no, date);
    state.busy = true;
    if (button) button.setAttribute("aria-busy", "true");
    (was ? unfollow(no, date) : follow(no, date)).then(function () {
      App.toast(was ? "Nu mai urmărești trenul " + no + "."
                    : "Urmărești trenul " + no + ". Primești notificare la schimbări.");
    }, function (e) {
      App.toast(e.message || "Nu am putut actualiza urmărirea.");
    }).then(function () {
      state.busy = false;
      state.loaded = true;
      if (button) button.removeAttribute("aria-busy");
      renderAll();
    });
  }

  function followState(train) {
    var reason = unsupportedReason() || (pastTrain(train) ? MSG_PAST : null);
    return { followed: !reason && isFollowed(train.train_no, trainDate(train)),
             unsupported: !!reason, reason: reason || "" };
  }

  function refresh() {
    // The browser's own subscription wins over what we remembered.
    return currentSubscription().then(function (sub) {
      var ep = sub ? sub.endpoint : null;
      if (!ep && !supported()) ep = null;
      state.endpoint = ep;
      if (ep !== loadEndpoint()) saveEndpoint(ep);
      return loadFollows();
    }).catch(function (e) {
      if (e && e.status === 422) { state.endpoint = null; saveEndpoint(null); }
      else App.toast("Nu am putut încărca trenurile urmărite. " + (e && e.message ? e.message : ""));
    }).then(function () {
      state.loaded = true;
      renderAll();
    });
  }

  function onSwitch() {
    var sw = $("f-switch");
    var want = sw.checked;
    state.busy = true;
    renderSwitch();
    (want ? ensureSubscription().then(loadFollows) : disableNotifications()).then(function () {
      App.toast(want ? "Notificări activate." : "Notificări dezactivate. Urmăririle au fost șterse.");
    }, function (e) {
      App.toast(e.message || "Nu am putut schimba setarea.");
    }).then(function () {
      state.busy = false;
      renderAll();
    });
  }

  function init() {
    var sw = $("f-switch");
    if (sw) sw.addEventListener("change", onSwitch);
    state.endpoint = supported() ? loadEndpoint() : null;
    renderSwitch();
    if (supported()) refresh();
    else {
      state.loaded = true;
      renderAll();
    }
  }

  App.onFollow = onFollow;
  App.followState = followState;
  App.follows = { urlBase64ToUint8Array: urlBase64ToUint8Array, refresh: refresh };
  App.views.urmarite = { show: function () { if (supported()) refresh(); else renderAll(); } };
  init();
})();
