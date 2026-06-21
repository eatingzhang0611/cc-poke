"""Push adapters and the adapter factory."""

from __future__ import annotations

from ..config import Config
from .base import PushAdapter
from .ntfy import NtfyAdapter

__all__ = ["PushAdapter", "NtfyAdapter", "make_adapter"]


def make_adapter(config: Config) -> PushAdapter:
    if config.adapter == "ntfy":
        return NtfyAdapter(config.ntfy_server, config.ntfy_topic)
    raise ValueError(f"unknown push adapter: {config.adapter!r}")
