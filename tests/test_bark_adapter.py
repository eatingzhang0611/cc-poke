import json

from cc_poke.adapters import make_adapter
from cc_poke.adapters.bark import BarkAdapter
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


def _payload(call):
    return json.loads(call["data"].decode("utf-8"))


def test_send_posts_json_to_push_endpoint_and_returns_true():
    poster = _RecordingPoster(status=200)
    adapter = BarkAdapter("https://api.day.app", "KEY123", poster=poster)
    ok = adapter.send("cc-poke", "Claude is waiting")
    assert ok is True
    call = poster.calls[0]
    assert call["url"] == "https://api.day.app/push"
    assert "application/json" in call["headers"]["Content-Type"]
    body = _payload(call)
    assert body["device_key"] == "KEY123"
    assert body["title"] == "cc-poke"
    assert body["body"] == "Claude is waiting"


def test_send_returns_false_on_non_2xx():
    adapter = BarkAdapter("https://api.day.app", "K", poster=_RecordingPoster(status=500))
    assert adapter.send("x", "y") is False


def test_send_returns_false_on_exception_never_raises():
    adapter = BarkAdapter("https://api.day.app", "K", poster=_RecordingPoster(raises=OSError("boom")))
    assert adapter.send("x", "y") is False


def test_send_uses_click_as_url_field():
    poster = _RecordingPoster(status=200)
    adapter = BarkAdapter("https://api.day.app", "K", poster=poster)
    adapter.send("t", "b", click="https://x/ccpoke/d?id=1&s=k")
    assert _payload(poster.calls[0])["url"] == "https://x/ccpoke/d?id=1&s=k"


def test_send_no_url_field_when_click_omitted():
    poster = _RecordingPoster(status=200)
    adapter = BarkAdapter("https://api.day.app", "K", poster=poster)
    adapter.send("t", "b")
    assert "url" not in _payload(poster.calls[0])


def test_send_sets_time_sensitive_level_by_default():
    poster = _RecordingPoster(status=200)
    adapter = BarkAdapter("https://api.day.app", "K", poster=poster)
    adapter.send("t", "b")
    assert _payload(poster.calls[0])["level"] == "timeSensitive"


def test_send_carries_unicode_title_and_body():
    poster = _RecordingPoster(status=200)
    adapter = BarkAdapter("https://api.day.app", "K", poster=poster)
    adapter.send("cc-poke 批准", "Claude 在等你")
    body = _payload(poster.calls[0])
    assert body["title"] == "cc-poke 批准"
    assert body["body"] == "Claude 在等你"


def test_server_trailing_slash_stripped():
    poster = _RecordingPoster(status=200)
    adapter = BarkAdapter("https://api.day.app/", "K", poster=poster)
    adapter.send("t", "b")
    assert poster.calls[0]["url"] == "https://api.day.app/push"


def test_make_adapter_bark():
    cfg = Config(ntfy_server="https://ntfy.sh", ntfy_topic="t", adapter="bark",
                 bark_server="https://api.day.app", bark_device_key="KEY123")
    adapter = make_adapter(cfg)
    assert isinstance(adapter, BarkAdapter)


def test_make_adapter_bark_requires_device_key():
    cfg = Config(ntfy_server="https://ntfy.sh", ntfy_topic="t", adapter="bark",
                 bark_server="https://api.day.app", bark_device_key="")
    try:
        make_adapter(cfg)
    except ValueError:
        return
    assert False, "expected ValueError when bark_device_key is empty"
