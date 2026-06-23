# cc-poke

当 Claude Code 停下等待时，把提醒推送到你的 iPhone（自托管、零第三方信任）。
Phase 1 = 只通知（你仍 SSH 回终端 approve）。

## 安装

前置：Debian/Ubuntu 需先装 venv 支持：`sudo apt install python3.12-venv`（其他平台通常已内置）。

```bash
cd /home/yd/workspace/cc-poke
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
echo '{"message":"hello from cc-poke","cwd":"/tmp"}' | /home/yd/workspace/cc-poke/.venv/bin/cc-poke-notify
```
手机应收到一条标题为 `cc-poke: Claude needs you`、正文含 `hello from cc-poke` 的通知。

## 设计与边界

见 `docs/superpowers/specs/2026-06-18-cc-poke-design.md`。
**起步 scope 钉死为"通知 + 远程批准"，不做会话托管平台。** 档1（手机远程批准）见 Phase 2。

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
