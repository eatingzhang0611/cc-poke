import pytest

from cc_poke.adapters import make_adapter
from cc_poke.adapters.base import Action
from cc_poke.adapters.ntfy import NtfyAdapter
from cc_poke.config import Config


class _RecordingPoster:
    def __init__(self, status=200, raises=None):
        self.status = status
        self.raises = raises
        self.calls = []

    def __call__(self, url, data, headers, timeout):
        self.calls.append({"url": url, "data": data, "headers": headers, "timeout": timeout})
        if self.raises is not None:
            raise self.raises
        return self.status


def test_send_posts_to_topic_url_and_returns_true():
    poster = _RecordingPoster(status=200)
    adapter = NtfyAdapter("https://ntfy.sh", "topic123", poster=poster)
    ok = adapter.send("cc-poke", "Claude is waiting")
    assert ok is True
    call = poster.calls[0]
    assert call["url"] == "https://ntfy.sh/topic123"
    assert call["headers"]["Title"] == "cc-poke"
    assert call["data"] == "Claude is waiting".encode("utf-8")
    assert call["timeout"] == 10.0


def test_send_returns_false_on_non_2xx():
    adapter = NtfyAdapter("https://ntfy.sh", "t", poster=_RecordingPoster(status=500))
    assert adapter.send("x", "y") is False


def test_send_returns_false_on_exception_never_raises():
    adapter = NtfyAdapter("https://ntfy.sh", "t", poster=_RecordingPoster(raises=OSError("boom")))
    assert adapter.send("x", "y") is False


def test_body_utf8_encoded():
    poster = _RecordingPoster(status=200)
    adapter = NtfyAdapter("https://ntfy.sh", "t", poster=poster)
    adapter.send("cc-poke", "Claude 在等你")
    assert poster.calls[0]["data"] == "Claude 在等你".encode("utf-8")


def test_make_adapter_ntfy():
    cfg = Config(ntfy_server="https://ntfy.sh", ntfy_topic="t", adapter="ntfy")
    adapter = make_adapter(cfg)
    assert isinstance(adapter, NtfyAdapter)


def test_make_adapter_unknown_raises():
    cfg = Config(ntfy_server="https://ntfy.sh", ntfy_topic="t", adapter="carrier-pigeon")
    with pytest.raises(ValueError):
        make_adapter(cfg)


def test_send_includes_actions_header():
    poster = _RecordingPoster(status=200)
    adapter = NtfyAdapter("https://ntfy.sh", "t", poster=poster)
    adapter.send("title", "body", [
        Action("Approve", "https://x/webhook?id=1&d=allow&s=k"),
        Action("Deny", "https://x/webhook?id=1&d=deny&s=k"),
    ])
    hdr = poster.calls[0]["headers"]["Actions"]
    assert "http, Approve, https://x/webhook?id=1&d=allow&s=k, method=POST, clear=true" in hdr
    assert "http, Deny, https://x/webhook?id=1&d=deny&s=k, method=POST, clear=true" in hdr
    assert "; " in hdr


def test_send_no_actions_header_when_omitted():
    poster = _RecordingPoster(status=200)
    NtfyAdapter("https://ntfy.sh", "t", poster=poster).send("t", "b")
    assert "Actions" not in poster.calls[0]["headers"]


def test_send_sets_click_header_when_provided():
    poster = _RecordingPoster(status=200)
    adapter = NtfyAdapter("https://ntfy.sh", "t", poster=poster)
    adapter.send("title", "body", click="https://x/d?id=1&s=k")
    assert poster.calls[0]["headers"]["Click"] == "https://x/d?id=1&s=k"


def test_send_no_click_header_when_not_provided():
    poster = _RecordingPoster(status=200)
    NtfyAdapter("https://ntfy.sh", "t", poster=poster).send("t", "b")
    assert "Click" not in poster.calls[0]["headers"]
