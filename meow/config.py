"""应用配置模型与 JSON 持久化。

配置分两层：

* :class:`~meow.engine.params.CatifyParams` —— 纯引擎参数（怎么改写文本）
* :class:`AppSettings` —— 应用级设置（开关、快捷键、托盘行为）+ 引擎参数
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .engine.params import CatifyParams, clamp_bool

LOGGER = logging.getLogger(__name__)

DEFAULT_HOTKEY = "alt+b"
CONFIG_VERSION = 2


@dataclass
class AppSettings:
    """整个应用的可持久化状态。"""

    enabled: bool = False
    hotkey: str = DEFAULT_HOTKEY
    auto_send: bool = True
    minimize_to_tray_on_close: bool = True
    show_tray_notifications: bool = True
    catify: CatifyParams = field(default_factory=CatifyParams)

    # ---------------- 序列化 ----------------

    @classmethod
    def from_dict(cls, data: Any) -> "AppSettings":
        if not isinstance(data, dict):
            LOGGER.warning("配置内容不是对象，使用默认配置")
            return cls()
        defaults = cls()
        hotkey = data.get("hotkey")
        if not isinstance(hotkey, str) or not hotkey.strip():
            hotkey = defaults.hotkey
        return cls(
            enabled=clamp_bool(data.get("enabled"), defaults.enabled),
            hotkey=hotkey.strip().lower(),
            auto_send=clamp_bool(data.get("auto_send"), defaults.auto_send),
            minimize_to_tray_on_close=clamp_bool(
                data.get("minimize_to_tray_on_close"), defaults.minimize_to_tray_on_close
            ),
            show_tray_notifications=clamp_bool(
                data.get("show_tray_notifications"), defaults.show_tray_notifications
            ),
            catify=CatifyParams.from_dict(data.get("catify")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": CONFIG_VERSION,
            "enabled": self.enabled,
            "hotkey": self.hotkey,
            "auto_send": self.auto_send,
            "minimize_to_tray_on_close": self.minimize_to_tray_on_close,
            "show_tray_notifications": self.show_tray_notifications,
            "catify": self.catify.to_dict(),
        }

    def clamp(self) -> "AppSettings":
        self.catify = self.catify.clamp()
        return self


class ConfigStore:
    """把 :class:`AppSettings` 读写到 JSON 文件。

    读取永远不抛异常：配置损坏时回退默认值并记日志（用户不该因为
    手改坏了一个 JSON 就打不开程序）。写入用「临时文件 + 替换」避免写一半崩掉。
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> AppSettings:
        if not self.path.exists():
            LOGGER.info("未找到配置文件，使用默认配置：%s", self.path)
            return AppSettings()
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, ValueError) as exc:
            LOGGER.error("读取配置失败（%s），回退默认配置：%s", self.path, exc)
            return AppSettings()
        settings = AppSettings.from_dict(data)
        LOGGER.debug("已加载配置：%s", self.path)
        return settings

    def save(self, settings: AppSettings) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(settings.to_dict(), ensure_ascii=False, indent=2)
            temporary = self.path.with_name(self.path.name + ".tmp")
            temporary.write_text(payload + "\n", encoding="utf-8")
            os.replace(temporary, self.path)
            LOGGER.debug("配置已保存：%s", self.path)
            return True
        except OSError as exc:
            LOGGER.error("保存配置失败（%s）：%s", self.path, exc)
            return False
