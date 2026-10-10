"""界面配色与 ttk 样式。

统一用 ``clam`` 主题做底：Windows 默认的 ``vista`` 主题会忽略大量样式选项，
在它上面做自定义配色会处处碰壁。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# ---------------- 配色 ----------------

COLORS = {
    "bg": "#FFF9F2",          # 窗口底色（奶白）
    "panel": "#FFFFFF",       # 卡片
    "border": "#EADFD2",
    "text": "#3B342D",
    "muted": "#8C8177",
    "accent": "#F2994A",      # 主色（橘猫）
    "accent_dark": "#D97E2B",
    "accent_soft": "#FFE9D2",
    "track_off": "#CFC7BE",
    "ok": "#3FA46A",
    "warn": "#D98A1F",
    "err": "#D9534F",
    "debug": "#9A9089",
}

FONT_CANDIDATES = ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "SimHei")
MONO_CANDIDATES = ("Cascadia Mono", "Consolas", "Microsoft YaHei UI", "Courier New")

BASE_SIZE = 10
LOG_SIZE = 9


def pick_font(root: tk.Misc, candidates: tuple[str, ...]) -> str:
    """挑一个系统里真实存在的字体。"""
    try:
        available = {name.lower() for name in tkfont.families(root)}
    except Exception:
        return candidates[-1]
    for name in candidates:
        if name.lower() in available:
            return name
    return candidates[-1]


class Theme:
    """把字体和颜色打包，界面各部件共用一份。"""

    def __init__(self, root: tk.Misc) -> None:
        self.colors = dict(COLORS)
        family = pick_font(root, FONT_CANDIDATES)
        mono = pick_font(root, MONO_CANDIDATES)

        self.body = (family, BASE_SIZE)
        self.body_bold = (family, BASE_SIZE, "bold")
        self.title = (family, BASE_SIZE + 6, "bold")
        self.subtitle = (family, BASE_SIZE - 1)
        self.label = (family, BASE_SIZE)
        self.log = (mono, LOG_SIZE)
        self.big = (family, BASE_SIZE + 2, "bold")
        self.status = (family, BASE_SIZE + 1, "bold")

    def color(self, key: str) -> str:
        return self.colors[key]


def apply_theme(root: tk.Misc, theme: Theme) -> ttk.Style:
    """把配色应用到 ttk 控件上。"""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    color = theme.color
    style.configure(".", background=color("bg"), foreground=color("text"), font=theme.body)

    style.configure("TFrame", background=color("bg"))
    style.configure("Card.TFrame", background=color("panel"))
    style.configure("TLabel", background=color("bg"), foreground=color("text"), font=theme.body)
    style.configure("Card.TLabel", background=color("panel"), foreground=color("text"))
    style.configure("Muted.TLabel", background=color("bg"), foreground=color("muted"), font=theme.subtitle)
    style.configure("CardMuted.TLabel", background=color("panel"), foreground=color("muted"), font=theme.subtitle)
    style.configure("Title.TLabel", background=color("bg"), foreground=color("text"), font=theme.title)
    style.configure("Status.TLabel", background=color("bg"), foreground=color("text"), font=theme.status)

    # LabelFrame 卡片
    style.configure(
        "Card.TLabelframe",
        background=color("panel"),
        bordercolor=color("border"),
        relief="solid",
        borderwidth=1,
    )
    style.configure(
        "Card.TLabelframe.Label",
        background=color("bg"),
        foreground=color("accent_dark"),
        font=theme.body_bold,
    )

    # 按钮
    style.configure(
        "TButton",
        background=color("panel"),
        foreground=color("text"),
        bordercolor=color("border"),
        focuscolor=color("accent"),
        padding=(10, 5),
        relief="flat",
    )
    style.map("TButton", background=[("active", color("accent_soft")), ("disabled", color("bg"))])

    style.configure(
        "Accent.TButton",
        background=color("accent"),
        foreground="#FFFFFF",
        bordercolor=color("accent_dark"),
        padding=(12, 5),
        font=theme.body_bold,
    )
    style.map(
        "Accent.TButton",
        background=[("active", color("accent_dark")), ("disabled", color("track_off"))],
    )

    # 复选框：只换背景色，指示器交给 clam 自带的样式（自带对勾最清楚）
    style.configure(
        "TCheckbutton",
        background=color("panel"),
        foreground=color("text"),
        focuscolor=color("panel"),
    )
    style.map(
        "TCheckbutton",
        background=[("active", color("panel"))],
        foreground=[("disabled", color("muted"))],
    )

    # 下拉框
    style.configure(
        "TCombobox",
        fieldbackground=color("panel"),
        background=color("panel"),
        bordercolor=color("border"),
        arrowcolor=color("accent_dark"),
        padding=3,
    )
    style.map("TCombobox", fieldbackground=[("readonly", color("panel"))])

    # 滑块
    style.configure(
        "Cat.Horizontal.TScale",
        background=color("panel"),
        troughcolor=color("accent_soft"),
        bordercolor=color("panel"),
        lightcolor=color("accent"),
        darkcolor=color("accent"),
    )

    # 输入框
    style.configure(
        "TEntry",
        fieldbackground=color("panel"),
        bordercolor=color("border"),
        lightcolor=color("border"),
        darkcolor=color("border"),
        padding=4,
    )

    # 分隔线
    style.configure("TSeparator", background=color("border"))

    return style
