# Phase 2 — 档1 远程批准 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Claude Code 在 VPS 停下等工具审批时推一条带「批准/拒绝」按钮的通知到 iPhone，用户手机点一下即放行/拒绝，Claude 继续，无需切回终端。

**Architecture:** PreToolUse hook(短进程 `cc-poke-approve`)拦截工具调用 → 查 allowlist 命中即放行；否则向常驻 `cc-poke-daemon` 注册并阻塞 long-poll。daemon 持有内存决定 store、经 push adapter 推带按钮通知、暴露公网 `/webhook`(手机点按钮打这)与极简决定网页。决定回传后 daemon 唤醒 long-poll，hook 返回 `permissionDecision: allow|deny`;超时则无决定退出 → CC 走原终端弹窗。

**Tech Stack:** Python 3.10+ 标准库(`http.server`、`threading`、`secrets`、`urllib`、`re`、`json`);零第三方运行时依赖;pytest(dev)。承接 Phase 1 的 `cc_poke` src-layout 包。

## Global Constraints

- 零第三方**运行时**依赖(仅 stdlib);dev 依赖仅 `pytest>=7`。
- `requires-python >= 3.10`。
- **`cc-poke-approve` 绝不阻断 Claude**:任何错误(配置缺失、daemon 不可达、异常)都吞掉并以**无决定**正常退出(exit 0、stdout 不输出 permissionDecision),让 CC 走原终端弹窗。
- ntfy 的 `Title` 与 `Actions` 请求头**仅 ASCII**(标题、动作 label、URL 均 ASCII;命令摘要放 body,UTF-8)。
- cc-poke 内部等待窗 `wait_seconds`(默认 300)必须**短于** CC 给 hook 配的 `timeout`(示例 600),hook 注册示例据此设置。
- webhook 安全:`request_id` = `secrets.token_urlsafe(32)`(不可猜);`/webhook` 校验共享 `webhook_secret`、id 必须 pending、**一次性**(决定后失效)。
- webhook 的 HTTP 响应**一律 200 + 友好页**,不靠状态码泄露 id 是否有效(是否真的 resolve 仅由内部 store 状态体现)。
- Phase 1 接口保持兼容:`adapter.send(title, body)` 旧调用不变(新增 `actions` 默认 None);`cc-poke-notify` 与 Notification hook 行为不动。
- **复用现有 `.venv`,不要重建**(VPS 缺 python3-venv/ensurepip)。运行测试:`/home/yd/workspace/cc-poke/.venv/bin/python -m pytest`。

---

### Task 1: Config 扩展 Phase 2 字段

**Files:**
- Modify: `src/cc_poke/config.py`
- Test: `tests/test_config.py`(追加)

**Interfaces:**
- Consumes: 现有 `Config`、`load_config`、`ConfigError`。
- Produces: `Config` 新增不可变字段 `daemon_url: str = "http://127.0.0.1:8787"`、`public_base_url: str = ""`、`webhook_secret: str = ""`、`allowlist: tuple[str, ...] = ()`、`wait_seconds: float = 300.0`;`load_config` 解析之(均可选、带默认;daemon 必需项的校验留到 Task 4 的 `DaemonApp.from_config`)。

- [ ] **Step 1: Write the failing tests**

追加到 `tests/test_config.py`(文件顶部已 `import json`、`from pathlib import Path`、`import pytest`、`from cc_poke.config import Config, ConfigError, load_config`;缺啥补啥):

```python
def test_phase2_fields_default(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"ntfy_topic": "t"}', encoding="utf-8")
    cfg = load_config(p)
    assert cfg.daemon_url == "http://127.0.0.1:8787"
    assert cfg.public_base_url == ""
    assert cfg.webhook_secret == ""
    assert cfg.allowlist == ()
    assert cfg.wait_seconds == 300.0


def test_phase2_fields_parsed(tmp_path):
    import json
    p = tmp_path / "c.json"
    p.write_text(json.dumps({
        "ntfy_topic": "t",
        "daemon_url": "http://127.0.0.1:9999/",
        "public_base_url": "https://poke.test/",
        "webhook_secret": "sek",
        "allowlist": ["^git status$", "^ls"],
        "wait_seconds": 120,
    }), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.daemon_url == "http://127.0.0.1:9999"
    assert cfg.public_base_url == "https://poke.test"
    assert cfg.webhook_secret == "sek"
    assert cfg.allowlist == ("^git status$", "^ls")
    assert cfg.wait_seconds == 120.0


def test_allowlist_must_be_list(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"ntfy_topic": "t", "allowlist": "nope"}', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(p)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/yd/workspace/cc-poke/.venv/bin/python -m pytest tests/test_config.py -k phase2 or allowlist -v`
Expected: FAIL(`Config` 无 `daemon_url` 等属性 / `AttributeError`)。

