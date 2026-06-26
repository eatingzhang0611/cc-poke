import json
import time
from pathlib import Path

import cc_poke.stopper as stopper
from cc_poke.config import Config, ConfigError


def _cfg(**kwargs):
    defaults = dict(ntfy_server="https://ntfy.sh", ntfy_topic="t",
                    daemon_url="http://127.0.0.1:8787", allowlist=(), wait_seconds=1.0,
                    stop_quiet_seconds=300.0, bypass=False)
    defaults.update(kwargs)
    return Config(**defaults)


class _Stdin:
    def __init__(self, text):
        self._text = text

    def read(self):
        return self._text


class _Adapter:
    def __init__(self):
        self.calls = []

    def send(self, title, body):
        self.calls.append((title, body))
        return True


def test_stop_hook_active_skips_push(monkeypatch):
    adapter = _Adapter()
    monkeypatch.setattr(stopper, "load_config", lambda: _cfg())
    monkeypatch.setattr(stopper, "make_adapter", lambda cfg: adapter)
    monkeypatch.setattr("sys.stdin", _Stdin(json.dumps({"stop_hook_active": True})))
    assert stopper.main() == 0
    assert adapter.calls == []


def test_bypass_skips_push(monkeypatch):
    adapter = _Adapter()
    monkeypatch.setattr(stopper, "load_config", lambda: _cfg(bypass=True))
    monkeypatch.setattr(stopper, "make_adapter", lambda cfg: adapter)
    monkeypatch.setattr("sys.stdin", _Stdin("{}"))
    assert stopper.main() == 0
    assert adapter.calls == []


def test_quiet_period_skips_push(monkeypatch, tmp_path):
    ts_file = tmp_path / "last_stop.ts"
    ts_file.write_text(str(time.time()), encoding="utf-8")
    monkeypatch.setattr(stopper, "_LAST_STOP_PATH", ts_file)
    adapter = _Adapter()
    monkeypatch.setattr(stopper, "load_config", lambda: _cfg(stop_quiet_seconds=300.0))
    monkeypatch.setattr(stopper, "make_adapter", lambda cfg: adapter)
    monkeypatch.setattr("sys.stdin", _Stdin("{}"))
    assert stopper.main() == 0
    assert adapter.calls == []


def test_pushes_after_quiet_period_expires(monkeypatch, tmp_path):
    ts_file = tmp_path / "last_stop.ts"
    ts_file.write_text(str(time.time() - 400), encoding="utf-8")
    monkeypatch.setattr(stopper, "_LAST_STOP_PATH", ts_file)
    adapter = _Adapter()
    monkeypatch.setattr(stopper, "load_config", lambda: _cfg(stop_quiet_seconds=300.0))
    monkeypatch.setattr(stopper, "make_adapter", lambda cfg: adapter)
    monkeypatch.setattr("sys.stdin", _Stdin("{}"))
    assert stopper.main() == 0
    assert len(adapter.calls) == 1


def test_records_timestamp_after_push(monkeypatch, tmp_path):
    ts_file = tmp_path / "last_stop.ts"
    monkeypatch.setattr(stopper, "_LAST_STOP_PATH", ts_file)
    adapter = _Adapter()
    monkeypatch.setattr(stopper, "load_config", lambda: _cfg())
    monkeypatch.setattr(stopper, "make_adapter", lambda cfg: adapter)
    monkeypatch.setattr("sys.stdin", _Stdin("{}"))
    t0 = time.time()
    stopper.main()
    assert ts_file.exists()
    assert abs(float(ts_file.read_text()) - t0) < 2.0


def test_cwd_in_stop_notification(monkeypatch, tmp_path):
    monkeypatch.setattr(stopper, "_LAST_STOP_PATH", tmp_path / "last_stop.ts")
    adapter = _Adapter()
    cwd = str(Path.home() / "workspace" / "myproject")
    monkeypatch.setattr(stopper, "load_config", lambda: _cfg())
    monkeypatch.setattr(stopper, "make_adapter", lambda cfg: adapter)
    monkeypatch.setattr("sys.stdin", _Stdin(json.dumps({"cwd": cwd})))
    stopper.main()
    assert len(adapter.calls) == 1
    _, body = adapter.calls[0]
    assert "~/workspace/myproject" in body


def test_stop_hook_empty_payload_pushes(monkeypatch, tmp_path):
    monkeypatch.setattr(stopper, "_LAST_STOP_PATH", tmp_path / "last_stop.ts")
    adapter = _Adapter()
    monkeypatch.setattr(stopper, "load_config", lambda: _cfg())
    monkeypatch.setattr(stopper, "make_adapter", lambda cfg: adapter)
    monkeypatch.setattr("sys.stdin", _Stdin(""))
    assert stopper.main() == 0
    assert len(adapter.calls) == 1


def test_stop_hook_config_error_exits_cleanly(monkeypatch):
    def _raise():
        raise ConfigError("missing")
    monkeypatch.setattr(stopper, "load_config", _raise)
    monkeypatch.setattr("sys.stdin", _Stdin("{}"))
    assert stopper.main() == 0


def test_stop_hook_adapter_error_exits_cleanly(monkeypatch, tmp_path):
    monkeypatch.setattr(stopper, "_LAST_STOP_PATH", tmp_path / "last_stop.ts")

    def _boom(title, body):
        raise RuntimeError("network error")

    adapter = _Adapter()
    adapter.send = _boom
    monkeypatch.setattr(stopper, "load_config", lambda: _cfg())
    monkeypatch.setattr(stopper, "make_adapter", lambda cfg: adapter)
    monkeypatch.setattr("sys.stdin", _Stdin("{}"))
    assert stopper.main() == 0
