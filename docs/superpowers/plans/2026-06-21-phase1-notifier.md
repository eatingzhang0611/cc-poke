# cc-poke Phase 1（档0 只通知）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 当 Claude Code 停下等待时，通过 Notification hook 把一条提醒推送到用户 iPhone（ntfy 通道），用户仍 SSH 回终端手动 approve。

**Architecture:** 一个 src-layout 的可安装 Python 包 `cc_poke`，提供 console 入口 `cc-poke-notify`，配置为 Claude Code 的 Notification hook command。包内分三层职责：`config`（读校验配置文件）、`adapters`（`PushAdapter` 抽象 + `NtfyAdapter` 首实现 + `make_adapter` 工厂）、`notifier`（hook 入口：读 stdin payload → 构造消息 → 经 adapter 推送）。推送失败绝不阻断 Claude（记本地日志并永远 exit 0）。

**Tech Stack:** Python 3.12（stdlib only，HTTP 用 `urllib.request`）；运行期零第三方依赖；pytest（仅开发期，装在 venv）；setuptools 打包。

## Global Constraints

- 运行期**零第三方依赖**，只用标准库（HTTP 用 `urllib.request`）。pytest 仅开发期。
- `requires-python = ">=3.10"`。
- **notifier 永不阻断 Claude**：任何错误（配置缺失、网络失败、stdin 损坏）都只记本地日志并 `return 0`，绝不抛异常、绝不非零退出。
- ntfy 的 `Title` HTTP header **只用 ASCII**（HTTP header 不可靠传非 ASCII）；中文/详情放进 POST body（body 用 UTF-8）。
- 包名 `cc-poke`，import 名 `cc_poke`，console 入口 `cc-poke-notify`。
- 所有路径基于仓库根 `/path/to/cc-poke/`。

---

### Task 1: 项目骨架 + venv + 可安装包

**Files:**
- Create: `pyproject.toml`
- Create: `src/cc_poke/__init__.py`
- Create: `src/cc_poke/notifier.py`（本任务先放 stub，Task 4 补全）
- Create: `.gitignore`

**Interfaces:**
- Consumes: 无
- Produces: 可安装包 `cc_poke`；console 入口 `cc-poke-notify` → `cc_poke.notifier:main`；`main() -> int`（stub，返回 0）。

- [ ] **Step 1: 写 `pyproject.toml`**

```toml
[project]
name = "cc-poke"
version = "0.1.0"
description = "Push Claude Code approval/notification prompts to your phone (self-hosted)."
requires-python = ">=3.10"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=7"]

[project.scripts]
cc-poke-notify = "cc_poke.notifier:main"

[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: 写包初始化与 notifier stub**

`src/cc_poke/__init__.py`:
```python
"""cc-poke — push Claude Code prompts to your phone."""

__version__ = "0.1.0"
```

`src/cc_poke/notifier.py`:
```python
"""Notification hook entry point (stub; filled in Task 4)."""


def main() -> int:
    return 0