- [ ] **Step 3: Implement**

`src/cc_poke/config.py` —— 扩展 `Config` 字段:

```python
@dataclass(frozen=True)
class Config:
    ntfy_server: str
    ntfy_topic: str
    adapter: str = "ntfy"
    daemon_url: str = "http://127.0.0.1:8787"
    public_base_url: str = ""
    webhook_secret: str = ""
    allowlist: tuple[str, ...] = ()
    wait_seconds: float = 300.0
```

并在 `load_config` 的 `return` 之前追加解析(放在 `adapter = ...` 之后):

```python
    daemon_url = str(data.get("daemon_url", "http://127.0.0.1:8787")).rstrip("/")
    public_base_url = str(data.get("public_base_url", "")).rstrip("/")
    webhook_secret = str(data.get("webhook_secret", ""))
    raw_allow = data.get("allowlist", [])
    if not isinstance(raw_allow, list):
        raise ConfigError(f'cc-poke config at {p} has "allowlist" that is not a list')
    allowlist = tuple(str(x) for x in raw_allow)
    try:
        wait_seconds = float(data.get("wait_seconds", 300.0))
    except (TypeError, ValueError) as e:
        raise ConfigError(f'cc-poke config at {p} has invalid "wait_seconds": {e}') from e
    return Config(
        ntfy_server=server,
        ntfy_topic=str(topic),
        adapter=adapter,
        daemon_url=daemon_url,
        public_base_url=public_base_url,
        webhook_secret=webhook_secret,
        allowlist=allowlist,
        wait_seconds=wait_seconds,
    )
```

(删除原来的单行 `return Config(...)`。)

- [ ] **Step 4: Run tests**

Run: `/home/yd/workspace/cc-poke/.venv/bin/python -m pytest tests/test_config.py -v`
Expected: 全部 PASS(含 Phase 1 既有 config 测试)。

- [ ] **Step 5: Commit**

```bash
git add src/cc_poke/config.py tests/test_config.py
git commit -m "feat: add Phase 2 config fields (daemon/webhook/allowlist/wait)"
```

---

### Task 2: push adapter 支持 `actions`

**Files:**
- Modify: `src/cc_poke/adapters/base.py`
- Modify: `src/cc_poke/adapters/ntfy.py`
- Test: `tests/test_ntfy_adapter.py`(追加)

**Interfaces:**
- Produces:
  - `cc_poke.adapters.base.Action`:`@dataclass(frozen=True)`,字段 `label: str`、`url: str`、`method: str = "POST"`、`clear: bool = True`。
  - `PushAdapter.send(self, title: str, body: str, actions: list[Action] | None = None) -> bool`(新增第三参,默认 None,向后兼容)。
  - `NtfyAdapter.send` 在 `actions` 非空时设置 `Actions` 头,格式每个动作:`http, <label>, <url>, method=<method>, clear=<true|false>`,多动作以 `; ` 连接。

- [ ] **Step 1: Write the failing tests**

追加到 `tests/test_ntfy_adapter.py`:

```python
from cc_poke.adapters.base import Action


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/yd/workspace/cc-poke/.venv/bin/python -m pytest tests/test_ntfy_adapter.py -k actions -v`
Expected: FAIL(`Action` 无法导入 / `send` 不接受第三参)。

- [ ] **Step 3: Implement base.py**

`src/cc_poke/adapters/base.py` 改为:

```python
"""Pluggable push-notification adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    """A tappable action attached to a push (e.g. an Approve/Deny button)."""

    label: str  # ASCII only — rendered into an HTTP header
    url: str    # ASCII only
    method: str = "POST"
    clear: bool = True


class PushAdapter(ABC):
    @abstractmethod
    def send(self, title: str, body: str, actions: list[Action] | None = None) -> bool:
        """Send one notification. Return True on success, False on failure.

        ``actions`` is an optional list of tappable buttons. Implementations
        MUST NOT raise — a push failure must never block Claude.
        """
        raise NotImplementedError
```

- [ ] **Step 4: Implement ntfy.py**

`src/cc_poke/adapters/ntfy.py` —— 加导入与格式化、改 `send`:

```python
from .base import Action, PushAdapter


def _format_actions(actions: list[Action]) -> str:
    segs = []
    for a in actions:
        clear = "true" if a.clear else "false"
        segs.append(f"http, {a.label}, {a.url}, method={a.method}, clear={clear}")
    return "; ".join(segs)
```

