"""Approval daemon: push approve/deny notifications and resolve decisions.

Single process, single port, stdlib-only. The reverse proxy should expose
ONLY /webhook and /d publicly; /requests stays localhost-only.
"""

from __future__ import annotations

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

_PAGE_DONE = (
    "<!doctype html><meta charset=utf-8><title>cc-poke</title>"
    "<body style='font-family:sans-serif;text-align:center;padding:3em'>"
    "<h2>Done</h2><p>You can close this page.</p></body>"
)
_PAGE_INVALID = (
    "<!doctype html><meta charset=utf-8><title>cc-poke</title>"
    "<body style='font-family:sans-serif;text-align:center;padding:3em'>"
    "<h2>No longer valid</h2><p>This request was already handled or has expired.</p></body>"
)
_PAGE_DECISION = (
    "<!doctype html><meta charset=utf-8><title>cc-poke</title>"
    "<body style='font-family:sans-serif;text-align:center;padding:2em'>"
    "<h2>cc-poke approval</h2>"
    "<form method=POST action='{base}/webhook'>"
    "<input type=hidden name=id value='{id}'>"
    "<input type=hidden name=s value='{s}'>"
    "<button name=d value=allow style='font-size:1.4em;padding:.5em 2em;margin:.5em'>Approve</button>"
    "</form>"
    "<form method=POST action='{base}/webhook'>"
    "<input type=hidden name=id value='{id}'>"
    "<input type=hidden name=s value='{s}'>"
    "<button name=d value=deny style='font-size:1.4em;padding:.5em 2em;margin:.5em'>Deny</button>"
    "</form></body>"
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
        s = self._config.webhook_secret
        actions = [
            Action("Approve", f"{base}/webhook?id={rid}&d=allow&s={s}"),
            Action("Deny", f"{base}/webhook?id={rid}&d=deny&s={s}"),
        ]
        title = f"cc-poke: approve {tool_name or 'tool'}?"  # ASCII
        if not self._adapter.send(title, summary or "(no detail)", actions):
            self.store.cancel(rid)
            return None
        return self.store.wait(rid, self._config.wait_seconds)

    def handle_webhook(self, rid: str, decision: str, secret: str) -> tuple[bool, str]:
        if not secret or secret != self._config.webhook_secret:
            return False, _PAGE_INVALID
        if decision not in ("allow", "deny"):
            return False, _PAGE_INVALID
        resolved = self.store.resolve(rid, decision)
        return resolved, (_PAGE_DONE if resolved else _PAGE_INVALID)

    def decision_page(self, rid: str, secret: str) -> str:
        return _PAGE_DECISION.format(
            base=html.escape(self._config.public_base_url, quote=True),
            id=html.escape(rid, quote=True),
            s=html.escape(secret, quote=True),
        )

    def dispatch(self, method: str, path: str, params: dict, body: bytes) -> Response:
        if path == "/requests" and method == "POST":
            try:
                data = json.loads(body or b"{}")
            except Exception:
                data = {}
            decision = self.handle_request(str(data.get("tool_name", "")), str(data.get("summary", "")))
            return Response(200, "application/json", json.dumps({"decision": decision}).encode("utf-8"))
        if path == "/webhook":
            _, page = self.handle_webhook(params.get("id", ""), params.get("d", ""), params.get("s", ""))
            return Response(200, "text/html; charset=utf-8", page.encode("utf-8"))
        if path == "/d":
            page = self.decision_page(params.get("id", ""), params.get("s", ""))
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
