#!/usr/bin/env python3
"""cc-poke 命门探针 — 最小 MCP stdio server.

目的：作为 `claude --permission-prompt-tool mcp__poke__approve` 注册，
验证交互式 TUI 会话里权限请求是否真的走 MCP（而不是仍弹终端 TUI）。

行为：被调用就把收到的参数追加写到 spike/probe.log（带时间戳），
然后固定返回 allow。零依赖，纯 stdlib。

MCP stdio 传输 = 按行分隔的 JSON-RPC（每行一个 JSON 对象，无 Content-Length 头）。
"""
import json
import sys
import os
import datetime

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe.log")

SERVER_NAME = "poke"
TOOL_NAME = "approve"


def log(msg: str) -> None:
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def reply(req_id, result=None, error=None) -> None:
    msg = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    send(msg)


def handle(req: dict) -> None:
    method = req.get("method")
    req_id = req.get("id")

    if method == "initialize":
        # 回显客户端请求的协议版本，避免版本不匹配
        client_ver = (req.get("params") or {}).get("protocolVersion", "2024-11-05")
        log(f"initialize (protocolVersion={client_ver})")
        reply(req_id, {
            "protocolVersion": client_ver,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "cc-poke-probe", "version": "0.0.1"},
        })

    elif method == "notifications/initialized":
        log("notifications/initialized")
        # 通知无需回复

    elif method == "tools/list":
        log("tools/list")
        reply(req_id, {
            "tools": [{
                "name": TOOL_NAME,
                "description": "cc-poke 探针：批准/拒绝权限请求（探针固定返回 allow）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "tool_name": {"type": "string"},
                        "input": {"type": "object"},
                    },
                },
            }],
        })

    elif method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        args = params.get("arguments", {})
        # 这是命门证据：交互式会话里这一行出现 == flag 真的把权限请求转给了 MCP
        log(f"!!! tools/call name={name} arguments={json.dumps(args, ensure_ascii=False)}")
        # permission-prompt-tool 契约：返回 JSON 字符串化的决定
        decision = {
            "behavior": "allow",
            "updatedInput": args.get("input", {}),
        }
        reply(req_id, {
            "content": [{"type": "text", "text": json.dumps(decision)}],
        })

    elif method in ("ping",):
        reply(req_id, {})

    else:
        log(f"unhandled method={method}")
        if req_id is not None:
            reply(req_id, error={"code": -32601, "message": f"Method not found: {method}"})


def main() -> None:
    log("=== probe server started ===")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            log(f"bad json: {e!r} :: {line!r}")
            continue
        try:
            handle(req)
        except Exception as e:  # noqa: BLE001
            log(f"handler error: {e!r}")
    log("=== probe server stdin closed ===")


if __name__ == "__main__":
    main()