`send` 改为:

```python
    def send(self, title: str, body: str, actions: list[Action] | None = None) -> bool:
        url = f"{self._server}/{self._topic}"
        headers = {
            "Title": title,  # ASCII only — see Global Constraints
            "Content-Type": "text/plain; charset=utf-8",
        }
        if actions:
            headers["Actions"] = _format_actions(actions)  # ASCII only
        try:
            status = self._poster(url, body.encode("utf-8"), headers, self._timeout)
        except Exception:
            return False
        return 200 <= status < 300
```

- [ ] **Step 5: Run tests**

Run: `/home/yd/workspace/cc-poke/.venv/bin/python -m pytest tests/test_ntfy_adapter.py -v`
Expected: 全 PASS(含 Phase 1 既有 adapter 测试,验证向后兼容)。

- [ ] **Step 6: Commit**

```bash
git add src/cc_poke/adapters/base.py src/cc_poke/adapters/ntfy.py tests/test_ntfy_adapter.py
git commit -m "feat: add optional actions (buttons) to push adapter + ntfy Actions header"
```

---

### Task 3: 决定 store(内存、并发、一次性、可超时)

**Files:**
- Create: `src/cc_poke/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Produces `cc_poke.store.DecisionStore`:
  - `register() -> str`:生成不可猜 `request_id`(`secrets.token_urlsafe(32)`),标记 pending,返回 id。
  - `resolve(rid: str, decision: str) -> bool`:仅当 rid 处于 pending 时写入 `decision`(应为 `"allow"`/`"deny"`)并唤醒等待者,返回 True;未知或已决定返回 False(一次性)。
  - `wait(rid: str, timeout: float) -> str | None`:阻塞至该 rid 被 resolve 或超时;命中返回 `"allow"`/`"deny"` 并清除该 rid;超时返回 None 并清除。
  - `cancel(rid: str) -> None`:移除 pending(无则忽略)。

- [ ] **Step 1: Write the failing tests**

`tests/test_store.py`:

```python
import threading
import time

from cc_poke.store import DecisionStore


def test_register_returns_unique_unguessable_ids():
    s = DecisionStore()
    a, b = s.register(), s.register()
    assert a != b
    assert len(a) > 20


def test_resolve_then_wait_returns_decision():
    s = DecisionStore()
    rid = s.register()
    assert s.resolve(rid, "allow") is True
    assert s.wait(rid, 1.0) == "allow"


def test_wait_blocks_until_resolved():
    s = DecisionStore()
    rid = s.register()

    def later():
        time.sleep(0.05)
        s.resolve(rid, "deny")

    threading.Thread(target=later).start()
    assert s.wait(rid, 2.0) == "deny"


def test_wait_times_out_returns_none():
    s = DecisionStore()
    rid = s.register()
    assert s.wait(rid, 0.05) is None


def test_resolve_unknown_id_returns_false():
    assert DecisionStore().resolve("nope", "allow") is False


def test_resolve_is_one_shot():
    s = DecisionStore()
    rid = s.register()
    assert s.resolve(rid, "allow") is True
    assert s.resolve(rid, "deny") is False
    assert s.wait(rid, 1.0) == "allow"


def test_wait_consumes_id():
    s = DecisionStore()
    rid = s.register()
    s.resolve(rid, "allow")
    assert s.wait(rid, 1.0) == "allow"
    # consumed: a second resolve sees an unknown id
    assert s.resolve(rid, "deny") is False


def test_cancel_makes_wait_return_none():
    s = DecisionStore()
    rid = s.register()
    s.cancel(rid)
    assert s.wait(rid, 0.05) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/yd/workspace/cc-poke/.venv/bin/python -m pytest tests/test_store.py -v`
Expected: FAIL(`ModuleNotFoundError: cc_poke.store`)。

- [ ] **Step 3: Implement**

`src/cc_poke/store.py`:

```python
"""In-memory, thread-safe, one-shot decision store for the approval daemon."""

from __future__ import annotations

import secrets
import threading
import time


class DecisionStore:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._decisions: dict[str, str | None] = {}  # rid -> None(pending) | "allow"/"deny"

    def register(self) -> str:
        rid = secrets.token_urlsafe(32)
        with self._cond:
            self._decisions[rid] = None
        return rid

    def resolve(self, rid: str, decision: str) -> bool:
        with self._cond:
            if rid not in self._decisions:
                return False  # unknown, or already consumed by wait()
            if self._decisions[rid] is not None:
                return False  # already decided (one-shot)
            self._decisions[rid] = decision
            self._cond.notify_all()
            return True

    def wait(self, rid: str, timeout: float) -> str | None:
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                cur = self._decisions.get(rid)
                if cur is not None:
                    del self._decisions[rid]
                    return cur
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._decisions.pop(rid, None)
                    return None
                self._cond.wait(remaining)

    def cancel(self, rid: str) -> None:
        with self._cond:
            self._decisions.pop(rid, None)
