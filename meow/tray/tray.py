"""通知区域（托盘）图标。

工作原理：在**独立线程**里注册一个窗口类、创建一个永不显示的窗口，
然后用 ``Shell_NotifyIconW`` 把图标挂到通知区域。鼠标事件通过窗口消息
回到我们这里，右键弹出原生菜单。

几个容易踩的坑，这里都处理了：

* 窗口必须在创建它的线程里收发消息，所以所有 ``Shell_NotifyIcon`` 调用
  都通过 ``PostMessage`` 回到托盘线程执行，而不是从 UI 线程直接调；
* ``TrackPopupMenu`` 之前必须先 ``SetForegroundWindow``，否则点菜单外面
  菜单不会消失；
* ``WNDPROC`` 回调对象必须保持引用，否则会被 GC 掉导致进程崩溃。
"""

from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from . import win32

LOGGER = logging.getLogger(__name__)

WM_TRAY_REFRESH = win32.WM_APP + 2
WM_TRAY_NOTIFY = win32.WM_APP + 3
WM_TRAY_STOP = win32.WM_APP + 4

WINDOW_CLASS_NAME = "MeowTrayWindow"
WINDOW_TITLE = "meow tray"
TRAY_ICON_ID = 1

START_TIMEOUT = 5.0
STOP_TIMEOUT = 2.0


@dataclass(frozen=True)
class MenuItem:
    """托盘右键菜单的一项。``separator=True`` 时其它字段被忽略。"""

    id: int = 0
    label: str = ""
    checked: bool = False
    enabled: bool = True
    separator: bool = False


SEPARATOR = MenuItem(separator=True)