```

- [ ] **Step 3: 写 `.gitignore`**

```gitignore
.venv/
__pycache__/
*.pyc
*.egg-info/
.pytest_cache/
build/
dist/
```

- [ ] **Step 4: 建 venv 并以可编辑模式安装（含 dev）**

Run:
```bash
cd /path/to/cc-poke
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"
```
Expected: 安装成功，结尾出现 `Successfully installed cc-poke-0.1.0 ... pytest-...`。

- [ ] **Step 5: 验证 console 入口可运行**

Run: `.venv/bin/cc-poke-notify; echo "exit=$?"`
Expected: 无输出，`exit=0`。

- [ ] **Step 6: 验证 pytest 可运行**

Run: `.venv/bin/pytest -q`
Expected: `no tests ran`（退出码非 0 但属预期，下一任务起就有测试）。

- [ ] **Step 7: Commit**

```bash
cd /path/to/cc-poke
git add pyproject.toml src/cc_poke/__init__.py src/cc_poke/notifier.py .gitignore
git commit -m "chore: scaffold cc_poke package with cc-poke-notify entry point"
```

---

### Task 2: 配置加载与校验（`config.py`）

**Files:**
- Create: `src/cc_poke/config.py`
- Create: `tests/test_config.py`
- Create: `config.example.json`

**Interfaces:**
- Consumes: 无
- Produces:
  - `class Config`（frozen dataclass）：字段 `ntfy_server: str`、`ntfy_topic: str`、`adapter: str`。
  - `class ConfigError(Exception)`。
  - `DEFAULT_CONFIG_PATH: Path`（`~/.config/cc-poke/config.json`）。
  - `load_config(path: str | Path | None = None, env: Mapping[str, str] | None = None) -> Config`。
    路径优先级：`path` 参数 > 环境变量 `CC_POKE_CONFIG` > `DEFAULT_CONFIG_PATH`。
    文件不存在或缺 `ntfy_topic` → 抛 `ConfigError`（消息清晰）。`ntfy_server` 默认 `https://ntfy.sh`、去掉结尾 `/`；`adapter` 默认 `"ntfy"`。

- [ ] **Step 1: 写失败测试 `tests/test_config.py`**

```python
import json
from pathlib import Path

import pytest

from cc_poke.config import Config, ConfigError, load_config


def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_load_minimal_config(tmp_path):
    p = _write(tmp_path, {"ntfy_topic": "my-secret-topic"})
    cfg = load_config(path=p)
    assert isinstance(cfg, Config)
    assert cfg.ntfy_topic == "my-secret-topic"
    assert cfg.ntfy_server == "https://ntfy.sh"  # default
    assert cfg.adapter == "ntfy"  # default


def test_server_trailing_slash_stripped(tmp_path):
    p = _write(tmp_path, {"ntfy_topic": "t", "ntfy_server": "https://push.example.com/"})
    cfg = load_config(path=p)
    assert cfg.ntfy_server == "https://push.example.com"


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(path=tmp_path / "nope.json")


def test_missing_topic_raises(tmp_path):
    p = _write(tmp_path, {"ntfy_server": "https://ntfy.sh"})
    with pytest.raises(ConfigError):
        load_config(path=p)


def test_path_from_env(tmp_path):
    p = _write(tmp_path, {"ntfy_topic": "envtopic"})
    cfg = load_config(env={"CC_POKE_CONFIG": str(p)})
    assert cfg.ntfy_topic == "envtopic"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_config.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'cc_poke.config'`）。

- [ ] **Step 3: 写实现 `src/cc_poke/config.py`**

```python
"""Load and validate cc-poke configuration from a JSON file."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "cc-poke" / "config.json"


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    ntfy_server: str
    ntfy_topic: str
    adapter: str = "ntfy"


def load_config(
    path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Config:
    env = os.environ if env is None else env
    resolved = path or env.get("CC_POKE_CONFIG") or DEFAULT_CONFIG_PATH
    p = Path(resolved).expanduser()
    if not p.exists():
        raise ConfigError(
            f"cc-poke config not found at {p}. "
            f'Create it, e.g. {{"ntfy_topic": "your-topic"}}'
        )
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"cc-poke config at {p} is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"cc-poke config at {p} must be a JSON object")
    topic = data.get("ntfy_topic")
    if not topic:
        raise ConfigError(f'cc-poke config at {p} is missing required "ntfy_topic"')
    server = str(data.get("ntfy_server", "https://ntfy.sh")).rstrip("/")
    adapter = str(data.get("adapter", "ntfy"))
    return Config(ntfy_server=server, ntfy_topic=str(topic), adapter=adapter)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_config.py -q`
Expected: PASS（5 passed）。

- [ ] **Step 5: 写 `config.example.json`**

```json
{
  "ntfy_server": "https://ntfy.sh",
  "ntfy_topic": "REPLACE-with-a-long-random-topic-you-keep-secret",
  "adapter": "ntfy"
}
```

- [ ] **Step 6: Commit**