```

- [ ] **Step 4: Run tests**

Run: `/home/yd/workspace/cc-poke/.venv/bin/python -m pytest tests/test_store.py -v`
Expected: 全 PASS,输出无 warning。

- [ ] **Step 5: Commit**

```bash
git add src/cc_poke/store.py tests/test_store.py
git commit -m "feat: add in-memory one-shot decision store"
```

---

### Task 4: approval daemon(逻辑 + 路由 + HTTP 服务)

**Files:**
- Create: `src/cc_poke/daemon.py`
- Test: `tests/test_daemon.py`

**Interfaces:**
- Consumes: `DecisionStore`(Task 3)、`Action`/`PushAdapter`(Task 2)、`Config`/`ConfigError`/`load_config`(Task 1)、`make_adapter`。
- Produces `cc_poke.daemon`:
  - `Response = namedtuple("Response", "status content_type body")`(`body: bytes`)。
  - `DaemonApp(store, adapter, config)`,属性 `store`;方法:
    - `handle_request(tool_name: str, summary: str) -> str | None`:register → 推带 Approve/Deny 两个 http 动作的通知(URL = `{public_base_url}/webhook?id=<rid>&d=allow|deny&s=<secret>`)→ 推失败则 `cancel` 并返回 None → 否则 `wait(wait_seconds)` 返回 `"allow"`/`"deny"`/None。
    - `handle_webhook(rid: str, decision: str, secret: str) -> tuple[bool, str]`:校验 secret、decision∈{allow,deny}、`store.resolve`;返回 `(resolved, html)`。
    - `decision_page(rid: str, secret: str) -> str`:返回含 Approve/Deny 两个 POST 表单(打 `/webhook`)的 HTML。
    - `dispatch(method: str, path: str, params: dict[str, str], body: bytes) -> Response`:路由 `POST /requests`、`/webhook`、`/d`,其余 404。
    - classmethod `from_config(config) -> DaemonApp`:校验 `public_base_url`、`webhook_secret` 非空(否则 `ConfigError`),用 `make_adapter` 建 adapter。
  - `main() -> int`:`load_config` → `DaemonApp.from_config` → 起 `ThreadingHTTPServer` 监听 `daemon_url` 的 host:port。

- [ ] **Step 1: Write the failing tests**

`tests/test_daemon.py`:

```python
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

    def send(self, title, body, actions=None):
        self.calls.append({"title": title, "body": body, "actions": actions})
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


def test_from_config_requires_public_base_url_and_secret():
    with pytest.raises(ConfigError):
        DaemonApp.from_config(Config(ntfy_server="https://ntfy.sh", ntfy_topic="t"))
    with pytest.raises(ConfigError):
        DaemonApp.from_config(Config(
            ntfy_server="https://ntfy.sh", ntfy_topic="t",
            public_base_url="https://poke.test",  # secret missing
        ))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/yd/workspace/cc-poke/.venv/bin/python -m pytest tests/test_daemon.py -v`
Expected: FAIL(`ModuleNotFoundError: cc_poke.daemon`)。

- [ ] **Step 3: Implement**

`src/cc_poke/daemon.py`:

```python
"""Approval daemon: push approve/deny notifications and resolve decisions.

Single process, single port, stdlib-only. The reverse proxy should expose
ONLY /webhook and /d publicly; /requests stays localhost-only.
"""

from __future__ import annotations

import html
import json
import urllib.parse
from collections import namedtuple
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .adapters import make_adapter
from .adapters.base import Action
from .config import Config, ConfigError, load_config
from .store import DecisionStore

Response = namedtuple("Response", "status content_type body")

