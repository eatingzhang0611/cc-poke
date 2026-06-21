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
