"""Windows 通知区域（托盘）支持。

::

    from meow.tray import MenuItem, SEPARATOR, TrayIcon, ensure_icons

    icons = ensure_icons(icon_dir)          # 生成猫头 .ico
    tray = TrayIcon(icons["off"], tooltip="meow")
    tray.start()
"""

from __future__ import annotations

from .icons import ICON_VERSION, build_ico, encode_ico, ensure_icons, render_icon
from .tray import SEPARATOR, MenuItem, TrayIcon

__all__ = [
    "ICON_VERSION",
    "MenuItem",
    "SEPARATOR",
    "TrayIcon",
    "build_ico",
    "encode_ico",
    "ensure_icons",
    "render_icon",
]
