"""UIAutomation 后端：直接读/写控件内容，最干净、不碰剪贴板。

注意：UIAutomation 是 COM 组件，**在子线程里用必须先初始化 COM**，
否则会看到 ``尚未调用 CoInitialize`` / ``Can not load UIAutomationCore.dll``。
所以调用方要配合 :meth:`UiaBackend.session` 一起用。
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

LOGGER = logging.getLogger(__name__)

SEARCH_TIMEOUT_SECONDS = 0.5


class UiaBackend:
    """通过 UIAutomation 读写焦点控件。

    ``read()`` 会把拿到的控件句柄缓存下来供 ``write()`` 使用 ——
    因为读和写之间用户没有再切窗口，这个缓存是安全的。
    """

    name = "UIAutomation"

    def __init__(self, automation: Any | None = None) -> None:
        self._automation = automation
        self._control: Any | None = None

    # ---------------- 惰性加载 ----------------

    @property
    def automation(self) -> Any:
        if self._automation is None:
            import uiautomation  # 导入慢，延迟到真正需要时

            uiautomation.SetGlobalSearchTimeout(SEARCH_TIMEOUT_SECONDS)
            self._automation = uiautomation
        return self._automation

    @classmethod
    def is_available(cls) -> bool:
        try:
            import uiautomation  # noqa: F401
        except Exception as exc:  # pragma: no cover - 取决于运行环境
            LOGGER.warning("UIAutomation 不可用，将只使用剪贴板方式：%s", exc)
            return False
        return True

    # ---------------- COM 会话 ----------------

    @contextmanager
    def session(self, debug: bool = False) -> Iterator["UiaBackend"]:
        """在子线程里包一层 COM 初始化。"""
        try:
            initializer = self.automation.UIAutomationInitializerInThread(debug=debug)
        except Exception as exc:
            LOGGER.debug("UIAutomation 初始化失败，降级到剪贴板：%s", exc)
            yield self
            return
        with initializer:
            yield self

    # ---------------- 读写 ----------------

    def focused_control(self) -> Any | None:
        try:
            return self.automation.GetFocusedControl()
        except Exception as exc:
            LOGGER.debug("获取焦点控件失败：%s", exc)
            return None

    def read(self) -> str | None:
        self._control = None
        control = self.focused_control()
        if control is None:
            return None

        text = self._read_value_pattern(control)
        if text is None:
            text = self._read_text_pattern(control)
        if text is None:
            return None

        self._control = control
        return text

    def write(self, text: str) -> bool:
        control = self._control
        if control is None:
            return False
        try:
            if control.IsValuePatternAvailable():
                pattern = control.GetValuePattern()
                if not pattern.IsReadOnly:
                    pattern.SetValue(text)
                    return True
        except Exception as exc:
            LOGGER.debug("UIAutomation 写回失败：%s", exc)
        return False

    # ---------------- 内部 ----------------

    @staticmethod
    def _read_value_pattern(control: Any) -> str | None:
        try:
            if control.IsValuePatternAvailable():
                return control.GetValuePattern().Value
        except Exception as exc:
            LOGGER.debug("ValuePattern 读取失败：%s", exc)
        return None

    @staticmethod
    def _read_text_pattern(control: Any) -> str | None:
        try:
            if control.IsTextPatternAvailable():
                return control.GetTextPattern().DocumentRange.GetText(-1)
        except Exception as exc:
            LOGGER.debug("TextPattern 读取失败：%s", exc)
        return None
