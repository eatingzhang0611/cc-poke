"""Approval daemon: push approve/deny notifications and resolve decisions.

Single process, single port, stdlib-only. The reverse proxy should expose
ONLY /webhook and /d publicly; /requests stays localhost-only.
"""

from __future__ import annotations

import hmac
import html
import json
import urllib.parse
from collections import namedtuple
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .adapters import make_adapter
from .adapters.base import Action
from .config import Config, ConfigError, load_config
from .store import DecisionStore

Response = namedtuple("Response", "status content_type body")

# --- approval page (terminal-console aesthetic, mobile-first, self-contained) ---

_STYLE = """<style>
*{box-sizing:border-box}
:root{
  --bg:#0d141c;--card:#121d28;--inset:#0a1117;--border:#22303d;
  --text:#e6edf3;--muted:#7d8da0;--teal:#5eead4;--amber:#f5b945;
  --approve:#2ea043;--approve-act:#26823a;--deny:#f85149;
}
html,body{margin:0}
body{background:var(--bg);color:var(--text);min-height:100dvh;
  font-family:-apple-system,system-ui,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;
  display:grid;place-items:center;padding:22px;line-height:1.45;-webkit-text-size-adjust:100%}
.card{width:100%;max-width:440px;background:var(--card);border:1px solid var(--border);
  border-radius:16px;padding:22px;box-shadow:0 14px 44px rgba(0,0,0,.5)}
.head{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px}
.brand{font-size:15px;font-weight:650;letter-spacing:.01em}
.brand b{color:var(--teal);font-weight:650}
.chip{display:inline-flex;align-items:center;gap:7px;font-size:12px;font-weight:600;
  color:var(--amber);background:#201a0c;border:1px solid #3a3115;border-radius:999px;padding:5px 11px}
.dot{width:7px;height:7px;border-radius:50%;background:var(--amber);
  box-shadow:0 0 0 0 rgba(245,185,69,.55);animation:pulse 1.9s infinite}
.label{color:var(--muted);font-size:13px;margin:0 0 10px}
.term{background:var(--inset);border:1px solid var(--border);border-radius:11px;padding:14px;
  font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-size:14px;color:#d7e2ee;
  white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere}
.term .p{color:var(--teal);user-select:none;margin-right:7px}
.caret{display:inline-block;width:7px;height:1.05em;background:var(--teal);
  vertical-align:-2px;margin-left:3px;animation:blink 1.05s steps(1) infinite}
.meta{margin:13px 2px 22px;font-size:12.5px;color:var(--muted)}
.meta .k{color:#9fb0c3}
.meta .v{color:var(--text);font-family:ui-monospace,"SF Mono",Menlo,monospace}
.actions{display:flex;gap:12px}
.actions form{flex:1;margin:0}
.btn{width:100%;border:0;border-radius:11px;padding:15px 0;font-size:16px;font-weight:650;
  cursor:pointer;-webkit-tap-highlight-color:transparent}
.approve{background:var(--approve);color:#fff}
.approve:active{background:var(--approve-act)}
.deny{background:transparent;color:var(--deny);border:1.5px solid #5a2a2a}
.deny:active{background:#2a1414}
.btn:focus-visible{outline:2px solid var(--teal);outline-offset:2px}
.note{text-align:center}
.note .glyph{font-size:38px;line-height:1;margin-bottom:10px}
.note h2{margin:0 0 6px;font-size:18px;font-weight:650}
.note p{margin:0;color:var(--muted);font-size:13.5px}
.ok .glyph{color:var(--approve)}
.gone .glyph{color:var(--deny)}
@keyframes blink{50%{opacity:0}}
@keyframes pulse{70%{box-shadow:0 0 0 7px rgba(245,185,69,0)}100%{box-shadow:0 0 0 0 rgba(245,185,69,0)}}
@media (prefers-reduced-motion:reduce){.caret,.dot{animation:none}}
</style>"""


def _doc(body: str) -> str:
    return (
        "<!doctype html><html lang=zh><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1,viewport-fit=cover'>"
        "<title>cc-poke</title>" + _STYLE + "</head><body>" + body + "</body></html>"
    )


_PAGE_DONE = _doc(
    "<main class='card note ok'><div class=glyph>&#10003;</div>"
    "<h2>已收到你的决定</h2>"  # 已收到你的决定
    "<p>可以关闭此页面。</p></main>"  # 可以关闭此页面。
)
_PAGE_INVALID = _doc(
    "<main class='card note gone'><div class=glyph>&#10005;</div>"
    "<h2>链接已失效</h2>"  # 链接已失效
    "<p>这条请求已处理或已过期。</p></main>"  # 这条请求已处理或已过期。
)


