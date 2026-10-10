#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""兼容入口（v1 的 demo.py 就住在这里）。

v2 起，所有启动逻辑都收进了 :mod:`meow.cli`，本文件只是转发一下，
让还记得 ``python demo.py`` 的人不至于撞墙。

    python demo.py              等价于 python main.py
    python demo.py --headless   等价于 python main.py --headless

推荐直接使用 ``main.py``。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from meow.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