```bash
cd /path/to/cc-poke
git add src/cc_poke/config.py tests/test_config.py config.example.json
git commit -m "feat: add config loading and validation"
```

---

### Task 3: 推送 adapter 抽象 + ntfy 实现 + 工厂

**Files:**
- Create: `src/cc_poke/adapters/__init__.py`
- Create: `src/cc_poke/adapters/base.py`
- Create: `src/cc_poke/adapters/ntfy.py`
- Create: `tests/test_ntfy_adapter.py`

**Interfaces:**
- Consumes: `cc_poke.config.Config`（Task 2）。
- Produces:
  - `base.PushAdapter`（`abc.ABC`）：抽象方法 `send(self, title: str, body: str) -> bool`。
  - `ntfy.NtfyAdapter(server: str, topic: str, *, poster: Callable = _default_poster, timeout: float = 10.0)`，实现 `send(title, body) -> bool`：POST `{server}/{topic}`，header `Title=<title>`，body 为 `body` 的 UTF-8 字节；2xx 返回 `True`，任何异常/非 2xx 返回 `False`（**绝不抛出**）。
  - `ntfy._default_poster(url: str, data: bytes, headers: dict[str, str], timeout: float) -> int`（返回 HTTP 状态码）。
  - `adapters.make_adapter(config: Config) -> PushAdapter`（`adapter == "ntfy"` → `NtfyAdapter`，否则抛 `ValueError`）。

