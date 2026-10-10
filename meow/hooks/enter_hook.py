"""Enter 拦截钩子。

职责很窄，只做四件事：

1. 装/卸 ``keyboard`` 的低层钩子（Enter + 全局开关快捷键）；
2. 过滤掉「我们自己补发的那次 Enter」，避免无限递归；
3. 把真正的 Enter 丢进工作线程处理 —— 钩子回调里绝对不能阻塞，
   否则整个系统的键盘都会卡住；
4. 提供 :meth:`send_enter` 给业务层补发 Enter。

业务逻辑（读文本 → 改写 → 写回 → 发送）通过 ``handler`` 注入，
所以这个类不需要知道 catify 的存在。
"""

from __future__ import annotations

import logging
import threading
from enum import Enum
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)


class EnterOutcome(Enum):
    """业务层处理一次 Enter 之后的结果。"""

    SENT = "sent"            # 我们已经补发过 Enter 了
    PASSTHROUGH = "pass"     # 原样放行：由钩子补发一次干净的 Enter
    SWALLOW = "swallow"      # 什么都不做（既不发送，也不放行）


# handler(send_enter) -> EnterOutcome
EnterHandler = Callable[[Callable[[], None]], EnterOutcome]


class EnterHook:
    """全局键盘钩子：拦截 Enter、注册快捷键。"""

    def __init__(
        self,
        handler: EnterHandler,
        *,
        gate: Callable[[], bool] | None = None,
        listener: Any | None = None,
        logger: logging.Logger | None = None,
        thread_factory: Callable[..., threading.Thread] = threading.Thread,
    ) -> None:
        self._handler = handler
        # gate 返回 False 时完全不碰这次按键（连吞都不吞）——比如功能关着的时候
        self._gate = gate or (lambda: True)
        self._listener = listener
        self._log = logger or LOGGER
        self._thread_factory = thread_factory

        self._enter_handle: Any | None = None
        self._hotkey_handle: Any | None = None
        # 我们自己补发的 Enter 会被钩子再次看到，用它打标记跳过
        self._injected = False
        # 上一次还没处理完就再来一次回车时，直接吞掉，避免并发打架
        self._busy = threading.Lock()
        self._running = False

    # ---------------- 依赖 ----------------

    @property
    def listener(self) -> Any:
        if self._listener is None:
            import keyboard

            self._listener = keyboard
        return self._listener

    @property
    def running(self) -> bool:
        return self._running

    # ---------------- 生命周期 ----------------

    def start(self, hotkey: str | None = None, on_hotkey: Callable[[], None] | None = None) -> None:
        """安装 Enter 钩子（可选安装开关快捷键）。"""
        if self._running:
            self._log.warning("钩子已经安装过了，先卸载再装")
            self.stop()

        self._enter_handle = self.listener.hook_key("enter", self._on_enter, suppress=True)
        self._running = True
        self._log.info("已拦截 Enter 键")

        if hotkey and on_hotkey is not None:
            try:
                self._hotkey_handle = self.listener.add_hotkey(hotkey, on_hotkey)
                self._log.info("已注册全局快捷键：%s", hotkey)
            except Exception as exc:
                self._log.error("注册快捷键 %s 失败：%s", hotkey, exc)

    def stop(self) -> None:
        """卸载所有钩子。重复调用安全。"""
        if not self._running and self._enter_handle is None and self._hotkey_handle is None:
            return
        try:
            if self._enter_handle is not None:
                self.listener.unhook(self._enter_handle)
        except Exception as exc:
            self._log.debug("卸载 Enter 钩子失败：%s", exc)
        try:
            if self._hotkey_handle is not None:
                self.listener.remove_hotkey(self._hotkey_handle)
        except Exception as exc:
            self._log.debug("卸载快捷键失败：%s", exc)
        self._enter_handle = None
        self._hotkey_handle = None
        self._running = False
        self._log.info("已卸载键盘钩子")

    # ---------------- 补发 Enter ----------------

    def send_enter(self) -> None:
        """补发一次 Enter，并让钩子忽略这一下。"""
        self._injected = True
        try:
            self.listener.send("enter")
        finally:
            self._injected = False

    # ---------------- 钩子回调 ----------------

    def _on_enter(self, event: Any) -> bool:
        """返回 ``False`` 表示吞掉这次按键，``True`` 表示放行。"""
        if getattr(event, "event_type", "down") != "down":
            return True
        if self._injected:
            return True
        if not self._gate():
            return True
        if not self._busy.acquire(blocking=False):
            self._log.debug("上一次还没处理完，忽略这次 Enter")
            return False

        try:
            worker = self._thread_factory(target=self._run_handler, daemon=True, name="meow-enter")
            worker.start()
        except Exception:
            self._busy.release()
            self._log.exception("启动处理线程失败")
            return True
        return False

    def _run_handler(self) -> None:
        try:
            outcome = self._handler(self.send_enter)
            if outcome in (None, EnterOutcome.PASSTHROUGH):
                # 业务层没有处理（读不到内容等），原样放行一次干净的 Enter
                self.send_enter()
        except Exception:
            self._log.exception("处理 Enter 时发生异常，原样放行")
            try:
                self.send_enter()
            except Exception:
                self._log.exception("补发 Enter 也失败了")
        finally:
            self._busy.release()
