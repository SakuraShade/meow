"""运行时目录解析。

所有会落盘的东西（配置、日志、图标缓存）都放在同一个「数据目录」下，
默认是项目根目录的 ``data/``，可以通过 ``--data-dir`` 或环境变量
``MEOW_DATA_DIR`` 覆盖。

之所以不用 ``%APPDATA%``：这个工具通常是「下载下来直接跑」的，
把数据放在项目目录里更符合直觉，也方便整个文件夹拷走。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent

ENV_DATA_DIR = "MEOW_DATA_DIR"
DEFAULT_DIR_NAME = "data"

CONFIG_FILE_NAME = "settings.json"
LOG_FILE_NAME = "meow.log"
ICON_DIR_NAME = "icons"


def default_data_dir() -> Path:
    """默认数据目录：项目根目录下的 ``data/``。"""
    return PROJECT_ROOT / DEFAULT_DIR_NAME


def resolve_data_dir(explicit: str | os.PathLike[str] | None = None) -> Path:
    """按 ``显式参数 → 环境变量 → 默认值`` 的顺序确定数据目录。"""
    if explicit:
        return Path(explicit).expanduser().resolve()
    from_env = os.environ.get(ENV_DATA_DIR)
    if from_env:
        return Path(from_env).expanduser().resolve()
    return default_data_dir()


@dataclass(frozen=True)
class AppPaths:
    """数据目录里各个文件的位置。"""

    data_dir: Path

    # ---- 派生路径 ----------------------------------------------------
    @property
    def config_file(self) -> Path:
        return self.data_dir / CONFIG_FILE_NAME

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def log_file(self) -> Path:
        return self.log_dir / LOG_FILE_NAME

    @property
    def icon_dir(self) -> Path:
        return self.data_dir / ICON_DIR_NAME

    # ---- 构造 / 准备 -------------------------------------------------
    @classmethod
    def resolve(cls, explicit: str | os.PathLike[str] | None = None) -> "AppPaths":
        return cls(data_dir=resolve_data_dir(explicit))

    def ensure(self) -> "AppPaths":
        """创建所有需要的目录（幂等）。"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.icon_dir.mkdir(parents=True, exist_ok=True)
        return self

    def icon(self, name: str) -> Path:
        return self.icon_dir / name
