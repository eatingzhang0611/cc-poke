import json

import cc_poke.approve as approve
from cc_poke.approve import build_summary, emit_decision, is_allowlisted
from cc_poke.config import Config, ConfigError


def _cfg(allowlist=()):
    return Config(ntfy_server="https://ntfy.sh", ntfy_topic="t",
                  daemon_url="http://127.0.0.1:8787", allowlist=tuple(allowlist), wait_seconds=1.0)


def test_is_allowlisted_matches_bash_command():
    assert is_allowlisted("Bash", {"command": "git status"}, ("^git status$",)) is True


def test_is_allowlisted_no_match():
    assert is_allowlisted("Bash", {"command": "rm -rf /"}, ("^git status$",)) is False


def test_is_allowlisted_non_bash_always_false():
    assert is_allowlisted("Write", {"file_path": "/x"}, (".*",)) is False


def test_is_allowlisted_bad_regex_skipped():
    assert is_allowlisted("Bash", {"command": "ls"}, ("(", "^ls$")) is True


def test_build_summary_bash():
    assert build_summary("Bash", {"command": "echo hi"}) == "echo hi"


def test_build_summary_other_tool():
    s = build_summary("Write", {"file_path": "/x"})
    assert s.startswith("Write:")


def test_emit_decision_json_shape(capsys):
    emit_decision("allow", "because")
    out = json.loads(capsys.readouterr().out)
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["permissionDecision"] == "allow"
    assert hso["permissionDecisionReason"] == "because"


def test_main_allowlisted_emits_allow_without_daemon(monkeypatch, capsys):
    monkeypatch.setattr(approve, "load_config", lambda: _cfg(allowlist=("^ls$",)))

    def _boom(*a, **k):
        raise AssertionError("daemon must not be called for allowlisted command")

    monkeypatch.setattr(approve, "request_decision", _boom)
    monkeypatch.setattr("sys.stdin", _Stdin(json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})))
    assert approve.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_main_emits_decision_from_daemon(monkeypatch, capsys):
    monkeypatch.setattr(approve, "load_config", lambda: _cfg())
    monkeypatch.setattr(approve, "request_decision", lambda *a, **k: "deny")
    monkeypatch.setattr("sys.stdin", _Stdin(json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}})))
    assert approve.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_main_timeout_emits_nothing(monkeypatch, capsys):
    monkeypatch.setattr(approve, "load_config", lambda: _cfg())
    monkeypatch.setattr(approve, "request_decision", lambda *a, **k: None)
    monkeypatch.setattr("sys.stdin", _Stdin(json.dumps({"tool_name": "Bash", "tool_input": {"command": "x"}})))
    assert approve.main() == 0
    assert capsys.readouterr().out.strip() == ""


def test_main_daemon_error_emits_nothing(monkeypatch, capsys):
    monkeypatch.setattr(approve, "load_config", lambda: _cfg())

    def _raise(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(approve, "request_decision", _raise)
    monkeypatch.setattr("sys.stdin", _Stdin(json.dumps({"tool_name": "Bash", "tool_input": {"command": "x"}})))
    assert approve.main() == 0
    assert capsys.readouterr().out.strip() == ""


def test_main_config_error_emits_nothing(monkeypatch, capsys):
    def _raise():
        raise ConfigError("missing config")

    monkeypatch.setattr(approve, "load_config", _raise)
    monkeypatch.setattr("sys.stdin", _Stdin(json.dumps({"tool_name": "Bash", "tool_input": {"command": "x"}})))
    assert approve.main() == 0
    assert capsys.readouterr().out.strip() == ""


def test_request_decision_parses_allow():
    captured = {}

    def fake_poster(url, data, timeout):
        captured["url"] = url
        captured["data"] = json.loads(data)
        captured["timeout"] = timeout
        return 200, json.dumps({"decision": "allow"}).encode("utf-8")

    cfg = _cfg()
    out = approve.request_decision(cfg, "Bash", {"command": "echo hi"}, poster=fake_poster)
    assert out == "allow"
    assert captured["url"] == "http://127.0.0.1:8787/requests"
    assert captured["data"]["tool_name"] == "Bash"
    assert captured["data"]["summary"] == "echo hi"
    assert captured["timeout"] == cfg.wait_seconds + 15.0


def test_request_decision_non_2xx_returns_none():
    def fake_poster(url, data, timeout):
        return 500, b"err"

    assert approve.request_decision(_cfg(), "Bash", {"command": "x"}, poster=fake_poster) is None


def test_main_passes_cwd_to_daemon(monkeypatch):
    captured = {}

    def fake_request(config, tool_name, tool_input, cwd="", **kwargs):
        captured["cwd"] = cwd
        return "allow"

    monkeypatch.setattr(approve, "load_config", lambda: _cfg())
    monkeypatch.setattr(approve, "request_decision", fake_request)
    payload = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": "/home/yd/workspace"}
    monkeypatch.setattr("sys.stdin", _Stdin(json.dumps(payload)))
    approve.main()
    assert captured["cwd"] == "/home/yd/workspace"


def test_main_bypass_emits_allow_without_daemon(monkeypatch, capsys):
    cfg = Config(ntfy_server="https://ntfy.sh", ntfy_topic="t",
                 daemon_url="http://127.0.0.1:8787", allowlist=(), wait_seconds=1.0, bypass=True)
    monkeypatch.setattr(approve, "load_config", lambda: cfg)

    def _boom(*a, **k):
        raise AssertionError("daemon must not be called in bypass mode")

    monkeypatch.setattr(approve, "request_decision", _boom)
    monkeypatch.setattr("sys.stdin", _Stdin(json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}})))
    assert approve.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert "bypass" in out["hookSpecificOutput"]["permissionDecisionReason"]


class _Stdin:
    def __init__(self, text):
        self._text = text

    def read(self):
        return self._text
