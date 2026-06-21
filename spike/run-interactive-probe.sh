#!/usr/bin/env bash
# cc-poke 命门探针 —— 交互式 TUI 测试启动器
#
# 用法：在 Termius / 任意真实终端里运行本脚本，会开一个交互式 claude 会话，
# 已挂好探针 MCP 作为 --permission-prompt-tool。
#
# 进会话后，把下面这句粘给 Claude（它需要审批才能跑）：
#
#     用 Bash 工具运行： rm -rf /tmp/cc-poke-probe-victim && mkdir /tmp/cc-poke-probe-victim
#
# 然后观察两件事（这就是 go/no-go 证据）：
#   A. 终端有没有弹出常规的「权限审批」TUI 弹窗？
#   B. 退出会话后，看 probe.log 里有没有新的 `!!! tools/call` 行：
#        cat /home/yd/workspace/cc-poke/spike/probe.log
#
# 判定：
#   - 没弹 TUI 弹窗 + probe.log 出现 tools/call  => 成功（交互式也走 MCP，档1 可做）
#   - 弹了 TUI 弹窗  + probe.log 没有 tools/call  => 失败（交互式绕过 MCP，触发 Plan B）

set -euo pipefail
SPIKE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== 清空旧日志 ==="
: > "$SPIKE_DIR/probe.log"

echo "=== 启动交互式 claude（已挂探针）==="
echo "进去后粘这句： 用 Bash 工具运行： rm -rf /tmp/cc-poke-probe-victim && mkdir /tmp/cc-poke-probe-victim"
echo

claude \
  --mcp-config "$SPIKE_DIR/mcp-config.json" \
  --permission-prompt-tool mcp__poke__approve \
  --permission-mode default \
  --strict-mcp-config

echo
echo "=== 退出了。看证据： ==="
echo "cat $SPIKE_DIR/probe.log"
