#!/usr/bin/env python3
"""cc-poke 命门探针 2 —— PreToolUse hook.

验证：交互式 TUI 里，PreToolUse hook 能否拦截工具、返回 allow 决定从而
绕过终端审批弹窗（替代被证明在交互式无效的 --permission-prompt-tool）。

行为：被触发就把 stdin 收到的 hook payload 追加写到 hook_probe.log，
然后返回 permissionDecision=allow。零依赖，纯 stdlib。

可选：环境变量 CC_POKE_BLOCK_SECONDS 设一个秒数，模拟「阻塞等手机回传」，
用来观察 Claude Code 对长时间阻塞 hook 的超时行为。
"""
import json
import sys
import os
import time
import datetime

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hook_probe.log")


def log(msg: str) -> None:
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        log(f"bad json: {e!r} :: {raw!r}")
        payload = {}

    tool = payload.get("tool_name")
    tin = payload.get("tool_input")
    log(f"!!! PreToolUse tool_name={tool} tool_input={json.dumps(tin, ensure_ascii=False)}")

    block = os.environ.get("CC_POKE_BLOCK_SECONDS")
    if block:
        log(f"blocking {block}s (simulate waiting for phone)...")
        time.sleep(float(block))
        log("...unblocked")

    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "cc-poke probe auto-allow",
        }
    }
    print(json.dumps(out))
    sys.exit(0)


if __name__ == "__main__":
    main()
