# cc-poke

[![CI](https://github.com/eatingzhang0611/cc-poke/actions/workflows/ci.yml/badge.svg)](https://github.com/eatingzhang0611/cc-poke/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

When Claude Code stops and waits for you, cc-poke sends a notification to your
phone. You can also approve or deny a command from the phone, and Claude Code
continues — no need to switch back to the terminal. It is self-hosted: the only
thing that leaves your machine is a short notification, sent through a push
service you choose.

> 当 Claude Code 停下来等你时，cc-poke 把一条通知推到你手机上。你还可以在手机上
> 直接点「批准 / 拒绝」，Claude Code 就接着跑，不用切回终端。它是自托管的：离开你
> 机器的只有一条通知，走你自己选的推送服务。

There are two levels, and you can stop at the first:

1. **Notify** — tell you on your phone that Claude Code needs attention. You
   still go back to the terminal to act.
2. **Remote approve** — tap Approve/Deny on the phone; the decision goes back to
   Claude Code and it continues.

> 分两档，用第一档就够：**1) 只通知** —— 手机上提醒你 Claude Code 在等，你仍回终端
> 操作；**2) 远程批准** —— 手机上点批准/拒绝，决定回传，Claude Code 直接继续。

## How it works / 工作原理

```
Claude Code ──hook──▶ cc-poke ──push──▶ your phone
                         ▲                   │
                         └──── decision ◀──tap┘   (remote-approve only)
```

cc-poke is two small pieces:

- A **hook** that Claude Code runs on each event (a notification, or a tool
  about to run). It is short-lived.
- A **daemon** (remote-approve only) that holds the pending decision, pushes the
  notification, and serves the approval page and the decision webhook.

If anything fails — push down, network gone, no answer in time — the hook exits
without a decision and Claude Code falls back to its normal terminal prompt. It
never blocks you.

> cc-poke 由两部分组成：**hook**（Claude Code 每次事件时运行，短命进程）和
> **daemon**（仅远程批准时需要，保存待决定、推通知、提供审批页与回调 webhook）。
> 任何环节出错——推送挂了、断网、超时没人理——hook 都会不带决定地退出，Claude Code
> 回退到它自己的终端提示。它绝不会把你卡住。

## The approval page / 审批页

Tapping the notification opens a small page showing the exact command before you
decide. Open [`assets/approval-page.html`](assets/approval-page.html) in a
browser for a live preview.

> 点开通知会打开一个小页面，决定前先看清要执行的命令。浏览器打开
> [`assets/approval-page.html`](assets/approval-page.html) 可预览。

![cc-poke approval page](assets/approval-page.png)

## Requirements / 依赖

- Python 3.10+
- A push app on your phone: **ntfy** (default) or **Bark** (iOS).
- For remote approve: Linux with a systemd user session, and an HTTPS reverse
  proxy in front of the daemon.

> Python 3.10+；手机推送 app（**ntfy** 默认，或 iOS 的 **Bark**）；远程批准还需
> Linux + systemd 用户会话，以及给 daemon 套一层 HTTPS 反代。

On Debian/Ubuntu you may need venv support first: `sudo apt install python3-venv`.

## Install / 安装

```bash
git clone git@github.com:eatingzhang0611/cc-poke.git
cd cc-poke
./install.sh
```

`install.sh` is idempotent. It creates a virtualenv, installs the package,
writes `~/.config/cc-poke/config.json` with a generated `webhook_secret`, and
installs the systemd user unit (without starting it). It then prints the
remaining steps. Edit the config before using it.

> `install.sh` 可重复运行：建 venv、装包、生成带随机 `webhook_secret` 的
> `~/.config/cc-poke/config.json`、装好 systemd 用户单元（不自动启动），最后打印后续
> 步骤。用之前先改配置。

## Push channels / 推送通道

cc-poke ships two backends, picked with the `adapter` field. The default is
**ntfy** (open source, self-hostable, notifications carry inline Approve/Deny
buttons). Works on iOS, Android, and desktop.

