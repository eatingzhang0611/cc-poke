# cc-poke — 设计文档

> 状态：待 review（2026-06-18 撰写）
> 项目名 `cc-poke` 为占位名，最终名待定。

## 1. 背景与动机

在 VPS 上用 Claude Code 开发，常通过 iPhone 的 Termius SSH 连接。Claude Code 经常停下来等用户处理**权限请求 / hook 批准**，但在手机终端上很难及时察觉，导致开发流被动卡住。

灵感来自 iPhone 灵动岛（"vibe island"）——希望在这种移动 SSH 场景下，能被动感知并响应 Claude Code 的等待状态。

**本项目为开源工具，不做商业化。** 目标用户是"已有 VPS、SSH 重度、注重隐私、不愿把会话交给第三方 SaaS"的开发者（作者本人即典型用户）。开源定位天然站在 Happy/Omnara 等自建会话托管方案够不到的"自托管、零第三方信任"位置。

## 2. 范围（Scope）

分两档，**本 spec 同时规划，但实现从档0 起步**。

- **档0 · 只通知（Phase 1，先做）**：Claude Code 停下等待时，推送提醒到 iPhone。用户仍需 SSH 回 Termius 手动 approve。
- **档1 · 远程批准（Phase 2，探针通过后做）**：用户直接在手机上点"批准/拒绝"，决定回传到 VPS 让 Claude 继续，无需切回终端。

**明确不做（YAGNI）：**
- 档2 原生 iOS App / 灵动岛 Live Activity —— 留给以后或社区。
- 会话托管平台（接管/托管 Claude 会话）—— 仅在档1 命门探针失败时才作为 Plan B 讨论。
- 商业化、账号体系、多用户。

## 3. 关键决策

| 决策 | 结论 | 理由 |
|------|------|------|
| 形态 | Claude Code 插件（hook + MCP）+ 小型本地服务 | 自托管、零第三方信任、可进 plugin marketplace |
| 推送通道 | 可插拔 adapter，**首实现 ntfy** | ntfy 纯开源可自托管，且原生支持免开 App 的 http 动作按钮，把档1 回传命门压力降到最低 |
| 第二通道 | Bark（紧随其后） | iOS 原生推送手感最好，适合档0 通知体验 |
| 排除通道 | Pushover | 闭源、不能自托管，与开源/零信任定位冲突 |
| 档1 回传基线 | "点通知 → 打开极简网页 → 点批准/拒绝 → 打 webhook" | 通道无关，不被各家按钮能力绑架 |
| 档1 回传增强 | ntfy 原生双按钮（免开 App） | 支持的通道才启用，作为体验升级 |

## 4. 架构与组件

```
┌─ VPS (workspace) ───────────────────────────────┐
│                                                  │
│  Claude Code ──(Notification hook)──> notifier   │  档0
│       │                                  │       │
│       └─(--permission-prompt-tool)─> MCP bridge   │  档1
│                                          │       │
│                              push adapter (ntfy)  │
│                              + decision webhook    │
└──────────────────────────────────│───────────────┘
                                    │ HTTPS
                              ┌─────▼─────┐
                              │  iPhone   │
                              │ ntfy/Bark │
                              └───────────┘
```

四个单元，各自单一职责、可独立理解与测试：

### 4.1 notifier（档0 核心）
- **做什么**：被 Claude Code 的 Notification hook 调用，把"Claude 在等你"消息交给 push adapter。
- **怎么用**：作为 hook command 配置在 Claude Code settings 中。
- **依赖**：push adapter。
- **特点**：无状态，最简单。推送失败不阻断 Claude（降级为本地 log）。

### 4.2 push adapter（可插拔）
- **做什么**：定义统一接口 `send(title, body, actions?) -> bool`，把"用哪个推送服务"与业务隔离。
- **怎么用**：notifier 和 MCP bridge 都通过此接口发推送；具体实现由配置选择。
- **依赖**：外部推送服务（ntfy server，可自托管）。
- **首实现**：ntfy。预留 Bark adapter 接口。

