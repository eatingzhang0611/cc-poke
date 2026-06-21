"""ntfy push adapter (https://ntfy.sh / self-hosted)."""

from __future__ import annotations

import urllib.request
from typing import Callable

from .base import PushAdapter


def _default_poster(url: str, data: bytes, headers: dict[str, str], timeout: float) -> int:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return int(resp.status)


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

    def send(self, title: str, body: str) -> bool:
        url = f"{self._server}/{self._topic}"
        headers = {
            "Title": title,  # ASCII only — see Global Constraints
            "Content-Type": "text/plain; charset=utf-8",
        }
        try:
            status = self._poster(url, body.encode("utf-8"), headers, self._timeout)
        except Exception:
            return False
        return 200 <= status < 300
