"""主窗口。

线程模型：Tk 只能在主线程里操作，所以后台线程（键盘钩子、托盘）产生的
一切事件都先塞进 ``ui_queue``，再由 :meth:`MeowWindow._poll_queue` 定时取出
并在主线程里更新界面。
"""

from __future__ import annotations

import logging
import os
import queue
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any, Callable

from .. import __version__
from ..config import AppSettings
from ..engine.params import (
    KAOMOJI_INTERVAL_RANGE,
    KAOMOJI_PROB_RANGE,
    KAOMOJI_STD_RANGE,
    STRENGTH_LABELS,
)
from ..logging_setup import format_record
from ..paths import AppPaths
from ..service import MeowService
from ..tray import SEPARATOR, MenuItem, TrayIcon, ensure_icons
from .theme import COLORS, Theme, apply_theme
from .widgets import LogView, ToggleSwitch

# 托盘菜单命令 ID
MENU_TOGGLE = 1
MENU_SHOW = 2
MENU_OPEN_LOG = 3
MENU_OPEN_CONFIG = 4
MENU_QUIT = 9

POLL_INTERVAL_MS = 100
DRAIN_LIMIT = 200
PERSIST_DELAY_MS = 600

# 强度在界面里的展示顺序：标准排最前
STRENGTH_ORDER = (2, 1, 0)


