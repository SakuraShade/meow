"""剪贴板兜底后端：靠 ``Ctrl+A / Ctrl+C / Ctrl+V`` 操作自绘控件。

微信 4.x、部分 Electron 应用对 UIAutomation 暴露不了输入框内容，
这时候只能走剪贴板。代价是会短暂借用用户的剪贴板（读完/写完都会还原）。

**相比旧实现的一个修正**：旧代码把剪贴板清空后再 ``Ctrl+C``，却只用
``text is None`` 判断失败，于是「应用不支持复制」这种情况会被误判成
「读到空字符串」，接着就会把输入框清空并回车发出去。现在把
「复制后依然是空」也当作读取失败，直接放行原始回车，不做破坏性操作。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClipboardTiming:
    """各步骤之间的等待时间（秒），不同机器/应用可能需要微调。"""

    after_clear: float = 0.02
    after_select_all: float = 0.03
    after_copy: float = 0.06
    after_paste: float = 0.10


class ClipboardBackend:
    """用剪贴板读写焦点输入框。"""

    name = "剪贴板"

    def __init__(
        self,
        clipboard: Any | None = None,
        keyboard: Any | None = None,
        timing: ClipboardTiming | None = None,
    ) -> None:
        self._clipboard = clipboard
        self._keyboard = keyboard
        self.timing = timing or ClipboardTiming()

    # ---------------- 惰性加载依赖 ----------------

    @property
    def clipboard(self) -> Any:
        if self._clipboard is None:
            import pyperclip

            self._clipboard = pyperclip
        return self._clipboard

    @property
    def keyboard(self) -> Any:
        if self._keyboard is None:
            import keyboard

            self._keyboard = keyboard
        return self._keyboard

    # ---------------- 读写 ----------------

    def read(self) -> str | None:
        """``Ctrl+A`` → ``Ctrl+C`` 读取焦点输入框；读不到返回 ``None``。"""
        backup = self._safe_paste()
        text: str | None = None
        try:
            self.clipboard.copy("")  # 清空，用来区分「复制成功」和「没复制到」
            time.sleep(self.timing.after_clear)
            self.keyboard.send("ctrl+a")
            time.sleep(self.timing.after_select_all)
            self.keyboard.send("ctrl+c")
            time.sleep(self.timing.after_copy)
            copied = self.clipboard.paste()
            text = copied if copied else None
        except Exception as exc:
            LOGGER.warning("剪贴板读取失败：%s", exc)
            text = None
        finally:
            self._safe_copy(backup)
        return text

    def write(self, text: str) -> bool:
        """``Ctrl+A`` → ``Ctrl+V`` 覆写焦点输入框。"""
        backup = self._safe_paste()
        try:
            self.clipboard.copy(text)
            time.sleep(self.timing.after_clear)
            self.keyboard.send("ctrl+a")
            time.sleep(self.timing.after_select_all)
            self.keyboard.send("ctrl+v")
            time.sleep(self.timing.after_paste)  # 等应用真正拿到内容再还原剪贴板
            return True
        except Exception as exc:
            LOGGER.warning("剪贴板写入失败：%s", exc)
            return False
        finally:
            self._safe_copy(backup)

    # ---------------- 内部 ----------------

    def _safe_paste(self) -> str:
        try:
            return self.clipboard.paste() or ""
        except Exception:
            return ""

    def _safe_copy(self, text: str) -> None:
        try:
            self.clipboard.copy(text)
        except Exception:
            pass
