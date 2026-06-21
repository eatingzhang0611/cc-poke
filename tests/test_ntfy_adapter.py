import pytest

from cc_poke.adapters import make_adapter
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
