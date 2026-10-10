"""日志配置：控制台 + 滚动文件 + UI 回调，三路输出。

UI 通过 :class:`CallbackHandler` 订阅日志，而不是去读 stdout，
所以「窗口里的日志」和「日志文件」内容完全一致。
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Callable

ROOT_LOGGER = "meow"

LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
DATE_FORMAT = "%H:%M:%S"
FILE_LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s (%(threadName)s): %(message)s"

MAX_BYTES = 512 * 1024
BACKUP_COUNT = 3

RecordSink = Callable[[logging.LogRecord], None]

# 这些第三方库话太多，或者会在正常运行时刷警告
NOISY_LOGGERS = ("jieba", "keyboard", "uiautomation", "comtypes", "PIL")


class CallbackHandler(logging.Handler):
    """把日志记录转交给一个回调（UI 侧通常是 ``queue.Queue.put``）。"""

    def __init__(self, sink: RecordSink, level: int = logging.NOTSET) -> None:
        super().__init__(level)
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._sink(record)
        except Exception:  # 见 logging 文档：handler 内部异常必须自己吞掉
            self.handleError(record)


def format_record(record: logging.LogRecord) -> str:
    """给 UI 用的单行格式化（带异常信息）。"""
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    text = formatter.format(record)
    if record.exc_info:
        text += "\n" + logging.Formatter().formatException(record.exc_info)
    return text


def _make_console_safe() -> None:
    """Windows 控制台默认是 GBK，日志里的颜文字会炸；让编码错误降级为替换。"""
    stream = sys.stderr
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):
            pass


def setup_logging(
    *,
    level: int = logging.INFO,
    log_file: Path | None = None,
    console: bool = True,
    ui_sink: RecordSink | None = None,
    logger_name: str = ROOT_LOGGER,
) -> logging.Logger:
    """配置并返回应用 logger。

    重复调用是安全的：会先清掉本模块之前加过的 handler。
    """
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    if console:
        _make_console_safe()
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        logger.addHandler(console_handler)

    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=MAX_BYTES,
                backupCount=BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setFormatter(logging.Formatter(FILE_LOG_FORMAT))
            logger.addHandler(file_handler)
        except OSError as exc:  # 磁盘只读之类，退化成无文件日志
            logger.warning("无法写入日志文件 %s：%s", log_file, exc)

    if ui_sink is not None:
        logger.addHandler(CallbackHandler(ui_sink))

    silence_noisy_libraries()
    return logger


def silence_noisy_libraries() -> None:
    """把话多的第三方 logger 压到 WARNING。"""
    for name in NOISY_LOGGERS:
        noisy = logging.getLogger(name)
        noisy.setLevel(logging.WARNING)
        # jieba 会在 DEBUG 级别输出每个词的切分过程
        noisy.propagate = False


def get_logger(name: str | None = None) -> logging.Logger:
    """取 ``meow`` 命名空间下的 logger。"""
    if not name or name == ROOT_LOGGER:
        return logging.getLogger(ROOT_LOGGER)
    return logging.getLogger(f"{ROOT_LOGGER}.{name}")