class MeowWindow:
    """meow 的主界面。"""

    def __init__(
        self,
        service: MeowService,
        paths: AppPaths,
        ui_queue: "queue.Queue[tuple[str, Any]]",
        *,
        enable_tray: bool = True,
        logger: logging.Logger | None = None,
    ) -> None:
        self._service = service
        self._paths = paths
        self._queue = ui_queue
        self._log = logger or logging.getLogger("meow.ui")
        self._enable_tray = enable_tray

        self._tray: TrayIcon | None = None
        self._icons: dict[str, Path] = {}
        self._persist_job: str | None = None
        self._syncing = False
        self._quitting = False

        self.root = tk.Tk()
        self.root.title(f"meow · 猫娘输入法  v{__version__}")
        self.root.minsize(900, 560)
        self.root.geometry(self._preferred_geometry())
        self.root.configure(bg=COLORS["bg"])

        self.theme = Theme(self.root)
        apply_theme(self.root, self.theme)

        self._build_ui()
        self._bind_shortcuts()
        self._apply_settings(self._service.settings, initial=True)
        self._setup_icons()
        self._setup_tray()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close_request)
        self.root.after(POLL_INTERVAL_MS, self._poll_queue)

    # ================= 构建界面 =================

    def _preferred_geometry(self) -> str:
        """按屏幕大小挑一个不会超出桌面的初始尺寸（小屏笔记本也能用）。"""
        try:
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()
        except Exception:
            return "1120x740"
        width = max(900, min(1160, screen_width - 80))
        height = max(560, min(760, screen_height - 120))
        return f"{width}x{height}"

    def _build_ui(self) -> None:
        # 左边一列放参数（宽度固定），右边一列放试转换和日志（吃掉多余空间）
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(1, weight=1)

        self._build_header()

        left = ttk.Frame(self.root)
        left.grid(row=1, column=0, sticky="new")
        self._build_parameters(left)

        right = ttk.Frame(self.root)
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        self._build_tryout(right)
        self._build_log(right)

        self._build_statusbar()

    # ---------------- 顶部：开关 ----------------

    def _build_header(self) -> None:
        header = ttk.Frame(self.root)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(14, 6))
        header.columnconfigure(1, weight=1)

        self.switch = ToggleSwitch(header, self.theme, command=self._on_switch_clicked)
        self.switch.grid(row=0, column=0, rowspan=2, padx=(0, 16))

        self.state_label = ttk.Label(header, text="已关闭", style="Title.TLabel")
        self.state_label.grid(row=0, column=1, sticky="w")

        self.hint_label = ttk.Label(header, text="", style="Muted.TLabel")
        self.hint_label.grid(row=1, column=1, sticky="w", pady=(2, 0))

        actions = ttk.Frame(header)
        actions.grid(row=0, column=2, rowspan=2, sticky="e")
        ttk.Button(actions, text="隐藏到托盘", command=self.hide_to_tray).pack(side="left", padx=4)
        self.exit_button = ttk.Button(actions, text="退出", command=self.quit)
        # 托盘不可用时才显示「退出」按钮：正常情况下退出入口只在托盘右键菜单里

    # ---------------- 参数 ----------------

    def _build_parameters(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text=" 猫化参数 ", style="Card.TLabelframe", padding=(14, 10))
        card.grid(row=0, column=0, sticky="new", padx=(16, 8), pady=(0, 10))
        card.columnconfigure(1, weight=1)

        self._sliders: dict[str, tuple[tk.DoubleVar, tk.StringVar, Callable[[float], None]]] = {}
        self._checks: dict[str, tk.BooleanVar] = {}

        row = 0
        ttk.Label(card, text="语气强度", style="Card.TLabel").grid(
            row=row, column=0, sticky="w", padx=(2, 12), pady=6
        )
        self._strength_var = tk.StringVar()
        self._strength_combo = ttk.Combobox(
            card,
            textvariable=self._strength_var,
            state="readonly",
            values=[STRENGTH_LABELS[s] for s in STRENGTH_ORDER],
            width=26,
        )
        self._strength_combo.grid(row=row, column=1, sticky="w", pady=6)
        self._strength_combo.bind("<<ComboboxSelected>>", self._on_strength_selected)
        row += 1

        row = self._add_slider(
            card, row, "kaomoji_prob", "颜文字概率（单句）",
            KAOMOJI_PROB_RANGE, 0.05,
            lambda value: f"{value:.0%}",
        )
        row = self._add_slider(
            card, row, "kaomoji_interval", "颜文字平均间隔（句）",
            KAOMOJI_INTERVAL_RANGE, 0.5,
            lambda value: f"{value:.1f}",
        )
        row = self._add_slider(
            card, row, "kaomoji_std", "间隔波动（越大越随性）",
            KAOMOJI_STD_RANGE, 0.1,
            lambda value: f"{value:.1f}",
        )

        checks = ttk.Frame(card, style="Card.TFrame")
        checks.grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 2))
        self._add_check(checks, "add_tilde", "句末加「~」")
        self._add_check(checks, "split_on_space", "空格也算分句（英文句子建议关掉）")
        self._add_check(checks, "only_subject_object", "只替换主语/宾语位置的代词")
        self._add_check(checks, "auto_send", "改写后自动发送回车")
        row += 1

        hotkey_row = ttk.Frame(card, style="Card.TFrame")
        hotkey_row.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Label(hotkey_row, text="全局开关快捷键", style="Card.TLabel").pack(side="left", padx=(2, 12))
        self._hotkey_var = tk.StringVar()
        ttk.Entry(hotkey_row, textvariable=self._hotkey_var, width=14).pack(side="left")
        ttk.Button(hotkey_row, text="应用", command=self._on_hotkey_apply).pack(side="left", padx=8)
        row += 1

        # 提示单独占一行，避免把整个左栏撑得过宽
        ttk.Label(
            card,
            text="例如 alt+b、ctrl+shift+m；改完需要重启程序才会生效",
            style="CardMuted.TLabel",
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=2, pady=(4, 0))
        row += 1

        buttons = ttk.Frame(card, style="Card.TFrame")
        buttons.grid(row=row, column=0, columnspan=2, sticky="w", pady=(12, 2))
        ttk.Button(buttons, text="恢复默认参数", command=self._on_reset).pack(side="left", padx=(2, 6))
        ttk.Button(buttons, text="打开配置文件", command=lambda: self._open_path(self._paths.config_file)).pack(
            side="left", padx=6
        )
        ttk.Button(buttons, text="打开日志文件", command=lambda: self._open_path(self._paths.log_file)).pack(
            side="left", padx=6
        )

    def _add_slider(
        self,
        parent: ttk.Frame,
        row: int,
        key: str,
        label: str,
        value_range: tuple[float, float],
        step: float,
        formatter: Callable[[float], str],
    ) -> int:
        ttk.Label(parent, text=label, style="Card.TLabel").grid(
            row=row, column=0, sticky="w", padx=(2, 12), pady=4
        )
        value_var = tk.DoubleVar(value=value_range[0])
        display_var = tk.StringVar(value=formatter(value_range[0]))

        holder = ttk.Frame(parent, style="Card.TFrame")
        holder.grid(row=row, column=1, sticky="ew", pady=4)
        holder.columnconfigure(0, weight=1)

        def on_move(raw: str) -> None:
            value = self._round_to(float(raw), step)
            display_var.set(formatter(value))
            if self._syncing:
                return
            self._apply_param(key, value)

        scale = ttk.Scale(
            holder,
            from_=value_range[0],
            to=value_range[1],
            orient="horizontal",
            length=240,
            variable=value_var,
            style="Cat.Horizontal.TScale",
            command=on_move,
        )
        scale.grid(row=0, column=0, sticky="ew")
        ttk.Label(holder, textvariable=display_var, style="Card.TLabel", width=6, anchor="e").grid(
            row=0, column=1, padx=(8, 0)
        )

        self._sliders[key] = (value_var, display_var, lambda v, f=formatter: f(v))
        return row + 1

    def _add_check(self, parent: ttk.Frame, key: str, label: str) -> None:
        """加一个复选框。

        这里刻意用经典的 ``tk.Checkbutton`` 而不是 ``ttk.Checkbutton``：
        clam 主题把「选中」画成一个实心叉号（×），很容易被误读成「关闭」，
        而经典控件的指示器在 Windows 上是系统原生画法，是清楚的对勾。
        """
        var = tk.BooleanVar(value=False)
        self._checks[key] = var
        tk.Checkbutton(
            parent,
            text=label,
            variable=var,
            command=lambda k=key: self._on_check_toggled(k),
            background=self.theme.color("panel"),
            foreground=self.theme.color("text"),
            activebackground=self.theme.color("panel"),
            activeforeground=self.theme.color("text"),
            selectcolor=self.theme.color("panel"),
            disabledforeground=self.theme.color("muted"),
            font=self.theme.label,
            highlightthickness=0,
            bd=0,
            anchor="w",
            cursor="hand2",
        ).pack(anchor="w", pady=2)

    # ---------------- 试一下 ----------------

    def _build_tryout(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text=" 试一下 ", style="Card.TLabelframe", padding=(14, 10))
        card.grid(row=0, column=0, sticky="ew", padx=(8, 16), pady=(0, 8))
        card.columnconfigure(0, weight=1)

        entry_row = ttk.Frame(card, style="Card.TFrame")
        entry_row.grid(row=0, column=0, sticky="ew")
        entry_row.columnconfigure(0, weight=1)

        self._try_var = tk.StringVar()
        entry = ttk.Entry(entry_row, textvariable=self._try_var)
        entry.grid(row=0, column=0, sticky="ew")
        entry.bind("<Return>", lambda _event: self._on_try())
        ttk.Button(entry_row, text="转换", style="Accent.TButton", command=self._on_try).grid(
            row=0, column=1, padx=(8, 0)
        )

        self._try_result = tk.Text(
            card,
            height=2,
            wrap="word",
            relief="flat",
            bd=0,
            padx=8,
            pady=6,
            background=self.theme.color("accent_soft"),
            foreground=self.theme.color("text"),
            font=self.theme.body,
            state="disabled",
        )
        self._try_result.grid(row=1, column=0, sticky="ew", pady=(8, 0))

    # ---------------- 日志 ----------------

    def _build_log(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text=" 运行日志 ", style="Card.TLabelframe", padding=(10, 8))
        card.grid(row=1, column=0, sticky="nsew", padx=(8, 16), pady=(0, 10))
        card.columnconfigure(0, weight=1)
        card.rowconfigure(0, weight=1)

        self.log_view = LogView(card, self.theme, height=14)
        self.log_view.grid(row=0, column=0, sticky="nsew")

        buttons = ttk.Frame(card, style="Card.TFrame")
        buttons.grid(row=1, column=0, sticky="e", pady=(6, 0))
        ttk.Button(buttons, text="清空", command=self.log_view.clear).pack(side="left", padx=4)

    # ---------------- 状态栏 ----------------

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self.root)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 12))
        bar.columnconfigure(0, weight=1)

        self.stats_label = ttk.Label(bar, text="尚未处理任何输入", style="Muted.TLabel")
        self.stats_label.grid(row=0, column=0, sticky="w")

        self.tray_label = ttk.Label(bar, text="", style="Muted.TLabel")
        self.tray_label.grid(row=0, column=1, sticky="e")

    # ================= 图标与托盘 =================

    def _setup_icons(self) -> None:
        try:
            self._icons = ensure_icons(self._paths.icon_dir)
        except Exception:
            self._log.exception("生成图标失败，将使用系统默认图标")
            return
        try:
            self.root.iconbitmap(default=str(self._icons["off"]))
        except Exception as exc:
            self._log.debug("设置窗口图标失败（不影响使用）：%s", exc)

    def _setup_tray(self) -> None:
        if not self._enable_tray or not self._icons:
            self._after_tray_unavailable("未启用托盘")
            return
        try:
            self._tray = TrayIcon(
                self._icons["off"],
                tooltip=self._tray_tooltip(self._service.enabled),
                on_command=lambda command: self._queue.put(("tray_command", command)),
                on_activate=lambda: self._queue.put(("tray_activate", None)),
                menu_provider=self._tray_menu,
                logger=self._log,
            )
        except Exception:
            self._log.exception("创建托盘图标失败")
            self._after_tray_unavailable("托盘初始化失败")
            return

        if not self._tray.start():
            reason = self._tray.failure_reason or "未知原因"
            self._log.error("托盘启动失败：%s", reason)
            self._tray = None
            self._after_tray_unavailable(reason)
            return

        self.tray_label.configure(text="托盘图标：运行中")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close_request)

    def _after_tray_unavailable(self, reason: str) -> None:
        """托盘不可用时降级：显示退出按钮，关闭窗口即真正退出。"""
        self._tray = None
        self.tray_label.configure(text=f"托盘不可用（{reason}）")
        self.log_view.append(
            f"[提示] 托盘图标不可用（{reason}）。关闭窗口将直接退出程序。",
            logging.WARNING,
        )
        self.exit_button.pack(side="left", padx=4)

    def _tray_tooltip(self, enabled: bool) -> str:
        hotkey = self._service.settings.hotkey
        return f"meow · {'已开启' if enabled else '已关闭'}（{hotkey} 切换）"

    def _tray_menu(self) -> list[MenuItem]:
        enabled = self._service.enabled
        items = [
            MenuItem(MENU_TOGGLE, f"猫化：{'已开启 ✅' if enabled else '已关闭'}（点击切换）", checked=enabled),
            SEPARATOR,
            MenuItem(MENU_SHOW, "显示主界面"),
            MenuItem(MENU_OPEN_LOG, "打开日志文件"),
            MenuItem(MENU_OPEN_CONFIG, "打开配置文件"),
            SEPARATOR,
            MenuItem(MENU_QUIT, "退出 meow"),
        ]
        return items

    def _sync_tray(self) -> None:
        if self._tray is None or not self._icons:
            return
        self._tray.set_icon(self._icons["on" if self._service.enabled else "off"])
        self._tray.set_tooltip(self._tray_tooltip(self._service.enabled))

    # ================= 事件处理 =================

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-l>", lambda _event: self.log_view.clear())
        self.root.bind("<Escape>", lambda _event: self.hide_to_tray())

    def _poll_queue(self) -> None:
        if self._quitting:
            return
        for _ in range(DRAIN_LIMIT):
            try:
                kind, payload = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                self._handle_event(kind, payload)
            except Exception:
                self._log.exception("处理界面事件 %s 失败", kind)
        self.root.after(POLL_INTERVAL_MS, self._poll_queue)

    def _handle_event(self, kind: str, payload: Any) -> None:
        if kind == "log":
            self.log_view.append(format_record(payload), payload.levelno)
        elif kind == "state":
            self._apply_state(bool(payload))
        elif kind == "settings":
            self._apply_settings(payload, update_sliders=False)
        elif kind == "stats":
            self._apply_stats(payload)
        elif kind == "tray_command":
            self._handle_tray_command(int(payload))
        elif kind == "tray_activate":
            self.show_window()
        elif kind == "switch":
            self.switch.set_state(bool(payload))

    def _handle_tray_command(self, command: int) -> None:
        if command == MENU_TOGGLE:
            self._service.toggle()
        elif command == MENU_SHOW:
            self.show_window()
        elif command == MENU_OPEN_LOG:
            self._open_path(self._paths.log_file)
        elif command == MENU_OPEN_CONFIG:
            self._open_path(self._paths.config_file)
        elif command == MENU_QUIT:
            self.quit()

    # ---------------- 开关 ----------------

    def _on_switch_clicked(self, value: bool) -> None:
        self._service.set_enabled(value)

    def _apply_state(self, enabled: bool) -> None:
        self.switch.set_state(enabled)
        self.state_label.configure(text="已开启" if enabled else "已关闭")
        self.state_label.configure(foreground=self.theme.color("accent_dark" if enabled else "text"))
        hotkey = self._service.settings.hotkey
        self.hint_label.configure(
            text=(
                f"按 Enter 会把输入框内容猫化后自动发送 · {hotkey} 切换开关"
                if enabled
                else f"当前不处理回车，输入框内容保持原样 · {hotkey} 切换开关"
            )
        )
        self._sync_tray()

    # ---------------- 参数 ----------------

    def _apply_settings(
        self, settings: AppSettings, *, initial: bool = False, update_sliders: bool = True
    ) -> None:
        self._syncing = True
        try:
            params = settings.catify
            index = STRENGTH_ORDER.index(params.strength) if params.strength in STRENGTH_ORDER else 0
            self._strength_combo.current(index)

            if update_sliders:
                # 用户正在拖滑块时不要回写，否则滑块会跳
                for key, (value_var, display_var, formatter) in self._sliders.items():
                    value = float(getattr(params, key))
                    value_var.set(value)
                    display_var.set(formatter(value))

            self._checks["add_tilde"].set(params.add_tilde)
            self._checks["split_on_space"].set(params.split_on_space)
            self._checks["only_subject_object"].set(params.only_subject_object)
            self._checks["auto_send"].set(settings.auto_send)
            self._hotkey_var.set(settings.hotkey)
        finally:
            self._syncing = False

        if initial:
            self._apply_state(settings.enabled)
            self._apply_stats(self._service.stats.to_dict())

    def _apply_param(self, key: str, value: Any) -> None:
        self._service.update_catify(persist=False, **{key: value})
        self._schedule_persist()

    def _on_check_toggled(self, key: str) -> None:
        if self._syncing:
            return
        value = self._checks[key].get()
        if key == "auto_send":
            self._service.update_app(persist=False, auto_send=value)
        else:
            self._service.update_catify(persist=False, **{key: value})
        self._schedule_persist()

    def _on_strength_selected(self, _event: tk.Event) -> None:
        if self._syncing:
            return
        index = self._strength_combo.current()
        if index < 0:
            return
        self._service.update_catify(persist=False, strength=STRENGTH_ORDER[index])
        self._schedule_persist()

    def _on_hotkey_apply(self) -> None:
        hotkey = self._hotkey_var.get().strip().lower()
        if not hotkey:
            self._hotkey_var.set(self._service.settings.hotkey)
            return
        self._service.update_app(hotkey=hotkey)
        self._log.info("快捷键已改为 %s，重启程序后生效", hotkey)

    def _on_reset(self) -> None:
        params = self._service.reset_catify()
        self._apply_settings(self._service.settings)
        self._log.info("参数已恢复默认：强度=%s", STRENGTH_LABELS.get(params.strength, params.strength))

    def _schedule_persist(self) -> None:
        if self._persist_job is not None:
            try:
                self.root.after_cancel(self._persist_job)
            except Exception:
                pass
        self._persist_job = self.root.after(PERSIST_DELAY_MS, self._do_persist)

    def _do_persist(self) -> None:
        self._persist_job = None
        self._service.save()

    def _flush_persist(self) -> None:
        if self._persist_job is not None:
            try:
                self.root.after_cancel(self._persist_job)
            except Exception:
                pass
            self._persist_job = None
        self._service.save()

    # ---------------- 试一下 ----------------

    def _on_try(self) -> None:
        source = self._try_var.get()
        if not source.strip():
            self._set_try_result("先在上面输入一句话，再点「转换」")
            return
        try:
            result = self._service.preview(source)
        except Exception as exc:
            self._log.exception("转换失败")
            self._set_try_result(f"转换失败：{exc}")
            return
        self._set_try_result(result or "（改写结果为空）")
        self._log.info("试转换：%s → %s", source, result)

    def _set_try_result(self, text: str) -> None:
        self._try_result.configure(state="normal")
        self._try_result.delete("1.0", "end")
        self._try_result.insert("1.0", text)
        self._try_result.configure(state="disabled")

    # ---------------- 统计 ----------------

    def _apply_stats(self, stats: dict[str, Any]) -> None:
        rewrites = stats.get("rewrites", 0)
        passthrough = stats.get("passthrough", 0)
        failures = stats.get("failures", 0)
        text = f"已改写 {rewrites} 次 · 原样放行 {passthrough} 次"
        if failures:
            text += f" · 失败 {failures} 次"
        backend = stats.get("last_backend")
        if backend:
            text += f" · 最近写入方式：{backend}"
        self.stats_label.configure(text=text)

    # ================= 窗口行为 =================

    def hide_to_tray(self) -> None:
        """隐藏窗口（从任务栏消失），保留托盘图标。"""
        if self._tray is None:
            self._log.info("没有托盘图标，直接退出")
            self.quit()
            return
        self.root.withdraw()
        self._log.info("已最小化到托盘，双击托盘图标可以重新打开")
        if self._service.settings.show_tray_notifications:
            self._tray.notify("meow", "已最小化到托盘。右键托盘图标可以退出程序。")

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except Exception:
            pass
        self._log.debug("窗口已恢复")

    def _on_close_request(self) -> None:
        """点窗口右上角的 × —— 按配置收进托盘或退出。"""
        if self._tray is not None and self._service.settings.minimize_to_tray_on_close:
            self.hide_to_tray()
        else:
            self.quit()

    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self._log.info("正在退出……")
        self._flush_persist()
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:
                self._log.exception("停止托盘时出错")
            self._tray = None
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            pass

    # ================= 杂项 =================

    @staticmethod
    def _round_to(value: float, step: float) -> float:
        if step <= 0:
            return value
        return round(round(value / step) * step, 4)

    def _open_path(self, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        if not path.exists():
            self._log.warning("文件还不存在：%s", path)
            try:
                os.startfile(str(path.parent))  # noqa: S606 - Windows 专用
            except Exception as exc:
                self._log.error("打开目录失败：%s", exc)
            return
        try:
            os.startfile(str(path))  # noqa: S606 - Windows 专用
        except Exception as exc:
            self._log.error("打开 %s 失败：%s", path, exc)

    def run(self) -> None:
        self.root.mainloop()