class TrayIcon:
    """一个通知区域图标。非 Windows 或初始化失败时 :meth:`start` 返回 ``False``。"""

    def __init__(
        self,
        icon_path: Path | str,
        *,
        tooltip: str = "meow",
        on_command: Callable[[int], None] | None = None,
        on_activate: Callable[[], None] | None = None,
        menu_provider: Callable[[], Sequence[MenuItem]] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._icon_path = Path(icon_path)
        self._tooltip = tooltip
        self._on_command = on_command
        self._on_activate = on_activate
        self._menu_provider = menu_provider
        self._log = logger or LOGGER

        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._started = False
        self._failed_reason = ""

        self._hwnd = 0
        self._hinstance = 0
        self._hicon = 0
        self._loaded_icon_path: Path | None = None
        self._state_lock = threading.RLock()

        self._pending_notification: tuple[str, str, int] | None = None
        # 必须留引用，否则 ctypes 回调会被垃圾回收
        self._wndproc = win32.WNDPROC(self._handle_message)

    # ---------------- 对外 API ----------------

    @property
    def started(self) -> bool:
        return self._started

    @property
    def failure_reason(self) -> str:
        return self._failed_reason

    def start(self, timeout: float = START_TIMEOUT) -> bool:
        """启动托盘线程并等待图标挂载完成。"""
        if self._started:
            return True
        if self._thread is not None and self._thread.is_alive():
            return self._ready.wait(timeout) and self._started

        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="meow-tray", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            self._failed_reason = "托盘初始化超时"
            self._log.error("%s", self._failed_reason)
            return False
        return self._started

    def stop(self, timeout: float = STOP_TIMEOUT) -> None:
        """从通知区域移除图标并结束托盘线程。"""
        if self._thread is None:
            return
        if self._hwnd:
            win32.user32.PostMessageW(self._hwnd, WM_TRAY_STOP, 0, 0)
        self._thread.join(timeout)
        if self._thread.is_alive():
            # 用户可能正开着右键菜单（TrackPopupMenu 是阻塞的），不强杀线程
            self._log.warning("托盘线程未能在 %.1fs 内退出（右键菜单可能还开着）", timeout)
        self._thread = None
        self._started = False

    def set_icon(self, icon_path: Path | str) -> None:
        with self._state_lock:
            self._icon_path = Path(icon_path)
        self._post(WM_TRAY_REFRESH)

    def set_tooltip(self, text: str) -> None:
        with self._state_lock:
            self._tooltip = text[: win32.TIP_MAX]
        self._post(WM_TRAY_REFRESH)

    def notify(self, title: str, message: str, level: str = "info") -> None:
        """弹出气泡提示（系统「专注助手」可能会把它收进通知中心）。"""
        flags = {
            "info": win32.NIIF_INFO,
            "warning": win32.NIIF_WARNING,
            "error": win32.NIIF_ERROR,
        }.get(level, win32.NIIF_INFO)
        with self._state_lock:
            self._pending_notification = (title, message, flags)
        self._post(WM_TRAY_NOTIFY)

    # ---------------- 内部：跨线程投递 ----------------

    def _post(self, message: int) -> None:
        if self._hwnd:
            win32.user32.PostMessageW(self._hwnd, message, 0, 0)

    # ---------------- 托盘线程 ----------------

    def _run(self) -> None:
        try:
            self._create_window()
            if not self._add_icon():
                self._failed_reason = "Shell_NotifyIcon 挂载图标失败"
                self._log.error("%s", self._failed_reason)
                return
            self._started = True
            self._log.info("托盘图标已就绪")
            self._ready.set()
            self._message_loop()
        except Exception as exc:
            self._failed_reason = f"托盘初始化异常：{exc}"
            self._log.exception("托盘线程异常退出")
        finally:
            self._ready.set()
            self._cleanup()

    def _create_window(self) -> None:
        instance = win32.kernel32.GetModuleHandleW(None)
        self._hinstance = instance

        window_class = win32.WNDCLASSEXW()
        window_class.cbSize = ctypes.sizeof(win32.WNDCLASSEXW)
        window_class.lpfnWndProc = self._wndproc
        window_class.hInstance = instance
        window_class.lpszClassName = WINDOW_CLASS_NAME

        atom = win32.user32.RegisterClassExW(ctypes.byref(window_class))
        if not atom:
            error = ctypes.get_last_error()
            # 1410 = 类已注册（同一进程重复注册），可以继续用
            if error != 1410:
                raise ctypes.WinError(error)

        style = win32.WS_OVERLAPPED  # 不带 WS_VISIBLE，窗口永远不显示
        self._hwnd = win32.user32.CreateWindowExW(
            0, WINDOW_CLASS_NAME, WINDOW_TITLE, style,
            0, 0, 0, 0,
            None, None, instance, None,
        )
        if not self._hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self._log.debug("托盘窗口已创建：hwnd=%s", self._hwnd)

    def _load_icon(self) -> int:
        with self._state_lock:
            path = self._icon_path
        if self._hicon and self._loaded_icon_path == path:
            return self._hicon
        handle = win32.load_icon(path)
        if not handle:
            self._log.error("加载图标失败：%s", path)
            return self._hicon
        previous = self._hicon
        self._hicon = handle
        self._loaded_icon_path = path
        if previous:
            win32.destroy_icon(previous)
        return handle

    def _add_icon(self) -> bool:
        data = win32.notify_icon_data(self._hwnd, TRAY_ICON_ID, win32.WM_TRAYICON)
        data.uFlags = win32.NIF_MESSAGE | win32.NIF_ICON | win32.NIF_TIP
        data.hIcon = self._load_icon()
        data.szTip = self._tooltip[: win32.TIP_MAX]
        if not data.hIcon:
            return False
        return bool(win32.shell32.Shell_NotifyIconW(win32.NIM_ADD, ctypes.byref(data)))

    def _refresh_icon(self) -> None:
        data = win32.notify_icon_data(self._hwnd, TRAY_ICON_ID, win32.WM_TRAYICON)
        data.uFlags = win32.NIF_ICON | win32.NIF_TIP
        data.hIcon = self._load_icon()
        data.szTip = self._tooltip[: win32.TIP_MAX]
        win32.shell32.Shell_NotifyIconW(win32.NIM_MODIFY, ctypes.byref(data))

    def _show_notification(self) -> None:
        with self._state_lock:
            pending = self._pending_notification
            self._pending_notification = None
        if pending is None:
            return
        title, message, flags = pending
        data = win32.notify_icon_data(self._hwnd, TRAY_ICON_ID, win32.WM_TRAYICON)
        data.uFlags = win32.NIF_INFO
        data.szInfoTitle = title[: win32.INFO_TITLE_MAX]
        data.szInfo = message[: win32.INFO_MAX]
        data.dwInfoFlags = flags
        win32.shell32.Shell_NotifyIconW(win32.NIM_MODIFY, ctypes.byref(data))

    def _message_loop(self) -> None:
        message = wintypes.MSG()
        while True:
            result = win32.user32.GetMessageW(ctypes.byref(message), None, 0, 0)
            if result in (0, -1):  # 0 = WM_QUIT，-1 = 出错
                break
            win32.user32.TranslateMessage(ctypes.byref(message))
            win32.user32.DispatchMessageW(ctypes.byref(message))

    def _cleanup(self) -> None:
        if self._hwnd:
            data = win32.notify_icon_data(self._hwnd, TRAY_ICON_ID, win32.WM_TRAYICON)
            win32.shell32.Shell_NotifyIconW(win32.NIM_DELETE, ctypes.byref(data))
        if self._hicon:
            win32.destroy_icon(self._hicon)
            self._hicon = 0
        if self._hwnd:
            win32.user32.DestroyWindow(self._hwnd)
            self._hwnd = 0
        self._started = False
        self._log.debug("托盘已清理")

    # ---------------- 窗口过程 ----------------

    def _handle_message(self, hwnd, message, wparam, lparam) -> int:
        try:
            if message == win32.WM_TRAYICON:
                return self._handle_tray_event(lparam)
            if message == WM_TRAY_REFRESH:
                self._refresh_icon()
                return 0
            if message == WM_TRAY_NOTIFY:
                self._show_notification()
                return 0
            if message == WM_TRAY_STOP:
                self._cleanup()
                win32.user32.PostQuitMessage(0)
                return 0
            if message == win32.WM_DESTROY:
                win32.user32.PostQuitMessage(0)
                return 0
        except Exception:
            self._log.exception("处理托盘消息 0x%04X 时出错", message)
        return win32.user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _handle_tray_event(self, event: int) -> int:
        if event in (win32.WM_RBUTTONUP, win32.WM_CONTEXTMENU):
            self._show_menu()
        elif event in (win32.WM_LBUTTONDBLCLK, win32.WM_LBUTTONUP):
            if self._on_activate is not None:
                try:
                    self._on_activate()
                except Exception:
                    self._log.exception("托盘激活回调出错")
        return 0

    def _show_menu(self) -> None:
        items: Sequence[MenuItem] = ()
        if self._menu_provider is not None:
            try:
                items = self._menu_provider() or ()
            except Exception:
                self._log.exception("生成托盘菜单出错")

        menu = win32.user32.CreatePopupMenu()
        if not menu:
            return
        command = 0
        try:
            for item in items:
                if item.separator:
                    win32.user32.AppendMenuW(menu, win32.MF_SEPARATOR, 0, None)
                    continue
                flags = win32.MF_STRING
                flags |= win32.MF_CHECKED if item.checked else win32.MF_UNCHECKED
                if not item.enabled:
                    flags |= win32.MF_GRAYED | win32.MF_DISABLED
                win32.user32.AppendMenuW(menu, flags, item.id, item.label)

            point = wintypes.POINT()
            win32.user32.GetCursorPos(ctypes.byref(point))
            # 先抢前台，否则菜单在点击别处时不会关闭
            win32.user32.SetForegroundWindow(self._hwnd)
            command = win32.user32.TrackPopupMenu(
                menu,
                win32.TPM_RIGHTBUTTON | win32.TPM_RETURNCMD | win32.TPM_NONOTIFY,
                point.x, point.y, 0, self._hwnd, None,
            )
            win32.user32.PostMessageW(self._hwnd, win32.WM_NULL, 0, 0)
        finally:
            win32.user32.DestroyMenu(menu)

        if command and self._on_command is not None:
            try:
                self._on_command(int(command))
            except Exception:
                self._log.exception("托盘菜单回调出错")
