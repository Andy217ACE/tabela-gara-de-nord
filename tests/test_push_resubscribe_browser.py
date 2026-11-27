# © 2026 Andy217Ace
"""Real-browser check of the VAPID self-heal in follows.js: a push subscription created
with an old applicationServerKey is replaced on app open and its follows are moved
server-side (POST /api/push/resubscribe). The browser's PushManager is stubbed (headless
Chromium cannot reach a real push service). Skipped without Playwright/Chromium."""
import base64
import socket
import threading
import time

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

import uvicorn  # noqa: E402

from app.api import create_app  # noqa: E402
from app.config import Settings  # noqa: E402
from tests.test_footer_browser import browser  # noqa: E402,F401  (shared fixture)

KEY = bytes([4]) + bytes(range(1, 65))        # 65-byte uncompressed P-256 point shape
KEY_B64 = base64.urlsafe_b64encode(KEY).rstrip(b"=").decode()
EP_OLD = "https://fcm.googleapis.com/fcm/send/old-sub"
EP_NEW = "https://fcm.googleapis.com/fcm/send/new-sub"

STUB = """
(() => {
  const toBuf = a => new Uint8Array(a).buffer;
  const OLD_KEY = %s;
  window.__push = { unsubscribed: 0, subscribed: 0 };
  let current = {
    endpoint: "%s", options: { applicationServerKey: toBuf(OLD_KEY) },
    toJSON() { return { endpoint: this.endpoint, keys: { p256dh: "p".repeat(20), auth: "a".repeat(10) } }; },
    unsubscribe() { window.__push.unsubscribed++; current = null; return Promise.resolve(true); }
  };
  const pushManager = {
    getSubscription: () => Promise.resolve(current),
    subscribe(opts) {
      window.__push.subscribed++;
      current = {
        endpoint: "%s", options: { applicationServerKey: toBuf(opts.applicationServerKey) },
        toJSON() { return { endpoint: this.endpoint, keys: { p256dh: "q".repeat(20), auth: "b".repeat(10) } }; },
        unsubscribe() { current = null; return Promise.resolve(true); }
      };
      return Promise.resolve(current);
    }
  };
  Object.defineProperty(Notification, "permission", { get: () => "granted" });
  const reg = { pushManager };
  navigator.serviceWorker.getRegistration = () => Promise.resolve(reg);
  navigator.serviceWorker.register = () => Promise.resolve(reg);
})();
"""


@pytest.fixture
def server(tmp_path):
    settings = Settings(db_path=str(tmp_path / "p.db"), source_url="http://127.0.0.1:9/none",
                        vapid_private_key="x", vapid_public_key=KEY_B64,
                        vapid_subject="mailto:a@b.c", tesseract_cmd="tesseract",
                        poller_enabled=False, last_image_path=None)
    app = create_app(settings, start_poller=False)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    store = app.state.store
    store.subscribe(EP_OLD, "p" * 20, "a" * 10)
    store.follow(EP_OLD, 1636, "2099-01-01")
    yield f"http://127.0.0.1:{port}", store
    srv.should_exit = True
    t.join(5)


def _open(browser, base, old_key):  # noqa: F811
    # bypass_csp: wait_for_function polls via eval, which the strict CSP blocks (intermittent EvalError in CI)
    ctx = browser.new_context(service_workers="block", bypass_csp=True)
    ctx.add_init_script(STUB % (list(old_key), EP_OLD, EP_NEW))
    ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(base) else r.abort())
    page = ctx.new_page()
    page.goto(base + "/")
    return ctx, page


def test_old_key_subscription_is_replaced_and_follows_moved(browser, server):  # noqa: F811
    base, store = server
    ctx, page = _open(browser, base, bytes([4]) + bytes(64))   # created with another key
    try:
        page.wait_for_function("window.__push.subscribed === 1", timeout=10000)
        page.wait_for_function("localStorage.getItem('tabela.push.endpoint') === '%s'" % EP_NEW,
                               timeout=10000)
        assert page.evaluate("window.__push.unsubscribed") == 1
    finally:
        ctx.close()
    assert store.get_subscription(EP_OLD) is None
    assert [f["train_no"] for f in store.list_follows(EP_NEW)] == [1636]


def test_current_key_subscription_is_kept(browser, server):  # noqa: F811
    base, store = server
    ctx, page = _open(browser, base, KEY)
    try:
        page.wait_for_function("localStorage.getItem('tabela.push.endpoint') === '%s'" % EP_OLD,
                               timeout=10000)
        page.wait_for_timeout(300)
        assert page.evaluate("window.__push") == {"unsubscribed": 0, "subscribed": 0}
    finally:
        ctx.close()
    assert len(store.list_follows(EP_OLD)) == 1
