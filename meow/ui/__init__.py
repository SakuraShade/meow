"""Tkinter 图形界面。"""

from __future__ import annotations

import ctypes
import sys

from .app import MeowWindow
from .theme import Theme, apply_theme

__all__ = ["MeowWindow", "Theme", "apply_theme", "enable_dpi_awareness"]


def enable_dpi_awareness() -> bool:
    """让窗口在高 DPI 屏幕上不发虚。

    必须在创建 ``Tk`` 之前调用。失败（老系统 / 已经被设过）不是错误。
    """
    if sys.platform != "win32":
        return False
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
        return True
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        return True
    except Exception:
        return False
