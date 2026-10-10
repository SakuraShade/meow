"""读写网关：按顺序尝试多个后端，读和写各有一条独立的降级链。

读：第一个读成功的后端胜出，并记住它；
写：优先用读成功的那个后端写，失败则依次尝试其它后端。
这样「UIAutomation 能读不能写」的应用也能正常工作。
"""

from __future__ import annotations

import logging
from contextlib import ExitStack, contextmanager
from typing import Iterator, Sequence

from .base import Field, InputBackend

LOGGER = logging.getLogger(__name__)


class TextGateway:
    """把多个 :class:`InputBackend` 组装成一次「读—改—写」的会话。"""

    def __init__(self, backends: Sequence[InputBackend]) -> None:
        if not backends:
            raise ValueError("至少需要一个输入后端")
        self._backends: list[InputBackend] = list(backends)

    @property
    def backends(self) -> list[InputBackend]:
        return list(self._backends)

    @contextmanager
    def session(self) -> Iterator["TextGateway"]:
        """进入一次读写会话。

        后端如果提供 ``session()``（例如 UIAutomation 需要初始化 COM），
        会被自动嵌套进入。业务层因此不必知道任何后端细节。
        """
        with ExitStack() as stack:
            for backend in self._backends:
                factory = getattr(backend, "session", None)
                if callable(factory):
                    try:
                        stack.enter_context(factory())
                    except Exception as exc:
                        LOGGER.debug("[%s] 会话初始化失败：%s", backend.name, exc)
            yield self

    def read(self) -> Field | None:
        """依次尝试各后端，返回第一个成功的结果。"""
        for backend in self._backends:
            try:
                text = backend.read()
            except Exception as exc:
                LOGGER.warning("[%s] 读取异常：%s", backend.name, exc)
                continue
            if text is None:
                LOGGER.debug("[%s] 未读到内容，尝试下一个后端", backend.name)
                continue
            if not text.strip():
                # 空输入框不需要改写，也没必要继续试其它后端
                LOGGER.debug("[%s] 读到空白内容，跳过", backend.name)
                return Field(text=text, backend=backend)
            return Field(text=text, backend=backend)
        return None

    def write(self, field: Field, text: str) -> tuple[bool, str]:
        """优先用读到的后端写回；失败则按顺序换其它后端。

        返回 ``(是否成功, 实际使用的后端名)``。
        """
        ordered = [field.backend] + [b for b in self._backends if b is not field.backend]
        for backend in ordered:
            try:
                if backend.write(text):
                    if backend is not field.backend:
                        LOGGER.info("改用 [%s] 写回", backend.name)
                    return True, backend.name
            except Exception as exc:
                LOGGER.warning("[%s] 写入异常：%s", backend.name, exc)
        return False, field.backend_name