_PAGE_DONE = (
    "<!doctype html><meta charset=utf-8><title>cc-poke</title>"
    "<body style='font-family:sans-serif;text-align:center;padding:3em'>"
    "<h2>Done</h2><p>You can close this page.</p></body>"
)
_PAGE_INVALID = (
    "<!doctype html><meta charset=utf-8><title>cc-poke</title>"
    "<body style='font-family:sans-serif;text-align:center;padding:3em'>"
    "<h2>No longer valid</h2><p>This request was already handled or has expired.</p></body>"
)
_PAGE_DECISION = (
    "<!doctype html><meta charset=utf-8><title>cc-poke</title>"
    "<body style='font-family:sans-serif;text-align:center;padding:2em'>"
    "<h2>cc-poke approval</h2>"
    "<form method=POST action='{base}/webhook'>"
    "<input type=hidden name=id value='{id}'>"
    "<input type=hidden name=s value='{s}'>"
    "<button name=d value=allow style='font-size:1.4em;padding:.5em 2em;margin:.5em'>Approve</button>"
    "</form>"
    "<form method=POST action='{base}/webhook'>"
    "<input type=hidden name=id value='{id}'>"
    "<input type=hidden name=s value='{s}'>"
    "<button name=d value=deny style='font-size:1.4em;padding:.5em 2em;margin:.5em'>Deny</button>"
    "</form></body>"
)


class DaemonApp:
    def __init__(self, store: DecisionStore, adapter, config: Config) -> None:
        self.store = store
        self._adapter = adapter
        self._config = config

    @classmethod
    def from_config(cls, config: Config) -> "DaemonApp":
        if not config.public_base_url:
            raise ConfigError('daemon requires a non-empty "public_base_url" in config')
        if not config.webhook_secret:
            raise ConfigError('daemon requires a non-empty "webhook_secret" in config')
        return cls(store=DecisionStore(), adapter=make_adapter(config), config=config)

    def handle_request(self, tool_name: str, summary: str) -> str | None:
        rid = self.store.register()
        base = self._config.public_base_url
        s = self._config.webhook_secret
        actions = [
            Action("Approve", f"{base}/webhook?id={rid}&d=allow&s={s}"),
            Action("Deny", f"{base}/webhook?id={rid}&d=deny&s={s}"),
        ]
        title = f"cc-poke: approve {tool_name or 'tool'}?"  # ASCII
        if not self._adapter.send(title, summary or "(no detail)", actions):
            self.store.cancel(rid)
            return None
        return self.store.wait(rid, self._config.wait_seconds)

    def handle_webhook(self, rid: str, decision: str, secret: str) -> tuple[bool, str]:
        if not secret or secret != self._config.webhook_secret:
            return False, _PAGE_INVALID
        if decision not in ("allow", "deny"):
            return False, _PAGE_INVALID
        resolved = self.store.resolve(rid, decision)
        return resolved, (_PAGE_DONE if resolved else _PAGE_INVALID)

    def decision_page(self, rid: str, secret: str) -> str:
        return _PAGE_DECISION.format(
            base=html.escape(self._config.public_base_url, quote=True),
            id=html.escape(rid, quote=True),
            s=html.escape(secret, quote=True),
        )

    def dispatch(self, method: str, path: str, params: dict, body: bytes) -> Response:
        if path == "/requests" and method == "POST":
            try:
                data = json.loads(body or b"{}")
            except Exception:
                data = {}
            decision = self.handle_request(str(data.get("tool_name", "")), str(data.get("summary", "")))
            return Response(200, "application/json", json.dumps({"decision": decision}).encode("utf-8"))
        if path == "/webhook":
            _, page = self.handle_webhook(params.get("id", ""), params.get("d", ""), params.get("s", ""))
            return Response(200, "text/html; charset=utf-8", page.encode("utf-8"))
        if path == "/d":
            page = self.decision_page(params.get("id", ""), params.get("s", ""))
            return Response(200, "text/html; charset=utf-8", page.encode("utf-8"))
        return Response(404, "text/plain; charset=utf-8", b"not found")


def _merge_params(query: str, body: bytes, content_type: str) -> dict:
    params = dict(urllib.parse.parse_qsl(query))
    if "application/x-www-form-urlencoded" in (content_type or ""):
        params.update(dict(urllib.parse.parse_qsl(body.decode("utf-8", "replace"))))
    return params


class _Handler(BaseHTTPRequestHandler):
    def _respond(self, method: str) -> None:
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        params = _merge_params(parsed.query, body, self.headers.get("Content-Type", ""))
        resp = self.server.app.dispatch(method, parsed.path, params, body)
        self.send_response(resp.status)
        self.send_header("Content-Type", resp.content_type)
        self.send_header("Content-Length", str(len(resp.body)))
        self.end_headers()
        self.wfile.write(resp.body)

    def do_GET(self):
        self._respond("GET")

    def do_POST(self):
        self._respond("POST")

    def log_message(self, *args):  # silence default stderr access log
        pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, app: DaemonApp):
        super().__init__(addr, _Handler)
        self.app = app


