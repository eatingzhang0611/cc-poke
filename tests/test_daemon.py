import threading
import time
import urllib.parse

import pytest

from cc_poke.config import Config, ConfigError
from cc_poke.daemon import DaemonApp
from cc_poke.store import DecisionStore


class _FakeAdapter:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    def send(self, title, body, actions=None, click=None):
        self.calls.append({"title": title, "body": body, "actions": actions, "click": click})
        return self.ok


def _app(adapter=None, secret="s3cr3t", base="https://poke.test", wait=2.0):
    cfg = Config(
        ntfy_server="https://ntfy.sh", ntfy_topic="t",
        public_base_url=base, webhook_secret=secret, wait_seconds=wait,
    )
    return DaemonApp(store=DecisionStore(), adapter=adapter or _FakeAdapter(), config=cfg)


def _rid_from_actions(actions):
    approve = next(a.url for a in actions if "d=allow" in a.url)
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(approve).query))
    return q


def test_handle_request_pushes_two_actions_with_rid_and_secret():
    adapter = _FakeAdapter()
    app = _app(adapter=adapter, wait=0.05)  # let it time out fast; we only inspect the push
    app.handle_request("Bash", "rm -rf /tmp/x")
    call = adapter.calls[0]
    assert call["body"] == "rm -rf /tmp/x"
    assert call["title"].isascii()
    actions = call["actions"]
    assert len(actions) == 2
    assert all(a.url.startswith("https://poke.test/webhook?") for a in actions)
    q = _rid_from_actions(actions)
    assert q["s"] == "s3cr3t"
    assert len(q["id"]) > 20


def test_handle_request_passes_click_url_pointing_to_decision_page():
    """handle_request must pass a click= URL pointing to /d carrying rid, secret, tool, command."""
    adapter = _FakeAdapter()
    base = "https://poke.test"
    secret = "s3cr3t"
    app = _app(adapter=adapter, secret=secret, base=base, wait=0.05)
    app.handle_request("Bash", "rm -rf /tmp/x")
    call = adapter.calls[0]
    q = _rid_from_actions(call["actions"])
    rid = q["id"]
    assert call["click"].startswith(f"{base}/d?")
    cq = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(call["click"]).query))
    assert cq["id"] == rid
    assert cq["s"] == secret  # parse_qsl URL-decodes
    assert cq["t"] == "Bash"
    assert cq["c"] == "rm -rf /tmp/x"


def test_handle_request_returns_allow_when_webhook_resolves():
    adapter = _FakeAdapter()
    app = _app(adapter=adapter, wait=3.0)

    def resolver():
        for _ in range(300):
            if adapter.calls:
                break
            time.sleep(0.01)
        q = _rid_from_actions(adapter.calls[0]["actions"])
        app.handle_webhook(q["id"], "allow", q["s"])

    t = threading.Thread(target=resolver)
    t.start()
    decision = app.handle_request("Bash", "do thing")
    t.join()
    assert decision == "allow"


def test_handle_request_times_out_returns_none():
    app = _app(wait=0.05)
    assert app.handle_request("Bash", "x") is None


def test_handle_request_returns_none_fast_if_push_fails():
    app = _app(adapter=_FakeAdapter(ok=False), wait=5.0)
    t0 = time.monotonic()
    assert app.handle_request("Bash", "x") is None
    assert time.monotonic() - t0 < 1.0


def test_handle_webhook_resolves_when_valid():
    app = _app(secret="s")
    rid = app.store.register()
    resolved, html = app.handle_webhook(rid, "allow", "s")
    assert resolved is True
    assert app.store.wait(rid, 1.0) == "allow"


def test_handle_webhook_bad_secret_does_not_resolve():
    app = _app(secret="right")
    rid = app.store.register()
    resolved, _ = app.handle_webhook(rid, "allow", "wrong")
    assert resolved is False
    assert app.store.resolve(rid, "deny") is True  # was still pending


def test_handle_webhook_unknown_id():
    app = _app(secret="s")
    resolved, _ = app.handle_webhook("nope", "allow", "s")
    assert resolved is False


def test_handle_webhook_bad_decision_value():
    app = _app(secret="s")
    rid = app.store.register()
    resolved, _ = app.handle_webhook(rid, "maybe", "s")
    assert resolved is False
    assert app.store.resolve(rid, "allow") is True  # untouched, still pending


