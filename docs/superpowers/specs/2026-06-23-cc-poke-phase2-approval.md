# cc-poke Phase 2 — 档1 远程批准 设计文档

> 状态：brainstorming 定稿（2026-06-23），待 user review → writing-plans。
> 本文是 Phase 2（档1 远程批准）的细化设计，承接总设计
> `2026-06-18-cc-poke-design.md`（§4.3 / §7）。命门探针已过：`PreToolUse`
> hook 在交互式 TUI 能拦截工具、绕过审批弹窗、配 `timeout` 可阻塞数分钟。

## 1. 目标

Claude Code 在 VPS 停下等工具审批时，推一条带「批准/拒绝」按钮的通知到 iPhone；
用户在手机上点一下，决定回传 VPS，Claude 直接继续，无需 SSH 切回 Termius。

## 2. 已定的关键决策（brainstorming 2026-06-23）

| # | 决策 | 结论 | 理由 |
|---|------|------|------|
| 1 | 回传通道 | **VPS 公网 webhook**（用户 VPS 已有公网 HTTPS + 反代） | ntfy 原生 http 动作按钮可直接 POST 到 VPS，免开 App，体验最好 |
| 2 | hook↔daemon 通信 | **本地 long-poll** | 手机一点立刻唤醒；状态单一内存源、无文件竞争；localhost 长连接无成本；daemon 重启则连接断 → 落超时兜底（安全方向） |
| 3 | 推送范围 | **窄 matcher + cc-poke 自带 allowlist** | hook 只挂在在意的工具（Bash/Edit/Write…）；再用可配正则 allowlist（如 `^git status$`）直接放行不推，避免琐碎命令刷屏 |
| 4 | 超时兜底 | **退回终端弹窗** | hook 无决定退出 → CC 走原终端审批弹窗；最安全、不丢控制，仍可 SSH 手动批 |
| 5 | webhook 安全 | **不可猜一次性 `request_id` + 部署期共享 secret** | 公网「点一下就放行工具」是敏感面，双保险 |
| 6 | 部署形态 | **systemd unit**（保留裸跑入口） | VPS 内存吃紧；stdlib 零依赖进程 idle ~十几 MB，避开 Docker 容器叠加开销 |

## 3. 架构与组件

```
┌─ VPS ─────────────────────────────────────────────┐
│                                                    │
│  Claude Code ─(PreToolUse hook)─> cc-poke-approve   │ 短进程
│                                    │  ▲             │
│                          注册请求  │  │ 决定(long-poll)
│                                    ▼  │             │
│                          ┌──────────────────┐       │
│                          │  cc-poke-daemon   │ 常驻  │
│                          │  ·决定 store(内存)│       │
│                          │  ·/webhook 端点   │◀──┐   │
│                          │  ·极简决定网页    │   │   │
│                          └────────┬─────────┘   │   │
│                            adapter.send(actions) │   │
└───────────────────────────────────│─────────────│───┘
                              出站   │         入站 │ (反代/公网 HTTPS)
                                ┌────▼────┐         │
                                │ iPhone  │─点按钮──┘
                                │  ntfy   │
                                └─────────┘
```

四个单元，各自单一职责、可独立理解与测试：

### 3.1 `cc-poke-approve`（PreToolUse hook 客户端，短进程）
- **做什么**：作为 `PreToolUse` hook 被 Claude Code 调用。读 stdin 的 `{tool_name, tool_input}`；
  对照 cc-poke allowlist，命中则直接放行（不推送）；否则生成不可猜 `request_id`，
  POST 注册到本地 daemon，阻塞 long-poll 等决定，返回
  `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow"|"deny"}}`。
- **怎么用**：配在 settings 的 `hooks.PreToolUse`，用 `matcher` 选工具，并配较大 `timeout`（见 §6）。
- **依赖**：本地 daemon（HTTP localhost）、config。
- **特点**：自身等待窗（默认 300s）短于 CC 给 hook 的 `timeout`，超时则**无决定退出**（exit 0、不输出 permissionDecision）→ CC 走原终端弹窗。daemon 连不上/出错也降级为无决定退出，绝不卡死 Claude。

### 3.2 `cc-poke-daemon`（常驻服务）
- **做什么**：持有内存决定 store；收到 hook 注册请求后经 adapter 推一条带「批准/拒绝」按钮的通知；
  暴露 `/webhook`（手机点按钮打这）和一个极简决定网页（点通知打开后可点按钮的兜底）；
  收到决定后唤醒对应的 long-poll。
- **怎么用**：systemd 常驻（或 `cc-poke-daemon` 裸跑）。单进程单端口监听 localhost；
  反代只把 `/webhook` 与决定网页两个路径暴露到公网给手机，`/requests` 与 long-poll
  端点不在反代白名单里，仅 localhost 可达（见 §8）。
- **依赖**：push adapter、config。
- **并发**：`ThreadingHTTPServer`，long-poll 阻塞与 webhook 写入在不同线程；决定 store 用锁 + `threading.Event`/`Condition` 唤醒等待者。
- **内存**：stdlib 单进程零依赖，idle ~十几 MB。

### 3.3 push adapter（扩展）
- **做什么**：`send(title, body, actions=None) -> bool`。`actions` 为可选动作列表（如批准/拒绝），
  ntfy 实现把它们渲染成 http 动作按钮（`Actions` 头），指向公网 `/webhook?id=…&d=allow|deny&s=<secret>`。
