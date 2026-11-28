# © 2026 Andy217Ace
"""Shared helper for browser tests: record same-origin request failures, except requests the
browser itself aborted because the page navigated/reloaded (normal, not an app error)."""

# Chromium: net::ERR_ABORTED, Firefox: NS_BINDING_ABORTED, WebKit: "cancelled"
ABORTED = ("ERR_ABORTED", "NS_BINDING_ABORTED", "cancelled")


def is_aborted(failure):
    return any(a in (failure or "") for a in ABORTED)


def on_request_failed(page, base_url, errors):
    def record(r):
        if r.url.startswith(base_url) and not is_aborted(r.failure):
            errors.append("failed " + r.url + " (" + str(r.failure) + ")")
    page.on("requestfailed", record)

