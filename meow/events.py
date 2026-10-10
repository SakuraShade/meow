"""极简的线程安全发布/订阅总线。

用途：后台线程（键盘钩子、托盘线程）产生的事件需要交给 Tk 主线程处理，
而 Tk 只能在自己的线程里被操作。这里的约定是：

* 后台线程 ``publish``；
* UI 的订阅者只做一件事 —— 把事件塞进 ``queue.Queue``；
* Tk 用 ``after()`` 轮询队列，再真正更新界面。

这样 UI 代码永远不会被别的线程碰到。
"""

from __future__ import annotations

import logging
from collections import defaultdict
from threading import RLock
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)

# 事件主题
TOPIC_STATE = "state"      # 开关状态变化，payload: bool
TOPIC_STATS = "stats"      # 统计信息变化，payload: dict
TOPIC_SETTINGS = "settings"  # 配置变化，payload: AppSettings

Handler = Callable[[Any], None]
Unsubscriber = Callable[[], None]


class EventBus:
    """同步分发的事件总线；订阅者异常不会影响其它订阅者。"""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._lock = RLock()

    def subscribe(self, topic: str, handler: Handler) -> Unsubscriber:
        with self._lock:
            self._handlers[topic].append(handler)

        def unsubscribe() -> None:
            with self._lock:
                try:
                    self._handlers[topic].remove(handler)
                except ValueError:
                    pass

        return unsubscribe

    def publish(self, topic: str, payload: Any = None) -> None:
        with self._lock:
            handlers = list(self._handlers.get(topic, ()))
        for handler in handlers:
            try:
                handler(payload)
            except Exception:  # 订阅者出问题不能拖垮发布方
                LOGGER.exception("事件订阅者处理 %s 时出错", topic)

    def clear(self) -> None:
        with self._lock:
            self._handlers.clear()
