#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""meow 启动入口。

    python main.py                启动图形界面
    python main.py --headless     无界面模式
    python main.py --self-test    环境自检

想运行时不带黑色控制台窗口，用 ``pythonw main.py`` 或者在文件管理器里
双击 ``start_meow.vbs``。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许从任意工作目录启动
sys.path.insert(0, str(Path(__file__).resolve().parent))

from meow.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
