import io
import json
from pathlib import Path

import cc_poke.notifier as notifier
from cc_poke.adapters.base import PushAdapter


class FakeAdapter(PushAdapter):
    def __init__(self, result=True):
        self.result = result
        self.sent = []

    def send(self, title: str, body: str) -> bool:
        self.sent.append((title, body))
        return self.result


def test_build_message_with_message_and_cwd():
    title, body = notifier.build_message({"message": "Needs permission", "cwd": "/home/user/p"})
    assert title == "cc-poke: Claude needs you"
    assert "Needs permission" in body
    assert "/home/user/p" in body


def test_build_message_defaults_when_empty():
    title, body = notifier.build_message({})
    assert title == "cc-poke: Claude needs you"
    assert body == "Claude is waiting for you"


def test_run_calls_adapter_and_returns_result():
    fake = FakeAdapter(result=True)
    assert notifier.run({"message": "hi"}, fake) is True
    assert fake.sent == [("cc-poke: Claude needs you", "hi")]


def _config_file(tmp_path: Path) -> Path:
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"ntfy_topic": "t"}), encoding="utf-8")
    return p


def test_main_sends_and_returns_zero(tmp_path, monkeypatch):
    fake = FakeAdapter(result=True)
    monkeypatch.setenv("CC_POKE_CONFIG", str(_config_file(tmp_path)))
    monkeypatch.setattr(notifier, "make_adapter", lambda cfg: fake)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"message": "Needs you", "cwd": "/x"})))
    assert notifier.main() == 0
    assert len(fake.sent) == 1
    assert "Needs you" in fake.sent[0][1]


def test_main_missing_config_returns_zero_and_does_not_send(tmp_path, monkeypatch):
    fake = FakeAdapter()
    monkeypatch.setenv("CC_POKE_CONFIG", str(tmp_path / "missing.json"))
    monkeypatch.setattr(notifier, "make_adapter", lambda cfg: fake)
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    assert notifier.main() == 0
    assert fake.sent == []


def test_main_bad_stdin_returns_zero_and_uses_default_message(tmp_path, monkeypatch):
    fake = FakeAdapter()
    monkeypatch.setenv("CC_POKE_CONFIG", str(_config_file(tmp_path)))
    monkeypatch.setattr(notifier, "make_adapter", lambda cfg: fake)
    monkeypatch.setattr("sys.stdin", io.StringIO("not-json{{{"))
    assert notifier.main() == 0
    assert fake.sent == [("cc-poke: Claude needs you", "Claude is waiting for you")]


def test_main_push_failure_still_returns_zero(tmp_path, monkeypatch):
    fake = FakeAdapter(result=False)
    monkeypatch.setenv("CC_POKE_CONFIG", str(_config_file(tmp_path)))
    monkeypatch.setattr(notifier, "make_adapter", lambda cfg: fake)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"message": "x"})))
    assert notifier.main() == 0
    assert len(fake.sent) == 1
