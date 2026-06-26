import json
from pathlib import Path

from cc_poke.setup_wizard import inject_cc_settings, _cmd_present


def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _bin(tmp_path: Path) -> Path:
    return tmp_path / "bin"


# ── _cmd_present ──────────────────────────────────────────────────────────────

def test_cmd_present_finds_command():
    hooks = {"Notification": [{"hooks": [{"type": "command", "command": "/venv/bin/cc-poke-notify"}]}]}
    assert _cmd_present(hooks, "cc-poke-notify") is True


def test_cmd_present_returns_false_when_absent():
    hooks = {"Notification": [{"hooks": [{"type": "command", "command": "/other/tool"}]}]}
    assert _cmd_present(hooks, "cc-poke-notify") is False


def test_cmd_present_handles_empty_hooks():
    assert _cmd_present({}, "cc-poke-notify") is False


# ── inject_cc_settings ────────────────────────────────────────────────────────

def test_inject_creates_file_if_missing(tmp_path):
    p = tmp_path / ".claude" / "settings.json"
    inject_cc_settings(p, bin_dir=_bin(tmp_path))
    data = json.loads(p.read_text())
    hooks = data["hooks"]
    assert any("cc-poke-notify" in h["command"]
               for e in hooks.get("Notification", []) for h in e.get("hooks", []))
    assert any("cc-poke-approve" in h["command"]
               for e in hooks.get("PreToolUse", []) for h in e.get("hooks", []))
    assert any("cc-poke-stop" in h["command"]
               for e in hooks.get("Stop", []) for h in e.get("hooks", []))


def test_inject_merges_into_existing_hooks(tmp_path):
    existing = {"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "/other/hook"}]}]}}
    p = _write(tmp_path, existing)
    inject_cc_settings(p, bin_dir=_bin(tmp_path))
    data = json.loads(p.read_text())
    # original hook preserved
    assert data["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"] == "/other/hook"
    # cc-poke hooks added
    assert "Notification" in data["hooks"]
    assert "PreToolUse" in data["hooks"]
    assert "Stop" in data["hooks"]


def test_inject_preserves_other_top_level_keys(tmp_path):
    existing = {"model": "sonnet", "theme": "dark", "hooks": {}}
    p = _write(tmp_path, existing)
    inject_cc_settings(p, bin_dir=_bin(tmp_path))
    data = json.loads(p.read_text())
    assert data["model"] == "sonnet"
    assert data["theme"] == "dark"


def test_inject_is_idempotent(tmp_path):
    p = tmp_path / "settings.json"
    inject_cc_settings(p, bin_dir=_bin(tmp_path))
    first = json.loads(p.read_text())
    inject_cc_settings(p, bin_dir=_bin(tmp_path))
    second = json.loads(p.read_text())
    # No duplicate entries added
    assert len(second["hooks"]["Notification"]) == len(first["hooks"]["Notification"])
    assert len(second["hooks"]["PreToolUse"]) == len(first["hooks"]["PreToolUse"])
    assert len(second["hooks"]["Stop"]) == len(first["hooks"]["Stop"])


def test_inject_pretooluse_has_bash_matcher(tmp_path):
    p = tmp_path / "settings.json"
    inject_cc_settings(p, bin_dir=_bin(tmp_path))
    data = json.loads(p.read_text())
    entry = next(e for e in data["hooks"]["PreToolUse"]
                 if any("cc-poke-approve" in h["command"] for h in e.get("hooks", [])))
    assert entry["matcher"] == "Bash"


def test_inject_approve_has_timeout(tmp_path):
    p = tmp_path / "settings.json"
    inject_cc_settings(p, bin_dir=_bin(tmp_path))
    data = json.loads(p.read_text())
    entry = next(e for e in data["hooks"]["PreToolUse"]
                 if any("cc-poke-approve" in h["command"] for h in e.get("hooks", [])))
    hook = next(h for h in entry["hooks"] if "cc-poke-approve" in h["command"])
    assert hook["timeout"] == 600


def test_inject_handles_corrupted_existing_file(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("not json", encoding="utf-8")
    inject_cc_settings(p, bin_dir=_bin(tmp_path))  # must not raise
    data = json.loads(p.read_text())
    assert "hooks" in data


def test_entrypoint_setup_exists():
    import importlib
    mod = importlib.import_module("cc_poke.setup_wizard")
    assert callable(mod.main)
