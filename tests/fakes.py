# -*- coding: utf-8 -*-
"""测试用的假实现与测试辅助。"""

from __future__ import annotations

import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# 临时目录放在项目内，不用系统 temp：
# 受限环境（比如 DSH 沙箱）只允许写工作区，写系统 temp 会被直接拒绝。
TEMP_ROOT = Path(__file__).resolve().parent / "_tmp"


@contextmanager
def workspace_temp_dir():
    """在 ``tests/_tmp`` 下开一个临时目录，退出时删除。

    这里刻意不用 ``tempfile.mkdtemp``：它会用 ``os.mkdir(path, 0o700)``
    建目录，在 Windows 上等于写了一个「禁用继承」的安全描述符，
    沙箱给工作区下的写权限就传不进去，后续写文件会 Access Denied。
    用普通 ``makedirs`` 建目录才会正常继承权限。
    """
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = TEMP_ROOT / f"case-{uuid.uuid4().hex[:12]}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class FakeBackend:
    """可编程的假输入后端。"""

    def __init__(
        self,
        name: str,
        text: str | None = None,
        can_write: bool = True,
        read_error: Exception | None = None,
        write_error: Exception | None = None,
    ) -> None:
        self.name = name
        self._text = text
        self._can_write = can_write
        self._read_error = read_error
        self._write_error = write_error
        self.written: list[str] = []
        self.read_calls = 0

    def read(self) -> str | None:
        self.read_calls += 1
        if self._read_error:
            raise self._read_error
        return self._text

    def write(self, text: str) -> bool:
        if self._write_error:
            raise self._write_error
        if not self._can_write:
            return False
        self.written.append(text)
        self._text = text
        return True


class SessionBackend(FakeBackend):
    """带 ``session()`` 的后端，用来验证网关会正确进入/退出会话。"""

    def __init__(self, name: str, **kwargs: Any) -> None:
        super().__init__(name, **kwargs)
        self.entered = 0
        self.exited = 0

    @contextmanager
    def session(self):
        self.entered += 1
        try:
            yield self
        finally:
            self.exited += 1


class FakeClipboard:
    """假剪贴板。"""

    def __init__(self, content: str = "") -> None:
        self.content = content
        self.history: list[str] = []

    def copy(self, text: str) -> None:
        self.content = text
        self.history.append(text)

    def paste(self) -> str:
        return self.content


class FakeKeyboard:
    """假键盘：``ctrl+c`` 时把预设文本写进剪贴板，模拟应用响应复制。"""

    def __init__(self, clipboard: FakeClipboard, copied: str = "", echo: bool = True) -> None:
        self._clipboard = clipboard
        self._copied = copied
        self._echo = echo
        self.sent: list[str] = []

    def send(self, keys: str) -> None:
        self.sent.append(keys)
        if self._echo and keys == "ctrl+c":
            self._clipboard.content = self._copied


class FakeListener:
    """假 ``keyboard`` 模块：记录装了哪些钩子，并允许手工触发事件。"""

    def __init__(self) -> None:
        self.hooks: dict[str, Any] = {}
        self.hotkeys: dict[str, Any] = {}
        self.sent: list[str] = []
        self.unhooked: list[Any] = []
        self.removed_hotkeys: list[Any] = []

    def hook_key(self, key: str, callback, suppress: bool = False):
        handler = {"key": key, "callback": callback, "suppress": suppress}
        self.hooks[key] = handler
        return handler

    def add_hotkey(self, hotkey: str, callback, **kwargs):
        handler = {"hotkey": hotkey, "callback": callback}
        self.hotkeys[hotkey] = handler
        return handler

    def unhook(self, handler) -> None:
        self.unhooked.append(handler)

    def remove_hotkey(self, handler) -> None:
        self.removed_hotkeys.append(handler)

    def send(self, keys: str) -> None:
        self.sent.append(keys)

    # ---- 测试辅助 ----

    def fire_enter(self, event_type: str = "down") -> bool:
        callback = self.hooks["enter"]["callback"]

        class Event:
            pass

        event = Event()
        event.event_type = event_type
        return callback(event)


class SynchronousThread:
    """把 ``threading.Thread`` 换成立即执行的假线程。

    钩子的处理逻辑跑在子线程里，单元测试里同步执行更好断言。
    """

    def __init__(self, target=None, daemon=None, name=None, args=(), kwargs=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}
        self.daemon = daemon
        self.name = name
        self.started = False

    def start(self) -> None:
        self.started = True
        if self._target:
            self._target(*self._args, **self._kwargs)

    def join(self, timeout=None) -> None:
        return None

    def is_alive(self) -> bool:
        return False
