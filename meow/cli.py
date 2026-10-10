"""命令行入口：图形界面、无界面模式、自检。"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from pathlib import Path

from . import __version__
from .engine import CatifyEngine, CatifyParams, preload
from .paths import ENV_DATA_DIR

PROG = "meow"

LEVEL_CHOICES = ("DEBUG", "INFO", "WARNING", "ERROR")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="按回车自动把输入框内容猫娘化的小工具（Windows）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python main.py                    启动图形界面（关闭窗口会收进托盘）\n"
            "  python main.py --no-tray          不启用托盘图标\n"
            "  python main.py --headless         无界面模式，只在控制台输出日志\n"
            "  python main.py --self-test        检查运行环境\n"
            f"  set {ENV_DATA_DIR}=D:\\meow-data   用环境变量指定数据目录\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"{PROG} {__version__}")
    parser.add_argument("--headless", action="store_true", help="不启动界面，只在控制台运行")
    parser.add_argument("--no-tray", action="store_true", help="不创建托盘图标")
    parser.add_argument("--data-dir", metavar="DIR", default=None,
                        help="配置/日志/图标存放目录（默认 ./data）")
    parser.add_argument("--log-level", choices=LEVEL_CHOICES, default="INFO", help="日志级别")
    parser.add_argument("--self-test", action="store_true", help="检查环境后退出")
    parser.add_argument("--preload", action="store_true", default=True,
                        help="后台预加载分词词典（默认开启）")
    return parser


def _resolve_level(name: str) -> int:
    return getattr(logging, name.upper(), logging.INFO)


# ==================== 图形界面 ====================


def run_gui(args: argparse.Namespace) -> int:
    from .bootstrap import build_runtime
    from .ui import MeowWindow, enable_dpi_awareness

    enable_dpi_awareness()  # 必须在创建 Tk 之前

    runtime = build_runtime(
        data_dir=args.data_dir,
        log_level=_resolve_level(args.log_level),
        console=False,          # 有界面时不再往控制台刷日志
        with_ui=True,
        install_hook=True,
    )

    if args.preload:
        threading.Thread(target=preload, name="meow-preload", daemon=True).start()

    window = MeowWindow(
        runtime.service,
        runtime.paths,
        runtime.ui_queue,
        enable_tray=not args.no_tray,
        logger=runtime.logger,
    )

    def _on_close() -> None:
        runtime.shutdown()

    try:
        window.run()
    except KeyboardInterrupt:
        runtime.logger.info("收到 Ctrl+C，退出")
    finally:
        _on_close()
    return 0


# ==================== 无界面模式 ====================


def run_headless(args: argparse.Namespace) -> int:
    from .bootstrap import build_runtime
    from .events import TOPIC_STATE

    runtime = build_runtime(
        data_dir=args.data_dir,
        log_level=_resolve_level(args.log_level),
        console=True,
        with_ui=False,
        install_hook=True,
    )
    logger = runtime.logger

    if args.preload:
        threading.Thread(target=preload, name="meow-preload", daemon=True).start()

    runtime.bus.subscribe(
        TOPIC_STATE, lambda value: logger.info("开关 -> %s", "开 ✅" if value else "关 ❌")
    )

    logger.info("=" * 58)
    logger.info("%s 无界面模式", PROG)
    logger.info("按 %s 切换开关；开启后按回车会自动猫化并发送", runtime.settings.hotkey)
    logger.info("按 Ctrl+C 退出")
    logger.info("=" * 58)

    try:
        while True:
            time.sleep(0.4)
    except KeyboardInterrupt:
        logger.info("退出中……")
    finally:
        runtime.shutdown()
    return 0


# ==================== 自检 ====================


def run_self_test(args: argparse.Namespace) -> int:
    """检查运行环境并把结论打出来，方便用户自查。"""
    from .paths import AppPaths
    from .tray import ICON_VERSION, build_ico, ensure_icons, TrayIcon

    problems: list[str] = []

    def line(status: str, text: str) -> None:
        print(f"  [{status}] {text}")

    print(f"{PROG} {__version__} 环境自检")
    print("-" * 58)

    # Python
    version = sys.version_info
    if version >= (3, 9):
        line("OK", f"Python {version.major}.{version.minor}.{version.micro}")
    else:
        line("!!", f"Python {version.major}.{version.minor} 过低，建议 3.9+")
        problems.append("Python 版本过低")

    # 第三方依赖
    for module, purpose, required in (
        ("jieba", "中文分词（补主语/换人称）", True),
        ("uiautomation", "直接读写输入框（首选方式）", False),
        ("keyboard", "全局键盘钩子", True),
        ("pyperclip", "剪贴板兜底", False),
    ):
        try:
            __import__(module)
            line("OK", f"{module} 可用 —— {purpose}")
        except Exception as exc:
            level = "!!" if required else "~~"
            line(level, f"{module} 不可用（{exc}）—— {purpose}")
            if required:
                problems.append(f"缺少依赖 {module}")

    # Tkinter
    try:
        import tkinter  # noqa: F401

        line("OK", "tkinter 可用 —— 图形界面")
    except Exception as exc:
        line("!!", f"tkinter 不可用（{exc}）—— 图形界面将无法启动")
        problems.append("缺少 tkinter")

    # 引擎
    try:
        engine = CatifyEngine()
        sample = engine.rewrite("你在做什么？", CatifyParams(strength=2, seed=1))
        line("OK", f"改写引擎正常，示例：{sample}")
    except Exception as exc:
        line("!!", f"改写引擎异常：{exc}")
        problems.append("改写引擎异常")

    # 配置读写
    try:
        paths = AppPaths.resolve(args.data_dir).ensure()
        from .config import ConfigStore

        store = ConfigStore(paths.config_file)
        before = store.load()
        store.save(before)
        line("OK", f"配置可读写：{paths.config_file}")
    except Exception as exc:
        line("!!", f"配置读写失败：{exc}")
        problems.append("配置目录不可写")

    # 图标
    try:
        data = build_ico(True)
        icons = ensure_icons(paths.icon_dir)
        line("OK", f"图标生成正常（ICON_VERSION={ICON_VERSION}，{len(data)} 字节）")
    except Exception as exc:
        line("!!", f"图标生成失败：{exc}")
        problems.append("图标生成失败")

    # 托盘
    tray = TrayIcon(icons["on"], tooltip="meow 自检")
    if tray.start():
        tray.stop()
        line("OK", "托盘图标可用")
    else:
        line("~~", f"托盘图标不可用：{tray.failure_reason}")
        print("       常见原因：进程完整性级别过低（沙箱/受限环境），")
        print("       或者资源管理器未运行。普通双击运行通常没有这个问题。")

    # 管理员权限
    try:
        import ctypes

        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        is_admin = False
    if is_admin:
        line("OK", "当前以管理员权限运行（兼容性最好）")
    else:
        line("~~", "当前不是管理员：对以管理员身份运行的窗口无效，建议右键以管理员身份运行")

    print("-" * 58)
    if problems:
        print("发现问题：" + "；".join(problems))
        return 1
    print("未发现阻塞性问题。")
    return 0


# ==================== 入口 ====================


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test(args)
    if args.headless:
        return run_headless(args)
    return run_gui(args)


__all__ = [
    "build_parser",
    "main",
    "run_gui",
    "run_headless",
    "run_self_test",
]
