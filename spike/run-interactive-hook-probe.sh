#!/usr/bin/env bash
# cc-poke 命门探针 2 —— PreToolUse hook 交互式 TUI 测试
#
# 用法：在 Termius/真实终端运行本脚本，开一个交互式 claude，已挂 PreToolUse hook。
#
# 进会话后粘这句（需审批的命令）：
#     用 Bash 工具运行： rm -rf /tmp/cc-poke-hook-victim && mkdir /tmp/cc-poke-hook-victim
#
# 观察 + 判定（这是这条路的 go/no-go）：
#   - 没弹「1 yes / 2 always / 3 no」审批弹窗，命令直接跑了
#     + hook_probe.log 出现 `PreToolUse`  => 成功！hook 能在交互式拦截+放行，档1 走 hook 这条路
#   - 仍弹审批弹窗  => 这条路也不行，回到「只做档0 / 会话托管」讨论
#
# 退出后看证据： cat /home/yd/workspace/cc-poke/spike/hook_probe.log

set -euo pipefail
SPIKE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== 清空旧日志 ==="
: > "$SPIKE_DIR/hook_probe.log"

echo "=== 启动交互式 claude（已挂 PreToolUse hook）==="
echo "进去后粘： 用 Bash 工具运行： rm -rf /tmp/cc-poke-hook-victim && mkdir /tmp/cc-poke-hook-victim"
echo "看：还弹不弹那个 1/2/3 审批弹窗？"
echo

claude \
  --settings "$SPIKE_DIR/hook-settings.json" \
  --permission-mode default

echo
echo "=== 退出了。看证据： ==="
echo "cat $SPIKE_DIR/hook_probe.log"
