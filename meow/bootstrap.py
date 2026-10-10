"""组装依赖：整个程序只有这里知道「有哪些实现」。

好处是核心逻辑（engine / service）不用 import 任何 Windows 相关模块，
测试里替换实现也只需要绕过这个文件。
"""

from __future__ import annotations

import logging
import queue
from dataclasses import dataclass
from typing import Any

from .config import AppSettings, ConfigStore
from .engine import CatifyEngine
from .events import TOPIC_SETTINGS, TOPIC_STATE, TOPIC_STATS, EventBus
from .hooks import EnterHook
from .input import TextGateway, default_gateway
from .logging_setup import setup_logging
from .paths import AppPaths
from .service import MeowService

LOGGER = logging.getLogger(__name__)

# UI 事件队列的元素类型：("log" | "state" | "settings" | "stats" | ..., payload)
UIEvent = tuple[str, Any]


@dataclass
class Runtime:
    """一整套装配好的运行时对象。"""

    paths: AppPaths
    settings: AppSettings
    store: ConfigStore
    bus: EventBus
    engine: CatifyEngine
    gateway: TextGateway
    service: MeowService
    hook: EnterHook
    logger: logging.Logger
    ui_queue: "queue.Queue[UIEvent]"
    use_ui_queue: bool

    def shutdown(self) -> None:
        """卸载钩子并落盘配置。"""
        try:
            self.hook.stop()
        except Exception:
            self.logger.exception("卸载钩子失败")
        try:
            self.store.save(self.service.settings)
        except Exception:
            self.logger.exception("保存配置失败")


def build_runtime(
    *,
    data_dir: str | None = None,
    log_level: int = logging.INFO,
    console: bool = True,
    with_ui: bool = True,
    install_hook: bool = True,
    gateway: TextGateway | None = None,
) -> Runtime:
    """创建运行时。

    ``with_ui=True`` 时日志会额外推送一份到队列，供界面显示。
    """
    paths = AppPaths.resolve(data_dir).ensure()
    ui_queue: "queue.Queue[UIEvent]" = queue.Queue()

    logger = setup_logging(
        level=log_level,
        log_file=paths.log_file,
        console=console,
        ui_sink=(lambda record: ui_queue.put(("log", record))) if with_ui else None,
    )

    store = ConfigStore(paths.config_file)
    settings = store.load()
    logger.info("数据目录：%s", paths.data_dir)

    bus = EventBus()
    engine = CatifyEngine()
    gateway = gateway or default_gateway()
    service = MeowService(settings, engine, gateway, bus=bus, store=store, logger=logger)

    def on_hotkey() -> None:
        service.toggle()

    hook = EnterHook(
        service.handle_enter,
        gate=lambda: service.enabled,
        logger=logger,
    )

    if with_ui:
        bus.subscribe(TOPIC_STATE, lambda value: ui_queue.put(("state", value)))
        bus.subscribe(TOPIC_SETTINGS, lambda value: ui_queue.put(("settings", value)))
        bus.subscribe(TOPIC_STATS, lambda value: ui_queue.put(("stats", value)))

    if install_hook:
        hook.start(hotkey=settings.hotkey, on_hotkey=on_hotkey)

    return Runtime(
        paths=paths,
        settings=settings,
        store=store,
        bus=bus,
        engine=engine,
        gateway=gateway,
        service=service,
        hook=hook,
        logger=logger,
        ui_queue=ui_queue,
        use_ui_queue=with_ui,
    )