```json
{ "adapter": "ntfy", "ntfy_server": "https://ntfy.sh", "ntfy_topic": "a-long-random-string" }
```

**Bark** is an alternative for iOS. It has no inline buttons, so Approve/Deny
happen on the page opened by tapping the notification. Install the Bark app,
copy its device key, then:

```json
{ "adapter": "bark", "bark_server": "https://api.day.app", "bark_device_key": "your-device-key" }
```

> 两个后端用 `adapter` 切换。默认 **ntfy**（开源、可自建、通知带内联 Approve/Deny
> 按钮，iOS/Android/桌面都能用）。**Bark** 是 iOS 备选，没有内联按钮，点通知打开页面
> 再批准。

### Not getting banners on iOS? / iOS 收不到横幅？

This is almost always your network, not ntfy. Both ntfy and Bark deliver
background notifications through Apple's APNs, which uses a long-lived
connection on port 5223. Some Wi-Fi networks allow normal web traffic
(80/443) but block 5223, so no APNs-based app gets background banners on them.

Quick check: switch to cellular data or turn on a VPN. If banners come back, the
Wi-Fi is blocking APNs — switching adapter won't help; fix it on the network
side (allow 5223, use a VPN, or use cellular).

> iOS 收不到横幅，基本是网络问题，不是 ntfy 的锅。ntfy 和 Bark 的后台推送都走 Apple
> APNs（长连接，5223 端口）。有些 WiFi 能正常上网（80/443）却拦了 5223，于是任何走
> APNs 的 app 都收不到后台横幅。**快速判定**：换蜂窝或开 VPN，横幅回来就是 WiFi 拦了
> APNs，换 adapter 没用，得从网络侧解决。

## Configuration / 配置

`~/.config/cc-poke/config.json`. See [`config.example.json`](config.example.json).

| Field | Used by | Meaning |
|-------|---------|---------|
| `adapter` | all | `"ntfy"` or `"bark"`. |
| `ntfy_server` / `ntfy_topic` | ntfy | Server URL and topic. Treat the topic as a password — make it long and random. |
| `bark_server` / `bark_device_key` | bark | Bark server and your device key. |
| `daemon_url` | approve hook | Where the hook reaches the daemon. Default `http://127.0.0.1:8787`. |
| `public_base_url` | daemon | Your public HTTPS address for the reverse proxy, e.g. `https://poke.example.com`. |
| `webhook_secret` | daemon | Shared secret guarding the decision webhook. Generated by `install.sh`. |
| `allowlist` | approve hook | Regexes for Bash commands to allow silently (no push), so trivial commands don't spam you. |
| `wait_seconds` | daemon | How long to wait for a phone decision before falling back to the terminal. Default 300. |

## Level 1: notifications only / 只通知

Merge [`hooks/notification-settings.example.json`](hooks/notification-settings.example.json)
into your Claude Code settings (`~/.claude/settings.json` or a project
`.claude/settings.json`), using the absolute path to `cc-poke-notify` printed by
`install.sh`.

Check it:

```bash
echo '{"message":"hello from cc-poke","cwd":"/tmp"}' | .venv/bin/cc-poke-notify
```

Your phone should get a notification titled `cc-poke: Claude needs you`.

> 把 `hooks/notification-settings.example.json` 合并进 Claude Code 设置，`command`
> 用 `install.sh` 打印的 `cc-poke-notify` 绝对路径。用上面的命令验证。

## Level 2: remote approve / 远程批准

This needs the daemon and a reverse proxy.

**1. Edit the config** — set `public_base_url` to your HTTPS address. Optionally
fill `allowlist` so trivial commands run without a push.

**2. Reverse proxy — expose only `/webhook` and `/d`.** Keep `/requests`
private (the hook calls it on localhost). Examples:

Caddy:

```
poke.example.com {
    @public path /webhook /d
    handle @public {
        reverse_proxy 127.0.0.1:8787
    }
    respond 404
}
```

nginx:

```nginx
server {
    listen 443 ssl;
    server_name poke.example.com;
    # ssl_certificate ... ; ssl_certificate_key ... ;
    location = /webhook { proxy_pass http://127.0.0.1:8787; }
    location = /d       { proxy_pass http://127.0.0.1:8787; }
    location /          { return 404; }
}
```

**3. Start the daemon:**

```bash
systemctl --user enable --now cc-poke-daemon
systemctl --user status cc-poke-daemon
```

**4. Register the approve hook** — merge
[`hooks/pretooluse-settings.example.json`](hooks/pretooluse-settings.example.json)
into your settings, using the `cc-poke-approve` path.

> 远程批准需要 daemon + 反代。改 `public_base_url`；反代**只**放行 `/webhook` 和
> `/d`，`/requests` 保持私有；起 daemon；注册 PreToolUse hook。

**Timeout rule.** The hook's `timeout` must be at least `wait_seconds + 30`,
otherwise Claude Code kills the hook before cc-poke can fall back to the terminal
prompt. If you raise `wait_seconds`, raise the hook `timeout` to match.

> **超时规则**：hook 的 `timeout` 必须 ≥ `wait_seconds + 30`，否则 Claude Code 会在
> cc-poke 退回终端弹窗前就杀掉 hook。调大 `wait_seconds` 时同步调大 `timeout`。

**End-to-end check:** in an interactive `claude` session, run a command not in
your allowlist (e.g. `rm -rf /tmp/cc-poke-test`). The phone gets a notification
with Approve/Deny → tap Approve → the command runs without a terminal prompt.

## Security / 安全

- `/webhook` runs a tool when tapped, so it is a sensitive endpoint. It is
  guarded by an unguessable `request_id`, the shared `webhook_secret` (compared
  in constant time), and being one-shot — a decision is consumed once and the
  request expires.
- Serve everything over HTTPS and keep `webhook_secret` private.
- Anyone who can read your ntfy topic can see the command in the notification
  body. Treat the topic itself as a secret.
- Expose only `/webhook` and `/d`. Never expose `/requests`.
- The `allowlist` is matched against the full command with `re.search`. Anchor
  every pattern (`^...$`) **and** exclude shell metacharacters (`; & | < > $ ( )`
  and backticks) in the argument part. Otherwise a loose pattern like
  `^ls( .*)?$` also allows `ls && rm -rf x`, which would then run with no push.

> `/webhook` 点一下就放行工具执行，是敏感端点：用不可猜的 `request_id` + 共享
> `webhook_secret`（常数时间比较）+ 一次性（用过即失效）防护。全程 HTTPS，
> `webhook_secret` 保密。能读你 ntfy topic 的人能看到命令内容，topic 本身要当机密。
> 只暴露 `/webhook` 和 `/d`，绝不暴露 `/requests`。`allowlist` 用 `re.search` 对整条
> 命令匹配——每个模式都要两端锚定 `^...$` **且**在参数里排除 shell 元字符
> （`; & | < > $ ( )` 和反引号），否则 `^ls( .*)?$` 这种松写法会连 `ls && rm -rf x`
> 一起放行、直接执行不推送。

## Uninstall / 卸载

```bash
./uninstall.sh           # stop and remove the daemon unit
./uninstall.sh --purge   # also remove the venv and config
```

It does not edit your Claude Code settings — remove the cc-poke hook entries
yourself.

> `uninstall.sh` 不会动你的 Claude Code 设置，hook 条目请自行删除。

## Development / 开发

```bash
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```

No runtime dependencies; the standard library only. Tests cover the config,
adapters, decision store, daemon, hooks, and entry points.

> 无运行时依赖，纯标准库。测试覆盖配置、适配器、决定 store、daemon、hook 和入口点。

## License / 许可证

MIT — see [LICENSE](LICENSE).