class DaemonApp:
    def __init__(self, store: DecisionStore, adapter, config: Config) -> None:
        self.store = store
        self._adapter = adapter
        self._config = config

    @classmethod
    def from_config(cls, config: Config) -> "DaemonApp":
        if not config.public_base_url:
            raise ConfigError('daemon requires a non-empty "public_base_url" in config')
        if not config.webhook_secret:
            raise ConfigError('daemon requires a non-empty "webhook_secret" in config')
        return cls(store=DecisionStore(), adapter=make_adapter(config), config=config)

    def handle_request(self, tool_name: str, summary: str) -> str | None:
        rid = self.store.register()
        base = self._config.public_base_url
        s = urllib.parse.quote(self._config.webhook_secret, safe="")
        actions = [
            Action("Approve", f"{base}/webhook?id={rid}&d=allow&s={s}"),
            Action("Deny", f"{base}/webhook?id={rid}&d=deny&s={s}"),
        ]
        t = urllib.parse.quote(tool_name or "", safe="")
        c = urllib.parse.quote(summary or "", safe="")
        click = f"{base}/d?id={rid}&s={s}&t={t}&c={c}"
        title = f"cc-poke: approve {tool_name or 'tool'}?"  # ASCII
        if not self._adapter.send(title, summary or "(no detail)", actions, click=click):
            self.store.cancel(rid)
            return None
        return self.store.wait(rid, self._config.wait_seconds)

    def handle_webhook(self, rid: str, decision: str, secret: str) -> tuple[bool, str]:
        if not secret or not hmac.compare_digest(secret, self._config.webhook_secret):
            return False, _PAGE_INVALID
        if decision not in ("allow", "deny"):
            return False, _PAGE_INVALID
        resolved = self.store.resolve(rid, decision)
        return resolved, (_PAGE_DONE if resolved else _PAGE_INVALID)

    def decision_page(self, rid: str, secret: str, tool_name: str = "", summary: str = "") -> str:
        base = html.escape(self._config.public_base_url, quote=True)
        rid_e = html.escape(rid, quote=True)
        s_e = html.escape(secret, quote=True)
        tool_e = html.escape(tool_name, quote=True) or "tool"
        cmd = summary.strip()
        cmd_e = html.escape(cmd) if cmd else "(no command detail)"
        hidden = (
            f"<input type=hidden name=id value=\"{rid_e}\">"
            f"<input type=hidden name=s value=\"{s_e}\">"
        )
        body = (
            "<main class=card>"
            "<div class=head><div class=brand>cc<b>&middot;</b>poke</div>"
            "<span class=chip><span class=dot></span>待批准</span></div>"  # 待批准 = pending
            "<p class=label>Claude 申请执行</p>"  # Claude 申请执行 = Claude wants to run
            f"<div class=term><span class=p>$</span>{cmd_e}<span class=caret></span></div>"
            f"<p class=meta><span class=k>工具</span> &nbsp;<span class=v>{tool_e}</span></p>"  # 工具 = tool
            "<div class=actions>"
            f"<form method=POST action=\"{base}/webhook\">{hidden}"
            "<button class='btn approve' name=d value=allow>Approve</button></form>"
            f"<form method=POST action=\"{base}/webhook\">{hidden}"
            "<button class='btn deny' name=d value=deny>Deny</button></form>"
            "</div></main>"
        )
        return _doc(body)

    def dispatch(self, method: str, path: str, params: dict, body: bytes) -> Response:
        if path == "/requests" and method == "POST":
            try:
                data = json.loads(body or b"{}")
            except Exception:
                data = {}
            decision = self.handle_request(str(data.get("tool_name", "")), str(data.get("summary", "")))
            return Response(200, "application/json", json.dumps({"decision": decision}).encode("utf-8"))
        if path == "/webhook" and method == "POST":
            _, page = self.handle_webhook(params.get("id", ""), params.get("d", ""), params.get("s", ""))
            return Response(200, "text/html; charset=utf-8", page.encode("utf-8"))
        if path == "/d":
            page = self.decision_page(
                params.get("id", ""), params.get("s", ""),
                params.get("t", ""), params.get("c", ""),
            )
            return Response(200, "text/html; charset=utf-8", page.encode("utf-8"))
        return Response(404, "text/plain; charset=utf-8", b"not found")


def _merge_params(query: str, body: bytes, content_type: str) -> dict:
    params = dict(urllib.parse.parse_qsl(query))
    if "application/x-www-form-urlencoded" in (content_type or ""):
        params.update(dict(urllib.parse.parse_qsl(body.decode("utf-8", "replace"))))
    return params


class _Handler(BaseHTTPRequestHandler):
    def _respond(self, method: str) -> None:
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        params = _merge_params(parsed.query, body, self.headers.get("Content-Type", ""))
        resp = self.server.app.dispatch(method, parsed.path, params, body)
        self.send_response(resp.status)
        self.send_header("Content-Type", resp.content_type)
        self.send_header("Content-Length", str(len(resp.body)))
        self.end_headers()
        self.wfile.write(resp.body)

    def do_GET(self):
        self._respond("GET")

    def do_POST(self):
        self._respond("POST")

    def log_message(self, *args):  # silence default stderr access log
        pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, app: DaemonApp):
        super().__init__(addr, _Handler)
        self.app = app


def main() -> int:
    config = load_config()
    app = DaemonApp.from_config(config)
    parsed = urllib.parse.urlparse(config.daemon_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8787
    server = _Server((host, port), app)
    print(f"cc-poke-daemon listening on {host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
