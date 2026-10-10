"""业务编排层：把「配置 + 引擎 + 输入后端 + 键盘钩子」粘成一个服务。

UI 和 headless 两种入口都只用这一层，因此界面里不会有任何改写逻辑，
命令行模式也不会缺功能。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, replace

from .config import AppSettings, ConfigStore
from .engine import CatifyEngine, CatifyParams
from .events import TOPIC_SETTINGS, TOPIC_STATE, TOPIC_STATS, EventBus
from .hooks import EnterOutcome
from .input import TextGateway

LOGGER = logging.getLogger(__name__)

# 改写后的预览文本在日志/UI 里最多显示多少个字符
PREVIEW_LIMIT = 120


def abbreviate(text: str, limit: int = PREVIEW_LIMIT) -> str:
    flat = text.replace("\n", "⏎")
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1] + "…"


@dataclass
class Stats:
    """运行统计，UI 状态栏用。"""

    rewrites: int = 0
    passthrough: int = 0
    failures: int = 0
    last_original: str = ""
    last_result: str = ""
    last_backend: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "rewrites": self.rewrites,
            "passthrough": self.passthrough,
            "failures": self.failures,
            "last_original": self.last_original,
            "last_result": self.last_result,
            "last_backend": self.last_backend,
        }


class MeowService:
    """应用服务：状态、参数、以及「按一次回车要做什么」。"""

    def __init__(
        self,
        settings: AppSettings,
        engine: CatifyEngine,
        gateway: TextGateway,
        *,
        bus: EventBus | None = None,
        store: ConfigStore | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._settings = settings
        self._engine = engine
        self._gateway = gateway
        self._bus = bus or EventBus()
        self._store = store
        self._log = logger or LOGGER

        self._lock = threading.RLock()
        self.stats = Stats()
        # 「不自动发送」模式下，记住上一次改写的结果，避免二次改写
        self._last_rewrite: str | None = None

    # ---------------- 只读访问 ----------------

    @property
    def bus(self) -> EventBus:
        return self._bus

    @property
    def settings(self) -> AppSettings:
        with self._lock:
            return self._settings

    @property
    def params(self) -> CatifyParams:
        with self._lock:
            return self._settings.catify

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._settings.enabled

    @property
    def auto_send(self) -> bool:
        with self._lock:
            return self._settings.auto_send

    # ---------------- 状态变更 ----------------

    def set_enabled(self, value: bool, *, persist: bool = True) -> bool:
        """打开/关闭猫化。返回是否真的发生了变化。"""
        with self._lock:
            if self._settings.enabled == bool(value):
                return False
            self._settings.enabled = bool(value)
            enabled = self._settings.enabled
            self._last_rewrite = None

        self._log.info("猫化已%s", "开启 ✅" if enabled else "关闭 ❌")
        if persist:
            self._persist()
        self._bus.publish(TOPIC_STATE, enabled)
        return True

    def toggle(self) -> bool:
        """切换开关，返回切换后的状态。"""
        self.set_enabled(not self.enabled)
        return self.enabled

    def update_catify(self, *, persist: bool = True, **changes: object) -> CatifyParams:
        """修改引擎参数（会自动 clamp 到合法范围）。"""
        with self._lock:
            self._settings.catify = replace(self._settings.catify, **changes).clamp()
            params = self._settings.catify
        if persist:
            self._persist()
        self._bus.publish(TOPIC_SETTINGS, self.settings)
        return params

    def update_app(self, *, persist: bool = True, **changes: object) -> AppSettings:
        """修改应用级设置（auto_send / hotkey / 托盘行为……）。"""
        with self._lock:
            settings = replace(self._settings, **changes)
            settings.catify = self._settings.catify
            self._settings = settings
        if persist:
            self._persist()
        self._bus.publish(TOPIC_SETTINGS, self.settings)
        return self.settings

    def reset_catify(self) -> CatifyParams:
        """把引擎参数恢复成默认值。"""
        with self._lock:
            self._settings.catify = CatifyParams()
            params = self._settings.catify
        self._persist()
        self._bus.publish(TOPIC_SETTINGS, self.settings)
        self._log.info("已恢复默认参数")
        return params

    def save(self) -> bool:
        """手动落盘（UI 里点「保存」时用）。"""
        return self._persist()

    def _persist(self) -> bool:
        if self._store is None:
            return False
        return self._store.save(self.settings)

    # ---------------- 核心流程 ----------------

    def preview(self, text: str) -> str:
        """只做改写，不做任何 IO —— 给 UI 的「试一下」输入框用。"""
        return self._engine.catify(text, self.params)

    def handle_enter(self, send_enter) -> EnterOutcome:
        """按了一次回车：读内容 → 改写 → 写回 → （可选）发送。

        ``send_enter`` 由 :class:`~meow.hooks.EnterHook` 注入，用于补发回车。
        """
        if not self.enabled:
            return EnterOutcome.PASSTHROUGH

        with self._gateway.session():
            field = self._gateway.read()

        if field is None:
            self._note_passthrough("两种方式都读不到输入框内容，原样发送")
            return EnterOutcome.PASSTHROUGH

        original = field.text
        if not original.strip():
            self._note_passthrough("输入框是空的，原样发送")
            return EnterOutcome.PASSTHROUGH

        # 「不自动发送」模式：如果内容已经是改写结果，这次回车就是用户确认发送
        if not self.auto_send and original == self._last_rewrite:
            self._last_rewrite = None
            self._log.info("内容已是改写结果，直接发送")
            return EnterOutcome.PASSTHROUGH

        rewritten = self._engine.catify(original, self.params)
        if not rewritten.strip() or rewritten == original:
            self._note_passthrough("改写结果为空或与原文相同，原样发送")
            return EnterOutcome.PASSTHROUGH

        with self._gateway.session():
            ok, backend_name = self._gateway.write(field, rewritten)

        if not ok:
            self.stats.failures += 1
            self._log.error("写回失败（读取方式=%s），原样发送", field.backend_name)
            self._publish_stats()
            return EnterOutcome.PASSTHROUGH

        self._last_rewrite = rewritten
        self.stats.rewrites += 1
        self.stats.last_original = original
        self.stats.last_result = rewritten
        self.stats.last_backend = backend_name
        self._log.info(
            "改写成功 [读=%s 写=%s] %s → %s",
            field.backend_name,
            backend_name,
            abbreviate(original),
            abbreviate(rewritten),
        )
        self._publish_stats()

        if not self.auto_send:
            self._log.info("已改写但未发送（可在界面里关闭「自动发送回车」）")
            return EnterOutcome.SWALLOW

        send_enter()
        return EnterOutcome.SENT

    # ---------------- 内部 ----------------

    def _note_passthrough(self, reason: str) -> None:
        self.stats.passthrough += 1
        self._log.debug("%s", reason)
        self._publish_stats()

    def _publish_stats(self) -> None:
        self._bus.publish(TOPIC_STATS, self.stats.to_dict())
