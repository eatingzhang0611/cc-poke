"""Bark push adapter (https://bark.day.app — reliable iOS push).

Bark has no inline action buttons, so Approve/Deny happen on the web page
opened by tapping the notification: ``click`` maps to Bark's ``url`` field.
"""

from __future__ import annotations

import json
from typing import Callable

from .base import Action, PushAdapter


def _default_poster(url: str, data: bytes, headers: dict[str, str], timeout: float) -> int:
    import urllib.request

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return int(resp.status)


class BarkAdapter(PushAdapter):
    def __init__(
        self,
        server: str,
        device_key: str,
        *,
        poster: Callable[[str, bytes, dict[str, str], float], int] = _default_poster,
        timeout: float = 10.0,
        level: str = "timeSensitive",
    ) -> None:
        self._server = server.rstrip("/")
        self._device_key = device_key
        self._poster = poster
        self._timeout = timeout
        self._level = level

    def send(
        self,
        title: str,
        body: str,
        actions: list[Action] | None = None,  # noqa: ARG002 — Bark has no inline buttons
        click: str | None = None,
    ) -> bool:
        url = f"{self._server}/push"
        payload = {
            "device_key": self._device_key,
            "title": title,
            "body": body,
            "level": self._level,
        }
        if click:
            payload["url"] = click  # tapping the notification opens this URL
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json; charset=utf-8"}
        try:
            status = self._poster(url, data, headers, self._timeout)
        except Exception:
            return False
        return 200 <= status < 300