- **兼容**：Phase 1 的 `send(title, body)` 调用不变（`actions` 默认 None）。
- **首实现**：`NtfyAdapter` 扩展。Bark 仍留待 Phase 3。

### 3.4 Notification 通知（Phase 1，不动）
- 继续作档0（Claude 泛等待提醒）。Phase 2 不修改其行为。

## 4. 数据流

```
Claude 要用工具 → PreToolUse hook 触发 → cc-poke-approve 读 {tool_name, tool_input}
  ├─ 命中 allowlist → 直接返回 permissionDecision:allow，结束（不推送）
  └─ 否则 → 生成 request_id = secrets.token_urlsafe(32)
       → POST localhost daemon /requests 注册 {id, tool_name, summary}
       → daemon: adapter.send(标题, 命令摘要,
             actions=[批准 → /webhook?id&d=allow&s, 拒绝 → /webhook?id&d=deny&s])
       → hook 阻塞 long-poll GET daemon（窗口默认 300s）
手机点「批准」 → 公网命中 daemon /webhook
       → 校验 secret + id 处于 pending + 未被决定过（一次性）
       → 记 decision[id]=allow，唤醒该 id 的等待者，返回友好页
       → daemon 应答 hook 的 long-poll：{decision: allow}
  → hook 返回 permissionDecision:allow → Claude 继续（不弹终端弹窗）
超时（300s 没点） → hook 无决定退出 → CC 走原终端审批弹窗（用户仍可 SSH 手动批）
```

回传基线：ntfy 原生双按钮（免开 App，直接打 `/webhook`）。
兜底：通知「点开」打开极简网页，页上同样的按钮打 `/webhook`（防个别客户端不渲染按钮）。

## 5. 配置

扩展 `~/.config/cc-poke/config.json`（Phase 1 字段保持兼容）：

| 字段 | 含义 | 默认/示例 |
|------|------|-----------|
| `daemon_url` | hook 连本地 daemon 的地址 | `http://127.0.0.1:8787` |
| `public_base_url` | 拼进按钮的公网地址（反代后） | `https://poke.example.com` |
| `webhook_secret` | 部署期生成的共享 secret，拼进 `/webhook` URL | 随机串 |
| `allowlist` | 正则数组，命中即放行不推送 | `["^git status$", "^ls( .*)?$"]` |
| `wait_seconds` | hook 等待窗口 | `300` |
| `ntfy_server` / `ntfy_topic` / `adapter` | Phase 1 既有 | — |

## 6. 超时分层（实现要点）

- cc-poke 内部等待窗 `wait_seconds`（如 300s）必须 **短于** CC 给 hook 配的 `timeout`（如 600s）。
- 这样 cc-poke 能在 CC 杀进程前干净地无决定退出 → CC 才会走它原本的终端弹窗。
- 若 CC 的 hook `timeout` 先触发，CC 对超时 hook 的处理不可控（可能阻断），故必须留足余量。

## 7. 错误处理

- **daemon 连不上 / hook 出错**：降级为无决定退出（不阻断 Claude）。
- **等待超时**：无决定退出 → 退回终端弹窗。
- **webhook 收到未知/过期/重复 id**：忽略写入，返回友好提示页（不报错、不泄露状态）。
- **webhook secret 不符**：拒绝并返回友好页。
- **推送失败**（adapter）：daemon 记录并立即让该请求走超时路径（不可能批准一条没推出去的请求）。
- **配置缺失**（如缺 `public_base_url`/`webhook_secret`）：daemon 启动时校验 + 清晰报错，不静默失败。

## 8. 安全

- `request_id`：`secrets.token_urlsafe(32)`，不可猜。
- `/webhook`：校验 `webhook_secret` + id 必须 pending + 一次性（决定后失效）。
- daemon 仅在请求 pending 期间持有 id，超时即清除（不可重放）。
- 决定网页与 `/webhook` 不泄露除「成功/已处理/无效」外的任何信息。
- localhost 注册/long-poll 接口不经公网（仅反代暴露 `/webhook` 与决定网页）。

## 9. 测试策略

- **adapter**：单测 `actions` 渲染进 ntfy 请求（`Actions` 头格式正确）；`send(title, body)` 旧签名兼容。
- **决定 store / daemon**：单测「注册 → webhook 写决定 → long-poll 读到」回路；未知/过期/重复 id 三条路径；secret 不符路径；超时清除。
- **approve hook**：单测 allowlist 命中放行、拿到 allow、拿到 deny、超时无决定退出、daemon 不可达降级 五条路径。
- **E2E 冒烟**：手动脚本真推一条带按钮通知到手机，点一下确认 daemon 收到决定、long-poll 放行。

## 10. 单元边界小结

| 单元 | 做什么 | 怎么用 | 依赖 |
|------|--------|--------|------|
| `cc-poke-approve` | PreToolUse hook 客户端：allowlist→注册→long-poll→返回决定 | settings hook command | daemon、config |
| `cc-poke-daemon` | 常驻：决定 store + webhook + 决定网页 + 推送 | systemd / 裸跑 | adapter、config |
| push adapter | `send(title, body, actions?)` | daemon 调用 | ntfy server |
| decision store | 内存 + 锁 + 唤醒；一次性、可超时清除 | daemon 内部 | — |

## 11. 非目标（YAGNI）

- 不做会话托管、不做账号体系、不做多用户。
- Bark adapter、档2 灵动岛留 Phase 3 / 社区。
- 不做 cc-poke 自己镜像 CC 完整权限规则；allowlist 只做简单正则放行。
