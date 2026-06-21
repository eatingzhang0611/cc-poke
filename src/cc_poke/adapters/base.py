"""Pluggable push-notification adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class PushAdapter(ABC):
    @abstractmethod
    def send(self, title: str, body: str) -> bool:
        """Send one notification. Return True on success, False on failure.

        Implementations MUST NOT raise — a push failure must never block Claude.
        """
        raise NotImplementedError