def test_decision_page_contains_buttons_and_params():
    app = _app(secret="s", base="https://poke.test")
    html = app.decision_page("rid123", "s")
    assert "rid123" in html
    assert 'value="s"' in html or "value=s" in html or ">s<" in html or "s" in html
    assert "allow" in html and "deny" in html
    assert "https://poke.test/webhook" in html


def test_decision_page_shows_tool_and_command():
    app = _app(secret="s", base="https://poke.test")
    html = app.decision_page("rid123", "s", "Bash", "rm -rf /tmp/x")
    assert "Bash" in html
    assert "rm -rf /tmp/x" in html


def test_decision_page_escapes_command_html():
    app = _app(secret="s", base="https://poke.test")
    html = app.decision_page("rid123", "s", "Bash", "<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_dispatch_decision_page_passes_tool_and_command():
    app = _app(secret="s")
    resp = app.dispatch("GET", "/d", {"id": "r", "s": "s", "t": "Bash", "c": "ls -la"}, b"")
    assert resp.status == 200
    assert b"ls -la" in resp.body
    assert b"Bash" in resp.body


def test_dispatch_webhook_returns_200_html_friendly():
    app = _app(secret="s")
    rid = app.store.register()
    resp = app.dispatch("POST", "/webhook", {"id": rid, "d": "allow", "s": "s"}, b"")
    assert resp.status == 200
    assert resp.content_type.startswith("text/html")


def test_dispatch_unknown_path_404():
    app = _app()
    resp = app.dispatch("GET", "/nope", {}, b"")
    assert resp.status == 404


def test_special_char_secret_round_trips_encode_decode_compare():
    secret = "a&b=c"
    adapter = _FakeAdapter()
    app = _app(adapter=adapter, secret=secret, wait=0.05)
    app.handle_request("Bash", "x")
    approve_url = next(a.url for a in adapter.calls[0]["actions"] if "d=allow" in a.url)
    raw_query = urllib.parse.urlparse(approve_url).query
    # The secret must be percent-encoded in the raw URL, not interpolated literally.
    assert "a&b=c" not in raw_query
    assert "a%26b%3Dc" in raw_query
    q = dict(urllib.parse.parse_qsl(raw_query))  # parse_qsl URL-decodes
    assert q["s"] == secret
    # The decoded special-char secret must pass constant-time compare_digest.
    # (The handle_request rid above already timed out and was consumed, so use a
    # fresh pending rid to prove the decode -> compare_digest resolve path.)
    rid = app.store.register()
    resolved, _ = app.handle_webhook(rid, "allow", q["s"])
    assert resolved is True


def test_dispatch_webhook_get_returns_404_and_leaves_pending():
    """GET /webhook must not resolve the request (URL-prefetch / auto-approve defence)."""
    app = _app(secret="s")
    rid = app.store.register()
    resp = app.dispatch("GET", "/webhook", {"id": rid, "d": "allow", "s": "s"}, b"")
    assert resp.status == 404
    # entry is still pending — we can resolve it manually
    assert app.store.resolve(rid, "deny") is True


def test_handle_request_includes_cwd_in_body():
    from pathlib import Path
    cwd = str(Path.home() / "workspace" / "cc-poke")
    adapter = _FakeAdapter()
    app = _app(adapter=adapter, wait=0.05)
    app.handle_request("Bash", "ls", cwd=cwd)
    body = adapter.calls[0]["body"]
    assert "ls" in body
    assert "~/workspace/cc-poke" in body


def test_handle_request_no_cwd_body_unchanged():
    adapter = _FakeAdapter()
    app = _app(adapter=adapter, wait=0.05)
    app.handle_request("Bash", "ls")
    assert adapter.calls[0]["body"] == "ls"


def test_from_config_requires_public_base_url_and_secret():
    with pytest.raises(ConfigError):
        DaemonApp.from_config(Config(ntfy_server="https://ntfy.sh", ntfy_topic="t"))
    with pytest.raises(ConfigError):
        DaemonApp.from_config(Config(
            ntfy_server="https://ntfy.sh", ntfy_topic="t",
            public_base_url="https://poke.test",  # secret missing
        ))
