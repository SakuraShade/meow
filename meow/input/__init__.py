"""输入框读写后端。

常用组合::

    from meow.input import ClipboardBackend, TextGateway, UiaBackend

    gateway = TextGateway([UiaBackend(), ClipboardBackend()])
"""

from __future__ import annotations

from .base import Field, InputBackend, NullBackend
from .clipboard_backend import ClipboardBackend, ClipboardTiming
from .gateway import TextGateway
from .uia_backend import UiaBackend

__all__ = [
    "ClipboardBackend",
    "ClipboardTiming",
    "Field",
    "InputBackend",
    "NullBackend",
    "TextGateway",
    "UiaBackend",
    "default_gateway",
]


def default_gateway() -> TextGateway:
    """默认后端顺序：先 UIAutomation（不打扰剪贴板），失败再走剪贴板。"""
    return TextGateway([UiaBackend(), ClipboardBackend()])
