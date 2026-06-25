"""Push adapters and the adapter factory."""

from __future__ import annotations

from ..config import Config
from .bark import BarkAdapter
from .base import PushAdapter
from .ntfy import NtfyAdapter

__all__ = ["PushAdapter", "NtfyAdapter", "BarkAdapter", "make_adapter"]


def make_adapter(config: Config) -> PushAdapter:
    if config.adapter == "ntfy":
        return NtfyAdapter(config.ntfy_server, config.ntfy_topic)
    if config.adapter == "bark":
        if not config.bark_device_key:
            raise ValueError('adapter "bark" requires a non-empty "bark_device_key"')
        return BarkAdapter(config.bark_server, config.bark_device_key)
    raise ValueError(f"unknown push adapter: {config.adapter!r}")