### 4.3 MCP bridge（档1 核心）
- **做什么**：作为 `--permission-prompt-tool` 注册给 Claude Code。收到权限请求 → 生成 `request_id` → 经 adapter 推一条带"批准/拒绝"动作的通知 → **阻塞等待**手机回传 → 把决定（allow/deny）返回给 Claude。
- **怎么用**：通过 `claude --permission-prompt-tool <this-mcp-tool>` 启用。
- **依赖**：push adapter、decision store。
- **关键参数**：等待超时（默认 5 分钟，可配）。

### 4.4 decision webhook（档1 回传）
- **做什么**：极简 HTTP 端点 + 极简网页。手机点按钮打到这里，记录决定到 decision store，唤醒阻塞中的 MCP bridge。
- **怎么用**：通知里的按钮/链接指向 `webhook?id=<request_id>&decision=allow|deny`。
- **依赖**：decision store（可为内存或轻量文件/sqlite）。

## 5. 数据流

### 档0 · 只通知
```
Claude 需要你 → Notification hook 触发 → notifier
  → adapter.send() → 手机弹通知
（用户 SSH 回 Termius 手动 approve）
```

### 档1 · 远程批准
```
Claude 要权限 → MCP bridge 收到 → 生成 request_id
  → adapter.send(带 批准/拒绝 按钮, 指向 webhook?id=xxx)
  → MCP bridge 阻塞轮询 decision store
手机点"批准" → webhook 记录 decision[xxx]=allow
  → MCP bridge 读到 → 返回 {allow} 给 Claude → Claude 继续
```

回传基线：点通知 → 打开极简网页 → 点批准/拒绝。
ntfy 通道升级：通知上原生双按钮，免开 App 直接打 webhook。

## 6. 命门探针（Phase 2 实现前的 go/no-go 关卡）

**实现档1 前，先用 0.5–1 天单独验证一件事**：在 Termius 的**交互式 `claude` 会话**里，`--permission-prompt-tool` 是否真的会把权限请求转给 MCP，而不是仍走终端 TUI 弹窗。

- **背景风险**：`--permission-prompt-tool` 主要为 headless / SDK 模式设计；交互式 TUI 是否走这条路径未经验证，这是整个档1 价值的命门。
- **探针做法**：写一个最小 MCP，权限请求来了就 log + 固定返回 allow，观察交互式会话是否真的走它。
- **结果分支**：
  - **成功** → 档1 按本设计实现。
  - **失败** → 触发 Plan B：档1 改为 headless 会话托管模式（工作量升级、定位变"轻量会话托管"），或档1 砍掉、稳定停在档0。

此关卡在 Phase 2 启动时必须先过。

## 7. 错误处理

- **推送失败**（网络/配置错）：notifier 不阻断 Claude，降级为本地 log。绝不因推送挂掉而卡住开发。
- **档1 等待超时**：MCP bridge 超时（默认 5 分钟，可配）返回 deny / 交还终端，避免 Claude 永久挂起。
- **webhook 收到未知/过期 request_id**：忽略并返回友好提示页。
- **配置缺失**（如未填 ntfy topic）：启动时校验 + 清晰报错，不静默失败。

## 8. 测试策略

- **push adapter**：单测 + mock HTTP，验证 ntfy 请求格式正确。
- **decision store / webhook**：单测"写入决定 → bridge 读到"的回路。
- **MCP bridge**：单测超时、未知 id、正常放行三条路径。
- **端到端冒烟**：手动脚本真发一条 ntfy 到手机，确认链路通。

## 9. 分期落地

- **Phase 1（先做）**：档0 notifier + ntfy adapter + Notification hook 配置 + README。交付即用。
- **Phase 2**：命门探针 → 成则 MCP bridge + decision webhook + 极简网页，完成档1。
- **Phase 3（可选/以后）**：Bark adapter；档2 原生灵动岛留给社区。

## 10. 开源维护边界（写进 README）

开源不等于零成本。为控制维护负担，**起步 scope 钉死为"通知 + 远程批准"**，不做会话托管平台。README 明确边界与非目标，避免 feature 蔓延。自己在用即达标；有人用是 bonus。
