"""In-memory, thread-safe, one-shot decision store for the approval daemon."""

from __future__ import annotations

import secrets
import threading
import time


class DecisionStore:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._decisions: dict[str, str | None] = {}  # rid -> None(pending) | "allow"/"deny"

    def register(self) -> str:
        rid = secrets.token_urlsafe(32)
        with self._cond:
            self._decisions[rid] = None
        return rid

    def resolve(self, rid: str, decision: str) -> bool:
        with self._cond:
            if rid not in self._decisions:
                return False  # unknown, or already consumed by wait()
            if self._decisions[rid] is not None:
                return False  # already decided (one-shot)
            self._decisions[rid] = decision
            self._cond.notify_all()
            return True

    def wait(self, rid: str, timeout: float) -> str | None:
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                cur = self._decisions.get(rid)
                if cur is not None:
                    del self._decisions[rid]
                    return cur
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._decisions.pop(rid, None)
                    return None
                self._cond.wait(remaining)

    def cancel(self, rid: str) -> None:
        with self._cond:
            self._decisions.pop(rid, None)