- [ ] **Step 1: 写失败测试 `tests/test_ntfy_adapter.py`**

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_ntfy_adapter.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'cc_poke.adapters'`）。

- [ ] **Step 3: 写 `src/cc_poke/adapters/base.py`**

```python
"""Pluggable push-notification adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class PushAdapter(ABC):
    @abstractmethod
    def send(self, title: str, body: str) -> bool:
        """Send one notification. Return True on success, False on failure.

        Implementations MUST NOT raise — a push failure must never block Claude.
        """
        raise NotImplementedError
```

- [ ] **Step 4: 写 `src/cc_poke/adapters/ntfy.py`**

```python
"""ntfy push adapter (https://ntfy.sh / self-hosted)."""

from __future__ import annotations

import urllib.request
from typing import Callable

from .base import PushAdapter


def _default_poster(url: str, data: bytes, headers: dict[str, str], timeout: float) -> int:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return int(resp.status)


class NtfyAdapter(PushAdapter):
    def __init__(
        self,
        server: str,
        topic: str,
        *,
        poster: Callable[[str, bytes, dict[str, str], float], int] = _default_poster,
        timeout: float = 10.0,
    ) -> None:
        self._server = server.rstrip("/")
        self._topic = topic
        self._poster = poster
        self._timeout = timeout

    def send(self, title: str, body: str) -> bool:
        url = f"{self._server}/{self._topic}"
        headers = {
            "Title": title,  # ASCII only — see Global Constraints
            "Content-Type": "text/plain; charset=utf-8",
        }
        try:
            status = self._poster(url, body.encode("utf-8"), headers, self._timeout)
        except Exception:
            return False
        return 200 <= status < 300
```

- [ ] **Step 5: 写 `src/cc_poke/adapters/__init__.py`**

```python
"""Push adapters and the adapter factory."""

from __future__ import annotations

from ..config import Config
from .base import PushAdapter
from .ntfy import NtfyAdapter

__all__ = ["PushAdapter", "NtfyAdapter", "make_adapter"]


def make_adapter(config: Config) -> PushAdapter:
    if config.adapter == "ntfy":
        return NtfyAdapter(config.ntfy_server, config.ntfy_topic)
    raise ValueError(f"unknown push adapter: {config.adapter!r}")
```

- [ ] **Step 6: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_ntfy_adapter.py -q`
Expected: PASS（6 passed）。

- [ ] **Step 7: Commit**

```bash
cd /path/to/cc-poke
git add src/cc_poke/adapters tests/test_ntfy_adapter.py
git commit -m "feat: add PushAdapter interface, NtfyAdapter, and adapter factory"
```

---

### Task 4: notifier 入口（读 hook payload → 推送）

**Files:**
- Modify: `src/cc_poke/notifier.py`（替换 Task 1 的 stub）
- Create: `tests/test_notifier.py`

**Interfaces:**
- Consumes: `cc_poke.config.load_config`、`cc_poke.config.ConfigError`、`cc_poke.adapters.make_adapter`、`cc_poke.adapters.base.PushAdapter`（Task 2/3）。
- Produces:
  - `build_message(payload: dict) -> tuple[str, str]`：返回 `(title, body)`。`title` 固定 ASCII `"cc-poke: Claude needs you"`；`body` 取 `payload["message"]`（缺省 `"Claude is waiting for you"`），若有 `payload["cwd"]` 则追加一行 `(<cwd>)`。
  - `run(payload: dict, adapter: PushAdapter) -> bool`：`build_message` 后调用 `adapter.send`。
  - `main() -> int`：读 `sys.stdin` 的 hook JSON（损坏/空则视为 `{}`）→ `load_config()` → `make_adapter()` → `run()`；任何错误记日志，**永远返回 0**。

- [ ] **Step 1: 写失败测试 `tests/test_notifier.py`**

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_notifier.py -q`
Expected: FAIL（`AttributeError: module 'cc_poke.notifier' has no attribute 'build_message'`）。

- [ ] **Step 3: 写实现，替换 `src/cc_poke/notifier.py` 全文**

```python
"""Notification hook entry point: read the hook payload and push it to the phone."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .adapters import make_adapter
from .adapters.base import PushAdapter
from .config import ConfigError, load_config

_TITLE = "cc-poke: Claude needs you"
_DEFAULT_BODY = "Claude is waiting for you"
_LOG_PATH = Path.home() / ".cache" / "cc-poke" / "notifier.log"


def _log(msg: str) -> None:
    """Best-effort local log. Never raises."""
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def build_message(payload: dict) -> tuple[str, str]:
    message = payload.get("message") or _DEFAULT_BODY
    cwd = payload.get("cwd")
    body = f"{message}\n({cwd})" if cwd else message
    return _TITLE, body


def run(payload: dict, adapter: PushAdapter) -> bool:
    title, body = build_message(payload)
    return adapter.send(title, body)


def main() -> int:
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    try:
        config = load_config()
    except ConfigError as e:
        _log(f"config error: {e}")
        return 0

    try:
        adapter = make_adapter(config)
        if not run(payload, adapter):
            _log("push failed (adapter returned False)")
    except Exception as e:  # noqa: BLE001 — never block Claude
        _log(f"notifier error: {e!r}")
    return 0
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_notifier.py -q`
Expected: PASS（6 passed）。

- [ ] **Step 5: 运行全量测试**

Run: `.venv/bin/pytest -q`
Expected: PASS（全部，17 passed）。

- [ ] **Step 6: Commit**

```bash
cd /path/to/cc-poke
git add src/cc_poke/notifier.py tests/test_notifier.py
git commit -m "feat: implement notifier hook entry point"
```

---

### Task 5: Notification hook 配置示例 + README + 端到端冒烟

**Files:**
- Create: `hooks/notification-settings.example.json`
- Create: `README.md`

**Interfaces:**
- Consumes: `cc-poke-notify`（Task 1 入口）、`config.example.json`（Task 2）。
- Produces: 安装/配置文档 + 可手动跑的端到端冒烟步骤。

- [ ] **Step 1: 写 `hooks/notification-settings.example.json`**

把以下片段合并进 Claude Code 的 settings（command 用 venv 内入口的绝对路径）：
```json
{
  "hooks": {
    "Notification": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/cc-poke/.venv/bin/cc-poke-notify"
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 2: 写 `README.md`**

````markdown
# cc-poke

当 Claude Code 停下等待时，把提醒推送到你的 iPhone（自托管、零第三方信任）。
Phase 1 = 只通知（你仍 SSH 回终端 approve）。

## 安装

```bash
cd /path/to/cc-poke
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

## 配置

1. 在手机装 ntfy app，订阅一个**长随机** topic（当密码用）。
2. 建配置文件 `~/.config/cc-poke/config.json`（参考 `config.example.json`）：

```json
{
  "ntfy_server": "https://ntfy.sh",
  "ntfy_topic": "your-long-random-secret-topic"
}
```

3. 把 `hooks/notification-settings.example.json` 的内容合并进你的 Claude Code settings
   （用户级 `~/.claude/settings.json` 或项目级 `.claude/settings.json`），
   `command` 用 `.venv/bin/cc-poke-notify` 的绝对路径。

## 验证

```bash
echo '{"message":"hello from cc-poke","cwd":"/tmp"}' | .venv/bin/cc-poke-notify
```
手机应收到一条标题为 `cc-poke: Claude needs you`、正文含 `hello from cc-poke` 的通知。

## 设计与边界

见 `docs/superpowers/specs/2026-06-18-cc-poke-design.md`。
**起步 scope 钉死为"通知 + 远程批准"，不做会话托管平台。** 档1（手机远程批准）见 Phase 2。
````

- [ ] **Step 3: 端到端冒烟（需真实 ntfy topic）**

先在 `~/.config/cc-poke/config.json` 填好真实 topic 并在手机订阅，然后：
Run:
```bash
echo '{"message":"hello from cc-poke smoke test","cwd":"/tmp"}' | /path/to/cc-poke/.venv/bin/cc-poke-notify; echo "exit=$?"
```
Expected: `exit=0`；**手机收到通知**（标题 `cc-poke: Claude needs you`，正文含 `hello from cc-poke smoke test`）。
若没收到：查 `~/.cache/cc-poke/notifier.log`。

- [ ] **Step 4: Commit**

```bash
cd /path/to/cc-poke
git add hooks/notification-settings.example.json README.md
git commit -m "docs: add Notification hook example, README, and smoke-test steps"
```

---

## Self-Review

**1. Spec coverage（对照 spec §4.1/4.2、§5 档0、§7、§8、§9 Phase 1）:**
- §4.1 notifier → Task 4 ✅
- §4.2 push adapter（统一接口 + ntfy 首实现 + 可插拔）→ Task 3 ✅（`send(title, body)`；`actions?` 参数留到 Phase 2 档1 再加，见下注）
- §5 档0 数据流（hook → notifier → adapter.send → 手机）→ Task 4 + Task 5 ✅
- §7 错误处理：推送失败不阻断、降级本地 log → Task 4 `main()` 永远返回 0 + `_log` ✅；配置缺失清晰报错 → Task 2 `ConfigError` ✅
- §8 测试策略：adapter mock HTTP 单测 → Task 3 ✅；端到端冒烟真发一条 → Task 5 Step 3 ✅
- §9 Phase 1 交付物（notifier + ntfy adapter + Notification hook 配置 + README）→ Task 1–5 ✅
- 注：spec §4.2 接口写的是 `send(title, body, actions?)`。Phase 1 不产生 actions，按 YAGNI/TDD 暂用 `send(title, body)`；Phase 2 实现档1 双按钮时再扩展该签名（届时更新 spec 与 base.py）。这是有意的范围收窄，非遗漏。

**2. Placeholder scan:** 无 TODO/TBD；每个代码步骤都给了完整代码与可运行命令及预期输出。✅

**3. Type consistency:** `Config(ntfy_server, ntfy_topic, adapter)` 在 Task 2 定义、Task 3 `make_adapter`/测试、Task 4 一致；`PushAdapter.send(title, body) -> bool` 在 base、NtfyAdapter、FakeAdapter、`run()` 一致；`make_adapter(config) -> PushAdapter`、`load_config(path, env)`、`build_message(payload) -> (title, body)`、`run(payload, adapter)`、`main() -> int` 跨任务签名一致。✅
