"""Pluggable push-notification adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    """A tappable action attached to a push (e.g. an Approve/Deny button)."""

    label: str  # ASCII only — rendered into an HTTP header
    url: str    # ASCII only
    method: str = "POST"
    clear: bool = True


class PushAdapter(ABC):
    @abstractmethod
    def send(
        self,
        title: str,
        body: str,
        actions: list[Action] | None = None,
        click: str | None = None,
    ) -> bool:
        """Send one notification. Return True on success, False on failure.

        ``actions`` is an optional list of tappable buttons.
        ``click`` is an optional URL opened when the notification is tapped.
        Implementations MUST NOT raise — a push failure must never block Claude.
        """
        raise NotImplementedError
