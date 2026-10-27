// © 2026 Andy217Ace
// Tabela Gara de Nord — service worker (scope "/").
// - App shell precached; network-first so a deploy is picked up at once, cache when offline.
// - /api/board: network-first; the last good board is kept and served when offline, with
//   "sw_offline": true and "sw_cached_at" (ms) added to the JSON so the page can mark it old.
// - No other /api call is ever cached (history, follows, push, weather are always live;
//   weather.js keeps its last value in memory and marks it "date vechi" when offline).
// - Web Push: shows {title, body, tag, url}; a click focuses/opens `url` (same origin only).
// Bump VERSION when the shell list changes; old caches are deleted on activate.
"use strict";

var VERSION = "v26";
var SHELL_CACHE = "tabela-shell-" + VERSION;
var BOARD_CACHE = "tabela-board-" + VERSION;
var BOARD_URL = "/api/board";
var OFFLINE_URL = "/offline.html";
var SHELL = [
  "/",
  OFFLINE_URL,
  "/theme-init.js",
  "/style.css",
  "/panel.css",
  "/app.js",
  "/history.js",
  "/follows.js",
  "/panel.js",
  "/weather.css",
  "/weather.js",
  "/versions.js",
  "/stats.css",
  "/stats.js",
  "/statistici.css",
  "/statistici.js",
  "/manifest.webmanifest",
  "/favicon.ico",
  "/icons/logo-96.png",
  "/icons/logo-192.png",
  "/icons/favicon-16.png",
  "/icons/favicon-32.png",
  "/icons/icon-192.png",
  "/icons/apple-touch-icon.png",
  "/fonts/fira-sans-400.woff2",
  "/fonts/fira-code.woff2"
];
// the other Fira Sans weights (500/600/700) load on demand (HTTP cache); offline they fall
// back to the 400 weight (synthetic bold) — keeps the precache inside its budget
// icon-512 / maskable are fetched by the browser from the manifest; not precached.
var DEFAULT_TITLE = "Gara de Nord";

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      .then(function (cache) { return cache.addAll(SHELL.map(function (u) { return new Request(u, { cache: "reload" }); })); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (event) {
  var keep = [SHELL_CACHE, BOARD_CACHE];
  event.waitUntil(
    caches.keys()
      .then(function (keys) {
        return Promise.all(keys.filter(function (k) {
          return k.indexOf("tabela-") === 0 && keep.indexOf(k) < 0;
        }).map(function (k) { return caches.delete(k); }));
      })
      .then(function () { return self.clients.claim(); })
  );
});

function boardFromNetwork(event) {
  return fetch(event.request).then(function (resp) {
    if (resp && resp.ok) {
      var copy = resp.clone();
      event.waitUntil(copy.json().then(function (data) {
        data.sw_cached_at = Date.now();
        var body = JSON.stringify(data);
        return caches.open(BOARD_CACHE).then(function (c) {
          return c.put(BOARD_URL, new Response(body, { headers: { "Content-Type": "application/json" } }));
        });
      }).catch(function () { /* not JSON: do not cache */ }));
    }
    return resp;
  });
}

function boardFromCache(err) {
  return caches.open(BOARD_CACHE)
    .then(function (c) { return c.match(BOARD_URL); })
    .then(function (hit) {
      if (!hit) throw err;
      return hit.json().then(function (data) {
        data.sw_offline = true;
        return new Response(JSON.stringify(data), { headers: { "Content-Type": "application/json" } });
      });
    });
}

function shellNetworkFirst(request, fallbackUrl, lastResort) {
  return fetch(request).catch(function (err) {
    return caches.open(SHELL_CACHE).then(function (c) {
      return c.match(fallbackUrl || request, { ignoreSearch: true }).then(function (hit) {
        return hit || (lastResort ? c.match(lastResort) : undefined);
      });
    }).then(function (hit) {
      if (hit) return hit;
      throw err;
    });
  });
}

self.addEventListener("fetch", function (event) {
  var req = event.request;
  if (req.method !== "GET") return;
  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // fonts etc.: browser default
  if (url.pathname === BOARD_URL) {
    event.respondWith(boardFromNetwork(event).catch(boardFromCache));
    return;
  }
  if (url.pathname.indexOf("/api/") === 0) return; // never cached
  if (req.mode === "navigate") {
    // the cached app shell first (it shows the last board); the offline page otherwise
    event.respondWith(shellNetworkFirst(req, url.pathname === OFFLINE_URL ? OFFLINE_URL : "/", OFFLINE_URL));
    return;
  }
  if (SHELL.indexOf(url.pathname) >= 0) {
    event.respondWith(shellNetworkFirst(req));
  }
});

function sameOriginUrl(raw) {
  try {
    var u = new URL(raw || "/", self.location.origin);
    return u.origin === self.location.origin ? u.href : self.location.origin + "/";
  } catch (e) {
    return self.location.origin + "/";
  }
}

self.addEventListener("push", function (event) {
  var data = {};
  if (event.data) {
    try { data = event.data.json() || {}; } catch (e) { data = { body: event.data.text() }; }
  }
  var title = typeof data.title === "string" && data.title ? data.title : DEFAULT_TITLE;
  var opts = {
    body: typeof data.body === "string" ? data.body : "",
    icon: "/icons/icon-192.png",
    badge: "/icons/icon-192.png",
    lang: "ro",
    data: { url: sameOriginUrl(data.url) }
  };
  if (typeof data.tag === "string" && data.tag) {
    opts.tag = data.tag;
    opts.renotify = true;
  }
  event.waitUntil(self.registration.showNotification(title, opts));
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  var target = sameOriginUrl(event.notification.data && event.notification.data.url);
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (list) {
      for (var i = 0; i < list.length; i++) {
        var c = list[i];
        if (c.url.indexOf(self.location.origin) === 0 && "focus" in c) {
          if (c.url !== target && "navigate" in c) {
            return c.navigate(target).then(function (w) { return (w || c).focus(); })
              .catch(function () { return c.focus(); });
          }
          return c.focus();
        }
      }
      return self.clients.openWindow(target);
    })
  );
});
