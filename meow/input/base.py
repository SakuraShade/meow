"""输入框读写的抽象层。

约定：一个后端要么能读到文本，要么返回 ``None``（并且不产生副作用）。
写回失败返回 ``False``，由 :class:`~meow.input.gateway.TextGateway` 决定降级。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class InputBackend(Protocol):
    """能读出/写回「当前焦点输入框」文本的后端。"""

    name: str

    def read(self) -> str | None:
        """读取焦点输入框内容；读不到返回 ``None``。"""

    def write(self, text: str) -> bool:
        """把文本写回焦点输入框；成功返回 ``True``。"""


@dataclass(frozen=True)
class Field:
    """一次成功读取的结果：内容 + 是哪个后端读到的。"""

    text: str
    backend: InputBackend

    @property
    def backend_name(self) -> str:
        return self.backend.name


class NullBackend:
    """占位后端：永远读不到、也写不进去。用于测试和降级。"""

    name = "无"

    def read(self) -> str | None:
        return None

    def write(self, text: str) -> bool:
        return False
