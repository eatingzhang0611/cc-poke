# cc-poke 命门探针（feasibility spike）

验证：`claude --permission-prompt-tool mcp__poke__approve` 是否真的把权限请求转给 MCP。
这是 spec §6 定的 Phase 2 go/no-go 关卡。

## 文件
- `mcp_probe.py` — 最小 MCP stdio server（纯 stdlib）。被调用就写 `probe.log` 并固定返回 allow。
- `mcp-config.json` — 把上面注册成名为 `poke` 的 server，工具名 `approve`（即 `mcp__poke__approve`）。
- `run-interactive-probe.sh` — 交互式 TUI 测试启动器。

## 已验证结论

环境：Claude Code **2.1.185**，Linux VPS，Python 3.12。

| 项 | 结果 |
|----|------|
| `--permission-prompt-tool` flag 是否还在 | **在**（2.1.185 里从 `--help` 隐藏了，但仍被接受） |
| MCP 协议握手 / tools/list / tools/call | 通过（手动喂 JSON-RPC 验证） |
| **print 模式 (`-p`)** 权限请求是否走 MCP | **PASS** —— 需审批的命令触发 `tools/call`，返回 allow 后执行 |
| **交互式 TUI** 权限请求是否走 MCP | **待测**（见下，需真实终端） |

权限工具收到的参数契约（实测）：
```json
{ "tool_name": "Bash",
  "input": { "command": "...", "description": "..." },
  "tool_use_id": "toolu_..." }
```
必须返回（作为 tool result 的 text content，JSON 字符串化）：
```json
{ "behavior": "allow", "updatedInput": { ... } }
// 或
{ "behavior": "deny", "message": "..." }
```
注意：安全命令（如 `echo`）会被自动放行、不触发权限工具；测试要用需审批的命令（如 `rm -rf`）。

## 交互式测试怎么跑（命门最后一关）

在 Termius/真实终端里：
```bash
/home/yd/workspace/cc-poke/spike/run-interactive-probe.sh
```
进会话后粘：`用 Bash 工具运行： rm -rf /tmp/cc-poke-probe-victim && mkdir /tmp/cc-poke-probe-victim`

观察 + 判定：
- **没弹常规 TUI 审批弹窗 + `probe.log` 出现 `tools/call`** → 成功，交互式也走 MCP，**档1 按设计做**。
- **弹了 TUI 弹窗 + `probe.log` 没有 `tools/call`** → 失败，交互式绕过 MCP，**触发 Plan B**（headless 会话托管 / 或档1 砍掉停在档0）。