def main() -> int:
    config = load_config()
    app = DaemonApp.from_config(config)
    parsed = urllib.parse.urlparse(config.daemon_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8787
    server = _Server((host, port), app)
    print(f"cc-poke-daemon listening on {host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
```

- [ ] **Step 4: Run tests**

Run: `/home/yd/workspace/cc-poke/.venv/bin/python -m pytest tests/test_daemon.py -v`
Expected: 全 PASS,输出无 warning。

- [ ] **Step 5: Commit**

```bash
git add src/cc_poke/daemon.py tests/test_daemon.py
git commit -m "feat: add approval daemon (decision logic, routing, threading HTTP server)"
```

---

### Task 5: `cc-poke-approve` PreToolUse hook 客户端

**Files:**
- Create: `src/cc_poke/approve.py`
- Test: `tests/test_approve.py`

**Interfaces:**
- Consumes: `load_config`/`ConfigError`(Task 1);通过 HTTP POST 调用 daemon 的 `/requests`(Task 4)。
- Produces `cc_poke.approve`:
  - `is_allowlisted(tool_name: str, tool_input: dict, patterns) -> bool`:仅对 `tool_name == "Bash"` 用 `re.search` 把 patterns 逐个匹配 `tool_input["command"]`;其它工具恒 False;非法正则跳过。
  - `build_summary(tool_name: str, tool_input: dict) -> str`:Bash 取 `command`,否则 `"<tool_name>: <json>"`,截断到 300 字符。
  - `emit_decision(decision: str, reason: str) -> None`:向 stdout 打印 `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":decision,"permissionDecisionReason":reason}}`。
  - `request_decision(config, tool_name, tool_input, *, poster=_default_poster) -> str | None`:POST `{tool_name, summary}` 到 `{daemon_url}/requests`(HTTP 超时 = `wait_seconds + 15`),解析 `{"decision": ...}`,仅返回 `"allow"`/`"deny"`,否则 None。
  - `main() -> int`:读 stdin JSON → `load_config`(失败→无决定退出)→ allowlist 命中→`emit_decision("allow", ...)` → 否则 `request_decision`(异常→无决定退出)→ 命中 allow/deny→`emit_decision`,None(超时)→无输出;**始终返回 0**。

- [ ] **Step 1: Write the failing tests**

`tests/test_approve.py`:

```python
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


class _Stdin:
    def __init__(self, text):
        self._text = text

    def read(self):
        return self._text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/yd/workspace/cc-poke/.venv/bin/python -m pytest tests/test_approve.py -v`
Expected: FAIL(`ModuleNotFoundError: cc_poke.approve`)。

- [ ] **Step 3: Implement**

`src/cc_poke/approve.py`:

```python
"""PreToolUse hook client: ask the phone to approve/deny a tool call.

NEVER blocks Claude: on config error, daemon error, or timeout it exits 0
with NO permissionDecision, so Claude Code falls back to its terminal popup.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

from .config import ConfigError, load_config

_LOG_PATH = Path.home() / ".cache" / "cc-poke" / "approve.log"


def _log(msg: str) -> None:
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def is_allowlisted(tool_name: str, tool_input: dict, patterns) -> bool:
    if tool_name != "Bash":
        return False
    command = str(tool_input.get("command", ""))
    for pat in patterns:
        try:
            if re.search(pat, command):
                return True
        except re.error:
            continue
    return False


def build_summary(tool_name: str, tool_input: dict) -> str:
    if tool_name == "Bash":
        return str(tool_input.get("command", ""))[:300]
    return f"{tool_name}: {json.dumps(tool_input, ensure_ascii=False)}"[:300]


def emit_decision(decision: str, reason: str) -> None:
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(out))


def _default_poster(url: str, data: bytes, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return int(resp.status), resp.read()


def request_decision(config, tool_name, tool_input, *, poster=_default_poster) -> str | None:
    summary = build_summary(tool_name, tool_input)
    payload = json.dumps({"tool_name": tool_name, "summary": summary}).encode("utf-8")
    url = f"{config.daemon_url}/requests"
    status, body = poster(url, payload, config.wait_seconds + 15.0)
    if not (200 <= status < 300):
        return None
    try:
        decision = json.loads(body).get("decision")
    except Exception:
        return None
    return decision if decision in ("allow", "deny") else None


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
    tool_name = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}

    try:
        config = load_config()
    except ConfigError as e:
        _log(f"config error: {e}")
        return 0  # no decision -> terminal popup

    if is_allowlisted(tool_name, tool_input, config.allowlist):
        emit_decision("allow", "cc-poke allowlist")
        return 0

    try:
        decision = request_decision(config, tool_name, tool_input)
    except Exception as e:  # noqa: BLE001 — never block Claude
        _log(f"approve error: {e!r}")
        return 0  # no decision -> terminal popup

    if decision in ("allow", "deny"):
        emit_decision(decision, "cc-poke remote")
    # else: timeout -> no decision -> terminal popup
    return 0
```

- [ ] **Step 4: Run tests**

Run: `/home/yd/workspace/cc-poke/.venv/bin/python -m pytest tests/test_approve.py -v`
Expected: 全 PASS,输出无 warning。

- [ ] **Step 5: Commit**

```bash
git add src/cc_poke/approve.py tests/test_approve.py
git commit -m "feat: add cc-poke-approve PreToolUse hook client"
```

---

### Task 6: 打包入口 + systemd + hook 示例 + README

**Files:**
- Modify: `pyproject.toml`
- Create: `deploy/cc-poke-daemon.service`
- Create: `hooks/pretooluse-settings.example.json`
- Create: `config.example.json`
- Modify: `README.md`(追加 Phase 2 段)
- Test: `tests/test_entrypoints.py`

**Interfaces:**
- Consumes: `cc_poke.daemon:main`、`cc_poke.approve:main`。
- Produces: console scripts `cc-poke-daemon`、`cc-poke-approve`;部署与配置示例文档。

- [ ] **Step 1: Write the failing test**

`tests/test_entrypoints.py`:

```python
import importlib


def test_daemon_and_approve_mains_exist():
    daemon = importlib.import_module("cc_poke.daemon")
    approve = importlib.import_module("cc_poke.approve")
    assert callable(daemon.main)
    assert callable(approve.main)
```

(此测试验证模块入口存在;console_scripts 注册由 `pyproject.toml` 编辑保证,Step 5 重装后用 `which` 验证。)

- [ ] **Step 2: Run test to verify it passes after Task 4/5**

Run: `/home/yd/workspace/cc-poke/.venv/bin/python -m pytest tests/test_entrypoints.py -v`
Expected: PASS(Task 4、5 已建模块)。若 import 失败说明前置任务未完成。

- [ ] **Step 3: Edit pyproject.toml**

`[project.scripts]` 段改为:

```toml
[project.scripts]
cc-poke-notify = "cc_poke.notifier:main"
cc-poke-daemon = "cc_poke.daemon:main"
cc-poke-approve = "cc_poke.approve:main"
```

- [ ] **Step 4: Create deploy + hook + config examples**

`config.example.json`:

```json
{
  "ntfy_server": "https://ntfy.sh",
  "ntfy_topic": "REPLACE-with-a-long-random-topic",
  "daemon_url": "http://127.0.0.1:8787",
  "public_base_url": "https://poke.example.com",
  "webhook_secret": "REPLACE-with-output-of: python -c \"import secrets;print(secrets.token_urlsafe(24))\"",
  "allowlist": ["^git status$", "^git diff( .*)?$", "^ls( .*)?$"],
  "wait_seconds": 300
}
```

`deploy/cc-poke-daemon.service`(systemd 用户/系统单元示例):

```ini
[Unit]
Description=cc-poke approval daemon
After=network.target

[Service]
Type=simple
ExecStart=/home/yd/workspace/cc-poke/.venv/bin/cc-poke-daemon
Restart=on-failure
RestartSec=2
# 低内存:无需额外解释器进程
MemoryMax=128M

[Install]
WantedBy=default.target
```

`hooks/pretooluse-settings.example.json`(注意 `timeout` 600 > `wait_seconds` 300):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "/home/yd/workspace/cc-poke/.venv/bin/cc-poke-approve",
            "timeout": 600
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 5: Append Phase 2 section to README.md**

在 `README.md` 末尾追加:

````markdown
## Phase 2 — 档1 远程批准(remote approve)

手机上点「批准/拒绝」,决定回传 VPS,Claude 直接继续,无需切回终端。

### 组件
- `cc-poke-daemon` —— 常驻服务:持有内存决定 store、推带按钮通知、暴露 `/webhook` 与决定网页 `/d`。
- `cc-poke-approve` —— `PreToolUse` hook:拦截工具调用、查 allowlist、向 daemon 注册并阻塞等手机决定。

### 1. 配置
复制 `config.example.json` 到 `~/.config/cc-poke/config.json` 并填写:
- `public_base_url`:反代后的公网地址(手机能访问)。
- `webhook_secret`:`python -c "import secrets;print(secrets.token_urlsafe(24))"` 生成。
- `allowlist`:正则数组,命中的 Bash 命令直接放行不推送(避免琐碎命令刷屏)。
- `wait_seconds`:hook 等待手机的窗口(默认 300)。

### 2. 起 daemon(systemd,低内存)
```bash
cp deploy/cc-poke-daemon.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now cc-poke-daemon
systemctl --user status cc-poke-daemon
```
或裸跑:`/home/yd/workspace/cc-poke/.venv/bin/cc-poke-daemon`。

### 3. 反代(只暴露两个路径)
把 `public_base_url` 指向的反代**仅**转发 `/webhook` 与 `/d` 到 `127.0.0.1:8787`;
**不要**暴露 `/requests`(仅 hook 在 localhost 调用)。

### 4. 注册 PreToolUse hook
把 `hooks/pretooluse-settings.example.json` 的内容合并进你的 Claude Code `settings.json`。
**关键**:hook 的 `timeout`(600s)必须大于 `wait_seconds`(300s),否则 CC 会在 cc-poke
退回终端弹窗前就杀掉 hook。

### 5. 冒烟验证(E2E)
1. daemon 已运行;手机已订阅 ntfy topic。
2. 在交互式 `claude` 里触发一个不在 allowlist 的命令(如 `rm -rf /tmp/cc-poke-test`)。
3. 手机收到带 Approve/Deny 的通知 → 点 Approve → 终端里 Claude 应直接继续(不弹终端审批)。
4. 不点、等满 `wait_seconds` → 应退回终端弹窗。

### 安全说明
公网上 `/webhook` 是「点一下就放行工具执行」的敏感端点。防护:`request_id` 不可猜
(`secrets.token_urlsafe(32)`)+ 共享 `webhook_secret` + 一次性(决定后即失效)。
请用 HTTPS,并妥善保管 `webhook_secret`。
````

- [ ] **Step 6: Reinstall + verify entry points**

```bash
/home/yd/workspace/cc-poke/.venv/bin/pip install -e . >/dev/null
ls /home/yd/workspace/cc-poke/.venv/bin/cc-poke-daemon /home/yd/workspace/cc-poke/.venv/bin/cc-poke-approve
```
Expected: 两个路径都存在。

- [ ] **Step 7: Full suite**

Run: `/home/yd/workspace/cc-poke/.venv/bin/python -m pytest -v`
Expected: 全 PASS(Phase 1 + Phase 2 全部),输出无 warning。

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml deploy/cc-poke-daemon.service hooks/pretooluse-settings.example.json config.example.json README.md tests/test_entrypoints.py
git commit -m "feat: add daemon/approve entry points, systemd unit, hook example, README"
```

---

## Self-Review

**Spec coverage**(对照 `2026-06-23-cc-poke-phase2-approval.md`):
- §2 决策1 公网 webhook → Task 4 `/webhook` + 反代说明(Task 6)✅
- §2 决策2 long-poll → Task 3 store.wait + Task 4 handle_request ✅
- §2 决策3 窄 matcher + allowlist → Task 5 is_allowlisted + Task 6 hook matcher ✅
- §2 决策4 超时退终端 → Task 5 main 无决定退出 ✅
- §2 决策5 secret + 一次性不可猜 → Task 3 register/resolve + Task 4 handle_webhook ✅
- §2 决策6 systemd 低内存 → Task 6 .service(MemoryMax)✅
- §3.3 adapter actions → Task 2 ✅
- §5 配置字段 → Task 1 ✅
- §6 超时分层 → Task 6 hook timeout 600 > wait 300 + README 强调 ✅
- §7 错误处理(daemon 连不上/超时/未知 id/secret 不符/推送失败/配置缺失)→ Task 4/5 各路径 + 测试 ✅
- §8 安全 → Task 3/4 + README ✅
- §9 测试策略 → Task 2/3/4/5 单测 + Task 6 E2E 冒烟 ✅

**Placeholder scan:** 无 TBD/TODO;每步含完整代码与命令。

**Type consistency:** `Action(label,url,method,clear)`、`DecisionStore.{register,resolve,wait,cancel}`、`DaemonApp.{handle_request,handle_webhook,decision_page,dispatch,from_config,store}`、`approve.{is_allowlisted,build_summary,emit_decision,request_decision,main}` 在定义与调用处一致;`send(title,body,actions=None)` 全程一致;`request_decision` 的 poster 签名 `(url,data,timeout)->(status,bytes)` 与测试一致。

**注:** Task 6 的 `test_entrypoints.py` 在 Task 4/5 完成后即 PASS(非 RED→GREEN);它是回归守卫而非新行为的 TDD,故 Step 2 预期直接 PASS。
