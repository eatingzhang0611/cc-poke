# cc-poke

[![CI](https://github.com/eatingzhang0611/cc-poke/actions/workflows/ci.yml/badge.svg)](https://github.com/eatingzhang0611/cc-poke/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[English](README.md) | **中文**

Claude Code 停下来等你授权时，往你手机推一条通知——你直接在手机上批准或拒绝，
Claude Code 就接着跑，不用切回终端。自托管：离开你机器的只有一条通知，走你自己
选的推送服务。

## 特点

- **自托管、低信任。** 没有 cc-poke 云端。对外发出的只有一条通知，走你掌控的推送
  服务（ntfy 或 Bark）。
- **双向，不只是提醒。** 在手机上点批准/拒绝，决定回传给 Claude Code——不用切回
  终端。
- **天生 fail-safe。** 推送失败、断网、超时没人理，hook 都会不带决定地退出，Claude
  Code 回退到它自己的终端弹窗。它绝不会把你卡住。
- **可插拔推送。** ntfy（默认，带内联 Approve/Deny 按钮）或面向 iOS 的 Bark。加一个
  新通道只是写一个小 adapter 类。
- **默认安静。** allowlist 把日常琐碎命令静音，只有真正要紧的才推到你手机。
- **轻量。** 纯 Python 标准库，零运行时依赖；daemon 空载只占几 MB 内存。

## 工作原理

cc-poke = 两个 hook + 一个小 daemon。可以只用第一个，也可以两个都用。

- **通知** —— `cc-poke-notify` 在 Claude Code 每次 *Notification* 事件时运行，推一条
  就退出。只想知道「Claude 在等你」的话，这个就够。
- **远程批准** —— `cc-poke-approve` 在工具执行**之前**运行：把请求交给常驻的
  `cc-poke-daemon` 并阻塞等待。daemon 推一条带 Approve/Deny 的通知，等你点它的
  webhook，再把决定回传给 hook，由 hook 告诉 Claude Code 放行还是拒绝。

```
                  ┌──────────────────── 你的机器 ────────────────────┐
  Claude Code ──▶ │  approve hook ──▶ daemon ──┐                      │
       ▲          │       ▲                     │ 推送                │
       │ 放行/    │       │ 决定                ▼                     │
       │ 拒绝     │       └──────── webhook ◀── 反向代理 ◀───────────┼──▶ 手机
       └──────────┤                  (HTTPS)                          │   （点击）
                  └───────────────────────────────────────────────────┘
```

通知这条路只有 hook 和一次推送——不需要 daemon、不需要反代。远程批准才加上 daemon
（保存待决定、提供审批页和 webhook）和它前面的 HTTPS 反向代理。

**Fail-safe。** 任何失败——推送挂了、断网、超时——最后都是 hook 不带决定退出，于是
Claude Code 用它自己的终端弹窗。

## 审批页

点开通知会打开一个页面，决定前先看清要执行的命令。浏览器打开
[`assets/approval-page.html`](assets/approval-page.html) 可预览。

![cc-poke 审批页](assets/approval-page.png)

## 依赖

- Python 3.10+（Debian/Ubuntu 可能需要先 `sudo apt install python3-venv`）。
- 手机推送 app：**ntfy**（默认）或 **Bark**（iOS）。
- 仅远程批准需要：Linux + systemd 用户会话，以及 daemon 前面的 HTTPS 反向代理。

## 安装

```bash
git clone git@github.com:eatingzhang0611/cc-poke.git
cd cc-poke
./install.sh
```

`install.sh` 可重复运行：建 venv、装包、生成带随机 `webhook_secret` 的
`~/.config/cc-poke/config.json`、装好 systemd 用户单元（不自动启动）。它会打印后续
步骤，且不会动你的 Claude Code 设置。用之前先改配置。

## 推送通道

用 `adapter` 字段选后端。默认 **ntfy**：开源、可自建，通知带内联 Approve/Deny 按钮，
iOS / Android / 桌面都能用。

```json
{ "adapter": "ntfy", "ntfy_server": "https://ntfy.sh", "ntfy_topic": "一串长随机字符" }
```

**Bark** 是 iOS 备选。它没有内联按钮，所以批准/拒绝在点开通知后的页面上完成。装好
app、复制 device key，然后：

```json
{ "adapter": "bark", "bark_server": "https://api.day.app", "bark_device_key": "你的-device-key" }
```

> **iOS 收不到横幅？基本是网络问题，不是 ntfy 的锅。** ntfy 和 Bark 的后台推送都走
> Apple APNs（长连接，5223 端口）。有些 WiFi 能正常上网（80/443）却拦了 5223，于是
> 任何走 APNs 的 app 都收不到后台横幅。换蜂窝或开 VPN 测一下——横幅回来就说明是
> WiFi 的问题，换 adapter 没用。

## 配置

`~/.config/cc-poke/config.json`，参见 [`config.example.json`](config.example.json)。

| 字段 | 谁用 | 含义 |
|------|------|------|
| `adapter` | 全部 | `"ntfy"` 或 `"bark"`。 |
| `ntfy_server` / `ntfy_topic` | ntfy | 服务器和 topic。topic 当密码用——要长、要随机。 |
| `bark_server` / `bark_device_key` | bark | Bark 服务器和你的 device key。 |
| `daemon_url` | approve hook | hook 找 daemon 的地址。默认 `http://127.0.0.1:8787`。 |
| `public_base_url` | daemon | 你的公网 HTTPS 地址，如 `https://poke.example.com`。 |
| `webhook_secret` | daemon | 守护 webhook 的共享密钥。`install.sh` 自动生成。 |
| `allowlist` | approve hook | 静默放行（不推送）的 Bash 命令正则。见[安全](#安全)。 |
| `wait_seconds` | daemon | 等手机决定多久后回退。默认 300。 |

## 通知

把 [`hooks/notification-settings.example.json`](hooks/notification-settings.example.json)
合并进你的 Claude Code 设置（`~/.claude/settings.json` 或项目级 `.claude/settings.json`），
`command` 用 `install.sh` 打印的 `cc-poke-notify` 绝对路径。验证：

```bash
echo '{"message":"hello from cc-poke","cwd":"/tmp"}' | .venv/bin/cc-poke-notify
```

手机应收到一条标题为 `cc-poke: Claude needs you` 的通知。

## 远程批准

**1. 配置。** 把 `public_base_url` 设成你的 HTTPS 地址。可选填 `allowlist`，让日常
命令不推送直接跑。

**2. 反向代理——只放行 `/webhook` 和 `/d`。** `/requests` 保持私有（hook 在
localhost 调它）。

Caddy：

```
poke.example.com {
    @public path /webhook /d
    handle @public { reverse_proxy 127.0.0.1:8787 }
    respond 404
}
```

nginx：

```nginx
server {
    listen 443 ssl;
    server_name poke.example.com;
    location = /webhook { proxy_pass http://127.0.0.1:8787; }
    location = /d       { proxy_pass http://127.0.0.1:8787; }
    location /          { return 404; }
}
```

**3. 启动 daemon。**

```bash
systemctl --user enable --now cc-poke-daemon
```

**4. 注册 approve hook。** 把
[`hooks/pretooluse-settings.example.json`](hooks/pretooluse-settings.example.json)
合并进设置，`command` 用 `cc-poke-approve` 路径。默认 matcher 是 `Bash|Edit|Write`，
只想拦 shell 命令就改成 `Bash`。

> **超时规则。** hook 的 `timeout` 必须 ≥ `wait_seconds + 30`，否则 Claude Code 会在
> cc-poke 退回终端弹窗前就杀掉 hook。调大 `wait_seconds` 时同步调大 `timeout`。

**端到端验证。** 在交互式 `claude` 里跑一条不在 allowlist 的命令（如
`rm -rf /tmp/cc-poke-test`），手机收到 Approve/Deny → 点 Approve → 命令直接执行、
不弹终端。

## 安全

- `/webhook` 点一下就放行工具执行，是敏感端点：用不可猜的 `request_id` + 共享
  `webhook_secret`（常数时间比较）+ 一次性（用过即失效）防护。
- 全程 HTTPS，`webhook_secret` 保密。
- 能读你 ntfy topic 的人能看到通知里的命令。topic 本身要当机密。
- 只暴露 `/webhook` 和 `/d`，绝不暴露 `/requests`。
- `allowlist` 用 `re.search` 对整条命令匹配。每个模式都要两端锚定 `^...$`，**并且**
  在参数里排除 shell 元字符（`; & | < > $ ( )` 和反引号）。`^ls( .*)?$` 这种松写法会
  连 `ls && rm -rf x` 一起放行、直接执行不推送。

## 卸载

```bash
./uninstall.sh           # 停止并移除 daemon 单元
./uninstall.sh --purge   # 连 venv 和配置一起删
```

它不会动你的 Claude Code 设置——hook 条目请自行删除。

## 开发

```bash
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```

无运行时依赖，纯标准库。测试覆盖配置、适配器、决定 store、daemon、hook 和入口点。

## 许可证

MIT，见 [LICENSE](LICENSE)。
