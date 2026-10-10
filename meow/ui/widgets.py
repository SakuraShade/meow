"""自定义控件：开关拨杆 + 日志面板。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from .theme import Theme

# ---------------- 颜色小工具 ----------------


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def blend(start: str, end: str, ratio: float) -> str:
    """在两个颜色之间线性插值，``ratio=0`` 返回 ``start``。"""
    a = _hex_to_rgb(start)
    b = _hex_to_rgb(end)
    return _rgb_to_hex(tuple(x + (y - x) * ratio for x, y in zip(a, b)))


def lighten(color: str, ratio: float = 0.5) -> str:
    return blend(color, "#FFFFFF", ratio)


# ---------------- 开关拨杆 ----------------


class ToggleSwitch(tk.Canvas):
    """会滑动的小开关。

    ``set_state`` 只负责显示（不会回调），``command`` 只在用户点击时触发，
    这样「程序改状态」和「用户改状态」不会互相打架。
    """

    WIDTH = 96
    HEIGHT = 46
    PAD = 5
    ANIMATION_STEPS = 9
    FRAME_MS = 16

    def __init__(
        self,
        master: tk.Misc,
        theme: Theme,
        command: Callable[[bool], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(
            master,
            width=self.WIDTH,
            height=self.HEIGHT,
            highlightthickness=0,
            bd=0,
            bg=theme.color("bg"),
            cursor="hand2",
            **kwargs,
        )
        self._theme = theme
        self._command = command
        self._state = False
        self._progress = 0.0  # 0 = 关，1 = 开
        self._animation_job: str | None = None

        self.bind("<Button-1>", self._on_click)
        self._draw()

    # ---------------- 对外 ----------------

    @property
    def state(self) -> bool:
        return self._state

    def set_state(self, value: bool, *, animate: bool = True) -> None:
        value = bool(value)
        if value == self._state and abs(self._progress - float(value)) < 0.01:
            return
        self._state = value
        target = 1.0 if value else 0.0
        if animate:
            self._animate_to(target)
        else:
            self._cancel_animation()
            self._progress = target
            self._draw()

    # ---------------- 交互 ----------------

    def _on_click(self, _event: tk.Event) -> None:
        self._state = not self._state
        self.set_state(self._state)
        if self._command is not None:
            self._command(self._state)

    # ---------------- 动画 ----------------

    def _cancel_animation(self) -> None:
        if self._animation_job is not None:
            try:
                self.after_cancel(self._animation_job)
            except Exception:
                pass
            self._animation_job = None

    def _animate_to(self, target: float) -> None:
        self._cancel_animation()
        start = self._progress
        distance = target - start

        def step(index: int) -> None:
            ratio = index / self.ANIMATION_STEPS
            eased = 1 - (1 - ratio) ** 3  # ease-out
            self._progress = start + distance * eased
            self._draw()
            if index < self.ANIMATION_STEPS:
                self._animation_job = self.after(self.FRAME_MS, lambda: step(index + 1))
            else:
                self._progress = target
                self._animation_job = None
                self._draw()

        step(1)

    # ---------------- 绘制 ----------------

    def _draw(self) -> None:
        self.delete("all")
        width, height = self.WIDTH, self.HEIGHT
        radius = height / 2
        ratio = self._progress

        track = blend(self._theme.color("track_off"), self._theme.color("accent"), ratio)
        self._pill(0, 0, width, height, radius, track)

        knob_radius = radius - self.PAD
        travel = width - 2 * (radius)
        center_x = radius + travel * ratio
        center_y = height / 2

        self.create_oval(
            center_x - knob_radius,
            center_y - knob_radius,
            center_x + knob_radius,
            center_y + knob_radius,
            fill="#FFFFFF",
            outline=blend(track, "#000000", 0.08),
            width=1,
        )

        # 旋钮反侧的「开 / 关」小字
        label = "开" if ratio > 0.5 else "关"
        label_x = (width - radius) if ratio > 0.5 else radius
        self.create_text(
            label_x,
            center_y,
            text=label,
            fill="#FFFFFF",
            font=self._theme.body_bold,
        )

    def _pill(self, x0: float, y0: float, x1: float, y1: float, radius: float, color: str) -> None:
        self.create_oval(x0, y0, x0 + 2 * radius, y1, fill=color, outline="")
        self.create_oval(x1 - 2 * radius, y0, x1, y1, fill=color, outline="")
        self.create_rectangle(x0 + radius, y0, x1 - radius, y1, fill=color, outline="")


# ---------------- 日志面板 ----------------


class LogView(ttk.Frame):
    """带等级配色、自动滚动的日志面板。

    只保留最近 ``max_lines`` 行，避免长时间运行把内存吃满。
    """

    LEVEL_TAGS = {
        10: ("debug", "debug"),
        20: ("info", "text"),
        30: ("warning", "warn"),
        40: ("error", "err"),
        50: ("critical", "err"),
    }

    def __init__(self, master: tk.Misc, theme: Theme, max_lines: int = 2000,
                 height: int = 8, **kwargs) -> None:
        super().__init__(master, style="Card.TFrame", **kwargs)
        self._theme = theme
        self._max_lines = max_lines
        self._autoscroll = tk.BooleanVar(value=True)

        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.text = tk.Text(
            self,
            wrap="word",
            height=height,
            relief="flat",
            bd=0,
            padx=10,
            pady=8,
            background=theme.color("panel"),
            foreground=theme.color("text"),
            font=theme.log,
            insertbackground=theme.color("text"),
            state="disabled",
        )
        self.text.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=scrollbar.set)

        for level, (tag, color_key) in self.LEVEL_TAGS.items():
            self.text.tag_configure(tag, foreground=theme.color(color_key))
        self.text.tag_configure("debug", foreground=theme.color("debug"))

        footer = ttk.Frame(self, style="Card.TFrame")
        footer.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 8))
        # 和参数区一样用经典复选框：clam 主题的「选中」是个叉号，容易看错
        tk.Checkbutton(
            footer,
            text="自动滚动",
            variable=self._autoscroll,
            background=theme.color("panel"),
            foreground=theme.color("text"),
            activebackground=theme.color("panel"),
            activeforeground=theme.color("text"),
            selectcolor=theme.color("panel"),
            font=theme.label,
            highlightthickness=0,
            bd=0,
            anchor="w",
            cursor="hand2",
        ).pack(side="left")

    # ---------------- 对外 ----------------

    def append(self, message: str, level: int = 20) -> None:
        tag = self.LEVEL_TAGS.get(level, ("info", "text"))[0]
        self.text.configure(state="normal")
        self.text.insert("end", message + "\n", tag)
        self._trim()
        self.text.configure(state="disabled")
        if self._autoscroll.get():
            self.text.see("end")

    def clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def line_count(self) -> int:
        return int(self.text.index("end-1c").split(".")[0])

    # ---------------- 内部 ----------------

    def _trim(self) -> None:
        excess = self.line_count() - self._max_lines
        if excess > 0:
            self.text.delete("1.0", f"{excess + 1}.0")
