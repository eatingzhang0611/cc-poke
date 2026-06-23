"""ntfy push adapter (https://ntfy.sh / self-hosted)."""

from __future__ import annotations

import urllib.request
from typing import Callable

from .base import Action, PushAdapter


def _default_poster(url: str, data: bytes, headers: dict[str, str], timeout: float) -> int:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return int(resp.status)


def _format_actions(actions: list[Action]) -> str:
    segs = []
    for a in actions:
        clear = "true" if a.clear else "false"
        segs.append(f"http, {a.label}, {a.url}, method={a.method}, clear={clear}")
    return "; ".join(segs)


class NtfyAdapter(PushAdapter):
    def __init__(
        self,
        server: str,
        topic: str,
        *,
        poster: Callable[[str, bytes, dict[str, str], float], int] = _default_poster,
        timeout: float = 10.0,
    ) -> None:
        self._server = server.rstrip("/")
        self._topic = topic
        self._poster = poster
        self._timeout = timeout

    def send(self, title: str, body: str, actions: list[Action] | None = None) -> bool:
        url = f"{self._server}/{self._topic}"
        headers = {
            "Title": title,  # ASCII only — see Global Constraints
            "Content-Type": "text/plain; charset=utf-8",
        }
        if actions:
            headers["Actions"] = _format_actions(actions)  # ASCII only
        try:
            status = self._poster(url, body.encode("utf-8"), headers, self._timeout)
        except Exception:
            return False
        return 200 <= status < 300
